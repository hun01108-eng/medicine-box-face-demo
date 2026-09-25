#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按月汇总周报并调用 DeepSeek 生成月度流感分析。"""

import argparse
import json
import os
import re
from datetime import datetime

from openai import OpenAI

from database import connect_db, ensure_schema


BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def validate_api_key(api_key):
    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("未设置环境变量 DEEPSEEK_API_KEY")
    try:
        api_key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            "DeepSeek API Key 中包含中文或全角字符，请只粘贴控制台中以 sk- 开头的密钥"
        ) from exc
    if not api_key.startswith("sk-"):
        raise RuntimeError("DeepSeek API Key 格式不正确，应当以 sk- 开头")
    return api_key


def get_available_months():
    ensure_schema()
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT DISTINCT report_month FROM flu_reports
               WHERE report_month IS NOT NULL ORDER BY report_month DESC"""
        ).fetchall()
    return [row["report_month"] for row in rows]


def get_monthly_weekly_data(report_month):
    ensure_schema()
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT report_week, report_date, south_positivity_rate,
                   north_positivity_rate, outbreak_count, south_trend,
                   north_trend, outbreak_status, h1n1_antigen_ratio,
                   h3n2_antigen_ratio, b_antigen_ratio,
                   h3n2_resistance_ratio, risk_level, risk_reason
            FROM flu_reports WHERE report_month = ?
            ORDER BY report_date, report_week
            """,
            (report_month,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_saved_monthly_report(report_month):
    ensure_schema()
    with connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM monthly_reports WHERE report_month = ?", (report_month,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["advice"] = json.loads(result.pop("advice_json"))
    return result


def build_prompt(report_month, weekly_data):
    payload = json.dumps(weekly_data, ensure_ascii=False, indent=2)
    return f"""
你是一位专业、谨慎的公共卫生信息分析助手。请根据 {report_month} 的周度流感监测数据生成月报。
数据中的周风险等级由本地确定性规则生成，只作为参考。不要编造缺失指标，也不要提供诊断或处方。

周度数据：
{payload}

只返回一个合法 JSON 对象，不要使用 Markdown 代码块：
{{
  "risk_level": "高或中或低",
  "summary": "80字以内的月度摘要",
  "full_report": "包含月内趋势、南北方差异、病毒型别和暴发情况的完整分析",
  "advice": ["建议1", "建议2", "建议3"]
}}
""".strip()


def parse_ai_json(content):
    """解析并严格校验模型输出，避免不完整内容进入正式月报。"""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI 返回内容为空")
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    result = json.loads(cleaned)
    required = {"risk_level", "summary", "full_report", "advice"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"AI 返回缺少字段: {', '.join(sorted(missing))}")
    if result["risk_level"] not in {"高", "中", "低"}:
        raise ValueError("AI 返回的 risk_level 必须是高、中或低")
    for field, label in (("summary", "summary"), ("full_report", "full_report")):
        if not isinstance(result[field], str) or not result[field].strip():
            raise ValueError(f"AI 返回的 {label} 必须是非空字符串")
        result[field] = result[field].strip()
    if not isinstance(result["advice"], list) or not 1 <= len(result["advice"]) <= 5:
        raise ValueError("AI 返回的 advice 必须是包含1至5项的数组")
    if any(not isinstance(item, str) or not item.strip() for item in result["advice"]):
        raise ValueError("AI 返回的每条 advice 必须是非空字符串")
    result["advice"] = [item.strip() for item in result["advice"]]
    return result


def save_monthly_report(report_month, result):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO monthly_reports (
                report_month, risk_level, summary, full_report,
                advice_json, model_name, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_month) DO UPDATE SET
                risk_level = excluded.risk_level,
                summary = excluded.summary,
                full_report = excluded.full_report,
                advice_json = excluded.advice_json,
                model_name = excluded.model_name,
                generated_at = excluded.generated_at
            """,
            (
                report_month, result["risk_level"], result["summary"],
                result["full_report"],
                json.dumps(result["advice"], ensure_ascii=False),
                MODEL_NAME, now,
            ),
        )
    return get_saved_monthly_report(report_month)


def generate_monthly_report(report_month, force=False):
    if not isinstance(report_month, str) or not re.fullmatch(
        r"\d{4}-(0[1-9]|1[0-2])", report_month
    ):
        raise ValueError("月份格式必须为 YYYY-MM")

    saved = get_saved_monthly_report(report_month)
    if saved and not force:
        return saved, False

    weekly_data = get_monthly_weekly_data(report_month)
    if not weekly_data:
        raise ValueError(f"{report_month} 没有可用于生成月报的周报数据")

    api_key = validate_api_key(os.getenv("DEEPSEEK_API_KEY"))

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": build_prompt(report_month, weekly_data)}],
        temperature=0.2,
        max_tokens=1200,
    )
    result = parse_ai_json(response.choices[0].message.content)
    return save_monthly_report(report_month, result), True


def main():
    parser = argparse.ArgumentParser(description="生成 AI 流感月报")
    parser.add_argument("--month", help="月份，格式 YYYY-MM；默认使用数据库中最新月份")
    parser.add_argument("--force", action="store_true", help="覆盖已经生成的月报")
    args = parser.parse_args()

    months = get_available_months()
    report_month = args.month or (months[0] if months else None)
    if not report_month:
        print("❌ 暂无周报数据，请先运行 update_db_curl.py")
        return 1

    try:
        report, generated = generate_monthly_report(report_month, force=args.force)
    except Exception as exc:
        print(f"❌ 月报生成失败: {exc}")
        return 1

    print(f"✅ {'已生成' if generated else '已读取'} {report_month} AI 月报")
    print(f"风险等级：{report['risk_level']}")
    print(report["full_report"])
    print("防护建议：")
    for item in report["advice"]:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
