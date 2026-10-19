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


async def test_a_credential_priced_on_its_own_carries_its_vendor_price_to_the_processor():
    impl = MagicMock()
    impl.start_connection_charge = AsyncMock()
    recurring.register_recurring_charges(impl)
    conn = MagicMock()
    await recurring.start_connection_charge(conn, user_id="u1", credential_id="c1", charge_type="phone_number",
                                            period_usd="2.00", upfront_usd="1.50")
    impl.start_connection_charge.assert_awaited_once_with(
        conn, user_id="u1", credential_id="c1", charge_type="phone_number", period_usd="2.00", upfront_usd="1.50"
    )


async def test_a_charge_is_priced_by_the_processor_else_at_the_vendors_price():
    from billing.markup import CREDITS_PER_DOLLAR

    recurring._impl = None
    assert await recurring.charge_credits("u1", "phone_number", "2.00") == round(2.0 * float(CREDITS_PER_DOLLAR), 4)
    impl = MagicMock()
    impl.charge_credits = AsyncMock(return_value=24.0)
    recurring.register_recurring_charges(impl)
    assert await recurring.charge_credits("u1", "phone_number", "2.00") == 24.0
    impl.charge_credits.assert_awaited_once_with("u1", "phone_number", "2.00")
