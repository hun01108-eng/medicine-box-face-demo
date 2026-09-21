import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from .config import AppConfig
from .flu_api import FluApiClient, FluRiskStatus
from .uno import UNO_BAUD, UnoNotifier


def add_flu_arguments(command: argparse.ArgumentParser, monitor: bool = False) -> None:
    command.add_argument("--api-base-url", help="cloud website URL; overrides config and FLU_API_BASE_URL")
    command.add_argument("--month", help="optional report month, for example 2026-08")
    command.add_argument("--timeout", type=float, help="HTTP timeout in seconds")
    command.add_argument("--cache", type=Path, help="local risk cache path")
    command.add_argument("--no-cache", action="store_true", help="fail instead of using cached data")
    if monitor:
        command.add_argument("--interval", type=float, help="poll interval in seconds")
        command.add_argument("--emit-unchanged", action="store_true", help="print every successful poll")


def add_flu_audio_arguments(command: argparse.ArgumentParser) -> None:
    add_flu_arguments(command)
    command.add_argument("--uno-port", required=True, help="stable Uno R3 serial device path")
    command.add_argument("--uno-baud", type=int, default=UNO_BAUD)
    command.add_argument("--state", type=Path, default=Path("data/last_flu_audio.json"))
    command.add_argument("--force", action="store_true", help="send even if this report was already announced")


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


def _write_audio_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def run_flu_audio(arguments, config: AppConfig, root: Path) -> int:
    status = _client(arguments, config, root).fetch_latest(arguments.month, not arguments.no_cache)
    state_path = arguments.state if arguments.state.is_absolute() else root / arguments.state
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        previous = {}
    signature = {"report_week": status.report_week, "risk_level": status.risk_level}
    if not arguments.force and all(previous.get(key) == value for key, value in signature.items()):
        print(json.dumps({"status": "FLU_AUDIO_SKIPPED", **signature}, ensure_ascii=False))
        return 0

    notifier = UnoNotifier(arguments.uno_port, arguments.uno_baud)
    try:
        audio_code, acknowledged = notifier.notify_risk(status.risk_level)
    finally:
        notifier.close()
    payload = {
        **signature,
        "audio_code": audio_code,
        "uno_ack": acknowledged,
        "source": status.source,
        "stale": status.stale,
        "sent_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_audio_state(state_path, payload)
    print(json.dumps({"status": "FLU_AUDIO_SENT", **payload}, ensure_ascii=False))
    return 0
