#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地读取最新周风险并测试微信公众号模板消息。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wechat_push import build_message, request_json, send_template_message


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "wechat_push.local.json"
REQUIRED_CONFIG = ("app_id", "app_secret", "openid", "template_id")


def load_config(path: Path) -> dict:
    """读取被Git忽略的本地测试配置，并拒绝尚未替换的占位值。"""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"未找到微信配置文件：{path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"微信配置文件不是合法JSON：{error}") from error

    missing = []
    for name in REQUIRED_CONFIG:
        value = config.get(name)
        if not isinstance(value, str) or not value.strip() or "请替换" in value:
            missing.append(name)
    if missing:
        raise RuntimeError(f"请先填写微信配置项：{', '.join(missing)}")

    config.setdefault("weekly_api_url", "http://127.0.0.1:5000/api/weekly")
    config.setdefault("report_url", "")
    return config


def get_latest_weekly_risk(config: dict) -> dict:
    """读取本地API按日期倒序返回的第一份周报。"""
    result = request_json(config["weekly_api_url"], "本地周报API")
    reports = result.get("data") or []
    if result.get("status") != "success" or not isinstance(reports, list) or not reports:
        raise RuntimeError("本地周报API中没有可推送的数据")
    return reports[0]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="测试微信公众号流感风险推送")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读取周报并显示消息内容，不调用微信接口",
    )
    arguments = parser.parse_args()

    try:
        config = load_config(arguments.config)
        report = get_latest_weekly_risk(config)
        if arguments.dry_run:
            result = {"status": "dry-run", "message": build_message(config, report)}
        else:
            wechat_result = send_template_message(config, report)
            result = {
                "status": "success",
                "report_week": report.get("report_week"),
                "risk_level": report.get("risk_level"),
                "msgid": wechat_result.get("msgid"),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
