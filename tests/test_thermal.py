import unittest

import numpy as np

from facebox.thermal import (
    COLS,
    FRAME_LEN,
    HEADER,
    ROWS,
    ThermalPersonDetector,
    clean_frame,
    parse_frame,
)


class ThermalTests(unittest.TestCase):
    def test_frame_parser_decodes_pixels_and_ambient(self):
        raw_value = int((31.25 + 40.0) * 100)
        ambient_value = int((25.5 + 40.0) * 100)
        frame = bytearray(FRAME_LEN)
        frame[:3] = HEADER
        frame[3] = 1
        pixels = np.full(ROWS * COLS, raw_value, dtype="<u2")
        frame[4 : 4 + pixels.nbytes] = pixels.tobytes()
        frame[1540] = ambient_value & 0xFF
        frame[1541] = ambient_value >> 8
        parsed = parse_frame(b"noise" + bytes(frame))
        self.assertIsNotNone(parsed)
        temperatures, ambient, consumed = parsed
        self.assertAlmostEqual(float(temperatures[10, 10]), 31.25, places=2)
        self.assertAlmostEqual(ambient, 25.5, places=2)
        self.assertEqual(consumed, len(b"noise") + FRAME_LEN)

    def test_clean_frame_removes_hot_edge_pixel(self):
        frame = np.full((ROWS, COLS), 30.0, dtype=np.float32)
        frame[0, 0] = 99.0
        self.assertLess(clean_frame(frame)[0, 0], -100.0)

    def test_detector_emits_once_until_person_leaves(self):
        detector = ThermalPersonDetector(
            warmup_frames=2, confirm_seconds=0.2, clear_seconds=0.2, offset=0
        )
        background = np.full((ROWS, COLS), 24.0, dtype=np.float32)
        person = background.copy()
        person[8:14, 13:18] = 34.0
        detector.step(background, 24.0, 0.0)
        detector.step(background, 24.0, 0.1)
        self.assertIsNone(detector.step(person, 24.0, 1.0)[0])
        event = detector.step(person, 24.0, 1.3)[0]
        self.assertIsNotNone(event)
        self.assertIsNone(detector.step(person, 24.0, 1.6)[0])
        detector.step(background, 24.0, 2.0)
        detector.step(background, 24.0, 2.3)
        detector.step(person, 24.0, 4.5)
        self.assertIsNotNone(detector.step(person, 24.0, 4.8)[0])

if __name__ == "__main__":
    unittest.main()
