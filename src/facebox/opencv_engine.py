import time
from pathlib import Path
from typing import Sequence

from .quality import QualityConfig, QualityMetrics, evaluate_quality
from .templates import FaceProfile
from .types import FrameObservation


class OpenCVFaceEngine:
    def __init__(
        self,
        detector_model: Path,
        recognizer_model: Path,
        quality_config: QualityConfig,
        score_threshold: float = 0.85,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
        use_clahe: bool = True,
    ):
        try:
            import cv2
            import numpy as np
        except ImportError as error:
            raise RuntimeError(
                "OpenCV/NumPy unavailable. Install Raspberry Pi dependencies from README.md."
            ) from error
        self.cv2 = cv2
        self.np = np
        self.quality_config = quality_config
        self.use_clahe = use_clahe
        if not Path(detector_model).is_file() or not Path(recognizer_model).is_file():
            raise FileNotFoundError("YuNet or SFace model is missing; run scripts/download_models.py")
        self.detector = cv2.FaceDetectorYN.create(
            str(detector_model), "", (320, 320), score_threshold, nms_threshold, top_k
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_model), "")
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def detect(self, frame):
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        return [] if faces is None else list(faces)

    def _metrics(self, frame, face) -> QualityMetrics:
        x, y, width, height = [int(value) for value in face[:4]]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(frame.shape[1], x + width), min(frame.shape[0], y + height)
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            return QualityMetrics(0, 0.0, 0.0)
        gray = self.cv2.cvtColor(roi, self.cv2.COLOR_BGR2GRAY)
        return QualityMetrics(width, float(gray.mean()), float(self.cv2.Laplacian(gray, self.cv2.CV_64F).var()))

    def _prepare_aligned(self, frame, face):
        aligned = self.recognizer.alignCrop(frame, self.np.asarray(face, dtype=self.np.float32))
        if not self.use_clahe:
            return aligned
        ycrcb = self.cv2.cvtColor(aligned, self.cv2.COLOR_BGR2YCrCb)
        ycrcb[:, :, 0] = self.clahe.apply(ycrcb[:, :, 0])
        return self.cv2.cvtColor(ycrcb, self.cv2.COLOR_YCrCb2BGR)

    def feature(self, frame, face) -> list[float]:
        aligned = self._prepare_aligned(frame, face)
        return self.recognizer.feature(aligned).flatten().astype(float).tolist()

    def observe(self, frame, profile: FaceProfile, timestamp: float | None = None) -> FrameObservation:
        now = time.monotonic() if timestamp is None else timestamp
        def observation(count, quality, score, reason=""):
            finished = time.monotonic() if timestamp is None else timestamp
            return FrameObservation(now, count, quality, score, reason, finished)
        faces = self.detect(frame)
        if len(faces) != 1:
            return observation(len(faces), False, None, "no_face" if not faces else "multiple_faces")
        quality = evaluate_quality(self._metrics(frame, faces[0]), self.quality_config)
        if not quality.ok:
            return observation(1, False, None, quality.reason)
        similarity = profile.best_cosine_similarity(self.feature(frame, faces[0]))
        return observation(1, True, similarity)

    def enrollment_feature(self, frame) -> tuple[list[float] | None, str]:
        faces = self.detect(frame)
        if len(faces) != 1:
            return None, "no_face" if not faces else "multiple_faces"
        quality = evaluate_quality(self._metrics(frame, faces[0]), self.quality_config)
        if not quality.ok:
            return None, quality.reason
        return self.feature(frame, faces[0]), "accepted"
