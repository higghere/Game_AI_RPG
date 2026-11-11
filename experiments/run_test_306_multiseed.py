"""TEST-306 Multi-Seed Starvation-Survival Experiment (10 Seeds).

Evaluates starvation-survival selection for low metabolic rate across 10 random seeds
with tracked births, deaths, living counts, allele frequencies f(low), and deterministic state hashes.
"""

import tempfile
from pathlib import Path
from genesis.core.arithmetic import FixedPoint
from genesis.ecosystem import load_ecosystem_schemas, load_ecosystem_resources
from genesis.agents.loader import load_agents
from genesis.substrate.world_state import WorldState
from tests.test_agents_phase3 import create_test_agent, create_test_plant


def run_test_306_multiseed():
    seeds = [42, 101, 202, 303, 404, 505, 606, 707, 808, 909]

    print("=" * 105)
    print("TEST-306: MULTI-SEED (10 SEEDS) RESOURCE-BOUND SELECTION & ALLELE FREQUENCIES")
    print("=" * 105)

    print(f"\n{'Seed':<6} | {'Founders':<10} | {'Deaths':<8} | {'Surviving Eff':<14} | {'Surviving Profl':<16} | {'Final Eff %':<12} | {'State Hash (16 hex)':<20} | {'Journal Hash (16 hex)'}")
    print("-" * 115)

    for seed in seeds:
        with tempfile.TemporaryDirectory() as td:
            w = WorldState(seed=seed, journal_dir=Path(td))
            load_ecosystem_schemas(w.schema_registry)
            load_ecosystem_resources(w.resources)
            load_agents(w)

            # Food plant with binding biomass (30.0 biomass, cap 30.0)
            plant_id = create_test_plant(w, cell_x=0, cell_y=0, biomass=30.0, energy=50.0)

            # 4 Efficient agents (2 pairs: sex 0, 1)
            eff_founder_ids = []
            for i in range(4):
                aid = create_test_agent(
                    w, cell_x=0, cell_y=0, sex=i % 2, biomass=40.0, energy=80.0,
                    metabolic_rate=0.5, gene_metabolic_rate=50, age_ticks=50,
                )
                eff_founder_ids.append(aid)

            # 4 Profligate agents (2 pairs: sex 0, 1)
            profl_founder_ids = []
            for i in range(4):
                aid = create_test_agent(
                    w, cell_x=0, cell_y=0, sex=i % 2, biomass=40.0, energy=80.0,
                    metabolic_rate=1.8, gene_metabolic_rate=180, age_ticks=50,
                )
                profl_founder_ids.append(aid)

            for t in range(200):
                w.advance_tick()

            s_hash = w.compute_state_hash(include_journal=False)[:16]
            j_hash = w.event_journal.hash_through_tick(200)[:16]

            living_final = [e for e in w.entities._entities.values() if e.entity_type == "agent" and e.get_property("is_alive") == 1]
            final_eff = sum(1 for e in living_final if e.get_property("gene_metabolic_rate") <= 100)
            final_profl = sum(1 for e in living_final if e.get_property("gene_metabolic_rate") > 100)

            records = w.event_journal.records
            deaths = len([r for r in records if r.event_type == "entity_destroyed" and r.payload.get("entity_type") == "agent"])

            tot = len(living_final)
            eff_pct = (final_eff / tot * 100.0) if tot > 0 else 0.0

            print(f"{seed:<6} | {'8 (4E+4P)':<10} | {deaths:<8} | {final_eff:<14} | {final_profl:<16} | {eff_pct:5.1f}%       | {s_hash:<20} | {j_hash}")


if __name__ == "__main__":
    run_test_306_multiseed()
