"""Small, testable wrapper for the Uno newline protocol."""

import time


def validate_command(command: str) -> str:
    if not isinstance(command, str):
        raise TypeError("command must be a string")
    if len(command) != 4 or not command.isdigit() or command == "0000":
        raise ValueError("command must be four digits from 0001 to 9999")
    return command


class SerialNotifier:
    """Send once, ignore debug lines, and wait to a monotonic deadline."""

    def __init__(
        self,
        port,
        command: str,
        timeout_seconds: float = 2.0,
        clock=time.monotonic,
    ) -> None:
        self.port = port
        self.command = validate_command(command)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    def send(self) -> str:
        # A late reply from an earlier attempt must not acknowledge this send.
        self.port.reset_input_buffer()
        self.port.write((self.command + "\n").encode("ascii"))
        self.port.flush()
        deadline = self.clock() + self.timeout_seconds
        while self.clock() < deadline:
            reply = self.port.readline().strip()
            if reply == b"ACK":
                return "ACK"
            if reply == b"ERR":
                return "ERR"
        return "TIMEOUT"


def open_serial(config):
    import serial

    return serial.Serial(
        config.port,
        config.baud,
        # Short reads let SerialNotifier enforce the overall ACK deadline.
        timeout=min(0.25, config.timeout_seconds / 8),
    )
