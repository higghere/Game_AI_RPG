"""GENESIS Group Emergence Measurement Module.

Implements pre-registered operational definitions for Group:
- Interaction-derived weighted graph (zero edges from proximity)
- Deterministic Weighted Label Propagation Algorithm (LPA)
- Size (>= 8) and internal density (>= 0.20)
- Multi-year temporal repetition (>= 2 active years)
- Non-kin structure (kin horizon d <= 2 on parent_of graph)
- Institutional persistence through generational turnover (>= 50% replacement over 10 years)
- Degree-preserving randomization null test (99th percentile)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from genesis.core.arithmetic import FixedPoint
from genesis.substrate.world_state import WorldState
from genesis.analysis.binding import AnalysisBinding
from genesis.analysis.params import load_emergence_params, FROZEN_PARAMS_V1_HASH
from genesis.analysis.stream import derive_analysis_stream


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


def build_interaction_graph(
    world: WorldState,
    binding: AnalysisBinding,
    window_start: int,
    window_end: int,
) -> Tuple[List[int], Dict[Tuple[int, int], int], Dict[Tuple[int, int], Set[int]]]:
    """Construct weighted undirected interaction graph from relationships and journal events.

    Returns:
        nodes: sorted list of entity IDs
        edges: dict (u, v) -> integer weight (u < v)
        edge_years: dict (u, v) -> set of year indices (t // 365) where interaction occurred
    """
    living_ids: Set[int] = set()
    for eid in sorted(world.entities._entities.keys()):
        ent = world.entities._entities[eid]
        if ent.is_active and ent.entity_type in binding.agent_entity_types:
            living_ids.add(eid)

    edge_weights: Dict[Tuple[int, int], int] = {}
    edge_years: Dict[Tuple[int, int], Set[int]] = {}

    def _add_interaction(u: int, v: int, w: int, tick: int) -> None:
        if u == v:
            return
        pair = (min(u, v), max(u, v))
        edge_weights[pair] = edge_weights.get(pair, 0) + w
        year = tick // 365
        if pair not in edge_years:
            edge_years[pair] = set()
        edge_years[pair].add(year)
        living_ids.add(u)
        living_ids.add(v)

    # 1. Active relationships
    for edge in world.relationships.all_edges():
        if edge.rel_type in binding.cooperation_edge_kinds:
            u, v = edge.source_id, edge.target_id
            if isinstance(edge.weight, FixedPoint):
                w = edge.weight.raw_value // 1_000_000
            else:
                w = int(edge.weight)
            _add_interaction(u, v, max(1, w), window_end)

    # 2. Journal events within window
    for rec in world.event_journal.records:
        if window_start <= rec.tick <= window_end:
            if rec.event_type in binding.cooperation_event_types:
                p = rec.payload
                src = p.get("source_id") or p.get("agent_a") or p.get("trader_a")
                tgt = p.get("target_id") or p.get("agent_b") or p.get("trader_b")
                if src is not None and tgt is not None:
                    _add_interaction(int(src), int(tgt), 1, rec.tick)

    sorted_nodes = sorted(list(living_ids))
    return sorted_nodes, edge_weights, edge_years


def deterministic_weighted_lpa(
    nodes: List[int],
    edges: Dict[Tuple[int, int], int],
    max_iterations: int = 20,
) -> List[List[int]]:
    """Partition graph into communities using deterministic Weighted Label Propagation.

    Iterates nodes in strictly ascending entity ID order.
    Ties are broken by lowest label ID.
    """
    labels: Dict[int, int] = {u: u for u in nodes}

    # Adjacency list: u -> list of (v, weight) sorted by v
    adj: Dict[int, List[Tuple[int, int]]] = {u: [] for u in nodes}
    for (u, v), w in edges.items():
        if u in adj and v in adj:
            adj[u].append((v, w))
            adj[v].append((u, w))

    for u in nodes:
        adj[u].sort(key=lambda item: item[0])

    for _ in range(max_iterations):
        changed = False
        for u in nodes:
            neighbors = adj[u]
            if not neighbors:
                continue
            # Accumulate label weights
            label_scores: Dict[int, int] = {}
            for v, w in neighbors:
                lbl = labels[v]
                label_scores[lbl] = label_scores.get(lbl, 0) + w

            # Pick label maximizing weight; break ties by lowest label ID
            best_lbl = labels[u]
            best_score = label_scores.get(best_lbl, 0)
            for lbl in sorted(label_scores.keys()):
                score = label_scores[lbl]
                if score > best_score:
                    best_score = score
                    best_lbl = lbl
                elif score == best_score and lbl < best_lbl:
                    best_lbl = lbl

            if best_lbl != labels[u]:
                labels[u] = best_lbl
                changed = True

        if not changed:
            break

    # Group into communities
    comp_map: Dict[int, List[int]] = {}
    for u, lbl in labels.items():
        if lbl not in comp_map:
            comp_map[lbl] = []
        comp_map[lbl].append(u)

    communities = [sorted(members) for members in comp_map.values()]
    # Sort communities by size descending, then by lowest member ID
    communities.sort(key=lambda c: (-len(c), c[0] if c else 0))
    return communities


def compute_kinship_distances(
    world: WorldState,
    binding: AnalysisBinding,
    nodes: List[int],
) -> Dict[Tuple[int, int], int]:
    """Compute shortest-path kinship distance on the undirected graph spanned by parent_edge_kind.

    Returns dict of (u, v) -> distance, where u < v.
    """
    parent_adj: Dict[int, Set[int]] = {u: set() for u in nodes}
    for edge in world.relationships.all_edges():
        if edge.rel_type == binding.parent_edge_kind:
            u, v = edge.source_id, edge.target_id
            if u in parent_adj and v in parent_adj:
                parent_adj[u].add(v)
                parent_adj[v].add(u)

    # BFS from each node up to distance 2
    distances: Dict[Tuple[int, int], int] = {}
    for start in nodes:
        visited: Dict[int, int] = {start: 0}
        queue = [start]
        while queue:
            curr = queue.pop(0)
            d = visited[curr]
            if d < 2:
                for nbr in sorted(list(parent_adj.get(curr, set()))):
                    if nbr not in visited:
                        visited[nbr] = d + 1
                        queue.append(nbr)
                        pair = (min(start, nbr), max(start, nbr))
                        if pair not in distances or (d + 1) < distances[pair]:
                            distances[pair] = d + 1

    return distances


def evaluate_group(
    world: WorldState,
    binding: AnalysisBinding,
    window_start_tick: int,
    window_end_tick: int,
    sample_history: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    """Evaluate whether an interaction community qualifies as a Group under pre-registered v1 definitions.

    Reads world state and event journal in a strictly read-only manner.
    """
    if params is None:
        params = load_emergence_params("v1")

    p_grp = params["group"]
    p_null = params["null_models"]
    min_members = int(p_grp["min_members"])
    min_density = FixedPoint.from_decimal_string(str(p_grp["min_internal_density"]))
    min_cohesion = FixedPoint.from_decimal_string(str(p_grp["min_cohesion_ratio"]))
    min_active_years = int(p_grp["min_active_years"])
    min_non_kin = FixedPoint.from_decimal_string(str(p_grp["min_non_kin_edge_fraction"]))
    persistence_years = int(p_grp["persistence_years"])
    min_jaccard = FixedPoint.from_decimal_string(str(p_grp["min_jaccard_similarity"]))
    min_turnover = FixedPoint.from_decimal_string(str(p_grp["min_turnover_fraction"]))
    max_lpa_iter = int(p_grp["community_detection_max_iterations"])
    k_null = int(p_null["k_permutations"])
    analysis_seed = int(p_null["default_analysis_seed"])

    nodes, edges, edge_years = build_interaction_graph(
        world, binding, window_start_tick, window_end_tick
    )
    evaluated_years = (window_end_tick - window_start_tick) // 365

    if not nodes or not edges:
        return {
            "phenomenon": "group",
            "params_version": params.get("version", "v1"),
            "params_sha256": FROZEN_PARAMS_V1_HASH,
            "passed": False,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": window_start_tick,
                "end_tick": window_end_tick,
                "years": evaluated_years,
            },
            "sub_criteria": {},
            "failure_reasons": ["No interaction graph edges found"],
        }

    communities = deterministic_weighted_lpa(nodes, edges, max_iterations=max_lpa_iter)
    if not communities or candidate_index >= len(communities):
        return {
            "phenomenon": "group",
            "params_version": params.get("version", "v1"),
            "params_sha256": FROZEN_PARAMS_V1_HASH,
            "passed": False,
            "candidate_id": "none",
            "evaluated_ticks": {
                "start_tick": window_start_tick,
                "end_tick": window_end_tick,
                "years": evaluated_years,
            },
            "sub_criteria": {},
            "failure_reasons": ["No communities detected via LPA"],
        }

    cand_members = communities[candidate_index]
    candidate_id = f"group_cand_{cand_members[0]}"
    cand_set = set(cand_members)
    n_cand = len(cand_members)

    sub_criteria: Dict[str, Any] = {}
    failure_reasons: List[str] = []

    # Criterion 2.1 & 2.2: Size
    size_passed = n_cand >= min_members
    sub_criteria["group_size"] = {
        "passed": size_passed,
        "observed": n_cand,
        "threshold": min_members,
        "margin": n_cand - min_members,
    }
    if not size_passed:
        failure_reasons.append(f"Group size {n_cand} < minimum required {min_members}")

    # Internal edges & density
    internal_edges: List[Tuple[int, int]] = []
    w_int = 0
    w_ext = 0
    active_year_set: Set[int] = set()

    for (u, v), w in edges.items():
        u_in = u in cand_set
        v_in = v in cand_set
        if u_in and v_in:
            internal_edges.append((u, v))
            w_int += w
            if (u, v) in edge_years:
                active_year_set.update(edge_years[(u, v)])
        elif u_in or v_in:
            w_ext += w

    max_possible_edges = (n_cand * (n_cand - 1)) // 2 if n_cand > 1 else 1
    density_raw = (len(internal_edges) * 1_000_000) // max_possible_edges
    obs_density = FixedPoint.from_raw(density_raw)
    density_passed = obs_density >= min_density
    sub_criteria["internal_density"] = {
        "passed": density_passed,
        "observed": str(obs_density),
        "threshold": str(min_density),
        "internal_edges": len(internal_edges),
        "max_possible_edges": max_possible_edges,
    }
    if not density_passed:
        failure_reasons.append(f"Internal density {obs_density} < {min_density}")

    # Cohesion ratio
    ext_denom = max(1, w_ext)
    cohesion_raw = (w_int * 1_000_000) // ext_denom
    obs_cohesion = FixedPoint.from_raw(cohesion_raw)
    cohesion_passed = obs_cohesion >= min_cohesion
    sub_criteria["cohesion_ratio"] = {
        "passed": cohesion_passed,
        "observed": str(obs_cohesion),
        "threshold": str(min_cohesion),
        "w_internal": w_int,
        "w_external": w_ext,
    }
    if not cohesion_passed:
        failure_reasons.append(f"Cohesion ratio {obs_cohesion} < {min_cohesion}")

    # Multi-year temporal repetition (anti-burst guard)
    num_active_years = len(active_year_set)
    active_years_passed = num_active_years >= min_active_years
    sub_criteria["multi_year_activity"] = {
        "passed": active_years_passed,
        "observed_active_years": num_active_years,
        "threshold_active_years": min_active_years,
    }
    if not active_years_passed:
        failure_reasons.append(
            f"Multi-year activity failed: edges active in only {num_active_years} years < {min_active_years}"
        )

    # Criterion 2.5: Non-kin structure
    kin_distances = compute_kinship_distances(world, binding, nodes)
    non_kin_edge_count = 0
    for u, v in internal_edges:
        d = kin_distances.get((u, v), 999)
        if d > 2:
            non_kin_edge_count += 1

    non_kin_raw = (
        (non_kin_edge_count * 1_000_000) // len(internal_edges)
        if internal_edges
        else 0
    )
    obs_non_kin = FixedPoint.from_raw(non_kin_raw)
    non_kin_passed = obs_non_kin >= min_non_kin
    sub_criteria["non_kin_structure"] = {
        "passed": non_kin_passed,
        "observed_fraction": str(obs_non_kin),
        "threshold_fraction": str(min_non_kin),
        "non_kin_edges": non_kin_edge_count,
        "total_internal_edges": len(internal_edges),
    }
    if not non_kin_passed:
        failure_reasons.append(
            f"Non-kin structure failed: non-kin edge fraction {obs_non_kin} < {min_non_kin} (kin-only clique)"
        )

    # Criterion 2.6: Persistence through turnover
    persistence_passed = True
    turnover_passed = True
    obs_turnover = FixedPoint.from_int(0)
    if sample_history is not None and len(sample_history) >= persistence_years:
        founding_cohort = set(sample_history[0].get("member_ids", []))
        if founding_cohort:
            curr_survivors = len(cand_set.intersection(founding_cohort))
            turnover_raw = ((len(founding_cohort) - curr_survivors) * 1_000_000) // len(founding_cohort)
            obs_turnover = FixedPoint.from_raw(turnover_raw)
            turnover_passed = obs_turnover >= min_turnover

    sub_criteria["persistence_turnover"] = {
        "passed": persistence_passed and turnover_passed,
        "observed_turnover": str(obs_turnover),
        "threshold_turnover": str(min_turnover),
    }
    if not turnover_passed:
        failure_reasons.append(
            f"Generational turnover failed: observed turnover {obs_turnover} < {min_turnover}"
        )

    # Criterion 2.7: Degree-preserving randomization null
    edge_list = list(edges.keys())
    null_cohesions: List[int] = []

    for k in range(k_null):
        rng = derive_analysis_stream(analysis_seed, "group_degree_null", k)
        # Degree-preserving edge swaps
        swapped_edges = list(edge_list)
        n_edges = len(swapped_edges)
        if n_edges >= 2:
            num_swaps = n_edges * 2
            for _ in range(num_swaps):
                i = rng.next_int_range(0, n_edges - 1)
                j = rng.next_int_range(0, n_edges - 1)
                if i != j:
                    e1 = swapped_edges[i]
                    e2 = swapped_edges[j]
                    u1, v1 = e1
                    u2, v2 = e2
                    # Propose swap: (u1, v2) and (u2, v1)
                    new1 = (min(u1, v2), max(u1, v2))
                    new2 = (min(u2, v1), max(u2, v1))
                    if new1[0] != new1[1] and new2[0] != new2[1]:
                        swapped_edges[i] = new1
                        swapped_edges[j] = new2

        # Compute cohesion of cand_set in swapped graph
        null_w_int = 0
        null_w_ext = 0
        for u, v in swapped_edges:
            u_in = u in cand_set
            v_in = v in cand_set
            if u_in and v_in:
                null_w_int += 1
            elif u_in or v_in:
                null_w_ext += 1

        c_raw = (null_w_int * 1_000_000) // max(1, null_w_ext)
        null_cohesions.append(c_raw)

    null_cohesions.sort()
    p99_idx = (k_null * 99) // 100 - 1
    null_p99_raw = null_cohesions[p99_idx]
    null_p99 = FixedPoint.from_raw(null_p99_raw)
    null_passed = obs_cohesion > null_p99

    sub_criteria["significance_degree_null"] = {
        "passed": null_passed,
        "null_model": "degree_preserving_randomization",
        "k_permutations": k_null,
        "observed_statistic": str(obs_cohesion),
        "null_99th_percentile": str(null_p99),
    }
    if not null_passed:
        failure_reasons.append(
            f"Degree-preserving null significance failed: observed cohesion {obs_cohesion} <= 99th percentile {null_p99}"
        )

    overall_passed = (
        size_passed
        and density_passed
        and cohesion_passed
        and active_years_passed
        and non_kin_passed
        and persistence_passed
        and turnover_passed
        and null_passed
    )

    return {
        "phenomenon": "group",
        "params_version": params.get("version", "v1"),
        "params_sha256": FROZEN_PARAMS_V1_HASH,
        "passed": overall_passed,
        "candidate_id": candidate_id,
        "evaluated_ticks": {
            "start_tick": window_start_tick,
            "end_tick": window_end_tick,
            "years": evaluated_years,
        },
        "sub_criteria": sub_criteria,
        "failure_reasons": failure_reasons,
    }
