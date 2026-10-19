"""Connect-time harness API-key validation.

Pins the fail-open/fail-closed policy: only DEFINITIVE provider rejections
(bad auth, no credits) block credential creation; network blips, provider
5xx, rate limits, and a drifted probe model must all allow — validation can
never make credential creation depend on provider availability.
"""

import json
from unittest.mock import patch

import httpx
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


# OpenCode Zen as a caller outside OpenCode meets it (read 2026-10-17): its
# free tier refuses every completion before it looks at the key, while /models
# lists the models to no key and answers a key it doesn't know with 401.
_ZEN_FREE_TIER_REFUSAL = {"type": "error", "error": {
    "type": "FreeTierError",
    "message": "OpenCode's free tier can only be used from within OpenCode. "
               "Download it at https://opencode.ai and keep building."}}
_ZEN_INVALID_CREDENTIAL = {"error": {"type": "server_error", "message": "Invalid credential"}}
_ZEN_MODELS = {"object": "list", "data": [{"id": "big-pickle"}, {"id": "deepseek-v4.1-flash-free"}, {"id": "glm-5.1"}]}


class _ZenResp(_Resp):
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return json.loads(self.text)


def _zen(monkeypatch, *, good_key):
    calls = []

    class _ZenClient(_Client):
        async def get(self, url, headers=None, **k):
            calls.append(("GET", url, headers))
            auth = (headers or {}).get("Authorization")
            if auth and auth != f"Bearer {good_key}":
                return _ZenResp(401, _ZEN_INVALID_CREDENTIAL)
            return _ZenResp(200, _ZEN_MODELS)

        async def post(self, url, headers=None, **k):
            calls.append(("POST", url, headers))
            return _ZenResp(403, _ZEN_FREE_TIER_REFUSAL)

    monkeypatch.setattr(key_validation.httpx, "AsyncClient", _ZenClient)
    return calls


async def test_opencode_key_zen_refuses_is_refused_in_zens_words(monkeypatch):
    # The free-model completion this used to send now meets the free tier's
    # refusal, so every key looked fine and a dead one was saved (2026-10-16).
    calls = _zen(monkeypatch, good_key="zen-good")
    msg = await validate_agent_api_key(
        "agent_opencode", _blob({"OPENCODE_API_KEY": "zen-bad"})
    )
    assert msg and "OpenCode Zen rejected the API key" in msg
    assert "Invalid credential" in msg
    assert "opencode.ai/auth" in msg
    # Judged without a completion: nothing is spent and the free tier isn't asked.
    assert calls == [("GET", "https://opencode.ai/zen/v1/models", {"Authorization": "Bearer zen-bad"})]


async def test_opencode_key_zen_accepts_is_saved(monkeypatch):
    _zen(monkeypatch, good_key="zen-good")
    assert await validate_agent_api_key(
        "agent_opencode", _blob({"OPENCODE_API_KEY": "zen-good"})
    ) is None


@pytest.mark.parametrize("body", [
    _ZEN_INVALID_CREDENTIAL,
    # The words Zen's own proxy answers a key it can't place with.
    {"type": "error", "error": {"type": "AuthError", "message": "Invalid API key."}},
])
async def test_opencode_key_zen_names_invalid_is_refused(monkeypatch, body):
    class _Refusing(_Client):
        async def get(self, *a, **k):
            return _ZenResp(401, body)

    monkeypatch.setattr(key_validation.httpx, "AsyncClient", _Refusing)
    assert await validate_agent_api_key("agent_opencode", _blob({"OPENCODE_API_KEY": "zen-x"}))


@pytest.mark.parametrize("answer", [
    httpx.ReadTimeout("Zen took too long"),
    httpx.ConnectError("Zen unreachable"),
    _ZenResp(503, "Inference routing is unavailable. Please retry later."),
    # A 401 that doesn't say the key is invalid judges nothing: if valid keys
    # ever met one here, every OpenCode key would be refused.
    _ZenResp(401, {"type": "error", "error": {"type": "AuthError", "message": "Missing API key."}}),
    _ZenResp(401, ""),
])
async def test_opencode_key_zen_cannot_judge_is_saved_unverified(monkeypatch, answer):
    class _Unjudged(_Client):
        async def get(self, *a, **k):
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(key_validation.httpx, "AsyncClient", _Unjudged)
    assert await validate_agent_api_key(
        "agent_opencode", _blob({"OPENCODE_API_KEY": "zen-x"})
    ) is None
