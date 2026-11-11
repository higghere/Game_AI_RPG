"""Pre-registered 100-Year Experiment: 300 Agents (Population Allowed to Grow).

Config:
  Initial Population: 300 agents (150 pairs across 15x10 grid)
  Ecosystem Plants: 150 autotrophs, cap=25.0, replenish=0.80/tick
  Duration: 100 years = 36,500 ticks
  Substrate Limits: 1,000 entities touched per tick, 256 ops/rule
"""

import sys
import time
from pathlib import Path
import tempfile
from genesis.core.arithmetic import FixedPoint
from genesis.ecosystem import load_ecosystem_schemas, load_ecosystem_resources
from genesis.agents.loader import load_agents
from genesis.substrate.world_state import WorldState
from tests.test_agents_phase3 import create_test_agent, create_test_plant


def run_300agent_growing_100y():
    print("=" * 80, flush=True)
    print("GENESIS TEST-303 FULL 100-YEAR RUN AT 300 AGENTS (POPULATION GROWING)", flush=True)
    print("Pre-registered Configuration:", flush=True)
    print("  Initial Population: 300 agents (150 pairs across 15x10 grid)", flush=True)
    print("  Ecosystem Plants: 150 autotrophs, cap=25.0, replenish=0.80/tick", flush=True)
    print("  Duration: 100 years = 36,500 ticks", flush=True)
    print("=" * 80, flush=True)

    with tempfile.TemporaryDirectory() as td:
        world = WorldState(seed=303, journal_dir=Path(td))
        load_ecosystem_schemas(world.schema_registry)
        load_ecosystem_resources(world.resources)
        load_agents(world)

        grid_w, grid_h = 15, 10
        autotroph_eids = []
        for x in range(grid_w):
            for y in range(grid_h):
                eid = create_test_plant(world, cell_x=x, cell_y=y, biomass=25.0, energy=50.0)
                autotroph_eids.append(eid)

        # 150 pairs = 300 initial agents
        for x in range(grid_w):
            for y in range(grid_h):
                create_test_agent(world, cell_x=x, cell_y=y, sex=0, biomass=50.0, energy=100.0)
                create_test_agent(world, cell_x=x, cell_y=y, sex=1, biomass=50.0, energy=100.0)

        total_years = 100
        ticks_per_year = 365
        total_ticks = total_years * ticks_per_year

        trajectory = []
        peak_entities_touched = 0
        peak_cell_density = 0
        t0 = time.time()

        cap_val = FixedPoint.from_decimal_string("25.000000")
        repl_val = FixedPoint.from_decimal_string("0.800000")
        autos = [world.entities.get_entity(eid) for eid in autotroph_eids]

        for tick in range(1, total_ticks + 1):
            for auto in autos:
                if auto and auto.is_active:
                    cur = auto.get_property("biomass")
                    if cur < cap_val:
                        nxt = cur + repl_val
                        auto.set_property("biomass", nxt if nxt < cap_val else cap_val)

            world.advance_tick()

            touched = len(world.entities_touched_this_tick)
            if touched > peak_entities_touched:
                peak_entities_touched = touched

            if tick % (10 * ticks_per_year) == 0:  # Every 10 years
                year = tick // ticks_per_year
                living = [e for e in world.entities._entities.values() if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1]
                count = len(living)
                cell_counts = {}
                for e in living:
                    pos = (e.get_property("cell_x"), e.get_property("cell_y"))
                    cell_counts[pos] = cell_counts.get(pos, 0) + 1
                max_cell = max(cell_counts.values()) if cell_counts else 0
                if max_cell > peak_cell_density:
                    peak_cell_density = max_cell

                elapsed = time.time() - t0
                rate = tick / elapsed if elapsed > 0 else 0
                trajectory.append((year, tick, count, max_cell, peak_entities_touched, rate))
                print(f"Year {year:3d} (tick {tick:5d}): Pop={count:3d}, Max/Cell={max_cell:2d}, PeakTouched={peak_entities_touched:3d}, Elapsed={elapsed:5.1f}s ({rate:5.1f} t/s)", flush=True)

        total_elapsed = time.time() - t0
        quota_fails = [r for r in world.event_journal.records if r.event_type == "rule_execution_failed" and r.payload.get("error_type") == "QuotaExceededError"]

        print("\n" + "=" * 80, flush=True)
        print("FINAL RESULTS - 300-AGENT GROWING 100-YEAR RUN", flush=True)
        print("=" * 80, flush=True)
        print(f"Total Simulated Time: 100 years ({total_ticks} ticks)")
        print(f"Wall-Clock Runtime:   {total_elapsed:.2f} s ({total_ticks/total_elapsed:.1f} ticks/s)")
        print(f"Initial Population:   300 agents (150 pairs)")
        print(f"Final Population:     {count} living agents")
        print(f"Peak Cell Density:    {peak_cell_density} agents / cell")
        print(f"Peak Touched / Tick:  {peak_entities_touched} entities (< 1,000 limit)")
        print(f"Quota Failures:       {len(quota_fails)} (Zero Quota Invariant)")
        print("=" * 80, flush=True)


if __name__ == "__main__":
    run_300agent_growing_100y()
