"""The account and its admin routes, each as one typed call: the account and its status, keys (listed, changed,
revoked, a setup code, a publishable one), connected apps a page at a time, a CLI sign-in answered, machines asked
for, a user reactivated and a deletion previewed. Each is the account's own call: none sends ``NoClick-User``."""

import noclick as nc
from platform_helpers import body, listing, user_row

ACCOUNT = {"object": "account", "id": "acc_1", "email": "ana@acme.test", "plan": {"tier": "member"},
           "balance": {"remaining_usd": 12.5}, "month": {"spent_usd": 3.2}, "spend_cap": None,
           "counts": {"agents": 4}, "limits": {"webhooks_max": 20}, "features": {"phone_numbers": True},
           "default_region": "eu", "spending_paused": {"message": "Top up", "action": None},
           "console_key_id": "key_c", "meta": {"scopes": ["agents"], "explicit_scopes": ["keys:create"]}}
KEY = {"object": "key", "id": "key_1", "kind": "api", "type": "secret", "name": "worker", "key_prefix": "nk_live_ab12",
       "scopes": ["agents"], "spend_cap_usd_per_month": None, "user_id": None, "created_at": "2026-11-25T10:00:00Z",
       "last_used_at": None, "expires_at": None, "revoked_at": None}


def test_the_account_is_read_changed_and_seen_at_a_glance(api):
    read = api.get("/v1/account").respond(json=ACCOUNT)
    account = nc.Account.get()
    assert (account.plan_tier, account.balance["remaining_usd"], account.default_region) == ("member", 12.5, "eu")
    assert account.spending_paused.message == "Top up" and account.explicit_scopes == ["keys:create"]
    assert "NoClick-User" not in read.calls.last.request.headers
    changed = api.patch("/v1/account").respond(json={**ACCOUNT, "default_region": None})
    assert nc.Account.update(default_region=None, spend_cap_usd=200).default_region is None
    assert body(changed.calls.last.request) == {"default_region": None, "spend_cap_usd": 200}  # only what's given

    api.get("/v1/status").respond(json={"object": "status", "account": {"id": "acc_1", "name": "Acme"},
                                        "user_id": None, "plan": {"name": "Member"}, "balance": {}, "month": {},
                                        "caps": [], "approvals_pending": [{"id": "ap_1"}], "failing": [],
                                        "operations": {"running": 1}})
    status = nc.Account.status()
    assert (status.account["name"], status.approvals_pending[0]["id"], status.operations["running"]) == (
        "Acme", "ap_1", 1)

    api.get("/v1/public_endpoints").respond(json=listing(
        {"object": "public_endpoint", "kind": "agent_share", "id": "sh_1", "name": "Support", "url": "https://x",
         "user_id": None}))
    [endpoint] = nc.Account.public_endpoints()
    assert (endpoint.kind, endpoint.name) == ("agent_share", "Support")
    found = api.get("/v1/objects/nk_live_ab12").respond(json={"object": "object_ref", "type": "key", "id": "key_1",
                                                              "user_id": None})
    assert (nc.Account.resolve("nk_live_ab12").type, found.call_count) == ("key", 1)
    linked = api.post("/v1/account/payment_links").respond(json={
        "object": "payment_link", "kind": "funds", "label": "$20 of funds", "price_usd": 23, "url": "https://pay",
        "expires_at": "2026-11-27T10:00:00Z", "operation_id": "op_p"})
    link = nc.Account.payment_link(amount_usd=20)
    assert body(linked.calls.last.request) == {"kind": "funds", "amount_usd": 20}
    assert (link.price_usd, link.url, link.operation_id) == (23, "https://pay", "op_p")


def test_keys_are_listed_changed_revoked_and_a_setup_code_made(api):
    listed = api.get("/v1/keys").respond(json=listing(KEY, next_cursor="c2"))
    page = nc.Key.list_page(status="active", limit=1)
    assert ([k.key_prefix for k in page.data], page.next_cursor) == (["nk_live_ab12"], "c2")
    assert listed.calls.last.request.url.params["status"] == "active"
    changed = api.patch("/v1/keys/key_1").respond(json={**KEY, "spend_cap_usd_per_month": None})
    nc.Key.update("key_1", name="worker (prod)", spend_cap_usd_per_month=None)
    assert body(changed.calls.last.request) == {"name": "worker (prod)", "spend_cap_usd_per_month": None}
    api.delete("/v1/keys/key_1").respond(json={**KEY, "revoked_at": "2026-11-25T11:00:00Z"})
    assert nc.Key.revoke("key_1").revoked_at is not None
    coded = api.post("/v1/cli/setup_codes").respond(201, json={"object": "setup_code", "code": "nc_setup_x",
                                                               "key_name": "Coding agent: build an agent", "expires_at": None})
    code = nc.Key.setup_code(name="Coding agent: build an agent")
    assert (code.code, code.key_name) == ("nc_setup_x", "Coding agent: build an agent")
    assert body(coded.calls.last.request) == {"name": "Coding agent: build an agent"}
    made = api.post("/v1/keys").respond(201, json={**KEY, "type": "publishable", "scopes": []})
    key = nc.Key.create("site", [], type="publishable", public_endpoints=[{"kind": "agent_share", "id": "sh_1"}],
                        allowed_origins=["https://acme.com"])
    assert body(made.calls.last.request) == {"name": "site", "scopes": [], "type": "publishable",
                                             "public_endpoints": [{"kind": "agent_share", "id": "sh_1"}],
                                             "allowed_origins": ["https://acme.com"]}
    assert key.type == "publishable"


def test_connected_apps_a_cli_sign_in_machines_and_a_user(api):
    apps = api.get("/v1/connected_apps").respond(json=listing(
        {"object": "connected_app", "id": "ca_1", "client": {"name": "Claude", "id": "c"}, "capabilities": ["read"]},
        next_cursor="n"))
    page = nc.ConnectedApp.list_page(cursor="c1")
    assert (page.data[0].client_name, page.next_cursor, apps.calls.last.request.url.params["cursor"]) == (
        "Claude", "n", "c1")

    login = {"object": "cli_login", "user_code": "WDJB-MJHT", "client": "noclick-cli", "hostname": "ana-mbp",
             "ip": "1.2.3.4", "key_name": "CLI on ana-mbp", "status": "pending"}
    api.get("/v1/cli/logins/WDJB-MJHT").respond(json=login)
    answered = api.post("/v1/cli/logins/WDJB-MJHT/answer").respond(json={**login, "status": "approved"})
    assert nc.CliLogin.get("WDJB-MJHT").answer(True).status == "approved"
    assert body(answered.calls.last.request) == {"approved": True}

    api.get("/v1/machines/vetting").respond(json={"object": "machine_vetting", "status": "not_submitted",
                                                  "policy_version": "2026-10"})
    assert nc.Machine.access().status == "not_submitted"
    asked = api.post("/v1/machines/vetting").respond(json={"object": "machine_vetting", "status": "pending",
                                                           "policy_version": "2026-10", "company_name": "Acme"})
    assert nc.Machine.request_access(company_name="Acme", website="https://acme.com", country="US",
                                     use_case="Agents", accept_usage_policy=True).status == "pending"
    assert body(asked.calls.last.request)["accept_usage_policy"] is True

    api.get("/v1/users/user_42").respond(json=user_row(status="suspended"))
    back = api.patch("/v1/users/user_42").respond(json=user_row(status="active"))
    assert nc.User.from_id("user_42").reactivate().status == "active"
    assert body(back.calls.last.request) == {"status": "active"}


def test_a_deletion_is_previewed_with_what_it_takes(api):
    previewed = api.post("/v1/delete_previews").respond(201, json={
        "object": "delete_preview", "operation": "agents_delete", "method": "DELETE", "path": "/v1/agents/ag_1",
        "title": "support", "impact": {"deletes": "The agent support", "depends_on_it": ["2 channels"],
                                       "data_lost": [], "stops_billing": [], "reversible": True,
                                       "undo": "Restorable from the trash for 30 days."},
        "confirm_token": "ct_1", "expires_in_s": 600})
    preview = nc.preview_delete("DELETE", "/v1/agents/ag_1")
    assert body(previewed.calls.last.request) == {"method": "DELETE", "path": "/v1/agents/ag_1"}
    assert (preview.impact.depends_on_it, preview.impact.reversible, preview.confirm_token) == (
        ["2 channels"], True, "ct_1")
