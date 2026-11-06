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
    collection_source: str  # e.g. "outgoing_relationships", "incoming_relationships"
    rel_type: Optional[str] = None
    body: List[GRLNode] = field(default_factory=list)


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
    elif isinstance(node, ForEachNode):
        return {
            "op": "FOR_EACH",
            "iterator_var": node.iterator_var,
            "collection_source": node.collection_source,
            "rel_type": node.rel_type,
            "body": [ast_to_canonical_dict(e) for e in node.body],
        }
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
