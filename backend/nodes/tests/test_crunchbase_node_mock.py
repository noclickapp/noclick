"""Offline tests for Crunchbase's fixed v4 routes and published wire shapes."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import crunchbase_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-crunchbase-key-42"
ID = "df662812-7f97-0b43-9d3e-12f64f504fbb"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(
        node_id="crunchbase-fixture",
        node_type="automation-crunchbase",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": native.CREDENTIAL,
                "api_key": TOKEN,
                **credential,
            },
        },
    )


def mock_http(monkeypatch, payload, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), **kwargs
        ) as session:
            yield session

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", list(native.ROUTES.items()))
async def test_every_native_operation_exact_route_auth_and_json(
    monkeypatch, operation, route
):
    method, collection = route
    config = {"operation": operation}
    if operation.startswith("get_"):
        config["entity_id"] = "crunchbase"
        payload = {"properties": {"identifier": {"uuid": ID, "value": "Crunchbase"}}}
    else:
        payload = {
            "count": 1,
            "entities": [{"uuid": ID, "properties": {"identifier": {"uuid": ID}}}],
        }
        if operation == "autocomplete":
            config.update(query="crunch", collection_ids=["organizations", "people"])
            payload = {
                "entities": [
                    {
                        "identifier": {
                            "uuid": ID,
                            "entity_def_id": "organization",
                            "value": "Crunchbase",
                        }
                    }
                ]
            }
    requests = mock_http(monkeypatch, payload)
    result = await node(config).execute({})
    assert NODE_REGISTRY["automation-crunchbase"] is native.CrunchbaseNode
    assert result["data"] == payload and result["success"] is True
    assert result["identity_verified"] is False
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.crunchbase.com"
    assert request.headers["X-cb-user-key"] == TOKEN
    assert "user_key" not in request.url.params and TOKEN not in str(result)
    if operation.startswith("get_"):
        assert request.url.path == "/v4/data/entities/" + collection + "/crunchbase"
        assert request.url.params["field_ids"] == "identifier"
    elif operation.startswith("search_"):
        assert request.url.path == "/v4/data/searches/" + collection
        assert json.loads(request.content) == {
            "field_ids": ["identifier"],
            "query": [],
            "limit": 100,
            "order": [],
        }
    else:
        assert request.url.path == "/v4/data/autocompletes"
        assert dict(request.url.params) == {
            "query": "crunch",
            "collection_ids": "organizations,people",
            "limit": "10",
        }


@pytest.mark.asyncio
async def test_documented_search_predicates_order_cursor_and_page_boundary(monkeypatch):
    payload = {
        "count": 20,
        "entities": [{"uuid": ID, "properties": {"identifier": {"uuid": ID}}}],
    }
    requests = mock_http(monkeypatch, payload)
    query = [
        {
            "type": "predicate",
            "field_id": "categories",
            "operator_id": "includes",
            "values": ["c08b5441-a05b-9777-b7a6-0122bbc9ebba"],
        }
    ]
    result = await node(
        {
            "operation": "search_organizations",
            "query": json.dumps(query),
            "field_ids": ["identifier", "short_description"],
            "after_id": ID,
            "limit": 1,
            "order": json.dumps([{"field_id": "rank_org", "sort": "asc"}]),
        }
    ).execute({})
    sent = json.loads(requests[0].content)
    assert sent["query"] == query and sent["after_id"] == ID
    assert sent["order"] == [{"field_id": "rank_org", "sort": "asc"}]
    assert result["next_after_id"] == ID and result["previous_before_id"] == ID
    requests = mock_http(monkeypatch, {"count": 0, "entities": []})
    result = await node({"operation": "search_people"}).execute({})
    assert result["items"] == [] and result["next_after_id"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"entity_id": "../people/foo"},
        {"entity_id": "https://crunchbase.com/organization/example"},
        {"entity_id": "a?user_key=stolen"},
        {"field_ids": ["invented_field"]},
    ],
)
def test_lookup_refuses_path_and_field_injection(changes):
    with pytest.raises((ValueError, ValidationError)):
        node({"operation": "get_organization", "entity_id": "crunchbase", **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"after_id": ID, "before_id": ID},
        {"limit": 1001},
        {"limit": True},
        {
            "query": json.dumps(
                [{"field_id": "categories", "operator_id": "gt", "values": [10]}]
            )
        },
        {"order": json.dumps([{"field_id": "made_up_field", "sort": "asc"}])},
    ],
)
def test_search_refuses_invalid_cursors_limits_operators_and_order(changes):
    with pytest.raises((ValueError, ValidationError)):
        node({"operation": "search_organizations", **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_rejection_remains_failure_and_redacts_key(monkeypatch, status):
    mock_http(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node(
        {"operation": "get_organization", "entity_id": "crunchbase"}
    ).execute({})
    assert result["success"] is False and result["http_status"] == status
    assert TOKEN not in str(result) and "Rejected" in result["message"]


@pytest.mark.asyncio
async def test_response_key_echo_redaction_and_malformed_envelope(monkeypatch):
    mock_http(monkeypatch, {"properties": {"description": TOKEN}})
    result = await node({"operation": "get_person", "entity_id": "example"}).execute({})
    assert result["data"]["properties"]["description"] == "[redacted]"
    mock_http(monkeypatch, {"entities": "wrong"})
    with pytest.raises(ValueError, match="unexpected JSON"):
        await node({"operation": "search_people"}).execute({})


def test_credential_and_reachability_contract():
    evidence = native.CrunchbaseNode.connection_evidence
    assert evidence.proves == "reachability"
    assert evidence.operation == "get_organization"
    assert evidence.operation_arguments == {"entity_id": "crunchbase"}
    for key in [
        "https://example.com/key",
        "Bearer key with spaces",
        "<token>",
        "line\nfeed",
    ]:
        with pytest.raises((ValueError, ValidationError)):
            native.CrunchbaseAPIKeyCredential(api_key=key)
    with pytest.raises((ValueError, ValidationError)):
        node({"operation": "search_people"}, credential_type="another_api_key")
