import unittest
from unittest.mock import patch

from facebox.opencv_engine import OpenCVFaceEngine


class EngineTimingTests(unittest.TestCase):
    def test_no_face_observation_records_processing_completion(self):
        engine = object.__new__(OpenCVFaceEngine)
        engine.detect = lambda frame: []
        with patch("facebox.opencv_engine.time.monotonic", side_effect=[10.0, 10.25]):
            observation = engine.observe(None, None)
        self.assertEqual(observation.timestamp, 10.0)
        self.assertEqual(observation.processed_at, 10.25)

    def test_explicit_clock_remains_deterministic(self):
        engine = object.__new__(OpenCVFaceEngine)
        engine.detect = lambda frame: []
        observation = engine.observe(None, None, timestamp=5.0)
        self.assertEqual(observation.processed_at, 5.0)
