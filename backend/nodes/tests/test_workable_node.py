"""Mocked contract tests for every Workable operation in the official reference."""

import json
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
