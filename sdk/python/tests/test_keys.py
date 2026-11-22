"""``noclick.Key.create``: one of your account's own keys holding ``keys:create`` makes another, no wider than itself.
It's the account's own call, so it never sends ``NoClick-User`` inside ``as_user``; the secret comes back once."""

from datetime import datetime, timezone

import pytest

import noclick as nc
from platform_helpers import body

MADE = {"object": "key", "id": "key_2", "kind": "api", "type": "secret", "name": "queue worker",
        "key_prefix": "nk_live_ab12", "scopes": ["queues", "agents"], "spend_cap_usd_per_month": 20.0,
        "user_id": None, "created_at": "2026-11-21T09:30:00+00:00", "last_used_at": None,
        "expires_at": "2026-12-01T00:00:00+00:00", "revoked_at": None, "minted_by": "key_1", "approvals": {},
        "raw_key": "nk_live_FAKESECRET0001"}


def test_create_sends_what_it_names_and_returns_the_secret_once(api, client):
    made = api.post("/v1/keys").respond(json=MADE)
    with nc.as_user("user_42"):  # the account's own call: never a user's
        key = nc.Key.create("queue worker", ["queues", "agents"], spend_cap_usd_per_month=20,
                            expires_at=datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert body(made.calls.last.request) == {"name": "queue worker", "scopes": ["queues", "agents"],
                                             "spend_cap_usd_per_month": 20,
                                             "expires_at": "2026-12-01T00:00:00+00:00"}
    assert "NoClick-User" not in made.calls.last.request.headers
    assert (key.id, key.minted_by, key.spend_cap_usd_per_month, key.secret) == (
        "key_2", "key_1", 20.0, "nk_live_FAKESECRET0001")
    assert key.expires_at == datetime(2026, 12, 1, tzinfo=timezone.utc)
    # Never printed, and not kept beside the rest.
    assert "FAKESECRET" not in repr(key) and "raw_key" not in key.raw


def test_a_key_wider_than_its_maker_raises_permission_denied(api, client):
    api.post("/v1/keys").respond(403, json={"error": {
        "type": "permission_denied", "field": "scopes", "scope": "phone",
        "message": "This key can't make a key holding phone: a key it makes holds only scopes it holds itself."}})
    with pytest.raises(nc.PermissionDenied) as refused:
        nc.Key.create("too wide", ["phone"])
    assert refused.value.field == "scopes"


async def test_create_aio(api, client):
    api.post("/v1/keys").respond(json={**MADE, "user_id": "dana"})
    key = await nc.Key.create.aio("dana's worker", ["agents"], user_id="dana")
    assert key.user_id == "dana"
