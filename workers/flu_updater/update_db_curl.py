#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动下载流感周报 PDF（修正 PDF 链接拼接，添加月份目录）
流程：列表页 → 详情页 → 提取 PDF 链接 → 拼接正确 URL（含月份目录）→ 下载 → 解析 → 入库
用法：python update_db_curl.py
"""

import argparse
import json
import os
import re
import sys
import time
import random
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from database import ORIGINAL_REPORT_DIR, ensure_schema, save_weekly_report

BASE_URL = "https://ivdc.chinacdc.cn/cnic/zyzx/lgzb/"

# 基础请求头
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def get_latest_pdf_info():
    """从列表页和详情页提取最新 PDF 链接（正确拼接月份目录）"""
    print("🔍 正在访问流感周报列表页...")
    session = requests.Session()
    resp = session.get(BASE_URL, headers=BASE_HEADERS, timeout=30)
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        print(f"❌ 访问列表页失败: {resp.status_code}")
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    # 找最新周报链接
    week_link = None
    week_text = None
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if "第" in text and "周" in text and href.endswith(".htm"):
            week_link = href
            week_text = text
            break
    if not week_link:
        print("❌ 未找到周报链接")
        return None
    print(f"📄 找到最新: {week_text}")

    # 补全详情页 URL
    if week_link.startswith("./"):
        detail_url = BASE_URL + week_link[2:]
    elif week_link.startswith("/"):
        detail_url = "https://ivdc.chinacdc.cn" + week_link
    else:
        detail_url = BASE_URL + week_link
    print(f"   🔗 详情页: {detail_url}")

    # 模拟人类停顿
    time.sleep(random.uniform(2, 5))

    # 访问详情页
    detail_resp = session.get(detail_url, headers=BASE_HEADERS, timeout=30)
    detail_resp.encoding = "utf-8"
    if detail_resp.status_code != 200:
        print(f"❌ 访问详情页失败: {detail_resp.status_code}")
        return None
    detail_soup = BeautifulSoup(detail_resp.text, "html.parser")

    # 提取 PDF 链接（相对路径，如 "./P020260903555272906874.pdf"）
    pdf_link = None
    pdf_name = None
    for a in detail_soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if href.endswith(".pdf") and "周报" in text:
            pdf_link = href
            pdf_name = text
            break
    if not pdf_link:
        print("❌ 未找到 PDF 下载链接")
        return None

    # ========== 关键修复：正确拼接 PDF URL，保留月份目录 ==========
    # 示例：pdf_link = "./P020260903555272906874.pdf"
    #       detail_url = "https://.../lgzb/202609/t20260903_1839795.htm"
    # 目标：https://.../lgzb/202609/P020260903555272906874.pdf
    if pdf_link.startswith("./"):
        # 从 detail_url 中提取目录部分（去掉最后的文件名）
        # 例如 "https://.../lgzb/202609/t20260903_1839795.htm" -> "https://.../lgzb/202609"
        pdf_dir = detail_url.rsplit('/', 1)[0]   # 取最后一个 '/' 之前的部分
        pdf_url = pdf_dir + "/" + pdf_link[2:]   # 去掉 "./" 后拼接
    elif pdf_link.startswith("/"):
        pdf_url = "https://ivdc.chinacdc.cn" + pdf_link
    else:
        pdf_url = BASE_URL + pdf_link

    print(f"   📄 PDF名称: {pdf_name}")
    print(f"   🔗 PDF链接: {pdf_url}")

    return detail_url, pdf_url, pdf_name


def download_pdf(pdf_url, detail_url, output_path):
    """下载 PDF，携带 Referer 防盗链"""
    headers = BASE_HEADERS.copy()
    headers["Referer"] = detail_url
    print("⬇️  正在下载 PDF（携带 Referer）...")
    try:
        resp = requests.get(pdf_url, headers=headers, timeout=120)
        if resp.status_code == 200 and resp.content[:4] == b'%PDF':
            with open(output_path, "wb") as f:
                f.write(resp.content)
            print(f"   ✅ 下载成功！文件大小: {len(resp.content)//1024} KB")
            return True
        else:
            print(f"❌ 下载失败，状态码: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ 下载异常: {e}")
        return False


# ==================== 解析和入库（与 manual_import.py 一致）====================
def extract_data_from_pdf(pdf_path, report_date=None):
    if not os.path.exists(pdf_path):
        print(f"❌ 文件不存在: {pdf_path}")
        return None
    full_text = ""
    try:
        if pdfplumber is not None:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
        else:
            completed = subprocess.run(
                ["pdftotext", "-layout", str(pdf_path), "-"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            full_text = completed.stdout
    except Exception as e:
        print(f"❌ 读取 PDF 失败: {e}")
        return None
    if not full_text.strip():
        print("❌ 未从 PDF 中提取到任何文字")
        return None

    # 阳性率：表格中依次为南方、北方和合计，不能依赖某一周的固定阳性数。
    rates_match = re.search(
        r'阳性数\(%\)\s+\d+\(([\d.]+)%\)\s+\d+\(([\d.]+)%\)',
        full_text,
    )
    if rates_match:
        south_rate = float(rates_match.group(1))
        north_rate = float(rates_match.group(2))
    else:
        south_match = re.search(
            r'南方省份.*?阳性数\(%\).*?\d+\(([\d.]+)%\)', full_text, re.DOTALL
        )
        north_match = re.search(
            r'北方省份.*?阳性数\(%\).*?\d+\(([\d.]+)%\)', full_text, re.DOTALL
        )
        south_rate = float(south_match.group(1)) if south_match else None
        north_rate = float(north_match.group(1)) if north_match else None

    outbreak_match = re.search(r'全国(?:未报告|共报告\s*([\d]+)\s*起)\s*流感样病例暴发疫情', full_text)
    if outbreak_match:
        outbreak = 0 if '未报告' in outbreak_match.group(0) else int(outbreak_match.group(1))
    else:
        outbreak = None

    week_match = re.search(r'第\s*(\d+)\s*周', full_text)
    report_year = report_date[:4] if report_date else str(datetime.now().year)
    report_week = f"{report_year}-W{int(week_match.group(1)):02d}" if week_match else None

    # 趋势
    south_trend = "未知"
    if "南方省份流感病毒检测阳性率上升" in full_text:
        south_trend = "上升"
    elif "南方省份流感病毒检测阳性率下降" in full_text:
        south_trend = "下降"
    elif "南方省份流感活动低" in full_text:
        south_trend = "低"

    north_trend = "未知"
    if "北方省份流感病毒检测阳性率上升" in full_text:
        north_trend = "上升"
    elif "北方省份流感病毒检测阳性率下降" in full_text:
        north_trend = "下降"
    elif "北方省份流感活动低" in full_text:
        north_trend = "低"

    outbreak_status = "未知"
    if "全国未报告流感样病例暴发疫情" in full_text:
        outbreak_status = "未报告"
    else:
        m = re.search(r'全国共报告\s*(\d+)\s*起', full_text)
        if m:
            outbreak_status = f"{m.group(1)}起"

    # 型别占比
    h1n1_match = re.search(r'A\(H1N1\)pdm09\s*亚型流感病毒毒株中有\s*([\d.]+)%\s*[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]', full_text, re.DOTALL)
    h1n1_ratio = float(h1n1_match.group(1)) if h1n1_match else None

    h3n2_match = re.search(r'A\(H3N2\)\s*亚型流感病毒毒株中有\s*([\d.]+)%\s*[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]', full_text, re.DOTALL)
    h3n2_ratio = float(h3n2_match.group(1)) if h3n2_match else None

    b_match = re.search(r'B\(Victoria\)\s*系流感病毒毒株中有\s*([\d.]+)%\s*[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]', full_text, re.DOTALL)
    b_ratio = float(b_match.group(1)) if b_match else None

    resistance_match = re.search(r'(\d+)\s*/\s*(\d+)\s*[）)]?\s*对神经氨酸酶抑制剂敏感性降低', full_text, re.DOTALL)
    if resistance_match:
        num = int(resistance_match.group(1))
        den = int(resistance_match.group(2))
        resistance_ratio = (num / den) * 100
    else:
        resistance_ratio = None

    print(f"\n📊 解析结果:")
    print(f"   报告周次: {report_week}")
    print(f"   南方阳性率: {south_rate}%")
    print(f"   北方阳性率: {north_rate}%")
    print(f"   暴发疫情起数: {outbreak}")
    print(f"   南方趋势: {south_trend}")
    print(f"   北方趋势: {north_trend}")
    if h1n1_ratio:
        print(f"   H1N1抗原类似株: {h1n1_ratio}%")
    if h3n2_ratio:
        print(f"   H3N2抗原类似株: {h3n2_ratio}%")
    if b_ratio:
        print(f"   B/Victoria抗原类似株: {b_ratio}%")
    if resistance_ratio:
        print(f"   H3N2耐药性降低: {resistance_ratio:.1f}%")

    return {
        "report_week": report_week,
        "south_rate": south_rate,
        "north_rate": north_rate,
        "outbreak": outbreak,
        "south_trend": south_trend,
        "north_trend": north_trend,
        "outbreak_status": outbreak_status,
        "h1n1_ratio": h1n1_ratio,
        "h3n2_ratio": h3n2_ratio,
        "b_ratio": b_ratio,
        "resistance_ratio": resistance_ratio,
    }


def save_to_database(data, detail_url, pdf_url, pdf_path, report_date):
    risk_level, risk_reason = save_weekly_report(
        data, detail_url, pdf_url, pdf_path, report_date
    )
    print("数据已存入数据库: flu_data.db")
    print(f"   周风险等级: {risk_level}（{risk_reason}）")


def upload_to_cloud(data, detail_url, pdf_url, pdf_path, report_date, cloud_url, token_file):
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"上传令牌为空: {token_file}")
    metadata = {
        "data": data,
        "detail_url": detail_url,
        "pdf_url": pdf_url,
        "report_date": report_date,
    }
    endpoint = f"{cloud_url.rstrip('/')}/api/ingest/weekly"
    with open(pdf_path, "rb") as stream:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            data={"metadata": json.dumps(metadata, ensure_ascii=False)},
            files={"pdf": (os.path.basename(pdf_path), stream, "application/pdf")},
            timeout=180,
        )
    try:
        result = response.json()
    except ValueError as error:
        raise RuntimeError(f"云端返回非 JSON 响应: HTTP {response.status_code}") from error
    if response.status_code != 200 or result.get("status") != "success":
        raise RuntimeError(f"上传失败: HTTP {response.status_code}: {result.get('message', result)}")
    print(f"数据已上传云端: {endpoint}")
    print(f"   周风险等级: {result['data']['risk_level']}（{result['data']['risk_reason']}）")
    return result


def main():
    parser = argparse.ArgumentParser(description="下载、解析并更新最新流感周报")
    parser.add_argument("--cloud-url", default=os.getenv("FLU_CLOUD_URL"))
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(
            os.getenv("FLU_INGEST_TOKEN_FILE", "/home/pi/medicine-box/secrets/flu_ingest_token")
        ),
    )
    args = parser.parse_args()
    print("=" * 55)
    print("🩺 自动下载流感周报（修正链接拼接版）")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    info = get_latest_pdf_info()
    if not info:
        print("❌ 获取周报信息失败")
        return
    detail_url, pdf_url, pdf_name = info

    date_match = re.search(r't(\d{8})_', detail_url)
    report_date = None
    if date_match:
        report_date = datetime.strptime(date_match.group(1), "%Y%m%d").strftime("%Y-%m-%d")

    if pdf_name and "周报" in pdf_name:
        filename = re.sub(r'[<>:"/\\|?*]', "_", pdf_name)
        if not filename.endswith(".pdf"):
            filename += ".pdf"
    else:
        filename = pdf_url.split("/")[-1]
    ensure_schema()
    filepath = ORIGINAL_REPORT_DIR / filename

    if not download_pdf(pdf_url, detail_url, filepath):
        print("❌ 下载失败")
        return

    data = extract_data_from_pdf(filepath, report_date=report_date)
    if not data:
        print("❌ 解析失败")
        return

    if args.cloud_url:
        upload_to_cloud(
            data, detail_url, pdf_url, filepath, report_date,
            args.cloud_url, args.token_file,
        )
    else:
        save_to_database(data, detail_url, pdf_url, filepath, report_date)

    print("\n" + "=" * 55)
    print("✅ 数据更新完成!")
    print(f"   周次: {data['report_week']}")
    print(f"   南方阳性率: {data['south_rate']}%")
    print(f"   北方阳性率: {data['north_rate']}%")
    print(f"   暴发疫情: {data['outbreak']} 起")
    print("=" * 55)


if __name__ == "__main__":
    main()
