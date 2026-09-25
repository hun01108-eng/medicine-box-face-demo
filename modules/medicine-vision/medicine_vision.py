"""Minimal green/red inventory vision runtime for Raspberry Pi."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _require_bool(name: str, value) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")


def _require_int(name: str, value, minimum: int = 1) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _finite(name: str, value, minimum: float = 0.0) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(float(value)) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")


def validate_command(command: str) -> str:
    if not isinstance(command, str):
        raise TypeError("command must be a string")
    if len(command) != 4 or not command.isdigit() or command == "0000":
        raise ValueError("command must be four digits from 0001 to 9999")
    return command


@dataclass(frozen=True)
class ColorConfig:
    h_ranges: tuple[tuple[int, int], ...]
    s_min: int
    v_min: int
    v_max: int
    min_area: float
    max_area: float
    min_count: int

    def __post_init__(self) -> None:
        if not self.h_ranges:
            raise ValueError("at least one hue range is required")
        for lower, upper in self.h_ranges:
            _require_int("hue lower", lower, 0)
            _require_int("hue upper", upper, 0)
            if not lower <= upper <= 179:
                raise ValueError("hue range must be within 0..179")
        for name, value in (("s_min", self.s_min), ("v_min", self.v_min),
                            ("v_max", self.v_max)):
            _require_int(name, value, 0)
            if value > 255:
                raise ValueError(f"{name} must be <= 255")
        if self.v_min > self.v_max:
            raise ValueError("v_min must be <= v_max")
        _finite("min_area", self.min_area, 0.001)
        _finite("max_area", self.max_area, self.min_area)
        _require_int("min_count", self.min_count)


@dataclass(frozen=True)
class CameraConfig:
    width: int = 1280
    height: int = 720
    target_width: int = 1000
    warmup_seconds: float = 1.0

    def __post_init__(self) -> None:
        _require_int("camera.width", self.width)
        _require_int("camera.height", self.height)
        _require_int("camera.target_width", self.target_width)
        _finite("camera.warmup_seconds", self.warmup_seconds)


@dataclass(frozen=True)
class SerialConfig:
    enabled: bool = False
    protocol_confirmed: bool = False
    port: str = "/dev/serial0"
    baud: int = 9600
    timeout_seconds: float = 2.0
    alert_command: str = "0012"

    def __post_init__(self) -> None:
        _require_bool("serial.enabled", self.enabled)
        _require_bool("serial.protocol_confirmed", self.protocol_confirmed)
        if not isinstance(self.port, str) or not self.port.strip():
            raise TypeError("serial.port must be a non-empty string")
        _require_int("serial.baud", self.baud)
        _finite("serial.timeout_seconds", self.timeout_seconds, 0.001)
        validate_command(self.alert_command)
        if self.alert_command != "0012":
            raise ValueError("low-inventory alert command must remain 0012")
        if self.enabled and not self.protocol_confirmed:
            raise ValueError("R3 protocol 0012 must be confirmed before serial is enabled")


@dataclass(frozen=True)
class AppConfig:
    green: ColorConfig
    red: ColorConfig
    camera: CameraConfig = field(default_factory=CameraConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    confirm_frames: int = 5
    alert_interval_seconds: float = 10.0

    def __post_init__(self) -> None:
        _require_int("confirm_frames", self.confirm_frames)
        _finite("alert_interval_seconds", self.alert_interval_seconds, 0.001)


def _color_config(payload: dict, *, red: bool) -> ColorConfig:
    if red:
        ranges = ((payload.pop("h_low_min", 0), payload.pop("h_low_max", 10)),
                  (payload.pop("h_high_min", 170), payload.pop("h_high_max", 179)))
        defaults = (100, 60, 255, 200.0, 100000.0, 3)
    else:
        ranges = ((payload.pop("h_min", 50), payload.pop("h_max", 90)),)
        defaults = (50, 150, 255, 300.0, 40000.0, 3)
    s_min, v_min, v_max, min_area, max_area, min_count = defaults
    return ColorConfig(
        h_ranges=ranges,
        s_min=payload.pop("s_min", s_min),
        v_min=payload.pop("v_min", v_min),
        v_max=payload.pop("v_max", v_max),
        min_area=payload.pop("min_area", min_area),
        max_area=payload.pop("max_area", max_area),
        min_count=payload.pop("min_count", min_count),
        **payload,
    )


def load_config(path: Path) -> AppConfig:
    def reject_constant(value: str):
        raise ValueError(f"invalid numeric constant: {value}")

    payload = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(payload, dict):
        raise TypeError("configuration root must be an object")
    green_payload = payload.pop("green", {})
    red_payload = payload.pop("red", {})
    if not isinstance(green_payload, dict) or not isinstance(red_payload, dict):
        raise TypeError("green and red configuration must be objects")
    return AppConfig(
        green=_color_config(green_payload, red=False),
        red=_color_config(red_payload, red=True),
        camera=CameraConfig(**payload.pop("camera", {})),
        serial=SerialConfig(**payload.pop("serial", {})),
        **payload,
    )


@dataclass(frozen=True)
class ShortageState:
    green_low: bool
    red_low: bool
    should_alert: bool


class ShortageGate:
    def __init__(self, green_min: int, red_min: int, confirm_frames: int, interval: float):
        self.green_min = green_min
        self.red_min = red_min
        self.confirm_frames = confirm_frames
        self.interval = interval
        self.shortage_frames = 0
        self.last_alert: Optional[float] = None

    def update(self, green_count: int, red_count: int, now: float) -> ShortageState:
        green_low = green_count < self.green_min
        red_low = red_count < self.red_min
        self.shortage_frames = self.shortage_frames + 1 if green_low or red_low else 0
        confirmed = self.shortage_frames >= self.confirm_frames
        ready = self.last_alert is None or now - self.last_alert >= self.interval
        should_alert = confirmed and ready
        if should_alert:
            self.last_alert = now
        return ShortageState(green_low, red_low, should_alert)


class SerialNotifier:
    def __init__(self, port, command: str, timeout_seconds: float):
        self.port = port
        self.command = validate_command(command)
        self.timeout_seconds = timeout_seconds

    def send(self) -> str:
        self.port.reset_input_buffer()
        self.port.write((self.command + "\n").encode("ascii"))
        self.port.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            reply = self.port.readline().strip()
            if reply == b"ACK":
                return "ACK"
            if reply == b"ERR":
                return "ERR"
        return "TIMEOUT"


class Detector:
    def __init__(self, config: AppConfig):
        try:
            import cv2
            import numpy as np
        except ImportError as error:
            raise RuntimeError("OpenCV and NumPy are required") from error
        self.cv2, self.np, self.config = cv2, np, config
        self.green_bounds = self._bounds(config.green)
        self.red_bounds = self._bounds(config.red)
        self.green_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        self.green_join_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        self.red_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def _bounds(self, config: ColorConfig):
        return tuple(
            (self.np.array([lower, config.s_min, config.v_min]),
             self.np.array([upper, 255, config.v_max]))
            for lower, upper in config.h_ranges
        )

    def _mask(self, hsv, bounds):
        mask = self.cv2.inRange(hsv, *bounds[0])
        for lower, upper in bounds[1:]:
            mask = self.cv2.bitwise_or(mask, self.cv2.inRange(hsv, lower, upper))
        return mask

    def _boxes(self, mask, config: ColorConfig):
        contours, _ = self.cv2.findContours(
            mask, self.cv2.RETR_EXTERNAL, self.cv2.CHAIN_APPROX_SIMPLE
        )
        return tuple(
            self.cv2.boundingRect(contour)
            for contour in contours
            if config.min_area <= self.cv2.contourArea(contour) <= config.max_area
        )

    def process(self, frame_bgr):
        height, width = frame_bgr.shape[:2]
        target_width = self.config.camera.target_width
        target_height = max(1, round(height * target_width / width))
        interpolation = self.cv2.INTER_AREA if target_width <= width else self.cv2.INTER_LINEAR
        image = self.cv2.resize(frame_bgr, (target_width, target_height), interpolation=interpolation)
        hsv = self.cv2.cvtColor(image, self.cv2.COLOR_BGR2HSV)

        green_mask = self._mask(hsv, self.green_bounds)
        green_mask = self.cv2.morphologyEx(green_mask, self.cv2.MORPH_OPEN, self.green_kernel)
        green_mask = self.cv2.morphologyEx(green_mask, self.cv2.MORPH_CLOSE, self.green_kernel)
        # Reconnect regions split by a narrow highlight.
        green_mask = self.cv2.morphologyEx(
            green_mask, self.cv2.MORPH_CLOSE, self.green_join_kernel, iterations=2
        )
        red_mask = self._mask(hsv, self.red_bounds)
        red_mask = self.cv2.morphologyEx(red_mask, self.cv2.MORPH_OPEN, self.red_kernel)
        red_mask = self.cv2.morphologyEx(red_mask, self.cv2.MORPH_CLOSE, self.red_kernel)
        return image, self._boxes(green_mask, self.config.green), self._boxes(red_mask, self.config.red)

    def annotate(self, image, green_boxes, red_boxes, shortage):
        output = image.copy()
        for box, label, color in (
            *((box, "Green", (0, 255, 0)) for box in green_boxes),
            *((box, "Red", (0, 0, 255)) for box in red_boxes),
        ):
            x, y, width, height = box
            self.cv2.rectangle(output, (x, y), (x + width, y + height), color, 2)
            self.cv2.putText(output, label, (x, max(18, y - 5)),
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, self.cv2.LINE_AA)
        low = shortage.green_low or shortage.red_low
        color = (0, 0, 255) if low else (255, 255, 255)
        text = f"Green: {len(green_boxes)}/{self.config.green.min_count}  Red: {len(red_boxes)}/{self.config.red.min_count}"
        self.cv2.putText(output, text, (10, 30), self.cv2.FONT_HERSHEY_SIMPLEX,
                         0.7, color, 2, self.cv2.LINE_AA)
        if low:
            self.cv2.putText(output, "ALERT", (10, 85), self.cv2.FONT_HERSHEY_SIMPLEX,
                             1.6, (0, 0, 255), 3, self.cv2.LINE_AA)
        return output


class Camera:
    def __init__(self, config: CameraConfig):
        from picamera2 import Picamera2

        self.camera = Picamera2()
        try:
            settings = self.camera.create_preview_configuration(
                main={"size": (config.width, config.height), "format": "RGB888"},
                buffer_count=4,
            )
            self.camera.configure(settings)
            self.camera.start()
            if config.warmup_seconds:
                time.sleep(config.warmup_seconds)
        except BaseException:
            self.camera.close()
            raise

    def capture_bgr(self):
        # Picamera2 RGB888 arrays are byte-ordered B, G, R for OpenCV.
        return self.camera.capture_array("main")

    def close(self):
        try:
            self.camera.stop()
        finally:
            self.camera.close()


def _open_serial(config: SerialConfig):
    if not config.enabled:
        print("[串口] 已关闭；当前R3固件尚未支持0012")
        return None, None
    import serial

    port = serial.Serial(
        config.port,
        config.baud,
        timeout=min(0.25, config.timeout_seconds / 8),
    )
    return port, SerialNotifier(port, config.alert_command, config.timeout_seconds)


def run(config_path: Path) -> int:
    config = load_config(config_path)
    detector = Detector(config)
    cv2 = detector.cv2
    camera = None
    port = None
    try:
        camera = Camera(config.camera)
        port, notifier = _open_serial(config.serial)
        gate = ShortageGate(
            config.green.min_count,
            config.red.min_count,
            config.confirm_frames,
            config.alert_interval_seconds,
        )
        cv2.namedWindow("Medicine Detection")
        print("按 q 键退出实时检测窗口")
        while True:
            image, green_boxes, red_boxes = detector.process(camera.capture_bgr())
            shortage = gate.update(len(green_boxes), len(red_boxes), time.monotonic())
            if shortage.should_alert:
                counts = f"绿:{len(green_boxes)}/{config.green.min_count} 红:{len(red_boxes)}/{config.red.min_count}"
                if notifier is None:
                    print(f"[报警] 数量不足，仅显示未发送 ({counts})")
                else:
                    print(f"[报警] 0012发送结果={notifier.send()} ({counts})")
            cv2.imshow("Medicine Detection", detector.annotate(image, green_boxes, red_boxes, shortage))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        print("[退出] 收到 Ctrl+C")
    finally:
        try:
            if camera is not None:
                camera.close()
        finally:
            try:
                if port is not None:
                    port.close()
            finally:
                cv2.destroyAllWindows()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal green/red inventory vision")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    arguments = parser.parse_args()
    try:
        return run(arguments.config.resolve())
    except (FileNotFoundError, ImportError, RuntimeError, ValueError, OSError, TypeError) as error:
        print(json.dumps({"status": "ERROR", "reason": str(error)}, ensure_ascii=False))
        return 4


if __name__ == "__main__":
    sys.exit(main())
