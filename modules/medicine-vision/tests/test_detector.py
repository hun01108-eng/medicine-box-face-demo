import unittest

from medicine_vision.detector import filter_areas


class DetectorHelpersTests(unittest.TestCase):
    def test_area_filter_is_inclusive_and_preserves_indices(self):
        areas = [199.9, 200.0, 500.0, 100000.0, 100000.1]
        self.assertEqual(filter_areas(areas, 200.0, 100000.0), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
