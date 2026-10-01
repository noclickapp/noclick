"""HTTP contract tests for every Recurly workflow operation.

The mock transport checks authentication, versioning, paths, methods, payloads,
and response handling without creating charges or changing a merchant account.
"""

import base64
import json
import re

import httpx
import pytest

from nodes.recurly_node import API_ACCEPT, CONFIG_MODELS, OPERATIONS, RecurlyNode, RecurlyNodeConfig


def _node(operation, **fields):
    config = RecurlyNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {"credential_type": "recurly_api_key", "api_key": "sandbox_secret"},
    })
    return RecurlyNode("test", "automation-recurly", {}, config=config)


def _fields(name, spec):
    fields = {key: "code-sample" for key in re.findall(r"\{(\w+)\}", spec.path)}
    if spec.list_result:
        fields["limit"] = 5
    if name == "create_account":
        fields.update(code="sample", email="customer@example.com")
    if name == "update_account":
        fields.update(email="changed@example.com")
    if spec.json_body:
        fields["body_json"] = json.dumps({
            "create_plan": {"code": "sample", "name": "Sample", "currencies": [{"currency": "USD", "unit_amount": 10}], "interval_length": 1, "interval_unit": "months"},
            "update_plan": {"name": "Updated"},
            "create_subscription": {"plan_code": "sample", "account": {"code": "sample"}, "currency": "USD"},
            "update_subscription": {"collection_method": "manual"},
            "preview_subscription_change": {"quantity": 2},
            "create_subscription_change": {"quantity": 2},
        }[name])
    return fields


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(OPERATIONS))
async def test_each_operation_sends_documented_contract(monkeypatch, name):
    spec = OPERATIONS[name]
    seen = []

    def handle(request):
        seen.append(request)
        if spec.list_result:
            return httpx.Response(200, json={"object": "list", "data": [{"id": "one"}], "has_more": True, "next": "https://v3.recurly.com/next"})
        return httpx.Response(201 if spec.method == "POST" else 200, json={"id": "one"})

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr("nodes.recurly_node.httpx.AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))

    result = await _node(name, **_fields(name, spec)).execute({})
    assert result["status"] == "success"
    assert result["action"] == name
    assert result["timing_ms"]["api_request"] >= 0
    assert len(seen) == 1
    request = seen[0]
    assert request.method == spec.method
    assert request.url.host == "v3.recurly.com"
    assert request.url.path == re.sub(r"\{\w+\}", "code-sample", spec.path)
    assert request.headers["Accept"] == API_ACCEPT
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"sandbox_secret:").decode()
    if spec.list_result:
        assert request.url.params["limit"] == "5"
        assert result["has_more"] is True
        assert result["next"].startswith("https://v3.recurly.com/")
    elif spec.json_body:
        assert isinstance(json.loads(request.content), dict)
    elif name == "cancel_subscription":
        assert request.content == b""


@pytest.mark.asyncio
async def test_account_fields_and_advanced_body(monkeypatch):
    captured = []
    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.recurly_node.httpx.AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: (captured.append(request), httpx.Response(201, json={"code": "sample"}))[1]),
        **kwargs,
    ))
    result = await _node("create_account", code="sample", email="typed@example.com", extra_json='{"email":"overridden@example.com","tax_exempt":true}').execute({})
    assert result["status"] == "success"
    assert json.loads(captured[0].content) == {"code": "sample", "email": "typed@example.com", "tax_exempt": True}


@pytest.mark.asyncio
async def test_api_error_is_structured_and_does_not_leak_key(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.recurly_node.httpx.AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(422, json={"error": {"type": "validation", "message": "Invalid code"}})),
        **kwargs,
    ))
    result = await _node("get_account", account_id="code-missing").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 422
    assert result["error"] == "Invalid code"
    assert result["error_code"] == "validation"
    assert "sandbox_secret" not in str(result)


@pytest.mark.asyncio
async def test_rejects_bad_inputs_before_network():
    with pytest.raises(ValueError, match="Invalid account_id"):
        await _node("get_account", account_id="../other").execute({})
    with pytest.raises(ValueError, match="valid JSON"):
        await _node("create_plan", body_json="{").execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await _node("create_plan", body_json="[]").execute({})


def test_schema_exposes_every_operation_and_masks_key():
    assert len(CONFIG_MODELS) == len(OPERATIONS) == 23
    schema = RecurlyNode.get_config_schema()
    credential = schema["$defs"]["RecurlyApiKeyCredential"]
    assert credential["properties"]["api_key"]["ui:widget"] == "password"
    assert set(CONFIG_MODELS) == {model.model_fields["operation"].default for model in CONFIG_MODELS.values()}
