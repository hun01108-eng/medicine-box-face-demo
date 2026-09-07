import unittest

from facebox.metrics import summarize_latencies


class MetricsTests(unittest.TestCase):
    def test_reports_p50_p95_and_three_second_pass(self):
        summary = summarize_latencies([0.4, 0.6, 0.8, 1.0, 2.9])
        self.assertEqual(summary["trials"], 5)
        self.assertEqual(summary["p50_seconds"], 0.8)
        self.assertEqual(summary["p95_seconds"], 2.9)
        self.assertTrue(summary["p95_within_3s"])

    def test_rejects_empty_measurement_set(self):
        with self.assertRaises(ValueError):
            summarize_latencies([])


if __name__ == "__main__":
    unittest.main()
