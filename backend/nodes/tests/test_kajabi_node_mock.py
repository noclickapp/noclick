"""Kajabi wire tests against provider-authored examples.

Source URLs are recorded per fixture, pinned to Kajabi's official OpenAPI:
https://github.com/Kajabi/public_api_docs/blob/1f378e1a90f07fbf12202e9c36852183aed00763/openapi.yaml
Bodies are copied from the endpoint descriptions; offer mutations use the
provider's documented relationship-list response. No provider calls are made.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from nodes.kajabi_node import KajabiNode, KajabiNodeConfig

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/kajabi/responses.json").read_text()
)


def node(config, credentials=True):
    return KajabiNode(
        node_id="kajabi-test",
        node_type="automation-kajabi",
        node_data={},
        config=KajabiNodeConfig(
            config=config,
            credentials={
                "credential_type": "kajabi_access_token",
                "access_token": "test-token",
            }
            if credentials
            else None,
        ),
        sio=Mock(),
    )


async def run(config, payload, status=200):
    requests = []
    original = httpx.AsyncClient

    def transport(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return httpx.Response(status, text=payload)
        return httpx.Response(status, json=payload)

    with patch(
        "nodes.kajabi_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(transport=httpx.MockTransport(transport)),
    ):
        result = await node(config).execute({})
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_every_documented_operation(operation):
    f = FIXTURES[operation]
    result, requests = await run(f["config"], f["body"], f["status_code"])
    (request,) = requests
    assert request.method == f["method"]
    expected_path = (
        f["path"]
        .replace("{contact_id}", f["config"].get("contact_id", ""))
        .replace(
            "{id}",
            next((str(v) for k, v in f["config"].items() if k.endswith("_id")), ""),
        )
    )
    assert request.url.host == "api.kajabi.com"
    assert request.url.path == expected_path
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["Accept"] == "application/vnd.api+json"
    if f["request_body"] is None:
        assert not request.content
    else:
        assert request.headers["Content-Type"] == "application/vnd.api+json"
        assert json.loads(request.content) == f["request_body"]
    assert result["status"] == "success"
    assert result["data"] == f["body"]["data"]
    assert result["status_code"] == f["status_code"]
    assert result["timing_ms"]["total"] >= 0
    if "page_number" in f["config"]:
        assert request.url.params["page[number]"] == "2"
        assert request.url.params["page[size]"] == "10"


@pytest.mark.asyncio
async def test_list_filters_and_false_values_are_serialized():
    f = FIXTURES["list_offers"]
    result, requests = await run({**f["config"], "published": False}, f["body"])
    assert dict(requests[0].url.params) == {
        "page[number]": "2",
        "page[size]": "10",
        "filter[site_id]": "123",
        "filter[title_cont]": "course",
        "filter[published]": "false",
    }
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,field",
    [("replace_contact_tags", "tag_ids"), ("replace_contact_offers", "offer_ids")],
)
async def test_replace_can_clear_all_relationships(operation, field):
    result, requests = await run(
        {**FIXTURES[operation]["config"], field: []}, {"data": []}
    )
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"data": []}


@pytest.mark.asyncio
async def test_grant_default_sends_welcome_email():
    config = {
        k: v
        for k, v in FIXTURES["grant_offers"]["config"].items()
        if k != "send_customer_welcome_email"
    }
    _, requests = await run(config, FIXTURES["grant_offers"]["body"])
    assert json.loads(requests[0].content)["meta"] == {
        "send_customer_welcome_email": True
    }


@pytest.mark.asyncio
async def test_update_omits_unset_attributes_and_keeps_false():
    _, requests = await run(
        {"operation": "update_contact", "contact_id": "456", "subscribed": False},
        FIXTURES["update_contact"]["body"],
    )
    assert json.loads(requests[0].content)["data"]["attributes"] == {
        "subscribed": False
    }


@pytest.mark.asyncio
async def test_list_preserves_pagination_and_included_records():
    payload = {
        **FIXTURES["list_contacts"]["body"],
        "links": {"next": "https://api.kajabi.com/v1/contacts?page[number]=3"},
        "meta": {"current_page": 2},
        "included": [{"id": "123", "type": "sites"}],
    }
    result, requests = await run(FIXTURES["list_contacts"]["config"], payload)
    assert len(requests) == 1
    for key in ["links", "meta", "included"]:
        assert result[key] == payload[key]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 422, 429, 500, 200])
async def test_provider_errors_do_not_report_success(status):
    # JSON:API errors are documented in components/schemas/errors_unauthorized.
    payload = {
        "errors": [
            {
                "title": "Unauthorized",
                "detail": "Authorization header is missing or invalid",
            }
        ]
    }
    result, _ = await run({"operation": "list_sites"}, payload, status)
    assert result["status"] == "error"
    assert result["error"] == "Authorization header is missing or invalid"
    assert result["status_code"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {}},
        {"data": [1]},
        {"data": [{"name": "fake"}]},
        {"data": None},
        "<html>Sign in</html>",
    ],
)
async def test_evidence_rejects_invalid_success_envelopes(payload):
    result, _ = await run({"operation": "list_sites"}, payload)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_empty_sites_is_valid():
    result, _ = await run({"operation": "list_sites"}, {"data": []})
    assert result["status"] == "success"
    assert result["data"] == []


@pytest.mark.asyncio
async def test_transport_failure_does_not_expose_token():
    result, _ = await run({"operation": "list_sites"}, httpx.ConnectError("test-token"))
    assert result["status"] == "error"
    assert "test-token" not in result["error"]


@pytest.mark.asyncio
async def test_missing_credentials():
    with pytest.raises(ValueError, match="access token"):
        await node({"operation": "list_sites"}, credentials=False).execute({})


@pytest.mark.asyncio
async def test_update_requires_an_attribute():
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_contact", "contact_id": "456"}).execute({})


@pytest.mark.asyncio
async def test_ids_cannot_inject_a_path():
    _, requests = await run(
        {"operation": "get_contact", "contact_id": "a/b?x=1"},
        FIXTURES["get_contact"]["body"],
    )
    assert requests[0].url.raw_path == b"/v1/contacts/a%2Fb%3Fx%3D1"


@pytest.mark.asyncio
async def test_site_picker_and_connection_evidence_show_site_titles():
    original = httpx.AsyncClient
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=FIXTURES["list_sites"]["body"])

    with patch(
        "nodes.kajabi_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(transport=httpx.MockTransport(transport)),
    ):
        result = await KajabiNode.load_field_options(
            "site_id", {"access_token": "test-token"}, search="advanced"
        )
    assert result["options"] == [{"label": "Advanced Training Site", "value": "123"}]
    assert requests[0].url.path == "/v1/sites"
    assert KajabiNode.connection_evidence.field == "site_id"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,status",
    [
        ({"errors": [{"title": "Unauthorized"}]}, 401),
        ({"data": [{"id": "123", "type": "sites"}]}, 200),
    ],
)
async def test_site_picker_propagates_failed_or_unrecognizable_response(
    payload, status
):
    original = httpx.AsyncClient
    with patch(
        "nodes.kajabi_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json=payload)
            )
        ),
    ):
        result = await KajabiNode.load_field_options(
            "site_id", {"access_token": "test-token"}
        )
    assert result["status"] == "error"
