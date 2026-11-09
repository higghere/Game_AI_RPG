"""GENESIS Agent Emergence Analysis Binding.

Binds the Phase 3 individual agent schema, parent relationships, and spatial
properties to the pre-registered emergence measurement suite (genesis/analysis/).
"""

from __future__ import annotations
from typing import Dict

from genesis.analysis.binding import AnalysisBinding


def get_agent_analysis_binding() -> AnalysisBinding:
    """Return the pre-registered AnalysisBinding for Phase 3 agents."""
    return AnalysisBinding(
        agent_entity_types=("agent",),
        pos_x_prop="cell_x",
        pos_y_prop="cell_y",
        alive_prop="is_alive",
        parent_edge_kind="parent_of",
        cooperation_edge_kinds=(),
        cooperation_event_types=(),
        practice_property="farming_technique",
        adoption_event_type="practice_adopted",
        stockpile_resource_property=None,
        resource_landscape_property="soil_water",
    )


AGENT_NOT_APPLICABLE_EMERGENCE_MEASURES: Dict[str, str] = {
    "group_emergence": (
        "Phase 3 agents have no trade, tribute, or political cooperation edges/events. "
        "The interaction graph has zero edges; analysis cleanly returns early-exit negative verdict."
    ),
    "cultural_spread": (
        "Phase 3 agents have no memes, practices, or adoption events. "
        "Adoption event count is zero; analysis cleanly returns early-exit negative verdict."
    ),
}
