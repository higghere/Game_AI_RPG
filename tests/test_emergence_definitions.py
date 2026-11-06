"""GENESIS Emergence Definitions Acceptance & Control Test Suite.

Proves pre-registered operational definitions for Settlement, Group, and Cultural Spread
separate emergence from noise before any Phase 3 agent, trait, or genome exists.
Implements synthetic positive and negative control worlds, including the oasis control world,
kinship horizon guards, read-only state hash preservation, and frozen parameter hash verification.
"""

from __future__ import annotations
import os
import shutil
import tempfile
import unittest
from typing import Any, Dict, List

from genesis.core.arithmetic import FixedPoint
from genesis.persistence.hasher import compute_canonical_hash
from genesis.substrate.events import EventRecord
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.world_state import WorldState

from genesis.analysis.binding import AnalysisBinding
from genesis.analysis.params import (
    load_emergence_params,
    compute_canonical_params_hash,
    FROZEN_PARAMS_V1_HASH,
)
from genesis.analysis.stream import derive_analysis_stream
from genesis.analysis.settlement import evaluate_settlement
from genesis.analysis.group import evaluate_group
from genesis.analysis.culture import evaluate_cultural_spread
from genesis.analysis.metrics import (
    measure_settlement,
    measure_group,
    measure_cultural_spread,
)


def _make_agent_schema() -> EntityTypeSchema:
    schema = EntityTypeSchema("agent")
    schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, min_value=-1000, max_value=1000, default_value=0))
    schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, min_value=-1000, max_value=1000, default_value=0))
    schema.add_property(PropertyDefinition("is_alive", PropertyType.INT64, min_value=0, max_value=1, default_value=1))
    schema.add_property(PropertyDefinition("birth_cell_x", PropertyType.INT64, min_value=-1000, max_value=1000, default_value=0))
    schema.add_property(PropertyDefinition("birth_cell_y", PropertyType.INT64, min_value=-1000, max_value=1000, default_value=0))
    schema.add_property(PropertyDefinition("farming_technique", PropertyType.INT64, min_value=0, max_value=100, default_value=0))
    schema.add_property(PropertyDefinition("soil_water", PropertyType.INT64, min_value=0, max_value=1000000, default_value=10))
    return schema


class TestEmergenceDefinitions(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.journal_dir = os.path.join(self.temp_dir, "journal")
        os.makedirs(self.journal_dir, exist_ok=True)
        self.binding = AnalysisBinding()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_world(self, seed: int = 42) -> WorldState:
        world = WorldState(seed=seed, journal_dir=self.journal_dir)
        world.schema_registry.register_type(_make_agent_schema())
        return world

    # =========================================================================
    # 1. Parameter Hash & Stream Reproducibility Tests
    # =========================================================================

    def test_parameter_file_hash_pinned(self) -> None:
        """Parameters file must match the frozen canonical SHA-256 hash bit-for-bit."""
        params = load_emergence_params("v1", verify_hash=True)
        computed = compute_canonical_params_hash(params)
        self.assertEqual(computed, FROZEN_PARAMS_V1_HASH)

    def test_analysis_stream_golden_reproducibility(self) -> None:
        """Analysis PRNG stream produces identical cross-platform sequence from fixed seed."""
        rng = derive_analysis_stream(1337, "golden_test", 0)
        generated = [rng.next_uint64() for _ in range(5)]
        expected = [
            7673574148279980716,
            13884609953370120892,
            6793737264868255537,
            16256038411204022503,
            4726979361265302715,
        ]
        self.assertEqual(generated, expected)

    # =========================================================================
    # 2. Settlement Controls
    # =========================================================================

    def test_settlement_positive_control(self) -> None:
        """A dense, 5-year persistent cluster with 50% native births passes settlement verdict."""
        world = self._create_world()
        # Create 12 agents clustered in cells (0,0), (0,1), (1,0), (1,1) within radius 2
        cluster_cells = [(0, 0), (0, 1), (1, 0), (1, 1)]
        agents: List[Dict[str, Any]] = []
        for i in range(12):
            c = cluster_cells[i % len(cluster_cells)]
            # 6 born inside footprint (50%), 6 born outside
            bx, by = c if i < 6 else (50, 50)
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": c[0], "cell_y": c[1], "is_alive": 1, "birth_cell_x": bx, "birth_cell_y": by},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, c[0], c[1])
            agents.append({"id": ent.id, "x": c[0], "y": c[1]})

        # Scatter 20 background agents across a 10x10 area so the null baseline has room
        for i in range(20):
            bx = 10 + (i % 5) * 3
            by = 10 + (i // 5) * 3
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": bx, "cell_y": by, "is_alive": 1, "birth_cell_x": bx, "birth_cell_y": by},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, bx, by)

        # 5-year sample history maintaining membership and low centroid drift
        sample_history = []
        for year in range(5):
            sample_agents = []
            for a in agents:
                sample_agents.append({"id": a["id"], "x": a["x"], "y": a["y"]})
            sample_history.append({"tick": year * 365, "agents": sample_agents})

        world.clock._tick = 1825
        verdict = measure_settlement(world, self.binding, sample_history)
        self.assertTrue(verdict["passed"], f"Settlement positive control failed: {verdict.get('failure_reasons')}")
        self.assertEqual(verdict["params_version"], "v1")
        self.assertEqual(verdict["params_sha256"], FROZEN_PARAMS_V1_HASH)
        self.assertTrue(verdict["sub_criteria"]["spatial_cluster_size"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["temporal_persistence"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["generational_anchoring"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["significance_uniform_null"]["passed"])

    def test_settlement_negative_uniform_scatter(self) -> None:
        """Uniformly scattered agents across grid fail the settlement cluster criteria."""
        world = self._create_world()
        # 25 agents separated by 5 cells each
        for i in range(25):
            x = (i % 5) * 5
            y = (i // 5) * 5
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": x, "cell_y": y, "is_alive": 1, "birth_cell_x": x, "birth_cell_y": y},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, x, y)

        verdict = measure_settlement(world, self.binding)
        self.assertFalse(verdict["passed"])
        # Largest component size is 1 (< 8)
        self.assertFalse(verdict["sub_criteria"]["spatial_cluster_size"]["passed"])

    def test_settlement_negative_dissolving_cluster(self) -> None:
        """A dense cluster that disperses before 5 years fails temporal persistence."""
        world = self._create_world()
        cluster_agents = []
        for i in range(12):
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": i % 2, "cell_y": i // 6, "is_alive": 1, "birth_cell_x": 0, "birth_cell_y": 0},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, ent.get_property("cell_x"), ent.get_property("cell_y"))
            cluster_agents.append({"id": ent.id, "x": ent.get_property("cell_x"), "y": ent.get_property("cell_y")})

        # History where agents scattered in year 3
        sample_history = []
        for year in range(5):
            sample_agents = []
            for idx, a in enumerate(cluster_agents):
                # Disperse in later years
                offset = year * 10 if year >= 2 else 0
                sample_agents.append({"id": a["id"], "x": a["x"] + offset, "y": a["y"] + offset})
            sample_history.append({"tick": year * 365, "agents": sample_agents})

        world.clock._tick = 1825
        verdict = measure_settlement(world, self.binding, sample_history)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["temporal_persistence"]["passed"])

    def test_settlement_negative_immigrants_only(self) -> None:
        """A dense persistent cluster with 0% native births fails generational anchoring."""
        world = self._create_world()
        agents = []
        for i in range(12):
            # All born in faraway cell (80, 80)
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": 1, "cell_y": 1, "is_alive": 1, "birth_cell_x": 80, "birth_cell_y": 80},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, 1, 1)
            agents.append({"id": ent.id, "x": 1, "y": 1})

        sample_history = [{"tick": y * 365, "agents": agents} for y in range(5)]
        world.clock._tick = 1825
        verdict = measure_settlement(world, self.binding, sample_history)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["generational_anchoring"]["passed"])
        self.assertEqual(verdict["sub_criteria"]["generational_anchoring"]["observed_born_in_count"], 0)

    def test_settlement_negative_undersized_cluster(self) -> None:
        """A cluster of 5 agents fails the N_min >= 8 threshold."""
        world = self._create_world()
        agents = []
        for i in range(5):
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": 0, "cell_y": 0, "is_alive": 1, "birth_cell_x": 0, "birth_cell_y": 0},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, 0, 0)
            agents.append({"id": ent.id, "x": 0, "y": 0})

        sample_history = [{"tick": y * 365, "agents": agents} for y in range(5)]
        world.clock._tick = 1825
        verdict = measure_settlement(world, self.binding, sample_history)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["spatial_cluster_size"]["passed"])

    def test_settlement_negative_oasis_control_world(self) -> None:
        """OASIS CONTROL: Organisms clustered around a fertile resource oasis fail the resource-weighted null."""
        world = self._create_world()
        # Oasis cell (2, 2) holds 98% of the world's resource
        # Environmental resource nodes defining landscape
        res_oasis = world.entities.create_entity("agent", 0, {"cell_x": 2, "cell_y": 2, "soil_water": 100000}, world.schema_registry)
        world.spatial_index.place_entity(res_oasis.id, 2, 2)

        oasis_agents = []
        # 12 organisms clustered at oasis (2, 2)
        for i in range(12):
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": 2, "cell_y": 2, "is_alive": 1, "birth_cell_x": 2, "birth_cell_y": 2, "soil_water": 10},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, 2, 2)
            oasis_agents.append({"id": ent.id, "x": 2, "y": 2})

        # 4 scattered agents at low-resource cells
        for i, c in enumerate([(10, 10), (10, 20), (20, 10), (20, 20)]):
            res_node = world.entities.create_entity("agent", 0, {"cell_x": c[0], "cell_y": c[1], "soil_water": 10}, world.schema_registry)
            world.spatial_index.place_entity(res_node.id, c[0], c[1])
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": c[0], "cell_y": c[1], "is_alive": 1, "birth_cell_x": c[0], "birth_cell_y": c[1], "soil_water": 10},
                world.schema_registry,
            )
            world.spatial_index.place_entity(ent.id, c[0], c[1])

        sample_history = [{"tick": y * 365, "agents": oasis_agents} for y in range(5)]
        world.clock._tick = 1825

        binding_with_resource = AnalysisBinding(resource_landscape_property="soil_water")
        verdict = measure_settlement(world, binding_with_resource, sample_history)

        # Crucial assertion: Uniform null passes, but Resource-Weighted Null FAILS because the null model
        # also clusters agents at the oasis!
        self.assertTrue(verdict["sub_criteria"]["significance_uniform_null"]["passed"])
        self.assertFalse(verdict["sub_criteria"]["significance_resource_weighted_null"]["passed"])
        self.assertFalse(verdict["passed"], "Oasis congregation erroneously passed settlement verdict!")

    def test_settlement_unbound_stockpile_caveat(self) -> None:
        """When stockpile_resource_property is None, verdict records 'stockpile not assessed'."""
        world = self._create_world()
        agents = []
        for i in range(10):
            ent = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry)
            world.spatial_index.place_entity(ent.id, 0, 0)
            agents.append({"id": ent.id, "x": 0, "y": 0})
        verdict = measure_settlement(world, AnalysisBinding(stockpile_resource_property=None))
        stockpile_info = verdict["sub_criteria"]["stockpile_enrichment"]
        self.assertEqual(stockpile_info["status"], "NOT_ASSESSED")
        self.assertEqual(stockpile_info["note"], "stockpile not assessed")

    # =========================================================================
    # 3. Group Controls
    # =========================================================================

    def test_group_positive_control(self) -> None:
        """A cooperating community (10 agents, density >= 0.20, cohesion >= 2.0, multi-year active, non-kin >= 30%) passes."""
        world = self._create_world()
        member_ids = []
        for i in range(10):
            ent = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry)
            member_ids.append(ent.id)

        # Add 15 internal bilateral relationships (density = 15 / 45 = 0.33 >= 0.20)
        # All non-kin (no parent_of edges exist)
        for i in range(10):
            next_id = member_ids[(i + 1) % 10]
            skip_id = member_ids[(i + 2) % 10]
            world.relationships.add_edge(member_ids[i], next_id, "traded_with", FixedPoint.from_int(2))
            world.relationships.add_edge(member_ids[i], skip_id, "allied_with", FixedPoint.from_int(1))

        # Add 2 external edges to non-members
        ext_ent1 = world.entities.create_entity("agent", 0, {"cell_x": 10, "cell_y": 10, "is_alive": 1}, world.schema_registry)
        ext_ent2 = world.entities.create_entity("agent", 0, {"cell_x": 10, "cell_y": 10, "is_alive": 1}, world.schema_registry)
        world.relationships.add_edge(member_ids[0], ext_ent1.id, "traded_with", FixedPoint.from_int(1))
        world.relationships.add_edge(member_ids[1], ext_ent2.id, "traded_with", FixedPoint.from_int(1))

        # Record events across 2 distinct years (Year 1: tick 100, Year 3: tick 800)
        rec1 = EventRecord(100, 1, 0, 1, "trade_executed", {"source_id": member_ids[0], "target_id": member_ids[1]})
        rec2 = EventRecord(800, 1, 0, 2, "tax_remitted", {"source_id": member_ids[2], "target_id": member_ids[3]})
        world.event_journal.append(rec1)
        world.event_journal.append(rec2)

        # 10-year persistence history with 50% member turnover (5 founders replaced)
        sample_history = [
            {"tick": 0, "member_ids": member_ids[:5] + [101, 102, 103, 104, 105]},  # 5 of original cohort survived
        ] + [{"tick": y * 365, "member_ids": member_ids} for y in range(1, 11)]

        verdict = measure_group(world, window_start_tick=0, window_end_tick=3650, binding=self.binding, sample_history=sample_history)
        self.assertTrue(verdict["passed"], f"Group positive control failed: {verdict.get('failure_reasons')}")
        self.assertTrue(verdict["sub_criteria"]["group_size"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["internal_density"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["cohesion_ratio"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["multi_year_activity"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["non_kin_structure"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["persistence_turnover"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["significance_degree_null"]["passed"])

    def test_group_negative_proximity_only_crowd(self) -> None:
        """A crowd sharing a cell with zero cooperative ties produces zero edges and fails."""
        world = self._create_world()
        for i in range(15):
            ent = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry)
            world.spatial_index.place_entity(ent.id, 0, 0)

        verdict = measure_group(world, window_start_tick=0, window_end_tick=3650, binding=self.binding)
        self.assertFalse(verdict["passed"])
        self.assertIn("No interaction graph edges found", verdict["failure_reasons"])

    def test_group_negative_kin_only_clique(self) -> None:
        """A cooperating family clique where 100% of ties connect parents/siblings fails the group verdict."""
        world = self._create_world()
        # Parent and 7 children
        parent = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry)
        children = [
            world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry)
            for _ in range(7)
        ]
        for c in children:
            world.relationships.add_edge(parent.id, c.id, "parent_of", FixedPoint.from_int(1))
            # Cooperative trading edge strictly between parent and child (kin distance = 1)
            world.relationships.add_edge(parent.id, c.id, "traded_with", FixedPoint.from_int(3))

        # Multi-year event
        world.event_journal.append(EventRecord(100, 1, 0, 1, "trade_executed", {"source_id": parent.id, "target_id": children[0].id}))
        world.event_journal.append(EventRecord(800, 1, 0, 2, "trade_executed", {"source_id": parent.id, "target_id": children[1].id}))

        verdict = measure_group(world, window_start_tick=0, window_end_tick=3650, binding=self.binding)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["non_kin_structure"]["passed"])
        self.assertEqual(verdict["sub_criteria"]["non_kin_structure"]["non_kin_edges"], 0)

    def test_group_negative_single_year_burst(self) -> None:
        """Cooperation confined strictly to 1 year fails min_active_years >= 2."""
        world = self._create_world()
        member_ids = [world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry).id for _ in range(8)]
        # All events in year 1 (tick 50 and 60)
        world.event_journal.append(EventRecord(50, 1, 0, 1, "trade_executed", {"source_id": member_ids[0], "target_id": member_ids[1]}))
        world.event_journal.append(EventRecord(60, 1, 0, 2, "trade_executed", {"source_id": member_ids[1], "target_id": member_ids[2]}))

        verdict = measure_group(world, window_start_tick=0, window_end_tick=3650, binding=self.binding)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["multi_year_activity"]["passed"])

    def test_group_negative_dies_with_founders(self) -> None:
        """A cohesive group that dissolves when founders die (0% turnover survival) fails."""
        world = self._create_world()
        member_ids = [world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry).id for _ in range(8)]
        for i in range(8):
            world.relationships.add_edge(member_ids[i], member_ids[(i + 1) % 8], "allied_with", FixedPoint.from_int(2))

        world.event_journal.append(EventRecord(100, 1, 0, 1, "trade_executed", {"source_id": member_ids[0], "target_id": member_ids[1]}))
        world.event_journal.append(EventRecord(800, 1, 0, 2, "trade_executed", {"source_id": member_ids[2], "target_id": member_ids[3]}))

        # Founding cohort was completely different; 0 survivors in current cohort
        sample_history = [
            {"tick": 0, "member_ids": [201, 202, 203, 204, 205, 206, 207, 208]},
        ] + [{"tick": y * 365, "member_ids": member_ids} for y in range(1, 11)]

        verdict = measure_group(world, window_start_tick=0, window_end_tick=3650, binding=self.binding, sample_history=sample_history)
        # Note: 0 survivors out of 8 founding cohort means 100% turnover! Turnover passed!
        # To fail turnover, ALL 8 founding members must still be present (0% turnover < 50% required)
        sample_history_no_turnover = [
            {"tick": 0, "member_ids": member_ids},  # 100% of founders still present at end
        ] + [{"tick": y * 365, "member_ids": member_ids} for y in range(1, 11)]

        verdict_no_turnover = measure_group(world, window_start_tick=0, window_end_tick=3650, binding=self.binding, sample_history=sample_history_no_turnover)
        self.assertFalse(verdict_no_turnover["passed"])
        self.assertFalse(verdict_no_turnover["sub_criteria"]["persistence_turnover"]["passed"])

    # =========================================================================
    # 4. Cultural Spread Controls
    # =========================================================================

    def test_cultural_spread_positive_control(self) -> None:
        """A practice transmitted across 3 distinct lineages and multiple cells with 100% fidelity passes."""
        world = self._create_world()
        # Founder (now deceased)
        founder = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 0, "farming_technique": 5}, world.schema_registry)

        # 3 distinct lineages of living agents
        # Lineage 1: root1 -> child1 -> grandchild1
        root1 = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 0}, world.schema_registry)
        root2 = world.entities.create_entity("agent", 0, {"cell_x": 5, "cell_y": 5, "is_alive": 0}, world.schema_registry)
        root3 = world.entities.create_entity("agent", 0, {"cell_x": 10, "cell_y": 10, "is_alive": 0}, world.schema_registry)

        living_adopters = []
        for i in range(10):
            # Place in cells spanning distance >= 2 from (0,0)
            cx = (i % 3) * 2
            cy = (i // 3) * 2
            ent = world.entities.create_entity("agent", 0, {"cell_x": cx, "cell_y": cy, "is_alive": 1, "farming_technique": 5}, world.schema_registry)
            world.spatial_index.place_entity(ent.id, cx, cy)
            living_adopters.append(ent)
            # Attach to roots (3 distinct lineages)
            r = [root1, root2, root3][i % 3]
            world.relationships.add_edge(r.id, ent.id, "parent_of", FixedPoint.from_int(1))

        # Add 15 scattered non-adopter living agents so population total = 25 (adopter fraction = 40% >= 10%)
        for i in range(15):
            nx = 10 + (i % 5) * 4
            ny = 10 + (i // 5) * 4
            ent = world.entities.create_entity("agent", 0, {"cell_x": nx, "cell_y": ny, "is_alive": 1, "farming_technique": 0}, world.schema_registry)
            world.spatial_index.place_entity(ent.id, nx, ny)

        # Journal events: founder transmitted to first 2, then horizontal peer learning
        world.event_journal.append(EventRecord(10, 1, 0, 1, "practice_adopted", {
            "adopter_id": living_adopters[0].id, "source_id": founder.id, "practice_value": 5, "source_value": 5, "cell_x": 0, "cell_y": 0
        }))
        for i in range(1, 10):
            src = living_adopters[i - 1]
            tgt = living_adopters[i]
            # Since src and tgt are attached to different roots (root i%3 vs (i-1)%3), they share NO common ancestor <= 4 gen
            world.event_journal.append(EventRecord(20 + i * 10, 1, 0, i + 1, "practice_adopted", {
                "adopter_id": tgt.id, "source_id": src.id, "practice_value": 5, "source_value": 5, "cell_x": tgt.get_property("cell_x"), "cell_y": tgt.get_property("cell_y")
            }))

        world.clock._tick = 500
        verdict = measure_cultural_spread(world, eval_tick=500, binding=self.binding)
        self.assertTrue(verdict["passed"], f"Cultural spread positive control failed: {verdict.get('failure_reasons')}")
        self.assertTrue(verdict["sub_criteria"]["non_kin_transmission"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["distinct_lineages"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["demographic_reach"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["spatial_span"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["speed_ratio_vs_lineage"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["copying_fidelity"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["post_founder_persistence"]["passed"])
        self.assertTrue(verdict["sub_criteria"]["significance_random_null"]["passed"])

    def test_cultural_spread_negative_single_lineage(self) -> None:
        """A practice transmitted exclusively within a single family lineage fails the non-kin criterion."""
        world = self._create_world()
        founder = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 0, "farming_technique": 5}, world.schema_registry)
        # 8 descendants in same lineage: all share founder as common ancestor within 3 generations!
        adopters = []
        prev = founder
        for i in range(8):
            ent = world.entities.create_entity("agent", 0, {"cell_x": i, "cell_y": i, "is_alive": 1, "farming_technique": 5}, world.schema_registry)
            world.spatial_index.place_entity(ent.id, i, i)
            world.relationships.add_edge(prev.id, ent.id, "parent_of", FixedPoint.from_int(1))
            adopters.append(ent)
            # Transmitted down the family tree
            world.event_journal.append(EventRecord(10 + i * 5, 1, 0, i + 1, "practice_adopted", {
                "adopter_id": ent.id, "source_id": prev.id, "practice_value": 5, "source_value": 5, "cell_x": i, "cell_y": i
            }))
            prev = ent

        verdict = measure_cultural_spread(world, eval_tick=200, binding=self.binding)
        self.assertFalse(verdict["passed"])
        # All transmissions connect kin sharing founder as common ancestor <= 4 gen!
        self.assertFalse(verdict["sub_criteria"]["non_kin_transmission"]["passed"])
        self.assertEqual(verdict["sub_criteria"]["non_kin_transmission"]["non_kin_events"], 0)

    def test_cultural_spread_negative_low_fidelity(self) -> None:
        """Garbled transmissions (fidelity < 90%) fail the copying fidelity criterion."""
        world = self._create_world()
        founder = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 0, "farming_technique": 10}, world.schema_registry)
        adopters = [world.entities.create_entity("agent", 0, {"cell_x": i, "cell_y": i, "is_alive": 1, "farming_technique": i}, world.schema_registry) for i in range(10)]
        # Transmissions with mutated values (e.g. 5 out of 10 match, 50% fidelity < 90%)
        for i in range(10):
            val = 10 if i < 5 else 99  # 50% corrupted
            world.event_journal.append(EventRecord(10 + i, 1, 0, i + 1, "practice_adopted", {
                "adopter_id": adopters[i].id, "source_id": founder.id, "practice_value": val, "source_value": 10, "cell_x": i, "cell_y": i
            }))

        verdict = measure_cultural_spread(world, eval_tick=100, binding=self.binding)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["copying_fidelity"]["passed"])

    def test_cultural_spread_negative_dies_with_founders(self) -> None:
        """When founders die and no living adopters remain, post-founder persistence fails."""
        world = self._create_world()
        # Founder died, zero living adopters
        founder = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 0, "farming_technique": 5}, world.schema_registry)
        world.event_journal.append(EventRecord(10, 1, 0, 1, "practice_adopted", {
            "adopter_id": founder.id, "source_id": None, "practice_value": 5, "source_value": 5, "cell_x": 0, "cell_y": 0
        }))
        verdict = measure_cultural_spread(world, eval_tick=200, binding=self.binding)
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["sub_criteria"]["post_founder_persistence"]["passed"])

    # =========================================================================
    # 5. Read-Only Invariants & Non-Interference
    # =========================================================================

    def test_read_only_and_rng_non_interference_invariants(self) -> None:
        """Running all metrics leaves world state hash, journal hash, and world.rng.step_count byte-identical."""
        world = self._create_world(seed=9999)
        # Add some entities and relationships
        e1 = world.entities.create_entity("agent", 0, {"cell_x": 0, "cell_y": 0, "is_alive": 1}, world.schema_registry)
        e2 = world.entities.create_entity("agent", 0, {"cell_x": 1, "cell_y": 1, "is_alive": 1}, world.schema_registry)
        world.spatial_index.place_entity(e1.id, 0, 0)
        world.spatial_index.place_entity(e2.id, 1, 1)
        world.relationships.add_edge(e1.id, e2.id, "traded_with", FixedPoint.from_int(1))
        world.event_journal.append(EventRecord(10, 1, 0, 1, "trade_executed", {"source_id": e1.id, "target_id": e2.id}))

        # Advance world.rng 15 steps
        for _ in range(15):
            world.rng.next_uint64()

        initial_state_hash = world.compute_state_hash()
        initial_journal_hash = world.event_journal.last_hash
        initial_rng_step = world.rng.step_count

        # Run all three metrics
        _ = measure_settlement(world, self.binding)
        _ = measure_group(world, window_start_tick=0, window_end_tick=100, binding=self.binding)
        _ = measure_cultural_spread(world, eval_tick=100, binding=self.binding)

        final_state_hash = world.compute_state_hash()
        final_journal_hash = world.event_journal.last_hash
        final_rng_step = world.rng.step_count

        self.assertEqual(final_state_hash, initial_state_hash, "State hash mutated during metric evaluation!")
        self.assertEqual(final_journal_hash, initial_journal_hash, "Journal hash mutated during metric evaluation!")
        self.assertEqual(final_rng_step, initial_rng_step, "world.rng.step_count advanced during metric evaluation!")


if __name__ == "__main__":
    unittest.main()
