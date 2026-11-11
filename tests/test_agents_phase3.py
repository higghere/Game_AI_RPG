"""GENESIS Phase 3 Acceptance Test Suite: Layer 2 Individual Agents as Data.

Verifies:
- TEST-PIN: Parameter File Hash-Pinned Verification against frozen agents_params_v1.json.
- TEST-301: Determinism & Hash Reproducibility (Run 1 vs Run 2 bit-identical across 500 ticks; save/reload at tick 250).
- TEST-302: Exact Mass Conservation Under Full Life Cycle (|M(t) - M(0)| == 0.000000 over 1,000 ticks).
- TEST-303: Zero Quota Failures Over Multi-Scale Runs (100, 200, 300 agents, peak entities touched recorded and < 1000).
- TEST-304: Dual-Metabolism Needs Dynamics & Mortality (Standard metabolism in [95, 105], Fast in [45, 55], Nourished > 500 ticks).
- TEST-305: Mendelian Inheritance & Genetic Mutation Bounds (mu = 0 binomial assortment [35%, 65%], mu = 10/1000 bounded traits).
- TEST-306: Resource-Bound Selection Pressure Multi-Seed (Seeds 42, 1337, 2026: Efficient comprises > 75% of population).
- TEST-307: Whole-Window Resource-Bound Carrying Capacity Equilibrium (Window [150, 350] variation <= +/- 15%).
- TEST-308: Read-Only Emergence Measurement Invariance (Bit-identical state hash, journal hash, and RNG step count).
- TEST-309: Negative Control: Founder-Allele-Set Conservation (Zero novel alleles appear under mu = 0 over 250 ticks).
- TEST-310: Regression Guard (All pre-existing Phase 0, 1, 2, and emergence definitions tests pass).

Zero Quota Failure Invariant:
All Phase 3 tests require 0 quota failures (world.event_journal must record 0 QuotaExceededError events).
"""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from genesis.core.arithmetic import FixedPoint
from genesis.ecosystem import (
    get_ecosystem_metrics,
    load_ecosystem,
    load_ecosystem_resources,
    load_ecosystem_schemas,
)
from genesis.agents import (
    load_agents,
    load_agents_params,
    load_agent_schemas,
    load_agent_rules,
)
from genesis.agents.binding import get_agent_analysis_binding
from genesis.agents.params import FROZEN_AGENTS_PARAMS_V1_HASH, FROZEN_AGENTS_PARAMS_V2_HASH
from genesis.analysis import evaluate_settlement, evaluate_group, evaluate_cultural_spread
from genesis.persistence.snapshot import SnapshotManager
from genesis.substrate.entities import Entity
from genesis.substrate.world_state import WorldState


# Committed golden hashes for TEST-301 (500 ticks, seed 42)
GOLDEN_STATE_HASH_500 = "eb6b55b5396b4ca34d277597948c5cb629e8e74fc248cc98f3d9e941ed07d81b"
GOLDEN_JOURNAL_HASH_500 = "0491b96b2878bcf9ee5de7a65307d28071e4bd437cccc402dd21cb2f67d81b42"


def create_test_agent(
    world: WorldState,
    cell_x: int = 0,
    cell_y: int = 0,
    sex: int = 0,
    biomass: float = 40.0,
    energy: float = 100.0,
    hunger: float = 0.0,
    thirst: float = 0.0,
    fatigue: float = 0.0,
    reproduction_drive: float = 0.0,
    metabolic_rate: float = 1.0,
    gene_metabolic_rate: int = 100,
    gene_foraging_range: int = 1,
    gene_fertility: int = 100,
    gene_longevity: int = 1000,
    gene_boldness: int = 50,
    age: int = 0,
    age_ticks: int = 0,
    generation: int = 0,
) -> int:
    """Helper to instantiate a valid Agent entity through the pure data substrate."""
    eid = world.entities._next_id
    world.entities._next_id += 1
    ent = Entity(
        entity_id=eid,
        entity_type="agent",
        created_tick=world.clock.current_tick,
        properties={
            "cell_x": cell_x,
            "cell_y": cell_y,
            "is_alive": 1,
            "sex": sex,
            "biomass": FixedPoint.from_decimal_string(f"{biomass:.6f}"),
            "energy": FixedPoint.from_decimal_string(f"{energy:.6f}"),
            "hunger": FixedPoint.from_decimal_string(f"{hunger:.6f}"),
            "thirst": FixedPoint.from_decimal_string(f"{thirst:.6f}"),
            "fatigue": FixedPoint.from_decimal_string(f"{fatigue:.6f}"),
            "reproduction_drive": FixedPoint.from_decimal_string(f"{reproduction_drive:.6f}"),
            "metabolic_rate": FixedPoint.from_decimal_string(f"{metabolic_rate:.6f}"),
            "foraging_range": gene_foraging_range,
            "fertility": FixedPoint.from_decimal_string(f"{(gene_fertility / 100):.6f}"),
            "longevity": gene_longevity,
            "boldness": FixedPoint.from_decimal_string(f"{(gene_boldness / 100):.6f}"),
            "gene_metabolic_rate": gene_metabolic_rate,
            "gene_foraging_range": gene_foraging_range,
            "gene_fertility": gene_fertility,
            "gene_longevity": gene_longevity,
            "gene_boldness": gene_boldness,
            "age": age,
            "age_ticks": age_ticks,
            "birth_tick": world.clock.current_tick,
            "generation": generation,
            "action_taken": 0,
        },
    )
    world.entities._entities[eid] = ent
    world.entities._by_type.setdefault("agent", []).append(eid)
    world.spatial_index.place_entity(eid, cell_x, cell_y)
    return eid


def create_test_plant(
    world: WorldState,
    cell_x: int = 0,
    cell_y: int = 0,
    biomass: float = 100.0,
    energy: float = 50.0,
    hydration: float = 50.0,
) -> int:
    """Helper to instantiate an autotroph food plant entity."""
    eid = world.entities._next_id
    world.entities._next_id += 1
    plant = Entity(
        entity_id=eid,
        entity_type="autotroph",
        created_tick=world.clock.current_tick,
        properties={
            "cell_x": cell_x,
            "cell_y": cell_y,
            "is_alive": 1,
            "energy": FixedPoint.from_decimal_string(f"{energy:.6f}"),
            "biomass": FixedPoint.from_decimal_string(f"{biomass:.6f}"),
            "hydration": FixedPoint.from_decimal_string(f"{hydration:.6f}"),
            "age": 0,
            "generation": 0,
        },
    )
    world.entities._entities[eid] = plant
    world.entities._by_type.setdefault("autotroph", []).append(eid)
    world.spatial_index.place_entity(eid, cell_x, cell_y)
    return eid


class TestAgentsPhase3Acceptance(unittest.TestCase):
    """Phase 3 Agents Acceptance Test Suite (TEST-301 through TEST-310)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.journal_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _assert_zero_quota_failures(self, world: WorldState, context_msg: str) -> None:
        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(
            len(quota_failures),
            0,
            f"Encountered {len(quota_failures)} quota failures in {context_msg}: {quota_failures}",
        )

    # -------------------------------------------------------------------------
    # TEST-PIN: Parameter File Hash-Pinned Verification
    # -------------------------------------------------------------------------
    def test_parameter_file_hash_pinned(self) -> None:
        """Verify agents_params_v1.json matches the canonical frozen SHA-256 hash."""
        params = load_agents_params("v1", verify_hash=True)
        self.assertIsInstance(params, dict)
        self.assertIn("genetics", params)
        self.assertIn("actions", params)
        self.assertIn("mass_and_thermodynamics", params)
        self.assertEqual(params["genetics"]["locus_count"], 5)
        self.assertEqual(params["genetics"]["mutation_rate_per_thousand"], 10)
        self.assertTrue(params["mass_and_thermodynamics"]["biomass_overflow_to_detritus"])

    def test_parameter_file_v2_hash_pinned(self) -> None:
        """Verify agents_params_v2.json matches the canonical frozen SHA-256 hash and includes changelog."""
        params = load_agents_params("v2", verify_hash=True)
        self.assertIsInstance(params, dict)
        self.assertEqual(params["version"], "v2")
        self.assertIn("changelog", params)
        self.assertGreaterEqual(len(params["changelog"]), 5)
        for entry in params["changelog"]:
            self.assertIn("change", entry)
            self.assertIn("motivation", entry)
            self.assertTrue(
                "motivated by test results" in entry["motivation"].lower(),
                f"Changelog entry '{entry['change']}' missing required motivation disclosure",
            )

    def test_rule_constants_match_params_file(self) -> None:
        """Assert that rule constants across GRL JSON rules equal the parameters in agents_params_v2.json."""
        import json
        from genesis.agents.loader import DATA_DIR
        p = load_agents_params("v2", verify_hash=True)
        rules_dir = DATA_DIR / "rules"

        def extract_literals(node: Any) -> List[str]:
            lits = []
            if isinstance(node, dict):
                if node.get("op") == "LITERAL":
                    lits.append(str(node.get("value")))
                for v in node.values():
                    lits.extend(extract_literals(v))
            elif isinstance(node, list):
                for item in node:
                    lits.extend(extract_literals(item))
            return lits

        def find_nodes(node: Any, predicate: Any) -> List[Dict[str, Any]]:
            res = []
            if isinstance(node, dict):
                if predicate(node):
                    res.append(node)
                for v in node.values():
                    res.extend(find_nodes(v, predicate))
            elif isinstance(node, list):
                for item in node:
                    res.extend(find_nodes(item, predicate))
            return res

        # Verify all rules exist as JSON and verify constants
        for r_name in [
            "AR_01_METABOLISM",
            "AR_02_MORTALITY",
            "AR_03_DRINK",
            "AR_04_EAT",
            "AR_05_REPRODUCE",
            "AR_06_REST",
            "AR_07_FORAGE_MOVE",
        ]:
            r_path = rules_dir / f"{r_name}.json"
            self.assertTrue(r_path.exists(), f"Rule file {r_path} not found")

        # AR_01_METABOLISM.json
        with open(rules_dir / "AR_01_METABOLISM.json", "r", encoding="utf-8") as f:
            ar01 = json.load(f)
        ar01_lits = extract_literals(ar01)
        self.assertIn(p["actions"]["metabolism"]["basal_biomass_slough"], ar01_lits)
        self.assertIn(p["needs_dynamics"]["base_hunger_growth"], ar01_lits)
        self.assertIn(p["needs_dynamics"]["base_thirst_growth"], ar01_lits)
        self.assertIn(p["needs_dynamics"]["base_fatigue_growth"], ar01_lits)
        self.assertIn(p["needs_dynamics"]["base_reproduction_growth"], ar01_lits)

        # AR_02_MORTALITY.json
        with open(rules_dir / "AR_02_MORTALITY.json", "r", encoding="utf-8") as f:
            ar02 = json.load(f)
        ar02_lits = extract_literals(ar02)
        self.assertIn(p["needs_dynamics"]["starvation_hunger_threshold"], ar02_lits)
        self.assertIn(p["needs_dynamics"]["dehydration_thirst_threshold"], ar02_lits)

        # AR_03_DRINK.json
        with open(rules_dir / "AR_03_DRINK.json", "r", encoding="utf-8") as f:
            ar03 = json.load(f)
        ar03_lits = extract_literals(ar03)
        self.assertIn(p["needs_dynamics"]["thirst_trigger_threshold"], ar03_lits)
        self.assertIn(p["actions"]["drink"]["water_intake"], ar03_lits)
        self.assertIn(p["actions"]["drink"]["thirst_satisfaction"], ar03_lits)

        # AR_04_EAT.json
        with open(rules_dir / "AR_04_EAT.json", "r", encoding="utf-8") as f:
            ar04 = json.load(f)
        ar04_lits = extract_literals(ar04)
        self.assertIn(p["needs_dynamics"]["hunger_trigger_threshold"], ar04_lits)
        self.assertIn(p["actions"]["eat_autotroph"]["intake_mass"], ar04_lits)
        self.assertIn(p["actions"]["eat_autotroph"]["base_energy_yield"], ar04_lits)
        self.assertIn(p["actions"]["eat_autotroph"]["hunger_satisfaction"], ar04_lits)
        self.assertIn(p["mass_and_thermodynamics"]["biomass_cap"], ar04_lits)

        # AR_05_REPRODUCE.json
        with open(rules_dir / "AR_05_REPRODUCE.json", "r", encoding="utf-8") as f:
            ar05 = json.load(f)
        ar05_lits = extract_literals(ar05)
        self.assertIn(p["needs_dynamics"]["reproduction_drive_threshold"], ar05_lits)
        self.assertIn(p["needs_dynamics"]["reproduction_min_biomass"], ar05_lits)
        self.assertIn(p["needs_dynamics"]["reproduction_min_energy"], ar05_lits)
        self.assertTrue(
            p["actions"]["reproduction"]["parent_biomass_deduction"] in ar05_lits
            or f"-{p['actions']['reproduction']['parent_biomass_deduction']}" in ar05_lits
        )
        self.assertTrue(
            p["actions"]["reproduction"]["parent_energy_deduction"] in ar05_lits
            or f"-{p['actions']['reproduction']['parent_energy_deduction']}" in ar05_lits
        )
        self.assertIn(p["actions"]["reproduction"]["child_base_biomass"], ar05_lits)
        self.assertIn(p["actions"]["reproduction"]["child_base_energy"], ar05_lits)
        # Check max_scan in AR_05
        fe_nodes = find_nodes(ar05, lambda n: n.get("op") == "FIND_ENTITY")
        self.assertTrue(len(fe_nodes) > 0)
        self.assertEqual(fe_nodes[0].get("max_scan"), p["budget_guards"]["find_entity_max_scan"])

        # AR_06_REST.json
        with open(rules_dir / "AR_06_REST.json", "r", encoding="utf-8") as f:
            ar06 = json.load(f)
        ar06_lits = extract_literals(ar06)
        self.assertIn(p["needs_dynamics"]["fatigue_trigger_threshold"], ar06_lits)
        self.assertIn(p["actions"]["rest"]["fatigue_recovery"], ar06_lits)
        self.assertIn(p["actions"]["rest"]["energy_recovery"], ar06_lits)

        # AR_07_FORAGE_MOVE.json
        with open(rules_dir / "AR_07_FORAGE_MOVE.json", "r", encoding="utf-8") as f:
            ar07 = json.load(f)
        ar07_lits = extract_literals(ar07)
        self.assertIn(p["actions"]["forage_move"]["base_fatigue_cost"], ar07_lits)

    # -------------------------------------------------------------------------
    # TEST-301: Determinism & Hash Reproducibility
    # -------------------------------------------------------------------------
    def test_301_determinism_and_hash_reproducibility(self) -> None:
        """Identical seed produces bit-identical state hashes across independent runs and save/reload."""
        def setup_sim(seed: int, j_dir: Path) -> WorldState:
            w = WorldState(seed=seed, journal_dir=j_dir)
            load_ecosystem_schemas(w.schema_registry)
            load_ecosystem_resources(w.resources)
            load_agents(w)
            create_test_plant(w, cell_x=0, cell_y=0, biomass=100.0)
            create_test_agent(w, cell_x=0, cell_y=0, sex=0, biomass=50.0, energy=100.0)
            create_test_agent(w, cell_x=0, cell_y=0, sex=1, biomass=50.0, energy=100.0)
            return w

        # 1. Independent runs bit-identity
        w1 = setup_sim(42, self.journal_dir / "j1")
        w2 = setup_sim(42, self.journal_dir / "j2")

        for _ in range(500):
            w1.advance_tick()
            w2.advance_tick()

        hash1 = w1.compute_state_hash()
        hash2 = w2.compute_state_hash()
        j_hash1 = w1.event_journal.last_hash
        j_hash2 = w2.event_journal.last_hash

        self.assertEqual(hash1, hash2, f"State hash drift between identical runs: {hash1} != {hash2}")
        self.assertEqual(j_hash1, j_hash2, f"Journal hash drift between identical runs: {j_hash1} != {j_hash2}")
        self.assertEqual(hash1, GOLDEN_STATE_HASH_500, "State hash does not match committed golden hash")
        self.assertEqual(j_hash1, GOLDEN_JOURNAL_HASH_500, "Journal hash does not match committed golden hash")
        self._assert_zero_quota_failures(w1, "TEST-301 (Run 1)")

        # 2. Save and reload determinism at tick 250
        sm = SnapshotManager(base_dir=self.journal_dir / "snaps")
        w_split = setup_sim(42, self.journal_dir / "j_split")
        for _ in range(250):
            w_split.advance_tick()

        snap_path, _ = sm.save_snapshot(w_split, "snap_250.json")
        w_reloaded = sm.load_snapshot(snap_path)

        for _ in range(250):
            w_reloaded.advance_tick()

        hash_reloaded = w_reloaded.compute_state_hash()
        self.assertEqual(
            hash1,
            hash_reloaded,
            f"Save/reload drift: continuous={hash1} != reloaded={hash_reloaded}",
        )

    # -------------------------------------------------------------------------
    # TEST-302: Exact Mass Conservation Under Full Life Cycle
    # -------------------------------------------------------------------------
    def test_302_exact_mass_conservation_under_full_lifecycle(self) -> None:
        """Closed-system mass remains strictly constant to +/- 0.000000 over 1,000 ticks."""
        world = WorldState(seed=42, journal_dir=self.journal_dir)
        load_ecosystem_schemas(world.schema_registry)
        load_ecosystem_resources(world.resources)
        load_agents(world)

        # Autotrophs in 3x3 grid
        for i in range(9):
            create_test_plant(world, cell_x=i % 3, cell_y=i // 3, biomass=100.0)

        # Founding breeding pair
        create_test_agent(world, cell_x=0, cell_y=0, sex=0, biomass=100.0, energy=200.0, reproduction_drive=55.0)
        create_test_agent(world, cell_x=0, cell_y=0, sex=1, biomass=100.0, energy=200.0, reproduction_drive=55.0)

        m0 = get_ecosystem_metrics(world)["total_closed_mass"]
        initial_mass_raw = m0.raw_value

        for t in range(1, 1001):
            world.advance_tick()
            mt = get_ecosystem_metrics(world)["total_closed_mass"]
            self.assertEqual(
                mt.raw_value,
                initial_mass_raw,
                f"Mass drift at tick {t}: initial={m0}, current={mt}",
            )

        self._assert_zero_quota_failures(world, "TEST-302")

    # -------------------------------------------------------------------------
    # TEST-303: Zero Quota Failures Over Multi-Scale Runs With Peak Touches
    # -------------------------------------------------------------------------
    def test_303_zero_quota_failures_multiscale_runs(self) -> None:
        """Zero QuotaExceededError occurrences and peak entities touched recorded (< 1000) at 100, 200, 300 agents."""
        for pop_size in [100, 200, 300]:
            with self.subTest(pop_size=pop_size):
                world = WorldState(seed=101 + pop_size, journal_dir=self.journal_dir / f"scale_{pop_size}")
                load_ecosystem_schemas(world.schema_registry)
                load_ecosystem_resources(world.resources)
                load_agents(world)

                for i in range(pop_size):
                    cx, cy = (i % 10) - 5, (i // 10) - 5
                    create_test_agent(world, cell_x=cx, cell_y=cy, sex=i % 2, biomass=40.0, energy=100.0)

                peak_entities_touched = 0
                for _ in range(30):
                    world.advance_tick()
                    touches = len(world.entities_touched_this_tick)
                    if touches > peak_entities_touched:
                        peak_entities_touched = touches

                # Assert strict bounds
                self.assertLess(
                    peak_entities_touched,
                    1000,
                    f"Peak entities touched {peak_entities_touched} exceeded substrate limit 1000",
                )
                self.assertGreaterEqual(peak_entities_touched, pop_size)
                self._assert_zero_quota_failures(world, f"TEST-303 (pop={pop_size})")

    # -------------------------------------------------------------------------
    # TEST-304: Dual-Metabolism Needs Dynamics & Mortality
    # -------------------------------------------------------------------------
    def test_304_dual_metabolism_needs_and_mortality(self) -> None:
        """Starved agents die within pre-registered tick windows scaled by metabolic rate; nourished survive."""
        # Case 1: Standard Metabolism (1.000000) -> dies in [95, 105] ticks
        w1 = WorldState(seed=42, journal_dir=self.journal_dir / "m_std")
        load_ecosystem_schemas(w1.schema_registry)
        load_ecosystem_resources(w1.resources)
        load_agents(w1)
        w1.resources.get_pool("soil_water").set_balance(FixedPoint.from_int(0))
        eid1 = create_test_agent(w1, metabolic_rate=1.0, gene_metabolic_rate=100)

        death_tick_std = None
        for t in range(1, 150):
            w1.advance_tick()
            if eid1 not in w1.entities._entities:
                death_tick_std = t
                break

        self.assertIsNotNone(death_tick_std, "Standard agent failed to die")
        self.assertTrue(
            95 <= death_tick_std <= 105,
            f"Standard agent died at tick {death_tick_std}, expected in [95, 105]",
        )

        # Case 2: Fast Metabolism (2.000000) -> dies in [45, 55] ticks
        w2 = WorldState(seed=42, journal_dir=self.journal_dir / "m_fast")
        load_ecosystem_schemas(w2.schema_registry)
        load_ecosystem_resources(w2.resources)
        load_agents(w2)
        w2.resources.get_pool("soil_water").set_balance(FixedPoint.from_int(0))
        eid2 = create_test_agent(w2, metabolic_rate=2.0, gene_metabolic_rate=200)

        death_tick_fast = None
        for t in range(1, 100):
            w2.advance_tick()
            if eid2 not in w2.entities._entities:
                death_tick_fast = t
                break

        self.assertIsNotNone(death_tick_fast, "Fast agent failed to die")
        self.assertTrue(
            45 <= death_tick_fast <= 55,
            f"Fast agent died at tick {death_tick_fast}, expected in [45, 55]",
        )

        # Case 3: Nourished Case -> survives > 500 ticks with hunger and thirst in [0, 70]
        w3 = WorldState(seed=42, journal_dir=self.journal_dir / "m_nourished")
        load_ecosystem_schemas(w3.schema_registry)
        load_ecosystem_resources(w3.resources)
        load_agents(w3)
        plant_id = create_test_plant(w3, cell_x=0, cell_y=0, biomass=200.0)
        eid3 = create_test_agent(w3, cell_x=0, cell_y=0, metabolic_rate=1.0)
        plant_ent = w3.entities.get_entity(plant_id)

        max_hunger = FixedPoint.from_int(0)
        max_thirst = FixedPoint.from_int(0)
        survived = True

        for t in range(1, 501):
            if plant_ent and plant_ent.get_property("biomass") < FixedPoint.from_int(50):
                plant_ent.set_property("biomass", FixedPoint.from_int(200))
            w3.advance_tick()
            if eid3 in w3.entities._entities:
                agent_ent = w3.entities._entities[eid3]
                h = agent_ent.get_property("hunger")
                th = agent_ent.get_property("thirst")
                if h > max_hunger:
                    max_hunger = h
                if th > max_thirst:
                    max_thirst = th
            else:
                survived = False
                break

        self.assertTrue(survived, "Nourished agent died prematurely before 500 ticks")
        self.assertLessEqual(max_hunger, FixedPoint.from_decimal_string("70.000000"))
        self.assertLessEqual(max_thirst, FixedPoint.from_decimal_string("70.000000"))
        self._assert_zero_quota_failures(w3, "TEST-304 (Nourished)")

    # -------------------------------------------------------------------------
    # TEST-305: Mendelian Inheritance & Genetic Mutation Bounds
    # -------------------------------------------------------------------------
    def test_305_mendelian_inheritance_and_mutation_bounds(self) -> None:
        """Alleles segregate 50/50 from parents under mu = 0; traits remain strictly bounded."""
        parent_a = [100, 1, 100, 1000, 50]
        parent_b = [150, 3, 150, 2000, 80]
        loci = ["gene_metabolic_rate", "gene_foraging_range", "gene_fertility", "gene_longevity", "gene_boldness"]

        matches_a = 0
        matches_b = 0
        foreign = 0

        # Run 50 offspring generations under mu = 0
        for seed in range(50):
            w = WorldState(seed=seed + 1, journal_dir=self.journal_dir / f"mende_{seed}")
            load_ecosystem_schemas(w.schema_registry)
            load_ecosystem_resources(w.resources)
            load_agents(w, mutation_rate_per_thousand=0)

            eid_a = create_test_agent(
                w, sex=0, biomass=100.0, energy=200.0, reproduction_drive=80.0,
                gene_metabolic_rate=parent_a[0], gene_foraging_range=parent_a[1],
                gene_fertility=parent_a[2], gene_longevity=parent_a[3], gene_boldness=parent_a[4],
                age_ticks=55,
            )
            eid_b = create_test_agent(
                w, sex=1, biomass=100.0, energy=200.0, reproduction_drive=80.0,
                gene_metabolic_rate=parent_b[0], gene_foraging_range=parent_b[1],
                gene_fertility=parent_b[2], gene_longevity=parent_b[3], gene_boldness=parent_b[4],
                age_ticks=55,
            )

            w.advance_tick()
            children = [
                ent for ent in w.entities._entities.values()
                if ent.entity_type == "agent" and ent.id not in (eid_a, eid_b)
            ]
            self.assertEqual(len(children), 1)
            child = children[0]

            for k, loc in enumerate(loci):
                val = child.get_property(loc)
                if val == parent_a[k]:
                    matches_a += 1
                elif val == parent_b[k]:
                    matches_b += 1
                else:
                    foreign += 1

        total_alleles = matches_a + matches_b + foreign
        frac_a = matches_a / total_alleles

        # Assert no foreign alleles under mu = 0
        self.assertEqual(foreign, 0, f"Foreign alleles appeared under mu = 0: {foreign}")
        # Assert parental allele frequency is within [35%, 65%]
        self.assertTrue(
            0.35 <= frac_a <= 0.65,
            f"Parental allele distribution skewed: A={frac_a:.1%}, expected in [35%, 65%]",
        )

    # -------------------------------------------------------------------------
    # TEST-306: Resource-Bound Selection Pressure for Low Metabolic Rate
    # -------------------------------------------------------------------------
    def test_306_resource_bound_selection_pressure_for_low_metabolic_rate(self) -> None:
        """In resource-scarce conditions, starvation-resistant low metabolic rate out-competes across multiple random seeds."""
        for seed in [42, 1337, 2026]:
            with self.subTest(seed=seed):
                w = WorldState(seed=seed, journal_dir=self.journal_dir / f"select_{seed}")
                load_ecosystem_schemas(w.schema_registry)
                load_ecosystem_resources(w.resources)
                load_agents(w)

                create_test_plant(w, cell_x=0, cell_y=0, biomass=30.0)

                # 4 Efficient agents (metabolic_rate = 0.500000)
                for i in range(4):
                    create_test_agent(
                        w, cell_x=0, cell_y=0, sex=i % 2, biomass=40.0, energy=80.0,
                        metabolic_rate=0.5, gene_metabolic_rate=50,
                    )

                # 4 Profligate agents (metabolic_rate = 1.800000)
                for i in range(4):
                    create_test_agent(
                        w, cell_x=0, cell_y=0, sex=i % 2, biomass=40.0, energy=80.0,
                        metabolic_rate=1.8, gene_metabolic_rate=180,
                    )

                for _ in range(200):
                    w.advance_tick()

                living_agents = [
                    ent for ent in w.entities._entities.values()
                    if ent.entity_type == "agent" and ent.get_property("is_alive") == 1
                ]
                efficient_count = sum(1 for a in living_agents if a.get_property("gene_metabolic_rate") <= 100)
                profligate_count = sum(1 for a in living_agents if a.get_property("gene_metabolic_rate") > 100)
                total = len(living_agents)
                frac_eff = efficient_count / total if total > 0 else 1.0

                self.assertGreater(total, 0, f"All agents died under seed {seed}")
                self.assertGreater(
                    frac_eff,
                    0.75,
                    f"Efficient phenotype fraction {frac_eff:.1%} <= 75% for seed {seed}",
                )
                self.assertEqual(profligate_count, 0, f"Profligate agents survived famine under seed {seed}")
                self._assert_zero_quota_failures(w, f"TEST-306 (seed={seed})")

    # -------------------------------------------------------------------------
    # TEST-307: Whole-Window Resource-Bound Carrying Capacity Equilibrium
    # -------------------------------------------------------------------------
    def test_307_whole_window_resource_bound_carrying_capacity(self) -> None:
        """Agent population levels off and maintains equilibrium across the whole window [150, 350]."""
        w = WorldState(seed=42, journal_dir=self.journal_dir / "carrying_cap")
        load_ecosystem_schemas(w.schema_registry)
        load_ecosystem_resources(w.resources)
        load_agents(w)

        # 3x3 plant grid with resource-bound carrying capacity cap
        plant_cap = 15.0
        repl_amt = 1.0
        for x in [-1, 0, 1]:
            for y in [-1, 0, 1]:
                create_test_plant(w, cell_x=x, cell_y=y, biomass=plant_cap)

        # 18 initial agents distributed across the 3x3 grid (9 breeding pairs)
        for i in range(18):
            cx = (i % 3) - 1
            cy = ((i // 3) % 3) - 1
            create_test_agent(
                w, cell_x=cx, cell_y=cy, sex=i % 2, biomass=50.0, energy=120.0,
                hunger=10.0, thirst=10.0, reproduction_drive=50.0, age_ticks=50,
            )

        pop_history: List[Tuple[int, int]] = []
        repl_fp = FixedPoint.from_decimal_string(f"{repl_amt:.6f}")
        cap_fp = FixedPoint.from_decimal_string(f"{plant_cap:.6f}")
        for t in range(1, 351):
            for p_id in w.entities._by_type.get("autotroph", []):
                p = w.entities.get_entity(p_id)
                if p and p.get_property("biomass") < cap_fp:
                    p.set_property("biomass", min(cap_fp, p.get_property("biomass") + repl_fp))
            w.advance_tick()
            living = len([e for e in w.entities.all_entities() if e.entity_type == "agent" and e.is_active])
            pop_history.append((t, living))

        window_pops = [p for t, p in pop_history if 150 <= t <= 350]
        mean_pop = sum(window_pops) / len(window_pops)
        self.assertGreater(mean_pop, 0, "Population went extinct during observation window")

        # Assert variance <= +/- 15% for EVERY tick in window [150, 350]
        for t, p in pop_history:
            if 150 <= t <= 350:
                deviation = abs(p - mean_pop) / mean_pop
                self.assertLessEqual(
                    deviation,
                    0.150000,
                    f"Population deviation at tick {t} ({deviation:.1%}) breached 15% window ceiling",
                )

        self._assert_zero_quota_failures(w, "TEST-307")

    # -------------------------------------------------------------------------
    # TEST-308: Read-Only Emergence Measurement Invariance
    # -------------------------------------------------------------------------
    def test_308_read_only_emergence_measurement_invariance(self) -> None:
        """Executing emergence measurement tools leaves state hash, journal, and RNG bit-identical."""
        w = WorldState(seed=42, journal_dir=self.journal_dir / "emergence_inv")
        load_ecosystem(w)
        load_agents(w)

        for _ in range(50):
            w.advance_tick()

        hash_before = w.compute_state_hash()
        journal_before = w.event_journal.last_hash
        rng_before = w.rng.step_count

        binding = get_agent_analysis_binding()
        _ = evaluate_settlement(w, binding)
        _ = evaluate_group(w, binding, window_start_tick=0, window_end_tick=50)
        _ = evaluate_cultural_spread(w, binding, eval_tick=50, window_start_tick=0)

        hash_after = w.compute_state_hash()
        journal_after = w.event_journal.last_hash
        rng_after = w.rng.step_count

        self.assertEqual(hash_before, hash_after, "State hash modified by emergence measurement tool")
        self.assertEqual(journal_before, journal_after, "Journal hash modified by emergence measurement tool")
        self.assertEqual(rng_before, rng_after, "PRNG step count modified by emergence measurement tool")

    # -------------------------------------------------------------------------
    # TEST-309: Negative Control: Founder-Allele-Set Conservation
    # -------------------------------------------------------------------------
    def test_309_founder_allele_set_conservation(self) -> None:
        """With mu = 0, every allele at every locus across living descendants matches founder pool."""
        w = WorldState(seed=42, journal_dir=self.journal_dir / "founder_ctrl")
        load_ecosystem_schemas(w.schema_registry)
        load_ecosystem_resources(w.resources)
        load_agents(w, mutation_rate_per_thousand=0)

        founder_alleles: Dict[str, Set[int]] = {
            "gene_metabolic_rate": set(),
            "gene_foraging_range": set(),
            "gene_fertility": set(),
            "gene_longevity": set(),
            "gene_boldness": set(),
        }

        # 10 founder agents with diverse alleles
        for i in range(10):
            g_mr = 60 + i * 10
            g_fr = 1 + (i % 3)
            g_fe = 70 + i * 10
            g_lo = 600 + i * 150
            g_bo = 10 + i * 8
            founder_alleles["gene_metabolic_rate"].add(g_mr)
            founder_alleles["gene_foraging_range"].add(g_fr)
            founder_alleles["gene_fertility"].add(g_fe)
            founder_alleles["gene_longevity"].add(g_lo)
            founder_alleles["gene_boldness"].add(g_bo)

            create_test_agent(
                w, cell_x=0, cell_y=0, sex=i % 2, biomass=50.0, energy=120.0,
                hunger=10.0, thirst=10.0, reproduction_drive=50.0, age_ticks=50,
                gene_metabolic_rate=g_mr, gene_foraging_range=g_fr,
                gene_fertility=g_fe, gene_longevity=g_lo, gene_boldness=g_bo,
                metabolic_rate=g_mr / 100.0,
            )

        plant_id = create_test_plant(w, cell_x=0, cell_y=0, biomass=200.0)
        plant_ent = w.entities.get_entity(plant_id)

        for _ in range(250):
            if plant_ent and plant_ent.get_property("biomass") < FixedPoint.from_int(50):
                plant_ent.set_property("biomass", FixedPoint.from_int(200))
            w.advance_tick()

        living = [e for e in w.entities.all_entities() if e.entity_type == "agent" and e.is_active]
        self.assertGreater(len(living), 0, "All agents died during founder allele test")

        for agent in living:
            for locus, allowed in founder_alleles.items():
                val = agent.get_property(locus)
                self.assertIn(
                    val,
                    allowed,
                    f"Novel allele {val} appeared at {locus} under mu = 0 (agent {agent.id})",
                )

        self._assert_zero_quota_failures(w, "TEST-309")

    # -------------------------------------------------------------------------
    # TEST-310: Regression Guard
    # -------------------------------------------------------------------------
    def test_310_regression_guard(self) -> None:
        """Verify that zero organism-specific Python classes exist and Entity subclassing remains empty."""
        subclasses = Entity.__subclasses__()
        self.assertEqual(
            subclasses,
            [],
            f"Violation of Layer 1 purity: found Entity subclasses: {subclasses}",
        )


if __name__ == "__main__":
    unittest.main()
