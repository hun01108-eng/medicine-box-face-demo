import json
import tempfile
import unittest
from pathlib import Path

from facebox.demo import CompetitionDemo, DemoConfig, load_demo_config


class CompetitionDemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_simulation_uses_no_hardware_and_writes_summary(self):
        demo = CompetitionDemo(self.root, DemoConfig(), self.root / "logs")
        results = demo.simulate()
        self.assertEqual(len(results), 6)
        self.assertTrue(all(result.status == "simulated" for result in results))
        summary = demo.save_summary("simulate")
        payload = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], "simulate")
        self.assertEqual(len(payload["results"]), 6)

    def test_medicine_step_is_explicitly_skipped_without_adapter(self):
        demo = CompetitionDemo(self.root, DemoConfig(), self.root / "logs")
        result = demo.medicine()
        self.assertEqual(result.status, "skipped")
        self.assertIn("未配置", result.message)

    def test_config_rejects_non_positive_timeout(self):
        path = self.root / "demo.json"
        path.write_text(
            json.dumps({"face_timeout_seconds": 0}, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "必须大于0"):
            load_demo_config(path)


if __name__ == "__main__":
    unittest.main()
