import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


def _normalize(values: Sequence[float]) -> list[float]:
    vector = [float(value) for value in values]
    if not vector or any(not math.isfinite(value) for value in vector):
        raise ValueError("face feature must contain finite values")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("face feature must have a finite non-zero length")
    return [value / norm for value in vector]


@dataclass(frozen=True)
class FaceProfile:
    user_id: str
    features: list[list[float]]

    def best_cosine_similarity(self, feature: Sequence[float]) -> float:
        candidate = _normalize(feature)
        if not self.features:
            raise ValueError("profile contains no face templates")
        if any(len(template) != len(candidate) for template in self.features):
            raise ValueError("feature dimensions do not match")
        similarities = [
            sum(a * b for a, b in zip(template, candidate))
            for template in self.features
        ]
        if any(not math.isfinite(score) for score in similarities):
            raise ValueError("profile contains a non-finite face template")
        return max(similarities)


class TemplateStore:
    """Stores embeddings only. It never stores enrollment images."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def save(self, user_id: str, features: Iterable[Sequence[float]]) -> None:
        normalized = [_normalize(feature) for feature in features]
        if not normalized:
            raise ValueError("at least one face template is required")
        dimension = len(normalized[0])
        if any(len(feature) != dimension for feature in normalized):
            raise ValueError("all face templates must have the same dimension")
        payload = {"schema_version": 1, "user_id": user_id, "features": normalized}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def load(self) -> FaceProfile:
        def reject_non_finite(value: str):
            raise ValueError(f"invalid numeric constant in profile: {value}")

        payload = json.loads(
            self.path.read_text(encoding="utf-8"),
            parse_constant=reject_non_finite,
        )
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported profile schema")
        user_id = payload.get("user_id")
        features = payload.get("features")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("profile user_id must be a non-empty string")
        if not isinstance(features, list):
            raise ValueError("profile features must be a list")
        return FaceProfile(user_id, [_normalize(feature) for feature in features])
