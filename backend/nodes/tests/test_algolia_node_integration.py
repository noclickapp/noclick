"""Contracts for Algolia's pinned OpenAPI routes and credential transport."""

import json
import re
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.core.binary_output import BinaryOutput

from nodes.algolia_node import (
    CONFIG_MODELS,
    OPERATIONS,
    AlgoliaApiKeyCredential,
    AlgoliaNode,
    AlgoliaNodeConfig,
    _parameter_field,
)


def make_node(config, credential=None):
    return AlgoliaNode(
        node_id="algolia-test", node_type="automation-algolia", node_data={},
        config=AlgoliaNodeConfig(
            config=config,
            credentials=credential or AlgoliaApiKeyCredential(application_id="TESTAPP123", api_key="secret"),
        ),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name,op", list(OPERATIONS.items()))
async def test_every_action_dispatches_to_official_route(name, op):
    path_args = {field: "sample/id" for field in re.findall(r"\{([^}]+)\}", op["path"])}
    required = {
        _parameter_field(p["name"], p["in"]): "sample"
        for p in op["required_params"]
    }
    kwargs = {**path_args, **required}
    if op["body_required"]:
        kwargs["body_json"] = '{"sample":true}'
    config = CONFIG_MODELS[name](**kwargs)
    node = make_node(config)
    path = op["path"]
    for field, value in path_args.items():
        path = path.replace("{" + field + "}", quote(value, safe=""))
    url = AlgoliaNode._base_url(op["family"], node.config.credentials) + path
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op["method"], url).mock(
            return_value=httpx.Response(200, json={"results": [{"objectID": "1"}]}))
        result = await node.execute({})
    assert route.called
    assert route.calls[0].request.headers["X-Algolia-Application-Id"] == "TESTAPP123"
    assert route.calls[0].request.headers["X-Algolia-API-Key"] == "secret"
    assert result["data"] == {"results": [{"objectID": "1"}]}


@pytest.mark.asyncio
async def test_eu_analytics_required_query_and_optional_params():
    config = CONFIG_MODELS["analytics_get_top_searches"](
        query_index="products", query_json='{"limit":5,"index":"overridden"}'
    )
    credential = AlgoliaApiKeyCredential(application_id="TESTAPP123", api_key="secret", region="eu")
    node = make_node(config, credential)
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://analytics.de.algolia.com/2/searches").mock(
            return_value=httpx.Response(200, json={"searches": []}))
        await node.execute({})
    assert route.calls[0].request.url.params["index"] == "products"
    assert route.calls[0].request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_eu_ingestion_and_agent_studio_host_paths():
    credential = AlgoliaApiKeyCredential(application_id="TESTAPP123", api_key="secret", region="eu")
    for operation, url in (
        ("ingestion_list_authentications", "https://data.eu.algolia.com/1/authentications"),
        ("agent_studio_list_agents", "https://TESTAPP123.algolia.net/agent-studio/1/agents"),
    ):
        with respx.mock(assert_all_called=True) as router:
            route = router.get(url).mock(return_value=httpx.Response(200, json={"items": []}))
            await make_node(CONFIG_MODELS[operation](), credential).execute({})
        assert route.called


@pytest.mark.asyncio
async def test_array_body_and_required_header():
    events = [{"eventType": "click", "eventName": "clicked", "index": "products"}]
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://insights.us.algolia.io/1/events").mock(
            return_value=httpx.Response(200, json={"status": 200}))
        await make_node(CONFIG_MODELS["insights_push_events"](body_json=json.dumps(events))).execute({})
    assert json.loads(route.calls[0].request.content) == events

    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://TESTAPP123.algolia.net/1/clusters/mapping").mock(
            return_value=httpx.Response(200, json={"updatedAt": "now"}))
        await make_node(CONFIG_MODELS["search_assign_user_id"](
            header_x_algolia_user_id="user-1", body_json="{}"
        )).execute({})
    assert route.calls[0].request.headers["X-Algolia-User-ID"] == "user-1"


def test_application_id_cannot_control_host():
    for bad in ("evil.test/path", "evil.test", "x@evil.test", "x:443", "x?y=1"):
        with pytest.raises(ValidationError):
            AlgoliaApiKeyCredential(application_id=bad, api_key="secret")


@pytest.mark.asyncio
async def test_invalid_json_rejected_before_network():
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node(CONFIG_MODELS["search_search_single_index"](
            indexName="products", body_json="{broken"
        )).execute({})


@pytest.mark.asyncio
async def test_api_error_is_actionable():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://TESTAPP123.algolia.net/1/indexes").mock(
            return_value=httpx.Response(403, json={"message": "ACL missing"}))
        with pytest.raises(ValueError, match="Algolia API error 403: ACL missing"):
            await make_node(CONFIG_MODELS["search_list_indices"]()).execute({})


@pytest.mark.asyncio
async def test_non_json_transport_output_uses_binary_marker():
    payload = b"\x00\x01\xff"
    with respx.mock(assert_all_called=True) as router:
        router.get("https://TESTAPP123.algolia.net/1/indexes").mock(
            return_value=httpx.Response(
                200, content=payload, headers={"content-type": "application/octet-stream"}
            )
        )
        result = await make_node(CONFIG_MODELS["search_list_indices"]()).execute({})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == payload
    assert result["data"].content_type == "application/octet-stream"
    assert result["data"].filename == "algolia-response"
