"""GENESIS Alpha — Phase 1 Mandatory Acceptance Tests.

Implements all 14 acceptance tests defined in the specification plus the
mandatory historical immutability test.
"""

from __future__ import annotations
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from genesis.core.arithmetic import FixedPoint, MAX_INT64
from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.core.errors import (
    ArithmeticRangeError,
    GRLStructuralValidationError,
    GRLValidationError,
    PropertySchemaValidationError,
    PropertyValueOutOfBoundsError,
    QuotaExceededError,
)
from genesis.grl.ast import (
    AdjustPropertyNode,
    BinaryOpNode,
    ConsumeResourceNode,
    ForEachNode,
    GetPropertyNode,
    GetResourceNode,
    LiteralNode,
    RuleDefinition,
    SetPropertyNode,
    TargetSelector,
)
from genesis.grl.interpreter import GRLInterpreter
from genesis.grl.parser import GRLParser
from genesis.grl.registry import RuleRegistry
from genesis.grl.validator import GRLValidator
from genesis.persistence.canonical import canonical_json_bytes
from genesis.persistence.hasher import compute_canonical_hash, compute_file_hash
from genesis.persistence.snapshot import SnapshotManager
from genesis.substrate.entities import EntityStorage
from genesis.substrate.properties import (
    EntityTypeSchema,
    PropertyDefinition,
    PropertyType,
    SchemaRegistry,
)
from genesis.substrate.world_state import WorldState


class TestPhase1Acceptance(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.snapshot_mgr = SnapshotManager(base_dir=os.path.join(self.temp_dir, "snapshots"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Acceptance Test 1: Create an entity type not hardcoded in the application
    # -------------------------------------------------------------------------
    def test_01_create_entity_type_not_hardcoded(self):
        world = WorldState(seed=42)
        # Verify 'crystal_formation' does not exist anywhere in runtime hardcoded types
        self.assertFalse(world.schema_registry.has_type("crystal_formation"))

        # Dynamically register new entity type
        schema = EntityTypeSchema("crystal_formation")
        schema.add_property(PropertyDefinition("resonance", PropertyType.FIXED_POINT))
        world.schema_registry.register_type(schema)

        # Instantiate two entities
        e1 = world.entities.create_entity("crystal_formation", world.clock.current_tick, {"resonance": "100.0"}, world.schema_registry)
        e2 = world.entities.create_entity("crystal_formation", world.clock.current_tick, {"resonance": "200.0"}, world.schema_registry)

        self.assertEqual(e1.id, 1)
        self.assertEqual(e2.id, 2)
        self.assertEqual(e1.entity_type, "crystal_formation")
        self.assertEqual(e2.entity_type, "crystal_formation")

        # Query by type returns entities sorted by ID
        queried = world.entities.get_entities_by_type("crystal_formation")
        self.assertEqual(len(queried), 2)
        self.assertEqual([e.id for e in queried], [1, 2])

    # -------------------------------------------------------------------------
    # Acceptance Test 2: Add dynamically defined properties
    # -------------------------------------------------------------------------
    def test_02_add_dynamically_defined_properties(self):
        world = WorldState(seed=42)
        schema = EntityTypeSchema("organism")
        schema.add_property(PropertyDefinition("hydration", PropertyType.FIXED_POINT, min_value=0, max_value=FixedPoint.from_int(100)))
        schema.add_property(PropertyDefinition("generation", PropertyType.INT64, min_value=0, max_value=1000))
        schema.add_property(PropertyDefinition("is_dormant", PropertyType.BOOLEAN, default_value=False))
        schema.add_property(PropertyDefinition("trophic_mode", PropertyType.ENUM, allowed_variants=["autotroph", "heterotroph"]))
        world.schema_registry.register_type(schema)

        # Valid instantiation
        ent = world.entities.create_entity(
            "organism",
            0,
            {
                "hydration": "50.0",
                "generation": 1,
                "is_dormant": False,
                "trophic_mode": "autotroph",
            },
            world.schema_registry,
        )
        self.assertEqual(ent.get_property("hydration"), FixedPoint.from_int(50))
        self.assertEqual(ent.get_property("generation"), 1)
        self.assertEqual(ent.get_property("is_dormant"), False)
        self.assertEqual(ent.get_property("trophic_mode"), "autotroph")

        # Bounds violation: hydration > 100
        with self.assertRaises(PropertyValueOutOfBoundsError):
            schema.validate_property("hydration", FixedPoint.from_int(150))

        # Enum variant violation
        with self.assertRaises(PropertySchemaValidationError):
            schema.validate_property("trophic_mode", "carnivore_dragon")

    # -------------------------------------------------------------------------
    # Acceptance Test 3: Create relationships between entities
    # -------------------------------------------------------------------------
    def test_03_create_relationships_between_entities(self):
        world = WorldState(seed=42)
        e1 = world.entities.create_entity("generic", 0)
        e2 = world.entities.create_entity("generic", 0)

        world.relationships.add_edge(e1.id, e2.id, "symbiont_with", weight=FixedPoint.from_decimal_string("0.750000"))
        self.assertTrue(world.relationships.has_edge(e1.id, e2.id, "symbiont_with"))

        edge = world.relationships.get_edge(e1.id, e2.id, "symbiont_with")
        self.assertIsNotNone(edge)
        self.assertEqual(edge.weight.to_decimal_string(), "0.750000")

        # Outgoing query sorted by target_id
        outgoing = world.relationships.get_outgoing(e1.id)
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0].target_id, e2.id)

        # Removal
        removed = world.relationships.remove_edge(e1.id, e2.id, "symbiont_with")
        self.assertTrue(removed)
        self.assertFalse(world.relationships.has_edge(e1.id, e2.id, "symbiont_with"))

    # -------------------------------------------------------------------------
    # Acceptance Test 4: Execute a valid GRL rule
    # -------------------------------------------------------------------------
    def test_04_execute_valid_grl_rule(self):
        world = WorldState(seed=42)
        world.resources.create_pool("soil_moisture", initial_balance=FixedPoint.from_int(1000))

        schema = EntityTypeSchema("plant")
        schema.add_property(PropertyDefinition("hydration", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(10)))
        world.schema_registry.register_type(schema)

        plant = world.entities.create_entity("plant", 0, {"hydration": "10.0"}, world.schema_registry)

        rule_dict = {
            "rule_id": "rule_absorb_moisture",
            "name": "Absorb Moisture",
            "version": "1.0.0",
            "priority": 50,
            "target_selector": {
                "entity_type": "plant",
                "limit": 10,
            },
            "preconditions": [
                {
                    "op": "GREATER_THAN_OR_EQUAL",
                    "left": {"op": "GET_RESOURCE", "pool": "soil_moisture"},
                    "right": {"op": "LITERAL", "type": "FIXED_POINT", "value": "5000000"},
                }
            ],
            "effects": [
                {
                    "op": "CONSUME_RESOURCE",
                    "pool": "soil_moisture",
                    "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "5000000"},
                },
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "hydration",
                    "delta": {"op": "LITERAL", "type": "FIXED_POINT", "value": "5000000"},
                },
            ],
        }

        parser = GRLParser()
        rule = parser.parse_rule(rule_dict)
        interpreter = GRLInterpreter()

        success, msg = interpreter.execute_rule(rule, world)
        self.assertTrue(success)

        # Hydration increased by 5.0 (from 10.0 to 15.0)
        self.assertEqual(plant.get_property("hydration").to_decimal_string(), "15.000000")
        # Soil moisture reduced by 5.0 (from 1000.0 to 995.0)
        self.assertEqual(world.resources.get_pool("soil_moisture").balance.to_decimal_string(), "995.000000")

    # -------------------------------------------------------------------------
    # Acceptance Test 5: Reject syntactically invalid GRL
    # -------------------------------------------------------------------------
    def test_05_reject_syntactically_invalid_grl(self):
        parser = GRLParser()

        # Missing required field
        with self.assertRaises(GRLValidationError):
            parser.parse_rule({"name": "No Rule ID", "version": "1.0"})

        # Unknown operator
        with self.assertRaises(GRLValidationError):
            parser.parse_expression({"op": "MAGIC_TRANSMUTE", "val": 42})

        # Non-dictionary input
        with self.assertRaises(GRLValidationError):
            parser.parse_rule("not a json dict")

    # -------------------------------------------------------------------------
    # Acceptance Test 6: Reject a rule exceeding 256 operations
    # -------------------------------------------------------------------------
    def test_06_reject_rule_exceeding_256_operations(self):
        world = WorldState(seed=42)
        schema = EntityTypeSchema("item")
        schema.add_property(PropertyDefinition("counter", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema)

        # Create 150 items
        for _ in range(150):
            world.entities.create_entity("item", 0, {"counter": 0}, world.schema_registry)

        # Target selector evaluates across 150 items with filter and effect:
        # Each item takes at least 3 operations: entity fetch, compare, and adjust.
        # 150 * 3 = 450 ops > 256 limit.
        rule_dict = {
            "rule_id": "rule_heavy_loop",
            "name": "Heavy Operations Rule",
            "version": "1.0.0",
            "target_selector": {
                "entity_type": "item",
                "filter": {
                    "op": "EQUALS",
                    "left": {"op": "GET_PROPERTY", "entity": "target", "property": "counter"},
                    "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                },
                "limit": 150,
            },
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "counter",
                    "delta": {"op": "LITERAL", "type": "INT64", "value": "1"},
                }
            ],
        }

        parser = GRLParser()
        rule = parser.parse_rule(rule_dict)
        interpreter = GRLInterpreter()

        success, msg = interpreter.execute_rule(rule, world)
        # Must fail and trigger single-rule rollback
        self.assertFalse(success)
        self.assertIn("QuotaExceededError", msg)

        # Verify rollback: counter must still be 0 for all items!
        for ent in world.entities.get_entities_by_type("item"):
            self.assertEqual(ent.get_property("counter"), 0)

    # -------------------------------------------------------------------------
    # Acceptance Test 7: Reject loop nesting beyond depth 4
    # -------------------------------------------------------------------------
    def test_07_reject_loop_nesting_beyond_depth_4(self):
        validator = GRLValidator()

        # Depth 4 nested loops (permitted)
        loop4 = ForEachNode("a", "coll", body=[
            ForEachNode("b", "coll", body=[
                ForEachNode("c", "coll", body=[
                    ForEachNode("d", "coll", body=[])
                ])
            ])
        ])
        rule_valid = RuleDefinition(rule_id="r4", name="r4", version="1.0", effects=[loop4])
        validator.validate_rule(rule_valid)  # Passes without error

        # Depth 5 nested loops (rejected)
        loop5 = ForEachNode("a", "coll", body=[
            ForEachNode("b", "coll", body=[
                ForEachNode("c", "coll", body=[
                    ForEachNode("d", "coll", body=[
                        ForEachNode("e", "coll", body=[])
                    ])
                ])
            ])
        ])
        rule_invalid = RuleDefinition(rule_id="r5", name="r5", version="1.0", effects=[loop5])
        with self.assertRaises(GRLStructuralValidationError):
            validator.validate_rule(rule_invalid)

    # -------------------------------------------------------------------------
    # Acceptance Test 8: Reject recursion
    # -------------------------------------------------------------------------
    def test_08_reject_recursion(self):
        # Verify parser rejects recursion operators
        parser = GRLParser()
        with self.assertRaises(GRLValidationError):
            parser.parse_effect({"op": "INVOKE_RULE", "rule_id": "self"})

        with self.assertRaises(GRLValidationError):
            parser.parse_effect({"op": "RECURSE", "args": []})

    # -------------------------------------------------------------------------
    # Acceptance Test 9: Reject a rule exceeding 1,000 touched entities per tick
    # -------------------------------------------------------------------------
    def test_09_reject_exceeding_1000_touched_entities(self):
        world = WorldState(seed=42)
        schema = EntityTypeSchema("particle")
        schema.add_property(PropertyDefinition("charge", PropertyType.INT64, default_value=1))
        world.schema_registry.register_type(schema)

        # Create 1,050 entities
        for _ in range(1050):
            world.entities.create_entity("particle", 0, {"charge": 1}, world.schema_registry)

        rule_dict = {
            "rule_id": "rule_touch_all",
            "name": "Touch All Particles",
            "version": "1.0.0",
            "target_selector": {
                "entity_type": "particle",
                "filter": {
                    "op": "EQUALS",
                    "left": {"op": "GET_PROPERTY", "entity": "target", "property": "charge"},
                    "right": {"op": "LITERAL", "type": "INT64", "value": "9999"},
                },
                "limit": 1000,
            },
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "charge",
                    "delta": {"op": "LITERAL", "type": "INT64", "value": "1"},
                }
            ],
        }

        # To specifically test the 1000 touched entities limit before 256 ops triggers:
        # Configure a test config with high operations but strict 1000 entity touch limit
        custom_config = RuntimeConfig(max_operations_per_rule=10000, max_entities_touched_per_tick=1000)
        rule = GRLParser().parse_rule(rule_dict)
        interpreter = GRLInterpreter(config=custom_config)

        success, msg = interpreter.execute_rule(rule, world)
        self.assertFalse(success)
        self.assertIn("max_entities_touched_per_tick", msg)

        # Verify rollback: all entities still have charge 1
        for p in world.entities.get_entities_by_type("particle"):
            self.assertEqual(p.get_property("charge"), 1)

    # -------------------------------------------------------------------------
    # Acceptance Test 10: Save and reload simulation state
    # -------------------------------------------------------------------------
    def test_10_save_and_reload_state(self):
        world = WorldState(seed=12345)
        world.resources.create_pool("energy", initial_balance=FixedPoint.from_int(500))
        schema = EntityTypeSchema("agent")
        schema.add_property(PropertyDefinition("vitality", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
        world.schema_registry.register_type(schema)

        for _ in range(5):
            world.entities.create_entity("agent", 0, {"vitality": "75.5"}, world.schema_registry)

        # Advance 20 ticks
        for _ in range(20):
            world.advance_tick()

        # Save snapshot
        filepath, original_hash = self.snapshot_mgr.save_snapshot(world, "snapshot_test_10.json")

        # Reload into new WorldState instance
        reloaded_world = self.snapshot_mgr.load_snapshot(filepath)

        self.assertEqual(reloaded_world.clock.current_tick, 20)
        self.assertEqual(reloaded_world.entities.count(), 5)
        self.assertEqual(reloaded_world.resources.get_pool("energy").balance, FixedPoint.from_int(500))

        # Re-save reloaded state and compare canonical byte hash
        _, reloaded_hash = self.snapshot_mgr.save_snapshot(reloaded_world, "snapshot_test_10_reloaded.json")
        self.assertEqual(original_hash, reloaded_hash)

    # -------------------------------------------------------------------------
    # Acceptance Test 11: Reproduce an identical run from the same seed
    # -------------------------------------------------------------------------
    def test_11_reproduce_identical_run_from_same_seed(self):
        def run_sim(seed: int) -> list:
            world = WorldState(seed=seed)
            world.resources.create_pool("minerals", initial_balance=FixedPoint.from_int(1000))
            schema = EntityTypeSchema("node")
            schema.add_property(PropertyDefinition("val", PropertyType.INT64))
            world.schema_registry.register_type(schema)

            for i in range(10):
                world.entities.create_entity("node", 0, {"val": i}, world.schema_registry)

            tick_states = []
            for _ in range(100):
                # Pseudo-random choice and step
                roll = world.rng.next_int_range(1, 10)
                world.resources.get_pool("minerals").produce(FixedPoint.from_int(roll))
                world.advance_tick()
                tick_states.append((world.clock.current_tick, world.resources.get_pool("minerals").balance.raw_value))
            return tick_states

        run1 = run_sim(seed=42)
        run2 = run_sim(seed=42)
        self.assertEqual(run1, run2)

    # -------------------------------------------------------------------------
    # Acceptance Test 12: Match full-state SHA-256 hashes across two independent runs
    # -------------------------------------------------------------------------
    def test_12_match_full_state_sha256_across_runs(self):
        def execute_simulation(seed: int) -> tuple[str, str]:
            world = WorldState(seed=seed)
            world.resources.create_pool("water", initial_balance=FixedPoint.from_int(1000))
            schema = EntityTypeSchema("cell")
            schema.add_property(PropertyDefinition("active", PropertyType.BOOLEAN, default_value=True))
            world.schema_registry.register_type(schema)

            for _ in range(20):
                world.entities.create_entity("cell", 0, {"active": True}, world.schema_registry)

            for _ in range(100):
                world.advance_tick()

            state_hash = compute_canonical_hash(world.to_canonical_dict())
            journal_hash = world.event_journal.last_hash
            return state_hash, journal_hash

        state_hash_1, journal_hash_1 = execute_simulation(seed=9999)
        state_hash_2, journal_hash_2 = execute_simulation(seed=9999)

        self.assertEqual(state_hash_1, state_hash_2)
        self.assertEqual(journal_hash_1, journal_hash_2)

    # -------------------------------------------------------------------------
    # Acceptance Test 13: Verify RNG state persists correctly across save and reload
    # -------------------------------------------------------------------------
    def test_13_verify_rng_state_persists_across_save_reload(self):
        # 1. Uninterrupted continuous run 0 -> 100 ticks
        w_cont = WorldState(seed=777)
        for _ in range(100):
            # Consume random steps
            w_cont.rng.next_uint64()
            w_cont.advance_tick()
        cont_hash = compute_canonical_hash(w_cont.to_canonical_dict())

        # 2. Interrupted run 0 -> 50 ticks, snapshot, reload, 50 -> 100 ticks
        w_split = WorldState(seed=777)
        for _ in range(50):
            w_split.rng.next_uint64()
            w_split.advance_tick()

        snap_path, _ = self.snapshot_mgr.save_snapshot(w_split, "snap_split_50.json")

        w_reloaded = self.snapshot_mgr.load_snapshot(snap_path)
        for _ in range(50):
            w_reloaded.rng.next_uint64()
            w_reloaded.advance_tick()
        split_hash = compute_canonical_hash(w_reloaded.to_canonical_dict())

        self.assertEqual(cont_hash, split_hash)

    # -------------------------------------------------------------------------
    # Acceptance Test 14: Verify GENESIS cannot modify the runtime (Boundaries)
    # -------------------------------------------------------------------------
    def test_14_verify_cannot_modify_runtime(self):
        world = WorldState(seed=42)
        schema = EntityTypeSchema("sandboxed_entity")
        schema.add_property(PropertyDefinition("meta", PropertyType.STRING))
        schema.add_property(PropertyDefinition("amount", PropertyType.INT64))
        world.schema_registry.register_type(schema)

        # 1. Path traversal injection attempt in property
        with self.assertRaises(PropertySchemaValidationError):
            schema.validate_property("meta", "../../genesis/core/config.py")

        with self.assertRaises(PropertySchemaValidationError):
            schema.validate_property("meta", "C:\\Windows\\System32")

        # 2. Integer overflow attempt beyond int64 max (2^63 - 1)
        with self.assertRaises(ArithmeticRangeError):
            schema.validate_property("amount", MAX_INT64 + 1)

        # 3. Limit tampering payload via GRL AST
        parser = GRLParser()
        with self.assertRaises(GRLValidationError):
            parser.parse_rule({
                "rule_id": "escape_rule",
                "name": "Tamper Limits",
                "version": "1.0",
                "effects": [
                    {"op": "SET_CONFIG", "key": "max_operations_per_rule", "value": 999999}
                ]
            })

        # 4. Attempt code execution in rule
        with self.assertRaises(GRLValidationError):
            parser.parse_rule({
                "rule_id": "exec_rule",
                "name": "Exec Code",
                "version": "1.0",
                "effects": [
                    {"op": "EXEC_PYTHON", "code": "__import__('os').system('dir')"}
                ]
            })

        # 5. Direct config object immutability check
        with self.assertRaises(Exception):  # FrozenInstanceError on dataclass
            DEFAULT_CONFIG.max_operations_per_rule = 999999

    # -------------------------------------------------------------------------
    # Historical Immutability Test (Mandatory)
    # -------------------------------------------------------------------------
    def test_15_historical_immutability(self):
        world = WorldState(seed=555)
        world.resources.create_pool("biomass", initial_balance=FixedPoint.from_int(100))
        registry = RuleRegistry()
        world.rule_engine_callback = registry.execute_active_rules

        # Run to tick T = 50
        for _ in range(50):
            world.advance_tick()

        # Compute hash of event history through tick 50
        history_hash_at_50 = world.event_journal.hash_through_tick(50)
        snap_path_50, snap_hash_at_50 = self.snapshot_mgr.save_snapshot(world, "snapshot_tick_50.json")

        # Install a new GRL rule at tick 50 (effective at tick 51 prospectively)
        rule_dict = {
            "rule_id": "rule_growth_at_51",
            "name": "Growth after tick 50",
            "version": "1.0.0",
            "priority": 10,
            "effects": [
                {
                    "op": "PRODUCE_RESOURCE",
                    "pool": "biomass",
                    "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "1000000"},
                }
            ],
        }
        rule = GRLParser().parse_rule(rule_dict)
        registry.register_rule(rule, current_tick=world.clock.current_tick)
        self.assertEqual(rule.active_from_tick, 51)

        # Advance to tick 100 with the new rule actively running
        for _ in range(50):
            world.advance_tick()

        self.assertEqual(world.clock.current_tick, 100)

        # Assert 1: Event history through tick 50 is identical
        history_hash_recomputed = world.event_journal.hash_through_tick(50)
        self.assertEqual(history_hash_at_50, history_hash_recomputed)

        # Assert 2: Snapshot at tick 50 file hash is identical
        snap_hash_rechecked = compute_file_hash(snap_path_50)
        self.assertEqual(snap_hash_at_50, snap_hash_rechecked)


if __name__ == "__main__":
    unittest.main()
