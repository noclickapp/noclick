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

from coder.openai_agent.agent import Agent, _build_model_settings, _session_key, _with_effort
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


class TestFirstCallEffort:
    """A turn someone waits on starts with a call that reasons little, so its first words come sooner; the calls
    after it reason as the model does by default."""

    MODEL = "openrouter/~openai/gpt-luna-latest"

    def test_it_asks_openrouter_for_that_effort_and_nothing_elsewhere(self):
        base = _build_model_settings(self.MODEL, 0.7, conversation="c1")
        quick = _with_effort(base, self.MODEL, "low")
        assert quick.extra_body == {**base.extra_body, "reasoning": {"effort": "low"}}
        assert "reasoning" not in base.extra_body  # the run's own settings are untouched
        groq = "groq/llama-3.3-70b-versatile"
        assert _with_effort(_build_model_settings(groq, 0.7), groq, "low") is None

    async def test_a_runs_first_call_goes_with_it_and_the_rest_as_the_run_was_set(self):
        """Through the real streamed SDK: the first call reasons little, the call after its tool round as before, and
        the next run starts the same way."""
        from agents.models.interface import Model
        from openai.types.responses import (
            Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
        )

        sent = []

        class ModelDouble(Model):
            """Looks the balance up, then answers."""

            async def get_response(self, *args, **kwargs):
                raise AssertionError("the run streams")

            async def stream_response(self, system_instructions, input, model_settings, *args, **kwargs):
                sent.append((model_settings.extra_body or {}).get("reasoning"))
                if len(sent) % 2:
                    output = [ResponseFunctionToolCall(type="function_call", name="status", call_id=f"c{len(sent)}",
                                                       arguments="{}")]
                else:
                    output = [ResponseOutputMessage(id="m", type="message", role="assistant", status="completed",
                                                    content=[ResponseOutputText(type="output_text", annotations=[],
                                                                                text="It's $0.99.")])]
                response = Response.model_construct(id=f"r{len(sent)}", created_at=0, model="test", object="response",
                                                    output=output, status="completed", usage=None)
                yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

        async def emit(event):
            pass

        async def status(name, arguments):
            return {"balance_usd": 0.99}

        tool = {"type": "function", "function": {"name": "status", "description": "The balance",
                                                 "parameters": {"type": "object", "properties": {}}}}
        agent = await Agent.create(emit_message=emit, conversation_id="c1", enable_persistence=False,
                                   custom_tool_executor=status, first_call_effort="low",
                                   config=AgentConfiguration.from_kwargs(model=self.MODEL, custom_tools=[tool]))
        agent._sdk_agent.model = ModelDouble()
        settings = agent._sdk_agent.model_settings
        for _ in range(2):
            await agent({"content_items": [{"type": "text", "text": "what's my balance?"}]})
        assert sent == [{"effort": "low"}, None, {"effort": "low"}, None]
        assert agent._sdk_agent.model_settings is settings
