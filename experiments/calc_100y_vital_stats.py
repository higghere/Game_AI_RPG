import time
from pathlib import Path
import tempfile
import json
from genesis.core.arithmetic import FixedPoint
from genesis.ecosystem import load_ecosystem_schemas, load_ecosystem_resources
from genesis.agents.loader import load_agents
from genesis.substrate.world_state import WorldState
from tests.test_agents_phase3 import create_test_agent, create_test_plant

def compute_vital_stats():
    print("=" * 80, flush=True)
    print("CALCULATING 100-YEAR RUN VITAL STATISTICS (36,500 TICKS)", flush=True)
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

        birth_ticks = {}
        living_agents = set()

        # 100 founders
        for x in range(grid_w):
            for y in range(grid_h):
                f_id = create_test_agent(world, cell_x=x, cell_y=y, sex=0, biomass=50.0, energy=100.0)
                m_id = create_test_agent(world, cell_x=x, cell_y=y, sex=1, biomass=50.0, energy=100.0)
                birth_ticks[f_id] = 0
                birth_ticks[m_id] = 0
                living_agents.add(f_id)
                living_agents.add(m_id)

        cap_val = FixedPoint.from_decimal_string("25.000000")
        repl_val = FixedPoint.from_decimal_string("0.800000")
        autos = [world.entities.get_entity(eid) for eid in autotroph_eids]

        total_ticks = 36500
        ticks_per_year = 365
        
        annual_births = [0] * 100
        annual_deaths = [0] * 100
        
        ages_at_death = []
        generation_times = []  # parent age in ticks when child was born

        t0 = time.time()
        for tick in range(1, total_ticks + 1):
            year_idx = (tick - 1) // ticks_per_year

            # Replenish plants
            for auto in autos:
                if auto and auto.is_active:
                    cur = auto.get_property("biomass")
                    if cur < cap_val:
                        nxt = cur + repl_val
                        auto.set_property("biomass", nxt if nxt < cap_val else cap_val)

            world.advance_tick()

            # Detect current living agents
            current_active = {
                eid for eid, e in world.entities._entities.items()
                if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1
            }

            # New births
            born = current_active - living_agents
            for nid in born:
                birth_ticks[nid] = tick
                annual_births[year_idx] += 1
                
                # Check incoming parent_of edges
                incoming = world.relationships.get_incoming(nid, rel_type="parent_of")
                for edge in incoming:
                    p_birth = birth_ticks.get(edge.source_id, 0)
                    gen_time = tick - p_birth
                    generation_times.append(gen_time)

            # Deaths
            died = living_agents - current_active
            for did in died:
                b_tick = birth_ticks.get(did, 0)
                lifespan = tick - b_tick
                ages_at_death.append(lifespan)
                annual_deaths[year_idx] += 1

            living_agents = current_active

            if tick % (10 * ticks_per_year) == 0:
                elapsed = time.time() - t0
                yr = tick // ticks_per_year
                print(f"Year {yr:3d} (tick {tick:5d}): Pop={len(living_agents):3d}, TotalBirths={sum(annual_births):4d}, TotalDeaths={sum(annual_deaths):4d}, Elapsed={elapsed:5.1f}s", flush=True)

        print("\n" + "=" * 80, flush=True)
        print("100-FOUNDER 100-YEAR RUN VITAL STATISTICS RESULTS", flush=True)
        print("=" * 80, flush=True)
        total_b = sum(annual_births)
        total_d = sum(annual_deaths)
        mean_births_per_year = total_b / 100.0
        mean_deaths_per_year = total_d / 100.0
        
        mean_age_at_death_ticks = sum(ages_at_death) / len(ages_at_death) if ages_at_death else 0.0
        mean_age_at_death_years = mean_age_at_death_ticks / 365.0
        
        mean_gen_time_ticks = sum(generation_times) / len(generation_times) if generation_times else 0.0
        mean_gen_time_years = mean_gen_time_ticks / 365.0

        print(f"Total Births: {total_b} ({mean_births_per_year:.2f} births/year)", flush=True)
        print(f"Total Deaths: {total_d} ({mean_deaths_per_year:.2f} deaths/year)", flush=True)
        print(f"Mean Age at Death: {mean_age_at_death_ticks:.1f} ticks ({mean_age_at_death_years:.2f} years)", flush=True)
        print(f"Mean Generation Time: {mean_gen_time_ticks:.1f} ticks ({mean_gen_time_years:.2f} years)", flush=True)
        
        print("\nAnnual Births and Deaths Summary (Decadal Brackets):", flush=True)
        for decade in range(10):
            d_b = sum(annual_births[decade*10 : (decade+1)*10])
            d_d = sum(annual_deaths[decade*10 : (decade+1)*10])
            print(f"Years {decade*10+1:2d}-{decade*10+10:3d}: Births={d_b:3d} ({d_b/10.0:.1f}/yr), Deaths={d_d:3d} ({d_d/10.0:.1f}/yr)", flush=True)

        out_path = Path("experiments/100y_vital_stats.json")
        with open(out_path, "w") as out:
            json.dump({
                "total_births": total_b,
                "total_deaths": total_d,
                "mean_births_per_year": mean_births_per_year,
                "mean_deaths_per_year": mean_deaths_per_year,
                "mean_age_at_death_ticks": mean_age_at_death_ticks,
                "mean_age_at_death_years": mean_age_at_death_years,
                "mean_generation_time_ticks": mean_gen_time_ticks,
                "mean_generation_time_years": mean_gen_time_years,
                "annual_births": annual_births,
                "annual_deaths": annual_deaths,
            }, out, indent=2)
        print(f"\nSaved vital statistics to {out_path}", flush=True)

if __name__ == "__main__":
    compute_vital_stats()
