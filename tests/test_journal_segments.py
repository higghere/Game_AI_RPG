"""Unit tests for GENESIS Segmented Event Journal, Continuous Hash Chain, and Crash Recovery."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from genesis.core.arithmetic import FixedPoint
from genesis.core.config import RuntimeConfig
from genesis.core.errors import JournalTamperError
from genesis.grl.parser import GRLParser
from genesis.persistence.snapshot import SnapshotManager
from genesis.substrate.events import (
    AUDIT_LEVEL_MINIMAL,
    AUDIT_LEVEL_SUMMARY,
    AUDIT_LEVEL_TRACE,
    GENESIS_BLOCK_HASH,
    EventJournal,
    EventRecord,
)
from genesis.substrate.world_state import WorldState


class TestJournalSegments(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.journal_dir = Path(self.temp_dir) / "journal"
        self.snapshot_dir = Path(self.temp_dir) / "snapshots"
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cross_segment_hash_through_tick_and_uncompressed_bytes(self):
        """Hash through tick must work continuously across segment boundaries and hash uncompressed canonical bytes."""
        world = WorldState(seed=42)
        world.event_journal.journal_dir = self.journal_dir
        world.event_journal.epoch_size = 10  # 10 ticks per epoch for testing

        # Advance 25 ticks (spans 2 completed epochs: Epoch 1 at 10, Epoch 2 at 20, active at 25)
        for _ in range(25):
            world.advance_tick()

        # Check committed segments
        segments = world.event_journal.committed_segments
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].epoch, 1)
        self.assertEqual(segments[0].start_tick, 1)
        self.assertEqual(segments[0].end_tick, 10)

        self.assertEqual(segments[1].epoch, 2)
        self.assertEqual(segments[1].start_tick, 11)
        self.assertEqual(segments[1].end_tick, 20)

        # Verify continuous hash chain across segments
        self.assertEqual(segments[0].start_prev_hash, GENESIS_BLOCK_HASH)
        self.assertEqual(segments[1].start_prev_hash, segments[0].terminal_hash)

        # Check that segment files exist on disk and contain uncompressed JSON lines
        seg1_file = Path(segments[0].filepath)
        self.assertTrue(seg1_file.exists())
        with open(seg1_file, "rb") as f:
            content = f.read()
            self.assertIn(b'"event_type":"tick_digest"', content)
            self.assertTrue(content.endswith(b"\n"))
            self.assertNotIn(b"\r", content)
            # Verify file SHA-256 matches uncompressed file bytes
            self.assertEqual(hashlib.sha256(content).hexdigest(), segments[0].file_sha256)

        # Test cross-segment hash_through_tick:
        # Tick 5 is inside Segment 1
        hash_at_5 = world.event_journal.hash_through_tick(5)
        self.assertNotEqual(hash_at_5, GENESIS_BLOCK_HASH)

        # Tick 10 is the boundary of Segment 1
        hash_at_10 = world.event_journal.hash_through_tick(10)
        self.assertEqual(hash_at_10, segments[0].terminal_hash)

        # Tick 15 is inside Segment 2
        hash_at_15 = world.event_journal.hash_through_tick(15)
        self.assertNotEqual(hash_at_15, hash_at_10)

        # Tick 20 is the boundary of Segment 2
        hash_at_20 = world.event_journal.hash_through_tick(20)
        self.assertEqual(hash_at_20, segments[1].terminal_hash)

        # Tick 25 is in active in-memory records
        hash_at_25 = world.event_journal.hash_through_tick(25)
        self.assertEqual(hash_at_25, world.event_journal.last_hash)

        # Integrity verification across all segments must pass
        self.assertTrue(world.event_journal.verify_integrity())

    def test_tamper_detection_in_segment_files(self):
        """Tampering with uncompressed segment bytes or records must raise JournalTamperError."""
        world = WorldState(seed=99)
        world.event_journal.journal_dir = self.journal_dir
        world.event_journal.epoch_size = 5

        for _ in range(10):
            world.advance_tick()

        self.assertEqual(len(world.event_journal.committed_segments), 2)
        seg1 = world.event_journal.committed_segments[0]
        seg1_path = Path(seg1.filepath)

        # Tamper test 1: Modify a single byte in the file
        with open(seg1_path, "r+b") as f:
            content = bytearray(f.read())
            # Invert one byte
            content[20] ^= 0xFF
            f.seek(0)
            f.write(content)
            f.flush()

        with self.assertRaises(JournalTamperError) as cm:
            world.event_journal.verify_integrity()
        self.assertIn("tampered", str(cm.exception).lower())

    def test_crash_recovery_between_segment_write_and_snapshot(self):
        """Simulate process crash after segment write but before snapshot; verify clean recovery."""
        snapshot_mgr = SnapshotManager(base_dir=str(self.snapshot_dir))
        world = WorldState(seed=555)
        world.event_journal.journal_dir = self.journal_dir
        world.event_journal.epoch_size = 10

        # Advance to tick 8 and save checkpoint snapshot
        for _ in range(8):
            world.advance_tick()
        snap_path_8, snap_hash_8 = snapshot_mgr.save_snapshot(world, "snapshot_tick_8.json")
        hash_at_8 = world.event_journal.last_hash

        # Now advance past epoch boundary to tick 10 (segment 1 is written to disk)
        world.advance_tick()  # tick 9
        world.advance_tick()  # tick 10: segment 1 committed to disk!

        self.assertEqual(len(world.event_journal.committed_segments), 1)
        seg1_path = Path(world.event_journal.committed_segments[0].filepath)
        self.assertTrue(seg1_path.exists())

        # --- SIMULATE CRASH ---
        # Process crashes before saving snapshot at tick 10.
        # Recovery procedure: load the latest valid snapshot (tick 8).
        recovered_world = snapshot_mgr.load_snapshot(snap_path_8)
        self.assertEqual(recovered_world.clock.current_tick, 8)
        self.assertEqual(recovered_world.event_journal.last_hash, hash_at_8)

        # Verify the orphaned segment written during the crash at tick 10 was quarantined
        self.assertEqual(len(recovered_world.event_journal.committed_segments), 0)
        orphaned_files = list(self.journal_dir.glob("*.orphaned_post_crash"))
        self.assertGreater(len(orphaned_files), 0, "Post-crash segment should be quarantined")

        # Recovered world can now cleanly resume simulation from tick 8 to tick 10 and beyond
        recovered_world.advance_tick()  # tick 9
        recovered_world.advance_tick()  # tick 10: re-commits segment 1 cleanly!

        self.assertEqual(len(recovered_world.event_journal.committed_segments), 1)
        self.assertTrue(recovered_world.event_journal.verify_integrity())

    def test_audit_level_changes_journaled_across_segments(self):
        """Audit level changes must be recorded in journal and maintain valid hash chain across epochs."""
        world = WorldState(seed=777)
        world.event_journal.journal_dir = self.journal_dir
        world.event_journal.epoch_size = 5

        # Tick 1: start at SUMMARY
        world.advance_tick()

        # Tick 2: change to TRACE
        world.set_audit_level("TRACE")
        world.advance_tick()

        # Tick 4: change to MINIMAL
        world.set_audit_level("MINIMAL")
        world.advance_tick()

        # Advance across epoch boundary (tick 5) and into Epoch 2 (ticks 6-10)
        for _ in range(7):
            world.advance_tick()

        self.assertEqual(world.clock.current_tick, 10)
        self.assertEqual(len(world.event_journal.committed_segments), 2)

        # Verify all records across segments contain the audit_level_changed events
        all_records = world.event_journal.records
        change_events = [e for e in all_records if e.event_type == "audit_level_changed"]
        self.assertEqual(len(change_events), 2)
        self.assertEqual(change_events[0].payload["from_level"], "SUMMARY")
        self.assertEqual(change_events[0].payload["to_level"], "TRACE")
        self.assertEqual(change_events[1].payload["from_level"], "TRACE")
        self.assertEqual(change_events[1].payload["to_level"], "MINIMAL")

        # Entire hash chain must be verified
        self.assertTrue(world.event_journal.verify_integrity())


if __name__ == "__main__":
    unittest.main()
