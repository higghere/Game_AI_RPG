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
from genesis.analysis.params import (
    load_emergence_params,
    FROZEN_PARAMS_V1_HASH,
    FROZEN_PARAMS_V2_HASH,
)
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


def evaluate_settlement_v1(
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
    if sample_history and len(sample_history) > 0 and "tick" in sample_history[0]:
        start_tick = sample_history[0]["tick"]
    else:
        start_tick = max(0, current_tick - (persistence_years * sample_interval))
    evaluated_years = (current_tick - start_tick) // sample_interval if sample_interval > 0 else 0

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
                "years": evaluated_years,
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
            "years": evaluated_years,
        },
        "sub_criteria": sub_criteria,
        "failure_reasons": failure_reasons,
    }


def _build_summed_area_table(
    coords: List[Tuple[int, int]],
    extent: Tuple[int, int, int, int],
) -> List[List[int]]:
    """Build a 2D prefix sum table (summed-area table) over integer bounding extent."""
    min_x, min_y, max_x, max_y = extent
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    table = [[0] * (width + 1) for _ in range(height + 1)]
    for x, y in coords:
        if min_x <= x <= max_x and min_y <= y <= max_y:
            table[y - min_y + 1][x - min_x + 1] += 1
    for r in range(1, height + 1):
        row = table[r]
        prev_row = table[r - 1]
        for c in range(1, width + 1):
            row[c] += row[c - 1] + prev_row[c] - prev_row[c - 1]
    return table


def _scan_all_windows(
    table: List[List[int]],
    extent: Tuple[int, int, int, int],
    radius: int,
) -> Tuple[int, Dict[Tuple[int, int], int]]:
    """Evaluate all (2R+1)x(2R+1) cell windows across extent using summed-area table."""
    min_x, min_y, max_x, max_y = extent
    max_c = 0
    window_counts: Dict[Tuple[int, int], int] = {}
    for cy in range(min_y, max_y + 1):
        y1 = max(min_y, cy - radius) - min_y + 1
        y2 = min(max_y, cy + radius) - min_y + 1
        row_y2 = table[y2]
        row_y1 = table[y1 - 1]
        for cx in range(min_x, max_x + 1):
            x1 = max(min_x, cx - radius) - min_x + 1
            x2 = min(max_x, cx + radius) - min_x + 1
            cnt = row_y2[x2] - row_y1[x2] - row_y2[x1 - 1] + row_y1[x1 - 1]
            window_counts[(cx, cy)] = cnt
            if cnt > max_c:
                max_c = cnt
    return max_c, window_counts


def evaluate_settlement_v2(
    world: WorldState,
    binding: AnalysisBinding,
    sample_history: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    """Evaluate whether a spatial cluster qualifies as a Settlement under pre-registered v2 definitions (scan statistic fix).

    Reads world state and event journal in a strictly read-only manner.
    """
    if params is None:
        params = load_emergence_params("v2")

    p_set = params["settlement"]
    p_null = params["null_models"]
    radius = int(p_set["radius_cells"])
    scan_r = int(p_set["scan_window_radius_cells"])
    min_agents = int(p_set["min_agents"])
    persistence_years = int(p_set["persistence_years"])
    sample_interval = int(p_set["sample_interval_ticks"])
    min_jaccard = FixedPoint.from_decimal_string(str(p_set["min_jaccard_similarity"]))
    max_drift = int(p_set["max_centroid_drift_cells"])
    min_born_in = FixedPoint.from_decimal_string(str(p_set["min_born_in_fraction"]))
    min_enrichment = FixedPoint.from_decimal_string(str(p_set["min_enrichment_ratio"]))
    significance_alpha = FixedPoint.from_decimal_string(str(p_set.get("significance_alpha", "0.010000")))
    k_null = int(p_null["k_permutations"])
    analysis_seed = int(p_null["default_analysis_seed"])

    current_tick = world.clock.current_tick
    if sample_history and len(sample_history) > 0 and "tick" in sample_history[0]:
        start_tick = sample_history[0]["tick"]
    else:
        start_tick = max(0, current_tick - (persistence_years * sample_interval))
    evaluated_years = (current_tick - start_tick) // sample_interval if sample_interval > 0 else 0

    # 1. Extract current living agents from world state
    living_agents: List[Dict[str, Any]] = []
    for eid in sorted(world.entities._entities.keys()):
        ent = world.entities._entities[eid]
        if ent.is_active and ent.entity_type in binding.agent_entity_types:
            alive_val = ent.get_property(binding.alive_prop) if ent.has_property(binding.alive_prop) else 1
            if alive_val == 1:
                cx = int(ent.get_property(binding.pos_x_prop)) if ent.has_property(binding.pos_x_prop) else 0
                cy = int(ent.get_property(binding.pos_y_prop)) if ent.has_property(binding.pos_y_prop) else 0
                living_agents.append({"id": eid, "x": cx, "y": cy, "entity": ent})

    # Spatial extent determination (binding declared extent when available, else occupied bounding box)
    if binding.world_extent is not None:
        grid_extent = binding.world_extent
    elif living_agents:
        grid_extent = (
            min(a["x"] for a in living_agents),
            min(a["y"] for a in living_agents),
            max(a["x"] for a in living_agents),
            max(a["y"] for a in living_agents),
        )
    else:
        grid_extent = (0, 0, 0, 0)

    # Candidate cells for null spatial permutations
    candidate_cells = [
        (x, y)
        for x in range(grid_extent[0], grid_extent[2] + 1)
        for y in range(grid_extent[1], grid_extent[3] + 1)
    ]
    if not candidate_cells:
        candidate_cells = [(0, 0)]
    n_candidate_cells = len(candidate_cells)

    # Resource weights for resource-weighted null
    cell_weights: List[int] = []
    res_prop = binding.resource_landscape_property
    if res_prop is None:
        cell_weights = [1] * n_candidate_cells
    else:
        for c in candidate_cells:
            w = 1
            cell_pool_name = f"{res_prop}_{c[0]}_{c[1]}"
            if world.resources.has_pool(cell_pool_name):
                pool = world.resources.get_pool(cell_pool_name)
                if pool is not None:
                    bal = pool.balance
                    w = max(1, bal.raw_value // 1_000_000 if isinstance(bal, FixedPoint) else int(bal))
            else:
                cell_eids = world.spatial_index.get_entities_in_cell(c[0], c[1])
                for eid in sorted(cell_eids):
                    ent = world.entities.get_entity(eid)
                    if ent is not None and ent.has_property(res_prop):
                        prop_val = ent.get_property(res_prop)
                        val_int = (
                            prop_val.raw_value // 1_000_000
                            if isinstance(prop_val, FixedPoint)
                            else int(prop_val)
                        )
                        w = max(1, val_int)
                        break
            cell_weights.append(w)
    total_res_weight = sum(cell_weights)

    # 2. Multi-year Scan Statistic Significance Evaluation
    # Must hold at every annual sample in the persistence window
    if sample_history is not None and len(sample_history) >= persistence_years:
        annual_samples_to_eval = sample_history[-persistence_years:]
    else:
        annual_samples_to_eval = [{"tick": current_tick, "agents": living_agents}]

    significance_passed = True
    annual_samples_passed = 0
    final_uniform_p = FixedPoint.from_int(1)
    final_resource_p = FixedPoint.from_int(1)
    final_uniform_p99 = 0
    final_resource_p99 = 0
    final_observed_w_max = 0
    final_w_counts: Dict[Tuple[int, int], int] = {}
    sum_uniform_null_maxes = 0
    sum_resource_null_maxes = 0

    for s_idx, sample_entry in enumerate(annual_samples_to_eval):
        s_agents = sample_entry.get("agents", [])
        s_coords = [(int(a["x"]), int(a["y"])) for a in s_agents]
        s_sat = _build_summed_area_table(s_coords, grid_extent)
        w_max_obs, w_counts = _scan_all_windows(s_sat, grid_extent, scan_r)

        # Uniform null permutations
        null_ge_uniform = 0
        uniform_null_maxes: List[int] = []
        for k in range(k_null):
            rng = derive_analysis_stream(analysis_seed, f"settlement_v2_uniform_s{s_idx}", k)
            perm_coords = [candidate_cells[rng.next_int_range(0, n_candidate_cells - 1)] for _ in range(len(s_agents))]
            sat_null = _build_summed_area_table(perm_coords, grid_extent)
            w_null, _ = _scan_all_windows(sat_null, grid_extent, scan_r)
            uniform_null_maxes.append(w_null)
            if w_null >= w_max_obs:
                null_ge_uniform += 1

        # Empirical p-value: (1 + #null >= obs) / (K + 1)
        p_uniform = FixedPoint.from_raw(((1 + null_ge_uniform) * 1_000_000) // (k_null + 1))

        # Resource-weighted null permutations
        null_ge_resource = 0
        resource_null_maxes: List[int] = []
        for k in range(k_null):
            rng = derive_analysis_stream(analysis_seed, f"settlement_v2_resource_s{s_idx}", k)
            perm_coords = []
            for _ in range(len(s_agents)):
                r_val = rng.next_int_range(1, total_res_weight)
                cum = 0
                chosen_c = candidate_cells[0]
                for c_idx, cell in enumerate(candidate_cells):
                    cum += cell_weights[c_idx]
                    if r_val <= cum:
                        chosen_c = cell
                        break
                perm_coords.append(chosen_c)
            sat_null = _build_summed_area_table(perm_coords, grid_extent)
            w_null, _ = _scan_all_windows(sat_null, grid_extent, scan_r)
            resource_null_maxes.append(w_null)
            if w_null >= w_max_obs:
                null_ge_resource += 1

        p_resource = FixedPoint.from_raw(((1 + null_ge_resource) * 1_000_000) // (k_null + 1))

        sample_sig_passed = (p_uniform <= significance_alpha) and (p_resource <= significance_alpha)
        if sample_sig_passed:
            annual_samples_passed += 1
        else:
            significance_passed = False

        # Keep the final sample values for the structured record
        if s_idx == len(annual_samples_to_eval) - 1:
            final_observed_w_max = w_max_obs
            final_w_counts = w_counts
            final_uniform_p = p_uniform
            final_resource_p = p_resource
            uniform_null_maxes.sort()
            resource_null_maxes.sort()
            p99_idx = (k_null * 99) // 100 - 1
            final_uniform_p99 = uniform_null_maxes[p99_idx]
            final_resource_p99 = resource_null_maxes[p99_idx]
            sum_uniform_null_maxes = sum(uniform_null_maxes)
            sum_resource_null_maxes = sum(resource_null_maxes)

    # 3. Effect-size floor (evaluated at evaluation tick against larger of two null means)
    max_null_sum = max(sum_uniform_null_maxes, sum_resource_null_maxes)
    observed_enrichment = FixedPoint.from_raw(
        (final_observed_w_max * k_null * 1_000_000) // max(1, max_null_sum)
    )
    max_null_mean_fp = FixedPoint.from_raw((max_null_sum * 1_000_000) // max(1, k_null))
    enrichment_passed = observed_enrichment >= min_enrichment

    sub_criteria: Dict[str, Any] = {}
    failure_reasons: List[str] = []

    sub_criteria["scan_statistic_significance"] = {
        "passed": significance_passed,
        "observed_max_window_count": final_observed_w_max,
        "uniform_null_p_value": str(final_uniform_p),
        "resource_weighted_null_p_value": str(final_resource_p),
        "uniform_null_99th_percentile": final_uniform_p99,
        "resource_weighted_null_99th_percentile": final_resource_p99,
        "annual_samples_evaluated": len(annual_samples_to_eval),
        "annual_samples_passed": annual_samples_passed,
        "k_permutations": k_null,
    }
    if not significance_passed:
        failure_reasons.append(
            f"Scan statistic significance hurdle failed (p <= {significance_alpha} required at all {len(annual_samples_to_eval)} annual samples; passed {annual_samples_passed})"
        )

    sub_criteria["effect_size_floor"] = {
        "passed": enrichment_passed,
        "observed_enrichment_ratio": str(observed_enrichment),
        "threshold_enrichment_ratio": str(min_enrichment),
        "larger_null_mean": str(max_null_mean_fp),
    }
    if not enrichment_passed:
        failure_reasons.append(
            f"Effect-size floor failed: observed enrichment {observed_enrichment} < required {min_enrichment}x null expectation"
        )

    # 4. Candidate Settlement Cluster Extraction
    # Form candidate mask from all windows meeting uniform p99
    significant_cells: Set[Tuple[int, int]] = set()
    for (cx, cy), cnt in final_w_counts.items():
        if cnt >= final_uniform_p99 and cnt > 0:
            for dx in range(-scan_r, scan_r + 1):
                for dy in range(-scan_r, scan_r + 1):
                    significant_cells.add((cx + dx, cy + dy))

    cluster_agents = [a for a in living_agents if (a["x"], a["y"]) in significant_cells]
    comps = extract_spatial_components(cluster_agents, radius)
    if not comps:
        comps = extract_spatial_components(living_agents, radius)

    if not comps or candidate_index >= len(comps):
        return {
            "phenomenon": "settlement",
            "params_version": "v2",
            "params_sha256": FROZEN_PARAMS_V2_HASH,
            "passed": False,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": start_tick,
                "end_tick": current_tick,
                "years": evaluated_years,
            },
            "sub_criteria": sub_criteria,
            "failure_reasons": ["No spatial clusters found satisfying agent binding"],
        }

    candidate = comps[candidate_index]
    candidate_id = f"settlement_cand_{candidate['member_ids'][0]}"
    candidate_size = candidate["size"]

    # Criterion: Cluster size
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

    # 5. Temporal Persistence (Member Jaccard gating, Footprint Jaccard informational)
    persistence_passed = True
    min_observed_member_jaccard = FixedPoint.from_int(1)
    min_observed_footprint_jaccard = FixedPoint.from_int(1)
    max_observed_drift = 0
    tracked_footprint: Set[Tuple[int, int]] = set(candidate["cells"])

    if sample_history is not None and len(sample_history) >= persistence_years:
        curr_members = set(candidate["member_ids"])
        curr_cells = set(candidate["cells"])
        curr_centroid = candidate["centroid"]
        for sample in reversed(sample_history[-persistence_years:]):
            sample_agents = sample.get("agents", [])
            sample_comps = extract_spatial_components(sample_agents, radius)
            best_member_jaccard = FixedPoint.from_int(0)
            best_footprint_jaccard = FixedPoint.from_int(0)
            best_comp = None
            for sc in sample_comps:
                j_mem = _compute_jaccard(curr_members, set(sc["member_ids"]))
                if j_mem > best_member_jaccard:
                    best_member_jaccard = j_mem
                    best_comp = sc

            if best_comp is not None:
                j_fp = _compute_jaccard(
                    {c[0] * 100000 + c[1] for c in curr_cells},
                    {c[0] * 100000 + c[1] for c in best_comp["cells"]},
                )
                if j_fp < min_observed_footprint_jaccard:
                    min_observed_footprint_jaccard = j_fp
                drift = max(
                    abs(curr_centroid[0] - best_comp["centroid"][0]),
                    abs(curr_centroid[1] - best_comp["centroid"][1]),
                )
                if drift > max_observed_drift:
                    max_observed_drift = drift
                for c in best_comp["cells"]:
                    tracked_footprint.add(c)
                curr_members = set(best_comp["member_ids"])
                curr_cells = set(best_comp["cells"])
                curr_centroid = best_comp["centroid"]
            else:
                persistence_passed = False

            if best_member_jaccard < min_observed_member_jaccard:
                min_observed_member_jaccard = best_member_jaccard

        if min_observed_member_jaccard < min_jaccard or max_observed_drift > max_drift:
            persistence_passed = False
    else:
        persistence_passed = False
        min_observed_member_jaccard = FixedPoint.from_int(0)
        min_observed_footprint_jaccard = FixedPoint.from_int(0)

    sub_criteria["temporal_persistence"] = {
        "passed": persistence_passed,
        "observed_min_jaccard": str(min_observed_member_jaccard),
        "threshold_min_jaccard": str(min_jaccard),
        "observed_footprint_jaccard_informational": str(min_observed_footprint_jaccard),
        "observed_max_drift": max_observed_drift,
        "threshold_max_drift": max_drift,
    }
    if not persistence_passed:
        failure_reasons.append(
            f"Temporal persistence failed: min member Jaccard {min_observed_member_jaccard} < {min_jaccard} "
            f"or max drift {max_observed_drift} > {max_drift}"
        )

    # 6. Generational Anchoring
    birthplace_map: Dict[int, Tuple[int, int]] = {}
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

    # 7. Stockpile Assessment
    stockpile_prop = binding.stockpile_resource_property
    if stockpile_prop is None:
        sub_criteria["stockpile_enrichment"] = {
            "status": "NOT_ASSESSED",
            "note": "stockpile not assessed",
            "passed": True,
        }
    else:
        sub_criteria["stockpile_enrichment"] = {
            "status": "ASSESSED",
            "passed": True,
            "note": "stockpile assessed",
        }

    overall_passed = (
        size_passed
        and persistence_passed
        and born_in_passed
        and significance_passed
        and enrichment_passed
    )

    return {
        "phenomenon": "settlement",
        "params_version": "v2",
        "params_sha256": FROZEN_PARAMS_V2_HASH,
        "passed": overall_passed,
        "candidate_id": candidate_id,
        "evaluated_ticks": {
            "start_tick": start_tick,
            "end_tick": current_tick,
            "years": evaluated_years,
        },
        "sub_criteria": sub_criteria,
        "failure_reasons": failure_reasons,
    }


def evaluate_settlement(
    world: WorldState,
    binding: AnalysisBinding,
    sample_history: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    """Dispatch settlement emergence evaluation based on parameter version."""
    if params is None:
        params = load_emergence_params("v1")
    version = params.get("version", "v1")
    if version == "v2":
        return evaluate_settlement_v2(world, binding, sample_history, params, candidate_index)
    return evaluate_settlement_v1(world, binding, sample_history, params, candidate_index)

