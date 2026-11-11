"""Provider examples, wire dispatch, errors and callback lifecycle."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from nodes.runscope_node import OPERATIONS, RunscopeNode, RunscopeTokenCredential

FIXTURES = Path(__file__).parent / "fixtures" / "runscope"
CREDENTIAL = {"credential_type": "runscope_api_token", "api_token": "personal-test-token"}


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def node(config):
    parsed = RunscopeNode.parse_config({"config": config, "credentials": CREDENTIAL})
    return RunscopeNode(node_id="runscope-test", node_type="automation-runscope",
        node_data={"config": config}, config=parsed, sio=Mock())


@pytest.fixture
def wire(monkeypatch):
    calls, replies = [], []
    async def request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        status, body = replies.pop(0) if replies else (200, {"data": {"id": "item", "name": "Example"}, "error": None})
        return httpx.Response(status, json=body, request=httpx.Request(method, url)) if status != 204 else httpx.Response(204, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    return calls, replies


# Independent expected routes, rather than assertions against the dispatch table.
ROUTES = [
    ("get_account", "GET", "/account"),
    ("list_team_people", "GET", "/teams/team/people"),
    ("list_team_integrations", "GET", "/teams/team/integrations"),
    ("list_team_agents", "GET", "/teams/team/agents"),
    ("list_buckets", "GET", "/buckets"),
    ("get_bucket", "GET", "/buckets/bucket"),
    ("create_bucket", "POST", "/buckets"),
    ("delete_bucket", "DELETE", "/buckets/bucket"),
    ("list_tests", "GET", "/buckets/bucket/tests"),
    ("get_test", "GET", "/buckets/bucket/tests/test"),
    ("create_test", "POST", "/buckets/bucket/tests"),
    ("update_test", "PUT", "/buckets/bucket/tests/test"),
    ("delete_test", "DELETE", "/buckets/bucket/tests/test"),
    ("list_steps", "GET", "/buckets/bucket/tests/test/steps"),
    ("create_step", "POST", "/buckets/bucket/tests/test/steps"),
    ("update_step", "PUT", "/buckets/bucket/tests/test/steps/step"),
    ("delete_step", "DELETE", "/buckets/bucket/tests/test/steps/step"),
    ("list_test_environments", "GET", "/buckets/bucket/tests/test/environments"),
    ("create_test_environment", "POST", "/buckets/bucket/tests/test/environments"),
    ("update_test_environment", "PUT", "/buckets/bucket/tests/test/environments/environment"),
    ("list_shared_environments", "GET", "/buckets/bucket/environments"),
    ("create_shared_environment", "POST", "/buckets/bucket/environments"),
    ("update_shared_environment", "PUT", "/buckets/bucket/environments/environment"),
    ("get_test_metrics", "GET", "/buckets/bucket/tests/test/metrics"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path", ROUTES)
async def test_runscope_wire_routes(operation, method, path, wire):
    model = OPERATIONS[operation]
    config = {"operation": operation}
    for field in ("bucket_key", "team_id", "test_id", "step_id", "environment_id"):
        if "{" + field + "}" in model.path:
            config[field] = field.removesuffix("_id").removesuffix("_key")
    body = None
    if model.payload == "bucket":
        config.update(name="Mobile Team", team_id="team")
        body = None
    elif model.payload:
        body = fixture("environment.json") if model.payload == "environment" else {"name": "Sample Name"} if model.payload == "test" else {"step_type": "request", "method": "GET", "url": "https://yourapihere.com/"}
        config["payload_json"] = json.dumps(body)
    calls, replies = wire
    if method == "DELETE":
        replies.append((204, None))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    got_method, url, kwargs = calls[0]
    assert (got_method, url) == (method, "https://api.runscope.com" + path)
    assert kwargs["headers"]["Authorization"] == "Bearer personal-test-token"
    assert kwargs["json"] == body
    if operation == "create_bucket":
        assert kwargs["params"] == {"name": "Mobile Team", "team_uuid": "team"}
    if method == "DELETE":
        assert result["data"] == {"deleted": True}


@pytest.mark.parametrize("value", ["https://example.com/key", "Bearer test", "<token>", " "])
def test_runscope_manual_token_rejects_bad_inputs(value):
    with pytest.raises(ValidationError):
        RunscopeTokenCredential(api_token=value)


def test_runscope_manual_token_default_and_trim():
    c = RunscopeTokenCredential(api_token=" personal-test-token ")
    assert c.credential_type == "runscope_api_token"
    assert c.api_token == "personal-test-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_runscope_provider_failures_do_not_succeed_or_leak(status, wire):
    calls, replies = wire
    replies.append((status, {"error": {"message": "personal-test-token"}}))
    with pytest.raises(ValueError, match=str(status)) as exc:
        await node({"operation": "list_buckets"}).execute({})
    assert "personal-test-token" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_runscope_error_envelope(wire):
    wire[1].append((200, {"error": {"message": "denied"}}))
    with pytest.raises(ValueError, match="error envelope"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ['[]', '{bad', '{}', '{"name": ""}'])
async def test_runscope_invalid_body_makes_no_request(value, wire):
    with pytest.raises(ValueError):
        await node({"operation": "create_test", "bucket_key": "bucket", "payload_json": value}).execute({})
    assert wire[0] == []


@pytest.mark.asyncio
async def test_runscope_callback_preserves_settings_and_removes_only_own_url(wire):
    calls, replies = wire
    env = fixture("environment.json")
    original = copy.deepcopy(env)
    config = {"bucket_key": "bucket", "environment_id": env["id"]}
    callback = "https://hooks.hooks.example.test/unique-callback"
    replies.extend([(200, env), (200, env)])
    state = await RunscopeNode._register_external_webhook(webhook_url=callback, credential=CREDENTIAL, config=config, node_id="node")
    assert state == {"external_webhook_id": callback}
    written = calls[1][2]["json"]
    assert written["webhooks"] == [*original["webhooks"], callback]
    for key in original.keys() - {"id", "test_id", "exported_at", "version", "webhooks"}:
        assert written[key] == original[key]
    assert env == original
    assert calls[0][:2] == ("GET", "https://api.runscope.com/buckets/bucket/environments")
    assert calls[1][:2] == ("PUT", "https://api.runscope.com/buckets/bucket/environments/" + env["id"])
    current = {**env, "webhooks": [*written["webhooks"], "https://later.example/hook"]}
    replies.extend([(200, current), (200, env)])
    await RunscopeNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **state}, node_id="node")
    assert calls[-1][2]["json"]["webhooks"] == [*env["webhooks"], "https://later.example/hook"]


@pytest.mark.asyncio
async def test_runscope_callback_idempotent_and_missing_environment(wire):
    env = fixture("environment.json")
    config = {"bucket_key": "bucket", "environment_id": env["id"]}
    wire[1].append((200, {"data": [env]}))
    await RunscopeNode._register_external_webhook(webhook_url=env["webhooks"][0], credential=CREDENTIAL, config=config, node_id="node")
    assert len(wire[0]) == 1
    wire[1].append((200, {"data": []}))
    with pytest.raises(ValueError, match="not found"):
        await RunscopeNode._register_external_webhook(webhook_url="https://hooks.example/a", credential=CREDENTIAL, config=config, node_id="node")
    assert len(wire[0]) == 2


def test_runscope_documented_callback_agent_turn_and_filter():
    payload = fixture("test_completed.json")
    assert RunscopeNode.verify_webhook_signature(b'{}', {}, {}) is True
    assert RunscopeNode.filter_trigger_payload(payload, {})
    assert not RunscopeNode.filter_trigger_payload(payload, {"test_id": "different-test"})
    # Inherited shared environments deliver the child's environment UUID.
    assert RunscopeNode.filter_trigger_payload(payload, {"environment_id": "parent-env"})
    output = RunscopeNode.resolve_trigger_payload({**payload, "_webhook": {}}, {})
    assert "_webhook" not in output["data"]
    event = RunscopeNode.resolve_agent_event(output)
    for value in (payload["test_name"], payload["result"], payload["team_name"], payload["environment_name"], payload["test_id"], payload["test_run_id"], payload["test_run_url"]):
        assert value in event["text"]
    assert "foo" not in event["text"]
