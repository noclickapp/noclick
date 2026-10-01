"""Google Classroom courses, assignments, announcements, topics, and rosters."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional, Type, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.scopes.google import GOOGLE_CLASSROOM_SCOPES

API_BASE = "https://classroom.googleapis.com/v1"

OPERATION_DESCRIPTIONS = {
    "list_courses": "List courses visible to the connected teacher or student.",
    "get_course": "Read a course by its Classroom ID.",
    "create_course": "Create a course owned by the connected user or another teacher.",
    "update_course": "Change course details or state.",
    "list_coursework": "List assignments and questions in a course.",
    "get_coursework": "Read one assignment or question.",
    "create_coursework": "Create a draft or published assignment.",
    "list_announcements": "List course announcements.",
    "create_announcement": "Create a draft or published announcement.",
    "list_topics": "List course topics.",
    "create_topic": "Create a topic in a course.",
    "list_students": "List enrolled students in a course.",
    "list_submissions": "List student submissions for one assignment.",
}


class GoogleClassroomOAuthCredential(BaseModel):
    credential_type: Literal["google_classroom_oauth"] = Field(
        "google_classroom_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str
    refresh_token: str
    expires_at: str
    email: str

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "google",
        "x-oauth-scopes": [
            "https://www.googleapis.com/auth/classroom.courses.readonly",
            "https://www.googleapis.com/auth/classroom.courses",
            "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
            "https://www.googleapis.com/auth/classroom.coursework.students",
            "https://www.googleapis.com/auth/classroom.announcements.readonly",
            "https://www.googleapis.com/auth/classroom.announcements",
            "https://www.googleapis.com/auth/classroom.topics.readonly",
            "https://www.googleapis.com/auth/classroom.topics",
            "https://www.googleapis.com/auth/classroom.rosters.readonly",
            "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
        ],
    })


def _operation(name: str, label: str, category: str, *, creates: bool = False):
    extra = {
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": label, "x-is-trigger": False,
    }
    if creates:
        extra["x-creates-resource"] = True
        extra["x-resource-type"] = "google_classroom"
        extra["x-resource-id-path"] = "id"
    return Field(name, title=label, description=OPERATION_DESCRIPTIONS[name], json_schema_extra=extra)


COURSE_PICKER = {"x-dynamic-options": {
    "field_name": "course_id", "placeholder": "Select a course...",
    "searchable": True, "allow_custom": True,
    "custom_placeholder": "Or paste a course ID",
}}


class ListCourses(BaseModel):
    operation: Literal["list_courses"] = _operation("list_courses", "List Courses", "Courses")
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class GetCourse(BaseModel):
    operation: Literal["get_course"] = _operation("get_course", "Get Course", "Courses")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)


class CreateCourse(BaseModel):
    operation: Literal["create_course"] = _operation("create_course", "Create Course", "Courses", creates=True)
    name: str = Field(..., title="Course Name")
    owner_id: str = Field("me", title="Owner ID", description="Google user ID or 'me'.")
    section: Optional[str] = None
    description: Optional[str] = None


class UpdateCourse(BaseModel):
    operation: Literal["update_course"] = _operation("update_course", "Update Course", "Courses")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    name: Optional[str] = None
    section: Optional[str] = None
    description: Optional[str] = None
    course_state: Optional[Literal["ACTIVE", "ARCHIVED", "PROVISIONED", "DECLINED", "SUSPENDED"]] = None


class ListCourseWork(BaseModel):
    operation: Literal["list_coursework"] = _operation("list_coursework", "List Course Work", "Course Work")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class GetCourseWork(BaseModel):
    operation: Literal["get_coursework"] = _operation("get_coursework", "Get Course Work", "Course Work")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")


class CreateCourseWork(BaseModel):
    operation: Literal["create_coursework"] = _operation("create_coursework", "Create Assignment", "Course Work", creates=True)
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    title: str
    description: Optional[str] = None
    state: Literal["PUBLISHED", "DRAFT"] = "DRAFT"
    max_points: Optional[float] = Field(None, ge=0)
    topic_id: Optional[str] = None


class ListAnnouncements(BaseModel):
    operation: Literal["list_announcements"] = _operation("list_announcements", "List Announcements", "Announcements")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class CreateAnnouncement(BaseModel):
    operation: Literal["create_announcement"] = _operation("create_announcement", "Create Announcement", "Announcements", creates=True)
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    text: str = Field(..., json_schema_extra={"ui:widget": "textarea"})
    state: Literal["PUBLISHED", "DRAFT"] = "DRAFT"


class ListTopics(BaseModel):
    operation: Literal["list_topics"] = _operation("list_topics", "List Topics", "Topics")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class CreateTopic(BaseModel):
    operation: Literal["create_topic"] = _operation("create_topic", "Create Topic", "Topics", creates=True)
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    name: str


class ListStudents(BaseModel):
    operation: Literal["list_students"] = _operation("list_students", "List Students", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class ListSubmissions(BaseModel):
    operation: Literal["list_submissions"] = _operation("list_submissions", "List Submissions", "Course Work")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


GoogleClassroomConfig = Annotated[
    Union[
        ListCourses, GetCourse, CreateCourse, UpdateCourse, ListCourseWork,
        GetCourseWork, CreateCourseWork, ListAnnouncements, CreateAnnouncement,
        ListTopics, CreateTopic, ListStudents, ListSubmissions,
    ],
    Discriminator("operation"),
]


class GoogleClassroomNodeConfig(NodeConfig[GoogleClassroomConfig, GoogleClassroomOAuthCredential]):
    pass


def _segment(value: str) -> str:
    """Encode a single path segment so user-supplied IDs cannot alter the route."""
    return quote(value, safe="")


def _page_params(config: BaseModel) -> dict[str, Any]:
    return {"pageSize": config.page_size, **({"pageToken": config.page_token} if config.page_token else {})}


async def _request(token: str, method: str, path: str, *, params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method, f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params, json=body,
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = response.json().get("error", {}).get("message", response.reason_phrase)
        except ValueError:
            detail = response.reason_phrase
        raise ValueError(f"Google Classroom API {response.status_code}: {detail}") from exc
    return response.json() if response.content else {}


class GoogleClassroomNode(WorkflowNode):
    """Common Google Classroom teacher workflows and read-only roster access."""

    scope_registry = GOOGLE_CLASSROOM_SCOPES
    connection_evidence = ConnectionEvidence(field="course_id", noun="courses")
    edit_examples = [
        "List my Google Classroom courses and assignments",
        "Create a draft assignment in my biology class",
        "Post an announcement to the class",
        "Read student submissions for an assignment",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return GoogleClassroomNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token,
            provider="google",
        )

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "course_id":
            return []
        token = require_credential_token(
            credential_data.get("access_token"), "Connect a Google account to load courses"
        )
        data = await _request(token, "GET", "/courses", params={"pageSize": 100})
        courses = data.get("courses", [])
        if search:
            courses = [course for course in courses if search.casefold() in course.get("name", "").casefold()]
        return [{"value": course["id"], "label": course.get("name") or course["id"]}
                for course in courses if course.get("id")]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, GoogleClassroomNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Google Classroom account before running this node")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        credential = self.config.credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential,
            refresh=refresh_access_token, provider="google",
        )
        config = self.config.config
        path = "/courses"
        if hasattr(config, "course_id"):
            path += f"/{_segment(config.course_id)}"
        params = body = None
        method = "GET"
        if isinstance(config, ListCourses):
            params = _page_params(config)
        elif isinstance(config, GetCourse):
            pass
        elif isinstance(config, CreateCourse):
            method = "POST"
            body = {"name": config.name, "ownerId": config.owner_id,
                    **({"section": config.section} if config.section is not None else {}),
                    **({"description": config.description} if config.description is not None else {})}
        elif isinstance(config, UpdateCourse):
            body = {k: v for k, v in {
                "name": config.name, "section": config.section,
                "description": config.description, "courseState": config.course_state,
            }.items() if v is not None}
            if not body:
                raise ValueError("Set at least one course field to update")
            method = "PATCH"
            params = {"updateMask": ",".join(body)}
        elif isinstance(config, ListCourseWork):
            path += "/courseWork"
            params = _page_params(config)
        elif isinstance(config, GetCourseWork):
            path += f"/courseWork/{_segment(config.coursework_id)}"
        elif isinstance(config, CreateCourseWork):
            path += "/courseWork"
            method = "POST"
            body = {"title": config.title, "workType": "ASSIGNMENT", "state": config.state,
                    **({"description": config.description} if config.description is not None else {}),
                    **({"maxPoints": config.max_points} if config.max_points is not None else {}),
                    **({"topicId": config.topic_id} if config.topic_id else {})}
        elif isinstance(config, ListAnnouncements):
            path += "/announcements"
            params = _page_params(config)
        elif isinstance(config, CreateAnnouncement):
            path += "/announcements"
            method = "POST"
            body = {"text": config.text, "state": config.state}
        elif isinstance(config, ListTopics):
            path += "/topics"
            params = _page_params(config)
        elif isinstance(config, CreateTopic):
            path += "/topics"
            method = "POST"
            body = {"name": config.name}
        elif isinstance(config, ListStudents):
            path += "/students"
            params = _page_params(config)
        elif isinstance(config, ListSubmissions):
            path += f"/courseWork/{_segment(config.coursework_id)}/studentSubmissions"
            params = _page_params(config)
        else:
            raise ValueError("Unsupported Google Classroom operation")
        output = await _request(token, method, path, params=params, body=body)
        await self.emit(output)
        return output
