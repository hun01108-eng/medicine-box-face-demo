"""Standalone color/contour detector for green and red targets."""

from dataclasses import dataclass
from typing import Sequence

from .config import AppConfig


@dataclass(frozen=True)
class DetectionResult:
    image: object
    green_count: int
    red_count: int
    green_boxes: tuple[tuple[int, int, int, int], ...]
    red_boxes: tuple[tuple[int, int, int, int], ...]
    green_mask: object
    red_mask: object
    green_mask_pixels: int
    red_mask_pixels: int
    green_contours: int
    red_contours: int


def filter_areas(areas: Sequence[float], minimum: float, maximum: float) -> list[int]:
    """Return indices whose contour area is inside the inclusive range."""
    return [index for index, area in enumerate(areas) if minimum <= area <= maximum]


class MedicineDetector:
    def __init__(self, config: AppConfig) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError as error:
            raise RuntimeError("OpenCV and NumPy are required") from error
        self.cv2 = cv2
        self.np = np
        self.config = config
        green = config.green
        red = config.red
        # Constant masks and kernels are built once instead of on every frame.
        self.green_lower = np.array([green.h_min, green.s_min, green.v_min])
        self.green_upper = np.array([green.h_max, 255, 255])
        self.red_low_lower = np.array([red.h_low_min, red.s_min, red.v_min])
        self.red_low_upper = np.array([red.h_low_max, 255, red.v_max])
        self.red_high_lower = np.array([red.h_high_min, red.s_min, red.v_min])
        self.red_high_upper = np.array([red.h_high_max, 255, red.v_max])
        self.green_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        self.green_join_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        self.red_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def _boxes(self, contours, minimum: float, maximum: float):
        areas = [float(self.cv2.contourArea(contour)) for contour in contours]
        accepted = filter_areas(areas, minimum, maximum)
        return tuple(self.cv2.boundingRect(contours[index]) for index in accepted)

    def process(self, frame_bgr) -> DetectionResult:
        original_height, original_width = frame_bgr.shape[:2]
        target_width = self.config.camera.target_width
        target_height = max(1, round(original_height * target_width / original_width))
        interpolation = self.cv2.INTER_AREA if target_width <= original_width else self.cv2.INTER_LINEAR
        image = self.cv2.resize(frame_bgr, (target_width, target_height), interpolation=interpolation)
        hsv = self.cv2.cvtColor(image, self.cv2.COLOR_BGR2HSV)

        green_mask = self.cv2.inRange(hsv, self.green_lower, self.green_upper)
        green_mask = self.cv2.morphologyEx(green_mask, self.cv2.MORPH_OPEN, self.green_kernel)
        green_mask = self.cv2.morphologyEx(green_mask, self.cv2.MORPH_CLOSE, self.green_kernel)
        # A second close reconnects capsule regions split by a narrow highlight.
        green_mask = self.cv2.morphologyEx(
            green_mask, self.cv2.MORPH_CLOSE, self.green_join_kernel, iterations=2
        )

        red_low = self.cv2.inRange(hsv, self.red_low_lower, self.red_low_upper)
        red_high = self.cv2.inRange(hsv, self.red_high_lower, self.red_high_upper)
        red_mask = self.cv2.bitwise_or(red_low, red_high)
        red_mask = self.cv2.morphologyEx(red_mask, self.cv2.MORPH_OPEN, self.red_kernel)
        red_mask = self.cv2.morphologyEx(red_mask, self.cv2.MORPH_CLOSE, self.red_kernel)

        green_contours, _ = self.cv2.findContours(
            green_mask, self.cv2.RETR_EXTERNAL, self.cv2.CHAIN_APPROX_SIMPLE
        )
        red_contours, _ = self.cv2.findContours(
            red_mask, self.cv2.RETR_EXTERNAL, self.cv2.CHAIN_APPROX_SIMPLE
        )
        green_boxes = self._boxes(
            green_contours, self.config.green.min_area, self.config.green.max_area
        )
        red_boxes = self._boxes(
            red_contours, self.config.red.min_area, self.config.red.max_area
        )
        return DetectionResult(
            image=image,
            green_count=len(green_boxes),
            red_count=len(red_boxes),
            green_boxes=green_boxes,
            red_boxes=red_boxes,
            green_mask=green_mask,
            red_mask=red_mask,
            green_mask_pixels=int(self.cv2.countNonZero(green_mask)),
            red_mask_pixels=int(self.cv2.countNonZero(red_mask)),
            green_contours=len(green_contours),
            red_contours=len(red_contours),
        )

    def annotate(self, result: DetectionResult, shortage) -> object:
        image = result.image.copy()
        for box in result.green_boxes:
            self._draw_box(image, box, "Green", (0, 255, 0))
        for box in result.red_boxes:
            self._draw_box(image, box, "Red", (0, 0, 255))
        shortage_active = shortage.green_low or shortage.red_low
        color = (0, 0, 255) if shortage_active else (255, 255, 255)
        text = (
            f"Green: {result.green_count}/{self.config.green.min_count}  "
            f"Red: {result.red_count}/{self.config.red.min_count}"
        )
        self.cv2.putText(image, text, (10, 30), self.cv2.FONT_HERSHEY_SIMPLEX,
                         0.7, color, 2, self.cv2.LINE_AA)
        if shortage_active:
            self.cv2.putText(image, "ALERT", (10, 85), self.cv2.FONT_HERSHEY_SIMPLEX,
                             1.6, (0, 0, 255), 3, self.cv2.LINE_AA)
        return image

    def _draw_box(self, image, box, label, color) -> None:
        x, y, width, height = box
        self.cv2.rectangle(image, (x, y), (x + width, y + height), color, 2)
        self.cv2.putText(image, label, (x, max(18, y - 5)),
                         self.cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, self.cv2.LINE_AA)
