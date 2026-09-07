import unittest

from facebox.quality import QualityConfig, QualityMetrics, evaluate_quality
from facebox.session import IdentitySession
from facebox.types import IdentityResult, IdentityStatus


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.config = QualityConfig(
            min_face_width=100,
            min_brightness=45.0,
            max_brightness=220.0,
            min_sharpness=60.0,
        )

    def test_accepts_valid_face(self):
        result = evaluate_quality(QualityMetrics(140, 110.0, 90.0), self.config)
        self.assertTrue(result.ok)

    def test_rejects_small_dark_overexposed_and_blurry_faces(self):
        cases = [
            (QualityMetrics(60, 110.0, 90.0), "face_too_small"),
            (QualityMetrics(140, 30.0, 90.0), "too_dark"),
            (QualityMetrics(140, 240.0, 90.0), "overexposed"),
            (QualityMetrics(140, 110.0, 20.0), "blurry"),
        ]
        for metrics, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_quality(metrics, self.config)
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, reason)


class SessionTests(unittest.TestCase):
    def test_identity_expires_after_person_leaves(self):
        session = IdentitySession(absence_timeout_seconds=2.0)
        session.accept(IdentityResult(IdentityStatus.MATCHED, "elder_001", 0.7), now=10.0)
        self.assertEqual(session.current_user(11.9), "elder_001")
        session.observe_no_face(now=12.0)
        self.assertIsNone(session.current_user(14.1))

    def test_unknown_result_clears_prior_identity(self):
        session = IdentitySession(absence_timeout_seconds=2.0)
        session.accept(IdentityResult(IdentityStatus.MATCHED, "elder_001", 0.7), now=10.0)
        session.accept(IdentityResult(IdentityStatus.UNKNOWN), now=10.5)
        self.assertIsNone(session.current_user(10.6))


if __name__ == "__main__":
    unittest.main()
