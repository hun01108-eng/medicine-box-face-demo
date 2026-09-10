from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IdentityStatus(str, Enum):
    WAITING = "WAITING"
    MATCHED = "MATCHED"
    UNKNOWN = "UNKNOWN"
    RETRY = "UNKNOWN_RETRY"
    ERROR = "ERROR"


@dataclass(frozen=True)
class FrameObservation:
    timestamp: float
    face_count: int
    quality_ok: bool
    similarity: Optional[float]
    quality_reason: str = ""
    processed_at: Optional[float] = None


@dataclass(frozen=True)
class IdentityResult:
    status: IdentityStatus
    user_id: Optional[str] = None
    confidence: Optional[float] = None
    reason: str = ""
    valid_frames: int = 0
    matching_frames: int = 0
    latency_seconds: float = 0.0
