"""GENESIS State Snapshot Substrate.

Provides atomic snapshot persistence (temp file, flush, fsync, atomic rename)
using canonical JSON in binary mode with UTF-8 and LF line endings.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.persistence.canonical import canonical_json_bytes
from genesis.persistence.hasher import compute_file_hash
from genesis.substrate.world_state import WorldState


class SnapshotManager:
    """Atomic snapshot saver and loader."""

    def __init__(self, base_dir: str = "data/snapshots") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, world: WorldState, filename: Optional[str] = None) -> Tuple[str, str]:
        """Save world state atomically to disk.

        Returns: (saved_filepath, sha256_hash)
        """
        if filename is None:
            filename = f"snapshot_tick_{world.clock.current_tick:010d}.json"

        target_path = self.base_dir / filename
        temp_path = self.base_dir / f"{filename}.tmp"

        # Serialize world state to canonical bytes (LF ending, UTF-8, stringified int64)
        canonical_bytes = canonical_json_bytes(world.to_canonical_dict())

        # Write to temporary file with flush and fsync
        with open(temp_path, "wb") as f:
            f.write(canonical_bytes)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename
        os.replace(temp_path, target_path)

        # Write runtime sidecar metadata (not hashed, for local path recovery)
        meta_target = self.base_dir / f"{filename}.meta.json"
        meta_temp = self.base_dir / f"{filename}.meta.json.tmp"
        with open(meta_temp, "w", encoding="utf-8") as f:
            json.dump({"journal_dir": str(world.event_journal.journal_dir)}, f)
        os.replace(meta_temp, meta_target)

        # Compute hash from persisted file
        file_hash = compute_file_hash(str(target_path))
        return str(target_path), file_hash

    def load_snapshot(
        self,
        filepath: str,
        config: Optional[RuntimeConfig] = None,
        journal_dir: Optional[Union[str, Path]] = None,
    ) -> WorldState:
        """Load world state from canonical snapshot file and reconcile journal crash recovery."""
        with open(filepath, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))

        if journal_dir is None:
            meta_path = Path(filepath).parent / f"{Path(filepath).name}.meta.json"
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                        journal_dir = meta_data.get("journal_dir")
                except Exception:
                    pass

        ws = WorldState.from_canonical_dict(data, config=config or DEFAULT_CONFIG, journal_dir=journal_dir)
        ws.event_journal.reconcile_crash_recovery(ws.clock.current_tick, ws.event_journal.last_hash)
        return ws
