"""Bearer-token extraction from HTTP headers."""

from __future__ import annotations

from app.exceptions import AuthTokenInvalidError


def extract_bearer_token(headers: dict[str, str]) -> str:
    """Extract and return the bearer token from *headers*.

    Looks for ``Authorization: Bearer <token>`` (case-insensitive key).
    Raises :exc:`AuthTokenInvalidError` if the header is absent or malformed.
    """
    auth_value: str | None = None
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth_value = value
            break

    if auth_value is None:
        raise AuthTokenInvalidError("Missing Authorization header")

    parts = auth_value.split(None, 1)  # split on first whitespace
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthTokenInvalidError(
            "Authorization header must be 'Bearer <token>'"
        )

    token = parts[1].strip()
    if not token:
        raise AuthTokenInvalidError("Bearer token must not be empty")

    return token
