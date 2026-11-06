"""GENESIS Deterministic Event Substrate.

Provides phased event queuing, multi-key deterministic event dispatch,
and an append-only cryptographic event hash chain.
"""

from __future__ import annotations
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from genesis.core.arithmetic import FixedPoint, check_int64

# Execution Phases
PHASE_PRE_TICK: int = 0
PHASE_PERCEPTION_EVENTS: int = 1
PHASE_GRL_RULES: int = 2
PHASE_RESOURCE_SETTLEMENT: int = 3
PHASE_POST_TICK: int = 4

GENESIS_BLOCK_HASH: str = hashlib.sha256(b"GENESIS_GENESIS_BLOCK").hexdigest()


class EventRecord:
    """Immutable record of a simulation event."""

    __slots__ = (
        "tick",
        "phase",
        "priority",
        "sequence_id",
        "event_type",
        "payload",
        "prev_hash",
        "record_hash",
    )

    def __init__(
        self,
        tick: int,
        phase: int,
        priority: int,
        sequence_id: int,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        prev_hash: str = "",
        record_hash: str = "",
    ) -> None:
        self.tick = check_int64(tick)
        self.phase = phase
        self.priority = priority
        self.sequence_id = check_int64(sequence_id)
        self.event_type = event_type
        self.payload = payload or {}
        self.prev_hash = prev_hash
        self.record_hash = record_hash

    @property
    def sort_key(self) -> Tuple[int, int, int, int]:
        """Multi-key deterministic ordering: tick ASC, phase ASC, priority DESC, seq ASC."""
        return (self.tick, self.phase, -self.priority, self.sequence_id)

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Serialize event record to canonical dict with decimal string numbers."""
        serialized_payload: Dict[str, Any] = {}
        for k in sorted(self.payload.keys()):
            v = self.payload[k]
            if isinstance(v, FixedPoint):
                serialized_payload[k] = {"__type__": "FIXED_POINT", "val": v.to_raw_string()}
            elif isinstance(v, int) and not isinstance(v, bool):
                serialized_payload[k] = {"__type__": "INT64", "val": str(v)}
            else:
                serialized_payload[k] = v

        return {
            "tick": str(self.tick),
            "phase": self.phase,
            "priority": self.priority,
            "sequence_id": str(self.sequence_id),
            "event_type": self.event_type,
            "payload": serialized_payload,
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self, prev_hash: str) -> str:
        """Compute SHA-256 hash incorporating prior block's hash."""
        self.prev_hash = prev_hash
        cd = self.to_canonical_dict()
        data_bytes = json.dumps(cd, sort_keys=True, separators=(",", ":")).encode("utf-8")
        h = hashlib.sha256()
        h.update(prev_hash.encode("utf-8"))
        h.update(data_bytes)
        self.record_hash = h.hexdigest()
        return self.record_hash

    def to_dict(self) -> Dict[str, Any]:
        d = self.to_canonical_dict()
        d["record_hash"] = self.record_hash
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventRecord:
        raw_payload = data.get("payload", {})
        payload: Dict[str, Any] = {}
        for k, v in raw_payload.items():
            if isinstance(v, dict) and "__type__" in v:
                if v["__type__"] == "FIXED_POINT":
                    payload[k] = FixedPoint.from_raw(int(v["val"]))
                elif v["__type__"] == "INT64":
                    payload[k] = int(v["val"])
                else:
                    payload[k] = v
            else:
                payload[k] = v

        rec = cls(
            tick=int(data["tick"]),
            phase=int(data["phase"]),
            priority=int(data["priority"]),
            sequence_id=int(data["sequence_id"]),
            event_type=data["event_type"],
            payload=payload,
            prev_hash=data.get("prev_hash", ""),
            record_hash=data.get("record_hash", ""),
        )
        return rec


class EventQueue:
    """Priority queue of scheduled simulation events sorted deterministically."""

    def __init__(self) -> None:
        self._events: List[EventRecord] = []
        self._next_sequence_id: int = 1

    def schedule(
        self,
        tick: int,
        phase: int,
        priority: int,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        sequence_id: Optional[int] = None,
    ) -> EventRecord:
        if sequence_id is not None:
            seq_id = check_int64(sequence_id)
        else:
            seq_id = self._next_sequence_id
            self._next_sequence_id = check_int64(self._next_sequence_id + 1)
        event = EventRecord(
            tick=tick,
            phase=phase,
            priority=priority,
            sequence_id=seq_id,
            event_type=event_type,
            payload=payload,
        )
        self._events.append(event)
        self._events.sort(key=lambda e: e.sort_key)
        return event

    def drain_for_tick_phase(self, tick: int, phase: int) -> List[EventRecord]:
        """Drain and return events matching tick and phase in exact deterministic order."""
        matching: List[EventRecord] = []
        remaining: List[EventRecord] = []
        for e in self._events:
            if e.tick == tick and e.phase == phase:
                matching.append(e)
            else:
                remaining.append(e)
        self._events = remaining
        matching.sort(key=lambda e: e.sort_key)
        return matching

    def is_empty(self) -> bool:
        return len(self._events) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "next_sequence_id": str(self._next_sequence_id),
            "events": [e.to_dict() for e in self._events],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventQueue:
        q = cls()
        q._next_sequence_id = int(data.get("next_sequence_id", "1"))
        for edata in data.get("events", []):
            q._events.append(EventRecord.from_dict(edata))
        q._events.sort(key=lambda e: e.sort_key)
        return q


class EventJournal:
    """Append-only cryptographic hash-chained event journal."""

    def __init__(self) -> None:
        self._records: List[EventRecord] = []
        self._last_hash: str = GENESIS_BLOCK_HASH

    @property
    def last_hash(self) -> str:
        return self._last_hash

    @property
    def records(self) -> List[EventRecord]:
        return list(self._records)

    def append(self, event: EventRecord) -> str:
        """Append event to journal and compute hash chained to prior record."""
        rec_hash = event.compute_hash(self._last_hash)
        self._records.append(event)
        self._last_hash = rec_hash
        return rec_hash

    def records_through_tick(self, tick: int) -> List[EventRecord]:
        """Return all committed records up to and including the specified tick."""
        return [r for r in self._records if r.tick <= tick]

    def hash_through_tick(self, tick: int) -> str:
        """Compute the cumulative hash of all records up to and including tick."""
        records = self.records_through_tick(tick)
        if not records:
            return GENESIS_BLOCK_HASH
        return records[-1].record_hash

    def verify_integrity(self) -> bool:
        """Verify the complete hash chain from the genesis block."""
        current_hash = GENESIS_BLOCK_HASH
        for rec in self._records:
            if rec.prev_hash != current_hash:
                return False
            expected_hash = rec.compute_hash(current_hash)
            if rec.record_hash != expected_hash:
                return False
            current_hash = expected_hash
        return current_hash == self._last_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_hash": self._last_hash,
            "records": [r.to_dict() for r in self._records],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventJournal:
        journal = cls()
        journal._last_hash = data.get("last_hash", GENESIS_BLOCK_HASH)
        for rdata in data.get("records", []):
            journal._records.append(EventRecord.from_dict(rdata))
        return journal
