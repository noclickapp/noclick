"""Offline endpoint, response and manual-connect regressions."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import dynamic_mockups_node as native
from nodes.core.registry import NodeFactory

TOKEN = "dynamic-mockups-test-secret"
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/dynamic-mockups/operations.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    instance = NodeFactory.create_node(
        node_id="dynamic-mockups-test",
        node_type="automation-dynamic-mockups",
        node_data={
            "config": config,
            "credentials": credentials
            or {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN},
        },
    )
    instance.emit = AsyncMock()
    return instance


def transport(monkeypatch, response):
    calls = []

    def handle(request):
        calls.append(request)
        return (
            response(request)
            if callable(response)
            else httpx.Response(200, json=response)
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES, ids=lambda operation: "dynamic-mockups:" + operation)
async def test_dynamic_mockups_each_documented_endpoint(monkeypatch, operation):
    fixture = FIXTURES[operation]
    calls = transport(monkeypatch, fixture["response"])
    instance = node({"operation": operation, **fixture["config"]})
    result = await instance.execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == fixture["method"]
    path = fixture["path"]
    for key in fixture["path_fields"]:
        path = path.replace("{" + key + "}", fixture["config"][key])
    assert str(request.url).split("?")[0] == native.BASE + path
    assert (
        request.headers["x-api-key"] == TOKEN
        and request.headers["Accept"] == "application/json"
    )
    assert "authorization" not in request.headers
    expected_query = {
        key: str(fixture["config"][key]).lower()
        if isinstance(fixture["config"][key], bool)
        else str(fixture["config"][key])
        for key in fixture["query"]
        if key in fixture["config"]
    }
    assert dict(request.url.params) == expected_query
    if request.method == "POST":
        assert json.loads(request.content) == {
            key: value
            for key, value in fixture["config"].items()
            if key not in fixture["query"] and key not in fixture["path_fields"]
        }
    else:
        assert request.content == b""
    assert result["success"] is True and result["status"] == "success"
    assert result["data"] == fixture["response"]["data"]
    instance.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_dynamic_mockups_false_query_and_nested_write_values_survive(monkeypatch):
    calls = transport(monkeypatch, {"success": True, "data": [], "message": ""})
    await node(
        {
            "operation": "list_mockups",
            "include_all_catalogs": False,
            "name": "Mug + shirt & tote",
        }
    ).execute({})
    assert dict(calls[0].url.params) == {
        "include_all_catalogs": "false",
        "name": "Mug + shirt & tote",
    }
    await node(
        {
            "operation": "delete_psd",
            "psd_uuid": "owned-psd",
            "delete_related_mockups": False,
        }
    ).execute({})
    assert json.loads(calls[1].content) == {
        "psd_uuid": "owned-psd",
        "delete_related_mockups": False,
    }
    smart_object = {
        "uuid": "owned-layer",
        "asset": {"url": "https://example.com/design.png", "rotate": 0},
        "pattern": {"enabled": False},
        "adjustment_layers": {"opacity": 0},
    }
    await node(
        {
            "operation": "create_render",
            "mockup_uuid": "owned-template",
            "smart_objects": [smart_object],
        }
    ).execute({})
    assert json.loads(calls[2].content)["smart_objects"][0] == smart_object


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_dynamic_mockups_http_failures_do_not_become_success(monkeypatch, status):
    calls = transport(
        monkeypatch,
        lambda request: httpx.Response(
            status,
            json={"message": "Provider rejected " + TOKEN},
            headers={"Location": "https://example.com/"},
        ),
    )
    result = await node({"operation": "list_catalogs"}).execute({})
    assert len(calls) == 1
    assert result == {
        "status": "error",
        "success": False,
        "http_status": status,
        "message": "Provider rejected [redacted]",
    }


@pytest.mark.asyncio
async def test_dynamic_mockups_error_envelope_and_empty_account(monkeypatch):
    transport(monkeypatch, {"success": False, "data": [], "message": "Invalid API key"})
    result = await node({"operation": "list_catalogs"}).execute({})
    assert result["status"] == "error" and result["message"] == "Invalid API key"
    transport(monkeypatch, {"success": True, "data": [], "message": ""})
    result = await node({"operation": "list_catalogs"}).execute({})
    assert result["data"] == [] and result["success"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [None, [], {"success": True}, {"data": [], "success": "true"}]
)
async def test_dynamic_mockups_malformed_json_envelope_is_unverified(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(
        ValueError, match="could not be verified|unexpected JSON response"
    ):
        await node({"operation": "list_catalogs"}).execute({})


@pytest.mark.asyncio
async def test_dynamic_mockups_timeout_never_retries_a_submission(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)

    calls = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect submitted jobs") as error:
        await node(
            {
                "operation": "create_motion_mockup",
                "start_image_url": "https://example.com/start.png",
            }
        ).execute({})
    assert len(calls) == 1 and TOKEN not in str(error.value)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_mockup", "uuid": "../other"},
        {"operation": "get_motion_status", "requestId": "abc?api_key=evil"},
        {"operation": "create_ai_mockup"},
        {"operation": "create_ai_mockup", "prompt": "A shirt", "style": "ugc"},
        {
            "operation": "create_ai_mockup",
            "prompt": "A shirt",
            "collections": [{"name": "new", "uuid": "existing"}],
        },
        {"operation": "list_blank_products", "per_page": 101},
        {
            "operation": "create_motion_mockup",
            "start_image_url": "https://example.com/start.png",
            "model": "unknown",
        },
    ],
)
def test_dynamic_mockups_rejects_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_dynamic_mockups_manual_credential_default_and_shape():
    from nodes.core.credential_connect import shape_credential

    shaped, errors, resolved = shape_credential(
        native.CREDENTIAL_TYPE, {"api_key": "  " + TOKEN + "  "}
    )
    assert not errors
    assert shaped["api_key"] == TOKEN
    assert resolved[1].model_validate(shaped).credential_type == native.CREDENTIAL_TYPE
    with pytest.raises(ValidationError):
        native.DynamicMockupsAPIKeyCredential(
            api_key=TOKEN, credential_type="other_provider"
        )
    evidence = native.DynamicMockupsNode.connection_evidence
    assert evidence.operation == "list_catalogs" and not evidence.operation_arguments
