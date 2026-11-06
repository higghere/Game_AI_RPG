"""GENESIS Rule Language (GRL) Abstract Syntax Tree (AST).

Pure data representations of GRL expressions, actions, selectors, and rules.
Fully serializable to and from canonical JSON.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from genesis.core.arithmetic import FixedPoint


@dataclass
class GRLNode:
    """Base class for all GRL AST nodes."""
    pass


# Expressions
@dataclass
class LiteralNode(GRLNode):
    val_type: str  # "INT64", "FIXED_POINT", "BOOLEAN", "STRING"
    value: Union[int, FixedPoint, bool, str]


@dataclass
class GetPropertyNode(GRLNode):
    entity_var: str  # e.g. "target", "source"
    property_name: str


@dataclass
class GetResourceNode(GRLNode):
    pool_name: str


@dataclass
class HasRelationshipNode(GRLNode):
    source_var: str
    target_var: str
    rel_type: str


@dataclass
class BinaryOpNode(GRLNode):
    op: str  # ADD, SUBTRACT, MULTIPLY, DIVIDE, MODULO, EQUALS, NOT_EQUALS, LESS_THAN, LESS_THAN_OR_EQUAL, GREATER_THAN, GREATER_THAN_OR_EQUAL, AND, OR
    left: GRLNode
    right: GRLNode


@dataclass
class UnaryOpNode(GRLNode):
    op: str  # NOT, NEG
    operand: GRLNode


@dataclass
class RandomIntNode(GRLNode):
    min_val: int
    max_val: int


@dataclass
class RandomFixedNode(GRLNode):
    min_val: FixedPoint
    max_val: FixedPoint


@dataclass
class AggregateNode(GRLNode):
    aggregate_func: str  # COUNT, SUM, MIN, MAX
    collection_source: str  # cell_entities, outgoing_relationships, incoming_relationships
    rel_type: Optional[str] = None
    entity_type: Optional[str] = None
    element_var: str = "item"
    expr: Optional[GRLNode] = None
    filter_expr: Optional[GRLNode] = None
    max_elements: int = 32
    result_var: Optional[str] = None


# Effects / Statements
@dataclass
class SetPropertyNode(GRLNode):
    entity_var: str
    property_name: str
    value_expr: GRLNode


@dataclass
class AdjustPropertyNode(GRLNode):
    entity_var: str
    property_name: str
    delta_expr: GRLNode


@dataclass
class ConsumeResourceNode(GRLNode):
    pool_name: str
    amount_expr: GRLNode


@dataclass
class ProduceResourceNode(GRLNode):
    pool_name: str
    amount_expr: GRLNode


@dataclass
class TransferResourceNode(GRLNode):
    from_pool: str
    to_pool: str
    amount_expr: GRLNode


@dataclass
class AddRelationshipNode(GRLNode):
    source_var: str
    target_var: str
    rel_type: str
    weight_expr: Optional[GRLNode] = None


@dataclass
class RemoveRelationshipNode(GRLNode):
    source_var: str
    target_var: str
    rel_type: str


@dataclass
class ScheduleEventNode(GRLNode):
    event_type: str
    delay_ticks: int
    payload_expr: Optional[Dict[str, GRLNode]] = None


@dataclass
class IfNode(GRLNode):
    condition: GRLNode
    then_effects: List[GRLNode]
    else_effects: List[GRLNode] = field(default_factory=list)


@dataclass
class ForEachNode(GRLNode):
    iterator_var: str
    collection_source: str  # e.g. "outgoing_relationships", "incoming_relationships", "cell_entities"
    rel_type: Optional[str] = None
    max_iterations: int = 32
    body: List[GRLNode] = field(default_factory=list)


@dataclass
class CreateEntityNode(GRLNode):
    entity_type: str
    result_var: str
    initial_properties: Dict[str, GRLNode] = field(default_factory=dict)


@dataclass
class DestroyEntityNode(GRLNode):
    entity_var: str


@dataclass
class FindEntityNode(GRLNode):
    result_var: str
    collection_source: str  # cell_entities, outgoing_relationships, incoming_relationships
    entity_type: Optional[str] = None
    rel_type: Optional[str] = None
    filter_expr: Optional[GRLNode] = None
    order_by: Optional[str] = None
    order_direction: str = "ASC"  # ASC, DESC
    max_scan: int = 16
    limit: int = 1


# Rule Structure
@dataclass
class TargetSelector:
    entity_type: str
    filter_expr: Optional[GRLNode] = None
    limit: int = 1000
    spatial_cell: Optional[Tuple[int, int]] = None


@dataclass
class RuleDefinition:
    rule_id: str
    name: str
    version: str
    priority: int = 0
    target_selector: Optional[TargetSelector] = None
    preconditions: List[GRLNode] = field(default_factory=list)
    effects: List[GRLNode] = field(default_factory=list)
    active_from_tick: int = 0
    spatial_partitioned: bool = False
    author: str = ""


def ast_to_canonical_dict(node: Any) -> Any:
    """Convert AST node to canonical serializable dictionary."""
    if isinstance(node, LiteralNode):
        val = node.value
        if isinstance(val, FixedPoint):
            val = val.to_raw_string()
        elif isinstance(val, int) and not isinstance(val, bool):
            val = str(val)
        return {"op": "LITERAL", "type": node.val_type, "value": val}
    elif isinstance(node, GetPropertyNode):
        return {"op": "GET_PROPERTY", "entity": node.entity_var, "property": node.property_name}
    elif isinstance(node, GetResourceNode):
        return {"op": "GET_RESOURCE", "pool": node.pool_name}
    elif isinstance(node, HasRelationshipNode):
        return {"op": "HAS_RELATIONSHIP", "source": node.source_var, "target": node.target_var, "rel_type": node.rel_type}
    elif isinstance(node, BinaryOpNode):
        return {"op": node.op, "left": ast_to_canonical_dict(node.left), "right": ast_to_canonical_dict(node.right)}
    elif isinstance(node, UnaryOpNode):
        return {"op": node.op, "operand": ast_to_canonical_dict(node.operand)}
    elif isinstance(node, SetPropertyNode):
        return {"op": "SET_PROPERTY", "entity": node.entity_var, "property": node.property_name, "value": ast_to_canonical_dict(node.value_expr)}
    elif isinstance(node, AdjustPropertyNode):
        return {"op": "ADJUST_PROPERTY", "entity": node.entity_var, "property": node.property_name, "delta": ast_to_canonical_dict(node.delta_expr)}
    elif isinstance(node, ConsumeResourceNode):
        return {"op": "CONSUME_RESOURCE", "pool": node.pool_name, "amount": ast_to_canonical_dict(node.amount_expr)}
    elif isinstance(node, ProduceResourceNode):
        return {"op": "PRODUCE_RESOURCE", "pool": node.pool_name, "amount": ast_to_canonical_dict(node.amount_expr)}
    elif isinstance(node, TransferResourceNode):
        return {"op": "TRANSFER_RESOURCE", "from_pool": node.from_pool, "to_pool": node.to_pool, "amount": ast_to_canonical_dict(node.amount_expr)}
    elif isinstance(node, AddRelationshipNode):
        d = {"op": "ADD_RELATIONSHIP", "source": node.source_var, "target": node.target_var, "rel_type": node.rel_type}
        if node.weight_expr:
            d["weight"] = ast_to_canonical_dict(node.weight_expr)
        return d
    elif isinstance(node, RemoveRelationshipNode):
        return {"op": "REMOVE_RELATIONSHIP", "source": node.source_var, "target": node.target_var, "rel_type": node.rel_type}
    elif isinstance(node, ScheduleEventNode):
        d = {"op": "SCHEDULE_EVENT", "event_type": node.event_type, "delay_ticks": node.delay_ticks}
        if node.payload_expr:
            d["payload"] = {k: ast_to_canonical_dict(v) for k, v in sorted(node.payload_expr.items())}
        return d
    elif isinstance(node, IfNode):
        return {
            "op": "IF",
            "condition": ast_to_canonical_dict(node.condition),
            "then": [ast_to_canonical_dict(e) for e in node.then_effects],
            "else": [ast_to_canonical_dict(e) for e in node.else_effects],
        }
    elif isinstance(node, RandomIntNode):
        return {
            "op": "RANDOM_INT",
            "min": str(node.min_val),
            "max": str(node.max_val),
        }
    elif isinstance(node, RandomFixedNode):
        return {
            "op": "RANDOM_FIXED",
            "min": node.min_val.to_decimal_string(),
            "max": node.max_val.to_decimal_string(),
        }
    elif isinstance(node, AggregateNode):
        d = {
            "op": "AGGREGATE",
            "aggregate_func": node.aggregate_func,
            "collection_source": node.collection_source,
            "element_var": node.element_var,
            "max_elements": node.max_elements,
        }
        if node.rel_type is not None:
            d["rel_type"] = node.rel_type
        if node.entity_type is not None:
            d["entity_type"] = node.entity_type
        if node.result_var is not None:
            d["result_var"] = node.result_var
        if node.expr is not None:
            d["expr"] = ast_to_canonical_dict(node.expr)
        if node.filter_expr is not None:
            d["filter"] = ast_to_canonical_dict(node.filter_expr)
        return d
    elif isinstance(node, CreateEntityNode):
        return {
            "op": "CREATE_ENTITY",
            "entity_type": node.entity_type,
            "result_var": node.result_var,
            "initial_properties": {k: ast_to_canonical_dict(v) for k, v in sorted(node.initial_properties.items())},
        }
    elif isinstance(node, DestroyEntityNode):
        return {
            "op": "DESTROY_ENTITY",
            "entity": node.entity_var,
        }
    elif isinstance(node, FindEntityNode):
        d = {
            "op": "FIND_ENTITY",
            "result_var": node.result_var,
            "collection_source": node.collection_source,
            "order_direction": node.order_direction,
            "max_scan": node.max_scan,
            "limit": node.limit,
        }
        if node.entity_type is not None:
            d["entity_type"] = node.entity_type
        if node.rel_type is not None:
            d["rel_type"] = node.rel_type
        if node.order_by is not None:
            d["order_by"] = node.order_by
        if node.filter_expr is not None:
            d["filter"] = ast_to_canonical_dict(node.filter_expr)
        return d
    elif isinstance(node, ForEachNode):
        d = {
            "op": "FOR_EACH",
            "iterator_var": node.iterator_var,
            "collection_source": node.collection_source,
            "max_iterations": node.max_iterations,
            "body": [ast_to_canonical_dict(e) for e in node.body],
        }
        if node.rel_type is not None:
            d["rel_type"] = node.rel_type
        return d
    return node


def rule_to_canonical_dict(rule: RuleDefinition) -> Dict[str, Any]:
    """Serialize full canonical rule body including all AST nodes and conditions."""
    d: Dict[str, Any] = {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "version": rule.version,
        "priority": rule.priority,
        "active_from_tick": str(rule.active_from_tick),
        "preconditions": [ast_to_canonical_dict(p) for p in rule.preconditions],
        "effects": [ast_to_canonical_dict(e) for e in rule.effects],
    }
    if rule.author:
        d["author"] = rule.author
    if rule.spatial_partitioned:
        d["spatial_partitioned"] = True
    if rule.target_selector:
        sel: Dict[str, Any] = {
            "entity_type": rule.target_selector.entity_type,
            "limit": rule.target_selector.limit,
        }
        if rule.target_selector.spatial_cell is not None:
            sel["spatial_cell"] = [rule.target_selector.spatial_cell[0], rule.target_selector.spatial_cell[1]]
        if rule.target_selector.filter_expr:
            sel["filter"] = ast_to_canonical_dict(rule.target_selector.filter_expr)
        d["target_selector"] = sel
    return d
