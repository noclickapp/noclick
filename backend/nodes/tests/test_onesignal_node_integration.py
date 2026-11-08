"""Every documented OneSignal action routes to its official API endpoint."""

import json
import re
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx

from nodes.onesignal_node import (
    API_BASE, CONFIG_MODELS, OPERATIONS, OneSignalCredential,
    OneSignalNode, OneSignalNodeConfig, _field_name,
)


def make_node(config, *, app_id="app-123", app_key="app-key", org_key="org-key"):
    return OneSignalNode(
        node_id="onesignal-test", node_type="automation-onesignal", node_data={},
        config=OneSignalNodeConfig(config=config, credentials=OneSignalCredential(
            app_id=app_id, app_api_key=app_key, organization_api_key=org_key,
        )),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


def sample_config(name, op):
    fields = {
        _field_name(variable, "path"): "example"
        for variable in re.findall(r"\{([^}]+)\}", op["path"])
        if variable != "app_id"
    }
    fields.update({
        _field_name(param["name"], "query"): "example"
        for param in op["query_params"] if param["required"]
    })
    fields.update({
        _field_name(param["name"], "header"): "example"
        for param in op["header_params"] if param["required"]
    })
    if op["body_type"] and op["method"] in {"POST", "PUT", "PATCH"}:
        fields["body_input"] = '{"example":true}'
    return CONFIG_MODELS[name](**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,op", list(OPERATIONS.items()))
async def test_every_documented_action_reaches_the_correct_endpoint(name, op):
    path = op["path"]
    for variable in re.findall(r"\{([^}]+)\}", path):
        path = path.replace("{" + variable + "}", quote("app-123" if variable == "app_id" else "example", safe=""))
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op["method"], API_BASE + path).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await make_node(sample_config(name, op)).execute({})
    assert route.called, name
    request = route.calls[0].request
    if op["auth"] == "app":
        assert request.headers["Authorization"] == "Key app-key"
    elif op["auth"] == "organization":
        assert request.headers["Authorization"] == "Key org-key"
    else:
        assert "Authorization" not in request.headers
    if "app_id" in op["query_template"]:
        assert request.url.params["app_id"] == "app-123"
    if op["body_app_id"] and request.content:
        assert json.loads(request.content)["app_id"] == "app-123"
    assert result["status"] == "success"
    assert result["operation"] == name
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
async def test_message_channel_and_query_fields():
    config = CONFIG_MODELS["send_push_notification"](body_input='{"contents":{"en":"Hello"}}')
    with respx.mock(assert_all_called=True) as router:
        route = router.post(API_BASE + "/notifications").mock(
            return_value=httpx.Response(200, json={"id": "notification-1"})
        )
        await make_node(config).execute({})
    assert route.calls[0].request.url.params["c"] == "push"
    assert json.loads(route.calls[0].request.content)["app_id"] == "app-123"

    config = CONFIG_MODELS["view_journeys"](query_limit="5", query_json='{"cursor":"next"}')
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API_BASE + "/apps/app-123/journeys").mock(
            return_value=httpx.Response(200, json={"journeys": []})
        )
        await make_node(config).execute({})
    assert route.calls[0].request.url.params["limit"] == "5"
    assert route.calls[0].request.url.params["cursor"] == "next"


@pytest.mark.asyncio
async def test_connection_can_use_organization_key_without_app_key():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API_BASE + "/apps").mock(
            return_value=httpx.Response(200, json=[{"id": "app-123"}])
        )
        result = await make_node(CONFIG_MODELS["test_connection"](), app_key=None).execute({})
    assert route.calls[0].request.headers["Authorization"] == "Key org-key"
    assert result["data"] == {"items": [{"id": "app-123"}]}


@pytest.mark.asyncio
async def test_organization_actions_can_target_another_app():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API_BASE + "/apps/other-app/auth/tokens").mock(
            return_value=httpx.Response(200, json={"tokens": []})
        )
        await make_node(CONFIG_MODELS["view_api_keys"](path_app_id="other-app")).execute({})
    assert route.called

    with respx.mock(assert_all_called=True) as router:
        route = router.post(API_BASE + "/templates/example/copy_to_app").mock(
            return_value=httpx.Response(200, json={"id": "copy-1"})
        )
        await make_node(CONFIG_MODELS["copy_template_to_another_app"](
            path_template_id="example", query_app_id="other-app", body_input="{}",
        )).execute({})
    assert route.calls[0].request.url.params["app_id"] == "other-app"


@pytest.mark.asyncio
async def test_missing_credentials_bad_json_and_api_error():
    with pytest.raises(ValueError, match="App API Key"):
        await make_node(CONFIG_MODELS["view_journeys"](), app_key=None).execute({})
    with pytest.raises(ValueError, match="Organization API Key"):
        await make_node(CONFIG_MODELS["view_apps"](), org_key=None).execute({})
    with pytest.raises(ValueError, match="App ID"):
        await make_node(CONFIG_MODELS["view_journeys"](), app_id=None).execute({})
    with pytest.raises(ValueError, match="validation error"):
        CONFIG_MODELS["unsubscribe_with_token"](path_notification_id="notification-1")
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node(CONFIG_MODELS["send_push_notification"](body_input="{" )).execute({})
    with respx.mock(assert_all_called=True) as router:
        router.get(API_BASE + "/apps/app-123").mock(
            return_value=httpx.Response(403, json={"errors": ["forbidden"]})
        )
        with pytest.raises(ValueError, match="OneSignal API error 403"):
            await make_node(CONFIG_MODELS["test_connection"]()).execute({})
