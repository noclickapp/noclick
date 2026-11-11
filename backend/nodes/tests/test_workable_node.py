"""Mocked contract tests for every Workable operation in the official reference."""

import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import workable_node as module
from nodes.workable_node import (
    WORKABLE_CONFIGS,
    WORKABLE_OPERATIONS,
    WorkableAccessTokenCredential,
    WorkableNode,
    WorkableNodeConfig,
)


def _node(operation, credential=None, **values):
    config = WORKABLE_CONFIGS[operation](**values)
    full = WorkableNodeConfig(
        config=config,
        credentials=credential
        or WorkableAccessTokenCredential(access_token="test-token", subdomain="acme"),
    )
    return WorkableNode("test", "automation-workable", {}, config=full)


def _values(spec):
    values = {}
    for parameter in spec["parameters"]:
        if not parameter["required"]:
            continue
        values[parameter["name"]] = {
            "integer": 17,
            "boolean": True,
            "array": ["a", "b"],
        }.get(parameter["type"], "test value")
    if spec["operation"] == "webhook-subscriptions":
        values["body"] = json.dumps({"target": "https://example.test/hook", "event": "employee_created"})
        return values
    if spec["has_body"]:
        values["body"] = json.dumps({"example": True})
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", WORKABLE_OPERATIONS)
async def test_each_documented_operation_uses_its_method_path_and_bearer_token(
    operation, monkeypatch
):
    spec = WORKABLE_OPERATIONS[operation]
    seen = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: (
                    seen.append(request),
                    httpx.Response(200, json={"ok": True}),
                )[-1]
            ),
            **kw,
        ),
    )
    values = _values(spec)
    result = await _node(operation, **values).execute({})
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["timing_ms"]["api_request"] >= 0
    request = seen.pop()
    assert request.method == spec["method"]
    assert request.url.host == (
        "workable.com" if spec["global_host"] else "acme.workable.com"
    )
    assert request.headers["Authorization"] == "Bearer test-token"
    expected_path = spec["path"].replace("{subdomain}", "acme")
    for parameter in spec["parameters"]:
        if parameter["in"] == "path":
            expected_path = expected_path.replace(
                "{" + parameter["name"] + "}",
                quote(str(values[parameter["name"]]), safe=""),
            )
        elif parameter["in"] == "query" and parameter["required"]:
            assert parameter["name"] in request.url.params
    assert request.url.raw_path.split(b"?")[0].decode() == "/spi/v3" + expected_path
    if spec["has_body"]:
        assert json.loads(request.content) == ({"target": "https://example.test/hook", "event": "employee_created"} if operation == "webhook-subscriptions" else {"example": True})


@pytest.mark.asyncio
async def test_path_segment_is_encoded(monkeypatch):
    operation = next(
        name
        for name, spec in WORKABLE_OPERATIONS.items()
        if any(p["in"] == "path" and p["type"] == "string" for p in spec["parameters"])
    )
    spec = WORKABLE_OPERATIONS[operation]
    values = _values(spec)
    parameter = next(
        p for p in spec["parameters"] if p["in"] == "path" and p["type"] == "string"
    )
    values[parameter["name"]] = "a/b ?"
    seen = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: (
                    seen.append(request.url),
                    httpx.Response(200, json={}),
                )[-1]
            ),
            **kw,
        ),
    )
    assert (await _node(operation, **values).execute({}))["status"] == "success"
    assert "a%2Fb%20%3F" in str(seen[0])


def test_untrusted_subdomain_cannot_choose_an_api_host():
    for subdomain in ["evil.com", "foo/bar", "-bad", "bad-", "foo:443", "UPPER"]:
        with pytest.raises(ValidationError):
            WorkableAccessTokenCredential(access_token="token", subdomain=subdomain)


@pytest.mark.asyncio
async def test_api_error_and_invalid_json_are_reported(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, json={"error": "rate limit"})
            ),
            **kw,
        ),
    )
    result = await _node("get_accounts").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 429
    assert result["error"] == {"error": "rate limit"}
    operation = next(
        name for name, spec in WORKABLE_OPERATIONS.items() if spec["has_body"]
    )
    with pytest.raises(ValueError, match="valid JSON"):
        await _node(
            operation, **{**_values(WORKABLE_OPERATIONS[operation]), "body": "{"}
        ).execute({})


def test_schema_covers_the_catalog():
    schema = WorkableNode.get_config_schema()
    assert len(WORKABLE_OPERATIONS) == len(WORKABLE_CONFIGS) == 82
    assert "WorkableAccessTokenCredential" in schema["$defs"]
    for spec in WORKABLE_OPERATIONS.values():
        assert spec["reference"].startswith("https://workable.readme.io/reference/")
        assert spec["path"].startswith("/")
        assert spec["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.mark.parametrize("body", [None, {"event": "employee_created"}, {"target": "not-a-url", "event": "employee_created"}, {"target": "https://example.test/hook", "event": "invalid"}, {"target": "https://example.test/hook", "event": "candidate_created", "args": {}}])
def test_subscription_rejects_incomplete_or_invalid_body(body):
    with pytest.raises(ValidationError):
        WORKABLE_CONFIGS["webhook-subscriptions"](body=body)


def test_subscription_accepts_existing_json_string_config():
    config = WORKABLE_CONFIGS["webhook-subscriptions"](
        body='{"target":"https://example.test/hook","event":"employee_created"}')
    assert config.body.event == "employee_created"


# Real example deliveries from Workable's candidate-events and employee-events pages.
EVENTS = json.loads((Path(__file__).parent / "fixtures/workable/events.json").read_text())


def test_trigger_schema_and_lifecycle_fields():
    schema = module.WorkableOnEventConfig.model_json_schema()
    assert schema["properties"]["operation"]["x-is-trigger"] is True
    assert schema["x-requires-webhook"] is True
    config = module.WorkableOnEventConfig(external_webhook_id=42, signing_secret="secret")
    assert config.model_dump()["signing_secret"] == "secret"
    assert config.external_webhook_id == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", module.WORKABLE_TRIGGER_EVENTS)
async def test_trigger_registers_and_unregisters_documented_subscription(event_type, monkeypatch):
    seen = []
    real_client = httpx.AsyncClient
    def respond(request):
        seen.append(request)
        return httpx.Response(201, json={"id": 42}) if request.method == "POST" else httpx.Response(204)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    config = {"operation": "on_event", "event_type": event_type, "job_shortcode": "GROOV005", "stage_slug": "hired"}
    credential = {"access_token": "test-token", "subdomain": "acme"}
    registered = await WorkableNode._register_external_webhook(webhook_url="https://example.test/hook", credential=credential, config=config, node_id="test")
    assert registered == {"external_webhook_id": "42", "signing_secret": "test-token"}
    body = json.loads(seen[0].content)
    assert body["target"] == "https://example.test/hook"
    assert body["event"] == event_type
    assert seen[0].url == "https://acme.workable.com/spi/v3/subscriptions"
    assert seen[0].headers["authorization"] == "Bearer test-token"
    if event_type.startswith("candidate_"):
        assert body["args"] == {"account_id": "acme", "job_shortcode": "GROOV005", "stage_slug": "hired"}
    else:
        assert "args" not in body
    await WorkableNode._unregister_external_webhook(credential=credential, config={**config, **registered}, node_id="test")
    assert seen[1].method == "DELETE"
    assert seen[1].url == "https://acme.workable.com/spi/v3/subscriptions/42"


@pytest.mark.asyncio
async def test_registration_failure_and_deleted_subscription(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(409)), **kw))
    kwargs = dict(credential={"access_token": "test-token", "subdomain": "acme"}, config={"operation": "on_event"}, node_id="test")
    with pytest.raises(httpx.HTTPStatusError):
        await WorkableNode._register_external_webhook(webhook_url="https://example.test/hook", **kwargs)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(404)), **kw))
    await WorkableNode._unregister_external_webhook(**{**kwargs, "config": {"external_webhook_id": "42"}})


@pytest.mark.parametrize("event", EVENTS)
def test_documented_deliveries_signature_routing_and_agent_turn(event):
    payload = EVENTS[event]["body"]
    raw = json.dumps(payload).encode()
    signature = hmac.new(b"account-token", raw, hashlib.sha256).hexdigest()
    config = {"operation": "on_event", "event_type": "timeoff_updated" if event.startswith("timeoff_") else event, "signing_secret": "account-token"}
    headers = {"X-Workable-Signature": signature}
    assert WorkableNode.verify_webhook_signature(raw, headers, config)
    assert WorkableNode.verify_webhook_signature(raw, {"x-workable-signature": signature}, config)
    assert not WorkableNode.verify_webhook_signature(raw+b" ", headers, config)
    assert not WorkableNode.verify_webhook_signature(raw, headers, {"signing_secret": "other"})
    assert not WorkableNode.verify_webhook_signature(raw, {"X-Workable-Signature": "é"}, config)
    assert not WorkableNode.verify_webhook_signature(raw, {}, config)
    assert not WorkableNode.verify_webhook_signature(raw, headers, {})
    assert WorkableNode.filter_trigger_payload(payload, config)
    assert not WorkableNode.filter_trigger_payload(payload, {"event_type": "unknown"})
    output = WorkableNode.resolve_trigger_payload(payload, config)
    assert output is payload
    agent = WorkableNode.resolve_agent_event(output)
    assert agent["conversation_key"] == ("candidate:3fc9a80f" if event == "candidate_moved" else "employee:"+payload["id"])
    assert payload["event_type"].replace("_", " ") in agent["text"]
    assert "To act:" in agent["text"]
    assert payload["fired_at"] in agent["text"]
    if event == "candidate_moved":
        assert "Jj Botha" in agent["text"] and "Office Manager" in agent["text"]
        assert payload["data"]["profile_url"] in agent["text"]
    if event.startswith("timeoff_"):
        assert payload["data"]["updated_by"] in agent["text"]


@pytest.mark.asyncio
async def test_trigger_manual_run_has_no_event():
    full = WorkableNodeConfig(config=module.WorkableOnEventConfig())
    node = WorkableNode("test", "automation-workable", {}, config=full)
    output = await node.execute({"unrelated": {"secret": "never copy"}})
    assert output["status"] == "no_event" and output["data"] == {}
    assert WorkableNode.resolve_agent_event(output) is None


def test_trigger_registration_fingerprint_changes_with_candidate_filters():
    base = {"operation": "on_event", "event_type": "candidate_created"}
    assert WorkableNode.registration_fingerprint_fields(base) != WorkableNode.registration_fingerprint_fields({**base, "stage_slug": "hired"})
    employee = {"operation": "on_event", "event_type": "employee_created"}
    assert WorkableNode.registration_fingerprint_fields(employee) == WorkableNode.registration_fingerprint_fields({**employee, "stage_slug": "hired"})
