"""Google Classroom courses, assignments, announcements, topics, and rosters."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional, Type, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CLASSROOM = "https://www.googleapis.com/auth/classroom."

GOOGLE_CLASSROOM_SCOPES = ScopeRegistry(
    provider="google-classroom",
    requirements={operation: ScopeRequirement(scopes=(scope,))
                  for scope, operations in {
        CLASSROOM + "courses.readonly": ("list_courses", "get_course"),
        CLASSROOM + "courses": ("create_course", "update_course", "delete_course"),
        CLASSROOM + "coursework.students.readonly": ("list_coursework", "get_coursework"),
        CLASSROOM + "coursework.students": (
            "create_coursework", "update_coursework", "delete_coursework",
            "grade_submission", "return_submission",
        ),
        CLASSROOM + "announcements.readonly": ("list_announcements", "get_announcement"),
        CLASSROOM + "announcements": (
            "create_announcement", "update_announcement", "delete_announcement",
        ),
        CLASSROOM + "topics.readonly": ("list_topics", "get_topic"),
        CLASSROOM + "topics": ("create_topic", "update_topic", "delete_topic"),
        CLASSROOM + "rosters.readonly": (
            "list_students", "get_student", "list_teachers", "get_teacher",
            "list_invitations", "get_invitation",
        ),
        CLASSROOM + "rosters": (
            "add_student", "remove_student", "add_teacher", "remove_teacher",
            "create_invitation", "delete_invitation", "accept_invitation",
        ),
        CLASSROOM + "courseworkmaterials.readonly": ("list_materials", "get_material"),
        CLASSROOM + "courseworkmaterials": (
            "create_material", "update_material", "delete_material",
        ),
        CLASSROOM + "student-submissions.students.readonly": (
            "list_submissions", "get_submission",
        ),
    }.items() for operation in operations},
)

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
    "delete_course": "Delete a course that Classroom permits the user to delete.",
    "update_coursework": "Change an assignment created by this OAuth project.",
    "delete_coursework": "Delete an assignment created by this OAuth project.",
    "get_announcement": "Read one announcement.",
    "update_announcement": "Change an announcement created by this OAuth project.",
    "delete_announcement": "Delete an announcement created by this OAuth project.",
    "get_topic": "Read one topic.",
    "update_topic": "Rename a topic.",
    "delete_topic": "Delete a topic.",
    "get_student": "Read an enrolled student's roster entry.",
    "add_student": "Enroll a student by Google user ID or email address.",
    "remove_student": "Remove a student from a course.",
    "list_teachers": "List teachers in a course.",
    "get_teacher": "Read a teacher's roster entry.",
    "add_teacher": "Add a teacher by Google user ID or email address.",
    "remove_teacher": "Remove a teacher from a course.",
    "list_invitations": "List course invitations.",
    "get_invitation": "Read an invitation by ID.",
    "create_invitation": "Invite a teacher or student to a course.",
    "delete_invitation": "Cancel an invitation.",
    "accept_invitation": "Accept an invitation for the connected account.",
    "get_submission": "Read one student submission.",
    "grade_submission": "Set draft or assigned points on a submission.",
    "return_submission": "Return a graded submission to the student.",
    "list_materials": "List course work materials.",
    "get_material": "Read one course work material.",
    "create_material": "Create draft or published course material.",
    "update_material": "Change course material created by this OAuth project.",
    "delete_material": "Delete course material created by this OAuth project.",
}


class GoogleClassroomOAuthCredential(BaseModel):
    credential_type: Literal["google_oauth", "google_classroom_oauth"] = Field(
        "google_oauth", json_schema_extra={"ui:hidden": True}
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
            "https://www.googleapis.com/auth/classroom.rosters",
            "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
            "https://www.googleapis.com/auth/classroom.courseworkmaterials",
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


class DeleteCourse(BaseModel):
    operation: Literal["delete_course"] = _operation("delete_course", "Delete Course", "Courses")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)


class UpdateCourseWork(BaseModel):
    operation: Literal["update_coursework"] = _operation("update_coursework", "Update Course Work", "Course Work")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")
    title: Optional[str] = None
    description: Optional[str] = None
    state: Optional[Literal["PUBLISHED", "DRAFT"]] = None
    max_points: Optional[float] = Field(None, ge=0)
    topic_id: Optional[str] = None


class DeleteCourseWork(BaseModel):
    operation: Literal["delete_coursework"] = _operation("delete_coursework", "Delete Course Work", "Course Work")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")


class GetAnnouncement(BaseModel):
    operation: Literal["get_announcement"] = _operation("get_announcement", "Get Announcement", "Announcements")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    announcement_id: str = Field(..., title="Announcement ID")


class UpdateAnnouncement(BaseModel):
    operation: Literal["update_announcement"] = _operation("update_announcement", "Update Announcement", "Announcements")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    announcement_id: str = Field(..., title="Announcement ID")
    text: Optional[str] = Field(None, json_schema_extra={"ui:widget": "textarea"})
    state: Optional[Literal["PUBLISHED", "DRAFT"]] = None


class DeleteAnnouncement(BaseModel):
    operation: Literal["delete_announcement"] = _operation("delete_announcement", "Delete Announcement", "Announcements")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    announcement_id: str = Field(..., title="Announcement ID")


class GetTopic(BaseModel):
    operation: Literal["get_topic"] = _operation("get_topic", "Get Topic", "Topics")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    topic_id: str = Field(..., title="Topic ID")


class UpdateTopic(BaseModel):
    operation: Literal["update_topic"] = _operation("update_topic", "Update Topic", "Topics")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    topic_id: str = Field(..., title="Topic ID")
    name: str


class DeleteTopic(BaseModel):
    operation: Literal["delete_topic"] = _operation("delete_topic", "Delete Topic", "Topics")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    topic_id: str = Field(..., title="Topic ID")


class GetStudent(BaseModel):
    operation: Literal["get_student"] = _operation("get_student", "Get Student", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="Student ID or Email")


class AddStudent(BaseModel):
    operation: Literal["add_student"] = _operation("add_student", "Add Student", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="Student ID or Email")


class RemoveStudent(BaseModel):
    operation: Literal["remove_student"] = _operation("remove_student", "Remove Student", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="Student ID or Email")


class ListTeachers(BaseModel):
    operation: Literal["list_teachers"] = _operation("list_teachers", "List Teachers", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class GetTeacher(BaseModel):
    operation: Literal["get_teacher"] = _operation("get_teacher", "Get Teacher", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="Teacher ID or Email")


class AddTeacher(BaseModel):
    operation: Literal["add_teacher"] = _operation("add_teacher", "Add Teacher", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="Teacher ID or Email")


class RemoveTeacher(BaseModel):
    operation: Literal["remove_teacher"] = _operation("remove_teacher", "Remove Teacher", "Roster")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="Teacher ID or Email")


class ListInvitations(BaseModel):
    operation: Literal["list_invitations"] = _operation("list_invitations", "List Invitations", "Invitations")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class GetInvitation(BaseModel):
    operation: Literal["get_invitation"] = _operation("get_invitation", "Get Invitation", "Invitations")
    invitation_id: str = Field(..., title="Invitation ID")


class CreateInvitation(BaseModel):
    operation: Literal["create_invitation"] = _operation("create_invitation", "Create Invitation", "Invitations", creates=True)
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    user_id: str = Field(..., title="User ID or Email")
    role: Literal["STUDENT", "TEACHER"] = "STUDENT"


class DeleteInvitation(BaseModel):
    operation: Literal["delete_invitation"] = _operation("delete_invitation", "Delete Invitation", "Invitations")
    invitation_id: str = Field(..., title="Invitation ID")


class AcceptInvitation(BaseModel):
    operation: Literal["accept_invitation"] = _operation("accept_invitation", "Accept Invitation", "Invitations")
    invitation_id: str = Field(..., title="Invitation ID")


class GetSubmission(BaseModel):
    operation: Literal["get_submission"] = _operation("get_submission", "Get Submission", "Submissions")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")
    submission_id: str = Field(..., title="Submission ID")


class GradeSubmission(BaseModel):
    operation: Literal["grade_submission"] = _operation("grade_submission", "Grade Submission", "Submissions")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")
    submission_id: str = Field(..., title="Submission ID")
    draft_grade: Optional[float] = Field(None, ge=0)
    assigned_grade: Optional[float] = Field(None, ge=0)


class ReturnSubmission(BaseModel):
    operation: Literal["return_submission"] = _operation("return_submission", "Return Submission", "Submissions")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    coursework_id: str = Field(..., title="Course Work ID")
    submission_id: str = Field(..., title="Submission ID")


class ListMaterials(BaseModel):
    operation: Literal["list_materials"] = _operation("list_materials", "List Materials", "Materials")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    page_size: int = Field(50, ge=1, le=100)
    page_token: Optional[str] = None


class GetMaterial(BaseModel):
    operation: Literal["get_material"] = _operation("get_material", "Get Material", "Materials")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    material_id: str = Field(..., title="Material ID")


class CreateMaterial(BaseModel):
    operation: Literal["create_material"] = _operation("create_material", "Create Material", "Materials", creates=True)
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    title: str
    description: Optional[str] = None
    state: Literal["PUBLISHED", "DRAFT"] = "DRAFT"
    topic_id: Optional[str] = None


class UpdateMaterial(BaseModel):
    operation: Literal["update_material"] = _operation("update_material", "Update Material", "Materials")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    material_id: str = Field(..., title="Material ID")
    title: Optional[str] = None
    description: Optional[str] = None
    state: Optional[Literal["PUBLISHED", "DRAFT"]] = None
    topic_id: Optional[str] = None


class DeleteMaterial(BaseModel):
    operation: Literal["delete_material"] = _operation("delete_material", "Delete Material", "Materials")
    course_id: str = Field(..., title="Course", json_schema_extra=COURSE_PICKER)
    material_id: str = Field(..., title="Material ID")


GoogleClassroomConfig = Annotated[
    Union[
        ListCourses, GetCourse, CreateCourse, UpdateCourse, ListCourseWork,
        GetCourseWork, CreateCourseWork, ListAnnouncements, CreateAnnouncement,
        ListTopics, CreateTopic, ListStudents, ListSubmissions,
        DeleteCourse, UpdateCourseWork, DeleteCourseWork,
        GetAnnouncement, UpdateAnnouncement, DeleteAnnouncement,
        GetTopic, UpdateTopic, DeleteTopic,
        GetStudent, AddStudent, RemoveStudent,
        ListTeachers, GetTeacher, AddTeacher, RemoveTeacher,
        ListInvitations, GetInvitation, CreateInvitation, DeleteInvitation, AcceptInvitation,
        GetSubmission, GradeSubmission, ReturnSubmission,
        ListMaterials, GetMaterial, CreateMaterial, UpdateMaterial, DeleteMaterial,
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


def _patch_body(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    body = {key: value for key, value in values.items() if value is not None}
    if not body:
        raise ValueError("Set at least one field to update")
    return body, {"updateMask": ",".join(body)}


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
    integration_type = "automation-google-classroom"
    credential_provider_labels = {"google_classroom": "Google Classroom Account"}
    auto_select_credential = False

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
            caller_path="execute",
        )
        config = self.config.config
        invitation_operation = isinstance(config, (
            ListInvitations, GetInvitation, CreateInvitation,
            DeleteInvitation, AcceptInvitation,
        ))
        path = "/invitations" if invitation_operation else "/courses"
        if not invitation_operation and hasattr(config, "course_id"):
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
            body, params = _patch_body({
                "name": config.name, "section": config.section,
                "description": config.description, "courseState": config.course_state,
            })
            method = "PATCH"
        elif isinstance(config, DeleteCourse):
            method = "DELETE"
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
        elif isinstance(config, UpdateCourseWork):
            path += f"/courseWork/{_segment(config.coursework_id)}"
            method = "PATCH"
            body, params = _patch_body({
                "title": config.title, "description": config.description,
                "state": config.state, "maxPoints": config.max_points,
                "topicId": config.topic_id,
            })
        elif isinstance(config, DeleteCourseWork):
            path += f"/courseWork/{_segment(config.coursework_id)}"
            method = "DELETE"
        elif isinstance(config, ListAnnouncements):
            path += "/announcements"
            params = _page_params(config)
        elif isinstance(config, CreateAnnouncement):
            path += "/announcements"
            method = "POST"
            body = {"text": config.text, "state": config.state}
        elif isinstance(config, GetAnnouncement):
            path += f"/announcements/{_segment(config.announcement_id)}"
        elif isinstance(config, UpdateAnnouncement):
            path += f"/announcements/{_segment(config.announcement_id)}"
            method = "PATCH"
            body, params = _patch_body({"text": config.text, "state": config.state})
        elif isinstance(config, DeleteAnnouncement):
            path += f"/announcements/{_segment(config.announcement_id)}"
            method = "DELETE"
        elif isinstance(config, ListTopics):
            path += "/topics"
            params = _page_params(config)
        elif isinstance(config, CreateTopic):
            path += "/topics"
            method = "POST"
            body = {"name": config.name}
        elif isinstance(config, GetTopic):
            path += f"/topics/{_segment(config.topic_id)}"
        elif isinstance(config, UpdateTopic):
            path += f"/topics/{_segment(config.topic_id)}"
            method = "PATCH"
            body = {"name": config.name}
            params = {"updateMask": "name"}
        elif isinstance(config, DeleteTopic):
            path += f"/topics/{_segment(config.topic_id)}"
            method = "DELETE"
        elif isinstance(config, ListStudents):
            path += "/students"
            params = _page_params(config)
        elif isinstance(config, (GetStudent, AddStudent, RemoveStudent)):
            path += "/students"
            if isinstance(config, AddStudent):
                method = "POST"
                body = {"userId": config.user_id}
            else:
                path += f"/{_segment(config.user_id)}"
                if isinstance(config, RemoveStudent):
                    method = "DELETE"
        elif isinstance(config, ListTeachers):
            path += "/teachers"
            params = _page_params(config)
        elif isinstance(config, (GetTeacher, AddTeacher, RemoveTeacher)):
            path += "/teachers"
            if isinstance(config, AddTeacher):
                method = "POST"
                body = {"userId": config.user_id}
            else:
                path += f"/{_segment(config.user_id)}"
                if isinstance(config, RemoveTeacher):
                    method = "DELETE"
        elif isinstance(config, ListSubmissions):
            path += f"/courseWork/{_segment(config.coursework_id)}/studentSubmissions"
            params = _page_params(config)
        elif isinstance(config, (GetSubmission, GradeSubmission, ReturnSubmission)):
            path += f"/courseWork/{_segment(config.coursework_id)}/studentSubmissions/{_segment(config.submission_id)}"
            if isinstance(config, GradeSubmission):
                method = "PATCH"
                body, params = _patch_body({
                    "draftGrade": config.draft_grade,
                    "assignedGrade": config.assigned_grade,
                })
            elif isinstance(config, ReturnSubmission):
                method = "POST"
                path += ":return"
        elif isinstance(config, ListInvitations):
            params = _page_params(config)
            if config.course_id:
                params["courseId"] = config.course_id
        elif isinstance(config, CreateInvitation):
            method = "POST"
            body = {"courseId": config.course_id, "userId": config.user_id, "role": config.role}
        elif isinstance(config, (GetInvitation, DeleteInvitation, AcceptInvitation)):
            path += f"/{_segment(config.invitation_id)}"
            if isinstance(config, DeleteInvitation):
                method = "DELETE"
            elif isinstance(config, AcceptInvitation):
                method = "POST"
                path += ":accept"
        elif isinstance(config, ListMaterials):
            path += "/courseWorkMaterials"
            params = _page_params(config)
        elif isinstance(config, CreateMaterial):
            path += "/courseWorkMaterials"
            method = "POST"
            body = {"title": config.title, "state": config.state,
                    **({"description": config.description} if config.description is not None else {}),
                    **({"topicId": config.topic_id} if config.topic_id else {})}
        elif isinstance(config, (GetMaterial, UpdateMaterial, DeleteMaterial)):
            path += f"/courseWorkMaterials/{_segment(config.material_id)}"
            if isinstance(config, UpdateMaterial):
                method = "PATCH"
                body, params = _patch_body({
                    "title": config.title, "description": config.description,
                    "state": config.state, "topicId": config.topic_id,
                })
            elif isinstance(config, DeleteMaterial):
                method = "DELETE"
        else:
            raise ValueError("Unsupported Google Classroom operation")
        output = await _request(token, method, path, params=params, body=body)
        await self.emit(output)
        return output
