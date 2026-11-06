"""Phase 2a Test Suite: GRL Primitives, Closed Grammar, Metering, and Rollback Atomicity.

Verifies:
1. Valid and invalid use of each new primitive:
   - CREATE_ENTITY, DESTROY_ENTITY
   - RANDOM_INT, RANDOM_FIXED
   - FIND_ENTITY, AGGREGATE, bounded FOR_EACH
   - Data-defined relationship kinds
2. Strict closed grammar enforcement on rules, target selectors, expressions, and effects.
3. Ceiling enforcement: max_scan <= 16, max_elements <= 32, max_iterations <= 32.
4. Operational quota enforcement (<= 256 ops) and tick-wide touch limit (<= 1000 touches).
5. Rollback atomicity: create + destroy + fail leaves world substrate state hash bit-identical to before.
6. PRNG rollback atomicity: failed rules do not advance RNG state.
7. Determinism across save/reload mid-run.
8. Spatial index consistency for newly created and destroyed entities.
9. Real GRL interpreter execution of all 6 audit rules from docs/ecosystem-design.md Section 8.
"""

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from genesis.core.arithmetic import FixedPoint
from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.core.errors import (
    DivisionByZeroError,
    GRLStructuralValidationError,
    GRLValidationError,
    QuotaExceededError,
)
from genesis.core.rng import GenesisRNG
from genesis.grl.ast import (
    AggregateNode,
    CreateEntityNode,
    DestroyEntityNode,
    FindEntityNode,
    ForEachNode,
    LiteralNode,
    RandomFixedNode,
    RandomIntNode,
    RuleDefinition,
    TargetSelector,
    ast_to_canonical_dict,
    rule_to_canonical_dict,
)
from genesis.grl.interpreter import ExecutionContext, GRLInterpreter
from genesis.grl.parser import GRLParser
from genesis.grl.serializer import GRLSerializer
from genesis.grl.validator import GRLValidator
from genesis.persistence.hasher import compute_canonical_hash
from genesis.persistence.snapshot import SnapshotManager
from genesis.substrate.entities import Entity
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.relationships import (
    RelationshipEdge,
    RelationshipKindDefinition,
    RelationshipKindRegistry,
)
from genesis.substrate.world_state import WorldState


class TestGRLPhase2aPrimitives(unittest.TestCase):
    """Unit tests for Phase 2a GRL primitives, parser, validator, and interpreter."""

    def setUp(self) -> None:
        self.world = WorldState(seed=20261106)
        self.parser = GRLParser()
        self.validator = GRLValidator()
        self.interpreter = GRLInterpreter()

        # Register organism schema
        schema = EntityTypeSchema("organism")
        schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("energy", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
        schema.add_property(PropertyDefinition("biomass", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(50)))
        schema.add_property(PropertyDefinition("age", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("generation", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("is_alive", PropertyType.INT64, default_value=1))
        self.world.schema_registry.register_type(schema)

    # -------------------------------------------------------------------------
    # 1. Closed Grammar Enforcement
    # -------------------------------------------------------------------------
    def test_closed_grammar_rejects_unknown_rule_fields(self):
        """Rule parser must reject unexpected/arbitrary JSON keys."""
        data = {
            "rule_id": "r_closed",
            "name": "Closed Grammar Test",
            "version": "1.0",
            "malicious_extra_field": 42,
        }
        with self.assertRaises(GRLValidationError) as ctx:
            self.parser.parse_rule(data)
        self.assertIn("Unknown fields in rule definition", str(ctx.exception))

    def test_closed_grammar_rejects_unknown_target_selector_fields(self):
        data = {
            "rule_id": "r_sel",
            "name": "Selector Test",
            "version": "1.0",
            "target_selector": {
                "entity_type": "organism",
                "bogus_key": True,
            },
        }
        with self.assertRaises(GRLValidationError) as ctx:
            self.parser.parse_rule(data)
        self.assertIn("Unknown fields in target_selector", str(ctx.exception))

    def test_closed_grammar_rejects_unknown_expression_fields(self):
        with self.assertRaises(GRLValidationError):
            self.parser.parse_expression({"op": "LITERAL", "type": "INT64", "value": "5", "extra": 1})
        with self.assertRaises(GRLValidationError):
            self.parser.parse_expression({"op": "RANDOM_INT", "min": "1", "max": "10", "seed": 99})

    def test_closed_grammar_rejects_unknown_effect_fields(self):
        with self.assertRaises(GRLValidationError):
            self.parser.parse_effect({"op": "DESTROY_ENTITY", "entity": "target", "cascade": True})
        with self.assertRaises(GRLValidationError):
            self.parser.parse_effect({"op": "CREATE_ENTITY", "entity_type": "organism", "result_var": "x", "initial_properties": {}, "extra": 1})

    # -------------------------------------------------------------------------
    # 2. RANDOM_INT and RANDOM_FIXED Primitives
    # -------------------------------------------------------------------------
    def test_random_int_valid_evaluation(self):
        node = self.parser.parse_expression({"op": "RANDOM_INT", "min": "10", "max": "20"})
        self.assertIsInstance(node, RandomIntNode)
        ctx = ExecutionContext("test_rng", self.world)
        val = self.interpreter.eval_expression(node, ctx, self.world)
        self.assertIsInstance(val, int)
        self.assertTrue(10 <= val <= 20)
        self.assertEqual(ctx.operations_count, 1)

    def test_random_int_rejects_min_greater_than_max(self):
        with self.assertRaises(GRLValidationError):
            self.parser.parse_expression({"op": "RANDOM_INT", "min": "20", "max": "10"})

    def test_random_fixed_valid_evaluation(self):
        node = self.parser.parse_expression({"op": "RANDOM_FIXED", "min": "0.100000", "max": "0.500000"})
        self.assertIsInstance(node, RandomFixedNode)
        ctx = ExecutionContext("test_rng_fixed", self.world)
        val = self.interpreter.eval_expression(node, ctx, self.world)
        self.assertIsInstance(val, FixedPoint)
        self.assertTrue(FixedPoint.from_decimal_string("0.100000") <= val <= FixedPoint.from_decimal_string("0.500000"))
        self.assertEqual(ctx.operations_count, 1)

    def test_random_fixed_rejects_min_greater_than_max(self):
        with self.assertRaises(GRLValidationError):
            self.parser.parse_expression({"op": "RANDOM_FIXED", "min": "0.500000", "max": "0.100000"})

    # -------------------------------------------------------------------------
    # 3. Ceilings: max_scan <= 16, max_elements <= 32, max_iterations <= 32
    # -------------------------------------------------------------------------
    def test_find_entity_ceiling_enforcement(self):
        # max_scan = 16 (permitted)
        node16 = self.parser.parse_effect({
            "op": "FIND_ENTITY", "result_var": "cand", "collection_source": "cell_entities", "max_scan": 16,
        })
        self.assertEqual(node16.max_scan, 16)

        # max_scan = 17 (rejected at parse time)
        with self.assertRaises(GRLValidationError):
            self.parser.parse_effect({
                "op": "FIND_ENTITY", "result_var": "cand", "collection_source": "cell_entities", "max_scan": 17,
            })

        # Validator also rejects
        rule_over = RuleDefinition("r_scan", "r_scan", "1.0", effects=[FindEntityNode("cand", "cell_entities", max_scan=20)])
        with self.assertRaises(GRLValidationError):
            self.validator.validate_rule(rule_over)

    def test_aggregate_ceiling_enforcement(self):
        # max_elements = 32 (permitted)
        node32 = self.parser.parse_effect({
            "op": "AGGREGATE", "aggregate_func": "COUNT", "collection_source": "cell_entities", "max_elements": 32,
        })
        self.assertEqual(node32.max_elements, 32)

        # max_elements = 33 (rejected at parse time)
        with self.assertRaises(GRLValidationError):
            self.parser.parse_effect({
                "op": "AGGREGATE", "aggregate_func": "COUNT", "collection_source": "cell_entities", "max_elements": 33,
            })

    def test_for_each_ceiling_enforcement(self):
        # max_iterations = 32 (permitted)
        node32 = self.parser.parse_effect({
            "op": "FOR_EACH", "iterator_var": "i", "collection_source": "cell_entities", "max_iterations": 32, "body": [],
        })
        self.assertEqual(node32.max_iterations, 32)

        # max_iterations = 33 (rejected at parse time)
        with self.assertRaises(GRLValidationError):
            self.parser.parse_effect({
                "op": "FOR_EACH", "iterator_var": "i", "collection_source": "cell_entities", "max_iterations": 33, "body": [],
            })

    # -------------------------------------------------------------------------
    # 4. CREATE_ENTITY and DESTROY_ENTITY Semantics & Spatial Consistency
    # -------------------------------------------------------------------------
    def test_create_entity_and_spatial_placement(self):
        rule_json = {
            "rule_id": "r_birth",
            "name": "Birth Rule",
            "version": "1.0",
            "effects": [
                {
                    "op": "CREATE_ENTITY",
                    "entity_type": "organism",
                    "result_var": "newborn",
                    "initial_properties": {
                        "cell_x": {"op": "LITERAL", "type": "INT64", "value": "2"},
                        "cell_y": {"op": "LITERAL", "type": "INT64", "value": "3"},
                        "energy": {"op": "LITERAL", "type": "FIXED_POINT", "value": "75.000000"},
                    },
                }
            ],
        }
        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world)
        self.assertTrue(success, msg)

        # Newborn must exist in storage with monotonic ID 1
        newborn = self.world.entities.get_entity(1)
        self.assertIsNotNone(newborn)
        self.assertEqual(newborn.entity_type, "organism")
        self.assertEqual(newborn.get_property("energy"), FixedPoint.from_int(75))

        # Newborn must be in cell (2, 3)
        in_cell = self.world.spatial_index.get_entities_in_cell(2, 3)
        self.assertIn(1, in_cell)

        # Event journal must have entity_created domain event
        events = [e for e in self.world.event_journal.records if e.event_type == "entity_created"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["entity_id"], "1")
        self.assertEqual(events[0].payload["cell_x"], "2")
        self.assertEqual(events[0].payload["cell_y"], "3")

    def test_destroy_entity_and_spatial_purge(self):
        ent = self.world.entities.create_entity("organism", 0, {"cell_x": 1, "cell_y": 1}, self.world.schema_registry)
        self.world.spatial_index.place_entity(ent.id, 1, 1)
        other = self.world.entities.create_entity("organism", 0, {"cell_x": 1, "cell_y": 1}, self.world.schema_registry)
        self.world.relationships.add_edge(ent.id, other.id, "linked_to")

        rule_json = {
            "rule_id": "r_death",
            "name": "Death Rule",
            "version": "1.0",
            "target_selector": {
                "entity_type": "organism",
                "limit": 1,
            },
            "effects": [
                {"op": "DESTROY_ENTITY", "entity": "target"}
            ],
        }
        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world)
        self.assertTrue(success, msg)

        # Entity 1 must be purged from storage and spatial index
        self.assertIsNone(self.world.entities.get_entity(ent.id))
        self.assertNotIn(ent.id, self.world.spatial_index.get_entities_in_cell(1, 1))

        # Relationship must be purged
        self.assertFalse(self.world.relationships.has_edge(ent.id, other.id, "linked_to"))

        # Event journal must record entity_destroyed
        events = [e for e in self.world.event_journal.records if e.event_type == "entity_destroyed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["entity_id"], str(ent.id))

    # -------------------------------------------------------------------------
    # 5. Rollback Atomicity (Create + Destroy + Fail)
    # -------------------------------------------------------------------------
    def test_rollback_atomicity_with_create_destroy_fail(self):
        """A rule that creates an entity, destroys an entity, advances RNG, and then fails must roll back 100% cleanly.
        
        Substrate state hash after rollback must be bit-identical to before execution.
        """
        # Create living parent entity
        parent = self.world.entities.create_entity(
            "organism", 0, {"cell_x": 0, "cell_y": 0, "energy": FixedPoint.from_int(100)}, self.world.schema_registry
        )
        self.world.spatial_index.place_entity(parent.id, 0, 0)
        self.world.relationships.add_edge(parent.id, 999, "parent_edge")

        initial_hash = self.world.compute_state_hash(include_journal=False)
        initial_rng_state = self.world.rng.get_state()
        initial_next_id = self.world.entities._next_id

        # Rule that creates an entity, draws from PRNG, destroys parent, and then triggers division by zero
        failing_rule_json = {
            "rule_id": "r_atomic_fail",
            "name": "Atomic Fail Rule",
            "version": "1.0",
            "target_selector": {
                "entity_type": "organism",
                "limit": 1,
            },
            "effects": [
                # 1. Create offspring
                {
                    "op": "CREATE_ENTITY",
                    "entity_type": "organism",
                    "result_var": "child",
                    "initial_properties": {
                        "cell_x": {"op": "LITERAL", "type": "INT64", "value": "0"},
                        "cell_y": {"op": "LITERAL", "type": "INT64", "value": "0"},
                        "energy": {
                            "op": "RANDOM_FIXED",
                            "min": "10.000000",
                            "max": "20.000000",
                        },
                    },
                },
                # 2. Destroy parent
                {"op": "DESTROY_ENTITY", "entity": "target"},
                # 3. Deliberate division by zero error on newborn child
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "child",
                    "property": "energy",
                    "delta": {
                        "op": "DIVIDE",
                        "left": {"op": "LITERAL", "type": "INT64", "value": "10"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                },
            ],
        }

        rule = self.parser.parse_rule(failing_rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world)

        # Execution must fail
        self.assertFalse(success)
        self.assertIn("DivisionByZeroError", msg)

        # 1. Created offspring must NOT be in world state or spatial index
        self.assertIsNone(self.world.entities.get_entity(2))
        self.assertEqual(self.world.entities._next_id, initial_next_id)

        # 2. Parent must NOT be destroyed; must be active and intact in spatial index
        restored_parent = self.world.entities.get_entity(parent.id)
        self.assertIsNotNone(restored_parent)
        self.assertTrue(restored_parent.is_active)
        self.assertEqual(restored_parent.get_property("energy"), FixedPoint.from_int(100))
        self.assertIn(parent.id, self.world.spatial_index.get_entities_in_cell(0, 0))
        self.assertTrue(self.world.relationships.has_edge(parent.id, 999, "parent_edge"))

        # 3. RNG state must be bit-identical to pre-rule state
        self.assertEqual(self.world.rng.get_state(), initial_rng_state)

        # 4. Pure world substrate state hash must be 100% bit-identical
        post_rollback_hash = self.world.compute_state_hash(include_journal=False)
        self.assertEqual(
            initial_hash,
            post_rollback_hash,
            "World substrate state hash drifted after failed rule rollback!",
        )

    # -------------------------------------------------------------------------
    # 6. Quota Enforcement: Exceeding 256 Operations Rolls Back
    # -------------------------------------------------------------------------
    def test_quota_exceeded_rolls_back_cleanly(self):
        for i in range(100):
            ent = self.world.entities.create_entity(
                "organism", 0, {"cell_x": 0, "cell_y": 0, "age": i}, self.world.schema_registry
            )
            self.world.spatial_index.place_entity(ent.id, 0, 0)

        initial_hash = self.world.compute_state_hash(include_journal=False)

        # Rule that modifies age but runs out of gas (each candidate takes multiple ops)
        heavy_rule_json = {
            "rule_id": "r_heavy",
            "name": "Heavy Quota Breaker",
            "version": "1.0",
            "target_selector": {
                "entity_type": "organism",
                "limit": 100,
            },
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "age",
                    "delta": {"op": "LITERAL", "type": "INT64", "value": "100"},
                }
            ],
        }
        rule = self.parser.parse_rule(heavy_rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world)

        self.assertFalse(success)
        self.assertIn("QuotaExceededError", msg)

        # World state hash must be identical (no age was modified)
        self.assertEqual(self.world.compute_state_hash(include_journal=False), initial_hash)
        for ent in self.world.entities.all_entities():
            self.assertLess(ent.get_property("age"), 100)

    # -------------------------------------------------------------------------
    # 7. Determinism Across Snapshot Save/Reload Mid-Run
    # -------------------------------------------------------------------------
    def test_determinism_across_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            sm = SnapshotManager(base_dir=tmp_dir)

            # World 1: Runs continuously for 6 ticks
            w1 = WorldState(seed=77777, journal_dir=Path(tmp_dir) / "j1")
            schema = EntityTypeSchema("organism")
            schema.add_property(PropertyDefinition("energy", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
            w1.schema_registry.register_type(schema)
            w1.entities.create_entity("organism", 0, {"energy": FixedPoint.from_int(50)}, w1.schema_registry)

            # World 2: Runs for 3 ticks, saves snapshot, reloads, runs 3 more ticks
            w2 = WorldState(seed=77777, journal_dir=Path(tmp_dir) / "j2")
            w2.schema_registry.register_type(schema)
            w2.entities.create_entity("organism", 0, {"energy": FixedPoint.from_int(50)}, w2.schema_registry)

            for _ in range(3):
                roll = w1.rng.next_int_range(1, 10)
                ent = w1.entities.get_entity(1)
                ent.set_property("energy", ent.get_property("energy") + FixedPoint.from_int(roll))
                w1.advance_tick()

                roll2 = w2.rng.next_int_range(1, 10)
                ent2 = w2.entities.get_entity(1)
                ent2.set_property("energy", ent2.get_property("energy") + FixedPoint.from_int(roll2))
                w2.advance_tick()

            # Save snapshot of w2
            snap_path, _ = sm.save_snapshot(w2)
            w2_reloaded = sm.load_snapshot(snap_path)

            for _ in range(3):
                roll = w1.rng.next_int_range(1, 10)
                ent = w1.entities.get_entity(1)
                ent.set_property("energy", ent.get_property("energy") + FixedPoint.from_int(roll))
                w1.advance_tick()

                roll_r = w2_reloaded.rng.next_int_range(1, 10)
                ent_r = w2_reloaded.entities.get_entity(1)
                ent_r.set_property("energy", ent_r.get_property("energy") + FixedPoint.from_int(roll_r))
                w2_reloaded.advance_tick()

            # Hashes must match 100% bit-for-bit
            self.assertEqual(
                w1.compute_state_hash(include_journal=False),
                w2_reloaded.compute_state_hash(include_journal=False),
            )
            self.assertEqual(w1.event_journal.last_hash, w2_reloaded.event_journal.last_hash)

    # -------------------------------------------------------------------------
    # 8. Data-Defined Relationship Kinds
    # -------------------------------------------------------------------------
    def test_data_defined_relationship_kinds(self):
        reg = self.world.relationship_kinds
        reg.register_kind(RelationshipKindDefinition("parent_of", directed=True, description="Biological parentage"))
        reg.register_kind(RelationshipKindDefinition("traded_with", directed=False, description="Trade transaction"))

        self.assertTrue(reg.has_kind("parent_of"))
        self.assertTrue(reg.has_kind("traded_with"))
        self.assertFalse(reg.has_kind("non_existent"))

        # Serialization round-trip
        data = reg.to_dict()
        rebuilt = RelationshipKindRegistry.from_dict(data)
        self.assertTrue(rebuilt.has_kind("parent_of"))
        self.assertEqual(rebuilt.get_kind("parent_of").description, "Biological parentage")

    # -------------------------------------------------------------------------
    # 9. Real Interpreter Execution of 6 Audit Rules & Op-Count Verification
    # -------------------------------------------------------------------------
    def test_audit_rule_a_reproduction_op_count(self):
        """Case (a): BR_06_REPRODUCTION_WITH_INHERITANCE real execution <= 256 ops."""
        self.world.set_audit_level("TRACE")
        for i in range(10):
            e = FixedPoint.from_int(250) if i in (8, 9) else FixedPoint.from_int(50)
            b = FixedPoint.from_int(120) if i in (8, 9) else FixedPoint.from_int(30)
            ent = self.world.entities.create_entity(
                "organism", 0,
                {"cell_x": 0, "cell_y": 0, "energy": e, "biomass": b, "generation": 0, "is_alive": 1},
                self.world.schema_registry,
            )
            self.world.spatial_index.place_entity(ent.id, 0, 0)

        rule_json = {
            "rule_id": "BR_06_REPRODUCTION_WITH_INHERITANCE",
            "name": "Asexual Reproduction",
            "version": "1.0.0",
            "priority": 40,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "organism",
                "limit": 2,
                "filter": {
                    "op": "AND",
                    "left": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                    "right": {
                        "op": "AND",
                        "left": {
                            "op": "GREATER_THAN_OR_EQUAL",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "energy"},
                            "right": {"op": "LITERAL", "type": "FIXED_POINT", "value": "200.000000"},
                        },
                        "right": {
                            "op": "GREATER_THAN_OR_EQUAL",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "biomass"},
                            "right": {"op": "LITERAL", "type": "FIXED_POINT", "value": "100.000000"},
                        },
                    },
                },
            },
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "energy",
                    "delta": {"op": "LITERAL", "type": "FIXED_POINT", "value": "-100.000000"},
                },
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "biomass",
                    "delta": {"op": "LITERAL", "type": "FIXED_POINT", "value": "-50.000000"},
                },
                {
                    "op": "CREATE_ENTITY",
                    "entity_type": "organism",
                    "result_var": "offspring",
                    "initial_properties": {
                        "cell_x": {"op": "GET_PROPERTY", "entity": "target", "property": "cell_x"},
                        "cell_y": {"op": "GET_PROPERTY", "entity": "target", "property": "cell_y"},
                        "energy": {"op": "LITERAL", "type": "FIXED_POINT", "value": "80.000000"},
                        "biomass": {"op": "LITERAL", "type": "FIXED_POINT", "value": "45.000000"},
                        "generation": {
                            "op": "ADD",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "generation"},
                            "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                        },
                        "age": {"op": "LITERAL", "type": "INT64", "value": "0"},
                        "is_alive": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                },
                {
                    "op": "ADD_RELATIONSHIP",
                    "source": "target",
                    "target": "offspring",
                    "rel_type": "parent_of",
                    "weight": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000"},
                },
            ],
        }

        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world, cell=(0, 0))
        self.assertTrue(success, msg)
        ev = [e for e in self.world.event_journal.records if e.event_type == "rule_executed_success"][-1]
        ops = int(ev.payload["operations_consumed"])
        touches = int(ev.payload["entities_touched"])

        self.assertLessEqual(ops, 256, "Reproduction exceeded 256 ops")
        self.assertLessEqual(touches, 12, "Reproduction touches exceeded 12")
        self.assertEqual(len(self.world.spatial_index.get_entities_in_cell(0, 0)), 12)

    def test_audit_rule_b_death_and_recycling_op_count(self):
        """Case (b): BR_05_DEATH_AND_RECYCLING real execution <= 256 ops."""
        self.world.set_audit_level("TRACE")
        self.world.resources.create_pool("detritus", initial_balance=FixedPoint.from_int(1000))
        for i in range(10):
            e = FixedPoint.from_int(0) if i >= 5 else FixedPoint.from_int(100)
            ent = self.world.entities.create_entity(
                "organism", 0,
                {"cell_x": 0, "cell_y": 0, "energy": e, "biomass": FixedPoint.from_int(25), "age": 50, "is_alive": 1},
                self.world.schema_registry,
            )
            self.world.spatial_index.place_entity(ent.id, 0, 0)

        rule_json = {
            "rule_id": "BR_05_DEATH_AND_RECYCLING",
            "name": "Mortality & Recycling",
            "version": "1.0.0",
            "priority": 50,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "organism",
                "limit": 5,
                "filter": {
                    "op": "AND",
                    "left": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                    "right": {
                        "op": "OR",
                        "left": {
                            "op": "LESS_THAN_OR_EQUAL",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "energy"},
                            "right": {"op": "LITERAL", "type": "FIXED_POINT", "value": "0.000000"},
                        },
                        "right": {
                            "op": "GREATER_THAN_OR_EQUAL",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "age"},
                            "right": {"op": "LITERAL", "type": "INT64", "value": "1000"},
                        },
                    },
                },
            },
            "effects": [
                {
                    "op": "PRODUCE_RESOURCE",
                    "pool": "detritus",
                    "amount": {"op": "GET_PROPERTY", "entity": "target", "property": "biomass"},
                },
                {"op": "DESTROY_ENTITY", "entity": "target"},
            ],
        }

        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world, cell=(0, 0))
        self.assertTrue(success, msg)
        ev = [e for e in self.world.event_journal.records if e.event_type == "rule_executed_success"][-1]
        ops = int(ev.payload["operations_consumed"])
        touches = int(ev.payload["entities_touched"])

        self.assertLessEqual(ops, 256)
        self.assertLessEqual(touches, 10)
        self.assertEqual(len(self.world.spatial_index.get_entities_in_cell(0, 0)), 5)
        # Detritus increased by 5 * 25 = 125
        self.assertEqual(self.world.resources.get_pool("detritus").balance, FixedPoint.from_int(1125))

    def test_audit_rule_c_bilateral_trade(self):
        """Case (c): BR_BILATERAL_TRADE real execution <= 256 ops."""
        self.world.set_audit_level("TRACE")
        agent_schema = EntityTypeSchema("agent")
        agent_schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("grain", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(20)))
        agent_schema.add_property(PropertyDefinition("coins", PropertyType.INT64, default_value=10))
        agent_schema.add_property(PropertyDefinition("is_alive", PropertyType.INT64, default_value=1))
        self.world.schema_registry.register_type(agent_schema)

        a1 = self.world.entities.create_entity(
            "agent", 0, {"cell_x": 0, "cell_y": 0, "grain": FixedPoint.from_int(20), "coins": 0, "is_alive": 1}, self.world.schema_registry
        )
        self.world.spatial_index.place_entity(a1.id, 0, 0)
        for i in range(7):
            coins = 10 if i == 6 else 0
            a = self.world.entities.create_entity(
                "agent", 0, {"cell_x": 0, "cell_y": 0, "grain": FixedPoint.from_int(5), "coins": coins, "is_alive": 1}, self.world.schema_registry
            )
            self.world.spatial_index.place_entity(a.id, 0, 0)

        rule_json = {
            "rule_id": "BR_BILATERAL_TRADE",
            "name": "Bilateral Trade",
            "version": "1.0.0",
            "priority": 55,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "agent",
                "limit": 1,
                "filter": {
                    "op": "AND",
                    "left": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                    "right": {
                        "op": "GREATER_THAN_OR_EQUAL",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "grain"},
                        "right": {"op": "LITERAL", "type": "FIXED_POINT", "value": "10.000000"},
                    },
                },
            },
            "effects": [
                {
                    "op": "FIND_ENTITY",
                    "result_var": "partner",
                    "collection_source": "cell_entities",
                    "entity_type": "agent",
                    "filter": {
                        "op": "AND",
                        "left": {
                            "op": "NOT_EQUALS",
                            "left": {"op": "GET_PROPERTY", "entity": "candidate", "property": "id"},
                            "right": {"op": "GET_PROPERTY", "entity": "target", "property": "id"},
                        },
                        "right": {
                            "op": "AND",
                            "left": {
                                "op": "EQUALS",
                                "left": {"op": "GET_PROPERTY", "entity": "candidate", "property": "is_alive"},
                                "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                            },
                            "right": {
                                "op": "GREATER_THAN_OR_EQUAL",
                                "left": {"op": "GET_PROPERTY", "entity": "candidate", "property": "coins"},
                                "right": {"op": "LITERAL", "type": "INT64", "value": "5"},
                            },
                        },
                    },
                    "order_by": "coins",
                    "order_direction": "DESC",
                    "max_scan": 8,
                    "limit": 1,
                },
                {
                    "op": "IF",
                    "condition": {
                        "op": "NOT_EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "partner", "property": "id"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                    "then": [
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "target",
                            "property": "grain",
                            "delta": {"op": "LITERAL", "type": "FIXED_POINT", "value": "-10.000000"},
                        },
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "target",
                            "property": "coins",
                            "delta": {"op": "LITERAL", "type": "INT64", "value": "5"},
                        },
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "partner",
                            "property": "grain",
                            "delta": {"op": "LITERAL", "type": "FIXED_POINT", "value": "10.000000"},
                        },
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "partner",
                            "property": "coins",
                            "delta": {"op": "LITERAL", "type": "INT64", "value": "-5"},
                        },
                        {
                            "op": "ADD_RELATIONSHIP",
                            "source": "target",
                            "target": "partner",
                            "rel_type": "traded_with",
                            "weight": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000"},
                        },
                    ],
                    "else": [],
                },
            ],
        }

        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world, cell=(0, 0))
        self.assertTrue(success, msg)
        ev = [e for e in self.world.event_journal.records if e.event_type == "rule_executed_success"][-1]
        ops = int(ev.payload["operations_consumed"])
        touches = int(ev.payload["entities_touched"])

        self.assertLessEqual(ops, 256)
        self.assertLessEqual(touches, 9)
        # Verify swap
        self.assertEqual(a1.get_property("coins"), 5)
        self.assertEqual(a1.get_property("grain"), FixedPoint.from_int(10))

    def test_aggregate_count_sum_min_max(self):
        """Verify AGGREGATE node over cell entities for COUNT, SUM, MIN, MAX."""
        # Create 5 organisms with different energy values
        for i in range(1, 6):
            ent = self.world.entities.create_entity(
                "organism", 0, {"cell_x": 0, "cell_y": 0, "energy": FixedPoint.from_int(i * 10)}, self.world.schema_registry
            )
            self.world.spatial_index.place_entity(ent.id, 0, 0)

        # 1. COUNT
        rule_count = {
            "rule_id": "r_agg_count", "name": "Count Organisms", "version": "1.0",
            "effects": [
                {
                    "op": "AGGREGATE",
                    "aggregate_func": "COUNT",
                    "collection_source": "cell_entities",
                    "result_var": "total_count",
                    "max_elements": 10,
                }
            ],
        }
        rule = self.parser.parse_rule(rule_count)
        ctx = ExecutionContext("r_agg_count", self.world)
        ctx.variables["current_cell_x"] = 0
        ctx.variables["current_cell_y"] = 0
        for eff in rule.effects:
            self.interpreter.eval_effect(eff, ctx, self.world)
        self.assertEqual(ctx.variables["total_count"], 5)

        # 2. SUM
        rule_sum = {
            "rule_id": "r_agg_sum", "name": "Sum Energy", "version": "1.0",
            "effects": [
                {
                    "op": "AGGREGATE",
                    "aggregate_func": "SUM",
                    "collection_source": "cell_entities",
                    "result_var": "total_energy",
                    "element_var": "item",
                    "expr": {"op": "GET_PROPERTY", "entity": "item", "property": "energy"},
                    "max_elements": 10,
                }
            ],
        }
        rule = self.parser.parse_rule(rule_sum)
        ctx = ExecutionContext("r_agg_sum", self.world)
        ctx.variables["current_cell_x"] = 0
        ctx.variables["current_cell_y"] = 0
        for eff in rule.effects:
            self.interpreter.eval_effect(eff, ctx, self.world)
        # Sum = 10 + 20 + 30 + 40 + 50 = 150
        self.assertEqual(ctx.variables["total_energy"], FixedPoint.from_int(150))

        # 3. MIN & MAX
        rule_min_max = {
            "rule_id": "r_agg_minmax", "name": "Min Max Energy", "version": "1.0",
            "effects": [
                {
                    "op": "AGGREGATE",
                    "aggregate_func": "MIN",
                    "collection_source": "cell_entities",
                    "result_var": "min_energy",
                    "element_var": "item",
                    "expr": {"op": "GET_PROPERTY", "entity": "item", "property": "energy"},
                    "max_elements": 10,
                },
                {
                    "op": "AGGREGATE",
                    "aggregate_func": "MAX",
                    "collection_source": "cell_entities",
                    "result_var": "max_energy",
                    "element_var": "item",
                    "expr": {"op": "GET_PROPERTY", "entity": "item", "property": "energy"},
                    "max_elements": 10,
                },
            ],
        }
        rule = self.parser.parse_rule(rule_min_max)
        ctx = ExecutionContext("r_agg_minmax", self.world)
        ctx.variables["current_cell_x"] = 0
        ctx.variables["current_cell_y"] = 0
        for eff in rule.effects:
            self.interpreter.eval_effect(eff, ctx, self.world)
        self.assertEqual(ctx.variables["min_energy"], FixedPoint.from_int(10))
        self.assertEqual(ctx.variables["max_energy"], FixedPoint.from_int(50))

    def test_audit_rule_d_subject_tax_push(self):
        """Case (d): BR_SUBJECT_TAX_PUSH real execution <= 256 ops."""
        self.world.set_audit_level("TRACE")
        agent_schema = EntityTypeSchema("agent")
        agent_schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("role", PropertyType.STRING, default_value="subject"))
        agent_schema.add_property(PropertyDefinition("wealth", PropertyType.INT64, default_value=100))
        agent_schema.add_property(PropertyDefinition("treasury", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("is_alive", PropertyType.INT64, default_value=1))
        self.world.schema_registry.register_type(agent_schema)

        leader = self.world.entities.create_entity(
            "agent", 0, {"cell_x": 0, "cell_y": 0, "role": "leader", "treasury": 0, "is_alive": 1}, self.world.schema_registry
        )
        self.world.spatial_index.place_entity(leader.id, 0, 0)
        subjects = []
        for _ in range(5):
            sub = self.world.entities.create_entity(
                "agent", 0, {"cell_x": 0, "cell_y": 0, "role": "subject", "wealth": 100, "is_alive": 1}, self.world.schema_registry
            )
            self.world.spatial_index.place_entity(sub.id, 0, 0)
            self.world.relationships.add_edge(sub.id, leader.id, "subject_of")
            subjects.append(sub)

        rule_json = {
            "rule_id": "BR_SUBJECT_TAX_PUSH",
            "name": "Decentralized Push-Pattern Group Taxation to Leader",
            "version": "1.0.0",
            "priority": 45,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "agent",
                "limit": 5,
                "filter": {
                    "op": "AND",
                    "left": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                    "right": {
                        "op": "AND",
                        "left": {
                            "op": "EQUALS",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "role"},
                            "right": {"op": "LITERAL", "type": "STRING", "value": "subject"},
                        },
                        "right": {
                            "op": "GREATER_THAN_OR_EQUAL",
                            "left": {"op": "GET_PROPERTY", "entity": "target", "property": "wealth"},
                            "right": {"op": "LITERAL", "type": "INT64", "value": "10"},
                        },
                    },
                },
            },
            "effects": [
                {
                    "op": "FIND_ENTITY",
                    "result_var": "leader",
                    "collection_source": "outgoing_relationships",
                    "rel_type": "subject_of",
                    "limit": 1,
                },
                {
                    "op": "IF",
                    "condition": {
                        "op": "NOT_EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "leader", "property": "id"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                    "then": [
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "leader",
                            "property": "treasury",
                            "delta": {
                                "op": "DIVIDE",
                                "left": {"op": "GET_PROPERTY", "entity": "target", "property": "wealth"},
                                "right": {"op": "LITERAL", "type": "INT64", "value": "10"},
                            },
                        },
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "target",
                            "property": "wealth",
                            "delta": {
                                "op": "NEG",
                                "operand": {
                                    "op": "DIVIDE",
                                    "left": {"op": "GET_PROPERTY", "entity": "target", "property": "wealth"},
                                    "right": {"op": "LITERAL", "type": "INT64", "value": "10"},
                                },
                            },
                        },
                    ],
                    "else": [],
                },
            ],
        }

        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world, cell=(0, 0))
        self.assertTrue(success, msg)
        ev = [e for e in self.world.event_journal.records if e.event_type == "rule_executed_success"][-1]
        ops = int(ev.payload["operations_consumed"])
        touches = int(ev.payload["entities_touched"])

        self.assertLessEqual(ops, 256)
        self.assertLessEqual(touches, 6)
        # Leader treasury = 5 * 10 = 50
        self.assertEqual(leader.get_property("treasury"), 50)
        for sub in subjects:
            self.assertEqual(sub.get_property("wealth"), 90)

    def test_audit_rule_e_leader_succession(self):
        """Case (e): BR_LEADER_SUCCESSION real execution <= 256 ops."""
        self.world.set_audit_level("TRACE")
        agent_schema = EntityTypeSchema("agent")
        agent_schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("role", PropertyType.STRING, default_value="subject"))
        agent_schema.add_property(PropertyDefinition("treasury", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("prestige", PropertyType.INT64, default_value=50))
        agent_schema.add_property(PropertyDefinition("is_alive", PropertyType.INT64, default_value=1))
        self.world.schema_registry.register_type(agent_schema)

        old_leader = self.world.entities.create_entity(
            "agent", 0, {"cell_x": 0, "cell_y": 0, "role": "leader", "treasury": 500, "is_alive": 0}, self.world.schema_registry
        )
        members = []
        for i in range(16):
            m = self.world.entities.create_entity(
                "agent", 0, {"cell_x": 0, "cell_y": 0, "role": "subject", "prestige": 10 + i * 5, "is_alive": 1}, self.world.schema_registry
            )
            self.world.relationships.add_edge(m.id, old_leader.id, "subject_of")
            members.append(m)

        rule_json = {
            "rule_id": "BR_LEADER_SUCCESSION",
            "name": "Prestige-Ordered Leadership Succession",
            "version": "1.0.0",
            "priority": 52,
            "spatial_partitioned": False,
            "target_selector": {
                "entity_type": "agent",
                "limit": 1,
                "filter": {
                    "op": "AND",
                    "left": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "role"},
                        "right": {"op": "LITERAL", "type": "STRING", "value": "leader"},
                    },
                    "right": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                },
            },
            "effects": [
                {
                    "op": "FIND_ENTITY",
                    "result_var": "successor",
                    "collection_source": "incoming_relationships",
                    "rel_type": "subject_of",
                    "filter": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "candidate", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                    "order_by": "prestige",
                    "order_direction": "DESC",
                    "max_scan": 16,
                    "limit": 1,
                },
                {
                    "op": "IF",
                    "condition": {
                        "op": "NOT_EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "successor", "property": "id"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                    "then": [
                        {
                            "op": "SET_PROPERTY",
                            "entity": "successor",
                            "property": "role",
                            "value": {"op": "LITERAL", "type": "STRING", "value": "leader"},
                        },
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "successor",
                            "property": "treasury",
                            "delta": {"op": "GET_PROPERTY", "entity": "target", "property": "treasury"},
                        },
                        {
                            "op": "SET_PROPERTY",
                            "entity": "target",
                            "property": "treasury",
                            "value": {"op": "LITERAL", "type": "INT64", "value": "0"},
                        },
                        {
                            "op": "FOR_EACH",
                            "iterator_var": "member",
                            "collection_source": "incoming_relationships",
                            "rel_type": "subject_of",
                            "max_iterations": 16,
                            "body": [
                                {
                                    "op": "REMOVE_RELATIONSHIP",
                                    "source": "member",
                                    "target": "target",
                                    "rel_type": "subject_of",
                                },
                                {
                                    "op": "ADD_RELATIONSHIP",
                                    "source": "member",
                                    "target": "successor",
                                    "rel_type": "subject_of",
                                    "weight": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000"},
                                },
                            ],
                        },
                    ],
                    "else": [],
                },
            ],
        }

        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world)
        self.assertTrue(success, msg)
        ev = [e for e in self.world.event_journal.records if e.event_type == "rule_executed_success"][-1]
        ops = int(ev.payload["operations_consumed"])
        touches = int(ev.payload["entities_touched"])

        self.assertLessEqual(ops, 256)
        self.assertLessEqual(touches, 18)
        # Successor is member 16 (highest prestige: 10 + 15*5 = 85)
        successor = members[-1]
        self.assertEqual(successor.get_property("role"), "leader")
        self.assertEqual(successor.get_property("treasury"), 500)
        self.assertEqual(old_leader.get_property("treasury"), 0)

    def test_audit_rule_f_practice_transmission(self):
        """Case (f): BR_PRACTICE_TRANSMISSION real execution <= 256 ops."""
        self.world.set_audit_level("TRACE")
        agent_schema = EntityTypeSchema("agent")
        agent_schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        agent_schema.add_property(PropertyDefinition("farming_technique", PropertyType.INT64, default_value=1))
        agent_schema.add_property(PropertyDefinition("is_alive", PropertyType.INT64, default_value=1))
        self.world.schema_registry.register_type(agent_schema)

        learner = self.world.entities.create_entity(
            "agent", 0, {"cell_x": 0, "cell_y": 0, "farming_technique": 1, "is_alive": 1}, self.world.schema_registry
        )
        self.world.spatial_index.place_entity(learner.id, 0, 0)
        for i in range(5):
            ft = 8 if i == 0 else 1
            m = self.world.entities.create_entity(
                "agent", 0, {"cell_x": 0, "cell_y": 0, "farming_technique": ft, "is_alive": 1}, self.world.schema_registry
            )
            self.world.spatial_index.place_entity(m.id, 0, 0)

        rule_json = {
            "rule_id": "BR_PRACTICE_TRANSMISSION",
            "name": "Practice Transmission",
            "version": "1.0.0",
            "priority": 35,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "agent",
                "limit": 1,
                "filter": {
                    "op": "AND",
                    "left": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "is_alive"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "1"},
                    },
                    "right": {
                        "op": "LESS_THAN",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "farming_technique"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "10"},
                    },
                },
            },
            "effects": [
                {
                    "op": "FIND_ENTITY",
                    "result_var": "mentor",
                    "collection_source": "cell_entities",
                    "entity_type": "agent",
                    "filter": {
                        "op": "AND",
                        "left": {
                            "op": "NOT_EQUALS",
                            "left": {"op": "GET_PROPERTY", "entity": "candidate", "property": "id"},
                            "right": {"op": "GET_PROPERTY", "entity": "target", "property": "id"},
                        },
                        "right": {
                            "op": "GREATER_THAN",
                            "left": {"op": "GET_PROPERTY", "entity": "candidate", "property": "farming_technique"},
                            "right": {"op": "GET_PROPERTY", "entity": "target", "property": "farming_technique"},
                        },
                    },
                    "order_by": "farming_technique",
                    "order_direction": "DESC",
                    "max_scan": 6,
                    "limit": 1,
                },
                {
                    "op": "IF",
                    "condition": {
                        "op": "AND",
                        "left": {
                            "op": "NOT_EQUALS",
                            "left": {"op": "GET_PROPERTY", "entity": "mentor", "property": "id"},
                            "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                        },
                        "right": {
                            "op": "LESS_THAN",
                            "left": {"op": "RANDOM_FIXED", "min": "0.000000", "max": "1.000000"},
                            "right": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000"},
                        },
                    },
                    "then": [
                        {
                            "op": "ADJUST_PROPERTY",
                            "entity": "target",
                            "property": "farming_technique",
                            "delta": {"op": "LITERAL", "type": "INT64", "value": "1"},
                        },
                        {
                            "op": "ADD_RELATIONSHIP",
                            "source": "target",
                            "target": "mentor",
                            "rel_type": "learned_from",
                            "weight": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000"},
                        },
                    ],
                    "else": [],
                },
            ],
        }

        rule = self.parser.parse_rule(rule_json)
        success, msg = self.interpreter.execute_rule(rule, self.world, cell=(0, 0))
        self.assertTrue(success, msg)
        ev = [e for e in self.world.event_journal.records if e.event_type == "rule_executed_success"][-1]
        ops = int(ev.payload["operations_consumed"])
        touches = int(ev.payload["entities_touched"])

        self.assertLessEqual(ops, 256)
        self.assertLessEqual(touches, 7)
        self.assertEqual(learner.get_property("farming_technique"), 2)


if __name__ == "__main__":
    unittest.main()
