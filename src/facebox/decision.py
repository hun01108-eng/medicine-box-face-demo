from dataclasses import dataclass
from statistics import median
from typing import Optional

from .types import FrameObservation, IdentityResult, IdentityStatus


@dataclass(frozen=True)
class DecisionConfig:
    similarity_threshold: float = 0.55
    required_matches: int = 3
    max_valid_frames: int = 5
    timeout_seconds: float = 3.0
    user_id: str = "elder_001"

    def __post_init__(self) -> None:
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0 and 1")
        if self.required_matches < 1:
            raise ValueError("required_matches must be positive")
        if self.max_valid_frames < self.required_matches:
            raise ValueError("max_valid_frames must be >= required_matches")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class MultiFrameDecision:
    def __init__(self, config: DecisionConfig):
        self.config = config
        self.reset()

    def reset(self) -> None:
        self._started_at: Optional[float] = None
        self._scores: list[float] = []
        self._matches = 0
        self._terminal: Optional[IdentityResult] = None

    def _result(self, status: IdentityStatus, now: float, *, reason: str = "") -> IdentityResult:
        confidence = median(self._scores) if self._scores else None
        latency = 0.0 if self._started_at is None else max(0.0, now - self._started_at)
        user_id = self.config.user_id if status == IdentityStatus.MATCHED else None
        return IdentityResult(status, user_id, confidence, reason, len(self._scores), self._matches, latency)

    def update(self, observation: FrameObservation) -> IdentityResult:
        if self._terminal is not None:
            return self._terminal
        now = observation.processed_at if observation.processed_at is not None else observation.timestamp
        if self._started_at is None and observation.face_count == 0:
            return self._result(IdentityStatus.WAITING, now, reason="no_face")
        if self._started_at is None:
            self._started_at = observation.timestamp

        if now - self._started_at >= self.config.timeout_seconds:
            self._terminal = self._result(IdentityStatus.RETRY, now, reason="timeout")
            return self._terminal
        if observation.face_count == 0:
            self._scores.clear()
            self._matches = 0
            return self._result(IdentityStatus.WAITING, now, reason="no_face")
        if observation.face_count > 1:
            self._terminal = self._result(IdentityStatus.RETRY, now, reason="multiple_faces")
            return self._terminal
        if not observation.quality_ok or observation.similarity is None:
            reason = observation.quality_reason or "poor_quality"
            return self._result(IdentityStatus.RETRY, now, reason=reason)

        score = max(-1.0, min(1.0, float(observation.similarity)))
        self._scores.append(score)
        if score >= self.config.similarity_threshold:
            self._matches += 1
        if self._matches >= self.config.required_matches:
            self._terminal = self._result(IdentityStatus.MATCHED, now)
        elif len(self._scores) >= self.config.max_valid_frames:
            self._terminal = self._result(IdentityStatus.UNKNOWN, now, reason="below_threshold")
        else:
            self._terminal = None
        return self._terminal or self._result(IdentityStatus.WAITING, now, reason="collecting_frames")
