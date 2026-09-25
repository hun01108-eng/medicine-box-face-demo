import tempfile
import unittest
import os
import io
import json
from pathlib import Path

import database
from ai_flu_alert import parse_ai_json, validate_api_key


class FluWebTest(unittest.TestCase):
    def setUp(self):
        self.original_api_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database.ORIGINAL_REPORT_DIR = Path(self.temp_dir.name) / "reports" / "original"

        import app
        import update_db_curl

        app.ORIGINAL_REPORT_DIR = database.ORIGINAL_REPORT_DIR
        self.app_module = app
        self.update_module = update_db_curl
        self.token_file = Path(self.temp_dir.name) / "ingest-token"
        self.token_file.write_text("test-secret", encoding="utf-8")
        self.original_token_file = self.app_module.INGEST_TOKEN_FILE
        self.app_module.INGEST_TOKEN_FILE = self.token_file
        database.ensure_schema()
        self.client = app.app.test_client()

    def tearDown(self):
        self.app_module.INGEST_TOKEN_FILE = self.original_token_file
        self.temp_dir.cleanup()
        if self.original_api_key is not None:
            os.environ["DEEPSEEK_API_KEY"] = self.original_api_key

    def test_weekly_ingest_requires_token_and_stores_pdf(self):
        metadata = {
            "report_date": "2026-09-11",
            "detail_url": "https://ivdc.chinacdc.cn/detail.htm",
            "pdf_url": "https://ivdc.chinacdc.cn/report.pdf",
            "data": {
                "report_week": "2026-W36",
                "south_rate": 22.5,
                "north_rate": 11.0,
                "outbreak": 2,
                "south_trend": "上升",
                "north_trend": "低",
                "outbreak_status": "2起",
                "h1n1_ratio": None,
                "h3n2_ratio": 90.0,
                "b_ratio": None,
                "resistance_ratio": None,
            },
        }
        unauthorized = self.client.post(
            "/api/ingest/weekly",
            data={"metadata": json.dumps(metadata), "pdf": (io.BytesIO(b"%PDF-test"), "report.pdf")},
        )
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.post(
            "/api/ingest/weekly",
            headers={"Authorization": "Bearer test-secret"},
            data={"metadata": json.dumps(metadata), "pdf": (io.BytesIO(b"%PDF-test"), "report.pdf")},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["data"]["report_week"], "2026-W36")
        self.assertEqual(set(body), {"status", "data"})
        self.assertTrue((database.ORIGINAL_REPORT_DIR / "2026-W36-流感周报.pdf").is_file())

    def seed_week(self):
        pdf_path = database.ORIGINAL_REPORT_DIR / "week.pdf"
        pdf_path.write_bytes(b"%PDF-test")
        data = {
            "report_week": "2026-W36",
            "south_rate": 16.2,
            "north_rate": 8.1,
            "outbreak": 0,
            "south_trend": "上升",
            "north_trend": "低",
            "outbreak_status": "未报告",
            "h1n1_ratio": 10.0,
            "h3n2_ratio": 85.0,
            "b_ratio": 5.0,
            "resistance_ratio": 1.0,
        }
        self.update_module.save_to_database(
            data,
            "https://example.test/detail.htm",
            "https://example.test/week.pdf",
            pdf_path,
            "2026-09-03",
        )

    def test_empty_dashboard_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("暂无周报数据", response.get_data(as_text=True))

    def test_weekly_report_and_risk_render(self):
        self.seed_week()
        response = self.client.get("/?month=2026-09")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("2026-W36", html)
        self.assertIn("高风险", html)
        self.assertIn("查看原始 PDF", html)
        self.assertIn("南北方阳性率趋势", html)
        self.assertIn("每周暴发疫情数量", html)
        self.assertIn("周风险等级分布", html)

        api_response = self.client.get("/api/weekly?month=2026-09")
        data = api_response.get_json()["data"]
        self.assertEqual(data[0]["risk_level"], "高")

    def test_monthly_generation_requires_key(self):
        self.seed_week()
        response = self.client.post(
            "/api/monthly/generate", json={"month": "2026-09"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("DEEPSEEK_API_KEY", response.get_json()["message"])

    def test_monthly_generation_requires_valid_month(self):
        response = self.client.post("/api/monthly/generate", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("YYYY-MM", response.get_json()["message"])

    def test_api_key_rejects_non_ascii_text(self):
        with self.assertRaisesRegex(RuntimeError, "中文或全角字符"):
            validate_api_key("sk-这里粘贴密钥")

    def test_api_key_accepts_ascii_key(self):
        self.assertEqual(validate_api_key("  sk-test123  "), "sk-test123")

    def test_ai_result_rejects_empty_report_fields(self):
        content = json.dumps(
            {"risk_level": "中", "summary": "", "full_report": "分析", "advice": ["建议"]},
            ensure_ascii=False,
        )
        with self.assertRaisesRegex(ValueError, "summary"):
            parse_ai_json(content)

    def test_weekly_upsert_preserves_database_identity(self):
        self.seed_week()
        with database.connect_db() as conn:
            before = conn.execute(
                "SELECT id FROM flu_reports WHERE report_week = ?", ("2026-W36",)
            ).fetchone()["id"]
        self.seed_week()
        with database.connect_db() as conn:
            after = conn.execute(
                "SELECT id FROM flu_reports WHERE report_week = ?", ("2026-W36",)
            ).fetchone()["id"]
        self.assertEqual(before, after)

    def test_pdf_falls_back_to_official_url(self):
        self.seed_week()
        (database.ORIGINAL_REPORT_DIR / "week.pdf").unlink()
        with database.connect_db() as conn:
            conn.execute(
                """UPDATE flu_reports SET pdf_path = ?, pdf_url = ?
                   WHERE report_week = ?""",
                (
                    r"C:\\missing\\week.pdf",
                    "https://ivdc.chinacdc.cn/example/week.pdf",
                    "2026-W36",
                ),
            )
        response = self.client.get("/reports/original/2026-W36")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.location, "https://ivdc.chinacdc.cn/example/week.pdf"
        )


if __name__ == "__main__":
    unittest.main()
