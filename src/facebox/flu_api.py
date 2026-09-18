import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


Transport = Callable[[str, float], dict]


@dataclass(frozen=True)
class FluRiskStatus:
    report_week: str
    report_date: str
    risk_level: str
    risk_reason: str
    fetched_at: str
    source: str = "cloud"
    stale: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _http_json(url: str, timeout: float) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "medicine-box-face-demo/0.2",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"flu API returned HTTP {response.status}")
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


class FluApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        cache_path: Path,
        transport: Transport | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("flu API base URL must not be empty")
        self.timeout = timeout
        self.cache_path = Path(cache_path)
        self.transport = transport or _http_json

    def fetch_latest(self, month: str | None = None, allow_cache: bool = True) -> FluRiskStatus:
        query = f"?{urlencode({'month': month})}" if month else ""
        url = f"{self.base_url}/api/weekly{query}"
        try:
            payload = self.transport(url, self.timeout)
            status = self._parse(payload)
            self._write_cache(status)
            return status
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            if allow_cache:
                cached = self._read_cache()
                if cached is not None:
                    return replace(cached, source="cache", stale=True)
            raise RuntimeError(f"failed to read flu risk from {url}: {error}") from error

    @staticmethod
    def _parse(payload: dict) -> FluRiskStatus:
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise ValueError("flu API returned an unsuccessful response")
        records = payload.get("data")
        if not isinstance(records, list) or not records:
            raise ValueError("flu API returned no weekly reports")
        records = [record for record in records if isinstance(record, dict)]
        if not records:
            raise ValueError("flu API returned invalid weekly reports")
        record = max(records, key=lambda item: (str(item.get("report_date", "")), str(item.get("report_week", ""))))
        level = str(record.get("risk_level", "")).strip()
        level = {"high": "高", "medium": "中", "low": "低"}.get(level.lower(), level)
        if level not in {"高", "中", "低"}:
            raise ValueError(f"unknown flu risk level: {level or 'empty'}")
        report_week = str(record.get("report_week", "")).strip()
        if not report_week:
            raise ValueError("weekly report is missing report_week")
        return FluRiskStatus(
            report_week=report_week,
            report_date=str(record.get("report_date", "")).strip(),
            risk_level=level,
            risk_reason=str(record.get("risk_reason", "")).strip(),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    def _write_cache(self, status: FluRiskStatus) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.cache_path.name}.",
            dir=self.cache_path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(status.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.cache_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _read_cache(self) -> FluRiskStatus | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return FluRiskStatus(**payload)
        except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError):
            return None
