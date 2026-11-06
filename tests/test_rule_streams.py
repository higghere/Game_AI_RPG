"""Tests for GENESIS Option C Deterministic Per-Invocation Rule Random Streams."""

import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

from genesis.core.arithmetic import FixedPoint
from genesis.core.errors import DivisionByZeroError, GRLExecutionError, QuotaExceededError, SerializationError
from genesis.core.rng import (
    FALLBACK_RNG_STATE,
    GLOBAL_RULE_CELL_SENTINEL,
    RULE_STREAM_DOMAIN_TAG,
    GenesisRNG,
    derive_rule_stream,
    serialize_rule_stream_payload,
)
from genesis.grl.ast import (
    AdjustPropertyNode,
    BinaryOpNode,
    CreateEntityNode,
    DestroyEntityNode,
    IfNode,
    LiteralNode,
    RandomFixedNode,
    RandomIntNode,
    RuleDefinition,
    SetPropertyNode,
)
from genesis.grl.interpreter import ExecutionContext, GRLInterpreter
from genesis.grl.parser import GRLParser
from genesis.grl.registry import RuleRegistry
from genesis.persistence.hasher import compute_canonical_hash
from genesis.persistence.snapshot import SnapshotManager
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.world_state import WorldState


# -----------------------------------------------------------------------------
# Committed Golden Vectors for Stream Derivation (Cross-Platform Invariant Contract)
# Generated deterministically using SHA-256 and pure integer xoshiro256**
# -----------------------------------------------------------------------------
GOLDEN_VECTORS = [
    # Vector 1: Standard spatial rule invocation at origin
    {
        "world_seed": 42,
        "tick": 0,
        "rule_id": "rule_basic",
        "cell": (0, 0),
        "invocation_index": 0,
        "expected_first_4": [
            "0xdf4db889f179f0ff",
            "0x547d188b5dfafc42",
            "0x2ad203e5a9c26a64",
            "0x58f29d904ba48089",
        ],
    },
    # Vector 2: Spatial rule with negative coordinate and non-zero tick
    {
        "world_seed": 123456789,
        "tick": 100,
        "rule_id": "BR_06_REPRODUCTION",
        "cell": (5, -3),
        "invocation_index": 0,
        "expected_first_4": [
            "0x93efc463273a2855",
            "0x77cfd35055f6f7ee",
            "0x16212c645122674e",
            "0x5d98d4e9cb6e0f7f",
        ],
    },
    # Vector 3: Non-spatial global rule with cell=None (sentinel pair)
    {
        "world_seed": 20261106,
        "tick": 365,
        "rule_id": "BR_LEADER_SUCCESSION",
        "cell": None,
        "invocation_index": 0,
        "expected_first_4": [
            "0xe9e3d0a32bb09e6e",
            "0x3547e4c072e0a1e4",
            "0x06fe93a863987105",
            "0x93b0b8cacf906e63",
        ],
    },
    # Vector 4: Non-ASCII UTF-8 rule_id with non-zero invocation_index
    {
        "world_seed": 987654321098765,
        "tick": 42,
        "rule_id": "RüLe_ünîcødé_π",
        "cell": (12, 34),
        "invocation_index": 1,
        "expected_first_4": [
            "0x843da1dd5911e091",
            "0x4d7d272d568efbc5",
            "0x6cb938e822e22449",
            "0x549c35c87331101e",
        ],
    },
    # Vector 5: Edge-case maximum uint64 seed and multiple earlier invocations
    {
        "world_seed": 0xFFFFFFFFFFFFFFFF,
        "tick": 1000,
        "rule_id": "edge_case_max",
        "cell": (-1, 1),
        "invocation_index": 5,
        "expected_first_4": [
            "0x6e76b04132d1b6ba",
            "0x1c4bc2887c8e4cc2",
            "0x7da067e69500362e",
            "0x7da96106d2a58c6c",
        ],
    },
]


class TestRuleStreams(unittest.TestCase):
    """Test suite for Option C per-invocation random streams."""

    def setUp(self) -> None:
        self.parser = GRLParser()
        self.interpreter = GRLInterpreter()

    def _setup_organism_world(self, seed: int = 42) -> WorldState:
        """Helper to create a standard test world with organism schema and pools."""
        temp_dir = tempfile.mkdtemp()
        world = WorldState(seed=seed, journal_dir=Path(temp_dir) / "journal")
        schema = EntityTypeSchema("organism")
        schema.add_property(PropertyDefinition("energy", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
        schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("generation", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema)
        return world

    # -------------------------------------------------------------------------
    # 1. Derivation Golden Vectors
    # -------------------------------------------------------------------------
    def test_derivation_golden_vectors(self):
        """Assert exact first 4 uint64 outputs of the 5 committed golden vectors."""
        for idx, gv in enumerate(GOLDEN_VECTORS, start=1):
            stream = derive_rule_stream(
                world_seed=gv["world_seed"],
                tick=gv["tick"],
                rule_id=gv["rule_id"],
                cell=gv["cell"],
                invocation_index=gv["invocation_index"],
            )
            outputs = [stream.next_uint64() for _ in range(4)]
            hex_outputs = [f"0x{out:016x}" for out in outputs]
            self.assertEqual(
                hex_outputs,
                gv["expected_first_4"],
                f"Golden vector {idx} drifted! Expected {gv['expected_first_4']}, got {hex_outputs}",
            )

    def test_derivation_all_zero_digest_fallback(self):
        """Assert that if a digest produces all zero words, it falls back to FALLBACK_RNG_STATE."""
        rng = GenesisRNG.from_state(0, 0, 0, 0, initial_seed=42)
        self.assertEqual(rng._s, FALLBACK_RNG_STATE)
        val = rng.next_uint64()
        self.assertIsInstance(val, int)
        self.assertNotEqual(val, 0)

    # -------------------------------------------------------------------------
    # 2. Input Sensitivity
    # -------------------------------------------------------------------------
    def test_input_sensitivity_every_field_changes_stream(self):
        """Assert changing any single input field produces a distinct PRNG stream."""
        base = {
            "world_seed": 100,
            "tick": 10,
            "rule_id": "rule_test",
            "cell": (1, 2),
            "invocation_index": 0,
        }
        base_stream = derive_rule_stream(**base)
        base_first = base_stream.next_uint64()

        variations = [
            ("world_seed", {**base, "world_seed": 101}),
            ("tick", {**base, "tick": 11}),
            ("rule_id", {**base, "rule_id": "rule_test_2"}),
            ("cell_x", {**base, "cell": (2, 2)}),
            ("cell_y", {**base, "cell": (1, 3)}),
            ("cell_none", {**base, "cell": None}),
            ("invocation_index", {**base, "invocation_index": 1}),
        ]

        for name, var_kwargs in variations:
            var_stream = derive_rule_stream(**var_kwargs)
            var_first = var_stream.next_uint64()
            self.assertNotEqual(
                base_first,
                var_first,
                f"Field variation '{name}' produced identical first random draw as base!",
            )

    def test_byte_boundary_concatenation_ambiguity(self):
        """Assert that length-prefixed strings prevent concatenation ambiguities (e.g. 'ab'+'c' vs 'a'+'bc')."""
        payload_1 = serialize_rule_stream_payload(
            world_seed=42, tick=0, rule_id="ab", cell=(1, 2), invocation_index=0
        )
        payload_2 = serialize_rule_stream_payload(
            world_seed=42, tick=0, rule_id="abc", cell=(1, 2), invocation_index=0
        )
        # Length prefixes differ
        self.assertNotEqual(payload_1, payload_2)
        stream_1 = derive_rule_stream(42, 0, "ab", (1, 2), 0)
        stream_2 = derive_rule_stream(42, 0, "abc", (1, 2), 0)
        self.assertNotEqual(stream_1.next_uint64(), stream_2.next_uint64())

    # -------------------------------------------------------------------------
    # 3. Failed Rule Leaves Main RNG Untouched
    # -------------------------------------------------------------------------
    def test_failed_rule_leaves_main_rng_untouched(self):
        """A rule that draws random numbers and fails must leave world.rng and state hash identical."""
        world = self._setup_organism_world(seed=777)
        ent = world.entities.create_entity(
            "organism", 0, {"energy": FixedPoint.from_int(100), "cell_x": 0, "cell_y": 0}, world.schema_registry
        )
        world.spatial_index.place_entity(ent.id, 0, 0)

        initial_rng_state = copy.deepcopy(world.rng.get_state())
        initial_step_count = world.rng.step_count
        initial_hash = world.compute_substrate_hash()

        # Rule draws multiple random numbers, creates an entity, and then divides by zero
        rule_dict = {
            "rule_id": "r_failing_random",
            "name": "Failing Random Rule",
            "version": "1.0",
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
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
                # Second random draw
                {
                    "op": "SET_PROPERTY",
                    "entity": "child",
                    "property": "generation",
                    "value": {"op": "RANDOM_INT", "min": "1", "max": "100"},
                },
                # Division by zero failure
                {
                    "op": "SET_PROPERTY",
                    "entity": "child",
                    "property": "generation",
                    "value": {
                        "op": "DIVIDE",
                        "left": {"op": "LITERAL", "type": "INT64", "value": "10"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                },
            ],
        }

        rule = self.parser.parse_rule(rule_dict)
        success, msg = self.interpreter.execute_rule(rule, world, cell=(0, 0))

        self.assertFalse(success)
        self.assertIn("DivisionByZeroError", msg)

        # 1. world.rng must NOT have advanced at all
        self.assertEqual(world.rng.step_count, initial_step_count)
        self.assertEqual(world.rng.get_state(), initial_rng_state)

        # 2. Substrate state hash must be bit-identical
        self.assertEqual(
            world.compute_substrate_hash(),
            initial_hash,
            "Substrate state hash changed after failed rule execution!",
        )

    # -------------------------------------------------------------------------
    # 4. Successful Rule Leaves Main RNG Untouched
    # -------------------------------------------------------------------------
    def test_successful_rule_leaves_main_rng_untouched(self):
        """A rule that draws random numbers and succeeds commits its properties but leaves world.rng untouched."""
        world = self._setup_organism_world(seed=888)
        ent = world.entities.create_entity(
            "organism", 0, {"energy": FixedPoint.from_int(100), "cell_x": 0, "cell_y": 0}, world.schema_registry
        )
        world.spatial_index.place_entity(ent.id, 0, 0)

        initial_rng_state = copy.deepcopy(world.rng.get_state())
        initial_step_count = world.rng.step_count

        rule_dict = {
            "rule_id": "r_success_random",
            "name": "Success Random Rule",
            "version": "1.0",
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
                {
                    "op": "SET_PROPERTY",
                    "entity": "target",
                    "property": "generation",
                    "value": {"op": "RANDOM_INT", "min": "5", "max": "15"},
                },
                {
                    "op": "SET_PROPERTY",
                    "entity": "target",
                    "property": "energy",
                    "value": {
                        "op": "RANDOM_FIXED",
                        "min": "50.000000",
                        "max": "60.000000",
                    },
                },
            ],
        }

        rule = self.parser.parse_rule(rule_dict)
        success, msg = self.interpreter.execute_rule(rule, world, cell=(0, 0))

        self.assertTrue(success)
        self.assertEqual(msg, "Executed successfully")

        # Entity properties were updated
        self.assertTrue(5 <= ent.get_property("generation") <= 15)
        self.assertTrue(
            FixedPoint.from_decimal_string("50.000000")
            <= ent.get_property("energy")
            <= FixedPoint.from_decimal_string("60.000000")
        )

        # world.rng step_count must NOT advance at all
        self.assertEqual(world.rng.step_count, initial_step_count)
        self.assertEqual(world.rng.get_state(), initial_rng_state)

    # -------------------------------------------------------------------------
    # 5. No Stuck Rule (Advance Tick, Draws Differ Across Ticks)
    # -------------------------------------------------------------------------
    def test_no_stuck_rule_across_ticks(self):
        """Rule fails when random draw <= 5 and succeeds when > 5.

        Stated parameters in advance: world_seed = 42, N = 20 ticks.
        Assert draws differ across ticks, and over 20 ticks it both succeeds and fails.
        """
        world = self._setup_organism_world(seed=42)
        ent = world.entities.create_entity(
            "organism", 0, {"energy": FixedPoint.from_int(100), "cell_x": 0, "cell_y": 0, "generation": 0}, world.schema_registry
        )
        world.spatial_index.place_entity(ent.id, 0, 0)

        rule_dict = {
            "rule_id": "r_threshold_rule",
            "name": "Threshold Rule",
            "version": "1.0",
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
                {
                    "op": "SET_PROPERTY",
                    "entity": "target",
                    "property": "generation",
                    "value": {"op": "RANDOM_INT", "min": "1", "max": "10"},
                },
                # Division by zero if generation <= 5 (fail), else succeed
                {
                    "op": "IF",
                    "condition": {
                        "op": "LESS_THAN_OR_EQUAL",
                        "left": {
                            "op": "GET_PROPERTY",
                            "entity": "target",
                            "property": "generation",
                        },
                        "right": {"op": "LITERAL", "type": "INT64", "value": "5"},
                    },
                    "then": [
                        {
                            "op": "SET_PROPERTY",
                            "entity": "target",
                            "property": "generation",
                            "value": {
                                "op": "DIVIDE",
                                "left": {"op": "LITERAL", "type": "INT64", "value": "1"},
                                "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                            },
                        }
                    ],
                    "else": [],
                },
            ],
        }

        rule = self.parser.parse_rule(rule_dict)

        success_count = 0
        failure_count = 0
        draws_observed = []

        for _ in range(20):
            # Inspect what draw this invocation will produce
            inv_idx = world.get_and_increment_rule_invocation_count(rule.rule_id, (0, 0))
            # Reset the count so execute_rule gets 0
            world._rule_invocation_counts.clear()

            test_stream = derive_rule_stream(world.world_seed, world.clock.current_tick, rule.rule_id, (0, 0), 0)
            expected_draw = test_stream.next_int_range(1, 10)
            draws_observed.append(expected_draw)

            success, msg = self.interpreter.execute_rule(rule, world, cell=(0, 0))
            if success:
                success_count += 1
                self.assertGreater(ent.get_property("generation"), 5)
            else:
                failure_count += 1
                self.assertIn("DivisionByZeroError", msg)

            world.advance_tick()

        # Draws must not all be identical
        self.assertGreater(len(set(draws_observed)), 1, "Draws across ticks were identical (stuck stream)!")
        # Over N=20 ticks, both outcomes must have occurred
        self.assertGreater(success_count, 0, "Rule never succeeded across 20 ticks!")
        self.assertGreater(failure_count, 0, "Rule never failed across 20 ticks!")

    # -------------------------------------------------------------------------
    # 6. Order Independence
    # -------------------------------------------------------------------------
    def test_order_independence_across_rules_and_shuffles(self):
        """Target rule's random draws depend only on its own inputs, not on other rules or cell shuffle order."""
        target_rule_dict = {
            "rule_id": "r_target",
            "name": "Target Rule",
            "version": "1.0",
            "spatial_partitioned": True,
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
                {
                    "op": "SET_PROPERTY",
                    "entity": "target",
                    "property": "generation",
                    "value": {"op": "RANDOM_INT", "min": "100", "max": "999"},
                }
            ],
        }
        target_rule = self.parser.parse_rule(target_rule_dict)

        unrelated_rule_dict = {
            "rule_id": "r_unrelated",
            "name": "Unrelated Rule",
            "version": "1.0",
            "priority": 10,  # runs earlier
            "spatial_partitioned": True,
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
                {
                    "op": "SET_PROPERTY",
                    "entity": "target",
                    "property": "energy",
                    "value": {
                        "op": "RANDOM_FIXED",
                        "min": "1.000000",
                        "max": "10.000000",
                    },
                }
            ],
        }
        unrelated_rule = self.parser.parse_rule(unrelated_rule_dict)

        cells = [(0, 0), (1, 1), (2, -1)]

        def run_target_draws(include_unrelated: bool, shuffle_cells_reverse: bool) -> List[Tuple[int, Tuple[int, int], int]]:
            w = self._setup_organism_world(seed=12345)
            for idx, (cx, cy) in enumerate(cells, start=1):
                e = w.entities.create_entity(
                    "organism", 0, {"energy": FixedPoint.from_int(100), "cell_x": cx, "cell_y": cy, "generation": 0}, w.schema_registry
                )
                w.spatial_index.place_entity(e.id, cx, cy)

            target_draws = []

            for tick in range(5):
                cur_cells = list(cells)
                if shuffle_cells_reverse:
                    cur_cells.reverse()

                if include_unrelated:
                    for c in cur_cells:
                        self.interpreter.execute_rule(unrelated_rule, w, cell=c)

                for c in cur_cells:
                    stream = derive_rule_stream(w.world_seed, w.clock.current_tick, target_rule.rule_id, c, 0)
                    draw = stream.next_int_range(100, 999)
                    self.interpreter.execute_rule(target_rule, w, cell=c)
                    target_draws.append((tick, c, draw))

                w.advance_tick()

            return sorted(target_draws)

        draws_baseline = run_target_draws(include_unrelated=False, shuffle_cells_reverse=False)
        draws_with_unrelated = run_target_draws(include_unrelated=True, shuffle_cells_reverse=False)
        draws_with_reverse_shuffle = run_target_draws(include_unrelated=False, shuffle_cells_reverse=True)

        self.assertEqual(
            draws_baseline,
            draws_with_unrelated,
            "Target rule draws changed when unrelated random rule was present!",
        )
        self.assertEqual(
            draws_baseline,
            draws_with_reverse_shuffle,
            "Target rule draws changed when cell processing order changed!",
        )

    # -------------------------------------------------------------------------
    # 7. Same-Tick Repeat (Invocation Index Divergence)
    # -------------------------------------------------------------------------
    def test_same_tick_repeat_invocation_index(self):
        """A rule invoked twice in the same tick for the same cell gets distinct streams and reproduces on replay."""
        stream_0 = derive_rule_stream(world_seed=42, tick=0, rule_id="repeat_rule", cell=(0, 0), invocation_index=0)
        stream_1 = derive_rule_stream(world_seed=42, tick=0, rule_id="repeat_rule", cell=(0, 0), invocation_index=1)

        draw_0 = stream_0.next_uint64()
        draw_1 = stream_1.next_uint64()

        self.assertNotEqual(draw_0, draw_1, "Repeated invocation in same tick received identical stream!")

        # Replay must produce identical outputs bit-for-bit
        replay_0 = derive_rule_stream(world_seed=42, tick=0, rule_id="repeat_rule", cell=(0, 0), invocation_index=0).next_uint64()
        replay_1 = derive_rule_stream(world_seed=42, tick=0, rule_id="repeat_rule", cell=(0, 0), invocation_index=1).next_uint64()

        self.assertEqual(draw_0, replay_0)
        self.assertEqual(draw_1, replay_1)

    # -------------------------------------------------------------------------
    # 8. Save / Reload Determinism (Preserving World Seed)
    # -------------------------------------------------------------------------
    def test_save_reload_determinism_and_seed_preservation(self):
        """Continuous 0..100 ticks matches 0..50 save reload 50..100 bit-for-bit with random rules."""
        snap_dir = tempfile.mkdtemp()
        snap_mgr = SnapshotManager(base_dir=snap_dir)

        rule_dict = {
            "rule_id": "r_evolution",
            "name": "Evolution Rule",
            "version": "1.0",
            "spatial_partitioned": True,
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "generation",
                    "delta": {"op": "RANDOM_INT", "min": "1", "max": "5"},
                },
                {
                    "op": "SET_PROPERTY",
                    "entity": "target",
                    "property": "energy",
                    "value": {
                        "op": "RANDOM_FIXED",
                        "min": "10.000000",
                        "max": "20.000000",
                    },
                },
            ],
        }
        rule = self.parser.parse_rule(rule_dict)

        # Run 1: Continuous 100 ticks
        w_cont = self._setup_organism_world(seed=999)
        reg_cont = RuleRegistry()
        reg_cont.register_rule(rule, world=w_cont)
        w_cont.rule_registry = reg_cont
        ent1 = w_cont.entities.create_entity(
            "organism", 0, {"energy": FixedPoint.from_int(50), "cell_x": 0, "cell_y": 0, "generation": 0}, w_cont.schema_registry
        )
        w_cont.spatial_index.place_entity(ent1.id, 0, 0)

        for _ in range(100):
            w_cont.advance_tick()

        hash_cont = w_cont.compute_substrate_hash()

        # Run 2: 0..50 ticks, snapshot, reload, 50..100 ticks
        w_split = self._setup_organism_world(seed=999)
        reg_split = RuleRegistry()
        reg_split.register_rule(rule, world=w_split)
        w_split.rule_registry = reg_split
        ent2 = w_split.entities.create_entity(
            "organism", 0, {"energy": FixedPoint.from_int(50), "cell_x": 0, "cell_y": 0, "generation": 0}, w_split.schema_registry
        )
        w_split.spatial_index.place_entity(ent2.id, 0, 0)

        for _ in range(50):
            w_split.advance_tick()

        snap_path, _ = snap_mgr.save_snapshot(w_split)
        w_reloaded = snap_mgr.load_snapshot(snap_path)

        # Assert world_seed is preserved
        self.assertEqual(w_reloaded.world_seed, 999)
        self.assertEqual(w_reloaded.world_seed, w_split.world_seed)

        for _ in range(50):
            w_reloaded.advance_tick()

        hash_reloaded = w_reloaded.compute_substrate_hash()
        self.assertEqual(
            hash_cont,
            hash_reloaded,
            "Continuous vs Save/Reload simulation drifted with random rules active!",
        )

    def test_from_canonical_dict_missing_world_seed_fails_loudly(self):
        """Loading a legacy snapshot dictionary lacking 'world_seed' raises structured SerializationError."""
        world = self._setup_organism_world(seed=123)
        data = world.to_canonical_dict()
        del data["world_seed"]

        with self.assertRaises(SerializationError) as ctx:
            WorldState.from_canonical_dict(data)

        self.assertIn("Missing required 'world_seed'", str(ctx.exception))
        self.assertIn("Alpha does not support migration", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 9. Determinism Across Runs (Bit-Identical Hashes and Journal Chains)
    # -------------------------------------------------------------------------
    def test_determinism_across_independent_runs(self):
        """Two independent runs from seed 77777 produce bit-identical substrate and journal hash chains."""
        rule_dict = {
            "rule_id": "r_evolution_det",
            "name": "Evolution Determinism Rule",
            "version": "1.0",
            "spatial_partitioned": True,
            "target_selector": {"entity_type": "organism", "limit": 1},
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "generation",
                    "delta": {"op": "RANDOM_INT", "min": "1", "max": "7"},
                }
            ],
        }

        def execute_sim_run() -> Tuple[str, str]:
            world = self._setup_organism_world(seed=77777)
            rule = self.parser.parse_rule(rule_dict)
            reg = RuleRegistry()
            reg.register_rule(rule, world=world)
            world.rule_registry = reg
            ent = world.entities.create_entity(
                "organism", 0, {"energy": FixedPoint.from_int(100), "cell_x": 0, "cell_y": 0, "generation": 0}, world.schema_registry
            )
            world.spatial_index.place_entity(ent.id, 0, 0)

            for _ in range(30):
                world.advance_tick()

            return world.compute_substrate_hash(), world.event_journal.last_hash

        state_hash_1, journal_hash_1 = execute_sim_run()
        state_hash_2, journal_hash_2 = execute_sim_run()

        self.assertEqual(state_hash_1, state_hash_2, "Substrate hashes diverged between independent runs!")
        self.assertEqual(journal_hash_1, journal_hash_2, "Journal hashes diverged between independent runs!")

    def test_missing_rule_stream_raises_error_and_does_not_touch_world_rng(self):
        """Assert that evaluating random expressions without an active rule stream in ctx raises GRLExecutionError and leaves world.rng untouched."""
        world = self._setup_organism_world(seed=555)
        initial_rng_state = copy.deepcopy(world.rng.get_state())
        initial_step_count = world.rng.step_count

        node_int = self.parser.parse_expression({"op": "RANDOM_INT", "min": "1", "max": "100"})
        node_fixed = self.parser.parse_expression({"op": "RANDOM_FIXED", "min": "0.100000", "max": "0.500000"})

        # Context explicitly with rng=None
        ctx_without_rng = ExecutionContext("test_no_rng", config=world.config, rule_rng=None)
        self.assertIsNone(ctx_without_rng.rng)

        # 1. RANDOM_INT must raise GRLExecutionError
        with self.assertRaises(GRLExecutionError) as cm_int:
            self.interpreter.eval_expression(node_int, ctx_without_rng, world)
        self.assertIn("Random evaluation requires an active rule PRNG stream", str(cm_int.exception))

        # 2. RANDOM_FIXED must raise GRLExecutionError
        with self.assertRaises(GRLExecutionError) as cm_fixed:
            self.interpreter.eval_expression(node_fixed, ctx_without_rng, world)
        self.assertIn("Random evaluation requires an active rule PRNG stream", str(cm_fixed.exception))

        # 3. world.rng must NEVER have been touched
        self.assertEqual(world.rng.step_count, initial_step_count)
        self.assertEqual(world.rng.get_state(), initial_rng_state)



if __name__ == "__main__":
    unittest.main()
