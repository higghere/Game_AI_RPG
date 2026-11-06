"""Unit test runner for the Phase 1 benchmark."""

import unittest
from tests.benchmark_phase1 import run_benchmark, print_benchmark_report


class TestInterpreterBenchmark(unittest.TestCase):

    def test_benchmark_throughput(self):
        """Execute benchmark and verify throughput."""
        res = run_benchmark(num_ticks=50, num_agents=300, num_cells=30)
        self.assertGreater(res["total_operations"], 0)
        self.assertGreater(res["ops_per_second"], 1000)
        self.assertLess(res["projected_time_3650_ticks_s"], 60.0)


if __name__ == "__main__":
    unittest.main()
