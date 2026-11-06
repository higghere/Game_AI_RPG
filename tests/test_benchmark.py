"""Unit test runner for the Phase 1 benchmark."""

import os
import unittest
from tests.benchmark_phase1 import run_benchmark


class TestInterpreterBenchmark(unittest.TestCase):

    def test_benchmark_throughput(self):
        """Execute benchmark and verify throughput with generous thresholds for slow machines."""
        if os.environ.get("GENESIS_SKIP_BENCHMARK") == "1":
            self.skipTest("Benchmark skipped via GENESIS_SKIP_BENCHMARK=1")

        res = run_benchmark(num_ticks=50, num_agents=300, num_cells=30)
        self.assertGreater(res["total_operations"], 0, "Benchmark must execute GRL operations")

        # Generous floor (50 ops/sec) ensuring correctness even on constrained hardware (e.g. Raspberry Pi / VMs)
        self.assertGreater(
            res["ops_per_second"],
            50.0,
            f"Interpreter throughput unexpectedly low: {res['ops_per_second']:.1f} ops/sec"
        )
        # Generous projection limit (600 seconds / 10 minutes for 3,650 ticks)
        self.assertLess(
            res["projected_time_3650_ticks_s"],
            600.0,
            f"Projected runtime for 3,650 ticks exceeds 10 minutes: {res['projected_time_3650_ticks_s']:.1f}s"
        )


if __name__ == "__main__":
    unittest.main()
