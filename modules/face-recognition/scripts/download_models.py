#!/usr/bin/env python3
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "models"
    output.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in MODELS.items():
        target = output / name
        if target.is_file() and digest(target) == expected:
            print(f"OK {name}")
            continue
        request = Request(url, headers={"User-Agent": "medicine-box-face-demo"})
        with urlopen(request, timeout=120) as response:
            target.write_bytes(response.read())
        actual = digest(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"checksum mismatch: {name}")
        print(f"DOWNLOADED {name}")


if __name__ == "__main__":
    main()
