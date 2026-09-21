import unittest

from medicine_vision.serial_link import SerialNotifier, validate_command


class FakePort:
    def __init__(self, replies):
        self.replies = list(replies)
        self.writes = []
        self.events = []

    def reset_input_buffer(self):
        self.events.append("reset")

    def write(self, payload):
        self.events.append("write")
        self.writes.append(payload)

    def flush(self):
        pass

    def readline(self):
        return self.replies.pop(0) if self.replies else b""


class AdvancingClock:
    def __init__(self, step=0.1):
        self.value = 0.0
        self.step = step

    def __call__(self):
        current = self.value
        self.value += self.step
        return current


class SerialLinkTests(unittest.TestCase):
    def test_command_must_be_four_digits(self):
        self.assertEqual(validate_command("0012"), "0012")
        for command in ("12", "0012\n", "ABCD", "0000"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    validate_command(command)

    def test_send_appends_newline_and_accepts_ack_after_debug_text(self):
        port = FakePort([b"debug\n", b"ACK\n"])
        notifier = SerialNotifier(port, "0012", timeout_seconds=2.0, clock=AdvancingClock())
        self.assertEqual(notifier.send(), "ACK")
        self.assertEqual(port.writes, [b"0012\n"])
        self.assertEqual(port.events[:2], ["reset", "write"])

    def test_send_reports_err_or_timeout_without_retrying(self):
        err_port = FakePort([b"ERR\n"])
        self.assertEqual(SerialNotifier(err_port, "0012", clock=AdvancingClock()).send(), "ERR")
        timeout_port = FakePort([])
        notifier = SerialNotifier(
            timeout_port, "0012", timeout_seconds=0.25, clock=AdvancingClock()
        )
        self.assertEqual(notifier.send(), "TIMEOUT")
        self.assertEqual(timeout_port.writes, [b"0012\n"])


if __name__ == "__main__":
    unittest.main()
