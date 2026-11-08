"""Greenhouse Harvest v3 request and OAuth contract tests."""

import base64
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.greenhouse_node import (
    GreenhouseNode, GreenhouseNodeConfig, GreenhouseOAuthCredential, _next_cursor,
    GreenhouseListCandidatesConfig, GreenhouseGetCandidateConfig,
    GreenhouseCreateCandidateConfig, GreenhouseUpdateCandidateConfig,
    GreenhouseListApplicationsConfig, GreenhouseGetApplicationConfig,
    GreenhouseCreateApplicationConfig, GreenhouseMoveApplicationConfig,
    GreenhouseRejectApplicationConfig, GreenhouseListJobsConfig,
    GreenhouseUnrejectApplicationConfig, GreenhouseHireApplicationConfig,
    GreenhouseGetJobConfig, GreenhouseListJobPostsConfig,
    GreenhouseListOpeningsConfig,
    GreenhouseListStagesConfig, GreenhouseListJobInterviewStagesConfig,
    GreenhouseListRejectionReasonsConfig, GreenhouseCreateNoteConfig,
    GreenhouseListTagsConfig, GreenhouseCreateTagConfig,
    GreenhouseApplyTagConfig, GreenhouseListUsersConfig,
    GreenhouseListDepartmentsConfig, GreenhouseListSourcesConfig,
)


CREDS = GreenhouseOAuthCredential(client_id="client-id", client_secret="secret")


def make_node(operation, credentials=CREDS):
    return GreenhouseNode(
        node_id="gh", node_type="automation-greenhouse", node_data={},
        config=GreenhouseNodeConfig(config=operation, credentials=credentials),
        sio=Mock(), sid="test", workflow_id="wf", user_id="user",
    )


@pytest.mark.parametrize("operation,method,path,params,body", [
    (GreenhouseListCandidatesConfig(email="ada@example.com"), "GET", "/candidates", {"per_page": 50, "email": "ada@example.com"}, None),
    (GreenhouseGetCandidateConfig(candidate_id=7), "GET", "/candidates", {"ids": 7}, None),
    (GreenhouseCreateCandidateConfig(first_name="Ada", last_name="Lovelace", email="ada@example.com", job_id=4), "POST", "/candidates", None, {"first_name": "Ada", "last_name": "Lovelace", "email_addresses": [{"value": "ada@example.com", "type": "personal"}], "application": {"job_id": 4}}),
    (GreenhouseUpdateCandidateConfig(candidate_id=7, title="Engineer"), "PATCH", "/candidates/7", None, {"title": "Engineer"}),
    (GreenhouseListApplicationsConfig(candidate_id=7, status="active"), "GET", "/applications", {"per_page": 50, "candidate_ids": 7, "status": "active"}, None),
    (GreenhouseGetApplicationConfig(application_id=8), "GET", "/applications", {"ids": 8}, None),
    (GreenhouseCreateApplicationConfig(candidate_id=7, job_id=4), "POST", "/applications", None, {"candidate_id": 7, "job_id": 4}),
    (GreenhouseMoveApplicationConfig(application_id=8, from_stage_id=2, to_stage_id=3), "POST", "/applications/8/move", None, {"from_stage_id": 2, "to_stage_id": 3}),
    (GreenhouseRejectApplicationConfig(application_id=8, rejection_reason_id=9), "POST", "/applications/8/reject", None, {"rejection_reason_id": 9}),
    (GreenhouseUnrejectApplicationConfig(application_id=8), "POST", "/applications/8/unreject", None, None),
    (GreenhouseHireApplicationConfig(application_id=8, opening_id=3), "POST", "/applications/8/hire", None, {"opening_id": 3}),
    (GreenhouseListJobsConfig(status="open"), "GET", "/jobs", {"per_page": 50, "status": "open"}, None),
    (GreenhouseGetJobConfig(job_id=4), "GET", "/jobs", {"ids": 4}, None),
    (GreenhouseListJobPostsConfig(job_id=4), "GET", "/job_posts", {"per_page": 50, "job_ids": 4}, None),
    (GreenhouseListOpeningsConfig(job_id=4, open=True), "GET", "/openings", {"per_page": 50, "job_ids": 4, "open": True}, None),
    (GreenhouseListStagesConfig(application_id=8), "GET", "/application_stages", {"per_page": 50, "application_ids": 8}, None),
    (GreenhouseListJobInterviewStagesConfig(job_id=4), "GET", "/job_interview_stages", {"per_page": 50, "job_ids": 4}, None),
    (GreenhouseListRejectionReasonsConfig(), "GET", "/rejection_reasons", {"per_page": 50}, None),
    (GreenhouseCreateNoteConfig(candidate_id=7, body="Reviewed", application_id=8), "POST", "/notes", None, {"candidate_id": 7, "body": "Reviewed", "note_type": "NOTE", "visibility": "public", "application_id": 8}),
    (GreenhouseListTagsConfig(), "GET", "/candidate_tags", {"per_page": 50}, None),
    (GreenhouseCreateTagConfig(name="Referral"), "POST", "/candidate_tags", None, {"name": "Referral"}),
    (GreenhouseApplyTagConfig(candidate_id=7, candidate_tag_id=3), "POST", "/applied_candidate_tags", None, {"candidate_id": 7, "candidate_tag_id": 3}),
    (GreenhouseListUsersConfig(primary_email="recruiter@example.com"), "GET", "/users", {"per_page": 50, "primary_email": "recruiter@example.com"}, None),
    (GreenhouseListDepartmentsConfig(), "GET", "/departments", {"per_page": 50}, None),
    (GreenhouseListSourcesConfig(), "GET", "/sources", {"per_page": 50}, None),
])
def test_documented_routes(operation, method, path, params, body):
    assert GreenhouseNode._request_for(operation) == (method, path, params, body)


def test_cursor_excludes_other_filters():
    operation = GreenhouseListCandidatesConfig(cursor="next-opaque", email="ignored@example.com")
    assert GreenhouseNode._request_for(operation)[2] == {"cursor": "next-opaque"}


def test_next_cursor_from_same_origin_link_only():
    link = '<https://harvest.greenhouse.io/v3/jobs?cursor=opaque%2Bnext>; rel="next"'
    assert _next_cursor(link, "/jobs") == "opaque+next"
    assert _next_cursor('<https://evil.example/v3/jobs?cursor=abc>; rel="next"', "/jobs") is None


def test_empty_update_and_unbounded_move_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        GreenhouseNode._request_for(GreenhouseUpdateCandidateConfig(candidate_id=1))
    with pytest.raises(ValueError, match="new stage or job"):
        GreenhouseNode._request_for(GreenhouseMoveApplicationConfig(application_id=1, from_stage_id=2))


@pytest.mark.asyncio
async def test_client_credentials_token_and_harvest_request():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "auth.greenhouse.io":
            assert request.url.path == "/token"
            assert request.headers["authorization"] == "Basic " + base64.b64encode(b"client-id:secret").decode()
            assert request.content == b"grant_type=client_credentials&sub=123"
            return httpx.Response(200, json={"access_token": "short-lived-token"})
        assert request.url.host == "harvest.greenhouse.io"
        assert request.headers["authorization"] == "Bearer short-lived-token"
        assert request.url.path == "/v3/jobs"
        return httpx.Response(200, json=[{"id": 4, "name": "Engineer"}])

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    creds = GreenhouseOAuthCredential(client_id="client-id", client_secret="secret", sub=123)
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=client_factory):
        result = await make_node(GreenhouseListJobsConfig(), creds).execute({})
    assert result["data"] == [{"id": 4, "name": "Engineer"}]
    assert result["count"] == 1
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unauthorized_request_renews_token_once():
    token_count = 0
    api_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_count, api_count
        if request.url.host == "auth.greenhouse.io":
            token_count += 1
            return httpx.Response(200, json={"access_token": f"token-{token_count}"})
        api_count += 1
        if api_count == 1:
            return httpx.Response(401, json={"error": "expired"})
        assert request.headers["authorization"] == "Bearer token-2"
        return httpx.Response(200, json=[])

    original_client = httpx.AsyncClient
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=lambda *a, **kw: original_client(transport=httpx.MockTransport(handler), **kw)):
        result = await make_node(GreenhouseListJobsConfig()).execute({})
    assert result["status"] == "success"
    assert (token_count, api_count) == (2, 2)


@pytest.mark.asyncio
async def test_get_candidate_unwraps_v3_list_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "auth.greenhouse.io":
            return httpx.Response(200, json={"access_token": "token"})
        assert request.url.params["ids"] == "7"
        return httpx.Response(200, json=[{"id": 7, "first_name": "Ada"}])

    original_client = httpx.AsyncClient
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=lambda *a, **kw: original_client(transport=httpx.MockTransport(handler), **kw)):
        result = await make_node(GreenhouseGetCandidateConfig(candidate_id=7)).execute({})
    assert result["data"] == {"id": 7, "first_name": "Ada"}
