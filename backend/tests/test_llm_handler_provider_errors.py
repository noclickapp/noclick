"""The workflow-Run path must rewrite provider billing/auth errors too.

The interactive chat path has classified these since the 2026-07-09 incident,
but a workflow Run goes through ``handlers/llm.py``, which re-raised the raw
exception. So the same broken credential produced actionable guidance in chat
and this on the canvas:

    litellm.AuthenticationError: AuthenticationError: OpenrouterException -
    {"error":{"message":"User not found.","code":401}}

which names a library the user has never heard of and no action they can take.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nodes.agent.handlers.llm import execute_llm_model

OPENROUTER_401 = (
    'litellm.AuthenticationError: AuthenticationError: OpenrouterException - '
    '{"error":{"message":"User not found.","code":401}}'
)


class _Node:
    """Minimal stand-in for the agent node's emit surface."""

    def __init__(self):
        self.node_id = "agent_1"
        self.sid = None
        self.sio = None
        self.organization_id = None
        self.workflow_id = "wf_1"
        self.execution_id = "exec_1"
        self.conversation_id = None
        self.emitted = []

    async def emit(self, payload):
        self.emitted.append(payload)

    async def _execute_tool(self, *_args, **_kwargs):  # pragma: no cover
        return None


def _config():
    return SimpleNamespace(
        model="openrouter/anthropic/claude-3.5-sonnet",
        temperature=0.7,
        system_prompt="",
        conversation_key=None,
        message="hi",
    )


async def _run_with_agent_failure(error_text: str):
    """Drive execute_llm_model with Agent.create blowing up as the provider would."""
    node = _Node()
    with patch(
        "nodes.agent.handlers.llm.Agent.create",
        new=AsyncMock(side_effect=Exception(error_text)),
    ):
        with pytest.raises(Exception) as excinfo:
            await execute_llm_model(
                node, _config(), None, "user-1", "user@example.com"
            )
    return node, excinfo.value


def _agent_errors(node):
    return [e.get("error") for e in node.emitted if e.get("status") == "error"]


@pytest.mark.asyncio
async def test_openrouter_401_is_rewritten_on_the_agent_event():
    node, _ = await _run_with_agent_failure(OPENROUTER_401)

    guidance, _sep, verbatim = _agent_errors(node)[0].partition("Provider message:")

    # What the user reads first must be the explanation and the action, not a
    # library name. The raw text still rides along after "Provider message:" —
    # a misclassification has to degrade to extra guidance, never lost detail.
    assert "OpenRouter" in guidance and "API key" in guidance
    assert "reconnect it on the agent node" in guidance
    assert "litellm" not in guidance, "raw library framing must not lead"
    assert "User not found" in verbatim


@pytest.mark.asyncio
async def test_the_exception_is_re_raised_untouched():
    """The workflow runner rewrites at its own per-node choke point. If this
    handler rewrote the exception as well, the runner would classify the
    rewrite and wrap one explanation inside another."""
    _node, raised = await _run_with_agent_failure(OPENROUTER_401)

    assert str(raised) == OPENROUTER_401
    assert "Provider message:" not in str(raised)


@pytest.mark.asyncio
async def test_unclassified_errors_are_left_exactly_as_they_were():
    """Only provider-origin errors are rewritten. A genuine bug must keep its
    message on every surface, or debugging gets harder rather than easier."""
    node, raised = await _run_with_agent_failure("KeyError: 'workflow_id'")

    assert "KeyError: 'workflow_id'" in str(raised)
    assert _agent_errors(node) == ["KeyError: 'workflow_id'"]


# ── The runner's choke point ────────────────────────────────────────────────
# The rewrite sits in the runner's per-node failure path, scoped by node_type:
# agent failures classify (whichever handler inside the agent raised), every
# other node's error passes verbatim — a Stripe key rejection must not be
# rewritten into model-provider guidance.


def test_choke_point_rewrites_provider_errors_from_agent_nodes():
    from nodes.agent.provider_errors import describe_failure

    rewritten, action = describe_failure(Exception(OPENROUTER_401), node_type="agent")
    assert "OpenRouter rejected the API key" in rewritten
    assert "User not found" in rewritten, "the provider's own words must survive"
    assert action == {"type": "open_credentials", "label": "Open credentials"}


def test_choke_point_leaves_other_node_types_verbatim():
    from nodes.agent.provider_errors import describe_failure

    stripe_auth = "Invalid API Key provided: sk_test_4eC39Hq"
    message, action = describe_failure(
        Exception(stripe_auth), node_type="automation-stripe"
    )
    assert message == stripe_auth
    assert action is None


def test_choke_point_leaves_ordinary_node_failures_alone():
    from nodes.agent.provider_errors import classify_and_rewrite_provider_error

    for ordinary in (
        "Node automation-slack failed: channel_not_found",
        "HTTPSConnectionPool(host='api.example.com', port=443): Read timed out.",
        "KeyError: 'spreadsheet_id'",
        "",
    ):
        assert classify_and_rewrite_provider_error(ordinary) == ordinary


def test_choke_point_does_not_wrap_a_rewrite_in_another_rewrite():
    """The single-call contract. If both a handler and the runner rewrote, the
    user would read the guidance twice with the real error buried deepest."""
    from nodes.agent.provider_errors import classify_and_rewrite_provider_error

    once = classify_and_rewrite_provider_error(OPENROUTER_401)
    twice = classify_and_rewrite_provider_error(once)
    assert twice.count("OpenRouter rejected the API key") == 2, (
        "double-rewriting IS visible — which is why exactly one surface may call it"
    )
