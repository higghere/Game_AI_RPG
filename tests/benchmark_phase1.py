"""GENESIS Interpreter Performance Benchmark.

Benchmarks GRL interpreter operations per second across 300 agents in a
spatial grid environment and projects wall-clock runtimes for 3,650 ticks
(10 simulated years) and 36,500 ticks (100 simulated years).
"""

import os
import sys
import time
import unittest
from typing import Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from genesis.core.arithmetic import FixedPoint
from genesis.core.config import RuntimeConfig
from genesis.grl.parser import GRLParser
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.world_state import WorldState


def run_benchmark(num_ticks: int = 100, num_agents: int = 300, num_cells: int = 30) -> Dict[str, Any]:
    """Execute benchmark simulation and compute performance metrics."""
    config = RuntimeConfig(
        max_operations_per_rule=256,
        max_entities_touched_per_tick=1000,
    )
    world = WorldState(seed=20261106, config=config)

    # 1. Setup Resource Pools
    world.resources.create_pool("biomass", initial_balance=FixedPoint.from_int(50000))
    world.resources.create_pool("water", initial_balance=FixedPoint.from_int(50000))

    # 2. Setup Entity Schemas
    schema = EntityTypeSchema("agent")
    schema.add_property(PropertyDefinition("cell_x", PropertyType.INT64, default_value=0))
    schema.add_property(PropertyDefinition("cell_y", PropertyType.INT64, default_value=0))
    schema.add_property(PropertyDefinition("energy", PropertyType.INT64, default_value=100))
    schema.add_property(PropertyDefinition("hydration", PropertyType.INT64, default_value=100))
    schema.add_property(PropertyDefinition("age", PropertyType.INT64, default_value=0))
    world.schema_registry.register_type(schema)

    # 3. Populate 300 Agents distributed across spatial grid cells
    # e.g. 5x6 = 30 cells (10 agents per cell)
    cell_coords = [(cx, cy) for cx in range(5) for cy in range(6)][:num_cells]
    for i in range(num_agents):
        cell = cell_coords[i % len(cell_coords)]
        ent = world.entities.create_entity(
            "agent",
            0,
            {
                "cell_x": cell[0],
                "cell_y": cell[1],
                "energy": 100,
                "hydration": 100,
                "age": 0,
            },
            world.schema_registry,
        )
        world.place_entity_in_cell(ent.id, cell[0], cell[1])

    # 4. Install Spatial-Partitioned Rules
    parser = GRLParser()

    # Rule 1: Metabolism (runs per cell, consumes energy & increments age)
    rule1_dict = {
        "rule_id": "r_agent_metabolism",
        "name": "Agent Metabolism",
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
                "delta": {"op": "LITERAL", "type": "INT64", "value": "-1"},
            },
            {
                "op": "ADJUST_PROPERTY",
                "entity": "target",
                "property": "age",
                "delta": {"op": "LITERAL", "type": "INT64", "value": "1"},
            },
        ],
    }
    world.register_rule(parser.parse_rule(rule1_dict))

    # Rule 2: Hydration decay with precondition check
    rule2_dict = {
        "rule_id": "r_hydration_decay",
        "name": "Hydration Decay",
        "version": "1.0.0",
        "priority": 9,
        "spatial_partitioned": True,
        "target_selector": {
            "entity_type": "agent",
            "filter": {
                "op": "GREATER_THAN",
                "left": {"op": "GET_PROPERTY", "entity": "target", "property": "hydration"},
                "right": {"op": "LITERAL", "type": "INT64", "value": "10"},
            },
        },
        "effects": [
            {
                "op": "ADJUST_PROPERTY",
                "entity": "target",
                "property": "hydration",
                "delta": {"op": "LITERAL", "type": "INT64", "value": "-1"},
            },
        ],
    }
    world.register_rule(parser.parse_rule(rule2_dict))

    # Rule 3: Environmental Replenishment (Global rule, priority 5)
    rule3_dict = {
        "rule_id": "r_env_replenish",
        "name": "Environmental Replenishment",
        "version": "1.0.0",
        "priority": 5,
        "spatial_partitioned": False,
        "effects": [
            {
                "op": "PRODUCE_RESOURCE",
                "pool": "biomass",
                "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "5000000"},
            },
            {
                "op": "PRODUCE_RESOURCE",
                "pool": "water",
                "amount": {"op": "LITERAL", "type": "FIXED_POINT", "value": "2000000"},
            },
        ],
    }
    world.register_rule(parser.parse_rule(rule3_dict))

    # Warmup 1 tick to activate rules (prospective activation tick + 1)
    world.advance_tick()

    # 5. Execute benchmark loop
    start_time = time.perf_counter()
    for _ in range(num_ticks):
        world.advance_tick()
    elapsed_time = time.perf_counter() - start_time

    # Calculate total operations from journal records
    total_ops = 0
    total_rule_executions = 0
    for record in world.event_journal.records:
        if record.event_type == "rule_executed_success" and record.tick > 1:
            total_ops += int(record.payload.get("operations_consumed", 0))
            total_rule_executions += 1

    ops_per_second = total_ops / elapsed_time if elapsed_time > 0 else 0
    ticks_per_second = num_ticks / elapsed_time if elapsed_time > 0 else 0
    ms_per_tick = (elapsed_time / num_ticks) * 1000.0 if num_ticks > 0 else 0
    ops_per_tick = total_ops / num_ticks if num_ticks > 0 else 0

    projected_seconds_3650 = 3650 / ticks_per_second if ticks_per_second > 0 else 0
    projected_seconds_36500 = 36500 / ticks_per_second if ticks_per_second > 0 else 0

    return {
        "num_agents": num_agents,
        "num_cells": num_cells,
        "num_ticks": num_ticks,
        "elapsed_seconds": elapsed_time,
        "total_operations": total_ops,
        "total_rule_executions": total_rule_executions,
        "ops_per_second": ops_per_second,
        "ticks_per_second": ticks_per_second,
        "ms_per_tick": ms_per_tick,
        "ops_per_tick": ops_per_tick,
        "projected_time_3650_ticks_s": projected_seconds_3650,
        "projected_time_36500_ticks_s": projected_seconds_36500,
    }


def print_benchmark_report(results: Dict[str, Any]) -> None:
    """Print formatted benchmark results."""
    print("=" * 70)
    print(" GENESIS ALPHA SUBSTRATE BENCHMARK REPORT (Option A: Spatial Partitioning)")
    print("=" * 70)
    print(f" Agents:                 {results['num_agents']}")
    print(f" Spatial Cells:          {results['num_cells']} (avg {results['num_agents'] // results['num_cells']} agents/cell)")
    print(f" Measured Ticks:         {results['num_ticks']}")
    print(f" Elapsed Wall-Clock:     {results['elapsed_seconds']:.4f} s")
    print(f" Total GRL Operations:   {results['total_operations']:,}")
    print(f" Total Rule Executions:  {results['total_rule_executions']:,}")
    print("-" * 70)
    print(f" Interpreter Speed:      {results['ops_per_second']:,.1f} ops/sec")
    print(f" Simulation Throughput:  {results['ticks_per_second']:,.1f} ticks/sec ({results['ms_per_tick']:.2f} ms/tick)")
    print(f" Workload Density:       {results['ops_per_tick']:,.1f} ops/tick")
    print("-" * 70)
    print(" PROJECTED RUNTIMES (300 AGENTS):")
    p3650 = results['projected_time_3650_ticks_s']
    p36500 = results['projected_time_36500_ticks_s']
    print(f"   3,650 ticks   (10 years):   {p3650:.2f} seconds ({p3650 / 60.0:.2f} minutes)")
    print(f"  36,500 ticks  (100 years):   {p36500:.2f} seconds ({p36500 / 60.0:.2f} minutes / {p36500 / 3600.0:.2f} hours)")
    print("=" * 70)


class TestBenchmark(unittest.TestCase):

    def test_benchmark_run(self):
        """Execute benchmark and verify throughput."""
        res = run_benchmark(num_ticks=50, num_agents=300, num_cells=30)
        self.assertGreater(res["total_operations"], 0)
        self.assertGreater(res["ops_per_second"], 1000)
        print_benchmark_report(res)


if __name__ == "__main__":
    results = run_benchmark(num_ticks=100, num_agents=300, num_cells=30)
    print_benchmark_report(results)
