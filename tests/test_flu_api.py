import json
import tempfile
import unittest
from pathlib import Path

from facebox.config import load_config
from facebox.flu_api import FluApiClient


def response(level="中"):
    return {
        "status": "success",
        "data": [
            {"report_week": "2026-W33", "report_date": "2026-08-16", "risk_level": "低", "risk_reason": "older"},
            {"report_week": "2026-W34", "report_date": "2026-08-23", "risk_level": level, "risk_reason": "latest"},
        ],
    }


class FluApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_fetches_latest_week_and_writes_cache(self):
        calls = []

        def transport(url, timeout):
            calls.append((url, timeout))
            return response()

        cache = self.root / "risk.json"
        result = FluApiClient("http://example.test/", 3.0, cache, transport).fetch_latest("2026-08")
        self.assertEqual(calls, [("http://example.test/api/weekly?month=2026-08", 3.0)])
        self.assertEqual(result.report_week, "2026-W34")
        self.assertEqual(result.risk_level, "中")
        self.assertEqual(result.source, "cloud")
        self.assertEqual(json.loads(cache.read_text(encoding="utf-8"))["risk_reason"], "latest")

    def test_uses_stale_cache_when_cloud_is_unavailable(self):
        cache = self.root / "risk.json"
        client = FluApiClient("http://example.test", 3.0, cache, lambda _url, _timeout: response("high"))
        client.fetch_latest()
        client.transport = lambda _url, _timeout: (_ for _ in ()).throw(OSError("offline"))
        result = client.fetch_latest()
        self.assertEqual(result.risk_level, "高")
        self.assertEqual(result.source, "cache")
        self.assertTrue(result.stale)

    def test_rejects_bad_data_without_cache(self):
        client = FluApiClient(
            "http://example.test",
            3.0,
            self.root / "missing.json",
            lambda _url, _timeout: {"status": "success", "data": []},
        )
        with self.assertRaisesRegex(RuntimeError, "no weekly reports"):
            client.fetch_latest()

    def test_old_config_without_flu_section_uses_defaults(self):
        path = self.root / "config.json"
        path.write_text("{}", encoding="utf-8")
        self.assertEqual(load_config(path).flu_api.cache_path, "data/flu_risk_cache.json")
