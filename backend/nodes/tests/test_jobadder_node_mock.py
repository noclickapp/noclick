"""JobAdder wire-contract regressions; all credentials and responses are synthetic."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError
from nodes import jobadder_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.jobadder_oauth import OAUTH_PROVIDER

TOKEN = "synthetic-jobadder-access-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="jobadder-fixture", node_type="automation-jobadder",
        node_data={"config": config, "credentials": credentials or {"credential_type": "jobadder_oauth", "access_token": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_current_user_and_manual_credential(monkeypatch):
    credential = native.JobAdderOAuthCredential(access_token=TOKEN)
    assert credential.credential_type == "jobadder_oauth"
    requests = transport(monkeypatch, {"userId": 9, "email": "recruiter@example.test"})
    result = await node({"operation": "get_current_user"}).run({})
    assert result["data"]["userId"] == 9
    assert requests[0].url == "https://api.jobadder.com/v2/users/current"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,id_field,wire", [
    ("get_candidate", "candidate_id", "candidateId"), ("get_company", "company_id", "companyId"),
    ("get_contact", "contact_id", "contactId"), ("get_job", "job_id", "jobId"),
    ("get_placement", "placement_id", "placementId")])
async def test_detail_bound_to_selected_id(monkeypatch, operation, id_field, wire):
    requests = transport(monkeypatch, {wire: 41})
    result = await node({"operation": operation, id_field: 41}).run({})
    assert result["status"] == "success" and requests[0].url.path.endswith("/41")
    transport(monkeypatch, {wire: 42})
    with pytest.raises(ValueError, match="different resource"):
        await node({"operation": operation, id_field: 41}).execute({})


@pytest.mark.asyncio
async def test_query_case_and_pagination(monkeypatch):
    requests = transport(monkeypatch, {"items": [{"candidateId": 41}], "totalCount": 4,
        "links": {"next": "https://untrusted.example.test/do-not-follow"}})
    result = await node({"operation": "list_candidates", "email": "a+b@example.test", "offset": 2, "limit": 1}).run({})
    assert dict(requests[0].url.params) == {"Offset": "2", "Limit": "1", "Email": "a+b@example.test"}
    assert result["has_more"] is True and result["next_offset"] == 3
    assert len(requests) == 1  # Continuation uses offsets, never a response URL.
    transport(monkeypatch, {"items": None, "totalCount": 0})
    result = await node({"operation": "list_candidates"}).execute({})
    assert result["items"] == [] and result["complete"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("config,expected", [
    ({"operation": "create_candidate", "first_name": "Ava", "email": "ava@example.test"}, {"firstName": "Ava", "email": "ava@example.test"}),
    ({"operation": "update_contact", "contact_id": 6, "company_id": 7, "position": "Recruiter"}, {"companyId": 7, "position": "Recruiter"}),
    ({"operation": "update_company", "company_id": 8, "name": "Example"}, {"name": "Example"}),
    ({"operation": "create_job", "job_title": "Engineer", "company_id": 7}, {"jobTitle": "Engineer", "companyId": 7}),
    ({"operation": "create_candidate_note", "candidate_id": 6, "text": "Interview booked", "note_type": "Interview", "created_by_integration": True}, {"text": "Interview booked", "type": "Interview", "createdByIntegration": True}),
    ({"operation": "add_candidates_to_job", "job_id": 6, "candidate_ids": [7, 8]}, {"candidateId": [7, 8]}),
])
async def test_write_payloads_are_single_documented_requests(monkeypatch, config, expected):
    op = native.OPERATIONS[config["operation"]]
    requests = transport(monkeypatch, {"candidateId": 7}, op["status"][0])
    result = await node(config).execute({})
    assert len(requests) == 1 and requests[0].method == op["method"]
    assert json.loads(requests[0].content) == expected
    assert result["write_acknowledged"] is True and result["readback_verified"] is False


@pytest.mark.asyncio
async def test_provider_rejection_redacts_tokens_and_never_retries(monkeypatch):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, 401)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"error": "bad"}, {"items": "bad", "totalCount": 2}, {"items": [], "totalCount": -1}])
async def test_invalid_list_is_not_success(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_jobs"}).execute({})


def test_invalid_config_fails_before_requests():
    for config in [
        {"operation": "get_job", "job_id": "https://bad.example"},
        {"operation": "get_candidate", "candidate_id": 0},
        {"operation": "create_company"},
        {"operation": "create_candidate_note", "candidate_id": 1, "text": ""},
        {"operation": "list_jobs", "limit": 1001},
    ]:
        with pytest.raises(ValueError):
            node(config)
    with pytest.raises(ValidationError):
        native.JobAdderOAuthCredential(access_token=TOKEN, expires_at="2026-11-01")


@pytest.mark.asyncio
async def test_execute_uses_shared_refresh_and_adopts_rotated_token(monkeypatch):
    calls = []
    async def fresh(**kwargs):
        calls.append(kwargs)
        kwargs["credential"].update(access_token="rotated-access", refresh_token="rotated-refresh")
        return "rotated-access"
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", fresh)
    requests = transport(monkeypatch, {"userId": 9})
    n = node({"operation": "get_current_user"}, {"credential_type": "jobadder_oauth", "access_token": TOKEN,
        "refresh_token": "old-refresh", "expires_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()})
    await n.execute({})
    assert calls[0]["provider"] == "jobadder" and calls[0]["refresh"] == OAUTH_PROVIDER.refresh
    assert n.config.credentials.refresh_token == "rotated-refresh"
    assert requests[0].headers["Authorization"] == "Bearer rotated-access"


def test_scope_and_oauth_contract():
    assert set(native.OPERATIONS) == set(native.JOBADDER_SCOPES.keys_declared)
    assert OAUTH_PROVIDER.identity_url == "https://api.jobadder.com/v2/users/current"
    assert OAUTH_PROVIDER.token_auth == "body" and OAUTH_PROVIDER.rotates_refresh_tokens
    assert "offline_access" in native.JOBADDER_SCOPES.declared_scopes()


@pytest.mark.asyncio
async def test_documented_update_acknowledgement_has_no_body(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200)
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "update_candidate", "candidate_id": 1, "email": "new@example.test"}).execute({})
    assert result["write_acknowledged"] is True and result["data"] is None
    assert len(requests) == 1
