"""GENESIS Ecosystem Metrics Helper.

Provides read-only, deterministic queries for trophic guild abundance,
living biomass, resource balances, and closed-system mass conservation.
"""

from __future__ import annotations
from typing import Any, Dict

from genesis.core.arithmetic import FixedPoint
from genesis.substrate.world_state import WorldState


def get_ecosystem_metrics(world: WorldState) -> Dict[str, Any]:
    """Compute read-only, deterministic ecosystem metrics at the current tick."""
    populations: Dict[str, int] = {
        "autotroph": 0,
        "herbivore": 0,
        "decomposer": 0,
    }
    living_biomass = FixedPoint.from_int(0)

    # Deterministic iteration over entities sorted by ID
    for eid in sorted(world.entities._entities.keys()):
        ent = world.entities._entities[eid]
        if ent.is_active:
            if ent.entity_type in populations:
                populations[ent.entity_type] += 1
            if ent.has_property("biomass"):
                bm = ent.get_property("biomass")
                if isinstance(bm, FixedPoint):
                    living_biomass += bm
                elif isinstance(bm, int):
                    living_biomass += FixedPoint.from_int(bm)

    total_pop = sum(populations.values())

    # Resource balances
    resource_balances: Dict[str, FixedPoint] = {}
    for pool in world.resources.all_pools():
        resource_balances[pool.name] = pool.balance

    soil_water = resource_balances.get("soil_water", FixedPoint.from_int(0))
    soil_minerals = resource_balances.get("soil_minerals", FixedPoint.from_int(0))
    detritus = resource_balances.get("detritus", FixedPoint.from_int(0))

    total_closed_mass = living_biomass + soil_water + soil_minerals + detritus

    occupied_cells = world.spatial_index.get_occupied_cells()

    return {
        "tick": world.clock.current_tick,
        "populations": populations,
        "total_population": total_pop,
        "living_biomass": living_biomass,
        "resource_balances": resource_balances,
        "total_closed_mass": total_closed_mass,
        "cell_occupancy": len(occupied_cells),
    }
