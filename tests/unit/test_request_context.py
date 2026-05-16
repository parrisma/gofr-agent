"""Tests for request-scoped correlation helpers."""

from app.request_context import (
    get_request_id,
    request_log_fields,
    reset_request_id,
    set_request_id,
)


class TestRequestContext:
    def test_set_request_id_generates_value_and_reset_clears_it(self) -> None:
        token, request_id = set_request_id()
        try:
            assert request_id
            assert get_request_id() == request_id
            assert request_log_fields() == {"request_id": request_id}
        finally:
            reset_request_id(token)

        assert get_request_id() is None
        assert request_log_fields() == {}

    def test_set_request_id_uses_explicit_value(self) -> None:
        token, request_id = set_request_id("req-explicit")
        try:
            assert request_id == "req-explicit"
            assert get_request_id() == "req-explicit"
        finally:
            reset_request_id(token)
