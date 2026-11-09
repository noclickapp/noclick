"""Fixed webCRM v1 wire contracts through the native node factory; no account used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import webcrm_node as webcrm
from nodes.core.registry import NodeFactory

TOKEN = "webcrm-synthetic-access-token"
AUTH = {"credential_type": "webcrm_access_token", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/webcrm/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="webcrm-test", node_type="automation-webcrm",
                                   node_data={"config": config, "credentials": AUTH})


def mock_transport(monkeypatch, response, code=200):
    seen = []
    original = httpx.AsyncClient

    def send(request):
        seen.append(request)
        return httpx.Response(code, json=response) if response is not None else httpx.Response(code)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(webcrm.httpx, "AsyncClient", client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_every_operation_exact_request_and_response(monkeypatch, case):
    seen = mock_transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == case["method"]
    assert request.url.host == "api.webcrm.com"
    assert request.url.path == case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == "application/json"
    assert dict(request.url.params) == case.get("query", {})
    if "body" in case:
        assert json.loads(request.content) == case["body"]
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert not request.content
    if case["method"] in {"POST", "PUT"}:
        assert result["id"] == (42 if case["method"] == "POST" else 9)
    elif isinstance(case["response"], list):
        assert result["items"] == case["response"]
        assert result["next_page"] is None
    else:
        assert result["data"] == case["response"]
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_explicit_pagination_and_search_encoding(monkeypatch):
    seen = mock_transport(monkeypatch, [{"PersonId": 9}])
    result = await node({"operation": "search_persons", "search": "a+b@example.test & café",
                         "page": 3, "page_size": 1, "sort_order": "Descending"}).execute({})
    assert dict(seen[0].url.params) == {"input": "a+b@example.test & café", "Page": "3", "Size": "1", "SortOrder": "Descending"}
    assert result["next_page"] == 4 and result["page"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_failure_is_never_success_or_retried(monkeypatch, status):
    seen = mock_transport(monkeypatch, {"Message": "Provider rejection " + TOKEN}, status)
    result = await node({"operation": "list_organisations"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Provider rejection" in result["error"]
    assert TOKEN not in json.dumps(result)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,response", [("list_users", {}), ("list_users", [1]),
                                                ("get_person", []), ("create_organisation", True)])
async def test_invalid_success_shape_is_refused(monkeypatch, operation, response):
    mock_transport(monkeypatch, response)
    config = {"operation": operation}
    if operation == "get_person":
        config["person_id"] = 9
    if operation == "create_organisation":
        config["name"] = "Example Ltd"
    with pytest.raises(ValueError):
        await node(config).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_person", "person_id": -1},
    {"operation": "get_person", "person_id": "9/Persons"},
    {"operation": "list_users", "page_size": 1001},
    {"operation": "list_users", "page": 0},
    {"operation": "search_persons", "search": ""},
    {"operation": "create_organisation", "name": "x" * 201},
    {"operation": "update_person", "person_id": 4},
    {"operation": "create_activity", "description": "Call", "organisation_id": 3, "status": "invalid"},
])
def test_invalid_config_is_refused_before_request(config):
    with pytest.raises(ValueError):
        node(config)


def test_credential_is_manually_fillable_and_secret_is_hidden():
    credential = webcrm.WebCRMAccessTokenCredential(access_token=TOKEN)
    assert credential.credential_type == "webcrm_access_token"
    assert TOKEN not in repr(credential)
    assert not webcrm.WebCRMAccessTokenCredential.model_fields["credential_type"].is_required()
    for bad in ["Bearer token", "a\nb", " ", "https://api.webcrm.com"]:
        with pytest.raises(ValidationError):
            webcrm.WebCRMAccessTokenCredential(access_token=bad)


@pytest.mark.asyncio
async def test_connection_evidence_names_account_organisations(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    mock_transport(monkeypatch, [{"OrganisationId": 8, "OrganisationName": "Example Ltd"}])
    evidence = await collect_evidence(node_type="automation-webcrm", credential_data=AUTH,
                                      user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert [s.label for s in evidence.samples] == ["Example Ltd"]
