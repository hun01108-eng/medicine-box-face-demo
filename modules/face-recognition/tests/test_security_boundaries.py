import json
import math
import tempfile
import unittest
from pathlib import Path

from facebox.decision import ContinuousDecision, DecisionConfig, MultiFrameDecision
from facebox.templates import FaceProfile, TemplateStore
from facebox.types import FrameObservation, IdentityStatus


class NonFiniteFeatureTests(unittest.TestCase):
    def test_save_rejects_nan_and_infinity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TemplateStore(Path(directory) / "profile.json")
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    store.save("elder_001", [[value, 1.0]])

    def test_load_rejects_non_finite_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(
                '{"schema_version":1,"user_id":"elder_001","features":[[NaN,1.0]]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                TemplateStore(path).load()

    def test_similarity_rejects_non_finite_candidate(self):
        profile = FaceProfile("elder_001", [[1.0, 0.0]])
        with self.assertRaises(ValueError):
            profile.best_cosine_similarity([math.nan, 1.0])


class NonFiniteDecisionTests(unittest.TestCase):
    def setUp(self):
        self.config = DecisionConfig(required_matches=1, max_valid_frames=1)

    def test_single_run_rejects_nan_similarity(self):
        result = MultiFrameDecision(self.config).update(
            FrameObservation(1.0, 1, True, math.nan)
        )
        self.assertEqual(result.status, IdentityStatus.RETRY)
        self.assertEqual(result.reason, "invalid_similarity")
        self.assertEqual(result.matching_frames, 0)

    def test_continuous_mode_rejects_infinite_similarity(self):
        result = ContinuousDecision(self.config).update(
            FrameObservation(1.0, 1, True, math.inf)
        )
        self.assertEqual(result.status, IdentityStatus.RETRY)
        self.assertEqual(result.reason, "invalid_similarity")
        self.assertEqual(result.matching_frames, 0)


if __name__ == "__main__":
    unittest.main()
