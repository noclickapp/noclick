"""What a test says a deployment's capabilities (``utils/capabilities.py``) answer, for tests of a path that asks
one something it doesn't test and that hold no database to ask it of. Absent a platform none is provided and nothing
asks. Import the fixture into the test module."""

from unittest.mock import AsyncMock

import pytest

from utils import capabilities


@pytest.fixture
def claimed_accounts(monkeypatch):
    """Every account a test names is a person's (``ACCOUNT_UNCLAIMED``): a webhook's delivery, a bridge link, a
    sandbox's network and a serverless run ask before they act for an account."""
    monkeypatch.setitem(capabilities._providers, capabilities.ACCOUNT_UNCLAIMED, AsyncMock(return_value=False))


@pytest.fixture
def deliveries_run_workflows(monkeypatch):
    """A fired trigger runs its workflow: no product takes its delivery (``TRIGGER_DELIVERY``)."""
    monkeypatch.delitem(capabilities._providers, capabilities.TRIGGER_DELIVERY, raising=False)


@pytest.fixture
def no_answer_pictures(monkeypatch):
    """No workflow's agents draw pictures for their replies (``ANSWER_PICTURES``), which an agent's turn asks."""
    monkeypatch.delitem(capabilities._providers, capabilities.ANSWER_PICTURES, raising=False)
