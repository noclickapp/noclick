"""OpenCode Zen/Go as an SDK-path inference provider (no sandbox).

``opencode/*`` (Zen) and ``opencode-go/*`` (Go) are OpenAI-compatible gateways
sharing one OPENCODE_API_KEY. The in-process LLM path routes them through
LiteLLM's ``openai/`` provider against the tier's base URL with the key passed
EXPLICITLY (inline params beat env lookups — the platform OPENAI_API_KEY must
never be sent to opencode.ai), and both tiers fold to the single ``opencode``
credential type, mirroring the FE fold in
agentCredentialModel.ts:inferProviderFromPrefix.
"""

import pytest

from nodes.agent.config.providers import (
    agent_credential_requirement,
    get_provider_credentials,
    resolve_zen_gateway_route,
)


# ---------------------------------------------------------------------------
# Gateway routing
# ---------------------------------------------------------------------------

def test_zen_tier_routes_to_zen_base():
    route = resolve_zen_gateway_route("opencode/glm-5")
    assert route is not None
    assert route.litellm_model == "openai/glm-5"
    assert route.base_url == "https://opencode.ai/zen/v1"
    assert route.api_key_env == "OPENCODE_API_KEY"


def test_go_tier_routes_to_go_base():
    route = resolve_zen_gateway_route("opencode-go/kimi-k2.5")
    assert route is not None
    assert route.litellm_model == "openai/kimi-k2.5"
    assert route.base_url == "https://opencode.ai/zen/go/v1"
    assert route.api_key_env == "OPENCODE_API_KEY"


def test_prefix_match_is_case_insensitive_but_preserves_id_case():
    route = resolve_zen_gateway_route("OpenCode-Go/GLM-5")
    assert route is not None and route.litellm_model == "openai/GLM-5"


@pytest.mark.parametrize("model", [
    "openrouter/anthropic/claude-sonnet-4-5",
    "anthropic/claude-sonnet-4-5",
    "opencode",       # bare CLI wrapper id — sandbox harness, not the gateway
    "codex",
    "openai/gpt-5",
])
def test_non_zen_models_do_not_route(model):
    assert resolve_zen_gateway_route(model) is None


# ---------------------------------------------------------------------------
# Credential fold: both tiers → the one `opencode` provider / credential type
# ---------------------------------------------------------------------------

def test_go_tier_folds_to_opencode_provider():
    env_vars, provider = get_provider_credentials("opencode-go/glm-5")
    assert env_vars == ["OPENCODE_API_KEY"]
    assert provider == "opencode"


@pytest.mark.parametrize("model", ["opencode/glm-5", "opencode-go/glm-5"])
def test_sdk_zen_model_requires_the_opencode_credential(model):
    req = agent_credential_requirement({"model": model})
    assert req.required is True
    assert req.credential_type == "agent_opencode"
    # Pre-fold rows saved under the Go stem must keep satisfying the node.
    assert "agent_opencode_go" in req.accepted_types
    assert "agent_api_key" in req.accepted_types
    # An API-key gateway — never subscription OAuth.
    assert not any(t.endswith("_oauth") for t in req.accepted_types)


# ---------------------------------------------------------------------------
# SDK model construction
# ---------------------------------------------------------------------------

def test_build_sdk_model_zen_sets_base_url_and_explicit_key():
    from coder.openai_agent.agent import _build_sdk_model

    m = _build_sdk_model("opencode-go/glm-5", {"OPENCODE_API_KEY": "zen-key"})
    assert m.model == "openai/glm-5"
    assert m.base_url == "https://opencode.ai/zen/go/v1"
    assert m.api_key == "zen-key"


def test_build_sdk_model_zen_without_key_fails_fast():
    from coder.openai_agent.agent import _build_sdk_model

    with pytest.raises(ValueError, match="OPENCODE_API_KEY"):
        _build_sdk_model("opencode/glm-5", None)
    # An OpenAI key must NOT satisfy a Zen model (the masking bug class):
    # constructing with api_key=None would let LiteLLM fall back to the
    # platform OPENAI_API_KEY and send it to opencode.ai.
    with pytest.raises(ValueError, match="OPENCODE_API_KEY"):
        _build_sdk_model("opencode/glm-5", {"OPENAI_API_KEY": "sk-x"})


def test_build_sdk_model_non_zen_keeps_native_routing():
    from coder.openai_agent.agent import _build_sdk_model

    m = _build_sdk_model("openrouter/openai/gpt-4o-mini", None)
    assert m.model == "openrouter/openai/gpt-4o-mini:exacto"
    assert m.base_url is None and m.api_key is None


# ---------------------------------------------------------------------------
# Catalog source (utils/model_catalog.py)
# ---------------------------------------------------------------------------

_CATALOG = {
    "opencode": {
        "name": "OpenCode Zen",
        "models": {
            "deepseek-v4-flash-free": {
                "name": "DeepSeek V4 Flash Free", "tool_call": True, "reasoning": True,
                "cost": {"input": 0, "output": 0}, "limit": {"context": 200000},
                "modalities": {"input": ["text"], "output": ["text"]},
            },
            # Rotated out of the live gateway — must be filtered.
            "minimax-m2.5-free": {
                "name": "MiniMax M2.5 Free", "tool_call": True,
                "cost": {"input": 0, "output": 0}, "limit": {"context": 204000},
            },
            # No tool calling — useless to an agent, filtered.
            "prose-only": {
                "name": "Prose Only", "tool_call": False,
                "cost": {"input": 0, "output": 0}, "limit": {"context": 8000},
            },
        },
    },
    "opencode-go": {
        "name": "OpenCode Go",
        "models": {
            "glm-5": {
                "name": "GLM-5", "tool_call": True,
                "cost": {"input": 1, "output": 3.2}, "limit": {"context": 202752},
                "modalities": {"input": ["text"], "output": ["text"]},
            },
        },
    },
}


def test_catalog_zen_source_filters_and_folds_provider(monkeypatch):
    import utils.opencode_zen as zen
    from utils.model_catalog import list_opencode_zen_models

    servable = {
        "opencode": {"deepseek-v4-flash-free", "prose-only"},
        "opencode-go": {"glm-5"},
    }
    monkeypatch.setattr(zen, "fetch_models_dev_sync", lambda: _CATALOG)
    monkeypatch.setattr(zen, "get_zen_servable_ids_sync", lambda tier: servable[tier])

    models = {m.id: m for m in list_opencode_zen_models()}
    assert set(models) == {"opencode/deepseek-v4-flash-free", "opencode-go/glm-5"}

    free = models["opencode/deepseek-v4-flash-free"]
    # Both tiers carry provider "opencode" — the FE resolves the credential
    # type catalog-first, and the tiers share one credential.
    assert free.provider == "opencode"
    assert free.free is True  # drives the picker's Free tag + "free" search
    assert free.capabilities.tools and free.capabilities.reasoning

    paid = models["opencode-go/glm-5"]
    assert paid.provider == "opencode"
    assert paid.free is False
    assert "OpenCode Go" in (paid.description or "")


def test_openrouter_free_flag_from_explicit_zero_pricing():
    from utils.model_catalog import _openrouter_is_free

    assert _openrouter_is_free({"prompt": "0", "completion": "0"}) is True
    assert _openrouter_is_free({"prompt": "0.00000014", "completion": "0"}) is False
    # Missing/unparseable pricing means unknown, never free.
    assert _openrouter_is_free({"prompt": "0"}) is False
    assert _openrouter_is_free(None) is False
    assert _openrouter_is_free({"prompt": "n/a", "completion": "0"}) is False


def test_catalog_zen_source_drops_tier_without_live_set(monkeypatch):
    """Never offer the models.dev superset unvalidated — a rotated-out model
    fails at run time with an opaque gateway error."""
    import utils.opencode_zen as zen
    from utils.model_catalog import list_opencode_zen_models

    monkeypatch.setattr(zen, "fetch_models_dev_sync", lambda: _CATALOG)
    monkeypatch.setattr(
        zen, "get_zen_servable_ids_sync",
        lambda tier: {"glm-5"} if tier == "opencode-go" else None,
    )
    ids = {m.id for m in list_opencode_zen_models()}
    assert ids == {"opencode-go/glm-5"}


# ---------------------------------------------------------------------------
# Builder model-registry variant: Zen models are LLM-path, not the CLI wrapper
# ---------------------------------------------------------------------------

def test_registry_variant_distinguishes_wrapper_from_zen_models():
    from coder.workflow.option_registries.models import _variant_for
    from utils.model_catalog import Model, Capabilities

    wrapper = Model(id="opencode", provider="opencode",
                    capabilities=Capabilities(tools=True))
    zen = Model(id="opencode/glm-5", provider="opencode",
                capabilities=Capabilities(tools=True))
    assert _variant_for(wrapper) == "variant:opencode"
    assert _variant_for(zen) == "variant:llm"
