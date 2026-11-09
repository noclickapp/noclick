"""Exercise native Recruit CRM operations through discovery and the real transport seam."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import recruitcrm_node as crm
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = "recruitcrm-fixture-token-never-live"
AUTH = {"credential_type": "recruitcrm_api_token", "api_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.recruitcrm.io"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        code, body = replies.pop(0)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, bytes):
            return httpx.Response(code, content=body)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(crm, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=AUTH):
    return await run_node_operation(node_type="automation-recruitcrm", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(credential), user_id=USER)


# Independent provider routes and representative inputs; this table does not read ROUTES.
CASES = [
    ("list_candidates", {"page": 2, "limit": 10}, "GET", "/v1/candidates"),
    ("get_candidate", {"candidate": "010011"}, "GET", "/v1/candidates/010011"),
    ("search_candidates", {"email": "mscott@gmail.com"}, "GET", "/v1/candidates/search"),
    ("create_candidate", {"first_name": "Michael", "email": "mscott@gmail.com"}, "POST", "/v1/candidates"),

    ("list_companies", {}, "GET", "/v1/companies"),
    ("get_company", {"company": "c01"}, "GET", "/v1/companies/c01"),
    ("search_companies", {"company_name": "Recruit CRM"}, "GET", "/v1/companies/search"),
    ("create_company", {"company_name": "Recruit CRM"}, "POST", "/v1/companies"),
    ("update_company", {"company": "c01", "company_name": "Recruit CRM", "city": "New York"}, "POST", "/v1/companies/c01"),
    ("list_contacts", {}, "GET", "/v1/contacts"),
    ("get_contact", {"contact": "p01"}, "GET", "/v1/contacts/p01"),
    ("search_contacts", {"email": "ryan.cooper@example.com"}, "GET", "/v1/contacts/search"),
    ("create_contact", {"first_name": "Ryan", "last_name": "Cooper"}, "POST", "/v1/contacts"),
    ("update_contact", {"contact": "p01", "designation": "Manager"}, "POST", "/v1/contacts/p01"),
    ("list_jobs", {}, "GET", "/v1/jobs"),
    ("get_job", {"job": "j01"}, "GET", "/v1/jobs/j01"),
    ("search_jobs", {"name": "Manager"}, "GET", "/v1/jobs/search"),
    ("assign_candidate", {"candidate": "1278655", "job_slug": "1206683"}, "POST", "/v1/candidates/1278655/assign"),
    ("get_hiring_stage", {"candidate": "1278655", "job": "1206683"}, "GET", "/v1/candidates/1278655/hiring-stages/1206683"),
    ("update_hiring_stage", {"candidate": "1278655", "job": "1206683", "status_id": 1, "remark": "Updated"}, "POST", "/v1/candidates/1278655/hiring-stages/1206683"),
    ("list_tasks", {}, "GET", "/v1/tasks"),
    ("get_task", {"task": 2}, "GET", "/v1/tasks/2"),
    ("create_task", {"title": "Follow up call", "reminder": 30, "start_date": "2020-06-29T05:36:22.000000Z"}, "POST", "/v1/tasks"),
    ("list_notes", {}, "GET", "/v1/notes"),
    ("create_note", {"description": "Will be open for offer after 2 months", "related_to": "23123", "related_to_type": "candidate"}, "POST", "/v1/notes"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path", CASES)
async def test_native_routes_and_encodings(transport, operation, config, method, path):
    requests, replies = transport
    payload = {"slug": "record01", "first_name": "Michael"}
    if operation.startswith(("list_", "search_")):
        payload = {"data": [payload], "current_page": 1, "next_page_url": None}
    if operation == "assign_candidate":
        payload = json.loads((Path(__file__).parent / "fixtures/recruitcrm/assigned_candidate.json").read_text())["body"]
    replies.append((200, payload))
    output = await run(operation, config)
    assert output["success"] is True and output["data"] == payload
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == path
    if method == "GET":
        assert not request.content
        for key, value in config.items():
            if "{" + key + "}" not in {"{candidate}", "{company}", "{contact}", "{job}", "{task}"}:
                assert request.url.params[key] == str(value)
    elif operation == "assign_candidate":
        assert request.url.params["job_slug"] == config["job_slug"]
        assert not request.content
    else:
        expected = {k: v for k, v in config.items() if k not in {"candidate", "company", "contact", "job"}}
        if "start_date" in expected:
            expected["start_date"] = datetime.fromisoformat(expected["start_date"]).isoformat().replace("+00:00", "Z")
        assert json.loads(request.content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (401, {"errorMessage": "API token is not active"}),
    (403, {"message": "Token rejected"}),
    (429, {"message": "Too many requests"}),
    (500, {"message": "Internal error"}),
    (200, {"error": True, "errorMessage": "Rejected"}),
])
async def test_failures_are_not_connection_successes_or_retried(transport, status, body):
    transport[1].append((status, body))
    result = await run("list_candidates")
    assert result["success"] is False
    assert result["message"] == body.get("errorMessage", body.get("message"))
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_one_page_does_not_follow_provider_next_url(transport):
    payload = {"data": [], "current_page": 2, "next_page_url": "https://untrusted.example/steal"}
    transport[1].append((200, payload))
    result = await run("list_candidates", {"page": 2, "limit": 10})
    assert result["data"] == payload
    assert dict(transport[0][0].url.params) == {"page": "2", "limit": "10", "sort_by": "updatedon", "sort_order": "desc"}
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_secrets_redacted_in_provider_error_and_success(transport):
    transport[1].append((403, {"message": "Rejected " + TOKEN}))
    assert TOKEN not in json.dumps(await run("list_candidates"))
    transport[1].append((200, {"description": TOKEN}))
    assert TOKEN not in json.dumps(await run("create_company", {"company_name": "Example"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"<html>Bad gateway</html>", b"null", b'"ok"'])
async def test_unreadable_or_scalar_response_fails(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await run("list_candidates")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_write_transport_failure_is_not_retried(transport):
    transport[1].append((200, httpx.ReadTimeout("private URL")))
    with pytest.raises(ValueError, match="verify the outcome"):
        await run("create_company", {"company_name": "Example"})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["../secret", "a/b", "a?x=1", "a%2fb", "https://evil.example", "a\n"])
async def test_path_injection_rejected_before_http(transport, slug):
    with pytest.raises(ValueError):
        await run("get_candidate", {"candidate": slug})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_foreign_credential_and_unsupported_fields_refused(transport):
    with pytest.raises(ValueError):
        await run("list_candidates", credential={**AUTH, "credential_type": "foreign_api_key"})
    with pytest.raises(ValueError):
        await run("create_company", {"company_name": "Example", "arbitrary_field": "bad"})
    with pytest.raises(ValueError):
        await run("update_contact", {"contact": "p01"})
    assert transport[0] == []


def test_manual_connect_defaults_type_and_shows_only_token():
    from nodes.core.credential_connect import shape_credential, typed_fields
    value, errors, _ = shape_credential("recruitcrm_api_token", {"api_token": "  " + TOKEN + "\n"})
    assert not errors and value["api_token"] == TOKEN
    assert crm.RecruitCRMTokenCredential.model_validate(value).credential_type == "recruitcrm_api_token"
    assert [f["name"] for f in typed_fields("recruitcrm_api_token")] == ["api_token"]


@pytest.mark.parametrize("token", ["Bearer abc", "https://example.com", "<token>", "abc\nxyz", "é"])
def test_invalid_token_cannot_be_pasted(token):
    with pytest.raises(ValueError):
        crm.RecruitCRMTokenCredential(api_token=token)
