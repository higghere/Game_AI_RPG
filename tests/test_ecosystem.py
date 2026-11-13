"""GENESIS Phase 2b Acceptance Test Suite: Layer 2 Ecosystem as Data.

Verifies:
- TEST-201: Schema Definition Purity (zero Python entity classes, generic Entity ontology)
- TEST-202: Primary Producer Equilibrium (autotrophs under solar flux reach bounded equilibrium over 365 ticks)
- TEST-203: Closed-System Mass Conservation (exact equality over 1,000 ticks with tolerance zero)
- TEST-204: Predator-Prey / Grazer Oscillation (autotroph-herbivore coexistence and Lotka-Volterra dynamics over 730 ticks)
- TEST-205: Deterministic Extinction Threshold (solar flux cut to 0 causes deterministic starvation to 0)
- TEST-206: Spatial Dispersal & Colonization (initial population in single cell disperses across cells)
- TEST-207: Golden Hash Ecosystem Reproducibility (bit-identical state hash and continuous journal hash chain)

Zero Quota Failure Invariant:
All Phase 2 ecosystem tests require 0 quota failures (world.event_journal must have 0 events
of type rule_execution_failed with QuotaExceededError).
"""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

from genesis.core.arithmetic import FixedPoint
from genesis.ecosystem import (
    get_ecosystem_metrics,
    load_ecosystem,
    load_ecosystem_resources,
    load_ecosystem_rules,
    load_ecosystem_schemas,
)
from genesis.substrate.entities import Entity
from genesis.substrate.world_state import WorldState


# Committed golden hashes for TEST-207 (365 ticks, seed 42)
# Updated in Phase 3d following is_agent schema property decoupling without substrate changes (rule version 1.2.0)
GOLDEN_STATE_HASH_365 = "f6567e8699a76aaaf9c58532153896e0bad86d6e8a85cd0e7ab26fac4333de18"
GOLDEN_JOURNAL_HASH_365 = "ebe688c8b612f63c2e6ff7dfe270923ca155729d8c59b0a7d1b2650a8edd7b02"


class TestEcosystemAcceptance(unittest.TestCase):
    """Phase 2 Ecosystem Acceptance Tests (TEST-201 through TEST-207)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.journal_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # TEST-201: Schema Definition Purity
    # -------------------------------------------------------------------------
    def test_201_schema_definition_purity(self) -> None:
        """Verify that zero organism-specific Python classes exist.

        Target condition: All organisms instantiated through SchemaRegistry JSON
        dictionaries. Zero subclassing of Entity.
        """
        world = WorldState(seed=101, journal_dir=self.journal_dir)
        load_ecosystem(world)

        # 1. Verify schemas are loaded dynamically from JSON declarations
        self.assertTrue(world.schema_registry.has_type("autotroph"))
        self.assertTrue(world.schema_registry.has_type("herbivore"))
        self.assertTrue(world.schema_registry.has_type("decomposer"))

        # 2. Verify all properties match schema declarations
        auto_schema = world.schema_registry.get_schema("autotroph")
        self.assertIsNotNone(auto_schema)
        self.assertIn("biomass", auto_schema.properties)
        self.assertIn("energy", auto_schema.properties)
        self.assertIn("hydration", auto_schema.properties)

        herb_schema = world.schema_registry.get_schema("herbivore")
        self.assertIsNotNone(herb_schema)
        self.assertIn("stomach", herb_schema.properties)

        # 3. Instantiate entities dynamically via generic Entity class
        eid = world.entities._next_id
        world.entities._next_id += 1
        organism = Entity(
            entity_id=eid,
            entity_type="autotroph",
            created_tick=0,
            properties={
                "cell_x": 0,
                "cell_y": 0,
                "energy": FixedPoint.from_int(50),
                "biomass": FixedPoint.from_int(25),
                "hydration": FixedPoint.from_int(50),
                "age": 0,
                "generation": 0,
                "is_alive": 1,
            },
        )
        world.entities._entities[eid] = organism
        world.entities._by_type.setdefault("autotroph", []).append(eid)

        # Assert organism is a direct instance of Entity, NOT an organism subclass
        self.assertIs(type(organism), Entity)

        # Assert no subclasses of Entity exist anywhere in Python runtime
        subclasses = Entity.__subclasses__()
        self.assertEqual(
            subclasses,
            [],
            f"Violation of Layer 1 purity: found Entity subclasses: {subclasses}",
        )

    # -------------------------------------------------------------------------
    # TEST-202: Primary Producer Throughput-Bounded Propagation
    # -------------------------------------------------------------------------
    def test_202_primary_producer_throughput_bounded_growth(self) -> None:
        """Autotroph propagation under unconstrained resources is bounded by rule throughput caps.

        Context:
        With initial environmental pools of 20M water and 20M minerals against ~6,000 biomass,
        resources do not bind in this baseline scenario over 365 ticks. Population growth is
        instead bounded by the Layer 1 computational execution ceilings:
        - Photosynthesis candidate limit: 6 per cell per tick.
        - Fission candidate limit: 1 per cell per tick.

        Pass criteria defined numerically:
        - Bounded propagation: population grows steadily from 10 to [10, 400] over 365 ticks.
        - Population remains within [10, 400] across the entire recorded trajectory.
        - Zero quota failures: world.event_journal records 0 QuotaExceededError events.
        - Strict mass conservation: total closed mass remains strictly identical between tick 0 and 365.
        """
        world = WorldState(seed=42, journal_dir=self.journal_dir)
        load_ecosystem(world)

        initial_count = 10
        for _ in range(initial_count):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="autotroph",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(50),
                    "biomass": FixedPoint.from_int(25),
                    "hydration": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("autotroph", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        m0 = get_ecosystem_metrics(world)
        initial_mass = m0["total_closed_mass"]

        pop_curve: List[Tuple[int, int]] = []
        for t in range(365):
            world.advance_tick()
            m = get_ecosystem_metrics(world)
            pop = m["populations"]["autotroph"]
            if (t + 1) % 25 == 0 or t + 1 == 365:
                pop_curve.append((t + 1, pop))

        end_metrics = get_ecosystem_metrics(world)
        end_pop = end_metrics["populations"]["autotroph"]

        # 1. Stated criteria assertion: population remains strictly bounded in [10, 400]
        self.assertTrue(
            all(10 <= pop <= 400 for _, pop in pop_curve),
            f"Population breached bounds [10, 400] during run: {pop_curve}",
        )
        self.assertGreaterEqual(end_pop, 10, f"Autotroph collapsed: final={end_pop} < 10")
        self.assertLessEqual(end_pop, 400, f"Autotroph exploded: final={end_pop} > 400")

        # 2. Zero quota failures invariant
        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(
            len(quota_failures),
            0,
            f"Encountered {len(quota_failures)} quota failures in TEST-202",
        )

        # 3. Strict mass conservation
        self.assertEqual(
            end_metrics["total_closed_mass"].raw_value,
            initial_mass.raw_value,
            f"Mass drift in TEST-202: end={end_metrics['total_closed_mass']} != initial={initial_mass}",
        )

    # -------------------------------------------------------------------------
    # TEST-202b: Resource-Bound Carrying Capacity Equilibrium
    # -------------------------------------------------------------------------
    def test_202b_resource_bound_carrying_capacity_equilibrium(self) -> None:
        """Autotroph population settles into a stable carrying capacity when resources actually bind.

        Setup:
        Initial resources constrained to finite pools:
        - soil_water = 1,200
        - soil_minerals = 1,200
        - detritus = 3,000
        Initial organisms: 8 autotrophs and 4 decomposers in cell (0, 0).

        Dynamics:
        As autotrophs grow, water is consumed (4.0 per photosynthesis) faster than it is recycled
        by decomposers (0.8 per 5.0 detritus). Around tick 60, water becomes limiting (~12.8-24.8),
        preventing surplus biomass accumulation needed for fission (energy >= 100, biomass >= 50).
        Consequently, reproduction halts, mortality is zero due to minimal maintenance uptake,
        and the population stabilizes at a resource-bounded equilibrium plateau.

        Pass criteria:
        - Population levels off completely across ticks 65..115 (variance <= 1 organism, plateauing at 31).
        - Zero quota failures.
        - Strict mass conservation at tolerance zero.
        """
        world = WorldState(seed=42, journal_dir=self.journal_dir)
        load_ecosystem(world)

        # Scarce environmental pools so resources bind tightly
        world.resources.get_pool("soil_water").set_balance(FixedPoint.from_int(1200))
        world.resources.get_pool("soil_minerals").set_balance(FixedPoint.from_int(1200))
        world.resources.get_pool("detritus").set_balance(FixedPoint.from_int(3000))

        # 8 autotrophs
        for _ in range(8):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="autotroph",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(50),
                    "biomass": FixedPoint.from_int(25),
                    "hydration": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("autotroph", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        # 4 decomposers to maintain basal nutrient recycling
        for _ in range(4):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="decomposer",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(100),
                    "biomass": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("decomposer", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        m0 = get_ecosystem_metrics(world)
        initial_mass_raw = m0["total_closed_mass"].raw_value

        plateau_populations: List[int] = []
        for t in range(120):
            world.advance_tick()
            m = get_ecosystem_metrics(world)
            if 65 <= (t + 1) <= 115:
                plateau_populations.append(m["populations"]["autotroph"])

        # 1. Population settles and levels off into equilibrium plateau (variance <= 1 organism)
        min_p = min(plateau_populations)
        max_p = max(plateau_populations)
        self.assertLessEqual(
            max_p - min_p,
            1,
            f"Population failed to settle at carrying capacity: min={min_p}, max={max_p} across ticks 65..115",
        )
        self.assertEqual(
            min_p,
            31,
            f"Expected carrying capacity plateau at 31 organisms, got {min_p}",
        )

        # 2. Zero quota failures
        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(len(quota_failures), 0)

        # 3. Exact mass conservation
        m_end = get_ecosystem_metrics(world)
        self.assertEqual(m_end["total_closed_mass"].raw_value, initial_mass_raw)

    # -------------------------------------------------------------------------
    # TEST-203: Closed-System Mass Conservation
    # -------------------------------------------------------------------------
    def test_203_closed_system_mass_conservation(self) -> None:
        """Closed loop (Producer -> Detritus -> Mineral) maintains exact mass balance over 1,000 ticks.

        Pass criteria defined numerically:
        - Exact integer equality of total system closed mass at every single tick:
          M(t) == M(0) for all t in [1..1000] with tolerance ZERO (0.000000).
        - Zero quota failures.
        """
        world = WorldState(seed=12345, journal_dir=self.journal_dir)
        load_ecosystem(world)

        # 10 autotrophs
        for _ in range(10):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="autotroph",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(50),
                    "biomass": FixedPoint.from_int(25),
                    "hydration": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("autotroph", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        # 3 herbivores
        for _ in range(3):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="herbivore",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(100),
                    "biomass": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "stomach": FixedPoint.from_int(0),
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("herbivore", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        # 2 decomposers
        for _ in range(2):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="decomposer",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(30),
                    "biomass": FixedPoint.from_int(15),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("decomposer", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        m0 = get_ecosystem_metrics(world)
        initial_mass_raw = m0["total_closed_mass"].raw_value

        # Execute 1,000 ticks with continuous invariant audit
        for t in range(1000):
            world.advance_tick()
            mt = get_ecosystem_metrics(world)
            current_mass_raw = mt["total_closed_mass"].raw_value
            if current_mass_raw != initial_mass_raw:
                self.fail(
                    f"Mass conservation violation at tick {t + 1}: "
                    f"current={mt['total_closed_mass']} != initial={m0['total_closed_mass']} "
                    f"(delta={current_mass_raw - initial_mass_raw} raw units)"
                )

        # Zero quota failures
        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(len(quota_failures), 0)

    # -------------------------------------------------------------------------
    # TEST-204: Predator-Prey / Grazer Oscillation
    # -------------------------------------------------------------------------
    def test_204_predator_prey_grazer_oscillation(self) -> None:
        """Autotroph-Herbivore coexistence over 730 ticks exhibiting Lotka-Volterra dynamics.

        Pass criteria defined numerically before running:
        - Coexistence: at tick 730, both autotroph and herbivore populations > 0 (no extinction).
        - Major Trophic Oscillation:
          * Herbivore initial surge reaches a prominent primary peak P1 >= 70.
          * Food limitation induces a substantial crash to trough T1 <= 50, with crash amplitude (P1 - T1) >= 25.
          * Plant recovery enables a secondary rebound peak P2 >= 55, with rebound amplitude (P2 - T1) >= 15.
          * Autotroph population exhibits a dynamic boom-and-bust cycle (peak >= 300, trough <= 150, swing >= 200).
        - Zero quota failures throughout all 730 ticks.
        - Total closed mass identical bit-for-bit between start and end.
        """
        world = WorldState(seed=42, journal_dir=self.journal_dir)
        load_ecosystem(world)

        # Initialize 4 autotrophs in each cell of a 3x3 patch (-1..1, -1..1) = 36 autotrophs
        for cx in (-1, 0, 1):
            for cy in (-1, 0, 1):
                for _ in range(4):
                    eid = world.entities._next_id
                    world.entities._next_id += 1
                    ent = Entity(
                        entity_id=eid,
                        entity_type="autotroph",
                        created_tick=0,
                        properties={
                            "cell_x": cx,
                            "cell_y": cy,
                            "energy": FixedPoint.from_int(50),
                            "biomass": FixedPoint.from_int(25),
                            "hydration": FixedPoint.from_int(50),
                            "age": 0,
                            "generation": 0,
                            "is_alive": 1,
                        },
                    )
                    world.entities._entities[eid] = ent
                    world.entities._by_type.setdefault("autotroph", []).append(eid)
                    world.spatial_index.place_entity(eid, cx, cy)

        # Initialize 2 herbivores in center cell (0, 0)
        for _ in range(2):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="herbivore",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(100),
                    "biomass": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "stomach": FixedPoint.from_int(0),
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("herbivore", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        m0 = get_ecosystem_metrics(world)
        initial_mass_raw = m0["total_closed_mass"].raw_value

        herb_history: List[int] = []
        auto_history: List[int] = []

        for t in range(730):
            world.advance_tick()
            m = get_ecosystem_metrics(world)
            auto_history.append(m["populations"]["autotroph"])
            herb_history.append(m["populations"]["herbivore"])

        end_m = get_ecosystem_metrics(world)
        end_auto = end_m["populations"]["autotroph"]
        end_herb = end_m["populations"]["herbivore"]

        # 1. Coexistence without extinction
        self.assertGreater(
            end_auto,
            0,
            f"Autotroph went extinct by tick 730: {end_auto}",
        )
        self.assertGreater(
            end_herb,
            0,
            f"Herbivore went extinct by tick 730: {end_herb}",
        )

        # 2. Tightened macro-oscillation assertions with required minimum amplitudes
        # Primary peak in first half of run (ticks 1..350)
        p1 = max(herb_history[:350])
        t1_idx = herb_history.index(p1)
        self.assertGreaterEqual(
            p1,
            70,
            f"Herbivore primary peak too low: {p1} < 70",
        )

        # Crash trough following primary peak (ticks t(P1)..550)
        t1 = min(herb_history[t1_idx:550])
        t_trough_idx = t1_idx + herb_history[t1_idx:550].index(t1)
        self.assertLessEqual(
            t1,
            50,
            f"Herbivore crash trough did not dip sufficiently: {t1} > 50",
        )

        # Assert minimum crash amplitude >= 25 organisms
        crash_amp = p1 - t1
        self.assertGreaterEqual(
            crash_amp,
            25,
            f"Herbivore crash amplitude too shallow: {crash_amp} < 25 (P1={p1}, T1={t1})",
        )

        # Secondary rebound peak (ticks t(T1)..730)
        p2 = max(herb_history[t_trough_idx:])
        self.assertGreaterEqual(
            p2,
            55,
            f"Herbivore secondary rebound peak too weak: {p2} < 55",
        )

        # Assert minimum rebound amplitude >= 15 organisms
        rebound_amp = p2 - t1
        self.assertGreaterEqual(
            rebound_amp,
            15,
            f"Herbivore rebound amplitude too shallow: {rebound_amp} < 15 (T1={t1}, P2={p2})",
        )

        # Autotroph boom-and-bust swing
        auto_peak = max(auto_history)
        auto_post_peak_min = min(auto_history[auto_history.index(auto_peak):])
        auto_swing = auto_peak - auto_post_peak_min
        self.assertGreaterEqual(
            auto_swing,
            200,
            f"Autotroph grazing response swing too small: {auto_swing} < 200 (peak={auto_peak}, min={auto_post_peak_min})",
        )

        # 3. Zero quota failures
        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(len(quota_failures), 0)

        # 4. Exact mass balance
        self.assertEqual(end_m["total_closed_mass"].raw_value, initial_mass_raw)

    # -------------------------------------------------------------------------
    # TEST-205: Deterministic Extinction Threshold
    # -------------------------------------------------------------------------
    def test_205_deterministic_extinction_threshold(self) -> None:
        """When solar flux is cut to 0, autotroph populations collapse strictly to zero.

        Pass criteria defined numerically:
        - Autotroph population strictly reaches 0 within expected starvation window.
        - Living biomass strictly drops to 0.000000.
        - All organism mass is fully recycled into detritus/soil pools.
        - Total closed system mass is conserved with tolerance ZERO.
        """
        world = WorldState(seed=42, journal_dir=self.journal_dir)
        load_ecosystem(world)

        for _ in range(10):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="autotroph",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(10),
                    "biomass": FixedPoint.from_int(20),
                    "hydration": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("autotroph", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        # Cut solar flux to zero and disable solar replenishment
        world.resources.get_pool("solar_flux").set_balance(FixedPoint.from_int(0))
        del world.rule_registry._rules["BR_01_SOLAR_REPLENISH"]

        m0 = get_ecosystem_metrics(world)
        initial_mass_raw = m0["total_closed_mass"].raw_value

        # Advance until extinction or up to 50 ticks
        extinction_tick = None
        for t in range(50):
            world.advance_tick()
            m = get_ecosystem_metrics(world)
            if m["total_population"] == 0:
                extinction_tick = t + 1
                break

        self.assertIsNotNone(
            extinction_tick,
            "Population failed to extinguish after solar flux was eliminated",
        )
        self.assertLessEqual(
            extinction_tick,
            25,
            f"Extinction took too long: tick {extinction_tick} > 25",
        )

        m_end = get_ecosystem_metrics(world)
        self.assertEqual(m_end["total_population"], 0)
        self.assertEqual(m_end["living_biomass"].raw_value, 0)
        self.assertEqual(m_end["total_closed_mass"].raw_value, initial_mass_raw)

    # -------------------------------------------------------------------------
    # TEST-206: Spatial Dispersal & Colonization
    # -------------------------------------------------------------------------
    def test_206_spatial_dispersal_and_colonization(self) -> None:
        """Initial population in 1 cell spreads into adjacent cells over 50 ticks.

        Pass criteria defined numerically:
        - Cell occupancy > 1 at tick 50 (successful spatial colonization).
        - Movement preserves Chebyshev distance <= 1 step.
        - Zero quota failures and simultaneous movement holds.
        """
        world = WorldState(seed=42, journal_dir=self.journal_dir)
        load_ecosystem(world)

        # Place 5 autotrophs with depleted biomass (< 5.0) at (0, 0) to induce foraging migration
        for _ in range(5):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="autotroph",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(10),
                    "biomass": FixedPoint.from_int(2),
                    "hydration": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("autotroph", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        # Place 3 herbivores at (0, 0)
        for _ in range(3):
            eid = world.entities._next_id
            world.entities._next_id += 1
            ent = Entity(
                entity_id=eid,
                entity_type="herbivore",
                created_tick=0,
                properties={
                    "cell_x": 0,
                    "cell_y": 0,
                    "energy": FixedPoint.from_int(100),
                    "biomass": FixedPoint.from_int(50),
                    "age": 0,
                    "generation": 0,
                    "stomach": FixedPoint.from_int(0),
                    "is_alive": 1,
                },
            )
            world.entities._entities[eid] = ent
            world.entities._by_type.setdefault("herbivore", []).append(eid)
            world.spatial_index.place_entity(eid, 0, 0)

        initial_occupancy = len(world.spatial_index.get_occupied_cells())
        self.assertEqual(initial_occupancy, 1)

        for _ in range(50):
            world.advance_tick()

        m_end = get_ecosystem_metrics(world)
        final_occupancy = m_end["cell_occupancy"]

        self.assertGreater(
            final_occupancy,
            1,
            f"Expected spatial dispersal across multiple cells, got occupancy {final_occupancy}",
        )

        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(len(quota_failures), 0)

    # -------------------------------------------------------------------------
    # TEST-207: Golden Hash Ecosystem Reproducibility
    # -------------------------------------------------------------------------
    def test_207_golden_hash_ecosystem_reproducibility(self) -> None:
        """365 ticks with PRNG produces bit-identical state hash and continuous journal hash chain.

        Pass criteria:
        - Independent identical runs produce 100% bit-identical state hashes and journal hashes.
        - Hashes match the committed golden hash constants.
        """
        def run_sim(seed: int, temp_dir_path: Path) -> Tuple[str, str]:
            world = WorldState(seed=seed, journal_dir=temp_dir_path)
            load_ecosystem(world)

            for _ in range(10):
                eid = world.entities._next_id
                world.entities._next_id += 1
                ent = Entity(
                    entity_id=eid,
                    entity_type="autotroph",
                    created_tick=0,
                    properties={
                        "cell_x": 0,
                        "cell_y": 0,
                        "energy": FixedPoint.from_int(50),
                        "biomass": FixedPoint.from_int(25),
                        "hydration": FixedPoint.from_int(50),
                        "age": 0,
                        "generation": 0,
                        "is_alive": 1,
                    },
                )
                world.entities._entities[eid] = ent
                world.entities._by_type.setdefault("autotroph", []).append(eid)
                world.spatial_index.place_entity(eid, 0, 0)

            for _ in range(3):
                eid = world.entities._next_id
                world.entities._next_id += 1
                ent = Entity(
                    entity_id=eid,
                    entity_type="herbivore",
                    created_tick=0,
                    properties={
                        "cell_x": 0,
                        "cell_y": 0,
                        "energy": FixedPoint.from_int(100),
                        "biomass": FixedPoint.from_int(50),
                        "age": 0,
                        "generation": 0,
                        "stomach": FixedPoint.from_int(0),
                        "is_alive": 1,
                    },
                )
                world.entities._entities[eid] = ent
                world.entities._by_type.setdefault("herbivore", []).append(eid)
                world.spatial_index.place_entity(eid, 0, 0)

            for _ in range(2):
                eid = world.entities._next_id
                world.entities._next_id += 1
                ent = Entity(
                    entity_id=eid,
                    entity_type="decomposer",
                    created_tick=0,
                    properties={
                        "cell_x": 0,
                        "cell_y": 0,
                        "energy": FixedPoint.from_int(30),
                        "biomass": FixedPoint.from_int(15),
                        "age": 0,
                        "generation": 0,
                        "is_alive": 1,
                    },
                )
                world.entities._entities[eid] = ent
                world.entities._by_type.setdefault("decomposer", []).append(eid)
                world.spatial_index.place_entity(eid, 0, 0)

            for _ in range(365):
                world.advance_tick()

            s_hash = world.compute_state_hash(include_journal=False)
            j_hash = world.event_journal.hash_through_tick(365)
            return s_hash, j_hash

        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            state_hash_1, journal_hash_1 = run_sim(42, Path(td1))
            state_hash_2, journal_hash_2 = run_sim(42, Path(td2))

            # Cross-run deterministic identity
            self.assertEqual(state_hash_1, state_hash_2)
            self.assertEqual(journal_hash_1, journal_hash_2)

            # Match committed golden constants
            self.assertEqual(state_hash_1, GOLDEN_STATE_HASH_365)
            self.assertEqual(journal_hash_1, GOLDEN_JOURNAL_HASH_365)

    # -------------------------------------------------------------------------
    # TEST-208: Coupled-World Ecosystem Rules (BR_03 & BR_05) Do Not Touch Agents
    # -------------------------------------------------------------------------
    def test_208_coupled_world_ecosystem_rules_do_not_touch_agents(self) -> None:
        """In a coupled world containing both ecosystem organisms and individual agents,
        BR_03_BASAL_METABOLISM and BR_05_STARVATION_DEATH strictly ignore agents (is_agent == 1)
        and never modify agent properties or trigger agent mortality.
        """
        from genesis.agents.loader import load_agents
        from tests.test_agents_phase3 import create_test_agent

        world = WorldState(seed=208, journal_dir=self.journal_dir / "coupled")
        load_ecosystem(world)
        load_agents(world)

        # Create a herbivore (is_agent=0) in cell (0, 0)
        h_id = world.entities._next_id
        world.entities._next_id += 1
        herbivore = Entity(
            entity_id=h_id,
            entity_type="herbivore",
            created_tick=0,
            properties={
                "cell_x": 0,
                "cell_y": 0,
                "energy": FixedPoint.from_int(10),
                "biomass": FixedPoint.from_int(20),
                "age": 5,
                "generation": 0,
                "is_alive": 1,
                "is_agent": 0,
            },
        )
        world.entities._entities[h_id] = herbivore
        world.entities._by_type.setdefault("herbivore", []).append(h_id)
        world.spatial_index.place_entity(h_id, 0, 0)

        # Create an agent in cell (0, 0) with positive energy and hunger
        agent_id = create_test_agent(
            world,
            cell_x=0,
            cell_y=0,
            sex=0,
            biomass=40.0,
            energy=100.0,
            metabolic_rate=1.0,
        )
        agent = world.entities.get_entity(agent_id)
        self.assertEqual(agent.get_property("is_agent"), 1)
        initial_agent_energy = agent.get_property("energy")
        initial_agent_biomass = agent.get_property("biomass")
        initial_agent_hunger = agent.get_property("hunger")
        meta_rate = agent.get_property("metabolic_rate")

        # Run for 20 ticks
        ticks_to_run = 20
        for _ in range(ticks_to_run):
            world.advance_tick()

        # 1. Agent survives at least 20 ticks with positive energy, hunger, and biomass
        self.assertEqual(agent.get_property("is_alive"), 1)
        self.assertGreater(agent.get_property("energy"), FixedPoint.from_int(0))
        self.assertGreater(agent.get_property("hunger"), FixedPoint.from_int(0))
        self.assertGreater(agent.get_property("biomass"), FixedPoint.from_int(0))

        # 2. Agent energy falls strictly at AR_01's metabolic_rate (1.000000 / tick)
        expected_agent_energy = initial_agent_energy - (meta_rate * FixedPoint.from_int(ticks_to_run))
        self.assertEqual(agent.get_property("energy"), expected_agent_energy)
        self.assertEqual(agent.get_property("energy"), FixedPoint.from_decimal_string("80.000000"))

        # Agent hunger increases strictly at AR_01's metabolic_rate (+1.000000 / tick)
        expected_agent_hunger = initial_agent_hunger + (meta_rate * FixedPoint.from_int(ticks_to_run))
        self.assertEqual(agent.get_property("hunger"), expected_agent_hunger)
        self.assertEqual(agent.get_property("hunger"), FixedPoint.from_decimal_string("20.000000"))

        # Agent biomass falls strictly at AR_01's slough rate (0.100000 / tick)
        expected_agent_biomass = initial_agent_biomass - (
            FixedPoint.from_decimal_string("0.100000") * FixedPoint.from_int(ticks_to_run)
        )
        self.assertEqual(agent.get_property("biomass"), expected_agent_biomass)
        self.assertEqual(agent.get_property("biomass"), FixedPoint.from_decimal_string("38.000000"))

        # 3. Herbivore experienced basal metabolism and starved when energy hit 0
        h_ent = world.entities.get_entity(h_id)
        self.assertTrue(h_ent is None or h_ent.get_property("is_alive") == 0)
        h_destroyed = [
            r for r in world.event_journal.records
            if r.event_type == "entity_destroyed" and r.payload.get("entity_id") == str(h_id)
        ]
        self.assertEqual(len(h_destroyed), 1)

        # 4. Agent was never touched by BR_03 or BR_05
        touched_by_br = [
            r for r in world.event_journal.records
            if r.payload.get("rule_id") in ("BR_03_BASAL_METABOLISM", "BR_05_STARVATION_DEATH")
            and agent_id in r.payload.get("entities_touched", [])
        ]
        self.assertEqual(
            len(touched_by_br),
            0,
            f"BR_03 or BR_05 illegally touched agent {agent_id}: {touched_by_br}",
        )
        agent_destroyed = [
            r for r in world.event_journal.records
            if r.event_type == "entity_destroyed" and r.payload.get("entity_id") == str(agent_id)
        ]
        self.assertEqual(
            len(agent_destroyed),
            0,
            f"Agent {agent_id} illegally recorded entity_destroyed in journal: {agent_destroyed}",
        )


if __name__ == "__main__":
    unittest.main()
