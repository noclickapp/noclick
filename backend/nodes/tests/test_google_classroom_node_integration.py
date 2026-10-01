"""Request-level tests for every Google Classroom workflow operation."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.google_classroom_node import (
    GoogleClassroomNode, GoogleClassroomNodeConfig,
    GoogleClassroomOAuthCredential, _request,
)
from wss.handlers.oauth.google_oauth_handler import GoogleOAuthHandler


CREDS = GoogleClassroomOAuthCredential(
    access_token="test-token", refresh_token="refresh-token",
    expires_at="2099-01-01T00:00:00Z", email="teacher@example.com",
)


def node_for(config):
    return GoogleClassroomNode(
        node_id="node-1", node_type="automation-google-classroom", node_data={},
        config=GoogleClassroomNodeConfig(config=config, credentials=CREDS),
        workflow_id="workflow-1", user_id="user-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", [
    ({"operation": "list_courses", "page_size": 20, "page_token": "next"},
     "GET", "/courses", {"pageSize": 20, "pageToken": "next"}, None),
    ({"operation": "get_course", "course_id": "course/1"},
     "GET", "/courses/course%2F1", None, None),
    ({"operation": "create_course", "name": "Biology"},
     "POST", "/courses", None, {"name": "Biology", "ownerId": "me"}),
    ({"operation": "update_course", "course_id": "c1", "name": "New name", "course_state": "ACTIVE"},
     "PATCH", "/courses/c1", {"updateMask": "name,courseState"},
     {"name": "New name", "courseState": "ACTIVE"}),
    ({"operation": "list_coursework", "course_id": "c1"},
     "GET", "/courses/c1/courseWork", {"pageSize": 50}, None),
    ({"operation": "get_coursework", "course_id": "c1", "coursework_id": "w1"},
     "GET", "/courses/c1/courseWork/w1", None, None),
    ({"operation": "create_coursework", "course_id": "c1", "title": "Lab", "max_points": 10},
     "POST", "/courses/c1/courseWork", None,
     {"title": "Lab", "workType": "ASSIGNMENT", "state": "DRAFT", "maxPoints": 10}),
    ({"operation": "list_announcements", "course_id": "c1"},
     "GET", "/courses/c1/announcements", {"pageSize": 50}, None),
    ({"operation": "create_announcement", "course_id": "c1", "text": "Hello"},
     "POST", "/courses/c1/announcements", None, {"text": "Hello", "state": "DRAFT"}),
    ({"operation": "list_topics", "course_id": "c1"},
     "GET", "/courses/c1/topics", {"pageSize": 50}, None),
    ({"operation": "create_topic", "course_id": "c1", "name": "Chapter 1"},
     "POST", "/courses/c1/topics", None, {"name": "Chapter 1"}),
    ({"operation": "list_students", "course_id": "c1"},
     "GET", "/courses/c1/students", {"pageSize": 50}, None),
    ({"operation": "list_submissions", "course_id": "c1", "coursework_id": "w1"},
     "GET", "/courses/c1/courseWork/w1/studentSubmissions", {"pageSize": 50}, None),
])
async def test_operation_routes_and_payload(config, method, path, params, body):
    node = node_for(config)
    with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", new_callable=AsyncMock, return_value="test-token"), \
         patch("nodes.google_classroom_node._request", new_callable=AsyncMock, return_value={"id": "result"}) as request:
        assert await node.execute({}) == {"id": "result"}
    request.assert_awaited_once_with("test-token", method, path, params=params, body=body)


@pytest.mark.asyncio
async def test_update_requires_a_field():
    node = node_for({"operation": "update_course", "course_id": "c1"})
    with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", new_callable=AsyncMock, return_value="test-token"):
        with pytest.raises(ValueError, match="at least one"):
            await node.execute({})


@pytest.mark.asyncio
async def test_course_picker_uses_account_data_and_search():
    with patch("nodes.google_classroom_node._request", new_callable=AsyncMock, return_value={
        "courses": [{"id": "a", "name": "Biology"}, {"id": "b", "name": "History"}]
    }) as request:
        result = await GoogleClassroomNode.load_field_options(
            "course_id", {"access_token": "account-token"}, search="bio"
        )
    assert result == [{"value": "a", "label": "Biology"}]
    request.assert_awaited_once_with("account-token", "GET", "/courses", params={"pageSize": 100})


@pytest.mark.asyncio
async def test_http_error_is_actionable_and_does_not_expose_token():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        return httpx.Response(403, json={"error": {"message": "Classroom API not enabled"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch("nodes.google_classroom_node.httpx.AsyncClient", return_value=client):
        with pytest.raises(ValueError, match="Classroom API 403: Classroom API not enabled") as error:
            await _request("secret-token", "GET", "/courses")
    assert "secret-token" not in str(error.value)


def test_google_oauth_routes_classroom_scopes_to_the_classroom_credential():
    scopes = [
        "email", "https://www.googleapis.com/auth/classroom.courses.readonly",
    ]
    assert GoogleOAuthHandler._get_credential_type_from_scopes(None, scopes) == "google_classroom_oauth"
