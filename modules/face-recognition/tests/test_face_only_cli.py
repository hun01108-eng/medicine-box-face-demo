import argparse
import json
import tempfile
import unittest
from pathlib import Path

from facebox.app import load_profile, monitor_label, parser
from facebox.config import AppConfig, load_config
from facebox.types import FrameObservation, IdentityResult, IdentityStatus


class FaceOnlyCliTests(unittest.TestCase):
    def test_parser_exposes_only_face_commands(self):
        cli = parser()
        subparsers = next(
            action for action in cli._actions if isinstance(action, argparse._SubParsersAction)
        )
        self.assertEqual(
            set(subparsers.choices),
            {"simulate", "enroll", "run", "monitor", "benchmark", "self-check"},
        )

    def test_default_config_contains_no_cloud_or_thermal_section(self):
        self.assertFalse(hasattr(AppConfig(), "flu_api"))

    def test_face_only_config_loads_without_flu_section(self):
        payload = {
            "detector_model": "models/detector.onnx",
            "recognizer_model": "models/recognizer.onnx",
            "profile_path": "data/elder_001.json",
            "decision": {"user_id": "elder_001"},
            "quality": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.decision.user_id, "elder_001")
        self.assertFalse(hasattr(config, "flu_api"))

    def test_profile_identity_must_match_configured_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "data" / "profile.json"
            store.parent.mkdir()
            store.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "user_id": "other_person",
                        "features": [[1.0, 0.0]],
                    }
                ),
                encoding="utf-8",
            )
            config = AppConfig(profile_path="data/profile.json")
            with self.assertRaisesRegex(ValueError, "profile user_id"):
                load_profile(config, root)

    def test_monitor_labels_match_quality_reason_names(self):
        observation = FrameObservation(1.0, 1, False, None)
        bright = IdentityResult(IdentityStatus.RETRY, reason="overexposed")
        blurry = IdentityResult(IdentityStatus.RETRY, reason="blurry")
        self.assertIn("过亮", monitor_label(observation, bright)[0])
        self.assertIn("模糊", monitor_label(observation, blurry)[0])


if __name__ == "__main__":
    unittest.main()
