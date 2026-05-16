"""Tests for hub error codes and MCP-safe mapping."""

from __future__ import annotations

from mcp.types import INVALID_PARAMS

from app.hub.errors import ALL_HUB_ERROR_CODES, HUB_MALFORMED_REQUEST, hub_mcp_error


class TestHubErrorCodes:
    def test_error_code_set_matches_spec(self) -> None:
        assert ALL_HUB_ERROR_CODES == (
            "hub.invalid_protocol_version",
            "hub.unauthorised",
            "hub.unregistered_service",
            "hub.registration_required",
            "hub.result_type_not_allowed",
            "hub.unknown_result",
            "hub.expired_result",
            "hub.oversized_result",
            "hub.capacity_exceeded",
            "hub.malformed_request",
            "hub.schema_mismatch",
        )

    def test_error_codes_are_unique(self) -> None:
        assert len(ALL_HUB_ERROR_CODES) == len(set(ALL_HUB_ERROR_CODES))

    def test_hub_mcp_error_uses_invalid_params_with_hub_code_data(self) -> None:
        error = hub_mcp_error(HUB_MALFORMED_REQUEST, "payload must be JSON-serialisable")

        assert error.error.code == INVALID_PARAMS
        assert error.error.message == (
            "hub.malformed_request: payload must be JSON-serialisable"
        )
        assert error.error.data == {"hub_code": HUB_MALFORMED_REQUEST}

    def test_hub_mcp_error_does_not_embed_payload_values(self) -> None:
        error = hub_mcp_error(HUB_MALFORMED_REQUEST, "request rejected")

        assert "secret-token" not in error.error.message
        assert "payload" not in str(error.error.data)
