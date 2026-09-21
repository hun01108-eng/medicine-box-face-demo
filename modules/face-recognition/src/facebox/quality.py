from dataclasses import dataclass


@dataclass(frozen=True)
class QualityConfig:
    min_face_width: int = 100
    min_brightness: float = 45.0
    max_brightness: float = 220.0
    min_sharpness: float = 60.0


@dataclass(frozen=True)
class QualityMetrics:
    face_width: int
    brightness: float
    sharpness: float


@dataclass(frozen=True)
class QualityResult:
    ok: bool
    reason: str = ""


def evaluate_quality(metrics: QualityMetrics, config: QualityConfig) -> QualityResult:
    if metrics.face_width < config.min_face_width:
        return QualityResult(False, "face_too_small")
    if metrics.brightness < config.min_brightness:
        return QualityResult(False, "too_dark")
    if metrics.brightness > config.max_brightness:
        return QualityResult(False, "overexposed")
    if metrics.sharpness < config.min_sharpness:
        return QualityResult(False, "blurry")
    return QualityResult(True)
