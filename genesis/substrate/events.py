"""GENESIS Deterministic Event Substrate.

Provides phased event queuing, multi-key deterministic event dispatch,
and an append-only cryptographic event hash chain.
"""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from genesis.core.arithmetic import FixedPoint, check_int64
from genesis.core.errors import JournalTamperError

# Execution Phases
PHASE_PRE_TICK: int = 0
PHASE_PERCEPTION_EVENTS: int = 1
PHASE_GRL_RULES: int = 2
PHASE_RESOURCE_SETTLEMENT: int = 3
PHASE_POST_TICK: int = 4

# Audit Levels
AUDIT_LEVEL_MINIMAL: str = "MINIMAL"
AUDIT_LEVEL_SUMMARY: str = "SUMMARY"
AUDIT_LEVEL_TRACE: str = "TRACE"
VALID_AUDIT_LEVELS: set = {"MINIMAL", "SUMMARY", "TRACE"}

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


@dataclass
class JournalSegmentMeta:
    """Metadata describing a finalized 365-tick epoch journal segment file."""
    epoch: int
    filename: str
    filepath: str
    start_tick: int
    end_tick: int
    start_sequence_id: int
    end_sequence_id: int
    start_prev_hash: str
    terminal_hash: str
    record_count: int
    file_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch": self.epoch,
            "filename": self.filename,
            "filepath": self.filepath,
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "start_sequence_id": str(self.start_sequence_id),
            "end_sequence_id": str(self.end_sequence_id),
            "start_prev_hash": self.start_prev_hash,
            "terminal_hash": self.terminal_hash,
            "record_count": self.record_count,
            "file_sha256": self.file_sha256,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JournalSegmentMeta:
        return cls(
            epoch=int(data["epoch"]),
            filename=data["filename"],
            filepath=data["filepath"],
            start_tick=int(data["start_tick"]),
            end_tick=int(data["end_tick"]),
            start_sequence_id=int(data["start_sequence_id"]),
            end_sequence_id=int(data["end_sequence_id"]),
            start_prev_hash=data["start_prev_hash"],
            terminal_hash=data["terminal_hash"],
            record_count=int(data["record_count"]),
            file_sha256=data["file_sha256"],
        )


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
    """Append-only cryptographic hash-chained event journal with epoch segmentation."""

    def __init__(self, journal_dir: Optional[str] = None, epoch_size: int = 365) -> None:
        self.journal_dir: Path = Path(journal_dir or "data/journal")
        self.epoch_size: int = epoch_size
        self._records: List[EventRecord] = []
        self._committed_segments: List[JournalSegmentMeta] = []
        self._last_hash: str = GENESIS_BLOCK_HASH
        self._latest_segment_hash: str = ""
        self._latest_segment_file_hash: str = ""

    @property
    def last_hash(self) -> str:
        return self._last_hash

    @property
    def latest_segment_hash(self) -> str:
        return self._latest_segment_hash

    @property
    def latest_segment_file_hash(self) -> str:
        return self._latest_segment_file_hash

    @property
    def committed_segments(self) -> List[JournalSegmentMeta]:
        return list(self._committed_segments)

    @property
    def active_records(self) -> List[EventRecord]:
        return list(self._records)

    @property
    def records(self) -> List[EventRecord]:
        """Return all records across all committed segments and the active in-memory buffer."""
        all_recs: List[EventRecord] = []
        for seg in self._committed_segments:
            all_recs.extend(self.read_segment_records(seg))
        all_recs.extend(self._records)
        return all_recs

    def append(self, event: EventRecord) -> str:
        """Append event to journal and compute hash chained to prior record."""
        rec_hash = event.compute_hash(self._last_hash)
        self._records.append(event)
        self._last_hash = rec_hash
        return rec_hash

    def commit_epoch_segment(self, epoch_num: int) -> Optional[JournalSegmentMeta]:
        """Finalize and commit records up to epoch_num * epoch_size to an append-only segment file.

        The segment is written atomically using uncompressed canonical JSON lines.
        Returns the committed segment metadata.
        """
        max_tick = epoch_num * self.epoch_size
        records_to_commit = [r for r in self._records if r.tick <= max_tick]
        if not records_to_commit:
            return None

        self.journal_dir.mkdir(parents=True, exist_ok=True)
        filename = f"journal_epoch_{epoch_num:05d}.jsonl"
        target_path = self.journal_dir / filename
        temp_path = self.journal_dir / f"{filename}.tmp"

        start_tick = records_to_commit[0].tick
        end_tick = records_to_commit[-1].tick
        start_seq = records_to_commit[0].sequence_id
        end_seq = records_to_commit[-1].sequence_id
        start_prev = records_to_commit[0].prev_hash
        terminal_hash = records_to_commit[-1].record_hash

        # Write uncompressed canonical JSON lines with atomic rename and fsync
        h = hashlib.sha256()
        with open(temp_path, "wb") as f:
            for rec in records_to_commit:
                rec_dict = rec.to_dict()
                line_bytes = json.dumps(rec_dict, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
                f.write(line_bytes)
                h.update(line_bytes)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, target_path)
        file_sha256 = h.hexdigest()

        meta = JournalSegmentMeta(
            epoch=epoch_num,
            filename=filename,
            filepath=str(target_path),
            start_tick=start_tick,
            end_tick=end_tick,
            start_sequence_id=start_seq,
            end_sequence_id=end_seq,
            start_prev_hash=start_prev,
            terminal_hash=terminal_hash,
            record_count=len(records_to_commit),
            file_sha256=file_sha256,
        )

        self._committed_segments.append(meta)
        self._latest_segment_hash = terminal_hash
        self._latest_segment_file_hash = file_sha256

        # Retain only uncommitted active records in memory
        self._records = [r for r in self._records if r.tick > max_tick]
        return meta

    def read_segment_records(self, seg: JournalSegmentMeta) -> List[EventRecord]:
        """Read and parse all EventRecords from an uncompressed segment file."""
        records: List[EventRecord] = []
        filepath = Path(seg.filepath)
        if not filepath.exists():
            filepath = self.journal_dir / seg.filename
        if not filepath.exists():
            raise JournalTamperError(f"Segment file missing on disk: {filepath}")
        with open(filepath, "rb") as f:
            for line in f:
                line_str = line.decode("utf-8").strip()
                if line_str:
                    records.append(EventRecord.from_dict(json.loads(line_str)))
        return records

    def verify_segment(self, seg: JournalSegmentMeta) -> bool:
        """Verify the cryptographic integrity of a segment file on disk.

        Checks uncompressed file SHA-256 and continuous hash chain.
        Raises JournalTamperError on any tampering.
        """
        filepath = Path(seg.filepath)
        if not filepath.exists():
            filepath = self.journal_dir / seg.filename
        if not filepath.exists():
            raise JournalTamperError(f"Segment file missing: {filepath}")

        # 1. Verify uncompressed file SHA-256
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        computed_file_hash = h.hexdigest()
        if computed_file_hash != seg.file_sha256:
            raise JournalTamperError(
                f"Segment file {seg.filename} SHA-256 mismatch (tampered file!): "
                f"expected {seg.file_sha256}, got {computed_file_hash}"
            )

        # 2. Verify record hash chain
        records = self.read_segment_records(seg)
        if len(records) != seg.record_count:
            raise JournalTamperError(
                f"Segment {seg.filename} record count mismatch: expected {seg.record_count}, got {len(records)}"
            )

        current_hash = seg.start_prev_hash
        for rec in records:
            if rec.prev_hash != current_hash:
                raise JournalTamperError(
                    f"Segment {seg.filename} broken hash chain at seq {rec.sequence_id}: "
                    f"prev_hash {rec.prev_hash} != {current_hash}"
                )
            recomputed = rec.compute_hash(current_hash)
            if rec.record_hash != recomputed:
                raise JournalTamperError(
                    f"Segment {seg.filename} tampered record at seq {rec.sequence_id}: "
                    f"record_hash {rec.record_hash} != {recomputed}"
                )
            current_hash = recomputed

        if current_hash != seg.terminal_hash:
            raise JournalTamperError(
                f"Segment {seg.filename} terminal hash mismatch: "
                f"expected {seg.terminal_hash}, got {current_hash}"
            )

        return True

    def hash_through_tick(self, tick: int) -> str:
        """Compute the cumulative hash of all records up to and including tick across all segments."""
        # 1. Check in active in-memory records
        matching_active = [r for r in self._records if r.tick <= tick]
        if matching_active:
            return matching_active[-1].record_hash

        # 2. Check in committed segments (newest to oldest)
        for seg in reversed(self._committed_segments):
            if seg.start_tick <= tick <= seg.end_tick:
                if tick == seg.end_tick:
                    return seg.terminal_hash
                recs = self.read_segment_records(seg)
                matching = [r for r in recs if r.tick <= tick]
                if matching:
                    return matching[-1].record_hash
                return seg.start_prev_hash
            elif tick > seg.end_tick:
                return seg.terminal_hash

        return GENESIS_BLOCK_HASH

    def verify_integrity(self) -> bool:
        """Verify entire cryptographic hash chain across all committed segments and active records."""
        expected_prev = GENESIS_BLOCK_HASH
        for seg in self._committed_segments:
            if seg.start_prev_hash != expected_prev:
                raise JournalTamperError(
                    f"Segment {seg.filename} does not chain to previous terminal hash: "
                    f"{seg.start_prev_hash} != {expected_prev}"
                )
            self.verify_segment(seg)
            expected_prev = seg.terminal_hash

        # Verify active in-memory records
        current_hash = expected_prev
        for rec in self._records:
            if rec.prev_hash != current_hash:
                raise JournalTamperError(
                    f"Active record seq {rec.sequence_id} prev_hash mismatch: "
                    f"{rec.prev_hash} != {current_hash}"
                )
            recomputed = rec.compute_hash(current_hash)
            if rec.record_hash != recomputed:
                raise JournalTamperError(
                    f"Active record seq {rec.sequence_id} tampered: "
                    f"{rec.record_hash} != {recomputed}"
                )
            current_hash = recomputed

        if current_hash != self._last_hash:
            raise JournalTamperError(f"Journal terminal hash mismatch: {current_hash} != {self._last_hash}")

        return True

    def reconcile_crash_recovery(self, snapshot_tick: int, snapshot_last_hash: str) -> None:
        """Reconcile on-disk segments with snapshot state after an unexpected process crash.

        Quarantines any on-disk segment written after the recovered snapshot's tick.
        """
        valid_segments: List[JournalSegmentMeta] = []
        for seg in self._committed_segments:
            if seg.end_tick <= snapshot_tick:
                valid_segments.append(seg)
            else:
                p = Path(seg.filepath)
                if p.exists():
                    quarantine_path = p.with_suffix(".orphaned_post_crash")
                    os.replace(p, quarantine_path)

        self._committed_segments = valid_segments
        if valid_segments:
            self._latest_segment_hash = valid_segments[-1].terminal_hash
            self._latest_segment_file_hash = valid_segments[-1].file_sha256
        else:
            self._latest_segment_hash = ""
            self._latest_segment_file_hash = ""

        # Trim active records to only those <= snapshot_tick
        self._records = [r for r in self._records if r.tick <= snapshot_tick]
        self._last_hash = snapshot_last_hash

        # Check for any orphaned segment files on disk in journal_dir
        if self.journal_dir.exists():
            for f in self.journal_dir.glob("journal_epoch_*.jsonl"):
                is_valid = any(Path(s.filepath).name == f.name for s in valid_segments)
                if not is_valid:
                    quarantine_path = f.with_suffix(".orphaned_post_crash")
                    os.replace(f, quarantine_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "journal_dir": str(self.journal_dir),
            "epoch_size": self.epoch_size,
            "last_hash": self._last_hash,
            "latest_segment_hash": self._latest_segment_hash,
            "latest_segment_file_hash": self._latest_segment_file_hash,
            "committed_segments": [s.to_dict() for s in self._committed_segments],
            "records": [r.to_dict() for r in self._records],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], journal_dir: Optional[str] = None) -> EventJournal:
        dir_to_use = journal_dir or data.get("journal_dir")
        epoch_size = int(data.get("epoch_size", 365))
        journal = cls(journal_dir=dir_to_use, epoch_size=epoch_size)
        journal._last_hash = data.get("last_hash", GENESIS_BLOCK_HASH)
        journal._latest_segment_hash = data.get("latest_segment_hash", "")
        journal._latest_segment_file_hash = data.get("latest_segment_file_hash", "")
        for sdata in data.get("committed_segments", []):
            journal._committed_segments.append(JournalSegmentMeta.from_dict(sdata))
        for rdata in data.get("records", []):
            journal._records.append(EventRecord.from_dict(rdata))
        return journal
