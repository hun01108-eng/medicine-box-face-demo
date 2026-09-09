"""Capture-only test, independent of OpenCV installation; no image writes."""
import json
import time
from facebox.camera import Picamera2Camera

camera = Picamera2Camera(640, 480)
try:
    frames = camera.frames()
    for _ in range(10):
        next(frames)
    start = time.monotonic()
    for _ in range(30):
        frame = next(frames)
        assert frame.shape == (480, 640, 3)
    print(json.dumps({"frames": 30, "shape": list(frame.shape),
                      "capture_fps": 30 / (time.monotonic() - start),
                      "images_saved": 0}))
finally:
    camera.close()
