import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from facebox.app import parser
from facebox.config import AppConfig


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "facebox.app", *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_known_simulation_outputs_matched_json(self):
        completed = self.run_cli("simulate", "--case", "known")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "MATCHED")
        self.assertEqual(payload["user_id"], "elder_001")
        self.assertLessEqual(payload["latency_seconds"], 3.0)

    def test_unknown_simulation_fails_closed(self):
        completed = self.run_cli("simulate", "--case", "unknown")
        self.assertEqual(completed.returncode, 2, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertIsNone(payload["user_id"])

    def test_dark_simulation_requests_retry(self):
        completed = self.run_cli("simulate", "--case", "dark")
        self.assertEqual(completed.returncode, 3, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "UNKNOWN_RETRY")
        self.assertEqual(payload["reason"], "too_dark")

    def test_usb_camera_is_the_default(self):
        arguments = parser().parse_args(["run"])
        config = AppConfig()
        self.assertIsNone(arguments.source)
        self.assertIsNone(arguments.device)
        self.assertEqual(config.camera_source, "opencv")
        self.assertEqual(config.camera_device, "/dev/video0")


if __name__ == "__main__":
    unittest.main()
