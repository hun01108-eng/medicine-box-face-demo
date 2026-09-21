"""树莓派各功能共用的 Arduino Uno R3 串口通信层。

人脸识别、红外检测和流感预警只提交业务事件；本模块统一完成事件到四位
音频编号的映射、进程互斥、发送以及 ACK/ERR 应答处理。
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


UNO_BAUD = 9600
UNO_ACK_TIMEOUT_SECONDS = 2.0

# 每周流感风险等级对应的语音编号。
RISK_AUDIO_COMMANDS = {
    "高": b"0009\n",
    "中": b"0010\n",
    "低": b"0011\n",
}

# 实时感知事件对应的语音编号；末尾换行是R3协议的帧结束标志。
EVENT_AUDIO_COMMANDS = {
    "person_passed": b"0004\n",
    "face_matched": b"0005\n",
    "face_failed": b"0006\n",
    "temperature_high": b"0007\n",
    "temperature_normal": b"0008\n",
}


class UnoNotifier:
    """向 Uno 发送数字音频指令，并在限定时间内等待确认。"""

    def __init__(
        self,
        port: str,
        baud: int = UNO_BAUD,
        ack_timeout: float = UNO_ACK_TIMEOUT_SECONDS,
        reset_delay: float = 2.0,
        serial_factory=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if ack_timeout <= 0:
            raise ValueError("ack_timeout must be positive")
        if serial_factory is None:
            import serial

            serial_factory = serial.Serial
        self.ack_timeout = ack_timeout
        self.serial = serial_factory(port, baud, timeout=ack_timeout)
        self.sleep = sleep
        # 树莓派上多个进程共用同一串口时，通过文件锁保证整组指令连续发送。
        self.lock_path = (
            Path(os.environ.get("FACEBOX_UNO_LOCK", "/tmp/facebox-uno.lock"))
            if os.name == "posix"
            else None
        )
        self.sleep(reset_delay)

    @contextmanager
    def _exclusive(self):
        """防止人脸、红外和流感进程的串口数据互相穿插。"""
        if self.lock_path is None:
            yield
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a", encoding="ascii") as handle:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _exchange(self, command: bytes) -> bool:
        """发送一条指令；收到 ACK 返回成功，ERR、空回复或超时返回失败。"""

        self.serial.write(command)
        self.serial.flush()
        deadline = time.monotonic() + self.ack_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                self.serial.timeout = remaining
            except (AttributeError, TypeError):
                pass
            reply = self.serial.readline().decode("ascii", errors="ignore").strip()
            if reply == "ACK":
                return True
            if reply == "ERR" or not reply:
                return False
            # 调试固件可能先输出诊断信息，此时继续等待正式 ACK/ERR。

    def notify(self, command: bytes) -> bool:
        """校验并发送一条以换行结束的纯数字指令。"""

        if not command.endswith(b"\n") or not command[:-1].decode("ascii").isdigit():
            raise ValueError("Uno command must be ASCII digits followed by a newline")
        with self._exclusive():
            return self._exchange(command)

    def notify_risk(self, risk_level: str) -> tuple[str, bool]:
        """发送高、中、低流感风险对应的音频指令。"""

        try:
            command = RISK_AUDIO_COMMANDS[risk_level]
        except KeyError as error:
            raise ValueError(f"unsupported flu risk level: {risk_level}") from error
        return command.decode("ascii").strip(), self.notify(command)

    def notify_event(self, event_name: str) -> tuple[str, bool]:
        """发送单个人脸或红外事件对应的音频指令。"""

        try:
            command = EVENT_AUDIO_COMMANDS[event_name]
        except KeyError as error:
            raise ValueError(f"unsupported Uno event: {event_name}") from error
        return command.decode("ascii").strip(), self.notify(command)

    def notify_event_sequence(
        self, event_names: list[str], gap_seconds: float = 0.0
    ) -> list[tuple[str, bool]]:
        """在一次互斥锁内按顺序发送多条事件指令。"""

        if gap_seconds < 0:
            raise ValueError("audio gap must not be negative")
        try:
            commands = [EVENT_AUDIO_COMMANDS[name] for name in event_names]
        except KeyError as error:
            raise ValueError(f"unsupported Uno event: {error.args[0]}") from error
        results = []
        with self._exclusive():
            for index, command in enumerate(commands):
                results.append(
                    (command.decode("ascii").strip(), self._exchange(command))
                )
                if index + 1 < len(commands):
                    self.sleep(gap_seconds)
        return results

    def close(self) -> None:
        self.serial.close()
