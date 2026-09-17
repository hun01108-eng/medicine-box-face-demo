import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .camera import OpenCVCamera, Picamera2Camera
from .config import AppConfig, load_config
from .decision import MultiFrameDecision
from .metrics import summarize_latencies
from .templates import TemplateStore
from .types import FrameObservation, IdentityResult, IdentityStatus


def emit(result: IdentityResult) -> None:
    payload = asdict(result)
    payload["status"] = result.status.value
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def exit_code(status: IdentityStatus) -> int:
    return {IdentityStatus.MATCHED: 0, IdentityStatus.UNKNOWN: 2, IdentityStatus.RETRY: 3}.get(status, 4)


def simulate(case: str, config: AppConfig) -> int:
    engine = MultiFrameDecision(config.decision)
    if case == "known":
        inputs = [(0.0, 1, True, 0.68, ""), (0.2, 1, True, 0.64, ""), (0.4, 1, True, 0.66, "")]
    elif case == "unknown":
        inputs = [(index * 0.2, 1, True, score, "") for index, score in enumerate([0.22, 0.31, 0.36, 0.29, 0.40])]
    elif case == "dark":
        inputs = [(0.0, 1, False, None, "too_dark")]
    elif case == "multiple":
        inputs = [(0.0, 2, True, None, "multiple_faces")]
    else:
        inputs = [(0.0, 1, True, 0.60, ""), (3.1, 1, True, 0.60, "")]
    result = None
    for values in inputs:
        result = engine.update(FrameObservation(*values))
    assert result is not None
    emit(result)
    return exit_code(result.status)


def build_engine(config: AppConfig, root: Path):
    from .opencv_engine import OpenCVFaceEngine
    return OpenCVFaceEngine(
        root / config.detector_model,
        root / config.recognizer_model,
        config.quality,
        config.detector_score_threshold,
        config.detector_nms_threshold,
        config.detector_top_k,
        config.use_clahe,
    )


def enroll(images: Path, config: AppConfig, root: Path, minimum: int) -> int:
    import cv2
    engine = build_engine(config, root)
    features = []
    rejected = []
    supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    for path in sorted(images.iterdir()):
        if path.suffix.lower() not in supported:
            continue
        frame = cv2.imread(str(path))
        if frame is None:
            rejected.append((path.name, "decode_failed"))
            continue
        feature, reason = engine.enrollment_feature(frame)
        if feature is None:
            rejected.append((path.name, reason))
        else:
            features.append(feature)
    if len(features) < minimum:
        print(json.dumps({"status": "ERROR", "accepted": len(features), "minimum": minimum, "rejected": rejected}, ensure_ascii=False))
        return 4
    TemplateStore(root / config.profile_path).save(config.decision.user_id, features)
    print(json.dumps({"status": "ENROLLED", "user_id": config.decision.user_id, "templates": len(features), "rejected": rejected}, ensure_ascii=False))
    return 0


def open_camera(source: str, device: str, config: AppConfig):
    if source == "picamera2":
        return Picamera2Camera(config.camera_width, config.camera_height)
    parsed_device = int(device) if device.isdigit() else device
    return OpenCVCamera(parsed_device, config.camera_width, config.camera_height)


def run_live(source: str, device: str, display: bool, config: AppConfig, root: Path) -> int:
    if display:
        import cv2
    profile = TemplateStore(root / config.profile_path).load()
    engine = build_engine(config, root)
    decision = MultiFrameDecision(config.decision)
    camera = open_camera(source, device, config)
    try:
        for frame in camera.frames():
            observation = engine.observe(frame, profile)
            result = decision.update(observation)
            if display:
                label = f"{result.status.value} score={result.confidence if result.confidence is not None else '-'}"
                cv2.putText(frame, label, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.imshow("FaceBox Demo - q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    return 130
            terminal = result.status in {IdentityStatus.MATCHED, IdentityStatus.UNKNOWN}
            terminal = terminal or (result.status == IdentityStatus.RETRY and result.reason in {"multiple_faces", "timeout"})
            if terminal:
                emit(result)
                return exit_code(result.status)
    finally:
        camera.close()
        if display:
            cv2.destroyAllWindows()
    return 4


def benchmark_live(source: str, device: str, trials: int, config: AppConfig, root: Path) -> int:
    if trials < 1:
        raise ValueError("trials must be positive")
    profile = TemplateStore(root / config.profile_path).load()
    engine = build_engine(config, root)
    camera = open_camera(source, device, config)
    latencies = []
    statuses = {}
    decision = MultiFrameDecision(config.decision)
    try:
        for frame in camera.frames():
            result = decision.update(engine.observe(frame, profile))
            terminal = result.status in {IdentityStatus.MATCHED, IdentityStatus.UNKNOWN}
            terminal = terminal or (result.status == IdentityStatus.RETRY and result.reason in {"multiple_faces", "timeout"})
            if not terminal:
                continue
            latencies.append(result.latency_seconds)
            statuses[result.status.value] = statuses.get(result.status.value, 0) + 1
            if len(latencies) >= trials:
                break
            decision.reset()
    finally:
        camera.close()
    summary = summarize_latencies(latencies)
    summary["statuses"] = statuses
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["p95_within_3s"] else 5


def self_check(config: AppConfig, root: Path) -> int:
    checks = {}
    try:
        import cv2
        import numpy
        checks["opencv"] = cv2.__version__
        checks["numpy"] = numpy.__version__
        checks["face_detector_api"] = hasattr(cv2, "FaceDetectorYN")
        checks["face_recognizer_api"] = hasattr(cv2, "FaceRecognizerSF")
    except ImportError as error:
        checks["dependency_error"] = str(error)
    checks["detector_model"] = (root / config.detector_model).is_file()
    checks["recognizer_model"] = (root / config.recognizer_model).is_file()
    checks["profile"] = (root / config.profile_path).is_file()
    ready = all(checks.get(key, False) for key in ["face_detector_api", "face_recognizer_api", "detector_model", "recognizer_model", "profile"])
    print(json.dumps({"ready": ready, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ready else 4


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Single-person privacy-first medicine-box face selector")
    result.add_argument("--config", default="config.json")
    commands = result.add_subparsers(dest="command", required=True)
    simulation = commands.add_parser("simulate")
    simulation.add_argument("--case", choices=["known", "unknown", "dark", "multiple", "timeout"], required=True)
    enrollment = commands.add_parser("enroll")
    enrollment.add_argument("--images", type=Path, required=True)
    enrollment.add_argument("--minimum", type=int, default=5)
    live = commands.add_parser("run")
    live.add_argument("--source", choices=["picamera2", "opencv"], default="picamera2")
    live.add_argument("--device", default="0")
    live.add_argument("--display", action="store_true")
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--source", choices=["picamera2", "opencv"], default="picamera2")
    benchmark.add_argument("--device", default="0")
    benchmark.add_argument("--trials", type=int, default=20)
    commands.add_parser("self-check")
    thermal = commands.add_parser(
        "thermal-monitor",
        help="detect a passing person with MLX90642 and notify an Arduino Uno",
    )
    from .thermal_app import add_thermal_arguments

    add_thermal_arguments(thermal)
    return result


def main() -> int:
    arguments = parser().parse_args()
    config_path = Path(arguments.config).resolve()
    config = load_config(config_path)
    root = config_path.parent
    try:
        if arguments.command == "simulate":
            return simulate(arguments.case, config)
        if arguments.command == "enroll":
            return enroll(arguments.images, config, root, arguments.minimum)
        if arguments.command == "run":
            return run_live(arguments.source, arguments.device, arguments.display, config, root)
        if arguments.command == "benchmark":
            return benchmark_live(arguments.source, arguments.device, arguments.trials, config, root)
        if arguments.command == "thermal-monitor":
            from .thermal_app import run_thermal_monitor

            return run_thermal_monitor(arguments)
        return self_check(config, root)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
        print(json.dumps({"status": "ERROR", "reason": str(error)}, ensure_ascii=False))
        return 4


if __name__ == "__main__":
    sys.exit(main())
