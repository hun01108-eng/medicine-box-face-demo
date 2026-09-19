import unittest

import numpy as np

from facebox.thermal import (
    COLS,
    EVENT_AUDIO_COMMANDS,
    FRAME_LEN,
    HEADER,
    PERSON_COMMAND,
    RISK_AUDIO_COMMANDS,
    ROWS,
    ThermalPersonDetector,
    UnoNotifier,
    clean_frame,
    parse_frame,
)


class FakeSerial:
    def __init__(self, *_args, **_kwargs):
        self.written = bytearray()
        self.closed = False

    def write(self, payload):
        self.written.extend(payload)

    def flush(self):
        pass

    def readline(self):
        return b"ACK\n"

    def close(self):
        self.closed = True


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

    def test_uno_notifier_uses_agreed_protocol(self):
        fake = FakeSerial()
        notifier = UnoNotifier(
            "test", serial_factory=lambda *_args, **_kwargs: fake, reset_delay=0
        )
        self.assertTrue(notifier.notify_person())
        self.assertEqual(bytes(fake.written), PERSON_COMMAND)
        notifier.close()
        self.assertTrue(fake.closed)

    def test_uno_notifier_sends_three_risk_audio_numbers(self):
        for risk_level, expected in RISK_AUDIO_COMMANDS.items():
            with self.subTest(risk_level=risk_level):
                fake = FakeSerial()
                notifier = UnoNotifier(
                    "test", serial_factory=lambda *_args, **_kwargs: fake, reset_delay=0
                )
                code, acknowledged = notifier.notify_risk(risk_level)
                self.assertTrue(acknowledged)
                self.assertEqual(code, expected.decode("ascii").strip())
                self.assertEqual(bytes(fake.written), expected)
                notifier.close()

    def test_uno_notifier_sends_face_and_thermal_audio_numbers(self):
        fake = FakeSerial()
        sleeps = []
        notifier = UnoNotifier(
            "test",
            serial_factory=lambda *_args, **_kwargs: fake,
            reset_delay=0,
            sleep=sleeps.append,
        )
        results = notifier.notify_event_sequence(
            [
                "person_passed",
                "temperature_high",
                "face_matched",
                "face_failed",
                "temperature_normal",
            ],
            gap_seconds=0.25,
        )
        self.assertTrue(all(acknowledged for _code, acknowledged in results))
        self.assertEqual(sleeps, [0, 0.25, 0.25, 0.25, 0.25])
        self.assertEqual(
            bytes(fake.written),
            b"0004\n0007\n0005\n0006\n0008\n",
        )
        self.assertEqual(EVENT_AUDIO_COMMANDS["person_passed"], b"0004\n")
        notifier.close()

    def test_uno_notifier_rejects_unknown_risk(self):
        fake = FakeSerial()
        notifier = UnoNotifier(
            "test", serial_factory=lambda *_args, **_kwargs: fake, reset_delay=0
        )
        with self.assertRaisesRegex(ValueError, "unsupported flu risk level"):
            notifier.notify_risk("未知")
        self.assertEqual(bytes(fake.written), b"")
        notifier.close()


if __name__ == "__main__":
    unittest.main()
