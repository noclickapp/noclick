"""Exercise TalentLMS through the registered factory and guarded HTTP transport."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import talentlms_node as talent
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "talentlms_api_key", "domain": "example", "api_key": "synthetic-talentlms-secret"}
USER = "00000000-0000-0000-0000-000000000001"

CASES = [
    ("list_users", {}, "GET", "/users", None),
    ("get_user", {"user_id": 12}, "GET", "/users/12", None),
    ("create_user", {"name": "John", "surname": "Doe", "login": "johndoe", "email": "john@example.com", "password": "Secret123"}, "POST", "/users", {"name": "John", "surname": "Doe", "login": "johndoe", "email": "john@example.com", "password": "Secret123"}),
    ("update_user", {"user_id": 12, "name": "Changed", "email_notifications": False}, "PATCH", "/users/12", {"name": "Changed", "email_notifications": False}),
    ("delete_user", {"user_id": 12, "permanent": False}, "DELETE", "/users/12", None),
    ("list_courses", {}, "GET", "/courses", None),
    ("get_course", {"course_id": 23}, "GET", "/courses/23", None),
    ("create_course", {"name": "Onboarding", "is_active": False}, "POST", "/courses", {"name": "Onboarding", "is_active": False}),
    ("delete_course", {"course_id": 23}, "DELETE", "/courses/23", None),
    ("enroll_user", {"course_id": 23, "user_id": 12}, "POST", "/enrollments", {"course_id": 23, "user_id": 12}),
    ("unenroll_user", {"course_id": 23, "user_id": 12}, "DELETE", "/enrollments", {"course_id": 23, "user_id": 12}),
    ("get_course_progress", {"course_id": 23, "user_id": 12}, "GET", "/course-progress", None),
    ("reset_course_progress", {"course_id": 23, "user_id": 12, "remove_certificate": False}, "DELETE", "/course-progress", None),
    ("list_groups", {}, "GET", "/groups", None),
    ("get_group", {"group_id": 34}, "GET", "/groups/34", None),
    ("create_group", {"name": "Sales Team", "auto_sync": False}, "POST", "/groups", {"name": "Sales Team", "auto_sync": False}),
    ("delete_group", {"group_id": 34}, "DELETE", "/groups/34", None),
    ("add_group_member", {"group_id": 34, "user_id": 12, "enroll_to_courses": False}, "POST", "/group-memberships", {"group_id": 34, "user_id": 12, "enroll_to_courses": False}),
    ("remove_group_member", {"group_id": 34, "user_id": 12}, "DELETE", "/group-memberships", {"group_id": 34, "user_id": 12}),
    ("list_branches", {}, "GET", "/branches", None),
    ("get_branch", {"branch_id": 45}, "GET", "/branches/45", None),
    ("list_categories", {}, "GET", "/categories", None),
    ("get_category", {"category_id": 56}, "GET", "/categories/56", None),
    ("list_course_users", {"course_id": 23}, "GET", "/courses/23/users", None),
    ("list_user_courses", {"user_id": 12}, "GET", "/users/12/courses", None),
]


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        calls.append(request)
        assert request.url.host == "example.talentlms.com"
        assert request.headers["X-API-Key"] == AUTH["api_key"]
        assert request.headers["Accept"] == "application/json"
        assert AUTH["api_key"] not in str(request.url)
        status, payload, *headers = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, headers=headers[0] if headers else {})
        return httpx.Response(status, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(talent, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type="automation-talentlms", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
async def test_native_requests(operation, arguments, method, path, body, transport):
    calls, replies = transport
    status = 204 if operation in {"update_user", "delete_user", "delete_course", "unenroll_user", "reset_course_progress", "delete_group", "add_group_member", "remove_group_member"} else 200
    data = [{"id": 12, "name": "John"}] if operation.startswith("list_") else {"id": 12}
    if operation == "list_user_courses":
        data = {"courses": [{"id": 23, "name": "Onboarding"}]}
    if operation == "enroll_user":
        data = {"role": "learner"}
    replies.append((status, b"" if status == 204 else {"_data": data}))
    result = await run(operation, arguments)
    assert result["success"] is True
    assert result["http_status"] == status
    assert len(calls) == 1 and not replies
    request = calls[0]
    assert request.method == method and request.url.path == "/api/v2" + path
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "reset_course_progress":
        assert dict(request.url.params) == {"course_id": "23", "user_id": "12", "remove-certificate": "false"}
    if operation == "delete_user":
        assert dict(request.url.params) == {"permanent": "false"}
    if operation == "get_course_progress":
        assert dict(request.url.params) == {"course_id": "23", "user_id": "12"}
    if status == 204:
        assert result["acknowledged"] is True and "data" not in result


@pytest.mark.asyncio
async def test_one_page_filters_and_returned_links_never_followed(transport):
    calls, replies = transport
    page = json.loads((Path(__file__).parent / "fixtures/talentlms/users.json").read_text())
    replies.append((200, page))
    result = await run("list_users", {"page_number": 2, "page_size": 10, "email_eq": "john@example.com", "last_updated_gte": "2024-01-01T00:00:00Z"})
    assert len(calls) == 1
    assert calls[0].url.params["page[number]"] == "2"
    assert calls[0].url.params["page[size]"] == "10"
    assert calls[0].url.params["filter[email][eq]"] == "john@example.com"
    assert calls[0].url.params["filter[last_updated][gte]"] == "2024-01-01T00:00:00Z"
    assert result["data"][0]["name"] == "John"
    assert result["pagination"] == page["_meta"] and result["links"] == page["_links"]


@pytest.mark.asyncio
async def test_enroll_by_email_and_empty_account_evidence(transport):
    transport[1].append((200, {"_data": {"role": "learner"}}))
    await run("enroll_user", {"course_id": 23, "user_email": "john@example.com"})
    assert json.loads(transport[0][0].content) == {"course_id": 23, "user_email": "john@example.com"}
    transport[1].append((200, {"_data": []}))
    assert (await run("list_users"))["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload,headers", [
    (401, {"error": {"type": "api_error", "message": "Invalid API key"}}, {}),
    (429, {"error": {"message": "Rate limit exceeded"}}, {}),
    (302, b"", {"Location": "https://foreign.example"}),
    (200, b"login page", {"Content-Type": "text/html"}),
    (200, {"error": "denied"}, {}),
    (200, {"_data": {}}, {}),
])
async def test_rejections_and_invalid_responses(code, payload, headers, transport):
    transport[1].append((code, payload, headers))
    try:
        result = await run("list_users")
    except ValueError:
        pass
    else:
        assert result["success"] is False
        if code == 401:
            assert result["error"] == "Invalid API key"
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_no_secret_reflection(transport):
    transport[1].append((401, {"error": {"message": "Rejected " + AUTH["api_key"]}}))
    assert AUTH["api_key"] not in json.dumps(await run("list_users"))
    transport[1].append((200, {"_data": {"id": 12, "password": "Secret123", "echo": AUTH["api_key"]}}))
    result = await run("create_user", CASES[2][1])
    assert AUTH["api_key"] not in json.dumps(result) and "Secret123" not in json.dumps(result)


@pytest.mark.parametrize("portal", ["https://evil.example", "http://example.talentlms.com", "https://user:pass@example.talentlms.com", "https://example.talentlms.com:8443", "https://example.talentlms.com/api/v2", "https://example.talentlms.com?key=x", "https://127.0.0.1", "https://example.talentlms.com.evil.example"])
def test_credential_host_validation(portal):
    with pytest.raises(ValueError):
        talent.TalentLMSAPIKeyCredential.model_validate({**AUTH, "domain": portal})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", [
    ("get_user", {"user_id": "../1"}), ("get_user", {"user_id": 0}),
    ("list_users", {"page_size": 101}), ("list_users", {"last_updated_gte": "invalid"}),
    ("update_user", {"user_id": 12}), ("enroll_user", {"course_id": 23}),
    ("create_user", {**CASES[2][1], "password": "weakpass"}),
    ("get_user", {"user_id": 12, "resources": "passwords"}),
    ("get_user", {"user_id": 12, "arbitrary": True}),
])
async def test_invalid_config_before_transport(operation, arguments, transport):
    with pytest.raises(ValueError):
        await run(operation, arguments)
    assert not transport[0]


def test_manual_credential_defaults_and_portal_normalization():
    credential = talent.TalentLMSAPIKeyCredential.model_validate({"domain": "example", "api_key": AUTH["api_key"]})
    assert credential.credential_type == "talentlms_api_key"
    assert credential.domain == "https://example.talentlms.com"
