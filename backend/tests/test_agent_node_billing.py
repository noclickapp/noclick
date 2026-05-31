"""Regression tests: agent-node usage must be recorded without a live socket.

Triggered workflow runs (cron, webhook, run-from-API) have no connected client
socket. The webhook/worker path runs the workflow with ``sid=""`` (empty string,
set in ``utils/webhook_routes.py`` and passed unchanged into
``NodeFactory.create_node``), so the agent node's BillingHooks gets a real
``sio`` but a falsy ``sid``.

The bug these tests guard against: ``BillingHooks.__init__`` used to *require*
socket context — ``has_direct_socket = sio and sid``, which is falsy when
``sid == ""`` — and raised ``ValueError`` otherwise. ``Agent._build_billing_hooks``
swallowed that error and set ``_billing_hooks = None``, so
``Runner.run_streamed(hooks=None)`` ran with no lifecycle hooks: ``on_llm_end``
never fired and the LLM cost was never recorded for ANY non-interactive run.

The socket is only used to push live UI updates; billing must never depend on it.
These tests use ``sid=None`` (a superset of the ``sid=""`` repro — both are
falsy) to assert that hooks construct and record usage regardless of socket.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from coder.openai_agent.billing import BillingHooks


@pytest.fixture
def anyio_backend():
    return "asyncio"


# Real UUID — UsageEventData validates user_id as a UUID string at insert time.
_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def test_billing_hooks_constructs_without_socket():
    """A billing entity (user_id) is the only requirement — no socket needed."""
    hooks = BillingHooks(
        model="gpt-4o",
        user_id=_TEST_USER_ID,
        sio=None,
        sid=None,
        organization_id=None,
        env=None,
    )
    assert hooks._user_id == _TEST_USER_ID
    assert hooks._sio is None
    assert hooks._sid is None


def test_billing_hooks_still_requires_user_id():
    """Without a billing entity there's nothing to charge — must still raise."""
    with pytest.raises(ValueError):
        BillingHooks(model="gpt-4o", user_id=None, sio=None, sid=None)


@pytest.mark.anyio
async def test_billing_hooks_records_usage_without_socket():
    """on_llm_end must record usage even when there is no client socket.

    This is the core regression: a cron/webhook-triggered agent run records its
    LLM cost to usage_events despite sio/sid being None.
    """
    hooks = BillingHooks(model="gpt-4o", user_id=_TEST_USER_ID, sio=None, sid=None)

    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=42),
        output=[],
        response_id="resp-test",
        request_id="req-test",
    )

    # track_usage_event is a sync fire-and-forget method on the singleton; the
    # _record_usage path imports it as `from billing.usage_tracker import
    # usage_tracker`, so patch the attribute on the singleton instance.
    with patch(
        "billing.usage_tracker.usage_tracker.track_usage_event", new=MagicMock()
    ) as mock_track:
        await hooks.on_llm_end(context=MagicMock(), agent=MagicMock(), response=response)

    mock_track.assert_called_once()
    args, kwargs = mock_track.call_args
    event = args[0]
    assert event.user_id == _TEST_USER_ID
    assert event.metadata["prompt_tokens"] == 100
    assert event.metadata["completion_tokens"] == 42
    # Usage recording does not depend on the socket — it's passed through as None.
    assert kwargs["sio"] is None
    assert kwargs["sid"] is None
