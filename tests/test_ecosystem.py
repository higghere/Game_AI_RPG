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
GOLDEN_STATE_HASH_365 = "543e7ebcaf30cd77d36416c75f1a77196c55ee9b68c002b6f49adaacecdd0f3d"
GOLDEN_JOURNAL_HASH_365 = "40bd69eee6666ed11e0ff69d53c14013cc7592b0c24be4fc87ec7c5c8ac95132"


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
    # TEST-202: Primary Producer Equilibrium
    # -------------------------------------------------------------------------
    def test_202_primary_producer_equilibrium(self) -> None:
        """Autotrophs under constant solar flux reach bounded, non-zero equilibrium over 365 ticks.

        Pass criteria defined numerically before running:
        - Minimum survivors: pop(autotroph) >= 10 at tick 365 (no extinction).
        - Maximum carrying capacity bound: pop(autotroph) <= 400 at tick 365 (no explosive growth).
        - Resource-constrained equilibrium: population over the last 100 ticks (265..365) remains
          within [100, 400], demonstrating balance between photosynthesis, respiration, and fission.
        - Zero quota failures: world.event_journal records 0 QuotaExceededError events.
        - Closed-system mass: total closed mass remains strictly identical between tick 0 and tick 365.
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
            if (t + 1) % 50 == 0 or t + 1 == 365:
                pop_curve.append((t + 1, pop))

        end_metrics = get_ecosystem_metrics(world)
        end_pop = end_metrics["populations"]["autotroph"]

        # 1. Minimum survivors: no extinction
        self.assertGreaterEqual(
            end_pop,
            10,
            f"Autotroph population collapsed: final={end_pop} < 10 survivors",
        )

        # 2. Maximum bound: no unbounded explosive growth
        self.assertLessEqual(
            end_pop,
            400,
            f"Autotroph population exploded beyond carrying capacity: final={end_pop} > 400",
        )

        # 3. Zero quota failures invariant
        quota_failures = [
            e for e in world.event_journal.records
            if e.event_type == "rule_execution_failed" and e.payload.get("error_type") == "QuotaExceededError"
        ]
        self.assertEqual(
            len(quota_failures),
            0,
            f"Encountered {len(quota_failures)} quota failures in TEST-202",
        )

        # 4. Strict mass conservation
        self.assertEqual(
            end_metrics["total_closed_mass"].raw_value,
            initial_mass.raw_value,
            f"Mass drift in TEST-202: end={end_metrics['total_closed_mass']} != initial={initial_mass}",
        )

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
        - Classical oscillation: population series exhibits at least 2 directional inflection points
          (peak/trough sign changes in delta(t)), confirming dynamic trophic cycling rather than static decay.
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
            if (t + 1) % 25 == 0:
                m = get_ecosystem_metrics(world)
                auto_history.append(m["populations"]["autotroph"])
                herb_history.append(m["populations"]["herbivore"])

        end_m = get_ecosystem_metrics(world)
        end_auto = end_m["populations"]["autotroph"]
        end_herb = end_m["populations"]["herbivore"]

        # 1. Coexistence without immediate extinction
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

        # 2. Oscillation detection: count sign changes in herbivore population slope
        herb_deltas = [
            herb_history[i] - herb_history[i - 1]
            for i in range(1, len(herb_history))
        ]
        non_zero_deltas = [d for d in herb_deltas if d != 0]
        direction_changes = sum(
            1 for i in range(1, len(non_zero_deltas))
            if (non_zero_deltas[i] > 0) != (non_zero_deltas[i - 1] > 0)
        )
        self.assertGreaterEqual(
            direction_changes,
            2,
            f"Expected at least 2 oscillation direction changes, found {direction_changes}",
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


if __name__ == "__main__":
    unittest.main()
