#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查云端周风险API，并可选向Uno R3发送对应语音编号。

该脚本保留早期 ``--mode debug/real`` 的使用方式，但统一复用项目正式的
``FluApiClient`` 和 ``UnoNotifier``，不再维护过期接口或第二套串口协议。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


# 支持从仓库内直接运行，不要求事先安装 facebox 包。
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from flu_runtime.flu_api import FluApiClient  # noqa: E402
from flu_runtime.uno import UNO_BAUD, UnoNotifier  # noqa: E402


def check_flu_alert(arguments) -> int:
    """输出最新周风险；real模式额外发送0009、0010或0011。"""
    client = FluApiClient(
        arguments.api_base_url,
        arguments.timeout,
        arguments.cache,
    )
    status = client.fetch_latest(arguments.month, allow_cache=not arguments.no_cache)
    output = {"status": "FLU_RISK", **status.to_dict()}

    if arguments.mode == "real":
        state_path = arguments.state
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError):
            previous = {}
        signature = {
            "report_week": status.report_week,
            "risk_level": status.risk_level,
        }
        if not arguments.force and all(
            previous.get(key) == value for key, value in signature.items()
        ):
            print(json.dumps({"status": "FLU_AUDIO_SKIPPED", **signature}, ensure_ascii=False))
            return 0

        notifier = UnoNotifier(arguments.port, arguments.baud)
        try:
            audio_code, acknowledged = notifier.notify_risk(status.risk_level)
        finally:
            notifier.close()
        output.update({"audio_code": audio_code, "uno_ack": acknowledged})
        state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.", dir=state_path.parent, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(signature, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary_name, state_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查流感周风险API和R3语音编号")
    parser.add_argument("--mode", choices=("debug", "real"), default="debug")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--month", help="可选月份，例如2026-09")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--cache", type=Path, default=Path("data/flu_risk_cache.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--state", type=Path, default=Path("data/last_flu_audio.json"))
    parser.add_argument("--force", action="store_true", help="忽略状态并重复发送")
    parser.add_argument(
        "--port",
        default="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
        help="real模式使用的Uno稳定设备路径",
    )
    parser.add_argument("--baud", type=int, default=UNO_BAUD)
    arguments = parser.parse_args()

    try:
        return check_flu_alert(arguments)
    except (RuntimeError, ValueError, OSError) as error:
        print(json.dumps({"status": "ERROR", "reason": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
