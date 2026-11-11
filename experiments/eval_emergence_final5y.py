import tempfile
import json
from pathlib import Path
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

def run_emergence_eval():
    p = load_agents_params("v2", verify_hash=True)
    b_data = p["emergence_binding"]
    binding = AnalysisBinding(
        agent_entity_types=("agent",),
        pos_x_prop=b_data["pos_x_prop"],
        pos_y_prop=b_data["pos_y_prop"],
        alive_prop=b_data["alive_prop"],
        parent_edge_kind=b_data.get("parent_edge_kind", "parent_of"),
    )

    print("=" * 80)
    print("EMERGENCE EVALUATION: FINAL 5 YEARS OF 100-YEAR RUNS (TICKS 34,675 TO 36,500)")
    print("=" * 80)

    # 1. 100-founder Run
    print("\n[1/2] Running 100-Founder Simulation to Year 100...")
    with tempfile.TemporaryDirectory() as td:
        w100 = WorldState(seed=42, journal_dir=Path(td))
        load_ecosystem_schemas(w100.schema_registry)
        load_ecosystem_resources(w100.resources)
        load_agents(w100)

        grid_w, grid_h = 10, 5
        plants = []
        for x in range(grid_w):
            for y in range(grid_h):
                eid = create_test_plant(w100, cell_x=x, cell_y=y, biomass=25.0, energy=50.0)
                plants.append(w100.entities.get_entity(eid))
        for x in range(grid_w):
            for y in range(grid_h):
                create_test_agent(w100, cell_x=x, cell_y=y, sex=0, biomass=50.0, energy=100.0)
                create_test_agent(w100, cell_x=x, cell_y=y, sex=1, biomass=50.0, energy=100.0)

        cap_val = FixedPoint.from_decimal_string("25.000000")
        repl_val = FixedPoint.from_decimal_string("0.800000")

        sample_history_100 = []

        for t in range(1, 36501):
            for p_ent in plants:
                if p_ent and p_ent.is_active:
                    cur = p_ent.get_property("biomass")
                    if cur < cap_val:
                        p_ent.set_property("biomass", min(cap_val, cur + repl_val))
            w100.advance_tick()

            # Record annual samples during final 5 years (ticks 34675, 35040, 35405, 35770, 36135, 36500)
            if t >= 34675 and (t - 34675) % 365 == 0:
                living = []
                for e in w100.entities._entities.values():
                    if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1:
                        living.append({"id": e.id, "x": e.get_property("cell_x"), "y": e.get_property("cell_y"), "entity": e})
                sample_history_100.append({"tick": t, "agents": living})

        v_settle_100 = evaluate_settlement(w100, binding, sample_history=sample_history_100)
        v_group_100 = evaluate_group(w100, binding, window_start_tick=34675, window_end_tick=36500)
        v_culture_100 = evaluate_cultural_spread(w100, binding, window_start_tick=34675, eval_tick=36500)

        print("\n--- 100-Founder Final 5-Year Emergence Verdicts ---")
        print("Settlement Verdict:\n", json.dumps(v_settle_100, indent=2))
        print("Group Verdict:\n", json.dumps(v_group_100, indent=2))
        print("Culture Verdict:\n", json.dumps(v_culture_100, indent=2))

    # 2. 300-Agent Growing Run
    print("\n[2/2] Running 300-Agent Simulation to Year 100...")
    with tempfile.TemporaryDirectory() as td:
        w300 = WorldState(seed=303, journal_dir=Path(td))
        load_ecosystem_schemas(w300.schema_registry)
        load_ecosystem_resources(w300.resources)
        load_agents(w300)

        grid_w, grid_h = 15, 10
        plants = []
        for x in range(grid_w):
            for y in range(grid_h):
                eid = create_test_plant(w300, cell_x=x, cell_y=y, biomass=25.0, energy=50.0)
                plants.append(w300.entities.get_entity(eid))
        for x in range(grid_w):
            for y in range(grid_h):
                create_test_agent(w300, cell_x=x, cell_y=y, sex=0, biomass=50.0, energy=100.0)
                create_test_agent(w300, cell_x=x, cell_y=y, sex=1, biomass=50.0, energy=100.0)

        sample_history_300 = []

        for t in range(1, 36501):
            for p_ent in plants:
                if p_ent and p_ent.is_active:
                    cur = p_ent.get_property("biomass")
                    if cur < cap_val:
                        p_ent.set_property("biomass", min(cap_val, cur + repl_val))
            w300.advance_tick()

            if t >= 34675 and (t - 34675) % 365 == 0:
                living = []
                for e in w300.entities._entities.values():
                    if e.is_active and e.entity_type == "agent" and e.get_property("is_alive") == 1:
                        living.append({"id": e.id, "x": e.get_property("cell_x"), "y": e.get_property("cell_y"), "entity": e})
                sample_history_300.append({"tick": t, "agents": living})

        v_settle_300 = evaluate_settlement(w300, binding, sample_history=sample_history_300)
        v_group_300 = evaluate_group(w300, binding, window_start_tick=34675, window_end_tick=36500)
        v_culture_300 = evaluate_cultural_spread(w300, binding, window_start_tick=34675, eval_tick=36500)

        print("\n--- 300-Agent Growing Final 5-Year Emergence Verdicts ---")
        print("Settlement Verdict:\n", json.dumps(v_settle_300, indent=2))
        print("Group Verdict:\n", json.dumps(v_group_300, indent=2))
        print("Culture Verdict:\n", json.dumps(v_culture_300, indent=2))

if __name__ == "__main__":
    run_emergence_eval()
