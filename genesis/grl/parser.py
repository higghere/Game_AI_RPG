"""GENESIS Rule Language (GRL) JSON AST Parser.

Parses and validates declarative JSON AST specifications into typed GRL AST objects.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from genesis.core.arithmetic import FixedPoint
from genesis.core.errors import GRLValidationError
from genesis.grl.ast import (
    AddRelationshipNode,
    AdjustPropertyNode,
    BinaryOpNode,
    ConsumeResourceNode,
    ForEachNode,
    GetPropertyNode,
    GetResourceNode,
    GRLNode,
    HasRelationshipNode,
    IfNode,
    LiteralNode,
    ProduceResourceNode,
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


class GRLParser:
    """Validating JSON AST parser for GRL."""

    def parse_rule(self, data: Dict[str, Any]) -> RuleDefinition:
        """Parse top-level rule JSON into a RuleDefinition AST."""
        if not isinstance(data, dict):
            raise GRLValidationError("Rule definition must be a JSON dictionary")

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
            filter_expr = self.parse_expression(sel_data["filter"]) if "filter" in sel_data else None
            limit = int(sel_data.get("limit", 1000))
            if limit < 1 or limit > 1000:
                raise GRLValidationError("target_selector limit must be between 1 and 1000")
            selector = TargetSelector(
                entity_type=sel_data["entity_type"],
                filter_expr=filter_expr,
                limit=limit,
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
        )

    def parse_expression(self, node: Any) -> GRLNode:
        """Parse an expression AST node."""
        if not isinstance(node, dict):
            raise GRLValidationError(f"Expression node must be dict, got {type(node).__name__}")
        if "op" not in node:
            raise GRLValidationError(f"Expression node missing 'op': {node}")

        op = node["op"]

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

        raise GRLValidationError(f"Unrecognized expression operator: '{op}'")

    def parse_effect(self, node: Any) -> GRLNode:
        """Parse an action/effect AST node."""
        if not isinstance(node, dict):
            raise GRLValidationError(f"Effect node must be dict, got {type(node).__name__}")
        if "op" not in node:
            raise GRLValidationError(f"Effect node missing 'op': {node}")

        op = node["op"]

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
            body = [self.parse_effect(e) for e in node.get("body", [])]
            return ForEachNode(
                iterator_var=node["iterator_var"],
                collection_source=node.get("collection_source", "outgoing_relationships"),
                rel_type=node.get("rel_type"),
                body=body,
            )

        raise GRLValidationError(f"Unrecognized effect operator: '{op}'")
