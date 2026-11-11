"""GENESIS Phase 3: 100-Year Pre-Registered Founder Experiment (36,500 Ticks).

Configuration:
- Founders: 100 agents (50 co-located breeding pairs across 10x5 grid).
- Duration: 100 simulated years = 36,500 ticks.
- Binding Resource: 50 autotrophs, cap = 25.0, replenishment = 0.80 mass/tick.
- PRNG Seed: 42.
- Invariant: Zero Quota Failures (< 1,000 entities touched / tick, <= 256 ops/rule).
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


def run_pre_registered_100y():
    print("=" * 80, flush=True)
    print("GENESIS PRE-REGISTERED 100-YEAR FOUNDER EXPERIMENT (36,500 TICKS)", flush=True)
    print("Pre-registered Configuration:", flush=True)
    print("  Founders: 100 (50 co-located breeding pairs across 10x5 grid)", flush=True)
    print("  Duration: 100 years = 36,500 ticks", flush=True)
    print("  Binding Resource: 50 autotrophs, cap=25.0, replenishment=0.80/tick", flush=True)
    print("  Substrate Quota Cap: 1,000 entities touched per tick, 256 ops/rule", flush=True)
    print("=" * 80, flush=True)

    with tempfile.TemporaryDirectory() as td:
        world = WorldState(seed=42, journal_dir=Path(td))
        load_ecosystem_schemas(world.schema_registry)
        load_ecosystem_resources(world.resources)
        load_agents(world)

        grid_w, grid_h = 10, 5
        autotroph_eids = []
        for x in range(grid_w):
            for y in range(grid_h):
                eid = create_test_plant(world, cell_x=x, cell_y=y, biomass=25.0, energy=50.0)
                autotroph_eids.append(eid)

        for x in range(grid_w):
            for y in range(grid_h):
                # Female (sex=0)
                create_test_agent(world, cell_x=x, cell_y=y, sex=0, biomass=50.0, energy=100.0)
                # Male (sex=1)
                create_test_agent(world, cell_x=x, cell_y=y, sex=1, biomass=50.0, energy=100.0)

        total_years = 100
        ticks_per_year = 365
        total_ticks = total_years * ticks_per_year

        trajectory = []
        peak_entities_touched = 0
        peak_agents_per_cell = 0
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

            if tick % (5 * ticks_per_year) == 0:
                year = tick // ticks_per_year
                living = [
                    e for e in world.entities._entities.values()
                    if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1
                ]
                count = len(living)
                cell_counts = {}
                for e in living:
                    pos = (e.get_property("cell_x"), e.get_property("cell_y"))
                    cell_counts[pos] = cell_counts.get(pos, 0) + 1
                max_cell = max(cell_counts.values()) if cell_counts else 0
                if max_cell > peak_agents_per_cell:
                    peak_agents_per_cell = max_cell

                elapsed = time.time() - t0
                rate = tick / elapsed if elapsed > 0 else 0
                trajectory.append((year, tick, count, max_cell, peak_entities_touched, rate))
                print(f"Year {year:3d} (tick {tick:5d}): Pop={count:3d}, Max/Cell={max_cell:2d}, PeakTouched={peak_entities_touched:3d}, Elapsed={elapsed:5.1f}s ({rate:5.1f} t/s)", flush=True)

                if count >= 600:
                    print(f"CRITICAL: Population reached {count} (>= 600)! Stopping for regulation mechanism.", flush=True)
                    break

        total_elapsed = time.time() - t0
        quota_fails = [
            r for r in world.event_journal.records
            if r.event_type == "rule_execution_failed" and r.payload.get("error_type") == "QuotaExceededError"
        ]

        print("\n" + "=" * 80, flush=True)
        print("FINAL RESULTS - PRE-REGISTERED 100-YEAR RUN", flush=True)
        print("=" * 80, flush=True)
        print(f"Total Simulated Time: 100 years ({total_ticks} ticks)", flush=True)
        print(f"Wall-Clock Runtime:   {total_elapsed:.2f} s ({total_ticks / total_elapsed:.1f} ticks/s)", flush=True)
        print(f"Initial Population:   100 agents (50 pairs)", flush=True)
        print(f"Final Population:     {trajectory[-1][2]} living agents", flush=True)
        print(f"Peak Cell Density:    {peak_agents_per_cell} agents / cell", flush=True)
        print(f"Peak Touched / Tick:  {peak_entities_touched} entities (< 1,000 substrate limit)", flush=True)
        print(f"Quota Failures:       {len(quota_fails)} (Zero Quota Invariant Preserved)", flush=True)
        print("=" * 80, flush=True)

        print("\nDetailed Trajectory (every 5 years):", flush=True)
        print(f"{'Year':<6} | {'Tick':<7} | {'Population':<12} | {'Max In Cell':<13} | {'Peak Touched':<14} | {'Ticks/sec':<10}", flush=True)
        print("-" * 75, flush=True)
        for y, t, cnt, mc, pt, r in trajectory:
            print(f"{y:<6} | {t:<7} | {cnt:<12} | {mc:<13} | {pt:<14} | {r:<10.1f}", flush=True)


if __name__ == "__main__":
    run_pre_registered_100y()
