"""The usage_tracker proxy forwards to whatever tracker is registered. A method
patched on it and restored never pins the proxy to that tracker, and a patch
survives a registration made while it is active."""

from unittest.mock import AsyncMock, patch

import pytest

from billing.usage_tracker import _UsageTrackerProxy


class Tracker:
    def __init__(self, name):
        self.name = name

    async def track_usage_event(self, event, sio=None, sid=None):
        return self.name


@pytest.mark.asyncio
async def test_a_patch_restored_by_value_leaves_later_registrations_in_charge():
    first, second = Tracker("first"), Tracker("second")
    proxy = _UsageTrackerProxy(first)

    with pytest.MonkeyPatch.context() as mp:
        async def patched(event, sio=None, sid=None):
            return "patched"

        mp.setattr(proxy, "track_usage_event", patched)
        assert await proxy.track_usage_event(None) == "patched"
    assert await proxy.track_usage_event(None) == "first"

    proxy._impl = second
    assert await proxy.track_usage_event(None) == "second"
    assert "track_usage_event" not in vars(proxy)


@pytest.mark.asyncio
async def test_a_patch_outlives_a_registration_made_while_it_is_active():
    proxy = _UsageTrackerProxy(Tracker("first"))
    with patch.object(proxy, "track_usage_event", new=AsyncMock(return_value="patched")):
        proxy._impl = Tracker("second")
        assert await proxy.track_usage_event(None) == "patched"
    assert await proxy.track_usage_event(None) == "second"
