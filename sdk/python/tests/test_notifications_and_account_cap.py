"""The email alerts NoClick sends your account's owner (``noclick.Notifications``), and your account's own monthly
spending cap (``noclick.Usage.limits().account``, ``noclick.Usage.set_account_cap``): both the account's, never a
user's, so neither sends ``NoClick-User`` inside ``as_user``."""

import pytest

import noclick as nc
from platform_helpers import body

CATEGORIES = {"run_failure": True, "credits": True, "digest": False, "spend_cap": True}
CAP = {"object": "spend_cap", "cap_usd": 50.0, "spent_usd": 12.5, "period_start": "2026-11-01T00:00:00+00:00",
       "resets_at": "2026-12-01T00:00:00+00:00", "reached": False}
LIMITS = {"object": "usage_limits", "period_start": "2026-11-01T00:00:00+00:00",
          "resets_at": "2026-12-01T00:00:00+00:00", "keys": [], "users": [], "agents": [], "projects": []}


def test_notifications_read_every_kind_on_or_off(api, client):
    read = api.get("/v1/notifications").respond(json={"object": "notifications", "categories": CATEGORIES})
    with nc.as_user("user_42"):  # the owner's alerts: never a user's
        alerts = nc.Notifications.get()
    assert alerts.categories == CATEGORIES
    assert "NoClick-User" not in read.calls.last.request.headers


def test_notifications_update_sends_only_the_kinds_it_names(api, client):
    patch = api.patch("/v1/notifications").respond(
        json={"object": "notifications", "categories": {**CATEGORIES, "digest": True, "credits": False}})
    alerts = nc.Notifications.update({"digest": True, "credits": False})
    assert body(patch.calls.last.request) == {"categories": {"digest": True, "credits": False}}
    assert "NoClick-User" not in patch.calls.last.request.headers
    assert (alerts.categories["digest"], alerts.categories["credits"], alerts.categories["run_failure"]) == (
        True, False, True)


def test_a_kind_noclick_doesnt_send_raises_invalid_request(api, client):
    api.patch("/v1/notifications").respond(400, json={"error": {
        "type": "invalid_request", "message": "categories.newsletter: Input should be 'approvals', ...",
        "field": "categories.newsletter"}})
    with pytest.raises(nc.InvalidRequest):
        nc.Notifications.update({"newsletter": False})


async def test_notifications_aio(api, client):
    api.get("/v1/notifications").respond(json={"object": "notifications", "categories": CATEGORIES})
    assert (await nc.Notifications.get.aio()).categories["digest"] is False


def test_limits_carry_the_accounts_own_cap(api, client):
    api.get("/v1/usage/limits").respond(json={**LIMITS, "account": CAP})
    account = nc.Usage.limits().account
    assert (account.cap_usd, account.spent_usd, account.reached) == (50.0, 12.5, False)
    assert account.resets_at.isoformat() == "2026-12-01T00:00:00+00:00"

    api.get("/v1/usage/limits").respond(json={**LIMITS, "account": {"object": "spend_cap", "cap_usd": None}})
    none = nc.Usage.limits().account
    assert (none.cap_usd, none.spent_usd, none.period_start, none.reached) == (None, None, None, False)


def test_set_account_cap_puts_it_as_the_account(api, client):
    put = api.put("/v1/usage/limits/account").respond(json={**CAP, "cap_usd": 30.0})
    with nc.as_user("user_42"):
        cap = nc.Usage.set_account_cap(30)
    assert body(put.calls.last.request) == {"cap_usd": 30}
    assert "NoClick-User" not in put.calls.last.request.headers
    assert (cap.cap_usd, cap.spent_usd) == (30.0, 12.5)


def test_a_key_raising_or_removing_the_cap_raises_permission_denied(api, client):
    put = api.put("/v1/usage/limits/account").respond(403, json={"error": {
        "type": "permission_denied",
        "message": "A key only lowers the account's monthly spending cap, or sets one where there's none: this "
                   "removes its spending cap of $50.00 a month, which is the account's owner's to do.",
        "next_step": "Ask the account's owner: they raise or remove it in Settings → Plan and billing in the NoClick "
                     "app."}})
    with pytest.raises(nc.PermissionDenied) as refused:
        nc.Usage.set_account_cap(None)
    assert body(put.calls.last.request) == {"cap_usd": None}
    assert "Settings → Plan and billing" in str(refused.value)
