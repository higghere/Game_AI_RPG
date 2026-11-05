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
        self.schema_registry: SchemaRegistry = SchemaRegistry()
        self.entities: EntityStorage = EntityStorage()
        self.relationships: RelationshipGraph = RelationshipGraph()
        self.resources: ResourceRegistry = ResourceRegistry()
        self.event_queue: EventQueue = EventQueue()
        self.event_journal: EventJournal = EventJournal()
        self.rule_engine_callback: Optional[Callable[[WorldState], None]] = None

    def advance_tick(self) -> int:
        """Execute one complete discrete simulation tick through all 5 phases."""
        current_tick = self.clock.advance_tick()

        # Phase 0: PRE_TICK
        pre_tick_event = EventRecord(
            tick=current_tick,
            phase=PHASE_PRE_TICK,
            priority=100,
            sequence_id=self.event_queue._next_sequence_id,
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

        # Phase 3: RESOURCE_SETTLEMENT
        self.resources.audit_invariants()
        settlement_event = EventRecord(
            tick=current_tick,
            phase=PHASE_RESOURCE_SETTLEMENT,
            priority=0,
            sequence_id=self.event_queue._next_sequence_id,
            event_type="resource_settlement_audited",
            payload={"tick": str(current_tick)},
        )
        self.event_journal.append(settlement_event)

        # Phase 4: POST_TICK
        post_tick_event = EventRecord(
            tick=current_tick,
            phase=PHASE_POST_TICK,
            priority=-100,
            sequence_id=self.event_queue._next_sequence_id,
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
            "clock": self.clock.to_dict(),
            "rng": self.rng.get_state(),
            "schemas": self.schema_registry.to_dict(),
            "entities": self.entities.to_dict(),
            "relationships": self.relationships.to_dict(),
            "resources": self.resources.to_dict(),
            "event_queue": self.event_queue.to_dict(),
            "event_journal": self.event_journal.to_dict(),
        }

    @classmethod
    def from_canonical_dict(cls, data: Dict[str, Any], config: Optional[RuntimeConfig] = None) -> WorldState:
        """Reconstruct full world state from canonical dictionary."""
        ws = cls(seed=0, config=config)
        ws.clock = SimulationClock.from_dict(data["clock"])
        ws.rng.set_state(data["rng"])
        ws.schema_registry = SchemaRegistry.from_dict(data.get("schemas", {}))
        ws.entities = EntityStorage.from_dict(data["entities"])
        ws.relationships = RelationshipGraph.from_dict(data["relationships"])
        ws.resources = ResourceRegistry.from_dict(data["resources"])
        ws.event_queue = EventQueue.from_dict(data["event_queue"])
        if "event_journal" in data:
            ws.event_journal = EventJournal.from_dict(data["event_journal"])
        return ws
