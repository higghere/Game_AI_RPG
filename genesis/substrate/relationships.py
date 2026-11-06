"""GENESIS Relationship Graph Substrate.

Provides dynamic, typed, weighted directed edges between entities with
deterministic traversal ordering.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from genesis.core.arithmetic import FixedPoint, check_int64


class RelationshipEdge:
    """Directed edge representing a relationship between two entities."""

    __slots__ = ("source_id", "target_id", "rel_type", "weight", "properties")

    def __init__(
        self,
        source_id: int,
        target_id: int,
        rel_type: str,
        weight: Optional[FixedPoint] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.source_id = check_int64(source_id)
        self.target_id = check_int64(target_id)
        self.rel_type = rel_type
        self.weight = weight if weight is not None else FixedPoint.from_int(1)
        self.properties = properties or {}

    def to_dict(self) -> Dict[str, Any]:
        serialized_props: Dict[str, Any] = {}
        for k in sorted(self.properties.keys()):
            v = self.properties[k]
            if isinstance(v, FixedPoint):
                serialized_props[k] = {"__type__": "FIXED_POINT", "val": v.to_raw_string()}
            elif isinstance(v, int) and not isinstance(v, bool):
                serialized_props[k] = {"__type__": "INT64", "val": str(v)}
            else:
                serialized_props[k] = v

        return {
            "source_id": str(self.source_id),
            "target_id": str(self.target_id),
            "rel_type": self.rel_type,
            "weight": self.weight.to_raw_string(),
            "properties": serialized_props,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RelationshipEdge:
        source_id = int(data["source_id"])
        target_id = int(data["target_id"])
        rel_type = data["rel_type"]
        weight = FixedPoint.from_raw(int(data["weight"]))
        raw_props = data.get("properties", {})
        props: Dict[str, Any] = {}
        for k, v in raw_props.items():
            if isinstance(v, dict) and "__type__" in v:
                if v["__type__"] == "FIXED_POINT":
                    props[k] = FixedPoint.from_raw(int(v["val"]))
                elif v["__type__"] == "INT64":
                    props[k] = int(v["val"])
                else:
                    props[k] = v
            else:
                props[k] = v
        return cls(source_id, target_id, rel_type, weight, props)


class RelationshipGraph:
    """Graph structure managing entity relationships with deterministic querying."""

    def __init__(self) -> None:
        # Key: (source_id, target_id, rel_type) -> RelationshipEdge
        self._edges: Dict[Tuple[int, int, str], RelationshipEdge] = {}
        # Outgoing index: source_id -> dict of (target_id, rel_type) -> edge
        self._out_index: Dict[int, Dict[Tuple[int, str], RelationshipEdge]] = {}
        # Incoming index: target_id -> dict of (source_id, rel_type) -> edge
        self._in_index: Dict[int, Dict[Tuple[int, str], RelationshipEdge]] = {}

    def add_edge(
        self,
        source_id: int,
        target_id: int,
        rel_type: str,
        weight: Optional[FixedPoint] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> RelationshipEdge:
        """Add or update a directed relationship edge."""
        edge = RelationshipEdge(source_id, target_id, rel_type, weight, properties)
        key = (edge.source_id, edge.target_id, edge.rel_type)
        self._edges[key] = edge

        self._out_index.setdefault(edge.source_id, {})[(edge.target_id, edge.rel_type)] = edge
        self._in_index.setdefault(edge.target_id, {})[(edge.source_id, edge.rel_type)] = edge
        return edge

    def remove_edge(self, source_id: int, target_id: int, rel_type: str) -> bool:
        """Remove a directed edge."""
        key = (source_id, target_id, rel_type)
        if key in self._edges:
            del self._edges[key]
            if source_id in self._out_index and (target_id, rel_type) in self._out_index[source_id]:
                del self._out_index[source_id][(target_id, rel_type)]
                if not self._out_index[source_id]:
                    del self._out_index[source_id]
            if target_id in self._in_index and (source_id, rel_type) in self._in_index[target_id]:
                del self._in_index[target_id][(source_id, rel_type)]
                if not self._in_index[target_id]:
                    del self._in_index[target_id]
            return True
        return False

    def remove_all_edges_for(self, entity_id: int) -> int:
        """Remove all incoming and outgoing edges for an entity. Returns count of removed edges."""
        edges_to_remove = []
        if entity_id in self._out_index:
            for (target_id, rel_type) in list(self._out_index[entity_id].keys()):
                edges_to_remove.append((entity_id, target_id, rel_type))
        if entity_id in self._in_index:
            for (source_id, rel_type) in list(self._in_index[entity_id].keys()):
                edges_to_remove.append((source_id, entity_id, rel_type))
        count = 0
        for s_id, t_id, r_type in set(edges_to_remove):
            if self.remove_edge(s_id, t_id, r_type):
                count += 1
        return count

    def has_edge(self, source_id: int, target_id: int, rel_type: str) -> bool:
        return (source_id, target_id, rel_type) in self._edges

    def get_edge(self, source_id: int, target_id: int, rel_type: str) -> Optional[RelationshipEdge]:
        return self._edges.get((source_id, target_id, rel_type))

    def get_outgoing(self, source_id: int, rel_type: Optional[str] = None) -> List[RelationshipEdge]:
        """Return outgoing edges deterministically sorted by target_id ASC, then rel_type ASC."""
        if source_id not in self._out_index:
            return []
        edges: List[RelationshipEdge] = []
        for (tgt_id, rtype), edge in self._out_index[source_id].items():
            if rel_type is None or rtype == rel_type:
                edges.append(edge)
        return sorted(edges, key=lambda e: (e.target_id, e.rel_type))

    def get_incoming(self, target_id: int, rel_type: Optional[str] = None) -> List[RelationshipEdge]:
        """Return incoming edges deterministically sorted by source_id ASC, then rel_type ASC."""
        if target_id not in self._in_index:
            return []
        edges: List[RelationshipEdge] = []
        for (src_id, rtype), edge in self._in_index[target_id].items():
            if rel_type is None or rtype == rel_type:
                edges.append(edge)
        return sorted(edges, key=lambda e: (e.source_id, e.rel_type))

    def all_edges(self) -> List[RelationshipEdge]:
        """Return all edges deterministically sorted by (source_id, target_id, rel_type)."""
        sorted_keys = sorted(self._edges.keys())
        return [self._edges[k] for k in sorted_keys]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edges": [e.to_dict() for e in self.all_edges()]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RelationshipGraph:
        graph = cls()
        for edata in data.get("edges", []):
            edge = RelationshipEdge.from_dict(edata)
            graph.add_edge(edge.source_id, edge.target_id, edge.rel_type, edge.weight, edge.properties)
        return graph


class RelationshipKindDefinition:
    """Schema definition for a relationship kind loaded from data declarations."""

    def __init__(
        self,
        rel_type: str,
        directed: bool = True,
        description: str = "",
        symmetric: bool = False,
    ) -> None:
        self.rel_type = rel_type
        self.directed = directed
        self.description = description
        self.symmetric = symmetric

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rel_type": self.rel_type,
            "directed": self.directed,
            "description": self.description,
            "symmetric": self.symmetric,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RelationshipKindDefinition:
        return cls(
            rel_type=data["rel_type"],
            directed=bool(data.get("directed", True)),
            description=data.get("description", ""),
            symmetric=bool(data.get("symmetric", False)),
        )


class RelationshipKindRegistry:
    """Registry of relationship kinds loaded from data definitions."""

    def __init__(self) -> None:
        self._kinds: Dict[str, RelationshipKindDefinition] = {}

    def register_kind(self, kind: RelationshipKindDefinition) -> None:
        self._kinds[kind.rel_type] = kind

    def get_kind(self, rel_type: str) -> Optional[RelationshipKindDefinition]:
        return self._kinds.get(rel_type)

    def has_kind(self, rel_type: str) -> bool:
        return rel_type in self._kinds

    def all_kinds(self) -> List[RelationshipKindDefinition]:
        return [self._kinds[k] for k in sorted(self._kinds.keys())]

    def to_dict(self) -> Dict[str, Any]:
        return {k: self._kinds[k].to_dict() for k in sorted(self._kinds.keys())}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RelationshipKindRegistry:
        reg = cls()
        for k, v in data.items():
            reg.register_kind(RelationshipKindDefinition.from_dict(v))
        return reg
