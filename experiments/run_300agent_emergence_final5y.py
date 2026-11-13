import time
from pathlib import Path
import tempfile
import json
from genesis.core.arithmetic import FixedPoint
from genesis.ecosystem import load_ecosystem_schemas, load_ecosystem_resources
from genesis.agents.loader import load_agents
from genesis.agents.params import load_agents_params
from genesis.analysis.binding import AnalysisBinding
from genesis.analysis.settlement import evaluate_settlement
from genesis.analysis.group import evaluate_group
from genesis.analysis.culture import evaluate_cultural_spread
from genesis.substrate.world_state import WorldState
from tests.test_agents_phase3 import create_test_agent, create_test_plant

def run_300agent_final5y():
    print("=" * 80, flush=True)
    print("RUNNING 300-AGENT SIMULATION TO YEAR 100 FOR FINAL 5-YEAR EMERGENCE EVAL", flush=True)
    print("=" * 80, flush=True)

    p = load_agents_params("v3", verify_hash=True)
    b_data = p["emergence_binding"]
    binding = AnalysisBinding(
        agent_entity_types=("agent",),
        pos_x_prop=b_data["pos_x_prop"],
        pos_y_prop=b_data["pos_y_prop"],
        alive_prop=b_data["alive_prop"],
        parent_edge_kind=b_data.get("parent_edge_kind", "parent_of"),
    )

    with tempfile.TemporaryDirectory() as td:
        world = WorldState(seed=303, journal_dir=Path(td))
        load_ecosystem_schemas(world.schema_registry)
        load_ecosystem_resources(world.resources)
        load_agents(world)

        grid_w, grid_h = 15, 10
        plants = []
        for x in range(grid_w):
            for y in range(grid_h):
                eid = create_test_plant(world, cell_x=x, cell_y=y, biomass=25.0, energy=50.0)
                plants.append(world.entities.get_entity(eid))

        for x in range(grid_w):
            for y in range(grid_h):
                create_test_agent(world, cell_x=x, cell_y=y, sex=0, biomass=50.0, energy=100.0)
                create_test_agent(world, cell_x=x, cell_y=y, sex=1, biomass=50.0, energy=100.0)

        cap_val = FixedPoint.from_decimal_string("25.000000")
        repl_val = FixedPoint.from_decimal_string("0.800000")

        total_ticks = 36500
        ticks_per_year = 365
        sample_history = []

        t0 = time.time()
        for tick in range(1, total_ticks + 1):
            for p_ent in plants:
                if p_ent and p_ent.is_active:
                    cur = p_ent.get_property("biomass")
                    if cur < cap_val:
                        nxt = cur + repl_val
                        p_ent.set_property("biomass", nxt if nxt < cap_val else cap_val)

            world.advance_tick()

            # Record annual samples during final 5 years (ticks 34675, 35040, 35405, 35770, 36135, 36500)
            if tick >= 34675 and (tick - 34675) % 365 == 0:
                living = []
                for e in world.entities._entities.values():
                    if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1:
                        living.append({"id": e.id, "x": e.get_property("cell_x"), "y": e.get_property("cell_y"), "entity": e})
                sample_history.append({"tick": tick, "agents": living})

            if tick % (10 * ticks_per_year) == 0:
                elapsed = time.time() - t0
                yr = tick // ticks_per_year
                living_cnt = sum(1 for e in world.entities._entities.values() if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1)
                print(f"Year {yr:3d} (tick {tick:5d}): Pop={living_cnt:3d}, Elapsed={elapsed:5.1f}s ({tick/elapsed:4.1f} t/s)", flush=True)

        print("\nEvaluating final 5-year emergence metrics...", flush=True)
        v_settle = evaluate_settlement(world, binding, sample_history=sample_history)

        # Unbound phenomena with passed: None (null in JSON)
        v_group = {
            "phenomenon": "group",
            "status": "NOT_APPLICABLE",
            "passed": None,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": 34675,
                "end_tick": 36500,
                "years": 5
            },
            "reason": b_data["not_applicable_reasons"]["group_emergence"],
            "sub_criteria": {},
            "failure_reasons": []
        }

        v_culture = {
            "phenomenon": "cultural_spread",
            "status": "NOT_APPLICABLE",
            "passed": None,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": 34675,
                "end_tick": 36500,
                "years": 5
            },
            "reason": b_data["not_applicable_reasons"]["cultural_spread"],
            "sub_criteria": {},
            "failure_reasons": []
        }

        result = {
            "settlement": v_settle,
            "group": v_group,
            "cultural_spread": v_culture
        }

        out_path = Path("experiments/300agent_final5y_verdicts.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        print(f"\nSaved verdicts to {out_path}", flush=True)
        print("\n--- SETTLEMENT VERDICT ---", flush=True)
        print(json.dumps(v_settle, indent=2), flush=True)
        print("\n--- GROUP VERDICT ---", flush=True)
        print(json.dumps(v_group, indent=2), flush=True)
        print("\n--- CULTURE VERDICT ---", flush=True)
        print(json.dumps(v_culture, indent=2), flush=True)

if __name__ == "__main__":
    run_300agent_final5y()
