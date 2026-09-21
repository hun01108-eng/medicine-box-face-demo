"""红外经过检测的命令行入口，负责组织采集、判断、播报和记录流程。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .thermal import (
    THERMAL_BAUD,
    ThermalEventLogger,
    ThermalPersonDetector,
    ThermalSerialReader,
    simulated_frame,
)
from .uno import UNO_BAUD, UnoNotifier


def run_thermal_monitor(arguments) -> int:
    """运行红外监测主循环，直到用户中断程序。"""

    if arguments.audio_gap_seconds < 0:
        raise ValueError("--audio-gap-seconds must not be negative")
    detector = ThermalPersonDetector(
        delta=arguments.delta,
        min_temperature=arguments.min_temperature,
        min_area=arguments.min_area,
        max_area=arguments.max_area,
        confirm_seconds=arguments.confirm_seconds,
        clear_seconds=arguments.clear_seconds,
        cooldown_seconds=arguments.cooldown_seconds,
        offset=0.0 if arguments.simulate else arguments.offset,
    )
    logger = ThermalEventLogger(Path(arguments.log))
    reader = None
    notifier = None
    # 模拟模式不打开红外串口，可在普通电脑上验证完整检测流程。
    if not arguments.simulate:
        if not arguments.thermal_port:
            raise ValueError("--thermal-port is required unless --simulate is used")
        reader = ThermalSerialReader(arguments.thermal_port, arguments.thermal_baud)
    if arguments.uno_port:
        notifier = UnoNotifier(arguments.uno_port, arguments.uno_baud)

    started = time.monotonic()
    print(
        json.dumps(
            {
                "status": "THERMAL_MONITOR_STARTED",
                "thermal_port": arguments.thermal_port,
                "uno_port": arguments.uno_port,
                "simulation": arguments.simulate,
            },
            ensure_ascii=False,
        )
    )
    try:
        while True:
            # 实机与模拟数据最终统一为温度矩阵、环境温度和单调时钟时间戳。
            if reader is None:
                now = time.monotonic()
                temperatures, ambient = simulated_frame(now - started)
                timestamp = now
                time.sleep(0.1)
            else:
                reader.read_once()
                if reader.latest is None:
                    time.sleep(0.02)
                    continue
                temperatures, ambient, timestamp = reader.latest
                reader.latest = None

            event, _ = detector.step(temperatures, ambient, timestamp)
            if event is None:
                continue

            # 校准后的峰值温度仅用于分级播报，不参与人员存在判定。
            temperature_status = (
                "high"
                if event.peak_temperature >= arguments.high_temperature
                else "normal"
            )
            audio_results = []
            if notifier is not None:
                # 先提示有人经过，再播报本次体温分类，两条指令之间保留音频间隔。
                audio_results = notifier.notify_event_sequence(
                    ["person_passed", f"temperature_{temperature_status}"],
                    arguments.audio_gap_seconds,
                )
            acknowledged = bool(audio_results) and all(
                acknowledged for _code, acknowledged in audio_results
            )
            logger.log(event, acknowledged)
            print(
                json.dumps(
                    {
                        "event": "PERSON_IN",
                        "count": event.detection_no,
                        "uno_ack": acknowledged,
                        "audio_codes": [code for code, _ack in audio_results],
                        "peak_temperature": round(event.peak_temperature, 2),
                        "temperature_status": temperature_status,
                        "high_temperature_threshold": arguments.high_temperature,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    except KeyboardInterrupt:
        return 130
    finally:
        if reader is not None:
            reader.close()
        if notifier is not None:
            notifier.close()


def add_thermal_arguments(parser) -> None:
    """注册红外监测的硬件端口、检测阈值和播报参数。"""

    parser.add_argument("--thermal-port")
    parser.add_argument("--thermal-baud", type=int, default=THERMAL_BAUD)
    parser.add_argument("--uno-port")
    parser.add_argument("--uno-baud", type=int, default=UNO_BAUD)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--log", default="logs/person_events.csv")
    parser.add_argument("--delta", type=float, default=4.0)
    parser.add_argument("--min-temperature", type=float, default=26.0)
    parser.add_argument("--min-area", type=int, default=2)
    parser.add_argument("--max-area", type=int, default=380)
    parser.add_argument("--confirm-seconds", type=float, default=0.6)
    parser.add_argument("--clear-seconds", type=float, default=1.5)
    parser.add_argument("--cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--offset", type=float, default=4.0)
    parser.add_argument("--high-temperature", type=float, default=37.3)
    parser.add_argument("--audio-gap-seconds", type=float, default=2.0)
