from typing import Optional

from .types import IdentityResult, IdentityStatus


class IdentitySession:
    """Prevents a later visitor from inheriting an earlier identity."""

    def __init__(self, absence_timeout_seconds: float = 2.0):
        self.absence_timeout_seconds = absence_timeout_seconds
        self._user_id: Optional[str] = None
        self._absence_started_at: Optional[float] = None

    def accept(self, result: IdentityResult, now: float) -> None:
        if result.status == IdentityStatus.MATCHED:
            self._user_id = result.user_id
            self._absence_started_at = None
        elif result.status in {IdentityStatus.UNKNOWN, IdentityStatus.ERROR}:
            self.clear()

    def observe_face(self) -> None:
        self._absence_started_at = None

    def observe_no_face(self, now: float) -> None:
        if self._absence_started_at is None:
            self._absence_started_at = now

    def current_user(self, now: float) -> Optional[str]:
        if self._absence_started_at is not None:
            if now - self._absence_started_at > self.absence_timeout_seconds:
                self.clear()
        return self._user_id

    def clear(self) -> None:
        self._user_id = None
        self._absence_started_at = None
