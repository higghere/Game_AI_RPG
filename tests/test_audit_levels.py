"""Unit tests for GENESIS Journal Audit Levels (MINIMAL, SUMMARY, TRACE)."""

import unittest

from genesis.core.arithmetic import FixedPoint
from genesis.core.config import RuntimeConfig
from genesis.grl.parser import GRLParser
from genesis.substrate.events import (
    AUDIT_LEVEL_MINIMAL,
    AUDIT_LEVEL_SUMMARY,
    AUDIT_LEVEL_TRACE,
    PHASE_PERCEPTION_EVENTS,
)
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.world_state import WorldState


class TestAuditLevels(unittest.TestCase):

    def test_default_audit_level_is_summary(self):
        """Default audit level must be SUMMARY."""
        world = WorldState(seed=1)
        self.assertEqual(world.audit_level, AUDIT_LEVEL_SUMMARY)

    def test_audit_level_change_is_journaled(self):
        """Changing audit level must append an audit_level_changed event to the journal."""
        world = WorldState(seed=2)
        initial_events = len(world.event_journal.records)

        world.set_audit_level("TRACE")
        self.assertEqual(world.audit_level, "TRACE")

        records = world.event_journal.records
        self.assertEqual(len(records), initial_events + 1)
        last_event = records[-1]
        self.assertEqual(last_event.event_type, "audit_level_changed")
        self.assertEqual(last_event.payload["from_level"], "SUMMARY")
        self.assertEqual(last_event.payload["to_level"], "TRACE")

        # Invalid audit level raises ValueError
        with self.assertRaises(ValueError):
            world.set_audit_level("VERBOSE_INVALID")

    def test_summary_and_minimal_collapse_routine_events_into_tick_digest(self):
        """In SUMMARY and MINIMAL, routine rule successes and tick boundaries collapse into one tick_digest."""
        world = WorldState(seed=3)
        world.resources.create_pool("biomass", initial_balance=FixedPoint.from_int(100))

        # Install a simple rule
        rule_dict = {
            "rule_id": "r_prod",
            "name": "Produce Biomass",
            "version": "1.0",
            "priority": 10,
            "effects": [
                {
                    "op": "PRODUCE_RESOURCE",
                    "pool": "biomass",
                    "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1000000"},
                }
            ],
        }
        world.register_rule(GRLParser().parse_rule(rule_dict))

        # Advance tick 1 (rule prospective activation + tick_digest)
        world.advance_tick()
        # Advance tick 2 (rule executes + tick_digest)
        world.advance_tick()

        # In SUMMARY mode, tick 2 should have exactly 1 event: tick_digest
        tick_2_events = [e for e in world.event_journal.records if e.tick == 2]
        self.assertEqual(len(tick_2_events), 1)
        digest = tick_2_events[0]
        self.assertEqual(digest.event_type, "tick_digest")
        self.assertEqual(digest.payload["tick"], "2")
        self.assertEqual(digest.payload["rules_executed"], "1")
        self.assertEqual(digest.payload["audit_level"], "SUMMARY")

        # Switch to MINIMAL and advance tick 3
        world.set_audit_level("MINIMAL")
        world.advance_tick()

        tick_3_events = [e for e in world.event_journal.records if e.tick == 3 and e.event_type == "tick_digest"]
        self.assertEqual(len(tick_3_events), 1)
        self.assertEqual(tick_3_events[0].payload["audit_level"], "MINIMAL")

    def test_trace_audit_level_logs_individual_events(self):
        """In TRACE mode, tick_started, rule_executed_success, and tick_completed are logged individually."""
        world = WorldState(seed=4)
        world.set_audit_level("TRACE")
        world.resources.create_pool("biomass", initial_balance=FixedPoint.from_int(100))

        rule_dict = {
            "rule_id": "r_trace_prod",
            "name": "Trace Produce",
            "version": "1.0",
            "priority": 10,
            "effects": [
                {
                    "op": "PRODUCE_RESOURCE",
                    "pool": "biomass",
                    "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1000000"},
                }
            ],
        }
        world.register_rule(GRLParser().parse_rule(rule_dict))
        world.advance_tick()  # tick 1
        world.advance_tick()  # tick 2

        tick_2_events = [e for e in world.event_journal.records if e.tick == 2]
        event_types = [e.event_type for e in tick_2_events]

        self.assertIn("tick_started", event_types)
        self.assertIn("rule_executed_success", event_types)
        self.assertIn("resource_settlement_audited", event_types)
        self.assertIn("tick_completed", event_types)

    def test_critical_events_always_logged_individually_at_every_level(self):
        """Domain events, rule installs, rule failures, and internal errors must be logged individually across all levels."""
        for level in [AUDIT_LEVEL_MINIMAL, AUDIT_LEVEL_SUMMARY, AUDIT_LEVEL_TRACE]:
            world = WorldState(seed=5)
            world.set_audit_level(level)

            # 1. Rule installation must be logged individually
            rule_dict = {
                "rule_id": f"r_fail_{level}",
                "name": "Failing Rule",
                "version": "1.0",
                "priority": 10,
                "effects": [
                    {
                        "op": "CONSUME_RESOURCE",
                        "pool": "non_existent_pool",
                        "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1000000"},
                    }
                ],
            }
            rule = GRLParser().parse_rule(rule_dict)
            world.register_rule(rule)

            # 2. Schedule a domain event (e.g. birth / perception event)
            world.event_queue.schedule(
                tick=1,
                phase=PHASE_PERCEPTION_EVENTS,
                priority=10,
                event_type="birth",
                payload={"organism_id": "org_42", "species": "algae"},
            )

            world.advance_tick()

            # Verify critical events are present in journal regardless of level
            records = [e for e in world.event_journal.records if e.tick <= 1]
            event_types = {e.event_type for e in records}

            self.assertIn("rule_installed", event_types, f"rule_installed missing in level {level}")
            self.assertIn("birth", event_types, f"Domain event 'birth' missing in level {level}")

            # Advance to tick 2 to run failing rule
            world.advance_tick()
            tick_2_types = {e.event_type for e in world.event_journal.records if e.tick == 2}
            self.assertIn("rule_execution_failed", tick_2_types, f"rule_execution_failed missing in level {level}")


if __name__ == "__main__":
    unittest.main()
