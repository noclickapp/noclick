"""Provider credential resolution — the pre-flight gate that must fail fast when a
model's required key is absent, instead of launching a sandbox that hangs with no
auth. Pins the OpenCode Zen regression where opencode/* models silently produced
no response (the gate passed on an unrelated OpenAI key)."""
import pytest
from nodes.agent.config.providers import (
    get_provider_credentials,
    validate_provider_credentials,
)
from nodes.agent.harness_oauth_flows import AGENT_PROVIDER_OAUTH_TYPE

requires_hosted_signins = pytest.mark.skipif(
    "github_copilot" not in AGENT_PROVIDER_OAUTH_TYPE,
    reason="this edition registers no Copilot/xAI sign-in",
)


def test_opencode_zen_requires_zen_key_not_openai_fallback():
    # opencode/* and opencode-go/* (Zen tiers) read OPENCODE_API_KEY. Without the
    # explicit prefix they fell through to the generic OPENAI_API_KEY fallback.
    vars_, provider = get_provider_credentials("opencode/mimo-v2.5-free")
    assert vars_ == ["OPENCODE_API_KEY"] and provider == "opencode"
    assert get_provider_credentials("opencode-go/grok-code")[0] == ["OPENCODE_API_KEY"]


def test_opencode_zen_fast_fails_without_zen_key():
    # The masking bug: an OpenAI key must NOT satisfy an opencode/* model. Before
    # the fix this passed and opencode then hung 300s; now it fails fast.
    with pytest.raises(ValueError, match="OPENCODE_API_KEY"):
        validate_provider_credentials("opencode/mimo-v2.5-free", {"OPENAI_API_KEY": "sk-x"})
    # A real Zen key satisfies it.
    validate_provider_credentials("opencode/mimo-v2.5-free", {"OPENCODE_API_KEY": "zen-x"})


def test_other_providers_unaffected():
    assert get_provider_credentials("openrouter/openai/gpt-4o-mini")[0] == ["OPENROUTER_API_KEY"]
    assert get_provider_credentials("anthropic/claude-sonnet-4-5")[0] == ["ANTHROPIC_API_KEY"]
    # The OpenAI fallback still applies to genuinely OpenAI-shaped ids.
    validate_provider_credentials("openai/gpt-4o-mini", {"OPENAI_API_KEY": "sk-x"})


@requires_hosted_signins
def test_github_copilot_uses_its_oauth_token_not_openai_fallback():
    required, provider = get_provider_credentials("github-copilot/gpt-4o")
    assert required == ["GITHUB_COPILOT_ACCESS_TOKEN"]
    assert provider == "github-copilot"
