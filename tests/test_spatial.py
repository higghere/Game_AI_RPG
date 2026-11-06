"""Unit tests for GENESIS Spatial Grid Index, Substrate Integration, and Per-Cell Rule Execution."""

import os
import shutil
import tempfile
import unittest

from genesis.core.arithmetic import FixedPoint, MAX_INT64, MIN_INT64
from genesis.core.config import RuntimeConfig
from genesis.core.errors import QuotaExceededError
from genesis.grl.ast import (
    AdjustPropertyNode,
    BinaryOpNode,
    LiteralNode,
    ProduceResourceNode,
    RuleDefinition,
    SetPropertyNode,
    TargetSelector,
)
from genesis.grl.interpreter import GRLInterpreter
from genesis.grl.parser import GRLParser
from genesis.grl.registry import RuleRegistry
from genesis.persistence.hasher import compute_canonical_hash
from genesis.persistence.snapshot import SnapshotManager
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.spatial import SpatialGridIndex
from genesis.substrate.world_state import WorldState


class TestSpatialGridSubstrate(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.snapshot_mgr = SnapshotManager(base_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_coordinate_types_and_quantization(self):
        """Coordinates must be integer or FixedPoint only; floats must be rejected."""
        idx = SpatialGridIndex(cell_size=10)

        # Integer coordinates
        idx.place_entity(1, 15, 25)  # cell (1, 2)
        self.assertEqual(idx.get_entity_cell(1), (1, 2))

        # FixedPoint coordinates: 15.5, 25.9 -> cell (1, 2)
        idx.place_entity(2, FixedPoint.from_decimal_string("15.5"), FixedPoint.from_decimal_string("25.9"))
        self.assertEqual(idx.get_entity_cell(2), (1, 2))

        # Negative coordinates
        idx.place_entity(3, -5, -15) # cell (-1, -2)
        self.assertEqual(idx.get_entity_cell(3), (-1, -2))

        # Rejection of float types
        with self.assertRaises(TypeError):
            idx.place_entity(4, 12.5, 10)  # float x
        with self.assertRaises(TypeError):
            idx.place_entity(4, 10, 12.5)  # float y

    def test_sorted_cell_and_entity_iteration(self):
        """Cell iteration and entity iteration must be strictly deterministically sorted."""
        idx = SpatialGridIndex(cell_size=1)

        # Insert in unsorted order across cells
        idx.place_entity(10, 2, 1)
        idx.place_entity(5, 0, 0)
        idx.place_entity(8, 0, 0)
        idx.place_entity(2, 0, 0)
        idx.place_entity(1, 1, -1)
        idx.place_entity(7, 2, 1)

        # Occupied cells must be sorted by (cx, cy) ascending
        cells = idx.get_occupied_cells()
        expected_cells = [(0, 0), (1, -1), (2, 1)]
        self.assertEqual(cells, expected_cells)

        # Entities in cell (0, 0) must be sorted by entity_id ascending
        ents_0_0 = idx.get_entities_in_cell(0, 0)
        self.assertEqual(ents_0_0, [2, 5, 8])

        # Entities in cell (2, 1) must be sorted
        ents_2_1 = idx.get_entities_in_cell(2, 1)
        self.assertEqual(ents_2_1, [7, 10])

        # Radius query Chebyshev neighborhood around (0, 0) with radius 1
        # Includes cells (0, 0) and (1, -1), sorted
        radius_ents = idx.get_entities_in_radius(0, 0, 1)
        self.assertEqual(radius_ents, [1, 2, 5, 8])

    def test_snapshot_save_reload_and_state_hash_match(self):
        """Saving to snapshot and reloading must preserve exact bit-level state hash."""
        world = WorldState(seed=12345)
        schema = EntityTypeSchema("agent")
        schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("energy", PropertyType.INT64, default_value=100))
        world.schema_registry.register_type(schema)

        for i in range(50):
            cx = (i * 3) % 7
            cy = (i * 5) % 7
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": cx, "cell_y": cy, "energy": 100 + i},
                world.schema_registry,
            )
            world.place_entity_in_cell(ent.id, cx, cy)

        # Compute initial state hash
        hash_before = compute_canonical_hash(world.to_canonical_dict())

        # Save snapshot
        snap_path, snap_hash = self.snapshot_mgr.save_snapshot(world, "spatial_test.json")

        # Reload snapshot
        world_loaded = self.snapshot_mgr.load_snapshot(snap_path)
        hash_after = compute_canonical_hash(world_loaded.to_canonical_dict())

        # Assert hashes match bit-for-bit
        self.assertEqual(hash_before, hash_after)
        self.assertEqual(world.spatial_index.get_occupied_cells(), world_loaded.spatial_index.get_occupied_cells())

        # Test deterministic rebuild from entities produces identical state hash
        world_rebuilt = WorldState.from_canonical_dict(world.to_canonical_dict())
        world_rebuilt.spatial_index = SpatialGridIndex(cell_size=1)
        world_rebuilt.rebuild_spatial_index()
        hash_rebuilt = compute_canonical_hash(world_rebuilt.to_canonical_dict())
        self.assertEqual(hash_before, hash_rebuilt)

    def test_rules_query_cells_through_substrate_and_count_toward_tick_cap(self):
        """Rules scoped to spatial cells must touch only matching cell entities and count toward tick cap."""
        config = RuntimeConfig(max_operations_per_rule=256, max_entities_touched_per_tick=1000)
        world = WorldState(seed=999, config=config)
        interp = GRLInterpreter(config)

        schema = EntityTypeSchema("tree")
        schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("height", PropertyType.INT64, default_value=1))
        world.schema_registry.register_type(schema)

        # Place 10 trees in cell (0, 0) and 10 trees in cell (1, 1)
        for i in range(10):
            ent = world.entities.create_entity("tree", 0, {"cell_x": 0, "cell_y": 0, "height": 1}, world.schema_registry)
            world.place_entity_in_cell(ent.id, 0, 0)
        for i in range(10):
            ent = world.entities.create_entity("tree", 0, {"cell_x": 1, "cell_y": 1, "height": 1}, world.schema_registry)
            world.place_entity_in_cell(ent.id, 1, 1)

        # Rule scoped specifically to cell (0, 0)
        rule = RuleDefinition(
            rule_id="r_grow_cell_0_0",
            name="Grow Trees in (0, 0)",
            version="1.0.0",
            target_selector=TargetSelector("tree", spatial_cell=(0, 0)),
            effects=[
                AdjustPropertyNode("target", "height", LiteralNode("INT64", 1))
            ]
        )

        success, msg = interp.execute_rule(rule, world)
        self.assertTrue(success)

        # Exactly 10 trees in cell (0, 0) must have been touched
        self.assertEqual(len(world.entities_touched_this_tick), 10)
        for eid in world.spatial_index.get_entities_in_cell(0, 0):
            self.assertEqual(world.entities.get_entity(eid).get_property("height"), 2)

        # Trees in cell (1, 1) were NOT touched and remain height 1
        for eid in world.spatial_index.get_entities_in_cell(1, 1):
            self.assertEqual(world.entities.get_entity(eid).get_property("height"), 1)
            self.assertNotIn(eid, world.entities_touched_this_tick)

    def test_spatial_partitioned_rules_over_300_agents(self):
        """300 agents partitioned across spatial cells execute successfully within 256 ops per cell."""
        config = RuntimeConfig(max_operations_per_rule=256, max_entities_touched_per_tick=1000)
        world = WorldState(seed=777, config=config)

        schema = EntityTypeSchema("agent")
        schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("energy", PropertyType.INT64, default_value=100))
        world.schema_registry.register_type(schema)

        # Distribute 300 agents across 30 cells (10 agents per cell)
        # Grid of 5 x 6 = 30 cells
        cell_coords = [(cx, cy) for cx in range(5) for cy in range(6)]
        for i in range(300):
            cell = cell_coords[i % len(cell_coords)]
            ent = world.entities.create_entity(
                "agent",
                0,
                {"cell_x": cell[0], "cell_y": cell[1], "energy": 100},
                world.schema_registry,
            )
            world.place_entity_in_cell(ent.id, cell[0], cell[1])

        self.assertEqual(len(world.spatial_index.get_occupied_cells()), 30)

        # If a rule tried to scan all 300 agents without spatial partitioning, it would consume > 300 ops
        # and fail the 256 max_operations_per_rule budget.
        # But with spatial_partitioned = True, it executes once per cell (10 agents / cell)
        rule_dict = {
            "rule_id": "r_agent_metabolism",
            "name": "Metabolism",
            "version": "1.0.0",
            "priority": 10,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "agent",
            },
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "energy",
                    "delta": {"op": "LITERAL", "type": "INT64", "value": "-5"},
                }
            ],
        }

        parser = GRLParser()
        rule = parser.parse_rule(rule_dict)
        world.register_rule(rule)

        # Advance tick to trigger Phase 2 GRL_RULES
        world.advance_tick()

        # All 300 agents must have energy 95
        for eid in range(1, 301):
            ent = world.entities.get_entity(eid)
            self.assertEqual(ent.get_property("energy"), 95)

        # Exactly 300 unique entities touched across the tick, within 1000 limit
        self.assertEqual(len(world.entities_touched_this_tick), 300)

    def test_simultaneous_movement_prevents_double_acting_or_skipping(self):
        """Agents moving into later or earlier cells must act exactly once per tick."""
        config = RuntimeConfig(max_operations_per_rule=256, max_entities_touched_per_tick=1000)
        world = WorldState(seed=4321, config=config)

        schema = EntityTypeSchema("migrant")
        schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
        schema.add_property(PropertyDefinition("action_count", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema)

        # Agent 1 starts in earlier cell (0, 0)
        # Agent 2 starts in later cell (1, 1)
        # Agent 3 starts in later cell (2, 2)
        a1 = world.entities.create_entity("migrant", 0, {"cell_x": 0, "cell_y": 0, "action_count": 0}, world.schema_registry)
        world.place_entity_in_cell(a1.id, 0, 0)

        a2 = world.entities.create_entity("migrant", 0, {"cell_x": 1, "cell_y": 1, "action_count": 0}, world.schema_registry)
        world.place_entity_in_cell(a2.id, 1, 1)

        a3 = world.entities.create_entity("migrant", 0, {"cell_x": 2, "cell_y": 2, "action_count": 0}, world.schema_registry)
        world.place_entity_in_cell(a3.id, 2, 2)

        # Rule moves:
        # If in cell_x == 0 -> move to (1, 1) (later cell)
        # Else -> move to (0, 0) (earlier cell)
        # And increments action_count by 1
        rule_dict = {
            "rule_id": "r_migrate_agents",
            "name": "Migrate Agents",
            "version": "1.0.0",
            "priority": 10,
            "spatial_partitioned": True,
            "target_selector": {
                "entity_type": "migrant",
            },
            "effects": [
                {
                    "op": "ADJUST_PROPERTY",
                    "entity": "target",
                    "property": "action_count",
                    "delta": {"op": "LITERAL", "type": "INT64", "value": "1"},
                },
                {
                    "op": "IF",
                    "condition": {
                        "op": "EQUALS",
                        "left": {"op": "GET_PROPERTY", "entity": "target", "property": "cell_x"},
                        "right": {"op": "LITERAL", "type": "INT64", "value": "0"},
                    },
                    "then": [
                        {"op": "SET_PROPERTY", "entity": "target", "property": "cell_x", "value": {"op": "LITERAL", "type": "INT64", "value": "1"}},
                        {"op": "SET_PROPERTY", "entity": "target", "property": "cell_y", "value": {"op": "LITERAL", "type": "INT64", "value": "1"}},
                    ],
                    "else": [
                        {"op": "SET_PROPERTY", "entity": "target", "property": "cell_x", "value": {"op": "LITERAL", "type": "INT64", "value": "0"}},
                        {"op": "SET_PROPERTY", "entity": "target", "property": "cell_y", "value": {"op": "LITERAL", "type": "INT64", "value": "0"}},
                    ],
                },
            ],
        }

        parser = GRLParser()
        world.register_rule(parser.parse_rule(rule_dict))

        # --- Tick 1 Execution ---
        world.advance_tick()

        # Verify action counts after Tick 1: every agent acted EXACTLY once
        self.assertEqual(a1.get_property("action_count"), 1, "Agent 1 (moving to later cell) must act exactly once")
        self.assertEqual(a2.get_property("action_count"), 1, "Agent 2 (moving to earlier cell) must act exactly once")
        self.assertEqual(a3.get_property("action_count"), 1, "Agent 3 (moving to earlier cell) must act exactly once")

        # Verify new spatial index positions committed at end of rule pass
        self.assertEqual(world.spatial_index.get_entity_cell(a1.id), (1, 1))
        self.assertEqual(world.spatial_index.get_entity_cell(a2.id), (0, 0))
        self.assertEqual(world.spatial_index.get_entity_cell(a3.id), (0, 0))

        self.assertEqual(world.spatial_index.get_entities_in_cell(0, 0), [a2.id, a3.id])
        self.assertEqual(world.spatial_index.get_entities_in_cell(1, 1), [a1.id])
        self.assertEqual(world.spatial_index.get_entities_in_cell(2, 2), [])

        # --- Tick 2 Execution ---
        # Now Agent 1 is at (1, 1) and will move to (0, 0)
        # Agents 2 and 3 are at (0, 0) and will move to (1, 1)
        world.advance_tick()

        self.assertEqual(a1.get_property("action_count"), 2, "Agent 1 must act exactly once in Tick 2")
        self.assertEqual(a2.get_property("action_count"), 2, "Agent 2 must act exactly once in Tick 2")
        self.assertEqual(a3.get_property("action_count"), 2, "Agent 3 must act exactly once in Tick 2")

        self.assertEqual(world.spatial_index.get_entity_cell(a1.id), (0, 0))
        self.assertEqual(world.spatial_index.get_entity_cell(a2.id), (1, 1))
        self.assertEqual(world.spatial_index.get_entity_cell(a3.id), (1, 1))


if __name__ == "__main__":
    unittest.main()
