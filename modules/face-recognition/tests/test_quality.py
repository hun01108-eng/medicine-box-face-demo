import unittest

from facebox.opencv_engine import _clipped_face_width
from facebox.quality import QualityConfig, QualityMetrics, evaluate_quality


class QualityTests(unittest.TestCase):
    def test_accepts_valid_face(self):
        result = evaluate_quality(QualityMetrics(140, 110.0, 90.0), QualityConfig())
        self.assertTrue(result.ok)

    def test_rejects_small_dark_overexposed_and_blurry_faces(self):
        cases = [
            (QualityMetrics(50, 100.0, 100.0), "face_too_small"),
            (QualityMetrics(120, 20.0, 100.0), "too_dark"),
            (QualityMetrics(120, 240.0, 100.0), "overexposed"),
            (QualityMetrics(120, 100.0, 10.0), "blurry"),
        ]
        for metrics, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(evaluate_quality(metrics, QualityConfig()).reason, reason)

    def test_clipped_face_width_uses_only_visible_pixels(self):
        self.assertEqual(_clipped_face_width((-20, 5, 100, 80), 200), 80)
        self.assertEqual(_clipped_face_width((190, 5, 50, 80), 200), 10)
        self.assertEqual(_clipped_face_width((20, 5, 100, 80), 200), 100)


if __name__ == "__main__":
    unittest.main()
