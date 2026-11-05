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
