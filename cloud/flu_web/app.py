#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端流感风险信息服务。

本模块保存树莓派上传的周报与原始 PDF，并提供网页、查询 API 和 AI 月报。
"""

import json
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file
from urllib.parse import urlparse

from ai_flu_alert import generate_monthly_report, get_available_months
from database import ORIGINAL_REPORT_DIR, connect_db, ensure_schema, save_weekly_report


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
INGEST_TOKEN_FILE = Path(os.getenv("FLU_INGEST_TOKEN_FILE", "/etc/flu-web-ingest-token"))


def serialize_monthly(row):
    if not row:
        return None
    data = dict(row)
    data["advice"] = json.loads(data.pop("advice_json"))
    return data


def get_dashboard_data(report_month=None):
    ensure_schema()
    with connect_db() as conn:
        if not report_month:
            row = conn.execute(
                """SELECT report_month FROM flu_reports
                   WHERE report_month IS NOT NULL
                   ORDER BY report_month DESC LIMIT 1"""
            ).fetchone()
            report_month = row["report_month"] if row else None

        monthly = None
        weekly = []
        if report_month:
            monthly = conn.execute(
                "SELECT * FROM monthly_reports WHERE report_month = ?",
                (report_month,),
            ).fetchone()
            weekly = conn.execute(
                """
                SELECT report_week, report_date, south_positivity_rate,
                       north_positivity_rate, outbreak_count, south_trend,
                       north_trend, outbreak_status, risk_level, risk_reason,
                       pdf_path, pdf_url, detail_url, updated_at
                FROM flu_reports WHERE report_month = ?
                ORDER BY report_date DESC, report_week DESC
                """,
                (report_month,),
            ).fetchall()

    weekly_reports = [dict(row) for row in weekly]
    chart_reports = [
        {
            "report_week": item["report_week"],
            "south_positivity_rate": item["south_positivity_rate"],
            "north_positivity_rate": item["north_positivity_rate"],
            "outbreak_count": item["outbreak_count"],
            "risk_level": item["risk_level"],
        }
        for item in weekly_reports
    ]
    return {
        "selected_month": report_month,
        "months": get_available_months(),
        "monthly_report": serialize_monthly(monthly),
        "weekly_reports": weekly_reports,
        "chart_reports": chart_reports,
    }


@app.get("/")
def index():
    report_month = request.args.get("month")
    if report_month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", report_month):
        report_month = None
    return render_template("index.html", **get_dashboard_data(report_month))


@app.get("/api/dashboard")
def api_dashboard():
    return jsonify({"status": "success", "data": get_dashboard_data(request.args.get("month"))})


@app.get("/api/monthly/latest")
def api_monthly_latest():
    data = get_dashboard_data(request.args.get("month"))
    if not data["monthly_report"]:
        return jsonify({"status": "error", "message": "该月尚未生成 AI 月报"}), 404
    return jsonify({"status": "success", "data": data["monthly_report"]})


@app.get("/api/weekly")
def api_weekly():
    data = get_dashboard_data(request.args.get("month"))
    return jsonify({"status": "success", "data": data["weekly_reports"]})


def _ingest_authorized():
    try:
        expected = INGEST_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        app.logger.error("流感数据接收令牌不可用")
        return False
    supplied = request.headers.get("Authorization", "")
    if not supplied.startswith("Bearer ") or not expected:
        return False
    return secrets.compare_digest(supplied[7:], expected)


def _validate_ingest_metadata(metadata):
    if not isinstance(metadata, dict) or not isinstance(metadata.get("data"), dict):
        raise ValueError("metadata.data 格式不正确")
    data = metadata["data"]
    report_week = str(data.get("report_week", ""))
    report_date = str(metadata.get("report_date", ""))
    if not re.fullmatch(r"\d{4}-W\d{2}", report_week):
        raise ValueError("report_week 格式不正确")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ValueError("report_date 格式不正确")
    required = {
        "south_rate", "north_rate", "outbreak", "south_trend", "north_trend",
        "outbreak_status", "h1n1_ratio", "h3n2_ratio", "b_ratio", "resistance_ratio",
    }
    if not required.issubset(data):
        raise ValueError("周报字段不完整")
    return data, report_week, report_date


@app.post("/api/ingest/weekly")
def api_ingest_weekly():
    if not _ingest_authorized():
        return jsonify({"status": "error", "message": "未授权"}), 401
    try:
        metadata = json.loads(request.form.get("metadata", ""))
        data, report_week, report_date = _validate_ingest_metadata(metadata)
        uploaded = request.files.get("pdf")
        if uploaded is None:
            raise ValueError("缺少原始 PDF")
        header = uploaded.stream.read(4)
        uploaded.stream.seek(0)
        if header != b"%PDF":
            raise ValueError("上传文件不是 PDF")

        ORIGINAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        final_path = ORIGINAL_REPORT_DIR / f"{report_week}-流感周报.pdf"
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{report_week}.", suffix=".pdf", dir=ORIGINAL_REPORT_DIR
        )
        os.close(fd)
        try:
            uploaded.save(temporary_name)
            os.replace(temporary_name, final_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

        risk_level, risk_reason = save_weekly_report(
            data,
            str(metadata.get("detail_url", "")),
            str(metadata.get("pdf_url", "")),
            final_path,
            report_date,
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    report = {
        "report_week": report_week,
        "risk_level": risk_level,
        "risk_reason": risk_reason,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return jsonify({
        "status": "success",
        "data": report,
    })


@app.post("/api/monthly/generate")
def api_generate_monthly():
    payload = request.get_json(silent=True) or request.form
    report_month = payload.get("month")
    force = str(payload.get("force", "false")).lower() in {"1", "true", "yes"}
    try:
        report, generated = generate_monthly_report(report_month, force=force)
    except (ValueError, RuntimeError) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("生成月报失败")
        return jsonify({"status": "error", "message": f"AI 月报生成失败: {exc}"}), 502
    return jsonify({"status": "success", "generated": generated, "data": report})


@app.get("/reports/original/<report_week>")
def original_report(report_week):
    with connect_db() as conn:
        row = conn.execute(
            """SELECT pdf_path, pdf_url, detail_url
               FROM flu_reports WHERE report_week = ?""",
            (report_week,),
        ).fetchone()
    if not row:
        return jsonify({"status": "error", "message": "未找到原始周报"}), 404

    allowed_dir = ORIGINAL_REPORT_DIR.resolve()
    candidates = []
    stored_path = row["pdf_path"]
    if stored_path:
        candidates.append(Path(stored_path))
        portable_name = str(stored_path).replace("\\", "/").rsplit("/", 1)[-1]
        candidates.append(ORIGINAL_REPORT_DIR / portable_name)
    candidates.extend(sorted(ORIGINAL_REPORT_DIR.glob(f"*{report_week}*.pdf")))

    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if allowed_dir in path.parents and path.is_file():
            return send_file(path, mimetype="application/pdf", as_attachment=False)

    for url in (row["pdf_url"], row["detail_url"]):
        if url and urlparse(url).hostname == "ivdc.chinacdc.cn":
            return redirect(url, code=302)

    return jsonify({"status": "error", "message": "本地和官网均未找到原始周报"}), 404


@app.get("/api/flu/health")
def api_health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


if __name__ == "__main__":
    ensure_schema()
    debug = os.getenv("FLU_WEB_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(
        host=os.getenv("FLU_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("FLU_WEB_PORT", "5000")),
        debug=debug,
        use_reloader=debug,
    )
