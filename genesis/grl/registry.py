"""GENESIS Rule Registry and Versioning Substrate.

Provides deterministic rule ordering, prospective rule installation,
full canonical rule body hashing, and journal event logging.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.grl.ast import RuleDefinition, rule_to_canonical_dict
from genesis.grl.interpreter import GRLInterpreter
from genesis.grl.parser import GRLParser
from genesis.grl.validator import GRLValidator
from genesis.persistence.hasher import compute_canonical_hash
from genesis.substrate.events import EventRecord, PHASE_PRE_TICK
from genesis.substrate.world_state import WorldState


class RuleRegistry:
    """Registry maintaining active and staged GRL rules with prospective installation."""

    def __init__(self, config: RuntimeConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self._rules: Dict[str, RuleDefinition] = {}
        self._rule_hashes: Dict[str, str] = {}
        self.validator = GRLValidator(config)
        self.interpreter = GRLInterpreter(config)

    def register_rule(
        self,
        rule: RuleDefinition,
        current_tick: int,
        world: Optional[WorldState] = None,
    ) -> str:
        """Statically validate, prospectively install, and hash the full canonical rule body.

        Writes a 'rule_installed' event to the world journal if world is provided.
        """
        # 1. Validate statically
        self.validator.validate_rule(rule)

        # 2. Prospective activation: tick + 1
        rule.active_from_tick = current_tick + 1

        # 3. Hash FULL canonical rule body (all AST nodes, selectors, preconditions, effects)
        canonical_body = rule_to_canonical_dict(rule)
        rule_hash = compute_canonical_hash(canonical_body)

        self._rules[rule.rule_id] = rule
        self._rule_hashes[rule.rule_id] = rule_hash

        # 4. Write rule_installed journal event
        if world is not None:
            install_event = EventRecord(
                tick=current_tick,
                phase=PHASE_PRE_TICK,
                priority=100,
                sequence_id=world.next_sequence_id(),
                event_type="rule_installed",
                payload={
                    "rule_id": rule.rule_id,
                    "rule_hash": rule_hash,
                    "version": rule.version,
                    "active_from_tick": str(rule.active_from_tick),
                },
            )
            world.event_journal.append(install_event)

        return rule_hash

    def get_rule(self, rule_id: str) -> Optional[RuleDefinition]:
        return self._rules.get(rule_id)

    def get_rule_hash(self, rule_id: str) -> Optional[str]:
        return self._rule_hashes.get(rule_id)

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

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Serialize complete rule definitions and full-body hashes."""
        out: Dict[str, Any] = {}
        for rid in sorted(self._rules.keys()):
            r = self._rules[rid]
            c_dict = rule_to_canonical_dict(r)
            c_dict["rule_hash"] = self._rule_hashes.get(rid, "")
            out[rid] = c_dict
        return out

    @classmethod
    def from_canonical_dict(cls, data: Dict[str, Any], config: Optional[RuntimeConfig] = None) -> RuleRegistry:
        """Restore rule registry from canonical snapshot data."""
        reg = cls(config or DEFAULT_CONFIG)
        parser = GRLParser()
        for rid in sorted(data.keys()):
            rdata = data[rid]
            rule = parser.parse_rule(rdata)
            rule.active_from_tick = int(rdata.get("active_from_tick", 0))
            rule_hash = rdata.get("rule_hash") or compute_canonical_hash(rule_to_canonical_dict(rule))
            reg._rules[rid] = rule
            reg._rule_hashes[rid] = rule_hash
        return reg

    def to_dict(self) -> Dict[str, Any]:
        return self.to_canonical_dict()
