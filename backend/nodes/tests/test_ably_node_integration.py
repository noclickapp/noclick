"""Ably REST action routing, authentication, and response contracts."""

import json
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx

from nodes.ably_node import (
    API_BASE,
    CONFIG_MODELS,
    OPERATIONS,
    PATH_VARIABLE_RE,
    AblyApiKeyCredential,
    AblyNode,
    AblyNodeConfig,
    _field_name,
)


def make_node(config, api_key="app.key:secret"):
    return AblyNode(
        node_id="ably-test",
        node_type="automation-ably",
        node_data={},
        config=AblyNodeConfig(
            config=config,
            credentials=AblyApiKeyCredential(api_key=api_key),
        ),
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


def sample_config(name, operation):
    fields = {
        _field_name(variable): "sample/id"
        for variable in PATH_VARIABLE_RE.findall(operation["path"])
    }
    if name == "batch_presence":
        fields["channels"] = "channel1,channel2,channel3"
    if operation["body_required"]:
        fields["body_json"] = '{"name":"test-event","data":{"value":1}}'
    return CONFIG_MODELS[name](**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation", list(OPERATIONS.items()))
async def test_each_action_uses_documented_route_and_basic_auth(name, operation):
    path = operation["path"]
    for variable in PATH_VARIABLE_RE.findall(path):
        path = path.replace("{" + variable + "}", quote("sample/id", safe=""))
    with respx.mock(assert_all_called=True) as router:
        route = router.request(operation["method"], API_BASE + path).mock(
            return_value=httpx.Response(200, json={"items": [{"id": "one"}]})
        )
        result = await make_node(sample_config(name, operation)).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Basic YXBwLmtleTpzZWNyZXQ="
    assert request.url.host == "rest.ably.io"
    if name == "batch_presence":
        assert request.url.params["channels"] == "channel1,channel2,channel3"
    if operation["body_required"]:
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content)["name"] == "test-event"
    assert result["status"] == "success"
    assert result["operation"] == name
    assert result["data"]["items"][0]["id"] == "one"
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
async def test_history_query_pagination_empty_response_and_errors():
    history = CONFIG_MODELS["get_message_history"](
        path_channel_id="orders",
        query_json='{"limit":50,"channels":["orders","alerts"]}',
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API_BASE + "/channels/orders/messages").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "message-1"}],
                headers={"Link": '</channels/orders/messages?page=2>; rel="next"'},
            )
        )
        result = await make_node(history).execute({})
    params = route.calls[0].request.url.params
    assert params["limit"] == "50"
    assert params.get_list("channels") == ["orders", "alerts"]
    assert result["data"]["items"][0]["id"] == "message-1"
    assert result["pagination"]["next"] == API_BASE + "/channels/orders/messages?page=2"

    with respx.mock:
        respx.get(API_BASE + "/time").mock(return_value=httpx.Response(204))
        assert (await make_node(CONFIG_MODELS["get_time"]()).execute({}))["data"] == {
            "ok": True
        }
    with respx.mock:
        respx.get(API_BASE + "/channels").mock(
            return_value=httpx.Response(401, json={"error": "invalid key"})
        )
        with pytest.raises(ValueError, match="Ably API error 401"):
            await make_node(CONFIG_MODELS["list_channels"]()).execute({})


@pytest.mark.asyncio
async def test_invalid_input_is_rejected_before_http():
    with pytest.raises(ValueError, match="appId.keyId:secret"):
        await make_node(CONFIG_MODELS["list_channels"](), api_key="malformed").execute(
            {}
        )
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node(
            CONFIG_MODELS["publish_message"](path_channel_id="orders", body_json="{")
        ).execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await make_node(CONFIG_MODELS["list_channels"](query_json="[]")).execute({})
    with pytest.raises(ValueError, match="scalars or arrays"):
        await make_node(
            CONFIG_MODELS["list_channels"](query_json='{"bad":{"nested":1}}')
        ).execute({})


def test_catalog_is_derived_from_official_rest_reference():
    assert len(OPERATIONS) == 32
    assert AblyNode.connection_evidence.operation == "list_channels"
    assert len({operation["name"] for operation in OPERATIONS.values()}) == 32
    for operation in OPERATIONS.values():
        assert operation["docs"].startswith("https://ably.com/docs/api/rest-api#")
        assert operation["path"].startswith("/")
        assert "{" not in PATH_VARIABLE_RE.sub("", operation["path"])


def test_batch_presence_requires_channels():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="channels"):
        CONFIG_MODELS["batch_presence"]()
    with pytest.raises(ValidationError, match="at least 1 character"):
        CONFIG_MODELS["batch_presence"](channels="")


@pytest.mark.asyncio
async def test_batch_presence_rejects_duplicate_channels_before_http():
    with pytest.raises(ValueError, match="Channels field"):
        await make_node(
            CONFIG_MODELS["batch_presence"](
                channels="channel1,channel2,channel3",
                query_json='{"channels":"channel1"}',
            )
        ).execute({})
