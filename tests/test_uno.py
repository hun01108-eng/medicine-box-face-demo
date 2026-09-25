import unittest

from facebox.uno import EVENT_AUDIO_COMMANDS, RISK_AUDIO_COMMANDS, UnoNotifier


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


class UnoTests(unittest.TestCase):
    def test_notifier_uses_extended_ack_timeout(self):
        captured = {}

        def serial_factory(*_args, **kwargs):
            captured.update(kwargs)
            return FakeSerial()

        notifier = UnoNotifier("test", serial_factory=serial_factory, reset_delay=0)
        self.assertEqual(captured["timeout"], 2.0)
        notifier.close()

    def test_notifier_ignores_debug_lines_before_ack(self):
        class DebugSerial(FakeSerial):
            def __init__(self):
                super().__init__()
                self.replies = iter((b'RX: "0005"\n', b"ACK\n"))

            def readline(self):
                return next(self.replies)

        fake = DebugSerial()
        notifier = UnoNotifier(
            "test", serial_factory=lambda *_args, **_kwargs: fake, reset_delay=0
        )
        self.assertTrue(notifier.notify(b"0005\n"))
        notifier.close()

    def test_notifier_sends_three_risk_audio_numbers(self):
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

    def test_notifier_sends_face_and_thermal_audio_numbers(self):
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

    def test_notifier_rejects_unknown_risk(self):
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
