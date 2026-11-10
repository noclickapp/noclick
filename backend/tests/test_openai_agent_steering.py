"""Steering a running turn (``coder.openai_agent.steering``) and the reason the
model gave beside a call (``turn_notes``), through the real streamed SDK and
PostgreSQL: steered text joins before the run's next model call (never its
first), is stored where the run had reached, and stays put for the run's
later calls; a tool call sees the text its response carried."""

from unittest.mock import AsyncMock

import pytest

from coder.openai_agent import turn_notes
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from utils import capabilities

pytestmark = pytest.mark.asyncio

CONVERSATION = "ck:wf:agent:sdk:account:agent-1:c1"
STEER = {"role": "user", "content": "Skip the e2e suite."}




async def test_no_steering_without_a_product_that_steers(monkeypatch):
    from coder.openai_agent import steering

    monkeypatch.setitem(capabilities._providers, capabilities.TURN_STEERING, None)
    assert steering.filter_for(CONVERSATION, None) is None
    assert turn_notes.stated_reason() is None  # outside a run
