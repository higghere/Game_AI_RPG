"""GENESIS Entity Storage Substrate.

Provides generic domain-agnostic entity storage, monotonic 64-bit ID assignment,
and deterministic entity traversal.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from genesis.core.arithmetic import FixedPoint, check_int64
from genesis.substrate.properties import PropertyType, SchemaRegistry


class Entity:
    """Generic simulation entity carrying dynamic properties."""

    __slots__ = ("id", "entity_type", "created_tick", "properties", "is_active")

    def __init__(
        self,
        entity_id: int,
        entity_type: str,
        created_tick: int,
        properties: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
    ) -> None:
        self.id: int = check_int64(entity_id)
        self.entity_type: str = entity_type
        self.created_tick: int = check_int64(created_tick)
        self.properties: Dict[str, Any] = properties or {}
        self.is_active: bool = is_active

    def get_property(self, name: str) -> Any:
        if name == "id":
            return self.id
        return self.properties.get(name)

    def has_property(self, name: str) -> bool:
        if name == "id":
            return True
        return name in self.properties

    def set_property(self, name: str, value: Any) -> None:
        self.properties[name] = value

    def to_dict(self) -> Dict[str, Any]:
        """Serialize entity with int64 and fixed-point quantities as decimal strings."""
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
            "id": str(self.id),
            "entity_type": self.entity_type,
            "created_tick": str(self.created_tick),
            "is_active": self.is_active,
            "properties": serialized_props,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Entity:
        entity_id = int(data["id"])
        created_tick = int(data["created_tick"])
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

        return cls(
            entity_id=entity_id,
            entity_type=data["entity_type"],
            created_tick=created_tick,
            properties=props,
            is_active=data.get("is_active", True),
        )


class EntityStorage:
    """Deterministic repository for generic simulation entities."""

    def __init__(self) -> None:
        self._entities: Dict[int, Entity] = {}
        self._by_type: Dict[str, List[int]] = {}
        self._next_id: int = 1

    def create_entity(
        self,
        entity_type: str,
        created_tick: int,
        initial_properties: Optional[Dict[str, Any]] = None,
        schema_registry: Optional[SchemaRegistry] = None,
    ) -> Entity:
        """Create and register a new entity with a monotonic 64-bit ID."""
        entity_id = self._next_id
        self._next_id = check_int64(self._next_id + 1)

        validated_props: Dict[str, Any] = {}
        schema = schema_registry.get_schema(entity_type) if schema_registry else None

        if schema:
            # Populate defaults
            for p_name, p_def in schema.properties.items():
                if p_def.default_value is not None:
                    validated_props[p_name] = p_def.default_value
            # Validate input properties
            if initial_properties:
                for p_name, p_val in initial_properties.items():
                    validated_props[p_name] = schema.validate_property(p_name, p_val)
        elif initial_properties:
            validated_props = dict(initial_properties)

        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            created_tick=created_tick,
            properties=validated_props,
        )

        self._entities[entity_id] = entity
        self._by_type.setdefault(entity_type, []).append(entity_id)
        return entity

    def get_entity(self, entity_id: int) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def destroy_entity(self, entity_id: int) -> Optional[Entity]:
        """Permanently remove an entity from storage."""
        ent = self._entities.pop(entity_id, None)
        if ent:
            type_list = self._by_type.get(ent.entity_type)
            if type_list and entity_id in type_list:
                type_list.remove(entity_id)
        return ent

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """Return active entities of the given type, deterministically sorted by ID."""
        ids = self._by_type.get(entity_type, [])
        active_entities = [self._entities[eid] for eid in sorted(ids) if self._entities[eid].is_active]
        return active_entities

    def all_entities(self) -> List[Entity]:
        """Return all entities deterministically sorted by EntityID ascending."""
        return [self._entities[eid] for eid in sorted(self._entities.keys())]

    def count(self) -> int:
        return len(self._entities)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize storage with entities sorted by ID."""
        sorted_entities = [self._entities[eid].to_dict() for eid in sorted(self._entities.keys())]
        return {
            "next_id": str(self._next_id),
            "entities": sorted_entities,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EntityStorage:
        storage = cls()
        storage._next_id = int(data.get("next_id", "1"))
        for edata in data.get("entities", []):
            entity = Entity.from_dict(edata)
            storage._entities[entity.id] = entity
            storage._by_type.setdefault(entity.entity_type, []).append(entity.id)
        return storage
