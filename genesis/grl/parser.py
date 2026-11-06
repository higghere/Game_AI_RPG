"""GENESIS Rule Language (GRL) JSON AST Parser.

Parses and validates declarative JSON AST specifications into typed GRL AST objects
with strict closed-grammar validation and ceiling limits.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from genesis.core.arithmetic import FixedPoint
from genesis.core.errors import GRLValidationError
from genesis.grl.ast import (
    AddRelationshipNode,
    AdjustPropertyNode,
    AggregateNode,
    BinaryOpNode,
    ConsumeResourceNode,
    CreateEntityNode,
    DestroyEntityNode,
    FindEntityNode,
    ForEachNode,
    GetPropertyNode,
    GetResourceNode,
    GRLNode,
    HasRelationshipNode,
    IfNode,
    LiteralNode,
    ProduceResourceNode,
    RandomFixedNode,
    RandomIntNode,
    RemoveRelationshipNode,
    RuleDefinition,
    ScheduleEventNode,
    SetPropertyNode,
    TargetSelector,
    TransferResourceNode,
    UnaryOpNode,
)

BINARY_OPS = {
    "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "MODULO",
    "EQUALS", "NOT_EQUALS", "LESS_THAN", "LESS_THAN_OR_EQUAL",
    "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "AND", "OR"
}
UNARY_OPS = {"NOT", "NEG"}

RULE_ALLOWED_KEYS = {
    "rule_id", "name", "version", "priority", "target_selector",
    "preconditions", "effects", "active_from_tick", "spatial_partitioned",
    "author", "rule_hash",
}

TARGET_SELECTOR_ALLOWED_KEYS = {
    "entity_type", "filter", "limit", "spatial_cell",
}

EXPRESSION_ALLOWED_KEYS: Dict[str, set] = {
    "LITERAL": {"op", "type", "value"},
    "GET_PROPERTY": {"op", "entity", "property"},
    "GET_RESOURCE": {"op", "pool"},
    "HAS_RELATIONSHIP": {"op", "source", "target", "rel_type"},
    "RANDOM_INT": {"op", "min", "max"},
    "RANDOM_FIXED": {"op", "min", "max"},
    "AGGREGATE": {
        "op", "aggregate_func", "collection_source", "element_var", "expr",
        "max_elements", "entity_type", "rel_type", "filter", "result_var",
    },
}
for bop in BINARY_OPS:
    EXPRESSION_ALLOWED_KEYS[bop] = {"op", "left", "right"}
for uop in UNARY_OPS:
    EXPRESSION_ALLOWED_KEYS[uop] = {"op", "operand"}

EFFECT_ALLOWED_KEYS: Dict[str, set] = {
    "SET_PROPERTY": {"op", "entity", "property", "value"},
    "ADJUST_PROPERTY": {"op", "entity", "property", "delta"},
    "CONSUME_RESOURCE": {"op", "pool", "amount"},
    "PRODUCE_RESOURCE": {"op", "pool", "amount"},
    "TRANSFER_RESOURCE": {"op", "from_pool", "to_pool", "amount"},
    "ADD_RELATIONSHIP": {"op", "source", "target", "rel_type", "weight"},
    "REMOVE_RELATIONSHIP": {"op", "source", "target", "rel_type"},
    "SCHEDULE_EVENT": {"op", "event_type", "delay_ticks", "payload"},
    "IF": {"op", "condition", "then", "else"},
    "FOR_EACH": {"op", "iterator_var", "collection_source", "rel_type", "max_iterations", "body"},
    "CREATE_ENTITY": {"op", "entity_type", "result_var", "initial_properties"},
    "DESTROY_ENTITY": {"op", "entity"},
    "FIND_ENTITY": {"op", "result_var", "collection_source", "entity_type", "rel_type", "filter", "order_by", "order_direction", "max_scan", "limit"},
    "AGGREGATE": {"op", "aggregate_func", "collection_source", "element_var", "expr", "max_elements", "entity_type", "rel_type", "filter", "result_var"},
}


class GRLParser:
    """Validating JSON AST parser for GRL with closed grammar enforcement."""

    def parse_rule(self, data: Dict[str, Any]) -> RuleDefinition:
        """Parse top-level rule JSON into a RuleDefinition AST."""
        if not isinstance(data, dict):
            raise GRLValidationError("Rule definition must be a JSON dictionary")

        # Enforce closed grammar on rule definition
        unknown_rule_keys = set(data.keys()) - RULE_ALLOWED_KEYS
        if unknown_rule_keys:
            raise GRLValidationError(f"Unknown fields in rule definition: {sorted(unknown_rule_keys)}")

        for req in ("rule_id", "name", "version"):
            if req not in data or not isinstance(data[req], str):
                raise GRLValidationError(f"Rule missing required string field: '{req}'")

        rule_id = data["rule_id"]
        name = data["name"]
        version = data["version"]
        priority = int(data.get("priority", 0))

        # Target Selector
        selector: Optional[TargetSelector] = None
        if "target_selector" in data:
            sel_data = data["target_selector"]
            if not isinstance(sel_data, dict) or "entity_type" not in sel_data:
                raise GRLValidationError("target_selector must specify 'entity_type'")
            
            unknown_sel_keys = set(sel_data.keys()) - TARGET_SELECTOR_ALLOWED_KEYS
            if unknown_sel_keys:
                raise GRLValidationError(f"Unknown fields in target_selector: {sorted(unknown_sel_keys)}")

            filter_expr = self.parse_expression(sel_data["filter"]) if "filter" in sel_data else None
            limit = int(sel_data.get("limit", 1000))
            if limit < 1 or limit > 1000:
                raise GRLValidationError("target_selector limit must be between 1 and 1000")
            spatial_cell = None
            if "spatial_cell" in sel_data and sel_data["spatial_cell"] is not None:
                sc = sel_data["spatial_cell"]
                if not isinstance(sc, (list, tuple)) or len(sc) != 2:
                    raise GRLValidationError("spatial_cell must be a 2-element array [cx, cy]")
                spatial_cell = (int(sc[0]), int(sc[1]))
            selector = TargetSelector(
                entity_type=sel_data["entity_type"],
                filter_expr=filter_expr,
                limit=limit,
                spatial_cell=spatial_cell,
            )

        # Preconditions
        preconditions: List[GRLNode] = []
        for p in data.get("preconditions", []):
            preconditions.append(self.parse_expression(p))

        # Effects
        effects: List[GRLNode] = []
        for e in data.get("effects", []):
            effects.append(self.parse_effect(e))

        return RuleDefinition(
            rule_id=rule_id,
            name=name,
            version=version,
            priority=priority,
            target_selector=selector,
            preconditions=preconditions,
            effects=effects,
            active_from_tick=int(data.get("active_from_tick", 0)),
            spatial_partitioned=bool(data.get("spatial_partitioned", False)),
            author=str(data.get("author", "")),
        )

    def parse_expression(self, node: Any) -> GRLNode:
        """Parse an expression AST node with strict closed-grammar validation."""
        if not isinstance(node, dict):
            raise GRLValidationError(f"Expression node must be dict, got {type(node).__name__}")
        if "op" not in node:
            raise GRLValidationError(f"Expression node missing 'op': {node}")

        op = node["op"]

        if op not in EXPRESSION_ALLOWED_KEYS:
            raise GRLValidationError(f"Unrecognized expression operator: '{op}'")

        allowed_keys = EXPRESSION_ALLOWED_KEYS[op]
        unknown = set(node.keys()) - allowed_keys
        if unknown:
            raise GRLValidationError(f"Unknown fields in expression '{op}': {sorted(unknown)}")

        if op == "LITERAL":
            val_type = node.get("type")
            raw_val = node.get("value")
            if val_type == "INT64":
                return LiteralNode("INT64", int(raw_val))
            elif val_type == "FIXED_POINT":
                if isinstance(raw_val, str) and "." in raw_val:
                    return LiteralNode("FIXED_POINT", FixedPoint.from_decimal_string(raw_val))
                return LiteralNode("FIXED_POINT", FixedPoint.from_raw(int(raw_val)))
            elif val_type == "BOOLEAN":
                if isinstance(raw_val, bool):
                    return LiteralNode("BOOLEAN", raw_val)
                return LiteralNode("BOOLEAN", str(raw_val).lower() == "true")
            elif val_type == "STRING":
                return LiteralNode("STRING", str(raw_val))
            raise GRLValidationError(f"Unsupported literal type: {val_type}")

        elif op == "GET_PROPERTY":
            return GetPropertyNode(
                entity_var=node.get("entity", "target"),
                property_name=node["property"],
            )

        elif op == "GET_RESOURCE":
            return GetResourceNode(pool_name=node["pool"])

        elif op == "HAS_RELATIONSHIP":
            return HasRelationshipNode(
                source_var=node.get("source", "target"),
                target_var=node["target"],
                rel_type=node["rel_type"],
            )

        elif op in BINARY_OPS:
            if "left" not in node or "right" not in node:
                raise GRLValidationError(f"Binary op '{op}' requires 'left' and 'right'")
            return BinaryOpNode(
                op=op,
                left=self.parse_expression(node["left"]),
                right=self.parse_expression(node["right"]),
            )

        elif op in UNARY_OPS:
            if "operand" not in node:
                raise GRLValidationError(f"Unary op '{op}' requires 'operand'")
            return UnaryOpNode(
                op=op,
                operand=self.parse_expression(node["operand"]),
            )

        elif op == "RANDOM_INT":
            if "min" not in node or "max" not in node:
                raise GRLValidationError("RANDOM_INT requires 'min' and 'max'")
            min_v = int(node["min"]["value"]) if isinstance(node["min"], dict) else int(node["min"])
            max_v = int(node["max"]["value"]) if isinstance(node["max"], dict) else int(node["max"])
            if min_v > max_v:
                raise GRLValidationError(f"RANDOM_INT min ({min_v}) cannot exceed max ({max_v})")
            return RandomIntNode(min_val=min_v, max_val=max_v)

        elif op == "RANDOM_FIXED":
            if "min" not in node or "max" not in node:
                raise GRLValidationError("RANDOM_FIXED requires 'min' and 'max'")
            raw_min = node["min"]["value"] if isinstance(node["min"], dict) else node["min"]
            raw_max = node["max"]["value"] if isinstance(node["max"], dict) else node["max"]
            min_v = FixedPoint.from_decimal_string(str(raw_min)) if "." in str(raw_min) else FixedPoint.from_int(int(raw_min))
            max_v = FixedPoint.from_decimal_string(str(raw_max)) if "." in str(raw_max) else FixedPoint.from_int(int(raw_max))
            if min_v > max_v:
                raise GRLValidationError(f"RANDOM_FIXED min ({min_v}) cannot exceed max ({max_v})")
            return RandomFixedNode(min_val=min_v, max_val=max_v)

        elif op == "AGGREGATE":
            return self._parse_aggregate_node(node)

        raise GRLValidationError(f"Unrecognized expression operator: '{op}'")

    def parse_effect(self, node: Any) -> GRLNode:
        """Parse an action/effect AST node with strict closed-grammar validation."""
        if not isinstance(node, dict):
            raise GRLValidationError(f"Effect node must be dict, got {type(node).__name__}")
        if "op" not in node:
            raise GRLValidationError(f"Effect node missing 'op': {node}")

        op = node["op"]

        if op not in EFFECT_ALLOWED_KEYS:
            raise GRLValidationError(f"Unrecognized effect operator: '{op}'")

        allowed_keys = EFFECT_ALLOWED_KEYS[op]
        unknown = set(node.keys()) - allowed_keys
        if unknown:
            raise GRLValidationError(f"Unknown fields in effect '{op}': {sorted(unknown)}")

        if op == "SET_PROPERTY":
            return SetPropertyNode(
                entity_var=node.get("entity", "target"),
                property_name=node["property"],
                value_expr=self.parse_expression(node["value"]),
            )

        elif op == "ADJUST_PROPERTY":
            return AdjustPropertyNode(
                entity_var=node.get("entity", "target"),
                property_name=node["property"],
                delta_expr=self.parse_expression(node["delta"]),
            )

        elif op == "CONSUME_RESOURCE":
            return ConsumeResourceNode(
                pool_name=node["pool"],
                amount_expr=self.parse_expression(node["amount"]),
            )

        elif op == "PRODUCE_RESOURCE":
            return ProduceResourceNode(
                pool_name=node["pool"],
                amount_expr=self.parse_expression(node["amount"]),
            )

        elif op == "TRANSFER_RESOURCE":
            return TransferResourceNode(
                from_pool=node["from_pool"],
                to_pool=node["to_pool"],
                amount_expr=self.parse_expression(node["amount"]),
            )

        elif op == "ADD_RELATIONSHIP":
            weight_expr = self.parse_expression(node["weight"]) if "weight" in node else None
            return AddRelationshipNode(
                source_var=node.get("source", "target"),
                target_var=node["target"],
                rel_type=node["rel_type"],
                weight_expr=weight_expr,
            )

        elif op == "REMOVE_RELATIONSHIP":
            return RemoveRelationshipNode(
                source_var=node.get("source", "target"),
                target_var=node["target"],
                rel_type=node["rel_type"],
            )

        elif op == "SCHEDULE_EVENT":
            payload_expr = None
            if "payload" in node and isinstance(node["payload"], dict):
                payload_expr = {k: self.parse_expression(v) for k, v in node["payload"].items()}
            return ScheduleEventNode(
                event_type=node["event_type"],
                delay_ticks=int(node.get("delay_ticks", 1)),
                payload_expr=payload_expr,
            )

        elif op == "IF":
            then_eff = [self.parse_effect(e) for e in node.get("then", [])]
            else_eff = [self.parse_effect(e) for e in node.get("else", [])]
            return IfNode(
                condition=self.parse_expression(node["condition"]),
                then_effects=then_eff,
                else_effects=else_eff,
            )

        elif op == "FOR_EACH":
            max_iters = int(node.get("max_iterations", 32))
            if max_iters < 1 or max_iters > 32:
                raise GRLValidationError(f"FOR_EACH max_iterations must be between 1 and 32, got {max_iters}")
            body = [self.parse_effect(e) for e in node.get("body", [])]
            return ForEachNode(
                iterator_var=node["iterator_var"],
                collection_source=node.get("collection_source", "outgoing_relationships"),
                rel_type=node.get("rel_type"),
                max_iterations=max_iters,
                body=body,
            )

        elif op == "CREATE_ENTITY":
            entity_type = node.get("entity_type")
            if not entity_type or not isinstance(entity_type, str):
                raise GRLValidationError("CREATE_ENTITY requires a non-empty string 'entity_type'")
            result_var = node.get("result_var")
            if not result_var or not isinstance(result_var, str):
                raise GRLValidationError("CREATE_ENTITY requires a non-empty string 'result_var'")
            raw_props = node.get("initial_properties", {})
            if not isinstance(raw_props, dict):
                raise GRLValidationError("CREATE_ENTITY initial_properties must be a dict")
            initial_props = {k: self.parse_expression(v) for k, v in raw_props.items()}
            return CreateEntityNode(
                entity_type=entity_type,
                result_var=result_var,
                initial_properties=initial_props,
            )

        elif op == "DESTROY_ENTITY":
            entity_var = node.get("entity")
            if not entity_var or not isinstance(entity_var, str):
                raise GRLValidationError("DESTROY_ENTITY requires a non-empty string 'entity'")
            return DestroyEntityNode(entity_var=entity_var)

        elif op == "FIND_ENTITY":
            result_var = node.get("result_var")
            if not result_var or not isinstance(result_var, str):
                raise GRLValidationError("FIND_ENTITY requires a non-empty string 'result_var'")
            coll_source = node.get("collection_source", "cell_entities")
            if coll_source not in ("cell_entities", "outgoing_relationships", "incoming_relationships"):
                raise GRLValidationError(f"Invalid collection_source for FIND_ENTITY: '{coll_source}'")
            max_scan = int(node.get("max_scan", 16))
            if max_scan < 1 or max_scan > 16:
                raise GRLValidationError(f"FIND_ENTITY max_scan must be between 1 and 16, got {max_scan}")
            limit = int(node.get("limit", 1))
            if limit < 1 or limit > 16:
                raise GRLValidationError(f"FIND_ENTITY limit must be between 1 and 16, got {limit}")
            order_dir = node.get("order_direction", "ASC").upper()
            if order_dir not in ("ASC", "DESC"):
                raise GRLValidationError(f"Invalid order_direction: '{order_dir}'. Must be ASC or DESC")
            filter_expr = self.parse_expression(node["filter"]) if "filter" in node else None
            return FindEntityNode(
                result_var=result_var,
                collection_source=coll_source,
                entity_type=node.get("entity_type"),
                rel_type=node.get("rel_type"),
                filter_expr=filter_expr,
                order_by=node.get("order_by"),
                order_direction=order_dir,
                max_scan=max_scan,
                limit=limit,
            )

        elif op == "AGGREGATE":
            return self._parse_aggregate_node(node)

        raise GRLValidationError(f"Unrecognized effect operator: '{op}'")

    def _parse_aggregate_node(self, node: Dict[str, Any]) -> AggregateNode:
        """Parse AGGREGATE node common to expressions and effects."""
        agg_func = node.get("aggregate_func", "COUNT").upper()
        if agg_func not in ("COUNT", "SUM", "MIN", "MAX"):
            raise GRLValidationError(f"Invalid aggregate_func: '{agg_func}'. Must be one of COUNT, SUM, MIN, MAX")
        coll_source = node.get("collection_source", "cell_entities")
        if coll_source not in ("cell_entities", "outgoing_relationships", "incoming_relationships"):
            raise GRLValidationError(f"Invalid collection_source for AGGREGATE: '{coll_source}'")
        max_elem = int(node.get("max_elements", 32))
        if max_elem < 1 or max_elem > 32:
            raise GRLValidationError(f"AGGREGATE max_elements must be between 1 and 32, got {max_elem}")
        
        expr = self.parse_expression(node["expr"]) if "expr" in node else None
        filter_expr = self.parse_expression(node["filter"]) if "filter" in node else None

        return AggregateNode(
            aggregate_func=agg_func,
            collection_source=coll_source,
            rel_type=node.get("rel_type"),
            entity_type=node.get("entity_type"),
            element_var=node.get("element_var", "item"),
            expr=expr,
            filter_expr=filter_expr,
            max_elements=max_elem,
            result_var=node.get("result_var"),
        )
