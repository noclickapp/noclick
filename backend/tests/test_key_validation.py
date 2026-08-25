"""Connect-time harness API-key validation.

Pins the fail-open/fail-closed policy: only DEFINITIVE provider rejections
(bad auth, no credits) block credential creation; network blips, provider
5xx, rate limits, and a drifted probe model must all allow — validation can
never make credential creation depend on provider availability.
"""

import json
from unittest.mock import patch

import pytest

from nodes.agent import key_validation
from nodes.agent.key_validation import validate_agent_api_key


class _Resp:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.text = body if isinstance(body, str) else json.dumps(body)


class _Client:
    """Stands in for httpx.AsyncClient; serves queued responses to any verb."""

    responses: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *a, **k):
        return _Client.responses.pop(0)

    async def post(self, *a, **k):
        return _Client.responses.pop(0)


def _patch(monkeypatch, *responses):
    _Client.responses = list(responses)
    monkeypatch.setattr(key_validation.httpx, "AsyncClient", _Client)


def _blob(env):
    return {"credentials": env}


async def test_non_agent_credential_types_are_never_probed(monkeypatch):
    _patch(monkeypatch)  # empty queue — any probe would raise IndexError
    assert await validate_agent_api_key("slack_oauth", _blob({"ANTHROPIC_API_KEY": "x"})) is None
    assert await validate_agent_api_key(None, _blob({"ANTHROPIC_API_KEY": "x"})) is None


async def test_anthropic_no_credits_rejected_with_disambiguation(monkeypatch):
    _patch(monkeypatch, _Resp(400, {"error": {
        "type": "invalid_request_error",
        "message": "Your credit balance is too low to access the Anthropic API."}}))
    msg = await validate_agent_api_key(
        "agent_claude_code", _blob({"ANTHROPIC_API_KEY": "sk-ant-dead"})
    )
    assert msg and "not your NoClick credits" in msg
    assert "platform.claude.com" in msg


async def test_anthropic_invalid_key_rejected(monkeypatch):
    _patch(monkeypatch, _Resp(401, {"error": {
        "type": "authentication_error", "message": "invalid x-api-key"}}))
    msg = await validate_agent_api_key(
        "agent_claude_code", _blob({"ANTHROPIC_API_KEY": "sk-ant-bad"})
    )
    assert msg and "rejected the API key" in msg


async def test_valid_key_allows(monkeypatch):
    _patch(monkeypatch, _Resp(200, {"content": [{"type": "text", "text": "hi"}]}))
    assert await validate_agent_api_key(
        "agent_claude_code", _blob({"ANTHROPIC_API_KEY": "sk-ant-good"})
    ) is None


@pytest.mark.parametrize("resp", [
    _Resp(429, "rate limited"),          # key works; provider is just busy
    _Resp(529, "overloaded"),            # provider outage
    _Resp(404, "model not found"),       # OUR probe model drifted — never block
])
async def test_non_definitive_provider_responses_allow(monkeypatch, resp):
    _patch(monkeypatch, resp)
    assert await validate_agent_api_key(
        "agent_claude_code", _blob({"ANTHROPIC_API_KEY": "sk-ant-x"})
    ) is None


async def test_network_failure_fails_open(monkeypatch):
    class _Exploding(_Client):
        async def post(self, *a, **k):
            raise ConnectionError("egress blip")

    monkeypatch.setattr(key_validation.httpx, "AsyncClient", _Exploding)
    assert await validate_agent_api_key(
        "agent_claude_code", _blob({"ANTHROPIC_API_KEY": "sk-ant-x"})
    ) is None


async def test_openai_quota_exhaustion_rejected(monkeypatch):
    _patch(
        monkeypatch,
        _Resp(200, {"data": []}),  # /v1/models: auth OK
        _Resp(429, {"error": {"type": "insufficient_quota",
                              "message": "You exceeded your current quota"}}),
    )
    msg = await validate_agent_api_key(
        "agent_codex", _blob({"OPENAI_API_KEY": "sk-dead"})
    )
    assert msg and "not your NoClick credits" in msg


async def test_openai_invalid_key_rejected_without_inference_probe(monkeypatch):
    _patch(monkeypatch, _Resp(401, {"error": {"code": "invalid_api_key"}}))
    msg = await validate_agent_api_key(
        "agent_codex", _blob({"OPENAI_API_KEY": "sk-bad"})
    )
    assert msg and "rejected the API key" in msg


async def test_openrouter_zero_balance_allows_but_bad_auth_rejects(monkeypatch):
    # Free models exist on OpenRouter — zero balance must not block.
    _patch(monkeypatch, _Resp(200, {"data": {"usage": 0, "limit_remaining": 0}}))
    assert await validate_agent_api_key(
        "agent_openrouter", _blob({"OPENROUTER_API_KEY": "sk-or-zero"})
    ) is None

    _patch(monkeypatch, _Resp(401, "No auth credentials found"))
    msg = await validate_agent_api_key(
        "agent_openrouter", _blob({"OPENROUTER_API_KEY": "sk-or-bad"})
    )
    assert msg and "rejected the API key" in msg


async def test_flat_legacy_blob_shape_is_probed(monkeypatch):
    _patch(monkeypatch, _Resp(401, "invalid x-api-key"))
    msg = await validate_agent_api_key(
        "agent_claude_code", {"ANTHROPIC_API_KEY": "sk-ant-bad"}
    )
    assert msg is not None


async def test_unrecognized_env_vars_allow_without_probing(monkeypatch):
    _patch(monkeypatch)  # any probe would IndexError
    assert await validate_agent_api_key(
        "agent_hermes_agent", _blob({"SOME_FUTURE_KEY": "x"})
    ) is None


def _stub_zen_servable(monkeypatch, ids):
    async def _servable(tier):
        return ids

    monkeypatch.setattr("utils.opencode_zen.get_zen_servable_ids", _servable)


async def test_opencode_invalid_key_rejected(monkeypatch):
    # Zen validates a PROVIDED key even on free models — definitive 401.
    _stub_zen_servable(monkeypatch, {"deepseek-v4-flash-free", "glm-5"})
    _patch(monkeypatch, _Resp(
        401, {"type": "error", "error": {"type": "AuthError", "message": "Invalid API key."}}
    ))
    msg = await validate_agent_api_key(
        "agent_opencode", _blob({"OPENCODE_API_KEY": "zen-bad"})
    )
    assert msg and "rejected the API key" in msg
    assert "opencode.ai/auth" in msg


async def test_opencode_valid_key_allows(monkeypatch):
    _stub_zen_servable(monkeypatch, {"deepseek-v4-flash-free"})
    _patch(monkeypatch, _Resp(200, {"choices": [{"message": {"content": "hi"}}]}))
    assert await validate_agent_api_key(
        "agent_opencode", _blob({"OPENCODE_API_KEY": "zen-good"})
    ) is None


async def test_opencode_probe_without_live_free_model_allows(monkeypatch):
    # Free tier rotated away entirely (or servable set unavailable) — the
    # probe is inconclusive and must allow without any HTTP call.
    _stub_zen_servable(monkeypatch, {"glm-5"})
    _patch(monkeypatch)  # empty queue — a probe attempt would IndexError
    assert await validate_agent_api_key(
        "agent_opencode", _blob({"OPENCODE_API_KEY": "zen-x"})
    ) is None
