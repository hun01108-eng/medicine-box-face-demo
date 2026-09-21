import unittest

from medicine_vision.app import PicameraSource


class FakeCamera:
    def __init__(self, frame):
        self.frame = frame

    def capture_array(self, stream):
        if stream != "main":
            raise AssertionError(stream)
        return self.frame


class StopFailureCamera(FakeCamera):
    def __init__(self):
        super().__init__(None)
        self.closed = False

    def stop(self):
        raise RuntimeError("stop failed")

    def close(self):
        self.closed = True


class PicameraSourceTests(unittest.TestCase):
    def test_rgb888_buffer_is_passed_directly_to_opencv(self):
        frame = object()
        source = object.__new__(PicameraSource)
        source.camera = FakeCamera(frame)
        self.assertIs(source.capture_bgr(), frame)

    def test_close_releases_camera_even_when_stop_fails(self):
        camera = StopFailureCamera()
        source = object.__new__(PicameraSource)
        source.camera = camera
        with self.assertRaises(RuntimeError):
            source.close()
        self.assertTrue(camera.closed)


if __name__ == "__main__":
    unittest.main()
