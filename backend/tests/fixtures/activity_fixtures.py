"""What the engine tells an activity feed (``ACTIVITY_SIGNAL``), recorded instead of posted."""

import pytest

from utils import capabilities
from utils.capabilities import ACTIVITY_SIGNAL


@pytest.fixture
def activity_signals(monkeypatch):
    """Each ``(user, action, details, key)`` the engine signals, in order."""
    seen = []

    def record(user, action, details=None, *, key=None):
        seen.append((user, action, details, key))

    monkeypatch.setitem(capabilities._providers, ACTIVITY_SIGNAL, record)
    return seen
