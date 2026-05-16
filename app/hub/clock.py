"""Clock helpers for deterministic hub-store tests."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Minimal time source used by the result store."""

    def utcnow(self) -> datetime:
        """Return the current UTC wall-clock time."""

        ...

    def monotonic(self) -> float:
        """Return the current monotonic time."""

        ...


class SystemClock:
    """Default wall-clock and monotonic time source."""

    def utcnow(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()
