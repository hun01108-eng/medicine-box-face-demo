#!/usr/bin/env python3
"""按发布日期月份批量导入中国疾控中心历史流感周报。"""

import argparse
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from database import ORIGINAL_REPORT_DIR, ensure_schema
from update_db_curl import (
    BASE_HEADERS,
    BASE_URL,
    download_pdf,
    extract_data_from_pdf,
    save_to_database,
)


def list_reports(report_month):
    response = requests.get(BASE_URL, headers=BASE_HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    month_token = report_month.replace("-", "")
    reports = []

    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        match = re.search(r"(\d{4})\s*年?\s*第\s*(\d+)\s*周", text)
        href = anchor["href"]
        if not match or f"/{month_token}/" not in href:
            continue
        reports.append(
            {
                "year": int(match.group(1)),
                "week": int(match.group(2)),
                "detail_url": urljoin(BASE_URL, href),
            }
        )

    reports.sort(key=lambda item: item["week"])
    return reports


def get_pdf_url(detail_url):
    response = requests.get(detail_url, headers=BASE_HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().split("?", 1)[0].endswith(".pdf"):
            return urljoin(detail_url, href)
    return None


def import_month(report_month):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", report_month):
        raise ValueError("月份格式必须为 YYYY-MM")

    ensure_schema()
    reports = list_reports(report_month)
    if not reports:
        print(f"未找到 {report_month} 发布的周报")
        return 0

    print(f"找到 {len(reports)} 份周报，开始导入……")
    imported = 0
    for index, report in enumerate(reports, start=1):
        detail_url = report["detail_url"]
        date_match = re.search(r"t(\d{8})_", detail_url)
        report_date = (
            datetime.strptime(date_match.group(1), "%Y%m%d").strftime("%Y-%m-%d")
            if date_match
            else None
        )
        report_week = f"{report['year']}-W{report['week']:02d}"
        print(f"\n[{index}/{len(reports)}] 导入 {report_week}（{report_date or '日期未知'}）")

        pdf_url = get_pdf_url(detail_url)
        if not pdf_url:
            print("未找到 PDF 地址，跳过")
            continue

        pdf_path = ORIGINAL_REPORT_DIR / f"{report_week}-流感周报.pdf"
        if not pdf_path.exists() and not download_pdf(pdf_url, detail_url, pdf_path):
            continue

        data = extract_data_from_pdf(pdf_path, report_date=report_date)
        if not data:
            continue
        data["report_week"] = report_week
        save_to_database(data, detail_url, pdf_url, pdf_path, report_date)
        imported += 1
        time.sleep(0.5)

    print(f"\n导入完成：成功 {imported}/{len(reports)} 份")
    return imported


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量导入历史流感周报")
    parser.add_argument("--month", required=True, help="发布日期月份，例如 2026-09")
    args = parser.parse_args()
    import_month(args.month)
