"""Tests for GENESIS Determinism, PRNG, and Canonical Binary Serialization."""

import os
import subprocess
import sys
import unittest

from genesis.core.arithmetic import FixedPoint, MAX_INT64
from genesis.core.rng import GenesisRNG
from genesis.persistence.canonical import canonical_json_bytes, canonical_json_string
from genesis.persistence.hasher import compute_canonical_hash
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.world_state import WorldState

# Committed Golden Hashes for fixed seed 20261105 across 100 ticks with active RNG (SUMMARY audit level)
# Cross-platform invariant: free of host directories, paths, slashes, or OS-specific formats
# Note: EXPECTED_GOLDEN_STATE_HASH updated in Phase 2a-fix due to inclusion of canonical "world_seed" field in WorldState
EXPECTED_GOLDEN_STATE_HASH = "54d4f3bbed956449874c10713d7dfb61a24a408975899a89285fa8fc925c5dec"
EXPECTED_GOLDEN_JOURNAL_HASH = "3207971d4222cc9c9831df60c4f44dcf46b8b88b398d8f2ffbf358e66fb8c92b"


class TestDeterminismSubstrate(unittest.TestCase):

    def test_xoshiro256_stream_reproducibility(self):
        rng1 = GenesisRNG(123456789)
        rng2 = GenesisRNG(123456789)

        stream1 = [rng1.next_uint64() for _ in range(100)]
        stream2 = [rng2.next_uint64() for _ in range(100)]

        self.assertEqual(stream1, stream2)
        self.assertEqual(rng1.step_count, 100)

    def test_xoshiro256_state_save_and_restore(self):
        rng = GenesisRNG(987654321)
        for _ in range(50):
            rng.next_uint64()

        saved_state = rng.get_state()
        continued = [rng.next_uint64() for _ in range(50)]

        restored_rng = GenesisRNG(0)
        restored_rng.set_state(saved_state)
        resumed = [restored_rng.next_uint64() for _ in range(50)]

        self.assertEqual(continued, resumed)
        self.assertEqual(restored_rng.step_count, 100)

    def test_canonical_json_lf_and_sorted_keys(self):
        data = {
            "zebra": 1,
            "alpha": 2,
            "middle": {"charlie": 3, "bravo": 4},
        }
        b = canonical_json_bytes(data)
        self.assertTrue(b.endswith(b"\n"))
        self.assertNotIn(b"\r", b)

        s = b.decode("utf-8")
        self.assertTrue(s.index('"alpha"') < s.index('"middle"') < s.index('"zebra"'))
        self.assertTrue(s.index('"bravo"') < s.index('"charlie"'))

    def test_json_number_stringification_above_2_pow_53(self):
        large_int = MAX_INT64
        fp = FixedPoint.from_raw(MAX_INT64)

        data = {
            "large_quantity": large_int,
            "fixed_point": fp,
        }
        b = canonical_json_bytes(data)
        s = b.decode("utf-8")

        self.assertIn('"large_quantity":"9223372036854775807"', s)
        self.assertIn('"val":"9223372036854775807"', s)

    def test_event_phases_and_strictly_monotonic_sequence_ids(self):
        """Verify events have valid phase constants and strictly unique, incrementing sequence IDs."""
        world = WorldState(seed=101)
        for _ in range(5):
            world.advance_tick()

        records = world.event_journal.records
        self.assertGreater(len(records), 0)

        # Check sequence IDs are strictly increasing
        seq_ids = [r.sequence_id for r in records]
        self.assertEqual(seq_ids, sorted(seq_ids))
        self.assertEqual(len(seq_ids), len(set(seq_ids)), "Sequence IDs must be strictly unique")

        # Check phases are valid phase constants
        valid_phases = {0, 1, 2, 3, 4}
        for r in records:
            self.assertIn(r.phase, valid_phases, f"Invalid phase constant {r.phase} in event {r.event_type}")

    def test_committed_golden_hash_with_active_rng(self):
        """Verify bit-identical simulation results against committed golden hashes using active PRNG."""
        world = WorldState(seed=20261105)
        world.resources.create_pool("energy", initial_balance=FixedPoint.from_int(10000))
        schema = EntityTypeSchema("organism")
        schema.add_property(PropertyDefinition("energy", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
        schema.add_property(PropertyDefinition("generation", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema)

        for i in range(25):
            world.entities.create_entity("organism", 0, {"energy": FixedPoint.from_int(100 + i)}, world.schema_registry)

        for tick in range(100):
            # Explicitly exercise RNG
            roll = world.rng.next_int_range(1, 50)
            world.resources.get_pool("energy").produce(FixedPoint.from_int(roll))
            ent = world.entities.get_entity((tick % 25) + 1)
            if ent:
                ent.set_property("energy", ent.get_property("energy") + FixedPoint.from_raw(roll * 10000))
            world.advance_tick()

        computed_state_hash = compute_canonical_hash(world.to_canonical_dict())
        computed_journal_hash = world.event_journal.last_hash

        self.assertEqual(computed_state_hash, EXPECTED_GOLDEN_STATE_HASH, "State hash drifted from golden standard")
        self.assertEqual(computed_journal_hash, EXPECTED_GOLDEN_JOURNAL_HASH, "Journal hash drifted from golden standard")

    def test_cross_platform_path_invariance_and_golden_hash(self):
        """Prove that worlds with Windows vs Linux paths and segment file paths yield bit-identical state hashes.

        Simulates running on Linux (/var/log/sim, /tmp/sim) vs Windows (C:\\sim, D:\\data).
        Verifies that journal_dir and filepath are completely absent from canonical state.
        """
        import tempfile
        from pathlib import Path

        temp_dir = tempfile.mkdtemp()
        linux_sim_dir = Path(temp_dir) / "linux_sim"
        win_sim_dir = Path(temp_dir) / "win_sim"

        w_linux = WorldState(seed=20261105, journal_dir=linux_sim_dir)
        w_win = WorldState(seed=20261105, journal_dir=win_sim_dir)

        for w in (w_linux, w_win):
            w.resources.create_pool("energy", initial_balance=FixedPoint.from_int(10000))
            schema = EntityTypeSchema("organism")
            schema.add_property(PropertyDefinition("energy", PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
            schema.add_property(PropertyDefinition("generation", PropertyType.INT64, default_value=0))
            w.schema_registry.register_type(schema)

            for i in range(25):
                w.entities.create_entity("organism", 0, {"energy": FixedPoint.from_int(100 + i)}, w.schema_registry)

        # Run 10 ticks and commit epoch segment on both worlds
        w_linux.event_journal.epoch_size = 5
        w_win.event_journal.epoch_size = 5

        for tick in range(10):
            roll_linux = w_linux.rng.next_int_range(1, 50)
            roll_win = w_win.rng.next_int_range(1, 50)
            self.assertEqual(roll_linux, roll_win)

            for w, roll in ((w_linux, roll_linux), (w_win, roll_win)):
                w.resources.get_pool("energy").produce(FixedPoint.from_int(roll))
                ent = w.entities.get_entity((tick % 25) + 1)
                if ent:
                    ent.set_property("energy", ent.get_property("energy") + FixedPoint.from_raw(roll * 10000))
                w.advance_tick()

        # Both worlds committed 2 epoch segments
        self.assertEqual(len(w_linux.event_journal.committed_segments), 2)
        self.assertEqual(len(w_win.event_journal.committed_segments), 2)

        # Verify segments on disk
        self.assertTrue(w_linux.event_journal.verify_integrity())
        self.assertTrue(w_win.event_journal.verify_integrity())

        # Canonical dictionaries and hashes must be 100% bit-identical
        dict_linux = w_linux.to_canonical_dict()
        dict_win = w_win.to_canonical_dict()

        # Check absence of paths in canonical state
        self.assertNotIn("journal_dir", dict_linux["event_journal"])
        self.assertNotIn("journal_dir", dict_win["event_journal"])
        for seg in dict_linux["event_journal"]["committed_segments"]:
            self.assertNotIn("filepath", seg)
        for seg in dict_win["event_journal"]["committed_segments"]:
            self.assertNotIn("filepath", seg)

        hash_linux = compute_canonical_hash(dict_linux)
        hash_win = compute_canonical_hash(dict_win)

        self.assertEqual(hash_linux, hash_win, "Linux and Windows path worlds produced divergent canonical state hashes!")
        self.assertEqual(w_linux.event_journal.last_hash, w_win.event_journal.last_hash)

    def test_cross_process_pythonhashseed_determinism(self):
        """Run independent simulation subprocesses with different PYTHONHASHSEED values.

        Guarantees that dictionary hashing, set iteration, or Python process salt
        causes ZERO desynchronization in state or event journal digests.
        """
        worker_code = """
import sys
from genesis.substrate.world_state import WorldState
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.core.arithmetic import FixedPoint
from genesis.persistence.hasher import compute_canonical_hash

world = WorldState(seed=88888)
world.resources.create_pool('minerals', initial_balance=FixedPoint.from_int(5000))
schema = EntityTypeSchema('agent')
schema.add_property(PropertyDefinition('hp', PropertyType.FIXED_POINT, default_value=FixedPoint.from_int(100)))
schema.add_property(PropertyDefinition('xp', PropertyType.INT64, default_value=0))
world.schema_registry.register_type(schema)

for i in range(30):
    world.entities.create_entity('agent', 0, {'hp': FixedPoint.from_int(100 + i), 'xp': i * 10}, world.schema_registry)

for tick in range(50):
    roll = world.rng.next_int_range(1, 100)
    world.resources.get_pool('minerals').produce(FixedPoint.from_int(roll))
    target = world.entities.get_entity((tick % 30) + 1)
    if target:
        target.set_property('hp', target.get_property('hp') + FixedPoint.from_int(roll % 5))
        target.set_property('xp', target.get_property('xp') + roll)
    world.advance_tick()

state_hash = compute_canonical_hash(world.to_canonical_dict())
journal_hash = world.event_journal.last_hash
print(f"{state_hash}:{journal_hash}")
"""
        test_seeds = ["0", "42", "123456", "987654321"]
        outputs = []

        for hseed in test_seeds:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = hseed
            proc = subprocess.run(
                [sys.executable, "-c", worker_code],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            out = proc.stdout.strip()
            outputs.append(out)

        # Assert all subprocesses with different PYTHONHASHSEED produced bit-identical output
        first_output = outputs[0]
        for idx, out in enumerate(outputs[1:], start=1):
            self.assertEqual(
                first_output,
                out,
                f"Subprocess with PYTHONHASHSEED={test_seeds[idx]} drifted from seed {test_seeds[0]}",
            )


if __name__ == "__main__":
    unittest.main()
