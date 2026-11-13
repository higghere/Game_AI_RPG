"""GENESIS Generic Analysis Binding.

Decouples emergence analysis algorithms from fictional domain ontologies.
Enables generic metrics to inspect entities, properties, relationships,
spatial cells, and journal events without hardcoding any Python entity subclasses.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Tuple

from genesis.core.arithmetic import FixedPoint


@dataclass(frozen=True)
class AnalysisBinding:
    """Ontological mapping connecting generic substrate data to emergence roles."""

    agent_entity_types: Tuple[str, ...] = ("agent",)
    pos_x_prop: str = "cell_x"
    pos_y_prop: str = "cell_y"
    alive_prop: str = "is_alive"
    parent_edge_kind: str = "parent_of"
    cooperation_edge_kinds: Tuple[str, ...] = ("traded_with", "subject_of", "allied_with")
    cooperation_event_types: Tuple[str, ...] = ("trade_executed", "tax_remitted")
    practice_property: str = "farming_technique"
    adoption_event_type: str = "practice_adopted"
    stockpile_resource_property: Optional[str] = None
    resource_landscape_property: Optional[str] = None
    world_extent: Optional[Tuple[int, int, int, int]] = None
    cell_size: Optional[FixedPoint] = None
