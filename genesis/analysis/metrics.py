"""GENESIS Analysis Metrics Dispatcher.

Top-level read-only metrics interface for Settlement, Group, and Cultural Spread.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from genesis.substrate.world_state import WorldState
from genesis.analysis.binding import AnalysisBinding
from genesis.analysis.settlement import evaluate_settlement
from genesis.analysis.group import evaluate_group
from genesis.analysis.culture import evaluate_cultural_spread
from genesis.analysis.params import load_emergence_params


def measure_settlement(
    world: WorldState,
    binding: Optional[AnalysisBinding] = None,
    sample_history: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    """Measure whether the world contains a valid emergent Settlement."""
    if binding is None:
        binding = AnalysisBinding()
    return evaluate_settlement(world, binding, sample_history, params, candidate_index)


def measure_group(
    world: WorldState,
    window_start_tick: int,
    window_end_tick: int,
    binding: Optional[AnalysisBinding] = None,
    sample_history: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    """Measure whether the world contains a valid emergent Group."""
    if binding is None:
        binding = AnalysisBinding()
    return evaluate_group(
        world,
        binding,
        window_start_tick,
        window_end_tick,
        sample_history,
        params,
        candidate_index,
    )


def measure_cultural_spread(
    world: WorldState,
    eval_tick: int,
    window_start_tick: int = 0,
    binding: Optional[AnalysisBinding] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Measure whether the world exhibits valid emergent Cultural Spread."""
    if binding is None:
        binding = AnalysisBinding()
    return evaluate_cultural_spread(
        world, binding, eval_tick, window_start_tick, params
    )
