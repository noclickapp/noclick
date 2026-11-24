"""An app's key to the account (``app.account_key``): read where it stands, give it, take it away, replace its
bearers. Nothing here ever carries a key's value: the API answers none."""

import json

import pytest

import noclick as nc
from platform_helpers import body, operation

ASKS = {"scopes": ["agents", "channels"], "commit": "9f2c1ab",
        "can": [{"scope": "agents", "can": "run, change and delete your agents", "reads_secrets": False},
                {"scope": "channels", "can": "read and post in your spaces and channels", "reads_secrets": False}]}
WAITING = {"object": "app_account_key", "project_id": "prj_1", "status": "waiting", "variable": "NOCLICK_API_KEY",
           "asks": ASKS, "key": None, "missing_scopes": [],
           "request": {"status": "waiting", "scopes": ["agents", "channels"], "asked_at": "2026-11-23T09:00:00+00:00",
                       "approval_id": "apr_1", "operation_id": "op_held"},
           "cannot": ["make, change or revoke API keys, its own included"], "note": "Anyone who can change it."}
GRANTED = {**WAITING, "status": "granted", "request": None,
           "key": {"id": "key_1", "name": "console (the app's key to the account)", "scopes": ["agents", "channels"],
                   "spend_cap_usd_per_month": 50.0, "granted_at": "2026-11-23T09:05:00+00:00", "last_used_at": None}}


def test_where_an_apps_key_stands_reads_what_it_asks_for_and_what_it_waits_on(api, client):
    api.get("/v1/projects/prj_1/account_key").respond(json=WAITING)
    key = nc.Project.from_id("prj_1").account_key.get()
    assert (key.status, key.granted, key.variable) == ("waiting", False, "NOCLICK_API_KEY")
    assert [(line.scope, line.reads_secrets) for line in key.asks] == [("agents", False), ("channels", False)]
    assert key.asks[0].can == "run, change and delete your agents" and key.commit == "9f2c1ab"
    assert (key.key_id, key.scopes, key.missing_scopes) == (None, [], [])
    assert (key.request.status, key.request.approval_id, key.request.operation_id) == ("waiting", "apr_1", "op_held")
    assert key.request.asked_at.year == 2026 and key.cannot == WAITING["cannot"]


def test_an_app_that_asks_for_nothing_reads_as_none(api, client):
    api.get("/v1/projects/prj_1/account_key").respond(json={
        **WAITING, "status": "none", "asks": None, "request": None})
    key = nc.Project.from_id("prj_1").account_key.get()
    assert (key.status, key.asks, key.commit, key.request) == ("none", [], None, None)


def test_giving_it_sends_the_scopes_and_never_a_key(api, client):
    give = api.put("/v1/projects/prj_1/account_key").respond(json=GRANTED)
    app = nc.Project.from_id("prj_1")
    key = app.account_key.give(["agents", "channels"], spend_cap_usd_per_month=50)
    assert body(give.calls.last.request) == {"scopes": ["agents", "channels"], "spend_cap_usd_per_month": 50}
    assert key.granted and (key.key_id, key.scopes, key.spend_cap_usd_per_month) == (
        "key_1", ["agents", "channels"], 50.0)
    assert key.granted_at.year == 2026 and key.last_used_at is None
    assert "nk_" not in json.dumps(key.raw)

    # Left out, the scopes are what its repository asks for now, and a cap it holds is left alone.
    api.get("/v1/projects/prj_1/account_key").respond(json=WAITING)
    app.account_key.give()
    assert body(give.calls.last.request) == {"scopes": ["agents", "channels"]}
    app.account_key.give(["agents", "channels"], spend_cap_usd_per_month=None)
    assert body(give.calls.last.request) == {"scopes": ["agents", "channels"], "spend_cap_usd_per_month": None}


def test_what_its_repository_doesnt_ask_for_is_a_conflict_and_a_held_one_waits_for_the_owner(api, client):
    api.put("/v1/projects/prj_1/account_key").respond(409, json={"error": {
        "type": "conflict", "message": "The app console's repository asks for agents, channels, not what this call "
                                       "gives.", "asks": ["agents", "channels"]}})
    with pytest.raises(nc.Conflict) as refused:
        nc.Project.from_id("prj_1").account_key.give(["agents", "queues"])
    assert refused.value.details["asks"] == ["agents", "channels"]

    api.put("/v1/projects/prj_2/account_key").respond(402, json={"error": {
        "type": "approval_required", "message": "It waits for the account's owner.", "approval_id": "apr_2",
        "operation_id": "op_2", "sent_to": ["email"]}})
    with pytest.raises(nc.ApprovalRequired) as held:
        nc.Project.from_id("prj_2").account_key.give(["agents"])
    assert held.value.details["approval_id"] == "apr_2"


def test_taking_it_away_and_replacing_its_bearers(api, client):
    revoke = api.post("/v1/projects/prj_1/account_key/revoke").respond(json={
        **WAITING, "status": "revoked", "request": {**WAITING["request"], "status": "revoked", "approval_id": None,
                                                    "operation_id": None}})
    gone = nc.Project.from_id("prj_1").account_key.revoke()
    assert revoke.called and (gone.status, gone.request.status, gone.request.approval_id) == (
        "revoked", "revoked", None)

    rotate = api.post("/v1/projects/prj_1/account_key/rotate").respond(
        202, json=operation(op_id="op_r", kind="deployment.promote", status="queued"))
    api.get("/v1/operations/op_r/wait").respond(json=operation(
        op_id="op_r", kind="deployment.promote", status="succeeded",
        result={"object": "deployment", "id": "dep_1", "project_id": "prj_1", "status": "ready", "production": True}))
    released = nc.Project.from_id("prj_1").account_key.rotate().wait()
    assert rotate.called and isinstance(released, nc.Deployment) and released.id == "dep_1"
