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
    ({"operation": "delete_course", "course_id": "c1"},
     "DELETE", "/courses/c1", None, None),
    ({"operation": "update_coursework", "course_id": "c1", "coursework_id": "w1", "title": "New lab"},
     "PATCH", "/courses/c1/courseWork/w1", {"updateMask": "title"}, {"title": "New lab"}),
    ({"operation": "delete_coursework", "course_id": "c1", "coursework_id": "w1"},
     "DELETE", "/courses/c1/courseWork/w1", None, None),
    ({"operation": "get_announcement", "course_id": "c1", "announcement_id": "a1"},
     "GET", "/courses/c1/announcements/a1", None, None),
    ({"operation": "update_announcement", "course_id": "c1", "announcement_id": "a1", "text": "Updated"},
     "PATCH", "/courses/c1/announcements/a1", {"updateMask": "text"}, {"text": "Updated"}),
    ({"operation": "delete_announcement", "course_id": "c1", "announcement_id": "a1"},
     "DELETE", "/courses/c1/announcements/a1", None, None),
    ({"operation": "get_topic", "course_id": "c1", "topic_id": "t1"},
     "GET", "/courses/c1/topics/t1", None, None),
    ({"operation": "update_topic", "course_id": "c1", "topic_id": "t1", "name": "New"},
     "PATCH", "/courses/c1/topics/t1", {"updateMask": "name"}, {"name": "New"}),
    ({"operation": "delete_topic", "course_id": "c1", "topic_id": "t1"},
     "DELETE", "/courses/c1/topics/t1", None, None),
    ({"operation": "get_student", "course_id": "c1", "user_id": "student@example.com"},
     "GET", "/courses/c1/students/student%40example.com", None, None),
    ({"operation": "add_student", "course_id": "c1", "user_id": "student@example.com"},
     "POST", "/courses/c1/students", None, {"userId": "student@example.com"}),
    ({"operation": "remove_student", "course_id": "c1", "user_id": "student@example.com"},
     "DELETE", "/courses/c1/students/student%40example.com", None, None),
    ({"operation": "list_teachers", "course_id": "c1"},
     "GET", "/courses/c1/teachers", {"pageSize": 50}, None),
    ({"operation": "get_teacher", "course_id": "c1", "user_id": "teacher@example.com"},
     "GET", "/courses/c1/teachers/teacher%40example.com", None, None),
    ({"operation": "add_teacher", "course_id": "c1", "user_id": "teacher@example.com"},
     "POST", "/courses/c1/teachers", None, {"userId": "teacher@example.com"}),
    ({"operation": "remove_teacher", "course_id": "c1", "user_id": "teacher@example.com"},
     "DELETE", "/courses/c1/teachers/teacher%40example.com", None, None),
    ({"operation": "list_invitations", "course_id": "c1"},
     "GET", "/invitations", {"pageSize": 50, "courseId": "c1"}, None),
    ({"operation": "get_invitation", "invitation_id": "i1"},
     "GET", "/invitations/i1", None, None),
    ({"operation": "create_invitation", "course_id": "c1", "user_id": "s@example.com"},
     "POST", "/invitations", None,
     {"courseId": "c1", "userId": "s@example.com", "role": "STUDENT"}),
    ({"operation": "delete_invitation", "invitation_id": "i1"},
     "DELETE", "/invitations/i1", None, None),
    ({"operation": "accept_invitation", "invitation_id": "i1"},
     "POST", "/invitations/i1:accept", None, None),
    ({"operation": "get_submission", "course_id": "c1", "coursework_id": "w1", "submission_id": "s1"},
     "GET", "/courses/c1/courseWork/w1/studentSubmissions/s1", None, None),
    ({"operation": "grade_submission", "course_id": "c1", "coursework_id": "w1", "submission_id": "s1", "draft_grade": 92},
     "PATCH", "/courses/c1/courseWork/w1/studentSubmissions/s1",
     {"updateMask": "draftGrade"}, {"draftGrade": 92}),
    ({"operation": "return_submission", "course_id": "c1", "coursework_id": "w1", "submission_id": "s1"},
     "POST", "/courses/c1/courseWork/w1/studentSubmissions/s1:return", None, None),
    ({"operation": "list_materials", "course_id": "c1"},
     "GET", "/courses/c1/courseWorkMaterials", {"pageSize": 50}, None),
    ({"operation": "get_material", "course_id": "c1", "material_id": "m1"},
     "GET", "/courses/c1/courseWorkMaterials/m1", None, None),
    ({"operation": "create_material", "course_id": "c1", "title": "Reading"},
     "POST", "/courses/c1/courseWorkMaterials", None,
     {"title": "Reading", "state": "DRAFT"}),
    ({"operation": "update_material", "course_id": "c1", "material_id": "m1", "title": "New reading"},
     "PATCH", "/courses/c1/courseWorkMaterials/m1", {"updateMask": "title"},
     {"title": "New reading"}),
    ({"operation": "delete_material", "course_id": "c1", "material_id": "m1"},
     "DELETE", "/courses/c1/courseWorkMaterials/m1", None, None),
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
