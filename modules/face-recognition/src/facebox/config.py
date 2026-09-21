import json
from dataclasses import dataclass, field
from pathlib import Path

from .decision import DecisionConfig
from .quality import QualityConfig


@dataclass(frozen=True)
class AppConfig:
    detector_model: str = "models/face_detection_yunet_2023mar.onnx"
    recognizer_model: str = "models/face_recognition_sface_2021dec.onnx"
    profile_path: str = "data/elder_001.json"
    camera_source: str = "opencv"
    camera_device: str = "/dev/video0"
    camera_width: int = 640
    camera_height: int = 480
    detector_score_threshold: float = 0.85
    detector_nms_threshold: float = 0.3
    detector_top_k: int = 5000
    use_clahe: bool = True
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)


def load_config(path: Path) -> AppConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    decision = DecisionConfig(**payload.pop("decision", {}))
    quality = QualityConfig(**payload.pop("quality", {}))
    return AppConfig(decision=decision, quality=quality, **payload)
