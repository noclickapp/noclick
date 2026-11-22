"""Connected apps (``noclick.ConnectedApp``): the account's signed-in owner lists them, revokes one and restores a
revoked one NoClick makes, as it was. They're the account's, so none sends ``NoClick-User`` inside ``as_user``."""

import httpx
import pytest

import noclick as nc

ASSISTANT = {
    "object": "connected_app", "id": "ca_1",
    "client": {"name": "NoClick (your assistant)", "uri": None, "id": "noclick:coordinator"},
    "capabilities": ["read", "build"], "spend_cap_usd_per_month": 25.0, "auto_approve_under_usd": None,
    "approvals": {}, "spent_usd_this_month": 1.5, "user_id": None, "resource": "https://mcp.noclick.com",
    "key_id": "key_1", "created_at": "2026-11-01T00:00:00+00:00", "last_used_at": None,
    "revoked_at": "2026-11-21T09:30:00+00:00", "restorable": True, "profile": "default",
}
CLAUDE = {**ASSISTANT, "id": "ca_2", "client": {"name": "Claude", "uri": "https://claude.ai", "id": "c-1"},
          "revoked_at": None, "restorable": False}


def test_list_reads_every_page_as_the_account(api, client):
    listed = api.get("/v1/connected_apps").mock(side_effect=[
        httpx.Response(200, json={"object": "list", "data": [ASSISTANT], "next_cursor": "ca_1"}),
        httpx.Response(200, json={"object": "list", "data": [CLAUDE], "next_cursor": None}),
    ])
    with nc.as_user("user_42"):
        apps = nc.ConnectedApp.list()
    assert listed.calls.last.request.url.params["cursor"] == "ca_1"
    assert [(a.id, a.client_name, a.client_id, a.revoked, a.restorable) for a in apps] == [
        ("ca_1", "NoClick (your assistant)", "noclick:coordinator", True, True),
        ("ca_2", "Claude", "c-1", False, False)]
    assert apps[0].capabilities == ["read", "build"] and apps[0].spend_cap_usd_per_month == 25.0
    assert apps[0].revoked_at.isoformat() == "2026-11-21T09:30:00+00:00" and apps[0].last_used_at is None
    assert "NoClick-User" not in listed.calls.last.request.headers


def test_restore_turns_a_revoked_one_back_on_and_revoke_ends_it(api, client):
    restored = api.post("/v1/connected_apps/ca_1/restore").respond(json={**ASSISTANT, "revoked_at": None})
    with nc.as_user("user_42"):
        app = nc.ConnectedApp.restore("ca_1")
    assert not app.revoked and app.capabilities == ["read", "build"]
    assert "NoClick-User" not in restored.calls.last.request.headers

    api.delete("/v1/connected_apps/ca_1").respond(json=ASSISTANT)
    assert nc.ConnectedApp.revoke("ca_1").revoked


def test_a_client_a_person_connected_isnt_restored_and_a_key_is_refused(api, client):
    api.post("/v1/connected_apps/ca_2/restore").respond(409, json={"error": {
        "type": "conflict", "reason": "reconnect",
        "message": "Claude is a client you connected, so it isn't restored: connect it again."}})
    with pytest.raises(nc.Conflict):
        nc.ConnectedApp.restore("ca_2")
    api.post("/v1/connected_apps/ca_1/restore").respond(403, json={"error": {
        "type": "permission_denied", "message": "This call is for the signed-in account owner, not an API key."}})
    with pytest.raises(nc.PermissionDenied):
        nc.ConnectedApp.restore("ca_1")


async def test_restore_aio(api, client):
    api.post("/v1/connected_apps/ca_1/restore").respond(json={**ASSISTANT, "revoked_at": None})
    assert not (await nc.ConnectedApp.restore.aio("ca_1")).revoked
