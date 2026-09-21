"""Configuration model for the standalone medicine-vision module."""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .serial_link import validate_command


def _require_bool(name: str, value) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")


def _require_int(name: str, value, minimum: int = 1) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _finite_number(name: str, value, *, minimum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


@dataclass(frozen=True)
class GreenConfig:
    h_min: int = 50
    h_max: int = 90
    s_min: int = 50
    v_min: int = 150
    min_area: float = 300.0
    max_area: float = 40000.0
    min_count: int = 3

    def __post_init__(self) -> None:
        _validate_color("green", self.h_min, self.h_max, self.s_min, self.v_min,
                        self.min_area, self.max_area, self.min_count)


@dataclass(frozen=True)
class RedConfig:
    h_low_min: int = 0
    h_low_max: int = 10
    h_high_min: int = 170
    h_high_max: int = 179
    s_min: int = 100
    v_min: int = 60
    v_max: int = 255
    min_area: float = 200.0
    max_area: float = 100000.0
    min_count: int = 3

    def __post_init__(self) -> None:
        _validate_color("red-low", self.h_low_min, self.h_low_max, self.s_min,
                        self.v_min, self.min_area, self.max_area, self.min_count)
        for name, value in (("h_high_min", self.h_high_min),
                            ("h_high_max", self.h_high_max),
                            ("v_max", self.v_max)):
            _require_int(f"red.{name}", value, 0)
        if not 0 <= self.h_high_min <= self.h_high_max <= 179:
            raise ValueError("red-high hue range must be within 0..179")
        if not self.v_min <= self.v_max <= 255:
            raise ValueError("red value range is invalid")


def _validate_color(name, h_min, h_max, s_min, v_min, min_area, max_area, min_count):
    for field_name, value in (("h_min", h_min), ("h_max", h_max),
                              ("s_min", s_min), ("v_min", v_min)):
        _require_int(f"{name}.{field_name}", value, 0)
    if not 0 <= h_min <= h_max <= 179:
        raise ValueError(f"{name} hue range must be within 0..179")
    if s_min > 255 or v_min > 255:
        raise ValueError(f"{name} saturation/value thresholds must be within 0..255")
    _finite_number(f"{name}.min_area", min_area, minimum=0.0)
    _finite_number(f"{name}.max_area", max_area, minimum=0.0)
    if min_area <= 0:
        raise ValueError(f"{name}.min_area must be positive")
    if max_area < min_area:
        raise ValueError(f"{name}.max_area must be >= min_area")
    _require_int(f"{name}.min_count", min_count)


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
        _finite_number("camera.warmup_seconds", self.warmup_seconds, minimum=0.0)


@dataclass(frozen=True)
class SerialConfig:
    # Sending remains blocked until the R3 firmware and 012.mp3 are updated.
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
        _finite_number("serial.timeout_seconds", self.timeout_seconds, minimum=0.001)
        validate_command(self.alert_command)
        if self.alert_command != "0012":
            raise ValueError("medicine shortage alert_command must remain 0012")
        if self.enabled and not self.protocol_confirmed:
            raise ValueError(
                "serial cannot be enabled until R3 protocol 0012 and 012.mp3 are confirmed"
            )


@dataclass(frozen=True)
class AppConfig:
    green: GreenConfig = field(default_factory=GreenConfig)
    red: RedConfig = field(default_factory=RedConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    shortage_confirm_frames: int = 5
    alert_interval_seconds: float = 10.0
    debug: bool = False
    show_masks: bool = False

    def __post_init__(self) -> None:
        _require_int("shortage_confirm_frames", self.shortage_confirm_frames)
        _finite_number("alert_interval_seconds", self.alert_interval_seconds, minimum=0.001)
        _require_bool("debug", self.debug)
        _require_bool("show_masks", self.show_masks)


def load_config(path: Path) -> AppConfig:
    def reject_constant(value: str):
        raise ValueError(f"invalid numeric constant: {value}")

    payload = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(payload, dict):
        raise TypeError("configuration root must be an object")
    green = GreenConfig(**payload.pop("green", {}))
    red = RedConfig(**payload.pop("red", {}))
    camera = CameraConfig(**payload.pop("camera", {}))
    serial = SerialConfig(**payload.pop("serial", {}))
    return AppConfig(green=green, red=red, camera=camera, serial=serial, **payload)
