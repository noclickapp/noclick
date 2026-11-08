"""Accredible wire contracts and documented response regressions, without an account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import accredible_certificates_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TYPE = "automation-accredible-certificates"
KEY = "fixture-accredible-key-123"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/accredible-certificates/responses.json").read_text())["responses"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region="us"):
    return NodeFactory.create_node(node_id="accredible-fixture", node_type=TYPE, node_data={
        "config": config, "credentials": {"credential_type": "accredible_certificates_api_key", "api_key": KEY, "region": region}})


def transport(monkeypatch, response):
    requests = []
    def handle(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Explicit expectations are independent of the node's route dispatch table.
CASES = [
    ({"operation": "get_issuer"}, "GET", "/v1/issuer/details"),
    ({"operation": "get_credential", "certificate_id": "10000005"}, "GET", "/v1/credentials/10000005"),
    ({"operation": "create_credential", "recipient_name": "John Doe", "recipient_email": "person@example.com", "group_id": 23}, "POST", "/v1/credentials"),
    ({"operation": "update_credential", "certificate_id": "10000005", "approve": True}, "PUT", "/v1/credentials/10000005"),
    ({"operation": "delete_credential", "certificate_id": "10000005"}, "DELETE", "/v1/credentials/10000005"),
    ({"operation": "list_credentials", "page": 2}, "GET", "/v1/all_credentials"),
    ({"operation": "search_credentials", "recipient_email": "person@example.com"}, "POST", "/v1/credentials/search"),
    ({"operation": "get_credential_analytics", "certificate_id": "10000005"}, "POST", "/v1/credentials/analytics/10000005"),
    ({"operation": "create_group", "name": "new group", "course_name": "Intro to Prgramming", "course_description": "Description of course"}, "POST", "/v1/issuer/groups"),
    ({"operation": "get_group", "group_id": 12345}, "GET", "/v1/issuer/groups/12345"),
    ({"operation": "update_group", "group_id": 12345, "name": "updated new group"}, "PUT", "/v1/issuer/groups/12345"),
    ({"operation": "delete_group", "group_id": 12345}, "DELETE", "/v1/issuer/groups/12345"),
    ({"operation": "search_groups", "name": "Programming Course"}, "POST", "/v1/issuer/groups/search"),
    ({"operation": "get_design", "design_id": 1234}, "GET", "/v1/designs/1234"),
    ({"operation": "search_designs", "kind": "certificate"}, "POST", "/v1/designs/search"),
    ({"operation": "search_departments"}, "POST", "/v1/departments/search"),
    ({"operation": "search_attribute_keys", "kind": "text"}, "POST", "/v1/attribute_keys/search"),
    ({"operation": "list_analytics", "start_date": "2023-01-01"}, "GET", "/v1/analytics"),
    ({"operation": "list_skill_categories"}, "GET", "/v1/skill_categories"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_every_operation_request_and_documented_response(monkeypatch, config, method, path):
    fixture_path = path.replace("10000005", "{id}").replace("12345", "{group_id}").replace("1234", "{design_id}")
    body = FIXTURES.get(method + " " + fixture_path, {})
    requests = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.accredible.com"
    assert request.headers["Authorization"] == "Token token=" + KEY
    assert KEY not in str(result)
    assert result["status"] == "success" and result["data"] == body
    if method == "DELETE":
        assert not request.content
    elif method == "GET":
        assert not request.content
        if config["operation"] == "list_credentials":
            assert dict(request.url.params) == {"page": "2", "page_size": "50"}
    else:
        wire = json.loads(request.content)
        if config["operation"] == "create_credential":
            assert wire == {"credential": {"group_id": 23, "recipient": {"name": "John Doe", "email": "person@example.com"}}}
        elif config["operation"] == "update_credential":
            assert wire == {"credential": {"approve": True}}
        elif config["operation"] == "update_group":
            assert wire == {"group": {"name": "updated new group"}}
        elif config["operation"] == "create_group":
            assert wire == {"group": {k: v for k, v in config.items() if k != "operation"}}
        elif config["operation"] == "search_credentials":
            assert wire == {"recipient.email": "person@example.com", "page": 1, "page_size": 50}


@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", [("us", "api.accredible.com"), ("eu", "eu.api.accredible.com"), ("sandbox", "sandbox.api.accredible.com")])
async def test_regions_and_identity(monkeypatch, region, host):
    requests = transport(monkeypatch, httpx.Response(200, json=FIXTURES["GET /v1/issuer/details"]))
    result = await node({"operation": "get_issuer"}, region).execute({})
    assert requests[0].url.host == host and result["name"] == "Example Provider"


@pytest.mark.asyncio
async def test_dates_false_and_nested_recipient(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"credential": {"id": 10000005}}))
    await node({"operation": "update_credential", "certificate_id": "10000005", "recipient_name": "John Doe",
                "issued_on": "2014-06-14", "complete": False, "custom_attributes": {"dob": "29 jan 1970"}}).execute({})
    assert json.loads(requests[0].content) == {"credential": {"recipient": {"name": "John Doe"},
        "issued_on": "2014-06-14", "complete": False, "custom_attributes": {"dob": "29 jan 1970"}}}


@pytest.mark.asyncio
async def test_evidence_pagination_and_partial_success(monkeypatch):
    assert NODE_REGISTRY[TYPE] is native.AccredibleCertificatesNode
    assert native.AccredibleCertificatesNode.connection_evidence.operation == "search_groups"
    body = FIXTURES["POST /v1/issuer/groups/search"]
    transport(monkeypatch, httpx.Response(200, json=body))
    result = await node({"operation": "search_groups"}).execute({})
    assert result["items"] == body["groups"] and result["meta"] == body["meta"]
    body = {"group": {"id": 12345}, "errors": [{"code": "skills_not_attached"}]}
    transport(monkeypatch, httpx.Response(207, json=body))
    result = await node({"operation": "update_group", "group_id": 12345, "name": "Updated"}).execute({})
    assert result["http_status"] == 207 and result["data"]["errors"] == body["errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 500, 302])
async def test_provider_errors_preserve_text_and_redact_key(monkeypatch, status):
    transport(monkeypatch, httpx.Response(status, text="HTTP Token: Access denied. " + KEY))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_issuer"}).execute({})
    assert "HTTP Token: Access denied." in str(exc.value) and KEY not in str(exc.value)


@pytest.mark.asyncio
async def test_empty_delete_response(monkeypatch):
    transport(monkeypatch, httpx.Response(204))
    result = await node({"operation": "delete_group", "group_id": 12345}).execute({})
    assert result == {"status": "success", "data": None, "http_status": 204}


@pytest.mark.parametrize("key", ["https://dashboard.accredible.com", "<token>", "Token token=abc", "abc\ndef", "abc\u200bdef", ""])
def test_reject_invalid_key(key):
    with pytest.raises(ValidationError):
        native.AccredibleCertificatesAPIKey(api_key=key)


def test_unknown_region_and_missing_create_fields():
    with pytest.raises(ValidationError):
        native.AccredibleCertificatesAPIKey(api_key=KEY, region="https://attacker.test")
    assert not native.AccredibleCertificatesNode.validate_config({"operation": "create_credential"})["valid"]
