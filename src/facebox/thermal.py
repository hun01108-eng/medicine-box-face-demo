"""MLX90642 红外阵列的数据解析、人体检测、事件记录与模拟数据。

本模块只负责红外感知，不直接控制 Uno。检测结果由 ``thermal_app`` 交给
共用串口模块发送，从而使传感器算法可以脱离硬件独立测试。
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


# MLX90642-mini 输出 24×32 个测温点，每帧共 1544 字节。
ROWS, COLS = 24, 32
FRAME_LEN = 1544
HEADER = bytes((0x5A, 0x06, 0x02))
THERMAL_BAUD = 921600

# 阵列边缘测温波动较大，不参与人体热斑判定。
EDGE_MARGIN = 3


def parse_frame(buffer: bytes):
    """从串口缓存中解析一帧，返回温度矩阵、环境温度和已消费字节数。"""
    start = buffer.find(HEADER)
    if start < 0 or len(buffer) - start < FRAME_LEN:
        return None
    frame = buffer[start : start + FRAME_LEN]
    raw = frame[4 : 4 + ROWS * COLS * 2]
    temperatures = np.frombuffer(raw, dtype="<u2").astype(np.float32)
    temperatures = (temperatures / 100.0 - 40.0).reshape(ROWS, COLS)
    ambient = ((frame[1541] << 8) | frame[1540]) / 100.0 - 40.0
    return temperatures, ambient, start + FRAME_LEN


def clean_frame(frame: np.ndarray, salt: float = 4.0) -> np.ndarray:
    """用邻域中值抑制孤立高温噪点，并屏蔽不稳定的阵列边缘。"""
    source = np.asarray(frame, dtype=np.float32)
    if source.shape != (ROWS, COLS):
        raise ValueError(f"thermal frame must be {ROWS}x{COLS}")
    padded = np.pad(source, 1, mode="edge")
    neighbours = []
    for row_offset in (-1, 0, 1):
        for column_offset in (-1, 0, 1):
            if row_offset or column_offset:
                neighbours.append(
                    padded[
                        1 + row_offset : 1 + row_offset + ROWS,
                        1 + column_offset : 1 + column_offset + COLS,
                    ]
                )
    median = np.median(np.stack(neighbours), axis=0)
    cleaned = np.where((source - median) > salt, median, source).copy()
    cleaned[:EDGE_MARGIN, :] = -273.0
    cleaned[-EDGE_MARGIN:, :] = -273.0
    cleaned[:, :EDGE_MARGIN] = -273.0
    cleaned[:, -EDGE_MARGIN:] = -273.0
    return cleaned


@dataclass(frozen=True)
class PersonEvent:
    """一次经过事件的结构化结果，用于播报、终端输出和CSV存档。"""

    detection_no: int
    timestamp: float
    peak_temperature: float
    area: int
    row: int
    column: int
    ambient_temperature: float


class ThermalPersonDetector:
    """基于自适应背景差分的热斑检测器，每次经过只产生一个事件。

    状态依次为 WARMUP（建立背景）、IDLE（等待人员）和 ACTIVE（人员仍在）。
    持续出现达到确认时间才触发，持续消失达到清除时间后才允许下一次检测，
    可避免瞬时噪声和人员停留造成重复播报。
    """

    def __init__(
        self,
        delta: float = 4.0,
        min_temperature: float = 26.0,
        min_area: int = 2,
        max_area: int = 380,
        confirm_seconds: float = 0.6,
        clear_seconds: float = 1.5,
        cooldown_seconds: float = 3.0,
        offset: float = 4.0,
        background_alpha: float = 0.10,
        foreground_alpha: float = 0.002,
        warmup_frames: int = 6,
    ):
        self.delta = delta
        self.min_temperature = min_temperature
        self.min_area = min_area
        self.max_area = max_area
        self.confirm_seconds = confirm_seconds
        self.clear_seconds = clear_seconds
        self.cooldown_seconds = cooldown_seconds
        self.offset = offset
        self.background_alpha = background_alpha
        self.foreground_alpha = foreground_alpha
        self.warmup_frames = warmup_frames
        self.state = "WARMUP"
        self.background: Optional[np.ndarray] = None
        self._warmup: list[np.ndarray] = []
        self._present_since: Optional[float] = None
        self._absent_since: Optional[float] = None
        self._next_event_at = float("-inf")
        self.detections = 0

    @staticmethod
    def _blobs(mask: np.ndarray) -> list[dict]:
        """用八邻域连通搜索将高温像素合并为候选人体热斑。"""
        visited = np.zeros_like(mask, dtype=bool)
        blobs = []
        for row in range(ROWS):
            for column in range(COLS):
                if not mask[row, column] or visited[row, column]:
                    continue
                stack = [(row, column)]
                visited[row, column] = True
                cells = []
                while stack:
                    current_row, current_column = stack.pop()
                    cells.append((current_row, current_column))
                    for row_offset in (-1, 0, 1):
                        for column_offset in (-1, 0, 1):
                            if not (row_offset or column_offset):
                                continue
                            next_row = current_row + row_offset
                            next_column = current_column + column_offset
                            if (
                                0 <= next_row < ROWS
                                and 0 <= next_column < COLS
                                and mask[next_row, next_column]
                                and not visited[next_row, next_column]
                            ):
                                visited[next_row, next_column] = True
                                stack.append((next_row, next_column))
                rows, columns = zip(*cells)
                blob_mask = np.zeros_like(mask)
                blob_mask[rows, columns] = True
                blobs.append(
                    {
                        "mask": blob_mask,
                        "area": len(cells),
                    }
                )
        return blobs

    def step(
        self, frame: np.ndarray, ambient: float, timestamp: float
    ) -> tuple[Optional[PersonEvent], Optional[dict]]:
        frame = clean_frame(frame)
        if self.state == "WARMUP":
            # 多帧中值比单帧更能代表无人状态下的稳定背景。
            self._warmup.append(frame.copy())
            if len(self._warmup) >= self.warmup_frames:
                self.background = np.median(np.stack(self._warmup), axis=0)
                self._warmup.clear()
                self.state = "IDLE"
            return None, None

        assert self.background is not None
        # 像素必须同时高于动态背景和绝对温度下限，才视为前景。
        threshold = np.maximum(self.background + self.delta, self.min_temperature)
        candidates = [
            blob
            for blob in self._blobs(frame > threshold)
            if self.min_area <= blob["area"] <= self.max_area
        ]
        primary = None
        for blob in candidates:
            values = frame[blob["mask"]]
            blob["peak"] = float(np.max(values))
            rows, columns = np.where(blob["mask"])
            peak_index = int(np.argmax(values))
            blob["peak_r"] = int(rows[peak_index])
            blob["peak_c"] = int(columns[peak_index])
        if candidates:
            primary = max(candidates, key=lambda blob: blob["peak"])

        if primary is None:
            if self._absent_since is None:
                self._absent_since = timestamp
            self._present_since = None
        else:
            if self._present_since is None:
                self._present_since = timestamp
            self._absent_since = None

        event = None
        if self.state == "IDLE" and primary is not None:
            confirmed = timestamp - self._present_since >= self.confirm_seconds
            if confirmed and timestamp >= self._next_event_at:
                self.state = "ACTIVE"
                self._next_event_at = timestamp + self.cooldown_seconds
                self.detections += 1
                event = PersonEvent(
                    detection_no=self.detections,
                    timestamp=time.time(),
                    peak_temperature=primary["peak"] + self.offset,
                    area=primary["area"],
                    row=primary["peak_r"],
                    column=primary["peak_c"],
                    ambient_temperature=float(ambient),
                )
        elif self.state == "ACTIVE" and primary is None:
            if timestamp - self._absent_since >= self.clear_seconds:
                self.state = "IDLE"

        alpha = np.full(frame.shape, self.background_alpha)
        if primary is not None:
            # 人体区域慢速更新，防止静止人员迅速融入背景。
            alpha = np.where(
                primary["mask"], self.foreground_alpha, self.background_alpha
            )
        self.background += alpha * (frame - self.background)
        return event, primary


class ThermalSerialReader:
    """持续接收传感器字节流，并保留最近一帧完整温度数据。"""

    def __init__(self, port: str, baud: int = THERMAL_BAUD, serial_factory=None):
        if serial_factory is None:
            import serial

            serial_factory = serial.Serial
        self.serial = serial_factory(port, baud, timeout=0.08)
        self.buffer = bytearray()
        self.latest = None

    def read_once(self) -> bool:
        """读取并解析当前缓存；成功获得新帧时返回 True。"""
        chunk = self.serial.read(65536)
        if chunk:
            self.buffer.extend(chunk)
        if len(self.buffer) > FRAME_LEN * 4:
            # 丢弃过旧的不完整数据，限制长期运行时的缓存大小。
            self.buffer = self.buffer[-FRAME_LEN * 3 :]
        updated = False
        while True:
            parsed = parse_frame(bytes(self.buffer))
            if parsed is None:
                break
            temperatures, ambient, consumed = parsed
            del self.buffer[:consumed]
            self.latest = (temperatures, ambient, time.monotonic())
            updated = True
        return updated

    def close(self) -> None:
        self.serial.close()


class ThermalEventLogger:
    """将经过检测结果追加到CSV，便于展示和后续复核。"""

    FIELDS = (
        "time",
        "event",
        "count",
        "peak_temp_c",
        "area_px",
        "pos_row",
        "pos_col",
        "ambient_c",
        "uno_ack",
    )

    def __init__(self, path: Path):
        self.path = path

    def log(self, event: PersonEvent, acknowledged: bool) -> None:
        exists = self.path.is_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.timestamp)),
            "event": "PERSON_IN",
            "count": event.detection_no,
            "peak_temp_c": round(event.peak_temperature, 2),
            "area_px": event.area,
            "pos_row": event.row,
            "pos_col": event.column,
            "ambient_c": round(event.ambient_temperature, 2),
            "uno_ack": "YES" if acknowledged else "NO",
        }
        with self.path.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow(row)


def simulated_frame(timestamp: float) -> tuple[np.ndarray, float]:
    """生成周期性人体热斑，用于无传感器条件下的联调测试。"""
    ambient = 26.0
    frame = np.full((ROWS, COLS), ambient, dtype=np.float32)
    phase = timestamp % 8.0
    if phase < 3.0:
        rows, columns = np.mgrid[0:ROWS, 0:COLS]
        person = np.exp(
            -(((rows - 12.0) / 4.0) ** 2) - (((columns - 16.0) / 2.5) ** 2)
        )
        frame += 10.0 * person
    return frame, ambient
