"""The OpenRouter ``usage.include`` extra_body is OpenRouter-ONLY.

litellm merges ``extra_body`` verbatim into the outbound JSON, and strict
providers reject unknown properties — Groq 400s every call with
``property 'usage' is unsupported`` (2026-08 BYOK incident), and
Anthropic rejects the literal ``extra_body`` key. These tests pin the gate at
both places that build it: the SDK agent's ModelSettings (construction AND
mid-conversation ``update_model``) and the extension/brain
``build_provider_extra_body`` helper.
"""
import pytest

from agents import Agent as SDKAgent

from coder.openai_agent.agent import Agent, _build_model_settings, _session_key
from coder.openai_agent.config import AgentConfiguration, LLMConfig
from coder.workflow.pass_base import build_provider_extra_body

OPENROUTER_EXTRA_BODY = {"usage": {"include": True}}

NON_OPENROUTER_MODELS = [
    "groq/llama-3.3-70b-versatile",
    "anthropic/claude-sonnet-4-5",
    "gemini/gemini-3.5-flash",
    "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "openai/gpt-5.2",
    "gpt-4o-mini",
    "opencode/gpt-5.2",  # Zen gateway rewrites to openai/…; gate sees the original
]


class TestBuildModelSettings:
    def test_openrouter_models_get_the_usage_extra_body(self):
        settings = _build_model_settings("openrouter/openai/gpt-5.6-luna", 0.7)
        assert settings.extra_body == OPENROUTER_EXTRA_BODY
        assert settings.include_usage is True
        assert settings.temperature == 0.7

    @pytest.mark.parametrize("model", ["openrouter/anthropic/claude-sonnet-5.5",
                                       "openrouter/~anthropic/claude-sonnet-latest"])
    def test_an_anthropic_model_through_openrouter_asks_for_its_prompt_cache(self, model):
        """Anthropic caches only what a request marks: unmarked, every call paid full input price for the same
        instructions, tools and history (a bench turn on Sonnet read 0 of 207k prompt tokens from cache)."""
        settings = _build_model_settings(model, 0.7)
        assert settings.extra_body == {**OPENROUTER_EXTRA_BODY, "cache_control": {"type": "ephemeral"}}

    def test_an_openrouter_call_names_its_conversation_so_it_stays_on_one_provider(self):
        """OpenRouter keeps a conversation on the provider holding its prompt cache by hashing its opening messages,
        which compaction rewrites; a session_id keys it on the conversation itself. Hashed: the conversation's ids
        stay ours."""
        model, conversation = "openrouter/~openai/gpt-luna-latest", "ck:wf-1:agent:sdk:account:agent-1:owner"
        first = _build_model_settings(model, 0.7, conversation=conversation)
        again = _build_model_settings(model, 0.7, conversation=conversation)
        other = _build_model_settings(model, 0.7, conversation="ck:wf-1:agent:sdk:account:agent-2:owner")
        session = first.extra_body["session_id"]
        assert session == again.extra_body["session_id"] != other.extra_body["session_id"]
        assert len(session) <= 256 and "agent-1" not in session
        assert first.extra_body == {**OPENROUTER_EXTRA_BODY, "session_id": session}
        assert _build_model_settings("groq/llama-3.3-70b-versatile", 0.7, conversation=conversation).extra_body is None

    async def test_an_agent_names_its_conversation_on_every_call(self):
        def created(conversation_id):
            return Agent.create(emit_message=lambda event: None, conversation_id=conversation_id,
                                enable_persistence=False,
                                config=AgentConfiguration.from_kwargs(model="openrouter/~openai/gpt-luna-latest"))

        one, two = await created("conversation-1"), await created("conversation-2")
        assert one._sdk_agent.model_settings.extra_body["session_id"] == _session_key("conversation-1")
        assert two._sdk_agent.model_settings.extra_body["session_id"] == _session_key("conversation-2")
        one.update_model("openrouter/anthropic/claude-sonnet-5.5")
        assert one._sdk_agent.model_settings.extra_body["session_id"] == _session_key("conversation-1")

    @pytest.mark.parametrize("model", NON_OPENROUTER_MODELS)
    def test_non_openrouter_models_get_no_extra_body(self, model):
        settings = _build_model_settings(model, 0.7)
        assert settings.extra_body is None
        # include_usage rides stream_options — standard, kept for all providers.
        assert settings.include_usage is True


class TestUpdateModelRebuildsSettings:
    """A mid-conversation model swap must recompute settings: keeping stale
    ones 400s on strict providers (openrouter→groq) or silently loses exact
    cost capture (groq→openrouter)."""

    def _make_agent(self, model):
        agent = Agent.__new__(Agent)
        agent.config = AgentConfiguration(llm=LLMConfig(model=model, temperature=0.3))
        agent.conversation_id = "test-conv"
        agent._env = {}
        agent._billing_hooks = None
        agent._sdk_agent = SDKAgent(
            name="test",
            instructions="test",
            tools=[],
            model_settings=_build_model_settings(model, 0.3),
        )
        agent._sdk_model = None
        return agent

    def test_openrouter_to_groq_drops_extra_body(self):
        agent = self._make_agent("openrouter/openai/gpt-5.6-luna")
        assert agent._sdk_agent.model_settings.extra_body == OPENROUTER_EXTRA_BODY
        agent.update_model("groq/llama-3.3-70b-versatile")
        assert agent._sdk_agent.model_settings.extra_body is None

    def test_groq_to_openrouter_gains_extra_body(self):
        agent = self._make_agent("groq/llama-3.3-70b-versatile")
        assert agent._sdk_agent.model_settings.extra_body is None
        agent.update_model("openrouter/openai/gpt-5.6-luna")
        assert agent._sdk_agent.model_settings.extra_body == {**OPENROUTER_EXTRA_BODY,
                                                              "session_id": _session_key("test-conv")}

    def test_temperature_update_is_reflected_in_settings(self):
        agent = self._make_agent("openrouter/openai/gpt-5.6-luna")
        agent.update_model("openrouter/openai/gpt-4o-mini", temperature=0.9)
        assert agent._sdk_agent.model_settings.temperature == 0.9


class TestBuilderProviderExtraBody:
    def test_openrouter_model_gets_provider_prefs_and_usage(self):
        body = build_provider_extra_body(
            "openrouter/google/gemini-3.5-flash", ["Fireworks"], "price"
        )
        assert body["usage"] == {"include": True}
        assert body["provider"]["order"] == ["Fireworks"]
        assert body["provider"]["allow_fallbacks"] is False
        assert body["provider"]["sort"] == "price"

    @pytest.mark.parametrize("model", NON_OPENROUTER_MODELS)
    def test_non_openrouter_model_gets_empty_body(self, model):
        assert build_provider_extra_body(model, ["Fireworks"], "price") == {}
