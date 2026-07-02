"""Regression: agent-node usage must record without a live socket.

Triggered runs (cron/webhook) execute with sid="". BillingHooks used to require
socket context and raise; _build_billing_hooks swallowed that and set hooks=None,
so on_llm_end never fired and cost was never recorded. Tests use sid=None (also
falsy) to assert hooks construct + record regardless of socket.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from coder.openai_agent.billing import BillingHooks
from coder.openai_agent.litellm_model import CostCapturingLitellmModel


@pytest.fixture
def anyio_backend():
    return "asyncio"


# Real UUID — UsageEventData validates user_id as a UUID string at insert time.
_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def _model(name: str = "gpt-4o") -> CostCapturingLitellmModel:
    return CostCapturingLitellmModel(model=name)


def test_billing_hooks_constructs_without_socket():
    """A billing entity (user_id) is the only requirement — no socket needed."""
    hooks = BillingHooks(
        model="gpt-4o",
        model_instance=_model(),
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
        BillingHooks(model="gpt-4o", model_instance=_model(), user_id=None, sio=None, sid=None)


@pytest.mark.anyio
async def test_billing_hooks_records_usage_without_socket():
    """on_llm_end records usage even with no client socket (the core regression)."""
    hooks = BillingHooks(
        model="gpt-4o", model_instance=_model(),
        user_id=_TEST_USER_ID, sio=None, sid=None,
    )

    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=42),
        output=[],
        response_id="resp-test",
        request_id="req-test",
    )

    # _record_usage imports the usage_tracker singleton, so patch it there.
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
