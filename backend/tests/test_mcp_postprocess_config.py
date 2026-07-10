"""Unit tests for NoClickMCPServer._postprocess_config — the consolidated
post-merge config validation pass (C1/C3/C4) added to the MCP update path.

The method reuses the internal builder's validation helpers; these tests verify
the WIRING: placeholder auth-header strip + credential hint, and the guard that
skips provider-wired / canvas-only-key configs from Pydantic validation.
"""
from mcp_server import NoClickMCPServer


def _srv():
    # The method only reads the class-level _CANVAS_ONLY_CONFIG_KEYS, no instance
    # state, so bypass __init__ (which needs a socket.io server).
    return NoClickMCPServer.__new__(NoClickMCPServer)


def test_strips_placeholder_auth_header_and_returns_hint():
    srv = _srv()
    config = {
        "url": "https://api.example.com/x",
        "headers": [{"key": "Authorization", "value": "Bearer {{API_KEY}}"}],
    }
    verdict = srv._postprocess_config("automation-http-request", "get", config)
    assert verdict is not None
    # Header carrying the placeholder secret is removed in place.
    assert config["headers"] == []
    # And surfaced as a bearer-token credential hint.
    assert verdict["http_auth_credential_hint"]["credential_type"] == "bearertokencredential"


def test_non_placeholder_header_is_kept():
    srv = _srv()
    config = {
        "url": "https://api.example.com/x",
        "headers": [{"key": "X-Custom", "value": "static-value"}],
    }
    verdict = srv._postprocess_config("automation-http-request", "get", config)
    assert config["headers"] == [{"key": "X-Custom", "value": "static-value"}]
    assert verdict is None or "http_auth_credential_hint" not in verdict


def test_provider_wired_node_skips_validation():
    srv = _srv()
    # A provider-wired node must not be Pydantic-validated (its config carries
    # the canvas-only agent_tool_operations key, not the operation model).
    config = {"agent_tool_operations": ["send_message_to_channel"]}
    assert srv._postprocess_config("automation-slack", "send_message_to_channel", config, is_provider=True) is None


def test_canvas_only_key_skips_validation():
    srv = _srv()
    config = {"agent_tool_operations": ["read_sheet_data"]}
    # Even without the is_provider flag, presence of a canvas-only key skips.
    assert srv._postprocess_config("automation-google-sheets", "read_sheet_data", config) is None


def test_returns_verdict_shape_for_normal_node():
    srv = _srv()
    # An empty/underspecified config for a real operation should still produce a
    # verdict dict with config_valid (True or False), never raise.
    verdict = srv._postprocess_config("automation-http-request", "get", {})
    # Either a verdict (with config_valid) or None if the op has no config class.
    assert verdict is None or "config_valid" in verdict
