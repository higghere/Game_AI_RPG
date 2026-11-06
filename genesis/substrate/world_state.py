"""GENESIS World State Substrate.

Central deterministic simulation state combining clock, PRNG, schemas,
entities, relationships, resources, and event ledger.
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional

from genesis.core.clock import SimulationClock
from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.core.rng import GenesisRNG
from genesis.substrate.entities import EntityStorage
from genesis.substrate.events import (
    EventJournal,
    EventQueue,
    EventRecord,
    PHASE_GRL_RULES,
    PHASE_PERCEPTION_EVENTS,
    PHASE_POST_TICK,
    PHASE_PRE_TICK,
    PHASE_RESOURCE_SETTLEMENT,
)
from genesis.substrate.properties import SchemaRegistry
from genesis.substrate.relationships import RelationshipGraph
from genesis.substrate.resources import ResourceRegistry
from genesis.substrate.spatial import SpatialGridIndex


class WorldState:
    """The complete, self-contained world state of a simulation run."""

    def __init__(
        self,
        seed: int = 42,
        config: Optional[RuntimeConfig] = None,
    ) -> None:
        self.config: RuntimeConfig = config or DEFAULT_CONFIG
        self.clock: SimulationClock = SimulationClock(0)
        self.rng: GenesisRNG = GenesisRNG(seed)
        self._next_sequence_id: int = 1
        self.schema_registry: SchemaRegistry = SchemaRegistry()
        self.entities: EntityStorage = EntityStorage()
        self.relationships: RelationshipGraph = RelationshipGraph()
        self.resources: ResourceRegistry = ResourceRegistry()
        self.spatial_index: SpatialGridIndex = SpatialGridIndex()
        self._pending_spatial_entities: Set[int] = set()
        self.event_queue: EventQueue = EventQueue()
        self.event_journal: EventJournal = EventJournal()
        self.entities_touched_this_tick: Set[int] = set()
        self.rule_registry: Optional[Any] = None
        self.rule_engine_callback: Optional[Callable[[WorldState], None]] = None

    def register_rule(self, rule: Any) -> str:
        """Register a rule prospectively, hashing full canonical body and writing rule_installed event."""
        if self.rule_registry is None:
            from genesis.grl.registry import RuleRegistry
            self.rule_registry = RuleRegistry(self.config)
        return self.rule_registry.register_rule(rule, self)

    def next_sequence_id(self) -> int:
        """Return next strictly monotonic sequence ID for events."""
        from genesis.core.arithmetic import check_int64
        seq = self._next_sequence_id
        self._next_sequence_id = check_int64(self._next_sequence_id + 1)
        return seq

    def get_entities_in_cell(self, cx: int, cy: int) -> List[int]:
        """Return all entity IDs in spatial cell (cx, cy) sorted ascending."""
        return self.spatial_index.get_entities_in_cell(cx, cy)

    def place_entity_in_cell(
        self,
        entity_id: int,
        cx: Any,
        cy: Any,
    ) -> Tuple[int, int]:
        """Place an entity in a spatial cell (cx, cy)."""
        return self.spatial_index.place_entity(entity_id, cx, cy)

    def move_entity_cell(
        self,
        entity_id: int,
        new_cx: Any,
        new_cy: Any,
    ) -> Tuple[int, int]:
        """Move entity to new spatial cell."""
        return self.spatial_index.move_entity(entity_id, new_cx, new_cy)

    def get_occupied_cells(self) -> List[Tuple[int, int]]:
        """Return all occupied spatial cells sorted ascending by (cx, cy)."""
        return self.spatial_index.get_occupied_cells()

    def rebuild_spatial_index(self) -> None:
        """Deterministically rebuild spatial index from entity properties."""
        self.spatial_index.rebuild_from_entities(self.entities._entities)

    def sync_entity_spatial(self, entity_id: int) -> None:
        """Sync an entity's cell position in the spatial index from its properties."""
        ent = self.entities.get_entity(entity_id)
        if ent:
            if ent.has_property("cell_x") and ent.has_property("cell_y"):
                self.spatial_index.place_entity(ent.id, ent.get_property("cell_x"), ent.get_property("cell_y"))
            elif ent.has_property("pos_x") and ent.has_property("pos_y"):
                self.spatial_index.place_entity(ent.id, ent.get_property("pos_x"), ent.get_property("pos_y"))

    def defer_spatial_sync(self, entity_id: int) -> None:
        """Stage an entity ID for deferred spatial index synchronization at the end of a rule pass."""
        self._pending_spatial_entities.add(entity_id)

    def commit_pending_spatial_moves(self) -> None:
        """Commit all pending spatial moves in deterministic entity_id order for simultaneous movement."""
        for eid in sorted(self._pending_spatial_entities):
            self.sync_entity_spatial(eid)
        self._pending_spatial_entities.clear()

    def advance_tick(self) -> int:
        """Execute one complete discrete simulation tick through all 5 phases."""
        current_tick = self.clock.advance_tick()
        self.entities_touched_this_tick.clear()

        # Phase 0: PRE_TICK
        pre_tick_event = EventRecord(
            tick=current_tick,
            phase=PHASE_PRE_TICK,
            priority=100,
            sequence_id=self.next_sequence_id(),
            event_type="tick_started",
            payload={"tick": str(current_tick)},
        )
        self.event_journal.append(pre_tick_event)

        # Phase 1: PERCEPTION_EVENTS
        events = self.event_queue.drain_for_tick_phase(current_tick, PHASE_PERCEPTION_EVENTS)
        for ev in events:
            # Commit event to journal
            self.event_journal.append(ev)

        # Phase 2: GRL_RULES
        if self.rule_engine_callback:
            self.rule_engine_callback(self)
        elif self.rule_registry:
            self.rule_registry.execute_active_rules(self)

        # Phase 3: RESOURCE_SETTLEMENT
        self.resources.audit_invariants()
        settlement_event = EventRecord(
            tick=current_tick,
            phase=PHASE_RESOURCE_SETTLEMENT,
            priority=0,
            sequence_id=self.next_sequence_id(),
            event_type="resource_settlement_audited",
            payload={"tick": str(current_tick)},
        )
        self.event_journal.append(settlement_event)

        # Phase 4: POST_TICK
        post_tick_event = EventRecord(
            tick=current_tick,
            phase=PHASE_POST_TICK,
            priority=-100,
            sequence_id=self.next_sequence_id(),
            event_type="tick_completed",
            payload={"tick": str(current_tick)},
        )
        self.event_journal.append(post_tick_event)

        return current_tick

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Produce canonical serialized representation of full simulation state."""
        return {
            "schema_version": self.config.schema_version,
            "runtime_version": self.config.runtime_version,
            "next_sequence_id": str(self._next_sequence_id),
            "clock": self.clock.to_dict(),
            "rng": self.rng.get_state(),
            "schemas": self.schema_registry.to_dict(),
            "entities": self.entities.to_dict(),
            "relationships": self.relationships.to_dict(),
            "resources": self.resources.to_dict(),
            "spatial_index": self.spatial_index.to_dict(),
            "event_queue": self.event_queue.to_dict(),
            "event_journal": self.event_journal.to_dict(),
            "rules": self.rule_registry.to_canonical_dict() if self.rule_registry else {},
        }

    @classmethod
    def from_canonical_dict(cls, data: Dict[str, Any], config: Optional[RuntimeConfig] = None) -> WorldState:
        """Reconstruct full world state from canonical dictionary."""
        ws = cls(seed=0, config=config)
        ws._next_sequence_id = int(data.get("next_sequence_id", "1"))
        ws.clock = SimulationClock.from_dict(data["clock"])
        ws.rng.set_state(data["rng"])
        ws.schema_registry = SchemaRegistry.from_dict(data.get("schemas", {}))
        ws.entities = EntityStorage.from_dict(data["entities"])
        ws.relationships = RelationshipGraph.from_dict(data["relationships"])
        ws.resources = ResourceRegistry.from_dict(data["resources"])
        if "spatial_index" in data:
            ws.spatial_index = SpatialGridIndex.from_dict(data["spatial_index"])
        ws.event_queue = EventQueue.from_dict(data["event_queue"])
        if "event_journal" in data:
            ws.event_journal = EventJournal.from_dict(data["event_journal"])
        if "rules" in data and data["rules"]:
            from genesis.grl.registry import RuleRegistry
            ws.rule_registry = RuleRegistry.from_canonical_dict(data["rules"], config=config)
        return ws
