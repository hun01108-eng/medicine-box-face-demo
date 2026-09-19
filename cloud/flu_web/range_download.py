#!/usr/bin/env python3
"""为连接限速但支持 Range 的服务器提供并行分段下载。"""

import argparse
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


def download_part(url, referer, part_path, start, end, retries=3):
    expected = end - start + 1
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Range": f"bytes={start}-{end}",
        "Accept-Encoding": "identity",
    }
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=(15, 180))
            response.raise_for_status()
            if response.status_code != 206:
                raise RuntimeError(f"服务器未返回分段响应: {response.status_code}")
            if len(response.content) != expected:
                raise RuntimeError(f"分段大小错误: {len(response.content)}/{expected}")
            part_path.write_bytes(response.content)
            return part_path
        except Exception:
            if attempt == retries:
                raise
            time.sleep(attempt * 2)


def parallel_download(url, referer, output, workers=24):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    head = requests.head(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": referer},
        timeout=(15, 30),
    )
    head.raise_for_status()
    total = int(head.headers["Content-Length"])
    chunk = math.ceil(total / workers)
    parts = []

    print(f"并行下载 {output.name}：{total / 1024 / 1024:.2f} MB，{workers} 个分段", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for index in range(workers):
            start = index * chunk
            if start >= total:
                break
            end = min(total - 1, start + chunk - 1)
            part_path = output.with_suffix(output.suffix + f".part{index:02d}")
            parts.append(part_path)
            futures.append(pool.submit(download_part, url, referer, part_path, start, end))

        finished = 0
        for future in as_completed(futures):
            future.result()
            finished += 1
            print(f"已完成 {finished}/{len(futures)} 个分段", flush=True)

    with output.open("wb") as destination:
        for part_path in parts:
            destination.write(part_path.read_bytes())
    for part_path in parts:
        part_path.unlink()

    if output.stat().st_size != total or output.read_bytes()[:4] != b"%PDF":
        raise RuntimeError("合并后的 PDF 校验失败")
    print(f"下载完成：{output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="并行分段下载 PDF")
    parser.add_argument("url")
    parser.add_argument("referer")
    parser.add_argument("output")
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    parallel_download(args.url, args.referer, args.output, args.workers)
