"""ClickSend API contracts; live FlowCanvas testing requires a real account."""

import base64
import json
import re

import httpx
import pytest
from pydantic import ValidationError

from nodes.clicksend_node import (
    CONFIG_MODELS,
    OPERATIONS,
    ClickSendNode,
    ClickSendNodeConfig,
)
from nodes.tests.fixtures.clicksend.generate_catalog import catalog_from_spec


_ORIGINAL_CLIENT = httpx.AsyncClient


def _config(operation: str, **fields):
    return ClickSendNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": {
                "credential_type": "clicksend_api_key",
                "api_username": "admin@noclick.com",
                "api_key": "test-key",
            },
        }
    )


def _node(config: ClickSendNodeConfig):
    return ClickSendNode(
        "clicksend-1", "automation-clicksend", {}, config, user_id="u1"
    )


def _transport(monkeypatch, callback):
    monkeypatch.setattr(
        "nodes.clicksend_node.httpx.AsyncClient",
        lambda *args, **kwargs: _ORIGINAL_CLIENT(
            transport=httpx.MockTransport(callback)
        ),
    )


def test_catalog_and_connection_proof_cover_pinned_official_spec():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 174
    assert {operation["method"] for operation in OPERATIONS.values()} == {
        "GET",
        "POST",
        "PUT",
        "DELETE",
    }
    for name, operation in OPERATIONS.items():
        assert name == operation["name"]
        assert operation["path"].startswith("/")
        assert set(operation["path_params"]) == set(
            re.findall(r"\{([^{}]+)\}", operation["path"])
        )
        assert CONFIG_MODELS[name].model_fields["operation"].default == name
    assert ClickSendNode.connection_evidence.operation == "get_account"
    assert "account_post" not in OPERATIONS
    assert "forgot_password_verify_put" not in OPERATIONS
    assert "recharge_credit_card_put" not in OPERATIONS


def test_generator_excludes_secret_management_endpoints():
    spec = {
        "paths": {
            "/account": {
                "get": {"operationId": "AccountGet", "summary": "Get account"},
                "post": {"operationId": "AccountPost", "summary": "Create account"},
            },
            "/sms/send": {
                "post": {
                    "operationId": "SmsSendPost",
                    "summary": "Send SMS",
                    "parameters": [
                        {
                            "in": "body",
                            "name": "messages",
                            "required": True,
                            "schema": {"$ref": "#/definitions/Messages"},
                        }
                    ],
                }
            },
        },
        "definitions": {"Messages": {"required": ["messages"], "type": "object"}},
    }
    operations = catalog_from_spec(spec)["operations"]
    assert [op["name"] for op in operations] == ["get_account", "sms_send_post"]
    assert operations[1]["body_required_fields"] == ["messages"]


def test_required_body_and_path_fields_are_in_ui_schema():
    with pytest.raises(ValidationError):
        _config("sms_send_post")
    with pytest.raises(ValidationError):
        _config("lists_by_list_id_get")
    with pytest.raises(ValidationError):
        _config("sms_history_export_get")
    assert _config("get_account")


@pytest.mark.asyncio
async def test_account_request_uses_basic_username_and_key(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "response_code": "SUCCESS",
                "data": {"username": "admin@noclick.com", "balance": 10},
            },
        )

    _transport(monkeypatch, callback)
    output = await _node(_config("get_account")).execute({})
    assert output["data"]["data"]["username"] == "admin@noclick.com"
    assert str(seen[0].url) == "https://rest.clicksend.com/v3/account"
    assert seen[0].headers["Authorization"] == (
        "Basic " + base64.b64encode(b"admin@noclick.com:test-key").decode()
    )


@pytest.mark.asyncio
async def test_sms_request_validates_required_payload_and_server_error(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200, json={"response_code": "SUCCESS", "data": {"total_count": 1}}
        )

    _transport(monkeypatch, callback)
    body = {"messages": [{"source": "python", "body": "test", "to": "+14055555555"}]}
    output = await _node(_config("sms_send_post", body_json=json.dumps(body))).execute(
        {}
    )
    assert output["data"]["data"]["total_count"] == 1
    assert json.loads(seen[0].content) == body
    assert seen[0].method == "POST"

    with pytest.raises(ValueError, match="required keys: messages"):
        await _node(_config("sms_send_post", body_json="{}")).execute({})
    assert len(seen) == 1

    _transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "response_code": "INVALID_CREDENTIALS",
                "response_msg": "Invalid API key",
            },
        ),
    )
    with pytest.raises(ValueError, match="Invalid API key"):
        await _node(_config("get_account")).execute({})


@pytest.mark.asyncio
async def test_path_encoding_required_query_and_http_error(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(404, json={"response_msg": "List not found"})

    _transport(monkeypatch, callback)
    with pytest.raises(ValueError, match="ClickSend API error 404: List not found"):
        await _node(_config("lists_by_list_id_get", path_list_id="a/b")).execute({})
    assert seen[0].url.raw_path.endswith(b"/lists/a%2Fb")

    _transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"response_code": "SUCCESS"}),
    )
    result = await _node(
        _config(
            "sms_history_export_get",
            query_filename="history.csv",
            query_json='{"limit": 20}',
        )
    ).execute({})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_invalid_json_and_query_shape_fail_before_network(monkeypatch):
    seen = []
    _transport(monkeypatch, lambda request: seen.append(request) or httpx.Response(200))
    with pytest.raises(ValueError, match="valid JSON"):
        await _node(_config("sms_send_post", body_json="{")).execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await _node(_config("get_account", query_json="[1,2]")).execute({})
    assert seen == []
