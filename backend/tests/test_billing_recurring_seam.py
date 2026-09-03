"""The recurring-charge seam: the engine bills nothing on its own; a platform
that registers a processor with ``start_connection_charge`` gets each new
connection-backed credential's clock started inside the caller's transaction."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from billing import recurring


@pytest.fixture(autouse=True)
def _restore_impl():
    saved = recurring._impl
    yield
    recurring._impl = saved


async def test_nothing_registered_bills_nothing():
    recurring._impl = None
    conn = MagicMock()
    await recurring.start_connection_charge(conn, user_id="u1", credential_id="c1", charge_type="whatsapp_connection")
    conn.execute.assert_not_called()


async def test_registered_platform_starts_the_clock():
    impl = MagicMock()
    impl.start_connection_charge = AsyncMock()
    recurring.register_recurring_charges(impl)
    conn = MagicMock()
    await recurring.start_connection_charge(conn, user_id="u1", credential_id="c1", charge_type="whatsapp_connection")
    impl.start_connection_charge.assert_awaited_once_with(
        conn, user_id="u1", credential_id="c1", charge_type="whatsapp_connection"
    )


async def test_a_processor_without_the_hook_is_left_alone():
    recurring.register_recurring_charges(object())
    conn = MagicMock()
    await recurring.start_connection_charge(conn, user_id="u1", credential_id="c1", charge_type="whatsapp_connection")
    conn.execute.assert_not_called()
