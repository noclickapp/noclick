"""What an agent may do with each app it reaches: its ``tool_rules``, sent as given, kept in step by ``from_name`` and
cleared with ``{}``, and ``tool_access()`` read app by app."""

import noclick as nc
from platform_helpers import agent_row, body, listing

RULES = {"*": "off", "work-gmail": "allow", "work-gmail.send_email_message": "ask"}
ACCESS = {
    "object": "agent_tool_access", "agent_id": "ag_1", "mode": "restricted", "listed": False, "rules": RULES,
    "since": "2026-11-07T10:00:00Z",
    "apps": [{
        "key": "work-gmail", "app": "work-gmail", "kind": "connection", "integration": "gmail",
        "credential_type": "gmail_oauth", "label": "Gmail", "account": "ada@example.com", "status": "connected",
        "on": True, "calls": 12,
        "actions": [{"key": "work-gmail.send_email_message", "action": "send_email_message",
                     "title": "Send Email Message", "group": "Message", "kind": "send", "verdict": "ask",
                     "can_ask": True, "calls": 3}],
    }, {
        "key": None, "app": "web", "kind": "web", "integration": None, "credential_type": None, "label": "Web",
        "account": "Search and read pages", "status": None, "on": False, "calls": 0,
        "actions": [{"key": "search", "action": "search", "title": "Search", "group": None, "kind": "read",
                     "verdict": "off", "can_ask": True, "calls": 0}],
    }],
}


def test_create_and_update_send_the_rules_given(api, client):
    create = api.post("/v1/agents").respond(201, json=agent_row(tools=["everything"], tool_rules=RULES))
    agent = nc.Agent.create("support", instructions="hi", tool_rules=RULES)
    assert body(create.calls.last.request) == {"name": "support", "instructions": "hi", "tool_rules": RULES}
    assert agent.tool_rules == RULES
    patch = api.patch("/v1/agents/ag_1").respond(json=agent_row(tools=["everything"], tool_rules={}))
    agent.update(tool_rules={})
    assert body(patch.calls.last.request) == {"tool_rules": {}}
    assert agent.tool_rules == {}


def test_from_name_sets_rules_that_differ(api, client):
    api.get("/v1/agents").respond(json=listing(agent_row(tools=["everything"], tool_rules=RULES)))
    patch = api.patch("/v1/agents/ag_1").respond(json=agent_row())
    nc.Agent.from_name("support", create_if_missing=True, instructions="hi", tool_rules=RULES).hydrate()
    assert patch.call_count == 0
    nc.Agent.from_name("support", create_if_missing=True, instructions="hi", tool_rules={"*": "off"}).hydrate()
    assert body(patch.calls.last.request) == {"tool_rules": {"*": "off"}}


def test_tool_access_reads_each_app_with_its_actions(api, client):
    api.get("/v1/agents/ag_1").respond(json=agent_row())
    api.get("/v1/agents/ag_1/tool_access").respond(json=ACCESS)
    access = nc.Agent.from_id("ag_1").tool_access()
    assert (access.mode, access.listed, access.rules) == ("restricted", False, RULES)
    assert access.since.isoformat().startswith("2026-11-07T10:00:00")
    gmail, web = access.apps
    assert (gmail.label, gmail.account, gmail.on, gmail.calls, gmail.credential_type) == (
        "Gmail", "ada@example.com", True, 12, "gmail_oauth")
    assert gmail.actions[0] == nc.AgentToolAction("work-gmail.send_email_message", "send_email_message",
                                                  "Send Email Message", "Message", "send", "ask", True, 3)
    assert web.key is None and web.actions[0].verdict == "off"
