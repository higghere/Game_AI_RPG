"""GENESIS Rule Language Read-Only Serializer.

Formats GRL AST definitions into clean, human-readable pseudocode
for inspection, logging, and debugging.
"""

from __future__ import annotations
from typing import List

from genesis.core.arithmetic import FixedPoint
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
    TransferResourceNode,
    UnaryOpNode,
)


class GRLSerializer:
    """Read-only serializer converting GRL AST into human-readable text."""

    def format_rule(self, rule: RuleDefinition) -> str:
        lines: List[str] = []
        lines.append(f"RULE {rule.rule_id} [v{rule.version}, Priority: {rule.priority}]")
        lines.append(f'  NAME: "{rule.name}"')

        if rule.target_selector:
            sel = rule.target_selector
            filt_str = f" WHERE {self.format_expression(sel.filter_expr)}" if sel.filter_expr else ""
            lines.append(f'  TARGET {sel.entity_type} IN world.entities("{sel.entity_type}") LIMIT {sel.limit}{filt_str}')

        if rule.preconditions:
            lines.append("  PRECONDITIONS:")
            for p in rule.preconditions:
                lines.append(f"    - {self.format_expression(p)}")

        if rule.effects:
            lines.append("  EFFECTS:")
            for e in rule.effects:
                lines.append(f"    {self.format_effect(e, indent=2)}")

        return "\n".join(lines)

    def format_expression(self, node: GRLNode) -> str:
        if isinstance(node, LiteralNode):
            if isinstance(node.value, FixedPoint):
                return node.value.to_decimal_string()
            return str(node.value)
        elif isinstance(node, GetPropertyNode):
            return f"{node.entity_var}.{node.property_name}"
        elif isinstance(node, GetResourceNode):
            return f'world.resource("{node.pool_name}")'
        elif isinstance(node, HasRelationshipNode):
            return f'world.has_relationship({node.source_var}, {node.target_var}, "{node.rel_type}")'
        elif isinstance(node, BinaryOpNode):
            left_str = self.format_expression(node.left)
            right_str = self.format_expression(node.right)
            op_sym = {
                "ADD": "+", "SUBTRACT": "-", "MULTIPLY": "*", "DIVIDE": "/", "MODULO": "%",
                "EQUALS": "==", "NOT_EQUALS": "!=", "LESS_THAN": "<", "LESS_THAN_OR_EQUAL": "<=",
                "GREATER_THAN": ">", "GREATER_THAN_OR_EQUAL": ">=", "AND": "AND", "OR": "OR"
            }.get(node.op, node.op)
            return f"({left_str} {op_sym} {right_str})"
        elif isinstance(node, UnaryOpNode):
            return f"{node.op}({self.format_expression(node.operand)})"
        return f"<{type(node).__name__}>"

    def format_effect(self, node: GRLNode, indent: int = 0) -> str:
        ind = "  " * indent
        if isinstance(node, SetPropertyNode):
            return f"{ind}{node.entity_var}.{node.property_name} = {self.format_expression(node.value_expr)}"
        elif isinstance(node, AdjustPropertyNode):
            return f"{ind}{node.entity_var}.{node.property_name} += {self.format_expression(node.delta_expr)}"
        elif isinstance(node, ConsumeResourceNode):
            return f'{ind}CONSUME_RESOURCE "{node.pool_name}" AMOUNT {self.format_expression(node.amount_expr)}'
        elif isinstance(node, ProduceResourceNode):
            return f'{ind}PRODUCE_RESOURCE "{node.pool_name}" AMOUNT {self.format_expression(node.amount_expr)}'
        elif isinstance(node, TransferResourceNode):
            return f'{ind}TRANSFER_RESOURCE FROM "{node.from_pool}" TO "{node.to_pool}" AMOUNT {self.format_expression(node.amount_expr)}'
        elif isinstance(node, AddRelationshipNode):
            w = f" WEIGHT {self.format_expression(node.weight_expr)}" if node.weight_expr else ""
            return f'{ind}ADD_RELATIONSHIP {node.source_var} -> {node.target_var} TYPE "{node.rel_type}"{w}'
        elif isinstance(node, RemoveRelationshipNode):
            return f'{ind}REMOVE_RELATIONSHIP {node.source_var} -> {node.target_var} TYPE "{node.rel_type}"'
        elif isinstance(node, ScheduleEventNode):
            return f'{ind}SCHEDULE_EVENT "{node.event_type}" IN {node.delay_ticks} TICKS'
        elif isinstance(node, IfNode):
            lines = [f"{ind}IF {self.format_expression(node.condition)} THEN:"]
            for child in node.then_effects:
                lines.append(self.format_effect(child, indent + 1))
            if node.else_effects:
                lines.append(f"{ind}ELSE:")
                for child in node.else_effects:
                    lines.append(self.format_effect(child, indent + 1))
            return "\n".join(lines)
        elif isinstance(node, ForEachNode):
            lines = [f"{ind}FOR EACH {node.iterator_var} IN {node.collection_source}:"]
            for child in node.body:
                lines.append(self.format_effect(child, indent + 1))
            return "\n".join(lines)
        return f"{ind}<{type(node).__name__}>"
