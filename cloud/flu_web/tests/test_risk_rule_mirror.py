"""保证树莓派与云端的独立规则副本不会悄然产生不同结果。"""

import importlib.util
import unittest
from pathlib import Path

import risk_rules as cloud_rules


WORKER_RULES_PATH = (
    Path(__file__).resolve().parents[3] / "workers" / "flu_updater" / "risk_rules.py"
)


def load_worker_rules():
    spec = importlib.util.spec_from_file_location("worker_risk_rules", WORKER_RULES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RiskRuleMirrorTest(unittest.TestCase):
    def test_cloud_and_pi_rules_match(self):
        worker_rules = load_worker_rules()
        samples = [
            {
                "south_positivity_rate": 16.0,
                "north_positivity_rate": 11.0,
                "outbreak_count": 2,
                "south_trend": "上升",
                "north_trend": "上升",
                "h3n2_resistance_ratio": 6.0,
            },
            {
                "south_positivity_rate": 5.0,
                "north_positivity_rate": 11.0,
                "outbreak_count": 0,
                "south_trend": "下降",
                "north_trend": "下降",
                "h3n2_resistance_ratio": 1.0,
            },
            {
                "south_positivity_rate": 5.0,
                "north_positivity_rate": 5.0,
                "outbreak_count": 0,
                "south_trend": "下降",
                "north_trend": "下降",
                "h3n2_resistance_ratio": 1.0,
            },
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(
                    cloud_rules.assess_weekly_risk(sample),
                    worker_rules.assess_weekly_risk(sample),
                )


if __name__ == "__main__":
    unittest.main()
