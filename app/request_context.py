"""Request-scoped correlation helpers for reasoning-path work."""

from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import uuid4

_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def create_request_id() -> str:
    return str(uuid4())


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def set_request_id(request_id: str | None = None) -> tuple[Token[str | None], str]:
    value = request_id or create_request_id()
    token = _REQUEST_ID.set(value)
    return token, value


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def request_log_fields() -> dict[str, str]:
    request_id = get_request_id()
    if request_id is None:
        return {}
    return {"request_id": request_id}
