"""流感周报、规则风险、AI月报和微信推送记录的SQLite持久化层。"""

from pathlib import Path
import os
import sqlite3
from datetime import datetime

from risk_rules import assess_weekly_risk


BASE_DIR = Path(os.getenv("FLU_DATA_DIR", Path(__file__).resolve().parent))
DB_PATH = BASE_DIR / "flu_data.db"
ORIGINAL_REPORT_DIR = BASE_DIR / "reports" / "original"


class ClosingConnection(sqlite3.Connection):
    """让 with 语句在提交或回滚后真正关闭 SQLite 连接。"""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect_db():
    """创建按字段名访问的短连接；退出with语句后自动关闭。"""
    conn = sqlite3.connect(DB_PATH, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    """初始化数据库，并为早期数据库补齐新增字段和表。"""
    ORIGINAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flu_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_week TEXT UNIQUE,
                south_positivity_rate REAL,
                north_positivity_rate REAL,
                outbreak_count INTEGER,
                south_trend TEXT,
                north_trend TEXT,
                outbreak_status TEXT,
                detail_url TEXT,
                updated_at TEXT,
                h1n1_antigen_ratio REAL,
                h3n2_antigen_ratio REAL,
                b_antigen_ratio REAL,
                h3n2_resistance_ratio REAL
            )
            """
        )
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(flu_reports)")
        }
        additions = {
            "report_date": "TEXT",
            "report_month": "TEXT",
            "pdf_url": "TEXT",
            "pdf_path": "TEXT",
            "risk_level": "TEXT",
            "risk_reason": "TEXT",
        }
        for name, column_type in additions.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE flu_reports ADD COLUMN {name} {column_type}"
                )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_month TEXT UNIQUE NOT NULL,
                risk_level TEXT NOT NULL,
                summary TEXT NOT NULL,
                full_report TEXT NOT NULL,
                advice_json TEXT NOT NULL,
                model_name TEXT,
                generated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wechat_push_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_week TEXT NOT NULL,
                openid TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                status TEXT NOT NULL,
                message_id TEXT,
                error_message TEXT,
                attempted_at TEXT NOT NULL,
                UNIQUE(report_week, openid)
            )
            """
        )


def save_weekly_report(data, detail_url, pdf_url, pdf_path, report_date):
    """计算确定性周风险，并按周次新增或更新一条完整记录。"""
    ensure_schema()
    risk_input = {
        "south_positivity_rate": data["south_rate"],
        "north_positivity_rate": data["north_rate"],
        "outbreak_count": data["outbreak"],
        "south_trend": data["south_trend"],
        "north_trend": data["north_trend"],
        "h3n2_resistance_ratio": data["resistance_ratio"],
    }
    risk_level, risk_reason = assess_weekly_risk(risk_input)
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO flu_reports (
                report_week, south_positivity_rate, north_positivity_rate, outbreak_count,
                south_trend, north_trend, outbreak_status, detail_url, updated_at,
                h1n1_antigen_ratio, h3n2_antigen_ratio, b_antigen_ratio,
                h3n2_resistance_ratio, report_date, report_month, pdf_url, pdf_path,
                risk_level, risk_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_week) DO UPDATE SET
                south_positivity_rate = excluded.south_positivity_rate,
                north_positivity_rate = excluded.north_positivity_rate,
                outbreak_count = excluded.outbreak_count,
                south_trend = excluded.south_trend,
                north_trend = excluded.north_trend,
                outbreak_status = excluded.outbreak_status,
                detail_url = excluded.detail_url,
                updated_at = excluded.updated_at,
                h1n1_antigen_ratio = excluded.h1n1_antigen_ratio,
                h3n2_antigen_ratio = excluded.h3n2_antigen_ratio,
                b_antigen_ratio = excluded.b_antigen_ratio,
                h3n2_resistance_ratio = excluded.h3n2_resistance_ratio,
                report_date = excluded.report_date,
                report_month = excluded.report_month,
                pdf_url = excluded.pdf_url,
                pdf_path = excluded.pdf_path,
                risk_level = excluded.risk_level,
                risk_reason = excluded.risk_reason
            """,
            (
                data["report_week"], data["south_rate"], data["north_rate"],
                data["outbreak"], data["south_trend"], data["north_trend"],
                data["outbreak_status"], detail_url,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data["h1n1_ratio"],
                data["h3n2_ratio"], data["b_ratio"], data["resistance_ratio"],
                report_date, report_date[:7] if report_date else None, pdf_url,
                str(pdf_path), risk_level, risk_reason,
            ),
        )
    return risk_level, risk_reason


def get_wechat_push(report_week, openid):
    """读取某一周向某一用户的最近推送结果。"""
    ensure_schema()
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM wechat_push_log WHERE report_week = ? AND openid = ?",
            (report_week, openid),
        ).fetchone()


def save_wechat_push(
    report_week,
    openid,
    risk_level,
    status,
    message_id=None,
    error_message=None,
):
    """保存推送结果；同一周和用户始终只保留一条状态记录。"""
    ensure_schema()
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO wechat_push_log (
                report_week, openid, risk_level, status,
                message_id, error_message, attempted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_week, openid) DO UPDATE SET
                risk_level = excluded.risk_level,
                status = excluded.status,
                message_id = excluded.message_id,
                error_message = excluded.error_message,
                attempted_at = excluded.attempted_at
            """,
            (
                report_week,
                openid,
                risk_level,
                status,
                str(message_id) if message_id is not None else None,
                error_message,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


ensure_schema()
