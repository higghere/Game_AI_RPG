"""GENESIS Spatial Substrate & Deterministic Spatial Grid Index.

Provides 2D spatial cell partitioning with integer/fixed-point coordinates,
deterministic sorted cell/entity iteration, and canonical serialization.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from genesis.core.arithmetic import FixedPoint, check_int64


class SpatialGridIndex:
    """Deterministic spatial grid index partitioning entities into discrete integer cells (cx, cy)."""

    def __init__(self, cell_size: int = 1) -> None:
        check_int64(cell_size)
        if cell_size <= 0:
            raise ValueError(f"cell_size must be a positive integer, got {cell_size}")
        self.cell_size: int = cell_size
        # Map: entity_id -> (cx, cy)
        self._entity_to_cell: Dict[int, Tuple[int, int]] = {}
        # Map: (cx, cy) -> Set[int] of entity_ids
        self._cell_to_entities: Dict[Tuple[int, int], Set[int]] = {}

    def quantize_coordinate(self, coord: Union[int, FixedPoint]) -> int:
        """Map integer or FixedPoint coordinate to integer grid cell index."""
        if isinstance(coord, FixedPoint):
            # Scale is 1,000,000
            scale = 1_000_000 * self.cell_size
            return check_int64(coord.raw_value // scale)
        elif isinstance(coord, int) and not isinstance(coord, bool):
            check_int64(coord)
            return check_int64(coord // self.cell_size)
        else:
            raise TypeError(f"Coordinate must be int or FixedPoint, got {type(coord).__name__}")

    def place_entity(
        self,
        entity_id: int,
        cx: Union[int, FixedPoint],
        cy: Union[int, FixedPoint],
    ) -> Tuple[int, int]:
        """Place an entity in cell (cx, cy). If already in another cell, moves it."""
        check_int64(entity_id)
        cell_x = self.quantize_coordinate(cx)
        cell_y = self.quantize_coordinate(cy)

        # Remove from previous cell if already placed
        if entity_id in self._entity_to_cell:
            old_cell = self._entity_to_cell[entity_id]
            if old_cell in self._cell_to_entities:
                self._cell_to_entities[old_cell].discard(entity_id)
                if not self._cell_to_entities[old_cell]:
                    del self._cell_to_entities[old_cell]

        cell = (cell_x, cell_y)
        self._entity_to_cell[entity_id] = cell
        self._cell_to_entities.setdefault(cell, set()).add(entity_id)
        return cell

    def remove_entity(self, entity_id: int) -> Optional[Tuple[int, int]]:
        """Remove entity from spatial index. Returns previous cell or None."""
        if entity_id not in self._entity_to_cell:
            return None
        cell = self._entity_to_cell.pop(entity_id)
        if cell in self._cell_to_entities:
            self._cell_to_entities[cell].discard(entity_id)
            if not self._cell_to_entities[cell]:
                del self._cell_to_entities[cell]
        return cell

    def move_entity(
        self,
        entity_id: int,
        new_cx: Union[int, FixedPoint],
        new_cy: Union[int, FixedPoint],
    ) -> Tuple[int, int]:
        """Move entity to new cell."""
        return self.place_entity(entity_id, new_cx, new_cy)

    def get_entity_cell(self, entity_id: int) -> Optional[Tuple[int, int]]:
        """Return the (cx, cy) cell of an entity, or None if not indexed."""
        return self._entity_to_cell.get(entity_id)

    def get_entities_in_cell(self, cx: int, cy: int) -> List[int]:
        """Return all entity IDs in cell (cx, cy), deterministically sorted ascending."""
        cell = (cx, cy)
        entities = self._cell_to_entities.get(cell, set())
        return sorted(entities)

    def get_occupied_cells(self) -> List[Tuple[int, int]]:
        """Return all occupied cells, deterministically sorted by cx ASC, cy ASC."""
        cells = [c for c, ents in self._cell_to_entities.items() if len(ents) > 0]
        return sorted(cells, key=lambda c: (c[0], c[1]))

    def get_entities_in_radius(self, center_x: int, center_y: int, radius: int) -> List[int]:
        """Return entities in Chebyshev neighborhood [center - radius, center + radius].

        Cells are visited in sorted (cx, cy) order; within each cell, entities are sorted.
        Returns a deterministically ordered, deduplicated list of entity IDs.
        """
        check_int64(radius)
        if radius < 0:
            raise ValueError(f"Radius must be non-negative, got {radius}")
        result: List[int] = []
        for cx in range(center_x - radius, center_x + radius + 1):
            for cy in range(center_y - radius, center_y + radius + 1):
                cell = (cx, cy)
                if cell in self._cell_to_entities:
                    result.extend(sorted(self._cell_to_entities[cell]))
        return result

    def rebuild_from_entities(self, entities: Dict[int, Any]) -> None:
        """Deterministically rebuild spatial index from entity properties."""
        self._entity_to_cell.clear()
        self._cell_to_entities.clear()
        for eid in sorted(entities.keys()):
            ent = entities[eid]
            if hasattr(ent, "has_property"):
                if ent.has_property("cell_x") and ent.has_property("cell_y"):
                    cx = ent.get_property("cell_x")
                    cy = ent.get_property("cell_y")
                    self.place_entity(eid, cx, cy)
                elif ent.has_property("pos_x") and ent.has_property("pos_y"):
                    px = ent.get_property("pos_x")
                    py = ent.get_property("pos_y")
                    self.place_entity(eid, px, py)

    def to_dict(self) -> Dict[str, Any]:
        """Produce canonical JSON-compatible serialization of spatial index."""
        sorted_cells = self.get_occupied_cells()
        cells_data = []
        for cell in sorted_cells:
            ents = sorted(self._cell_to_entities[cell])
            cells_data.append({
                "cell": [cell[0], cell[1]],
                "entities": ents,
            })
        return {
            "cell_size": self.cell_size,
            "cells": cells_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SpatialGridIndex:
        """Reconstruct spatial index from serialized dict."""
        cell_size = int(data.get("cell_size", 1))
        idx = cls(cell_size=cell_size)
        for cdata in data.get("cells", []):
            cell = tuple(cdata["cell"])
            cx, cy = int(cell[0]), int(cell[1])
            ents = [int(eid) for eid in cdata.get("entities", [])]
            for eid in sorted(ents):
                idx.place_entity(eid, cx, cy)
        return idx
