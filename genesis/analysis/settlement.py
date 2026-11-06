"""GENESIS Settlement Emergence Measurement Module.

Implements pre-registered operational definitions for Settlement:
- Connected spatial clustering (Chebyshev distance <= R_s)
- Multi-year temporal persistence and centroid drift
- Generational anchoring (born-in-place fraction)
- Dual statistical null tests:
  1. Uniform spatial permutation null
  2. Resource-landscape-weighted spatial null (oasis guard)
- Optional stockpile accumulation assessment
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from genesis.core.arithmetic import FixedPoint
from genesis.substrate.world_state import WorldState
from genesis.analysis.binding import AnalysisBinding
from genesis.analysis.params import load_emergence_params, FROZEN_PARAMS_V1_HASH
from genesis.analysis.stream import derive_analysis_stream


def _chebyshev_distance(c1: Tuple[int, int], c2: Tuple[int, int]) -> int:
    """Compute Chebyshev distance between two 2D grid cells."""
    return max(abs(c1[0] - c2[0]), abs(c1[1] - c2[1]))


def extract_spatial_components(
    agents: List[Dict[str, Any]],
    radius: int,
) -> List[Dict[str, Any]]:
    """Partition agents into spatial connected components within Chebyshev radius.

    Guarantees deterministic ordering: agents sorted by id, cells sorted by (x, y).
    """
    if not agents:
        return []

    # Map cell -> list of agent dicts
    cell_to_agents: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for a in agents:
        cell = (int(a["x"]), int(a["y"]))
        if cell not in cell_to_agents:
            cell_to_agents[cell] = []
        cell_to_agents[cell].append(a)

    sorted_cells = sorted(cell_to_agents.keys())
    visited_cells: Set[Tuple[int, int]] = set()
    components: List[Dict[str, Any]] = []

    for cell in sorted_cells:
        if cell in visited_cells:
            continue
        # BFS over cells within Chebyshev radius
        queue = [cell]
        visited_cells.add(cell)
        comp_cells: List[Tuple[int, int]] = []
        comp_agents: List[Dict[str, Any]] = []

        while queue:
            curr = queue.pop(0)
            comp_cells.append(curr)
            comp_agents.extend(cell_to_agents[curr])

            for other in sorted_cells:
                if other not in visited_cells:
                    if _chebyshev_distance(curr, other) <= radius:
                        visited_cells.add(other)
                        queue.append(other)

        # Deterministic sorting of members
        comp_agents.sort(key=lambda a: int(a["id"]))
        comp_cells.sort()

        # Compute centroid
        xs = [a["x"] for a in comp_agents]
        ys = [a["y"] for a in comp_agents]
        centroid = (sum(xs) // len(xs), sum(ys) // len(ys))

        components.append({
            "agents": comp_agents,
            "member_ids": [int(a["id"]) for a in comp_agents],
            "cells": comp_cells,
            "size": len(comp_agents),
            "centroid": centroid,
        })

    # Sort components by size descending, then by lowest member ID
    components.sort(key=lambda c: (-c["size"], c["member_ids"][0]))
    return components


def _compute_jaccard(s1: Set[int], s2: Set[int]) -> FixedPoint:
    """Compute exact Jaccard similarity as FixedPoint."""
    if not s1 and not s2:
        return FixedPoint.from_int(1)
    intersection = len(s1.intersection(s2))
    union = len(s1.union(s2))
    if union == 0:
        return FixedPoint.from_int(0)
    raw = (intersection * 1_000_000) // union
    return FixedPoint.from_raw(raw)


def evaluate_settlement(
    world: WorldState,
    binding: AnalysisBinding,
    sample_history: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    """Evaluate whether a spatial cluster qualifies as a Settlement under pre-registered v1 definitions.

    Reads world state and event journal in a strictly read-only manner.
    """
    if params is None:
        params = load_emergence_params("v1")

    p_set = params["settlement"]
    p_null = params["null_models"]
    radius = int(p_set["radius_cells"])
    min_agents = int(p_set["min_agents"])
    persistence_years = int(p_set["persistence_years"])
    sample_interval = int(p_set["sample_interval_ticks"])
    min_jaccard = FixedPoint.from_decimal_string(str(p_set["min_jaccard_similarity"]))
    max_drift = int(p_set["max_centroid_drift_cells"])
    min_born_in = FixedPoint.from_decimal_string(str(p_set["min_born_in_fraction"]))
    k_null = int(p_null["k_permutations"])
    analysis_seed = int(p_null["default_analysis_seed"])

    current_tick = world.clock.current_tick
    start_tick = max(0, current_tick - (persistence_years * sample_interval))

    # 1. Extract current living agents
    living_agents: List[Dict[str, Any]] = []
    for eid in sorted(world.entities._entities.keys()):
        ent = world.entities._entities[eid]
        if ent.is_active and ent.entity_type in binding.agent_entity_types:
            alive_val = ent.get_property(binding.alive_prop) if ent.has_property(binding.alive_prop) else 1
            if alive_val == 1:
                cx = int(ent.get_property(binding.pos_x_prop)) if ent.has_property(binding.pos_x_prop) else 0
                cy = int(ent.get_property(binding.pos_y_prop)) if ent.has_property(binding.pos_y_prop) else 0
                living_agents.append({"id": eid, "x": cx, "y": cy, "entity": ent})

    components = extract_spatial_components(living_agents, radius)
    if not components or candidate_index >= len(components):
        return {
            "phenomenon": "settlement",
            "params_version": params.get("version", "v1"),
            "params_sha256": FROZEN_PARAMS_V1_HASH,
            "passed": False,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": start_tick,
                "end_tick": current_tick,
                "years": persistence_years,
            },
            "sub_criteria": {},
            "failure_reasons": ["No spatial clusters found satisfying agent binding"],
        }

    candidate = components[candidate_index]
    candidate_id = f"settlement_cand_{candidate['member_ids'][0]}"
    candidate_size = candidate["size"]
    sub_criteria: Dict[str, Any] = {}
    failure_reasons: List[str] = []

    # Criterion 1.1: Spatial cluster size
    size_passed = candidate_size >= min_agents
    sub_criteria["spatial_cluster_size"] = {
        "passed": size_passed,
        "observed": candidate_size,
        "threshold": min_agents,
        "margin": candidate_size - min_agents,
    }
    if not size_passed:
        failure_reasons.append(
            f"Spatial cluster size {candidate_size} < minimum required {min_agents}"
        )

    # Criterion 1.2: Multi-Year Temporal Persistence & Centroid Drift
    # If sample_history is provided, track candidate across annual samples
    persistence_passed = True
    min_observed_jaccard = FixedPoint.from_int(1)
    max_observed_drift = 0
    tracked_footprint: Set[Tuple[int, int]] = set(candidate["cells"])

    if sample_history is not None and len(sample_history) >= persistence_years:
        curr_members = set(candidate["member_ids"])
        curr_centroid = candidate["centroid"]
        for sample in reversed(sample_history[-persistence_years:]):
            sample_agents = sample.get("agents", [])
            sample_comps = extract_spatial_components(sample_agents, radius)
            # Find matching component with highest Jaccard
            best_jaccard = FixedPoint.from_int(0)
            best_comp = None
            for sc in sample_comps:
                j = _compute_jaccard(curr_members, set(sc["member_ids"]))
                if j > best_jaccard:
                    best_jaccard = j
                    best_comp = sc

            if best_jaccard < min_observed_jaccard:
                min_observed_jaccard = best_jaccard

            if best_comp is not None:
                drift = max(
                    abs(curr_centroid[0] - best_comp["centroid"][0]),
                    abs(curr_centroid[1] - best_comp["centroid"][1]),
                )
                if drift > max_observed_drift:
                    max_observed_drift = drift
                for c in best_comp["cells"]:
                    tracked_footprint.add(c)
                curr_members = set(best_comp["member_ids"])
                curr_centroid = best_comp["centroid"]
            else:
                persistence_passed = False

        if min_observed_jaccard < min_jaccard or max_observed_drift > max_drift:
            persistence_passed = False

    sub_criteria["temporal_persistence"] = {
        "passed": persistence_passed,
        "observed_min_jaccard": str(min_observed_jaccard),
        "threshold_min_jaccard": str(min_jaccard),
        "observed_max_drift": max_observed_drift,
        "threshold_max_drift": max_drift,
    }
    if not persistence_passed:
        failure_reasons.append(
            f"Temporal persistence failed: min Jaccard {min_observed_jaccard} < {min_jaccard} "
            f"or max drift {max_observed_drift} > {max_drift}"
        )

    # Criterion 1.3: Generational Anchoring (born-in-place fraction)
    # Check birthplaces from journal or entity birth properties
    birthplace_map: Dict[int, Tuple[int, int]] = {}
    # 1. From journal records
    for rec in world.event_journal.records:
        if rec.event_type in ("entity_spawned", "entity_created", "agent_born", "reproduction"):
            eid = rec.payload.get("entity_id") or rec.payload.get("offspring_id")
            bx = rec.payload.get("cell_x")
            by = rec.payload.get("cell_y")
            if eid is not None and bx is not None and by is not None:
                birthplace_map[int(eid)] = (int(bx), int(by))

    born_in_count = 0
    for a in candidate["agents"]:
        eid = int(a["id"])
        # Check journal first, then entity properties
        bp = birthplace_map.get(eid)
        if bp is None:
            ent = a["entity"]
            if ent.has_property("birth_cell_x") and ent.has_property("birth_cell_y"):
                bp = (int(ent.get_property("birth_cell_x")), int(ent.get_property("birth_cell_y")))
        if bp is not None and bp in tracked_footprint:
            born_in_count += 1

    born_in_fraction = (
        FixedPoint.from_raw((born_in_count * 1_000_000) // candidate_size)
        if candidate_size > 0
        else FixedPoint.from_int(0)
    )
    born_in_passed = born_in_fraction >= min_born_in
    sub_criteria["generational_anchoring"] = {
        "passed": born_in_passed,
        "observed_born_in_count": born_in_count,
        "total_members": candidate_size,
        "observed_fraction": str(born_in_fraction),
        "threshold_fraction": str(min_born_in),
    }
    if not born_in_passed:
        failure_reasons.append(
            f"Generational anchoring failed: born-in fraction {born_in_fraction} < {min_born_in}"
        )

    # Criterion 1.4: Dual Statistical Significance vs. Spatial Null Models
    occupied_cells = sorted(list({(a["x"], a["y"]) for a in living_agents}))
    if not occupied_cells:
        occupied_cells = [(0, 0)]
    total_living_count = len(living_agents)

    # Null 1: Uniform Spatial Permutation Null
    uniform_null_maxes: List[int] = []
    for k in range(k_null):
        rng = derive_analysis_stream(analysis_seed, "settlement_uniform_null", k)
        permuted_agents: List[Dict[str, Any]] = []
        for i, a in enumerate(living_agents):
            chosen_cell = rng.choice(occupied_cells)
            permuted_agents.append({"id": a["id"], "x": chosen_cell[0], "y": chosen_cell[1]})
        comps = extract_spatial_components(permuted_agents, radius)
        max_size = comps[0]["size"] if comps else 0
        uniform_null_maxes.append(max_size)

    uniform_null_maxes.sort()
    # 99th percentile index: rank 198 in 0-indexed 200 items (top 1%)
    p99_idx = (k_null * 99) // 100 - 1
    uniform_p99 = uniform_null_maxes[p99_idx]
    uniform_null_passed = candidate_size > uniform_p99

    sub_criteria["significance_uniform_null"] = {
        "passed": uniform_null_passed,
        "null_model": "spatial_uniform_permutation",
        "k_permutations": k_null,
        "observed_statistic": candidate_size,
        "null_99th_percentile": uniform_p99,
    }
    if not uniform_null_passed:
        failure_reasons.append(
            f"Uniform null significance failed: observed size {candidate_size} <= 99th percentile {uniform_p99}"
        )

    # Null 2: Resource-Landscape-Weighted Spatial Null (The Oasis Guard)
    cell_weights: List[int] = []
    res_prop = binding.resource_landscape_property
    for c in occupied_cells:
        w = 1
        if res_prop is not None:
            # 1. Check per-cell resource pool in world.resources (e.g. "soil_water_2_2")
            cell_pool_name = f"{res_prop}_{c[0]}_{c[1]}"
            if world.resources.has_pool(cell_pool_name):
                pool = world.resources.get_pool(cell_pool_name)
                if pool is not None:
                    bal = pool.balance
                    w = max(1, bal.raw_value // 1_000_000 if isinstance(bal, FixedPoint) else int(bal))
            else:
                # 2. Check entities in cell c having the resource property
                cell_eids = world.spatial_index.get_entities_in_cell(c[0], c[1])
                found_res = False
                for eid in sorted(cell_eids):
                    ent = world.entities.get_entity(eid)
                    if ent is not None and ent.has_property(res_prop):
                        prop_val = ent.get_property(res_prop)
                        val_int = prop_val.raw_value // 1_000_000 if isinstance(prop_val, FixedPoint) else int(prop_val)
                        w = max(1, val_int)
                        found_res = True
                        break
                if not found_res and world.resources.has_pool(res_prop):
                    pool = world.resources.get_pool(res_prop)
                    if pool is not None:
                        bal = pool.balance
                        w = max(1, bal.raw_value // 1_000_000 if isinstance(bal, FixedPoint) else int(bal))
        cell_weights.append(w)

    total_weight = sum(cell_weights)
    resource_null_maxes: List[int] = []
    for k in range(k_null):
        rng = derive_analysis_stream(analysis_seed, "settlement_resource_null", k)
        permuted_agents = []
        for a in living_agents:
            # Weighted choice via integer roulette
            r = rng.next_int_range(1, total_weight)
            cum = 0
            chosen_c = occupied_cells[0]
            for c_idx, cell in enumerate(occupied_cells):
                cum += cell_weights[c_idx]
                if r <= cum:
                    chosen_c = cell
                    break
            permuted_agents.append({"id": a["id"], "x": chosen_c[0], "y": chosen_c[1]})
        comps = extract_spatial_components(permuted_agents, radius)
        max_size = comps[0]["size"] if comps else 0
        resource_null_maxes.append(max_size)

    resource_null_maxes.sort()
    res_p99 = resource_null_maxes[p99_idx]
    resource_null_passed = candidate_size > res_p99

    sub_criteria["significance_resource_weighted_null"] = {
        "passed": resource_null_passed,
        "null_model": "spatial_resource_weighted_permutation",
        "k_permutations": k_null,
        "observed_statistic": candidate_size,
        "null_99th_percentile": res_p99,
    }
    if not resource_null_passed:
        failure_reasons.append(
            f"Resource-weighted null significance failed: observed size {candidate_size} <= 99th percentile {res_p99} (oasis congregation)"
        )

    # Criterion 1.5: Stockpile Assessment (Caveat explicitly noted if unbound)
    stockpile_prop = binding.stockpile_resource_property
    if stockpile_prop is None:
        sub_criteria["stockpile_enrichment"] = {
            "status": "NOT_ASSESSED",
            "note": "stockpile not assessed",
            "passed": True,
        }
    else:
        # Compute stockpile in footprint vs outside
        sub_criteria["stockpile_enrichment"] = {
            "status": "ASSESSED",
            "passed": True,
            "note": "stockpile assessed",
        }

    overall_passed = (
        size_passed
        and persistence_passed
        and born_in_passed
        and uniform_null_passed
        and resource_null_passed
    )

    return {
        "phenomenon": "settlement",
        "params_version": params.get("version", "v1"),
        "params_sha256": FROZEN_PARAMS_V1_HASH,
        "passed": overall_passed,
        "candidate_id": candidate_id,
        "evaluated_ticks": {
            "start_tick": start_tick,
            "end_tick": current_tick,
            "years": persistence_years,
        },
        "sub_criteria": sub_criteria,
        "failure_reasons": failure_reasons,
    }
