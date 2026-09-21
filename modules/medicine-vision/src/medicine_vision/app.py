"""CLI and hardware lifecycle for the standalone medicine-vision module."""

import argparse
import json
import sys
import time
from pathlib import Path

from .alerting import ShortageGate
from .config import load_config
from .detector import MedicineDetector
from .serial_link import SerialNotifier, open_serial


class PicameraSource:
    def __init__(self, width: int, height: int, warmup_seconds: float) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()
        try:
            # An explicit three-channel format avoids depending on Picamera2 defaults.
            configuration = self.camera.create_preview_configuration(
                main={"size": (width, height), "format": "RGB888"},
                buffer_count=4,
            )
            self.camera.configure(configuration)
            self.camera.start()
            if warmup_seconds:
                time.sleep(warmup_seconds)
        except BaseException:
            self.camera.close()
            raise

    def capture_bgr(self):
        # Picamera2 RGB888 is byte-ordered as B, G, R for OpenCV arrays.
        return self.camera.capture_array("main")

    def close(self) -> None:
        try:
            self.camera.stop()
        finally:
            self.camera.close()


class ColorSampler:
    """Keep the latest rendered frame without module-level mutable globals."""

    def __init__(self, cv2) -> None:
        self.cv2 = cv2
        self.image = None
        self.hsv = None

    def update(self, image) -> None:
        self.image = image
        self.hsv = self.cv2.cvtColor(image, self.cv2.COLOR_BGR2HSV)

    def callback(self, event, x, y, _flags, _parameter) -> None:
        if event != self.cv2.EVENT_LBUTTONDOWN or self.image is None or self.hsv is None:
            return
        if not 0 <= y < self.image.shape[0] or not 0 <= x < self.image.shape[1]:
            return
        blue, green, red = (int(value) for value in self.image[y, x])
        hue, saturation, value = (int(item) for item in self.hsv[y, x])
        print(
            f"[取色] ({x},{y}) BGR=({blue},{green},{red}) "
            f"RGB=({red},{green},{blue}) HSV=({hue},{saturation},{value})"
        )


def _open_notifier(config):
    if not config.serial.enabled:
        print("[串口] 发送已关闭；当前R3固件尚未分配0012指令")
        return None, None
    try:
        port = open_serial(config.serial)
    except (ImportError, OSError) as error:
        print(f"[串口] 打开失败，自动降级为仅显示: {error}")
        return None, None
    print(f"[串口] 已打开 {config.serial.port} @ {config.serial.baud}")
    return port, SerialNotifier(
        port,
        config.serial.alert_command,
        timeout_seconds=config.serial.timeout_seconds,
    )


def _debug_summary(result, config) -> str:
    return (
        f"[GREEN] mask={result.green_mask_pixels} contours={result.green_contours} "
        f"count={result.green_count}/{config.green.min_count}\n"
        f"[RED] mask={result.red_mask_pixels} contours={result.red_contours} "
        f"count={result.red_count}/{config.red.min_count}"
    )


def run(config_path: Path, headless: bool = False) -> int:
    config = load_config(config_path)
    detector = MedicineDetector(config)
    cv2 = detector.cv2
    window_name = "Medicine Detection"
    last_debug_at = float("-inf")
    camera = None
    port = None
    try:
        camera = PicameraSource(
            config.camera.width,
            config.camera.height,
            config.camera.warmup_seconds,
        )
        gate = ShortageGate(
            config.green.min_count,
            config.red.min_count,
            config.shortage_confirm_frames,
            config.alert_interval_seconds,
        )
        port, notifier = _open_notifier(config)
        sampler = ColorSampler(cv2)
        if not headless:
            cv2.namedWindow(window_name)
            cv2.setMouseCallback(window_name, sampler.callback)
            print("按 q 键退出实时检测窗口")

        while True:
            frame = camera.capture_bgr()
            detection = detector.process(frame)
            now = time.monotonic()
            shortage = gate.update(detection.green_count, detection.red_count, now)

            if config.debug and now - last_debug_at >= 1.0:
                print(_debug_summary(detection, config))
                last_debug_at = now

            if shortage.should_alert:
                counts = f"绿:{detection.green_count}/{config.green.min_count} 红:{detection.red_count}/{config.red.min_count}"
                if notifier is None:
                    print(f"[报警] 数量不足，仅显示未发送 ({counts})")
                else:
                    reply = notifier.send()
                    print(f"[报警] 已发送 {config.serial.alert_command}，R3回复={reply} ({counts})")

            if not headless:
                annotated = detector.annotate(detection, shortage)
                sampler.update(detection.image)
                cv2.imshow(window_name, annotated)
                if config.show_masks:
                    cv2.imshow("mask_green", detection.green_mask)
                    cv2.imshow("mask_red", detection.red_mask)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("[退出] 收到 Ctrl+C")
    finally:
        try:
            if camera is not None:
                camera.close()
        finally:
            try:
                if port is not None:
                    port.close()
            finally:
                if not headless:
                    cv2.destroyAllWindows()
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Green/red medicine inventory vision")
    result.add_argument("--config", type=Path, default=Path("config.json"))
    result.add_argument("--headless", action="store_true", help="disable preview windows")
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        return run(arguments.config.resolve(), arguments.headless)
    except (FileNotFoundError, ImportError, RuntimeError, ValueError, OSError, TypeError) as error:
        print(json.dumps({"status": "ERROR", "reason": str(error)}, ensure_ascii=False))
        return 4


if __name__ == "__main__":
    sys.exit(main())
