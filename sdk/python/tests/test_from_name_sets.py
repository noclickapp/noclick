"""``from_name`` gets (or creates), then sets the fields it's given; an argument it can't set on an existing
object is checked, never ignored. ``create(..., allow_existing=True)`` makes an object once and leaves it alone."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, user_row

TAKEN = {"error": {"type": "conflict", "message": "It already exists.", "existing_id": "x_1"}}


def taken(existing_id="x_1"):
    return httpx.Response(409, json={"error": {**TAKEN["error"], "existing_id": existing_id}})


# --- fields from_name can't set ------------------------------------------------------

def test_an_agent_s_ttl_and_parent_are_checked_never_ignored(api, client):
    api.get("/v1/agents").respond(json=listing(agent_row(ttl_s=None, parent_id="ag_parent")))
    patch = api.patch("/v1/agents/ag_1").respond(json=agent_row())
    with pytest.raises(nc.Conflict) as ttl:
        nc.Agent.from_name("support", create_if_missing=True, instructions="new", ttl_s=3600).hydrate()
    assert (ttl.value.field, ttl.value.ttl_s, ttl.value.existing_id) == ("ttl_s", None, "ag_1")
    assert "ttl_s" in str(ttl.value) and "support" in str(ttl.value)
    with pytest.raises(nc.Conflict) as parent:
        nc.Agent.from_name("support", create_if_missing=True, instructions="new",
                           parent_id=nc.Agent.from_id("ag_other")).hydrate()
    assert (parent.value.field, parent.value.parent_id) == ("parent_id", "ag_parent")
    # Nothing was set on the agent by a call that was refused.
    assert patch.call_count == 0

    # Given as the agent has them, they pass, and the fields from_name can set are set.
    nc.Agent.from_name("support", create_if_missing=True, instructions="new",
                       parent_id=nc.Agent.from_id("ag_parent")).hydrate()
    assert body(patch.calls.last.request) == {"instructions": "new"}


def test_a_machine_s_region_is_checked_and_its_ceiling_set(api, client):
    machine = {"object": "machine", "id": "m_1", "name": "box", "size": "small", "region": "eu",
               "max_monthly_usd": 120.0, "network": True, "volumes": {}}
    api.get("/v1/machines").respond(json=listing(machine))
    patch = api.patch("/v1/machines/m_1").respond(json=machine)
    with pytest.raises(nc.Conflict) as region:
        nc.Machine.from_name("box", create_if_missing=True, region="us-east", max_monthly_usd=120).hydrate()
    assert (region.value.field, region.value.region) == ("region", "eu")
    assert patch.call_count == 0
    # Its own region passes; the ceiling it's given is the one the new size is judged against, set with it.
    nc.Machine.from_name("box", create_if_missing=True, region="eu", size="medium", max_monthly_usd=150).hydrate()
    assert body(patch.calls.last.request) == {"size": "medium", "max_monthly_usd": 150}
    # The same ceiling as it has is no change.
    nc.Machine.from_name("box", create_if_missing=True, size="medium", max_monthly_usd=120).hydrate()
    assert body(patch.calls.last.request) == {"size": "medium"}


def test_an_inbox_s_address_is_checked(api, client):
    inbox = {"object": "inbox", "id": "inb_1", "name": "support", "address": "help@mail.acme.test",
             "agent_id": None, "senders": "anyone", "conversation": None, "user_id": None}
    api.get("/v1/inboxes").respond(json=listing(inbox))
    patch = api.patch("/v1/inboxes/inb_1").respond(json=inbox)
    with pytest.raises(nc.Conflict) as local:
        nc.Inbox.from_name("support", create_if_missing=True, local_part="sales").hydrate()
    assert (local.value.field, local.value.local_part) == ("local_part", "help")
    with pytest.raises(nc.Conflict) as domain:
        nc.Inbox.from_name("support", create_if_missing=True, local_part="help", domain="acme.test").hydrate()
    assert (domain.value.field, domain.value.domain) == ("domain", "mail.acme.test")
    # Its own address, in any case, passes.
    nc.Inbox.from_name("support", create_if_missing=True, local_part="Help", domain="mail.acme.test",
                       senders="users").hydrate()
    assert body(patch.calls.last.request) == {"senders": "users"}


def test_a_connected_number_is_checked_against_connect(api, client):
    number = {"object": "phone_number", "id": "pn_2", "name": "front-desk", "number": "+14155550123",
              "source": "connected", "connection": "phone-provider", "record_calls": False}
    api.get("/v1/phone_numbers").respond(json=listing(number))
    with pytest.raises(nc.Conflict) as other:
        nc.PhoneNumber.from_name("front-desk", create_if_missing=True, connect="+14155550199",
                                 connection="phone-provider").hydrate()
    assert (other.value.field, other.value.number) == ("number", "+14155550123")
    # The same number, written another way, is the same number.
    found = nc.PhoneNumber.from_name("front-desk", create_if_missing=True, connect="+1 (415) 555-0123",
                                     connection="phone-provider")
    assert found.id == "pn_2"


def test_a_connection_s_credential_type_is_checked(api, client):
    api.get("/v1/connections/claude").respond(json={
        "object": "connection", "id": "con_1", "name": "claude", "integration": "anthropic",
        "credential_type": "agent_anthropic_api_key", "user_id": None, "status": "connected"})
    with pytest.raises(nc.Conflict) as kind:
        nc.Connection.from_name("claude", integration="anthropic", credential_type="agent_claude_code_oauth").hydrate()
    assert (kind.value.field, kind.value.credential_type) == ("credential_type", "agent_anthropic_api_key")
    assert nc.Connection.from_name("claude", integration="anthropic").id == "con_1"


# --- fields without create_if_missing ---------------------------------------------------

URL = "https://api.yourco.test/noclick/events"
# kind -> (the existing object, from_name with one field and no create_if_missing, the PATCH it sends)
SETS = {
    "agents": (agent_row(id="x_1"),
               lambda: nc.Agent.from_name("support", instructions="new"), {"instructions": "new"}),
    "cards": ({"id": "x_1", "name": "Travel", "status": "active", "limit_usd": 100, "interval": "day"},
              lambda: nc.Card.from_name("Travel", limit_usd=200), {"limit_usd": 200}),
    "channels": ({"id": "x_1", "name": "billing", "status": "open", "workspace_id": None, "members": []},
                 lambda: nc.Channel.from_name("billing", topic="Billing questions"), {"topic": "Billing questions"}),
    "machines": ({"id": "x_1", "name": "box", "size": "small", "region": "eu", "max_monthly_usd": 120.0},
                 lambda: nc.Machine.from_name("box", max_monthly_usd=150), {"max_monthly_usd": 150}),
    "mcp_servers": ({"id": "x_1", "name": "crm-tools", "tools": ["search"]},
                    lambda: nc.McpServer.from_name("crm-tools", tools=["search", "fetch"]),
                    {"tools": ["search", "fetch"]}),
    "domains": ({"id": "x_1", "name": "acme.test", "auto_renew": False},
                lambda: nc.Domain.from_name("acme.test", auto_renew=True), {"auto_renew": True}),
    "phone_numbers": ({"id": "x_1", "name": "front-desk", "number": "+14155550123", "record_calls": False},
                      lambda: nc.PhoneNumber.from_name("front-desk", record_calls=True), {"record_calls": True}),
    "inboxes": ({"id": "x_1", "name": "support", "address": "help@noclick.email", "senders": "anyone"},
                lambda: nc.Inbox.from_name("support", senders="users"), {"senders": "users"}),
    "projects": ({"id": "x_1", "name": "booking", "deploy_on_push": "off"},
                 lambda: nc.Project.from_name("booking", deploy_on_push="production"), {"deploy_on_push": "production"}),
    "secrets": ({"id": "x_1", "name": "shipping", "user_id": None, "keys": ["API_KEY"]},
                lambda: nc.Secret.from_name("shipping", values={"API_KEY": "new"}), {"values": {"API_KEY": "new"}}),
    "webhooks": ({"id": "x_1", "url": URL, "events": ["operation.*"], "user_id": None},
                 lambda: nc.Webhook.from_name(URL, events=["human.answered"]), {"events": ["human.answered"]}),
    "workspaces": ({"id": "x_1", "name": "Acme", "status": "active", "budget_usd_per_month": None, "members": []},
                   lambda: nc.Workspace.from_name("Acme", budget_usd_per_month=50), {"budget_usd_per_month": 50}),
    "queues": ({"id": "x_1", "name": "jobs", "max_attempts": 5},
               lambda: nc.Queue.from_name("jobs", max_attempts=8), {"max_attempts": 8}),
}


@pytest.mark.parametrize("kind", sorted(SETS))
def test_fields_without_create_if_missing_are_set_on_the_one_that_exists(api, client, kind):
    row, lazy, sent = SETS[kind]
    read = api.get(f"/v1/{kind}").mock(side_effect=[
        httpx.Response(200, json=listing(row)), httpx.Response(200, json=listing())])
    patch = api.patch(f"/v1/{kind}/x_1").respond(json=row)
    create = api.post(f"/v1/{kind}").respond(json=row)
    lazy().hydrate()
    assert body(patch.calls.last.request) == sent
    # When there's none, it's NotFound, as without fields: only create_if_missing creates.
    with pytest.raises(nc.NotFound):
        lazy().hydrate()
    assert (read.call_count, patch.call_count, create.call_count) == (2, 1, 0)


def test_a_user_s_fields_without_create_if_missing_are_set(api, client):
    found = api.get(f"/v1/users/{USER_ID}").mock(side_effect=[
        httpx.Response(200, json=user_row()), httpx.Response(404, json={"error": {"type": "not_found", "message": "No"}})])
    patch = api.patch(f"/v1/users/{USER_ID}").respond(json=user_row(name="Ana"))
    create = api.post("/v1/users").respond(json=user_row())
    nc.User.from_id(USER_ID, name="Ana").hydrate()
    assert body(patch.calls.last.request) == {"name": "Ana"}
    with pytest.raises(nc.NotFound):
        nc.User.from_id(USER_ID, name="Ana").hydrate()
    assert (found.call_count, create.call_count) == (2, 0)


def test_a_bare_from_name_sets_nothing(api, client):
    api.get("/v1/agents").respond(json=listing(agent_row()))
    patch = api.patch("/v1/agents/ag_1").respond(json=agent_row())
    assert nc.Agent.from_name("support").hydrate().id == "ag_1"
    assert patch.call_count == 0


def test_fields_it_cant_set_are_checked_without_create_if_missing_too(api, client):
    api.get("/v1/agents").respond(json=listing(agent_row(ttl_s=None)))
    with pytest.raises(nc.Conflict) as ttl:
        nc.Agent.from_name("support", ttl_s=60).hydrate()
    assert ttl.value.field == "ttl_s"
    api.get("/v1/inboxes").respond(json=listing({"id": "inb_1", "name": "support", "address": "help@noclick.email"}))
    with pytest.raises(nc.Conflict) as local:
        nc.Inbox.from_name("support", local_part="sales").hydrate()
    assert (local.value.field, local.value.local_part) == ("local_part", "help")
    api.get("/v1/phone_numbers").respond(json=listing({"id": "pn_1", "name": "front-desk", "number": "+14155550123"}))
    with pytest.raises(nc.Conflict) as number:
        nc.PhoneNumber.from_name("front-desk", connect="+14155550199").hydrate()
    assert number.value.field == "number"


# --- create(..., allow_existing=True) --------------------------------------------------

def test_agent_create_allow_existing_returns_the_agent_untouched(api, client):
    create = api.post("/v1/agents").mock(side_effect=[taken("ag_1"), taken("ag_1")])
    found = api.get("/v1/agents/ag_1").respond(json=agent_row(instructions="edited in the app"))
    patch = api.patch("/v1/agents/ag_1").respond(json=agent_row())
    with pytest.raises(nc.Conflict):
        nc.Agent.create("support", instructions="hi")
    assert found.call_count == 0
    agent = nc.Agent.create("support", instructions="hi", allow_existing=True)
    assert (agent.id, agent.instructions) == ("ag_1", "edited in the app")
    assert create.call_count == 2 and found.call_count == 1 and patch.call_count == 0


def test_allow_existing_keeps_a_conflict_that_isn_t_the_name(api, client):
    # The conflict named something else: another agent's name, or nothing this route reads.
    api.post("/v1/agents").mock(return_value=taken("ag_9"))
    api.get("/v1/agents/ag_9").respond(json=agent_row(id="ag_9", name="someone-else"))
    with pytest.raises(nc.Conflict) as other:
        nc.Agent.create("support", instructions="hi", allow_existing=True)
    assert other.value.existing_id == "ag_9"
    api.post("/v1/projects").mock(return_value=taken("repo_1"))
    api.get("/v1/projects/repo_1").respond(404, json={"error": {"type": "not_found", "message": "No project."}})
    with pytest.raises(nc.Conflict) as repo:
        nc.Project.create("booking", allow_existing=True)
    assert repo.value.existing_id == "repo_1"


ROWS = {
    "cards": {"object": "card", "id": "x_1", "name": "Travel", "status": "active"},
    "machines": {"object": "machine", "id": "x_1", "name": "box", "region": "eu"},
    "mcp_servers": {"object": "mcp_server", "id": "x_1", "name": "crm-tools", "tools": []},
    "inboxes": {"object": "inbox", "id": "x_1", "name": "support", "address": "help@noclick.email"},
    "projects": {"object": "project", "id": "x_1", "name": "booking"},
    "secrets": {"object": "secret", "id": "x_1", "name": "shipping", "keys": ["API_KEY"]},
    "workspaces": {"object": "workspace", "id": "x_1", "name": "Acme", "members": []},
    "connections": {"object": "connection", "id": "x_1", "name": "slack", "integration": "slack"},
    "buckets": {"object": "bucket", "id": "x_1", "name": "uploads"},
    "dicts": {"object": "dict", "id": "x_1", "name": "seen"},
    "queues": {"object": "queue", "id": "x_1", "name": "jobs"},
    "volumes": {"object": "volume", "id": "x_1", "name": "data"},
    "databases": {"object": "database", "id": "x_1", "name": "orders", "engine": "sqlite"},
    "memories": {"object": "memory", "id": "x_1", "name": "company"},
    "repos": {"object": "repo", "id": "x_1", "name": "site"},
    "browser_profiles": {"object": "browser_profile", "id": "x_1", "name": "ana-work"},
    "channels": {"object": "channel", "id": "x_1", "name": "billing", "status": "open", "members": []},
}

CREATES = {
    "cards": lambda **kw: nc.Card.create("Travel", limit_usd=100, **kw),
    "machines": lambda **kw: nc.Machine.create("box", max_monthly_usd=60, **kw),
    "mcp_servers": lambda **kw: nc.McpServer.create("crm-tools", tools=["search"], **kw),
    "inboxes": lambda **kw: nc.Inbox.create(name="support", local_part="help", **kw),
    "projects": lambda **kw: nc.Project.create("booking", repo="repo_1", **kw),
    "secrets": lambda **kw: nc.Secret.create("shipping", {"API_KEY": "new"}, **kw),
    "workspaces": lambda **kw: nc.Workspace.create("Acme", **kw),
    "connections": lambda **kw: nc.Connection.create("slack", integration="slack", **kw),
    "buckets": lambda **kw: nc.Bucket.create("uploads", **kw),
    "dicts": lambda **kw: nc.Dict.create("seen", **kw),
    "queues": lambda **kw: nc.Queue.create("jobs", **kw),
    "volumes": lambda **kw: nc.Volume.create("data", **kw),
    "databases": lambda **kw: nc.Database.create("orders", **kw),
    "memories": lambda **kw: nc.Memory.create("company", **kw),
    "repos": lambda **kw: nc.Repo.create("site", **kw),
    "browser_profiles": lambda **kw: nc.BrowserProfile.create("ana-work", **kw),
    "channels": lambda **kw: nc.Channel.create("billing", workspace="ws_1", **kw),
}


@pytest.mark.parametrize("kind", sorted(CREATES))
def test_every_named_create_takes_allow_existing(api, client, kind):
    create = api.post(f"/v1/{kind}").mock(return_value=taken())
    found = api.get(f"/v1/{kind}/x_1").respond(json=ROWS[kind])
    with pytest.raises(nc.Conflict):
        CREATES[kind]()
    made = CREATES[kind](allow_existing=True)
    assert made.id == "x_1" and made.name == ROWS[kind]["name"]
    # One more POST and one read: nothing about the existing one is written.
    assert create.call_count == 2 and found.call_count == 1
    assert all(call.request.method in ("POST", "GET") for call in api.calls)


def test_user_and_webhook_creates_find_theirs_by_id_and_url(api, client):
    api.post("/v1/users").mock(return_value=taken(USER_ID))
    read = api.get(f"/v1/users/{USER_ID}").respond(json=user_row(name="Ana"))
    assert nc.User.create(USER_ID, name="Bo", allow_existing=True).name == "Ana" and read.call_count == 1

    url = "https://api.yourco.test/noclick/events"
    api.post("/v1/webhooks").mock(return_value=taken("wh_1"))
    hook = {"object": "webhook", "id": "wh_1", "url": url, "events": ["operation.*"], "user_id": None}
    api.get("/v1/webhooks/wh_1").respond(json=hook)
    made = nc.Webhook.create(url, events=["human.answered"], allow_existing=True)
    assert (made.id, made.events, made.secret) == ("wh_1", ["operation.*"], None)


def test_allow_existing_says_what_it_needs_to_find_one(api, client):
    with pytest.raises(ValueError, match="needs workspace="):
        nc.Channel.create("billing", allow_existing=True)
    with pytest.raises(ValueError, match="needs name="):
        nc.Inbox.create(local_part="help", allow_existing=True)


def test_a_connection_found_by_allow_existing_is_still_its_integration(api, client):
    api.post("/v1/connections").mock(return_value=taken("con_1"))
    api.get("/v1/connections/con_1").respond(json={"object": "connection", "id": "con_1", "name": "slack",
                                                   "integration": "discord", "credential_type": "DiscordBot"})
    with pytest.raises(nc.Conflict) as other:
        nc.Connection.create("slack", integration="slack", allow_existing=True)
    assert (other.value.field, other.value.integration) == ("integration", "discord")
