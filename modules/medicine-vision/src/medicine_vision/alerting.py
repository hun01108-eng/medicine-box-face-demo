"""Deterministic low-inventory gating for medicine-vision counts."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ShortageState:
    green_low: bool
    red_low: bool
    confirmed_frames: int
    should_alert: bool
    reasons: tuple[str, ...]


class ShortageGate:
    """Confirm shortages across frames and rate-limit reminder events."""

    def __init__(
        self,
        green_min_count: int,
        red_min_count: int,
        confirm_frames: int,
        interval_seconds: float,
    ) -> None:
        if min(green_min_count, red_min_count, confirm_frames) < 1:
            raise ValueError("count thresholds and confirm_frames must be positive")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.green_min_count = green_min_count
        self.red_min_count = red_min_count
        self.confirm_frames = confirm_frames
        self.interval_seconds = interval_seconds
        self._shortage_frames = 0
        self._last_alert_at: Optional[float] = None

    def update(self, green_count: int, red_count: int, now: float) -> ShortageState:
        green_low = green_count < self.green_min_count
        red_low = red_count < self.red_min_count
        if green_low or red_low:
            self._shortage_frames += 1
        else:
            self._shortage_frames = 0

        confirmed = self._shortage_frames >= self.confirm_frames
        cooldown_ready = (
            self._last_alert_at is None
            or now - self._last_alert_at >= self.interval_seconds
        )
        should_alert = confirmed and cooldown_ready
        if should_alert:
            # Limit both successful sends and failed attempts to avoid serial spam.
            self._last_alert_at = now

        reasons = tuple(
            reason
            for active, reason in ((green_low, "green_low"), (red_low, "red_low"))
            if active
        )
        return ShortageState(
            green_low,
            red_low,
            self._shortage_frames,
            should_alert,
            reasons,
        )
