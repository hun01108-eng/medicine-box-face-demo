import argparse
import json
import os
import time
from pathlib import Path

from .config import AppConfig
from .flu_api import FluApiClient, FluRiskStatus


def add_flu_arguments(command: argparse.ArgumentParser, monitor: bool = False) -> None:
    command.add_argument("--api-base-url", help="cloud website URL; overrides config and FLU_API_BASE_URL")
    command.add_argument("--month", help="optional report month, for example 2026-08")
    command.add_argument("--timeout", type=float, help="HTTP timeout in seconds")
    command.add_argument("--cache", type=Path, help="local risk cache path")
    command.add_argument("--no-cache", action="store_true", help="fail instead of using cached data")
    if monitor:
        command.add_argument("--interval", type=float, help="poll interval in seconds")
        command.add_argument("--emit-unchanged", action="store_true", help="print every successful poll")


def _client(arguments, config: AppConfig, root: Path) -> FluApiClient:
    base_url = arguments.api_base_url or os.environ.get("FLU_API_BASE_URL") or config.flu_api.base_url
    timeout = arguments.timeout if arguments.timeout is not None else config.flu_api.timeout_seconds
    cache = arguments.cache or Path(config.flu_api.cache_path)
    if not cache.is_absolute():
        cache = root / cache
    return FluApiClient(base_url, timeout, cache)


def _emit(status: FluRiskStatus) -> None:
    print(json.dumps({"status": "FLU_RISK", **status.to_dict()}, ensure_ascii=False, separators=(",", ":")), flush=True)


def run_flu_status(arguments, config: AppConfig, root: Path) -> int:
    status = _client(arguments, config, root).fetch_latest(arguments.month, not arguments.no_cache)
    _emit(status)
    return 0


def run_flu_monitor(arguments, config: AppConfig, root: Path) -> int:
    interval = arguments.interval if arguments.interval is not None else config.flu_api.poll_interval_seconds
    if interval <= 0:
        raise ValueError("interval must be positive")
    client = _client(arguments, config, root)
    previous = None
    previous_error = None
    while True:
        try:
            status = client.fetch_latest(arguments.month, not arguments.no_cache)
            signature = (status.report_week, status.risk_level, status.risk_reason, status.stale)
            if arguments.emit_unchanged or signature != previous:
                _emit(status)
            previous = signature
            previous_error = None
        except RuntimeError as error:
            message = str(error)
            if message != previous_error:
                print(json.dumps({"status": "ERROR", "reason": message}, ensure_ascii=False), flush=True)
            previous_error = message
        time.sleep(interval)
