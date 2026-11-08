"""Offline checks against CATS's pinned, provider-authored request/response examples."""
import json
from pathlib import Path

import httpx
import jsonschema
import pytest
from pydantic import ValidationError

from nodes import cats_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-cats-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/cats/contract.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="cats-test", node_type="automation-cats", node_data={
        "config": config, "credentials": {"credential_type": "cats_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_cats_provider_contract_one_request(monkeypatch, operation):
    case = CASES[operation]
    response = httpx.Response(case["status"], **({"json": case["body"]} if case["body"] is not None else {}))
    requests = transport(monkeypatch, response)
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    expected_route = case["route"]
    if "{id}" in expected_route:
        identifier = case["config"][operation.split("_", 1)[1] + "_id"]
        expected_route = expected_route.replace("{id}", str(identifier))
    # /v3 comes from the provider's Host docs; the pinned OpenAPI servers URL omits it.
    assert str(request.url).startswith("https://api.catsone.com/v3/")
    assert request.url.path == "/v3" + expected_route
    assert request.headers["Authorization"] == "Token " + TOKEN
    assert request.headers["Content-Type"] == "application/json"
    expected_query = {p["name"] for p in case["parameters"] if p["in"] == "query"}
    assert set(request.url.params) == expected_query
    for param in case["parameters"]:
        if param["in"] != "query":
            continue
        value = request.url.params[param["name"]]
        kind = param["schema"]["type"]
        if kind == "number":
            assert int(value) > 0
        elif kind == "boolean":
            assert value in {"true", "false"}
        else:
            assert value == case["config"][param["name"]]
    if case["request_schema"]:
        body = json.loads(request.content)
        jsonschema.validate(body, case["request_schema"])
        assert set(body) <= set(case["request_schema"]["properties"])
        # Provider example values survive; operation selectors, IDs and query flags stay out of JSON.
        for key, value in body.items():
            assert value == case["config"].get(key, value)
    else:
        assert request.content == b""
    assert TOKEN not in str(result)
    if case["method"] != "GET":
        assert result == {"success": True, "operation": operation, "http_status": case["status"]}
    elif operation.startswith(("list_", "search_")):
        kind = "candidates" if operation == "search_candidates" else operation.removeprefix("list_")
        assert result["items"] == native._redact(case["body"]["_embedded"][kind], TOKEN)
        assert result["total"] == case["body"]["total"]
    else:
        assert result == native._redact(case["body"], TOKEN)


@pytest.mark.asyncio
async def test_cats_page_and_query_boundary(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"count": 0, "total": 0, "_embedded": {"candidates": []}, "_links": {"next": {"href": "https://untrusted.test/"}}}))
    result = await node({"operation": "search_candidates", "query": "Ada + café", "page": 4, "per_page": 100}).execute({})
    assert result["items"] == []
    assert dict(requests[0].url.params) == {"page": "4", "per_page": "100", "query": "Ada + café"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_cats_errors_and_no_write_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"error": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as error:
        await node(CASES["create_candidate"]["config"]).execute({})
    assert f"CATS HTTP {status}" in str(error.value)
    assert TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_cats_uncertain_write_does_not_retry(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("lost response", request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="check the record before retrying"):
        await node(CASES["create_pipeline"]["config"]).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors": [{"message": "denied"}]}, {"_embedded": {"companies": [7]}}, []])
async def test_cats_invalid_list_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "list_companies"}).execute({})


@pytest.mark.asyncio
async def test_cats_redacts_provider_password_and_echoed_key(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"id": 1, "password": "private", "notes": TOKEN, "_embedded": {"owner": {"api_key": TOKEN}}}))
    result = await node({"operation": "get_candidate", "candidate_id": 1}).execute({})
    assert result == {"id": 1, "notes": "[redacted]", "_embedded": {"owner": {}}}


@pytest.mark.parametrize("key", ["https://catsone.com/key", "<token>", "Token abc", "abc\nxyz", "abcé", None])
def test_cats_rejects_invalid_keys(key):
    with pytest.raises(ValidationError):
        native.CatsAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation": "get_candidate", "candidate_id": "../site"},
    {"operation": "list_candidates", "per_page": 101},
    {"operation": "list_companies", "page": 0},
    {"operation": "create_candidate", "first_name": "Ada"},
    {"operation": "update_company", "company_id": 1, "name": "Acme"},
    {"operation": "create_pipeline", "candidate_id": 1, "job_id": 2, "rating": 6},
    {"operation": "create_job", "title": "Engineer", "company_id": 1},
    {"operation": "create_task", "priority": 6},
    {"operation": "get_site", "url": "https://untrusted.test"},
])
def test_cats_rejects_bad_config(config):
    assert not native.CatsNode.validate_config({"config": config})["valid"]


@pytest.mark.asyncio
async def test_cats_creation_exposes_documented_location_without_following(monkeypatch):
    # https://docs.catsone.com/#candidates-create-a-candidate promises the Location header.
    location = "https://api.catsone.com/v3/candidates/123"
    requests = transport(monkeypatch, httpx.Response(201, headers={"Location": location}))
    result = await node({"operation": "create_candidate", "first_name": "Ada", "last_name": "Lovelace"}).execute({})
    assert result["location"] == location
    assert len(requests) == 1
