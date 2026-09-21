import json
import tempfile
import unittest
from pathlib import Path

from facebox.templates import TemplateStore


class TemplateStoreTests(unittest.TestCase):
    def test_round_trip_preserves_normalized_templates_without_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "elder_001.json"
            store = TemplateStore(path)
            store.save("elder_001", [[3.0, 4.0], [0.0, 2.0]])
            profile = store.load()
            self.assertEqual(profile.user_id, "elder_001")
            self.assertAlmostEqual(profile.features[0][0], 0.6)
            self.assertAlmostEqual(profile.features[0][1], 0.8)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("image", payload)
            self.assertEqual(payload["schema_version"], 1)

    def test_rejects_zero_length_feature(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TemplateStore(Path(directory) / "profile.json")
            with self.assertRaises(ValueError):
                store.save("elder_001", [[0.0, 0.0]])

    def test_similarity_uses_best_registered_lighting_template(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TemplateStore(Path(directory) / "profile.json")
            store.save("elder_001", [[1.0, 0.0], [0.0, 1.0]])
            profile = store.load()
            self.assertAlmostEqual(profile.best_cosine_similarity([0.1, 0.9]), 0.9938837347)


if __name__ == "__main__":
    unittest.main()
