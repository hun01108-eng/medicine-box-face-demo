import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import wechat_push
from wechat_test_push import build_message, load_config


class WechatPushTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_report_dir = database.ORIGINAL_REPORT_DIR
        database.DB_PATH = Path(self.temporary.name) / "test.db"
        database.ORIGINAL_REPORT_DIR = Path(self.temporary.name) / "reports"
        database.ensure_schema()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        database.ORIGINAL_REPORT_DIR = self.original_report_dir
        self.temporary.cleanup()

    def test_load_config_rejects_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wechat.json"
            path.write_text(
                json.dumps(
                    {
                        "app_id": "请替换为测试号AppID",
                        "app_secret": "secret",
                        "openid": "openid",
                        "template_id": "template",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "app_id"):
                load_config(path)

    def test_build_message_matches_template_fields(self):
        config = {
            "openid": "user-openid",
            "template_id": "template-id",
            "report_url": "https://example.com/report",
        }
        report = {
            "report_week": "2026-W39",
            "risk_level": "中",
            "risk_reason": "北方阳性率呈上升趋势",
            "updated_at": "2026-09-28 10:01:00",
        }
        message = build_message(config, report)
        self.assertEqual(message["touser"], "user-openid")
        self.assertEqual(message["data"]["risk_level"]["value"], "中风险")
        self.assertEqual(message["url"], "https://example.com/report")
        self.assertEqual(
            set(message["data"]),
            {"first", "report_week", "risk_level", "risk_reason", "updated_at", "remark"},
        )

    def test_production_push_is_idempotent(self):
        config = {
            "app_id": "app-id",
            "app_secret": "secret",
            "template_id": "template-id",
            "openids": ["openid-1"],
            "report_url": "https://example.com/report",
        }
        report = {
            "report_week": "2026-W39",
            "risk_level": "中",
            "risk_reason": "北方阳性率呈上升趋势",
        }
        with (
            patch.object(wechat_push, "config_from_environment", return_value=config),
            patch.object(wechat_push, "get_access_token", return_value="token"),
            patch.object(
                wechat_push,
                "send_template_message",
                return_value={"errcode": 0, "msgid": 123},
            ) as sender,
        ):
            first = wechat_push.push_weekly_report(report)
            second = wechat_push.push_weekly_report(report)
        self.assertEqual(first["results"][0]["status"], "success")
        self.assertEqual(second["results"][0]["status"], "skipped")
        self.assertEqual(sender.call_count, 1)
        self.assertNotIn("openid", first["results"][0])


if __name__ == "__main__":
    unittest.main()
