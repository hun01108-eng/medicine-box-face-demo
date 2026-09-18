"""Command-line runner for thermal passage detection and Uno notification."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .thermal import (
    THERMAL_BAUD,
    UNO_BAUD,
    ThermalEventLogger,
    ThermalPersonDetector,
    ThermalSerialReader,
    UnoNotifier,
    simulated_frame,
)


def run_thermal_monitor(arguments) -> int:
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

            event, _primary = detector.step(temperatures, ambient, timestamp)
            if event is None:
                continue
            acknowledged = notifier.notify_person() if notifier is not None else False
            logger.log(event, acknowledged)
            print(
                json.dumps(
                    {
                        "event": "PERSON_IN",
                        "count": event.detection_no,
                        "uno_ack": acknowledged,
                        "peak_temperature": round(event.peak_temperature, 2),
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
