import unittest

from facebox.decision import DecisionConfig, MultiFrameDecision
from facebox.types import FrameObservation, IdentityStatus


class MultiFrameDecisionTests(unittest.TestCase):
    def setUp(self):
        self.engine = MultiFrameDecision(
            DecisionConfig(
                similarity_threshold=0.55,
                required_matches=3,
                max_valid_frames=5,
                timeout_seconds=3.0,
            )
        )

    def test_three_matching_frames_confirm_registered_elder(self):
        now = 10.0
        observations = [
            FrameObservation(now, 1, True, 0.61),
            FrameObservation(now + 0.2, 1, True, 0.58),
            FrameObservation(now + 0.4, 1, True, 0.63),
        ]
        result = None
        for observation in observations:
            result = self.engine.update(observation)
        self.assertEqual(result.status, IdentityStatus.MATCHED)
        self.assertEqual(result.user_id, "elder_001")

    def test_low_similarity_frames_return_unknown(self):
        result = None
        for index, score in enumerate([0.20, 0.31, 0.42, 0.39, 0.28]):
            result = self.engine.update(
                FrameObservation(20.0 + index * 0.2, 1, True, score)
            )
        self.assertEqual(result.status, IdentityStatus.UNKNOWN)
        self.assertIsNone(result.user_id)

    def test_poor_quality_never_counts_as_match(self):
        result = None
        for index in range(5):
            result = self.engine.update(
                FrameObservation(30.0 + index * 0.2, 1, False, 0.99, "too_dark")
            )
        self.assertEqual(result.status, IdentityStatus.RETRY)
        self.assertEqual(result.reason, "too_dark")

    def test_multiple_faces_fail_closed_immediately(self):
        result = self.engine.update(FrameObservation(40.0, 2, True, 0.99))
        self.assertEqual(result.status, IdentityStatus.RETRY)
        self.assertEqual(result.reason, "multiple_faces")

    def test_waiting_without_face_does_not_start_three_second_timer(self):
        self.engine.update(FrameObservation(40.0, 0, False, None, "no_face"))
        result = self.engine.update(FrameObservation(50.0, 1, True, 0.60))
        self.assertEqual(result.status, IdentityStatus.WAITING)
        self.assertEqual(result.reason, "collecting_frames")

    def test_timeout_returns_retry(self):
        self.engine.update(FrameObservation(50.0, 1, True, 0.60))
        result = self.engine.update(FrameObservation(53.1, 1, True, 0.60))
        self.assertEqual(result.status, IdentityStatus.RETRY)
        self.assertEqual(result.reason, "timeout")


if __name__ == "__main__":
    unittest.main()
