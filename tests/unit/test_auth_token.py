"""Unit tests for bearer token extraction (Phase A.5)."""

from __future__ import annotations

import pytest

from app.auth.token import extract_bearer_token
from app.exceptions import AuthTokenInvalidError


class TestExtractBearerToken:
    def test_extracts_token(self) -> None:
        headers = {"Authorization": "Bearer my-secret-token"}
        assert extract_bearer_token(headers) == "my-secret-token"

    def test_case_insensitive_header_key(self) -> None:
        headers = {"authorization": "Bearer my-secret-token"}
        assert extract_bearer_token(headers) == "my-secret-token"

    def test_mixed_case_header_key(self) -> None:
        headers = {"AUTHORIZATION": "Bearer tok"}
        assert extract_bearer_token(headers) == "tok"

    def test_missing_header_raises(self) -> None:
        with pytest.raises(AuthTokenInvalidError, match="Missing"):
            extract_bearer_token({})

    def test_no_authorization_header_raises(self) -> None:
        headers = {"Content-Type": "application/json"}
        with pytest.raises(AuthTokenInvalidError):
            extract_bearer_token(headers)

    def test_wrong_scheme_raises(self) -> None:
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        with pytest.raises(AuthTokenInvalidError, match="Bearer"):
            extract_bearer_token(headers)

    def test_empty_token_raises(self) -> None:
        headers = {"Authorization": "Bearer "}
        with pytest.raises(AuthTokenInvalidError):
            extract_bearer_token(headers)

    def test_only_bearer_keyword_raises(self) -> None:
        headers = {"Authorization": "Bearer"}
        with pytest.raises(AuthTokenInvalidError):
            extract_bearer_token(headers)

    def test_strips_whitespace_from_token(self) -> None:
        headers = {"Authorization": "Bearer  tok  "}
        # strip is applied after split
        assert extract_bearer_token(headers) == "tok"
