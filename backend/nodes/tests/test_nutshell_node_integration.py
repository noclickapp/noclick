"""Nutshell REST route and Basic authentication contract checks."""

import json
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx

from nodes.nutshell_node import (
    API_BASE,
    CONFIG_MODELS,
    OPERATIONS,
    PATH_VARIABLE_RE,
    NutshellApiKeyCredential,
    NutshellNode,
    NutshellNodeConfig,
    _field_name,
)


def make_node(config):
    return NutshellNode(
        node_id="nutshell-test",
        node_type="automation-nutshell",
        node_data={},
        config=NutshellNodeConfig(
            config=config,
            credentials=NutshellApiKeyCredential(
                email="person@example.com", api_key="secret-key"
            ),
        ),
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


def sample_config(name, op):
    fields = {
        _field_name(variable): "sample/id"
        for variable in PATH_VARIABLE_RE.findall(op["path"])
    }
    if op["body_required"]:
        fields["body_json"] = (
            '[{"op":"replace","path":"/contacts/0/name","value":"Ada"}]'
            if op["content_type"] == "application/json-patch+json"
            else '{"sample":{"value":"hello"}}'
        )
    return CONFIG_MODELS[name](**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,op", list(OPERATIONS.items()))
async def test_every_action_uses_its_documented_route_and_basic_auth(name, op):
    path = op["path"]
    for variable in PATH_VARIABLE_RE.findall(path):
        path = path.replace("{" + variable + "}", quote("sample/id", safe=""))
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op["method"], API_BASE + path).mock(
            return_value=httpx.Response(200, json={"items": [{"id": "one"}]})
        )
        result = await make_node(sample_config(name, op)).execute({})
    request = route.calls[0].request
    assert (
        request.headers["Authorization"]
        == "Basic cGVyc29uQGV4YW1wbGUuY29tOnNlY3JldC1rZXk="
    )
    assert request.url.host == "app.nutshell.com"
    if op["body_required"]:
        assert request.headers["Content-Type"] == op["content_type"]
        assert json.loads(request.content)
    assert result["status"] == "success"
    assert result["operation"] == name
    assert result["data"]["items"][0]["id"] == "one"
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
async def test_json_patch_query_filters_empty_response_and_errors():
    patch_op = "contacts_people_update_a_contact"
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node(CONFIG_MODELS[patch_op](path_id="1", body_json="{")).execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await make_node(CONFIG_MODELS["list_accounts"](query_json="[]")).execute({})
    with pytest.raises(ValueError, match="scalar values"):
        await make_node(
            CONFIG_MODELS["list_accounts"](query_json='{"sort":[{"bad":1}]}')
        ).execute({})
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API_BASE + "/accounts").mock(
            return_value=httpx.Response(200, json={"accounts": []})
        )
        result = await make_node(
            CONFIG_MODELS["list_accounts"](
                query_json='{"filter":{"name":"Ada"},"sort":["name","id"]}'
            )
        ).execute({})
    assert route.calls[0].request.url.params["filter[name]"] == "Ada"
    assert route.calls[0].request.url.params.get_list("sort") == ["name", "id"]
    assert result["data"] == {"accounts": []}

    with respx.mock:
        respx.get(API_BASE + "/accounts").mock(return_value=httpx.Response(204))
        result = await make_node(CONFIG_MODELS["list_accounts"]()).execute({})
    assert result["data"] == {"ok": True}
    with respx.mock:
        respx.get(API_BASE + "/accounts").mock(
            return_value=httpx.Response(401, json={"message": "unauthorized"})
        )
        with pytest.raises(ValueError, match="Nutshell API error 401"):
            await make_node(CONFIG_MODELS["list_accounts"]()).execute({})


def test_catalog_is_bounded_to_official_json_rest_actions():
    assert len(OPERATIONS) == 113
    assert len({op["name"] for op in OPERATIONS.values()}) == 113
    assert NutshellNode.connection_evidence.operation == "list_accounts"
    for op in OPERATIONS.values():
        assert op["docs"].startswith("https://developers.nutshell.com/reference/")
        assert op["path"].startswith("/")
        assert "{" not in PATH_VARIABLE_RE.sub("", op["path"])
        assert op["category"]
        assert not op["path"].endswith("/export")
