"""Exercise published response structures with signed document URLs sanitized."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import recruiterflow_node as rf
from nodes.core.credential_connect import shape_credential

FIXTURES = json.loads((Path(__file__).parent / "fixtures/recruiterflow/published_responses.json").read_text())
AUTH = {"credential_type": "recruiterflow_api_key", "api_key": "fixture-recruiterflow-key"}
CONFIGS = {
    "list_candidates": {}, "get_candidate": {"candidate_id": 10},
    "create_candidate": {"name": "Swagger Candidate", "email": [{"email": "swagger@mail.com", "is_primary": 1}]},
    "update_candidate": {"candidate_id": 10, "tags": []},
    "add_candidate_to_job": {"candidate_id": 123, "job_id": 456},
    "move_candidate_to_stage": {"candidate_id": 123, "job_id": 456, "stage_id": 2, "user_id": 12},
    "add_candidate_note": {"candidate_id": 123, "created_by": 12, "value": "Interview complete"},
    "list_contacts": {}, "get_contact": {"contact_id": 10},
    "create_contact": {"first_name": "Swagger", "last_name": "Contact"},
    "update_contact": {"contact_id": 10, "email": []},
    "list_companies": {}, "get_company": {"company_id": 1},
    "create_company": {"name": "Test Company", "domain": "example.com"},
    "list_jobs": {}, "get_job": {"job_id": 10}, "get_job_pipeline": {"job_id": 10},
    "list_campaigns": {}, "add_to_campaign": {"campaign_id": 10, "prospect_ids": [123], "user_id": 12},
    "remove_from_campaign": {"campaign_id": 10, "prospect_ids": [123]},
    "list_users": {}, "list_tags": {},
}
EXPECTED = {
    "list_candidates": {"current_page": "1", "items_per_page": "10"},
    "get_candidate": {"id": "10"},
    "create_candidate": {"name": "Swagger Candidate", "email": [{"email": "swagger@mail.com", "is_primary": 1}]},
    "update_candidate": {"id": 10, "tags": []},
    "add_candidate_to_job": {"id": 123, "job_id": 456, "applied": 0},
    "move_candidate_to_stage": {"id": 123, "job_id": 456, "stage": {"id": 2}, "user_id": 12},
    "add_candidate_note": {"id": 123, "created_by": 12, "value": "Interview complete"},
    "list_contacts": {"current_page": "1", "items_per_page": "10"},
    "get_contact": {"id": "10"},
    "create_contact": {"first_name": "Swagger", "last_name": "Contact"},
    "update_contact": {"id": 10, "email": []},
    "list_companies": {"current_page": "1", "items_per_page": "10"},
    "get_company": {"id": "1"},
    "create_company": {"name": "Test Company", "domain": "example.com"},
    "list_jobs": {"current_page": "1", "items_per_page": "10"},
    "get_job": {"job_id": "10", "include_stages": "1"},
    "get_job_pipeline": {"job_id": "10"},
    "list_campaigns": {"current_page": "1", "items_per_page": "10"},
    "add_to_campaign": {"campaign_id": 10, "id": [123], "user_id": 12},
    "remove_from_campaign": {"campaign_id": 10, "id": [123]},
    "list_users": {}, "list_tags": {"current_page": "1", "items_per_page": "10"},
}


def node(operation, **changes):
    config = {"operation": operation, **CONFIGS[operation], **changes}
    data = {"config": config, "credentials": AUTH}
    return rf.RecruiterflowNode("test", "automation-recruiterflow", data, config=rf.RecruiterflowNode.parse_config(data))


def transport(monkeypatch, response):
    requests = []

    def handle(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(rf, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_published_responses_and_exact_request(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, fixture["response"])
    result = await node(operation).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert str(request.url.copy_with(query=None)) == rf.BASE_URL + fixture["path"]
    assert request.headers["RF-Api-Key"] == AUTH["api_key"]
    assert AUTH["api_key"] not in str(result)
    sent = dict(request.url.params) if request.method == "GET" else json.loads(request.content)
    assert sent == EXPECTED[operation]
    if operation.startswith("list_"):
        expected = fixture["response"]
        assert result["items"] == (expected if isinstance(expected, list) else expected["data"])
    else:
        assert result["data"] == fixture["response"]


@pytest.mark.asyncio
async def test_page_numbers_and_flags_are_not_dropped(monkeypatch):
    requests = transport(monkeypatch, [])
    await node("list_jobs", current_page=2, items_per_page=25, only_open=0).execute({})
    assert dict(requests[0].url.params) == {"current_page": "2", "items_per_page": "25", "only_open": "0"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_failure_does_not_retry_write_or_expose_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": "Rejected " + AUTH["api_key"]}, headers={"Location": "https://example.com/"}))
    result = await node("create_candidate").execute({})
    assert result["status"] == "error"
    assert result["http_status"] == status
    assert AUTH["api_key"] not in result["error"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_200_failure_envelope_is_not_success(monkeypatch):
    transport(monkeypatch, {"RESULT": "FAILURE", "message": "Invalid API key"})
    result = await node("list_users").execute({})
    assert result["status"] == "error" and result["error"] == "Invalid API key"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": {}}, ["bad"], "bad"])
async def test_malformed_list_not_connected(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node("list_users").execute({})


@pytest.mark.parametrize("config", [
    {"operation": "update_candidate", "candidate_id": 10},
    {"operation": "update_contact", "contact_id": 10},
    {"operation": "get_job"}, {"operation": "get_candidate", "candidate_id": 0},
    {"operation": "list_candidates", "current_page": 0},
    {"operation": "list_candidates", "items_per_page": 101},
    {"operation": "remove_from_campaign", "campaign_id": 1, "prospect_ids": []},
    {"operation": "create_contact", "name": "Wrong field"},
    {"operation": "get_candidate", "candidate_id": 10, "url": "https://example.com"},
])
def test_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        rf.RecruiterflowNode.parse_config({"config": config, "credentials": AUTH})


def test_manual_credential_default_and_evidence():
    shaped, errors, resolved = shape_credential("recruiterflow_api_key", {"api_key": AUTH["api_key"]})
    assert not errors and resolved[1] is rf.RecruiterflowApiKeyCredential
    assert shaped["api_key"] == AUTH["api_key"]
    assert rf.RecruiterflowApiKeyCredential.model_validate(shaped).credential_type == AUTH["credential_type"]
    assert rf.RecruiterflowNode.connection_evidence.operation == "list_users"
    assert len(rf.ROUTES) == 22 and set(rf.ROUTES) == set(FIXTURES)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_candidate", "create_contact", "create_company", "update_candidate", "update_contact", "add_candidate_to_job", "move_candidate_to_stage", "add_candidate_note", "add_to_campaign", "remove_from_campaign"])
async def test_write_needs_documented_confirmation(monkeypatch, operation):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="documented result"):
        await node(operation).execute({})
    assert len(requests) == 1


def test_response_fixtures_never_publish_signed_document_credentials():
    """Public API examples can contain signed URLs; those are not safe fixtures."""
    from urllib.parse import parse_qs, urlsplit
    import re

    serialized = json.dumps(FIXTURES)
    forbidden = {"awsaccesskeyid", "signature", "x-amz-credential", "x-amz-signature", "x-amz-security-token"}

    def check(value):
        if isinstance(value, dict):
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif isinstance(value, str) and value.startswith(("https://", "http://")):
            assert not forbidden.intersection(k.lower() for k in parse_qs(urlsplit(value).query))

    check(FIXTURES)
    assert not re.search("AK" + "IA" + r"[A-Z0-9]{16}", serialized)
