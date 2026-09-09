"""Bounded hardware test. Never saves frames or enrolls a person."""
import json
import time
from pathlib import Path

import cv2
import numpy as np

from facebox.app import build_engine
from facebox.camera import Picamera2Camera
from facebox.config import load_config


root = Path(__file__).resolve().parents[1]
config = load_config(root / "config.json")
engine = build_engine(config, root)
# Exercise both ONNX graphs without generating a real person's embedding.
blank = np.zeros((480, 640, 3), dtype=np.uint8)
assert len(engine.detect(blank)) == 0
synthetic = engine.recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
assert synthetic.size == 128 and np.isfinite(synthetic).all()
camera = Picamera2Camera(640, 480)
try:
    frames = camera.frames()
    for _ in range(10):
        next(frames)
    start = time.monotonic()
    brightness = []
    for _ in range(30):
        frame = next(frames)
        assert frame.shape == (480, 640, 3) and frame.dtype == np.uint8
        brightness.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()))
    elapsed = time.monotonic() - start
    print(json.dumps({"opencv": cv2.__version__, "frame_shape": list(frame.shape),
                      "frames": 30, "capture_fps": 30 / elapsed,
                      "mean_brightness": sum(brightness) / len(brightness),
                      "synthetic_feature_dimensions": int(synthetic.size),
                      "images_saved": 0, "real_face_embeddings_created": 0}, indent=2))
finally:
    camera.close()
