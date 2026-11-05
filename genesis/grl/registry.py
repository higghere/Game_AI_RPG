"""GENESIS Rule Registry and Versioning Substrate.

Provides deterministic rule ordering, prospective rule installation,
and version tracking.
"""

from __future__ import annotations
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.grl.ast import RuleDefinition
from genesis.grl.interpreter import GRLInterpreter
from genesis.grl.validator import GRLValidator
from genesis.substrate.world_state import WorldState


class RuleRegistry:
    """Registry maintaining active and staged GRL rules with prospective installation."""

    def __init__(self, config: RuntimeConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self._rules: Dict[str, RuleDefinition] = {}
        self._rule_hashes: Dict[str, str] = {}
        self.validator = GRLValidator(config)
        self.interpreter = GRLInterpreter(config)

    def register_rule(self, rule: RuleDefinition, current_tick: int) -> str:
        """Statically validate and install a rule prospectively.

        Prospective installation rule: active_from_tick = current_tick + 1.
        """
        # Validate statically first
        self.validator.validate_rule(rule)

        # Enforce prospective activation
        rule.active_from_tick = current_tick + 1

        # Compute canonical hash
        rule_dict = {
            "rule_id": rule.rule_id,
            "version": rule.version,
            "priority": rule.priority,
            "active_from_tick": rule.active_from_tick,
        }
        rule_hash = hashlib.sha256(
            json.dumps(rule_dict, sort_keys=True).encode("utf-8")
        ).hexdigest()

        self._rules[rule.rule_id] = rule
        self._rule_hashes[rule.rule_id] = rule_hash
        return rule_hash

    def get_active_rules(self, current_tick: int) -> List[RuleDefinition]:
        """Return rules active at current_tick, sorted deterministically by (-priority, rule_id)."""
        active = [r for r in self._rules.values() if r.active_from_tick <= current_tick]
        return sorted(active, key=lambda r: (-r.priority, r.rule_id))

    def execute_active_rules(self, world: WorldState) -> List[Tuple[str, bool, str]]:
        """Execute all active rules in deterministic priority order."""
        active_rules = self.get_active_rules(world.clock.current_tick)
        results: List[Tuple[str, bool, str]] = []
        for rule in active_rules:
            success, msg = self.interpreter.execute_rule(rule, world)
            results.append((rule.rule_id, success, msg))
        return results

    def to_dict(self) -> Dict[str, Any]:
        """Serialize registered rules."""
        out: Dict[str, Any] = {}
        for rid in sorted(self._rules.keys()):
            r = self._rules[rid]
            out[rid] = {
                "rule_id": r.rule_id,
                "name": r.name,
                "version": r.version,
                "priority": r.priority,
                "active_from_tick": str(r.active_from_tick),
                "hash": self._rule_hashes.get(rid, ""),
            }
        return out
