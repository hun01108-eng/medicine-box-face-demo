import unittest

from medicine_vision.alerting import ShortageGate


class ShortageGateTests(unittest.TestCase):
    def test_requires_consecutive_shortage_frames(self):
        gate = ShortageGate(green_min_count=3, red_min_count=3, confirm_frames=3, interval_seconds=10)
        self.assertFalse(gate.update(2, 3, now=0.0).should_alert)
        self.assertFalse(gate.update(2, 3, now=0.1).should_alert)
        result = gate.update(2, 3, now=0.2)
        self.assertTrue(result.should_alert)
        self.assertEqual(result.reasons, ("green_low",))

    def test_sufficient_frame_resets_confirmation(self):
        gate = ShortageGate(3, 3, confirm_frames=2, interval_seconds=10)
        self.assertFalse(gate.update(2, 3, now=0.0).should_alert)
        self.assertFalse(gate.update(3, 3, now=0.1).should_alert)
        self.assertFalse(gate.update(2, 3, now=0.2).should_alert)
        self.assertTrue(gate.update(2, 3, now=0.3).should_alert)

    def test_alerts_are_rate_limited(self):
        gate = ShortageGate(3, 3, confirm_frames=1, interval_seconds=10)
        self.assertTrue(gate.update(2, 2, now=0.0).should_alert)
        self.assertFalse(gate.update(2, 2, now=9.9).should_alert)
        self.assertTrue(gate.update(2, 2, now=10.0).should_alert)


if __name__ == "__main__":
    unittest.main()
