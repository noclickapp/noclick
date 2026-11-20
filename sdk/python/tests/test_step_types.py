"""The step catalog (``GET /v1/step_types`` and ``/v1/step_types/{step_type}``): what the client sends and how it
reads the answer, against the mocked transport."""

import httpx
import pytest

import noclick as nc
from platform_helpers import listing

SLACK = {
    "object": "step_type", "type": "automation-slack", "label": "Slack", "description": "Slack automation",
    "category": "communication", "kinds": ["trigger", "tool"], "trigger": False,
    "operations": [
        {"name": "on_channel_message", "label": "On Channel Message", "trigger": True, "needs_account": True},
        {"name": "send_message_to_channel", "label": "Send Message", "trigger": False, "needs_account": True},
    ],
    "connection": {"needed": True, "integration": "slack", "credential_types": ["slack_oauth", "slack_bot_token"]},
    "retired": None,
}
CRON = {
    "object": "step_type", "type": "trigger-cron", "label": "Schedule", "description": "Runs on a schedule",
    "category": None, "kinds": ["trigger"], "trigger": True,
    "operations": [{"name": "default", "label": None, "trigger": False, "needs_account": False}],
    "connection": None, "retired": None,
}


def test_step_types_read_every_page_for_no_user(api, client):
    route = api.get("/v1/step_types").mock(side_effect=[
        httpx.Response(200, json=listing(CRON, next_cursor="trigger-cron")),
        httpx.Response(200, json=listing(SLACK)),
    ])
    with nc.as_user("user_42"):
        found = nc.step_types()
    first, second = (call.request for call in route.calls)
    assert "NoClick-User" not in first.headers and "cursor" not in first.url.params
    assert second.url.params["cursor"] == "trigger-cron"
    assert [t.type for t in found] == ["trigger-cron", "automation-slack"]

    cron, slack = found
    assert (cron.label, cron.kinds, cron.trigger, cron.connection, cron.schema) == (
        "Schedule", ["trigger"], True, None, None)
    send = slack.operations[1]
    assert (send.name, send.label, send.trigger, send.needs_account, send.description) == (
        "send_message_to_channel", "Send Message", False, True, None)
    assert slack.operations[0].trigger is True
    assert (slack.connection.needed, slack.connection.integration, slack.connection.credential_types) == (
        True, "slack", ["slack_oauth", "slack_bot_token"])
    assert slack.category == "communication" and slack.retired is None


def test_a_query_kind_and_limit_are_sent_as_the_route_takes_them(api, client):
    route = api.get("/v1/step_types").respond(json=listing(SLACK, next_cursor="automation-slack"))
    [slack] = nc.step_types("post to slack", kind="trigger", limit=1)
    params = route.calls.last.request.url.params
    assert (params["q"], params["kind"], params["limit"]) == ("post to slack", "trigger", "1")
    assert route.call_count == 1 and slack.type == "automation-slack"


def test_one_step_type_reads_its_schema_and_each_operation_described(api, client):
    schema = {"type": "object", "properties": {"config": {"oneOf": [{"$ref": "#/$defs/SendMessage"}]}},
              "$defs": {"SendMessage": {"properties": {"channel": {"type": "string", "x-dynamic-options": {}}}}}}
    described = {**SLACK, "operations": [{**op, "description": f"{op['label']}."} for op in SLACK["operations"]],
                 "schema": schema}
    route = api.get("/v1/step_types/automation-slack").respond(json=described)
    slack = nc.step_type("automation-slack")
    assert "NoClick-User" not in route.calls.last.request.headers
    assert slack.schema == schema and slack.raw["schema"] == schema
    assert [op.description for op in slack.operations] == ["On Channel Message.", "Send Message."]


def test_a_type_name_is_one_path_segment_and_an_unknown_one_is_not_found(api, client):
    api.get("/v1/step_types/a%2Fb").respond(404, json={"error": {
        "type": "not_found", "message": "No step type 'a/b'.", "next_step": "Find one with GET /v1/step_types?q=."}})
    with pytest.raises(nc.NotFound, match="No step type 'a/b'"):
        nc.step_type("a/b")


def test_a_type_that_takes_no_settings_has_no_schema(api, client):
    api.get("/v1/step_types/trigger-run").respond(json={
        **CRON, "type": "trigger-run", "label": "Run", "operations": [], "schema": None})
    run = nc.step_type("trigger-run")
    assert run.schema is None and run.operations == []
