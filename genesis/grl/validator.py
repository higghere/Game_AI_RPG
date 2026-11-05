"""GENESIS Rule Language Static Validator.

Statically enforces loop depth limits (<= 4), recursion prohibition,
and structural constraints prior to rule registration.
"""

from __future__ import annotations
from typing import List

from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.core.errors import GRLStructuralValidationError, GRLValidationError
from genesis.grl.ast import ForEachNode, GRLNode, IfNode, RuleDefinition


class GRLValidator:
    """Static AST analyzer for GRL safety and limit verification."""

    def __init__(self, config: RuntimeConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def validate_rule(self, rule: RuleDefinition) -> None:
        """Validate structural safety, bounds, and absence of recursion."""
        # 1. Check loop depth
        max_depth = self._calculate_max_loop_depth(rule.effects, current_depth=0)
        if max_depth > self.config.max_loop_depth:
            raise GRLStructuralValidationError(
                f"Rule '{rule.rule_id}' exceeds maximum loop depth: {max_depth} > {self.config.max_loop_depth}"
            )

        # 2. Check for recursion / dynamic code execution
        self._check_for_recursion(rule.effects)
        for pre in rule.preconditions:
            self._check_node_recursion(pre)

    def _calculate_max_loop_depth(self, nodes: List[GRLNode], current_depth: int) -> int:
        """Recursively compute maximum loop nesting depth in an AST node list."""
        max_depth = current_depth
        for node in nodes:
            if isinstance(node, ForEachNode):
                branch_depth = self._calculate_max_loop_depth(node.body, current_depth + 1)
                max_depth = max(max_depth, branch_depth)
            elif isinstance(node, IfNode):
                then_depth = self._calculate_max_loop_depth(node.then_effects, current_depth)
                else_depth = self._calculate_max_loop_depth(node.else_effects, current_depth)
                max_depth = max(max_depth, then_depth, else_depth)
        return max_depth

    def _check_for_recursion(self, nodes: List[GRLNode]) -> None:
        """Traverse nodes and reject any unauthorized recursive constructs."""
        for node in nodes:
            self._check_node_recursion(node)

    def _check_node_recursion(self, node: GRLNode) -> None:
        # Check node class name or attributes for invocation constructs
        node_name = type(node).__name__.lower()
        if "recurse" in node_name or "invokerule" in node_name or "call" in node_name:
            raise GRLStructuralValidationError("Recursion and subrule invocation are strictly prohibited in GRL")

        if isinstance(node, ForEachNode):
            for child in node.body:
                self._check_node_recursion(child)
        elif isinstance(node, IfNode):
            for child in node.then_effects:
                self._check_node_recursion(child)
            for child in node.else_effects:
                self._check_node_recursion(child)
