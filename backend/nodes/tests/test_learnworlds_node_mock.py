"""LearnWorlds API v2 schemas and provider-authored response regressions, without a live account."""
import json
from pathlib import Path

import httpx
import jsonschema
import pytest
from nodes.core.base import ConfigValidationError

from nodes import learnworlds_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/learnworlds/contract_cases.json").read_text())
CREDENTIAL = {"credential_type": "learnworlds_access_token", "school_url": "https://academy.learnworlds.com", "client_id": "school-fixture", "access_token": "fixture-learnworlds-token"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="learnworlds-fixture", node_type="automation-learnworlds",
        node_data={"config": config, "credentials": credentials or CREDENTIAL})


def mock_http(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_learnworlds_published_request_and_response_contract(monkeypatch, operation):
    case = CASES[operation]
    response = httpx.Response(case["response_status"], **({"json": case["response"]} if case["response"] is not None else {}))
    requests = mock_http(monkeypatch, response)
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "academy.learnworlds.com"
    assert request.url.path == case["expected_path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer fixture-learnworlds-token"
    assert request.headers["Lw-Client"] == "school-fixture"
    if case["body"] is not None:
        payload = json.loads(request.content)
        assert payload == case["body"]
        jsonschema.Draft202012Validator(case["request_schema"]).validate(payload)
    else:
        assert request.content == b""
    assert result["status"] == "success"
    assert result["data"] == (case["response"]["data"] if operation.startswith("list_") else case["response"])
    if operation.startswith("list_"):
        assert result["next_page"] is None
    assert CREDENTIAL["access_token"] not in str(result)


@pytest.mark.parametrize("url", ["https://evil.test", "https://school.learnworlds.com.evil.test", "https://school.learnworlds.com@evil.test", "http://school.learnworlds.com", "https://school.learnworlds.com:444", "https://school.learnworlds.com/admin/api?x=1", "https://school.learnworlds.com/other", "https://127.0.0.1"])
def test_learnworlds_refuses_unsafe_school_urls(url):
    with pytest.raises(ValueError):
        native.LearnWorldsAccessTokenCredential.model_validate({**CREDENTIAL, "school_url": url})


def test_learnworlds_manual_credential_defaults_and_api_url():
    cred = native.LearnWorldsAccessTokenCredential.model_validate({k: v for k, v in {**CREDENTIAL, "school_url": "https://academy.learnworlds.com/admin/api/v2/"}.items() if k != "credential_type"})
    assert cred.credential_type == "learnworlds_access_token"
    assert cred.school_url == "https://academy.learnworlds.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_learnworlds_errors_are_not_success_or_retried(monkeypatch, status):
    requests = mock_http(monkeypatch, httpx.Response(status, json={"message": "Provider rejected " + CREDENTIAL["access_token"]}))
    result = await node({"operation": "list_courses"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Provider rejected" in result["error"]
    assert CREDENTIAL["access_token"] not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_learnworlds_next_page_uses_returned_page_and_stops_at_last(monkeypatch):
    mock_http(monkeypatch, httpx.Response(200, json={"data": [], "meta": {"page": 2, "totalPages": 3}}))
    result = await node({"operation": "list_courses", "page": 2}).execute({})
    assert result["next_page"] == 3
    mock_http(monkeypatch, httpx.Response(200, json={"data": [], "meta": {"page": 3, "totalPages": 3}}))
    result = await node({"operation": "list_courses", "page": 99}).execute({})
    assert result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"success": False, "errors": [{"message": "Access denied"}]}, {"error": "Denied"}])
async def test_learnworlds_200_error_envelopes(monkeypatch, body):
    mock_http(monkeypatch, httpx.Response(200, json=body))
    result = await node({"operation": "list_courses"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_learnworlds_encodes_user_email_and_keeps_delete_body(monkeypatch):
    requests = mock_http(monkeypatch, httpx.Response(204))
    result = await node({"operation": "unenroll_user", "user_id": "a+b@example.com", "productId": "bundle-new", "productType": "bundle"}).execute({})
    assert b"a%2Bb%40example.com" in requests[0].url.raw_path
    assert json.loads(requests[0].content) == {"productId": "bundle-new", "productType": "bundle"}
    assert result["http_status"] == 204


@pytest.mark.asyncio
async def test_learnworlds_rejects_redirect_and_malformed_list(monkeypatch):
    for response in [httpx.Response(302, headers={"Location": "https://evil.test"}), httpx.Response(200, json={"data": []})]:
        requests = mock_http(monkeypatch, response)
        with pytest.raises(ValueError):
            await node({"operation": "list_courses"}).execute({})
        assert len(requests) == 1


@pytest.mark.parametrize("operation", ["get_user", "get_course", "get_payment"])
def test_learnworlds_refuses_path_injection(operation):
    case = {**CASES[operation]["config"]}
    field = next(k for k in case if k.endswith("_id"))
    for value in ["..", "../users", "id?x=1", "%2fusers"]:
        with pytest.raises(ConfigValidationError):
            node({**case, field: value})
