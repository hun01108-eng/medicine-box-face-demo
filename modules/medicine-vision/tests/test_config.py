import json
import tempfile
import unittest
from pathlib import Path

from medicine_vision.app import parser
from medicine_vision.config import load_config


class ConfigTests(unittest.TestCase):
    def test_module_import_does_not_open_hardware(self):
        self.assertIn("config", parser().format_help())

    def test_serial_is_disabled_by_default_for_unassigned_0012_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}", encoding="utf-8")
            config = load_config(path)
        self.assertFalse(config.serial.enabled)
        self.assertEqual(config.serial.alert_command, "0012")

    def test_invalid_count_and_area_ranges_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"green": {"min_count": 0}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_string_false_cannot_enable_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"serial": {"enabled": "false"}}), encoding="utf-8")
            with self.assertRaises(TypeError):
                load_config(path)

    def test_serial_requires_explicit_protocol_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"serial": {"enabled": True}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_non_integer_dimensions_and_non_finite_values_are_rejected(self):
        invalid_payloads = (
            {"camera": {"width": 1280.5}},
            {"camera": {"warmup_seconds": float("inf")}},
            {"green": {"max_area": float("inf")}},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises((TypeError, ValueError)):
                    load_config(path)


if __name__ == "__main__":
    unittest.main()
