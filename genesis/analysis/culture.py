"""GENESIS Cultural Spread Emergence Measurement Module.

Implements pre-registered operational definitions for Cultural Spread:
- Social transmission beyond extended kin (common ancestor <= 4 generations counted as kin)
- Lineage breadth (>= 3 distinct genealogical lineage roots)
- Demographic reach (>= 10% and >= 8 living agents)
- Spatial expansion (span >= 2 cells from founding cell)
- Transmission speed outrunning genetic descent (speed ratio >= 2.0)
- High copying fidelity (>= 90% exact replication)
- Post-founder generational persistence (>= 5 adopters after all founders dead)
- Significance vs. random adoption null model (99th percentile)
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


def get_ancestors_up_to_depth(
    parent_map: Dict[int, List[int]],
    agent_id: int,
    max_depth: int = 4,
) -> Set[int]:
    """Find all ancestors of an agent up to max_depth generations back."""
    ancestors: Set[int] = set()
    queue = [(agent_id, 0)]
    visited = {agent_id}

    while queue:
        curr, depth = queue.pop(0)
        if depth < max_depth:
            for p in parent_map.get(curr, []):
                if p not in visited:
                    visited.add(p)
                    ancestors.add(p)
                    queue.append((p, depth + 1))

    return ancestors


def are_extended_kin(
    parent_map: Dict[int, List[int]],
    a: int,
    b: int,
    max_depth: int = 4,
) -> bool:
    """Determine if agents a and b share a common ancestor within max_depth generations."""
    if a == b:
        return True
    anc_a = get_ancestors_up_to_depth(parent_map, a, max_depth)
    anc_b = get_ancestors_up_to_depth(parent_map, b, max_depth)

    # Check direct ancestor/descendant
    if a in anc_b or b in anc_a:
        return True

    # Check common ancestor
    return len(anc_a.intersection(anc_b)) > 0


def evaluate_cultural_spread(
    world: WorldState,
    binding: AnalysisBinding,
    eval_tick: int,
    window_start_tick: int = 0,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate whether a practice exhibits Cultural Spread under pre-registered v1 definitions.

    Reads world state and event journal in a strictly read-only manner.
    """
    if params is None:
        params = load_emergence_params("v1")

    p_cul = params["cultural_spread"]
    p_null = params["null_models"]
    max_kin_gen = int(p_cul["max_common_ancestor_generations"])
    min_non_kin = FixedPoint.from_decimal_string(str(p_cul["min_non_kin_transmission_fraction"]))
    min_lineages = int(p_cul["min_distinct_lineages"])
    min_adopt_frac = FixedPoint.from_decimal_string(str(p_cul["min_adopter_fraction"]))
    min_adopt_abs = int(p_cul["min_adopter_absolute"])
    min_span = int(p_cul["min_spatial_span_cells"])
    min_speed_ratio = FixedPoint.from_decimal_string(str(p_cul["min_speed_ratio_vs_lineage"]))
    min_fidelity = FixedPoint.from_decimal_string(str(p_cul["min_fidelity_fraction"]))
    min_post_founder = int(p_cul["min_post_founder_adopters"])
    k_null = int(p_null["k_permutations"])
    analysis_seed = int(p_null["default_analysis_seed"])

    # 1. Build parent map (child -> parents) and child map (parent -> children)
    parent_map: Dict[int, List[int]] = {}
    child_map: Dict[int, List[int]] = {}
    for edge in world.relationships.all_edges():
        if edge.rel_type == binding.parent_edge_kind:
            p, c = edge.source_id, edge.target_id
            if c not in parent_map:
                parent_map[c] = []
            parent_map[c].append(p)
            if p not in child_map:
                child_map[p] = []
            child_map[p].append(c)

    # 2. Extract adoption events from journal
    adoption_events: List[Dict[str, Any]] = []
    founder_ids: Set[int] = set()
    founder_cells: Dict[int, Tuple[int, int]] = {}

    for rec in world.event_journal.records:
        if window_start_tick <= rec.tick <= eval_tick:
            if rec.event_type == binding.adoption_event_type:
                payload = rec.payload
                adopter = payload.get("adopter_id") or payload.get("target_id")
                source = payload.get("source_id") or payload.get("mentor_id")
                val_adopt = payload.get("practice_value") or payload.get("value")
                val_source = payload.get("source_value") or payload.get("expected_value") or val_adopt
                cell_x = payload.get("cell_x", 0)
                cell_y = payload.get("cell_y", 0)

                if adopter is not None:
                    event_dict = {
                        "tick": rec.tick,
                        "adopter": int(adopter),
                        "source": int(source) if source is not None else None,
                        "val_adopt": val_adopt,
                        "val_source": val_source,
                        "cell": (int(cell_x), int(cell_y)),
                    }
                    adoption_events.append(event_dict)
                    if not founder_ids:
                        # First recorded adopters are founders
                        if source is not None:
                            founder_ids.add(int(source))
                            founder_cells[int(source)] = (int(cell_x), int(cell_y))
                        else:
                            founder_ids.add(int(adopter))
                            founder_cells[int(adopter)] = (int(cell_x), int(cell_y))

    if not adoption_events:
        return {
            "phenomenon": "cultural_spread",
            "params_version": params.get("version", "v1"),
            "params_sha256": FROZEN_PARAMS_V1_HASH,
            "passed": False,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": window_start_tick,
                "end_tick": eval_tick,
            },
            "sub_criteria": {},
            "failure_reasons": ["No practice adoption events found in journal"],
        }

    sub_criteria: Dict[str, Any] = {}
    failure_reasons: List[str] = []

    # Criterion 3.1: Social Transmission Beyond Extended Kinship (depth <= 4)
    non_kin_trans_count = 0
    valid_trans_events = [e for e in adoption_events if e["source"] is not None]
    total_trans = len(valid_trans_events)

    for e in valid_trans_events:
        a = e["adopter"]
        s = e["source"]
        if not are_extended_kin(parent_map, a, s, max_depth=max_kin_gen):
            non_kin_trans_count += 1

    obs_non_kin_raw = (
        (non_kin_trans_count * 1_000_000) // total_trans
        if total_trans > 0
        else 0
    )
    obs_non_kin = FixedPoint.from_raw(obs_non_kin_raw)
    non_kin_passed = obs_non_kin >= min_non_kin
    sub_criteria["non_kin_transmission"] = {
        "passed": non_kin_passed,
        "observed_fraction": str(obs_non_kin),
        "threshold_fraction": str(min_non_kin),
        "non_kin_events": non_kin_trans_count,
        "total_transmissions": total_trans,
    }
    if not non_kin_passed:
        failure_reasons.append(
            f"Non-kin transmission failed: fraction {obs_non_kin} < {min_non_kin} (lineage-bound practice)"
        )

    # Lineage breadth: distinct roots
    all_adopters = {e["adopter"] for e in adoption_events}
    root_ancestors: Set[int] = set()
    for a in all_adopters:
        # Trace up to roots
        curr_set = {a}
        while curr_set:
            next_set: Set[int] = set()
            for node in curr_set:
                parents = parent_map.get(node, [])
                if not parents:
                    root_ancestors.add(node)
                else:
                    next_set.update(parents)
            curr_set = next_set

    num_roots = len(root_ancestors)
    lineages_passed = num_roots >= min_lineages
    sub_criteria["distinct_lineages"] = {
        "passed": lineages_passed,
        "observed_roots": num_roots,
        "threshold_roots": min_lineages,
    }
    if not lineages_passed:
        failure_reasons.append(
            f"Distinct lineages failed: {num_roots} root ancestors < {min_lineages}"
        )

    # Living agents at eval_tick
    living_agents: List[Dict[str, Any]] = []
    living_adopters: List[Dict[str, Any]] = []
    for eid in sorted(world.entities._entities.keys()):
        ent = world.entities._entities[eid]
        if ent.is_active and ent.entity_type in binding.agent_entity_types:
            alive_val = ent.get_property(binding.alive_prop) if ent.has_property(binding.alive_prop) else 1
            if alive_val == 1:
                cx = int(ent.get_property(binding.pos_x_prop)) if ent.has_property(binding.pos_x_prop) else 0
                cy = int(ent.get_property(binding.pos_y_prop)) if ent.has_property(binding.pos_y_prop) else 0
                living_agents.append({"id": eid, "x": cx, "y": cy, "entity": ent})
                has_practice = ent.has_property(binding.practice_property)
                if has_practice:
                    pval = ent.get_property(binding.practice_property)
                    # If property value indicates holding the practice
                    if pval not in (0, "0", False, None, FixedPoint.from_int(0)):
                        living_adopters.append({"id": eid, "x": cx, "y": cy, "entity": ent})
                elif eid in all_adopters:
                    living_adopters.append({"id": eid, "x": cx, "y": cy, "entity": ent})

    n_living_total = len(living_agents)
    n_living_adopters = len(living_adopters)

    # Criterion 3.2: Demographic and Spatial Reach
    adopt_frac_raw = (
        (n_living_adopters * 1_000_000) // n_living_total
        if n_living_total > 0
        else 0
    )
    obs_adopt_frac = FixedPoint.from_raw(adopt_frac_raw)
    adopt_reach_passed = (
        n_living_adopters >= min_adopt_abs and obs_adopt_frac >= min_adopt_frac
    )
    sub_criteria["demographic_reach"] = {
        "passed": adopt_reach_passed,
        "observed_adopters": n_living_adopters,
        "threshold_absolute": min_adopt_abs,
        "observed_fraction": str(obs_adopt_frac),
        "threshold_fraction": str(min_adopt_frac),
    }
    if not adopt_reach_passed:
        failure_reasons.append(
            f"Demographic reach failed: {n_living_adopters} adopters ({obs_adopt_frac}) < "
            f"required {min_adopt_abs} ({min_adopt_frac})"
        )

    # Spatial span
    origin_cell = next(iter(founder_cells.values())) if founder_cells else (0, 0)
    max_observed_span = 0
    for a in living_adopters:
        d = _chebyshev_distance(origin_cell, (a["x"], a["y"]))
        if d > max_observed_span:
            max_observed_span = d

    span_passed = max_observed_span >= min_span
    sub_criteria["spatial_span"] = {
        "passed": span_passed,
        "observed_span_cells": max_observed_span,
        "threshold_span_cells": min_span,
        "origin_cell": origin_cell,
    }
    if not span_passed:
        failure_reasons.append(
            f"Spatial span failed: observed span {max_observed_span} < {min_span}"
        )

    # Criterion 3.3: Speed Ratio vs. Lineage
    primary_founder = next(iter(founder_ids)) if founder_ids else 0
    # Collect living biological descendants of primary founder
    descendants: Set[int] = set()
    queue = [primary_founder]
    while queue:
        curr = queue.pop(0)
        for child in child_map.get(curr, []):
            if child not in descendants:
                descendants.add(child)
                queue.append(child)

    living_descendant_count = sum(1 for a in living_agents if a["id"] in descendants)
    speed_denom = max(1, living_descendant_count)
    speed_ratio_raw = (n_living_adopters * 1_000_000) // speed_denom
    obs_speed_ratio = FixedPoint.from_raw(speed_ratio_raw)
    speed_passed = obs_speed_ratio >= min_speed_ratio
    sub_criteria["speed_ratio_vs_lineage"] = {
        "passed": speed_passed,
        "observed_ratio": str(obs_speed_ratio),
        "threshold_ratio": str(min_speed_ratio),
        "living_cultural_adopters": n_living_adopters,
        "living_biological_descendants": living_descendant_count,
    }
    if not speed_passed:
        failure_reasons.append(
            f"Speed ratio failed: observed {obs_speed_ratio} < {min_speed_ratio}"
        )

    # Criterion 3.4: Copying Fidelity
    exact_copies = sum(
        1 for e in valid_trans_events if str(e["val_adopt"]) == str(e["val_source"])
    )
    fidelity_raw = (
        (exact_copies * 1_000_000) // total_trans
        if total_trans > 0
        else 1_000_000
    )
    obs_fidelity = FixedPoint.from_raw(fidelity_raw)
    fidelity_passed = obs_fidelity >= min_fidelity
    sub_criteria["copying_fidelity"] = {
        "passed": fidelity_passed,
        "observed_fidelity": str(obs_fidelity),
        "threshold_fidelity": str(min_fidelity),
        "exact_copies": exact_copies,
        "total_transmissions": total_trans,
    }
    if not fidelity_passed:
        failure_reasons.append(
            f"Copying fidelity failed: observed {obs_fidelity} < {min_fidelity}"
        )

    # Criterion 3.5: Post-Founder Generational Persistence
    founders_alive = 0
    living_ids = {a["id"] for a in living_agents}
    for f in founder_ids:
        if f in living_ids:
            founders_alive += 1

    all_founders_dead = founders_alive == 0
    post_founder_passed = all_founders_dead and n_living_adopters >= min_post_founder
    sub_criteria["post_founder_persistence"] = {
        "passed": post_founder_passed,
        "all_founders_dead": all_founders_dead,
        "founders_alive_count": founders_alive,
        "living_adopters": n_living_adopters,
        "threshold_post_founder": min_post_founder,
    }
    if not post_founder_passed:
        failure_reasons.append(
            f"Post-founder persistence failed: {founders_alive} founders still alive or "
            f"{n_living_adopters} adopters < {min_post_founder}"
        )

    # Criterion 3.6: Statistical Significance vs. Random Adoption Null (Spatial Clustering)
    obs_clustered_pairs = 0
    adopter_list = list(living_adopters)
    for i in range(len(adopter_list)):
        for j in range(i + 1, len(adopter_list)):
            if _chebyshev_distance((adopter_list[i]["x"], adopter_list[i]["y"]), (adopter_list[j]["x"], adopter_list[j]["y"])) <= 2:
                obs_clustered_pairs += 1

    null_clusterings: List[int] = []
    for k in range(k_null):
        rng = derive_analysis_stream(analysis_seed, "culture_random_null", k)
        # Sample n_living_adopters at random without replacement from living_agents
        shuffled = rng.deterministic_shuffle(living_agents)[:n_living_adopters]
        sim_clustered = 0
        for i in range(len(shuffled)):
            for j in range(i + 1, len(shuffled)):
                if _chebyshev_distance((shuffled[i]["x"], shuffled[i]["y"]), (shuffled[j]["x"], shuffled[j]["y"])) <= 2:
                    sim_clustered += 1
        null_clusterings.append(sim_clustered)

    null_clusterings.sort()
    p99_idx = (k_null * 99) // 100 - 1
    null_p99 = null_clusterings[p99_idx]
    null_passed = obs_clustered_pairs > null_p99

    sub_criteria["significance_random_null"] = {
        "passed": null_passed,
        "null_model": "random_adoption_spatial_assignment",
        "k_permutations": k_null,
        "observed_statistic": obs_clustered_pairs,
        "null_99th_percentile": null_p99,
    }
    if not null_passed:
        failure_reasons.append(
            f"Random adoption null significance failed: observed spatial clustering {obs_clustered_pairs} <= 99th percentile {null_p99}"
        )

    overall_passed = (
        non_kin_passed
        and lineages_passed
        and adopt_reach_passed
        and span_passed
        and speed_passed
        and fidelity_passed
        and post_founder_passed
        and null_passed
    )

    return {
        "phenomenon": "cultural_spread",
        "params_version": params.get("version", "v1"),
        "params_sha256": FROZEN_PARAMS_V1_HASH,
        "passed": overall_passed,
        "candidate_id": "cultural_practice_eval",
        "evaluated_ticks": {
            "start_tick": window_start_tick,
            "end_tick": eval_tick,
        },
        "sub_criteria": sub_criteria,
        "failure_reasons": failure_reasons,
    }
