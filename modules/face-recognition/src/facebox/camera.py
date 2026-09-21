from pathlib import Path
from typing import Iterator


class OpenCVCamera:
    def __init__(self, device: int | str, width: int, height: int):
        import cv2
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(device)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.capture.isOpened():
            raise RuntimeError(f"cannot open camera: {device}")

    def frames(self) -> Iterator[object]:
        while True:
            ok, frame = self.capture.read()
            if not ok:
                raise RuntimeError("camera frame read failed")
            yield frame

    def close(self) -> None:
        self.capture.release()


class Picamera2Camera:
    def __init__(self, width: int, height: int):
        from picamera2 import Picamera2
        self.camera = Picamera2()
        configuration = self.camera.create_preview_configuration(
            # libcamera RGB888 produces B,G,R bytes, as expected by OpenCV.
            main={"size": (width, height), "format": "RGB888"},
            buffer_count=4,
        )
        self.camera.configure(configuration)
        self.camera.start()

    def frames(self) -> Iterator[object]:
        while True:
            yield self.camera.capture_array("main")

    def close(self) -> None:
        self.camera.stop()
        self.camera.close()
