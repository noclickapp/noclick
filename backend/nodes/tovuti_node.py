"""Tovuti LMS actions and scheduled change triggers, pinned to REST API 1.66.7.

Bearer tokens are pasted by a person; connection evidence reads their courses.
Each action maps to one published endpoint; poll triggers scan stable time-ordered pages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.tovuti.io/api/v1"
CONTRACT_URL = "https://api.tovuti.io/schema.yml"


class TovutiTokenCredential(BaseModel):
    model_config = ConfigDict(title="Tovuti LMS API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": CONTRACT_URL,
            "x-credential-instructions": "Paste a Tovuti REST API bearer token with permission for the actions you use."})
    credential_type: Literal["tovuti_api_token"] = Field("tovuti_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False,
        description="Your Tovuti API token, without the Bearer prefix.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def clean_token(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 32 for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


OPERATIONS = {
    'list_users': Operation('GET', '/users', ('name', 'email', 'status', 'registeredAfter', 'timestampModifiedAfter', 'page', 'pageSize', 'sortBy', 'sortDir'), ()),
    'get_user': Operation('GET', '/user/{id}', (), ()),
    'create_user': Operation('POST', '/user', (), ('name', 'username', 'email', 'password', 'userGroupIds', 'userTeamIds', 'enrolledCourseIds', 'requireReset', 'status')),
    'update_user': Operation('PATCH', '/user/{id}', (), ('name', 'username', 'email', 'password', 'userGroupIds', 'userTeamIds', 'enrolledCourseIds', 'requireReset', 'status')),
    'delete_user': Operation('DELETE', '/user/{id}', (), ()),
    'list_courses': Operation('GET', '/courses', ('title', 'published', 'modifiedAfter', 'page', 'pageSize', 'sortBy', 'sortDir'), ()),
    'get_course': Operation('GET', '/course/{id}', (), ()),
    'list_assignments': Operation('GET', '/assignments', ('title', 'userIds', 'groupIds', 'dueBefore', 'page', 'pageSize', 'sortBy', 'sortDir'), ()),
    'get_assignment': Operation('GET', '/assignment/{id}', (), ()),
    'create_assignment': Operation('POST', '/assignment', (), ('title', 'type', 'assignment_type', 'course_ids', 'learning_path_ids', 'user_ids', 'usergroups', 'due_date', 'assignment_filter_type', 'description')),
    'update_assignment': Operation('PATCH', '/assignment/{id}', (), ('title', 'type', 'assignment_type', 'course_ids', 'learning_path_ids', 'user_ids', 'usergroups', 'due_date', 'assignment_filter_type', 'description')),
    'delete_assignment': Operation('DELETE', '/assignment/{id}', (), ()),
    'list_user_groups': Operation('GET', '/userGroups', ('title', 'userIds', 'parentId', 'page', 'pageSize', 'sortBy', 'sortDir'), ()),
    'get_user_group': Operation('GET', '/userGroup/{id}', (), ()),
    'create_user_group': Operation('POST', '/userGroup', (), ('title', 'parent_id', 'userIds')),
    'update_user_group': Operation('PATCH', '/userGroup/{id}', (), ('title', 'parent_id', 'userIds')),
    'list_course_progress': Operation('GET', '/courseProgresses', ('userId', 'courseId', 'completedAfter', 'page', 'pageSize', 'sortBy', 'sortDir'), ()),
    'get_course_progress': Operation('GET', '/courseProgress/{id}', (), ()),
    'create_course_progress': Operation('POST', '/courseProgress', (), ('user_id', 'course_id', 'language', 'progress', 'score', 'date_started', 'date_completed', 'date_due', 'lessons_completed_list')),
    'update_course_progress': Operation('PATCH', '/courseProgress/{id}', (), ('user_id', 'course_id', 'language', 'progress', 'score', 'date_started', 'date_completed', 'date_due', 'lessons_completed_list')),
    'list_learning_paths': Operation('GET', '/learningPaths', ('title', 'user', 'published', 'page', 'pageSize', 'sortBy', 'sortDir'), ()),
    'get_learning_path': Operation('GET', '/learningPath/{id}', (), ()),
}


class _Action(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def assignment_dependencies(self):
        kind = getattr(self, "assignment_type", None)
        if kind and not getattr(self, "course_ids" if kind == "courses" else "learning_path_ids", None):
            raise ValueError("Choose the courses or learning paths for this assignment")
        return self


class TovutiListUsersConfig(_Action):
    operation: Literal['list_users'] = Field('list_users', title='List Users', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Users'})
    name: str | None = Field(None, title='Name')
    email: str | None = Field(None, title='Email')
    status: Literal['active', 'disabled'] | None = Field(None, title='Status')
    registeredAfter: date | None = Field(None, title='Registered After')
    timestampModifiedAfter: str | None = Field(None, title='Modified After')
    page: int = Field(1, title='Page', ge=1)
    pageSize: Literal[10, 25, 50, 100, 250] = Field(25, title='Page Size')
    sortBy: Literal['timestampModified'] = Field('timestampModified', title='Sort By')
    sortDir: Literal['asc', 'desc'] = Field('desc', title='Sort Direction')


class TovutiGetUserConfig(_Action):
    operation: Literal['get_user'] = Field('get_user', title='Get User', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Users'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiCreateUserConfig(_Action):
    operation: Literal['create_user'] = Field('create_user', title='Create User', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Users'})
    name: str = Field(..., title='Name')
    username: str = Field(..., title='Username')
    email: str = Field(..., title='Email')
    password: str = Field(..., title='Password', repr=False, json_schema_extra={"ui:widget": "password"})
    userGroupIds: list[int] | None = Field(None, title='User Group IDs')
    userTeamIds: list[int] | None = Field(None, title='User Team IDs')
    enrolledCourseIds: list[int] | None = Field(None, title='Enrolled Course IDs')
    requireReset: bool | None = Field(None, title='Require Password Reset')
    status: Literal['active', 'disabled'] | None = Field(None, title='Status')


class TovutiUpdateUserConfig(_Action):
    operation: Literal['update_user'] = Field('update_user', title='Update User', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Users'})
    resource_id: int = Field(..., title='Resource Id', ge=1)
    name: str | None = Field(None, title='Name')
    username: str | None = Field(None, title='Username')
    email: str | None = Field(None, title='Email')
    password: str | None = Field(None, title='Password', repr=False, json_schema_extra={"ui:widget": "password"})
    userGroupIds: list[int] | None = Field(None, title='User Group IDs')
    userTeamIds: list[int] | None = Field(None, title='User Team IDs')
    enrolledCourseIds: list[int] | None = Field(None, title='Enrolled Course IDs')
    requireReset: bool | None = Field(None, title='Require Password Reset')
    status: Literal['active', 'disabled'] | None = Field(None, title='Status')


class TovutiDeleteUserConfig(_Action):
    operation: Literal['delete_user'] = Field('delete_user', title='Delete User', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Users'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiListCoursesConfig(_Action):
    operation: Literal['list_courses'] = Field('list_courses', title='List Courses', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Courses'})
    title: str | None = Field(None, title='Title')
    published: bool | None = Field(None, title='Published')
    modifiedAfter: date | None = Field(None, title='Modified After')
    page: int = Field(1, title='Page', ge=1)
    pageSize: Literal[10, 25, 50, 100, 250] = Field(25, title='Page Size')
    sortBy: Literal['timestampModified'] = Field('timestampModified', title='Sort By')
    sortDir: Literal['asc', 'desc'] = Field('desc', title='Sort Direction')


class TovutiGetCourseConfig(_Action):
    operation: Literal['get_course'] = Field('get_course', title='Get Course', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Courses'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiListAssignmentsConfig(_Action):
    operation: Literal['list_assignments'] = Field('list_assignments', title='List Assignments', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Assignments'})
    title: str | None = Field(None, title='Title')
    userIds: str | None = Field(None, title='User IDs')
    groupIds: str | None = Field(None, title='Group IDs')
    dueBefore: date | None = Field(None, title='Due Before')
    page: int = Field(1, title='Page', ge=1)
    pageSize: Literal[10, 25, 50, 100, 250] = Field(25, title='Page Size')
    sortBy: Literal['timestampModified'] = Field('timestampModified', title='Sort By')
    sortDir: Literal['asc', 'desc'] = Field('desc', title='Sort Direction')


class TovutiGetAssignmentConfig(_Action):
    operation: Literal['get_assignment'] = Field('get_assignment', title='Get Assignment', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Assignments'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiCreateAssignmentConfig(_Action):
    operation: Literal['create_assignment'] = Field('create_assignment', title='Create Assignment', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Assignments'})
    title: str = Field(..., title='Title')
    type: Literal['Assigned', 'Recommended', 'assigned', 'recommended'] | None = Field(None, title='Type')
    assignment_type: Literal['courses', 'learningpaths'] | None = Field(None, title='Assignment Type')
    course_ids: list[int] | None = Field(None, title='Course Ids')
    learning_path_ids: list[int] | None = Field(None, title='Learning Path Ids')
    user_ids: list[int] | None = Field(None, title='User Ids')
    usergroups: list[int] | None = Field(None, title='Usergroups')
    due_date: date | None = Field(None, title='Due Date')
    assignment_filter_type: Literal['users', 'groups'] | None = Field(None, title='Assignment Filter Type')
    description: str | None = Field(None, title='Description', max_length=50)


class TovutiUpdateAssignmentConfig(_Action):
    operation: Literal['update_assignment'] = Field('update_assignment', title='Update Assignment', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Assignments'})
    resource_id: int = Field(..., title='Resource Id', ge=1)
    title: str | None = Field(None, title='Title')
    type: Literal['Assigned', 'Recommended', 'assigned', 'recommended'] | None = Field(None, title='Type')
    assignment_type: Literal['courses', 'learningpaths'] | None = Field(None, title='Assignment Type')
    course_ids: list[int] | None = Field(None, title='Course Ids')
    learning_path_ids: list[int] | None = Field(None, title='Learning Path Ids')
    user_ids: list[int] | None = Field(None, title='User Ids')
    usergroups: list[int] | None = Field(None, title='Usergroups')
    due_date: date | None = Field(None, title='Due Date')
    assignment_filter_type: Literal['users', 'groups'] | None = Field(None, title='Assignment Filter Type')
    description: str | None = Field(None, title='Description', max_length=50)


class TovutiDeleteAssignmentConfig(_Action):
    operation: Literal['delete_assignment'] = Field('delete_assignment', title='Delete Assignment', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Assignments'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiListUserGroupsConfig(_Action):
    operation: Literal['list_user_groups'] = Field('list_user_groups', title='List User Groups', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'User Groups'})
    title: str | None = Field(None, title='Title')
    userIds: str | None = Field(None, title='User IDs')
    parentId: int | None = Field(None, title='Parent ID')
    page: int = Field(1, title='Page', ge=1)
    pageSize: Literal[10, 25, 50, 100, 250] = Field(25, title='Page Size')
    sortBy: Literal['timestampModified'] = Field('timestampModified', title='Sort By')
    sortDir: Literal['asc', 'desc'] = Field('desc', title='Sort Direction')


class TovutiGetUserGroupConfig(_Action):
    operation: Literal['get_user_group'] = Field('get_user_group', title='Get User Group', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'User Groups'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiCreateUserGroupConfig(_Action):
    operation: Literal['create_user_group'] = Field('create_user_group', title='Create User Group', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'User Groups'})
    title: str = Field(..., title='Title')
    parent_id: int = Field(..., title='Parent Id')
    userIds: list[int] | None = Field(None, title='User IDs')


class TovutiUpdateUserGroupConfig(_Action):
    operation: Literal['update_user_group'] = Field('update_user_group', title='Update User Group', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'User Groups'})
    resource_id: int = Field(..., title='Resource Id', ge=1)
    title: str | None = Field(None, title='Title')
    parent_id: int | None = Field(None, title='Parent Id')
    userIds: list[int] | None = Field(None, title='User IDs')


class TovutiListCourseProgressConfig(_Action):
    operation: Literal['list_course_progress'] = Field('list_course_progress', title='List Course Progress', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Course Progress'})
    userId: int | None = Field(None, title='User ID')
    courseId: int | None = Field(None, title='Course ID')
    completedAfter: str | None = Field(None, title='Completed After')
    page: int = Field(1, title='Page', ge=1)
    pageSize: Literal[10, 25, 50, 100, 250] = Field(25, title='Page Size')
    sortBy: Literal['timestampModified'] = Field('timestampModified', title='Sort By')
    sortDir: Literal['asc', 'desc'] = Field('desc', title='Sort Direction')


class TovutiGetCourseProgressConfig(_Action):
    operation: Literal['get_course_progress'] = Field('get_course_progress', title='Get Course Progress', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Course Progress'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiCreateCourseProgressConfig(_Action):
    operation: Literal['create_course_progress'] = Field('create_course_progress', title='Create Course Progress', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Course Progress'})
    user_id: int = Field(..., title='User Id')
    course_id: int = Field(..., title='Course Id')
    language: str = Field(..., title='Language')
    progress: float | None = Field(None, title='Progress')
    score: float | None = Field(None, title='Score')
    date_started: date | None = Field(None, title='Date Started')
    date_completed: date | None = Field(None, title='Date Completed')
    date_due: date | None = Field(None, title='Date Due')
    lessons_completed_list: list[int] | None = Field(None, title='Lessons Completed List')


class TovutiUpdateCourseProgressConfig(_Action):
    operation: Literal['update_course_progress'] = Field('update_course_progress', title='Update Course Progress', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Course Progress'})
    resource_id: int = Field(..., title='Resource Id', ge=1)
    user_id: int | None = Field(None, title='User Id')
    course_id: int | None = Field(None, title='Course Id')
    language: str | None = Field(None, title='Language')
    progress: float | None = Field(None, title='Progress')
    score: float | None = Field(None, title='Score')
    date_started: date | None = Field(None, title='Date Started')
    date_completed: date | None = Field(None, title='Date Completed')
    date_due: date | None = Field(None, title='Date Due')
    lessons_completed_list: list[int] | None = Field(None, title='Lessons Completed List')


class TovutiListLearningPathsConfig(_Action):
    operation: Literal['list_learning_paths'] = Field('list_learning_paths', title='List Learning Paths', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Learning Paths'})
    title: str | None = Field(None, title='Title')
    user: int | None = Field(None, title='User')
    published: bool | None = Field(None, title='Published')
    page: int = Field(1, title='Page', ge=1)
    pageSize: Literal[10, 25, 50, 100, 250] = Field(25, title='Page Size')
    sortBy: Literal['timestampModified'] = Field('timestampModified', title='Sort By')
    sortDir: Literal['asc', 'desc'] = Field('desc', title='Sort Direction')


class TovutiGetLearningPathConfig(_Action):
    operation: Literal['get_learning_path'] = Field('get_learning_path', title='Get Learning Path', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Learning Paths'})
    resource_id: int = Field(..., title='Resource Id', ge=1)


class TovutiOnUpdatedUserConfig(PollTriggerConfigBase):
    operation: Literal['on_updated_user'] = Field('on_updated_user', title='New or Updated User', json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": 'New or Updated User'})


class TovutiOnUpdatedCourseConfig(PollTriggerConfigBase):
    operation: Literal['on_updated_course'] = Field('on_updated_course', title='New or Updated Course', json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": 'New or Updated Course'})


class TovutiOnUpdatedCourseProgressConfig(PollTriggerConfigBase):
    operation: Literal['on_updated_course_progress'] = Field('on_updated_course_progress', title='New or Updated Course Progress', json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": 'New or Updated Course Progress'})
    userId: int | None = Field(None, title='User ID', ge=1)
    courseId: int | None = Field(None, title='Course ID', ge=1)


TovutiConfig = Annotated[Union[TovutiListUsersConfig, TovutiGetUserConfig, TovutiCreateUserConfig, TovutiUpdateUserConfig, TovutiDeleteUserConfig, TovutiListCoursesConfig, TovutiGetCourseConfig, TovutiListAssignmentsConfig, TovutiGetAssignmentConfig, TovutiCreateAssignmentConfig, TovutiUpdateAssignmentConfig, TovutiDeleteAssignmentConfig, TovutiListUserGroupsConfig, TovutiGetUserGroupConfig, TovutiCreateUserGroupConfig, TovutiUpdateUserGroupConfig, TovutiListCourseProgressConfig, TovutiGetCourseProgressConfig, TovutiCreateCourseProgressConfig, TovutiUpdateCourseProgressConfig, TovutiListLearningPathsConfig, TovutiGetLearningPathConfig, TovutiOnUpdatedUserConfig, TovutiOnUpdatedCourseConfig, TovutiOnUpdatedCourseProgressConfig], Field(discriminator="operation")]


class TovutiFullConfig(NodeConfig[TovutiConfig, TovutiTokenCredential]):
    pass


TRIGGERS = {
    "on_updated_user": "/users",
    "on_updated_course": "/courses",
    "on_updated_course_progress": "/courseProgresses",
}


class TovutiNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-tovuti"
    connection_evidence = ConnectionEvidence(operation="list_courses", noun="courses")

    @classmethod
    def get_config_model(cls):
        return TovutiFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Tovuti LMS API token")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                json=body, headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Tovuti returned an unexpected JSON response")
        return data

    async def _poll(self, config):
        path = TRIGGERS[config.operation]
        params = {"pageSize": 250, "sortBy": "timestampModified", "sortDir": "asc"}
        params.update(config.model_dump(mode="json", include={"userId", "courseId"}, exclude_none=True))
        items = []
        # Rebuild page numbers against the fixed API origin, never follow a response URL.
        # Refuse a truncated scan without advancing the seen-set.
        for page in range(1, 41):
            data = await self._request("GET", path, params={**params, "page": page})
            rows = data.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Tovuti returned an invalid list response")
            items.extend(rows)
            if len(rows) < params["pageSize"] or not data.get("next_page_url"):
                break
        else:
            raise ValueError("Tovuti poll exceeds 10,000 records; narrow the watched scope")
        fresh = await self._filter_unseen(items, lambda row: str(row["id"]) + ":" + str(row.get("timestamp_modified")) if row.get("id") is not None else None)
        return {"operation": config.operation, "items": fresh, "event_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in TRIGGERS:
            return super().resolve_agent_event(output)
        items = output.get("items", [])
        if not items:
            return None
        kind = output["operation"]
        lines = []
        for row in items[:20]:
            if kind == "on_updated_user":
                lines.append(f"Learner {row.get('name') or row.get('username') or row.get('id')} ({row.get('email') or 'no email'}), user ID {row.get('id')}, status {row.get('status')}")
            elif kind == "on_updated_course":
                lines.append(f"Course {row.get('title') or row.get('id')}, course ID {row.get('id')}")
            else:
                lines.append(f"Learner {row.get('user_name') or row.get('user_id')} (user ID {row.get('user_id')}), course {row.get('course_title') or row.get('course_id')} (course ID {row.get('course_id')}), progress {row.get('progress')}, status {row.get('status')}, progress ID {row.get('id')}")
        return {"text": f"Tovuti LMS: {len(items)} new or updated record(s) in your LMS:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self.config.config
        if config.operation in TRIGGERS:
            return await self._poll(config)
        op = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = op.path.replace("{id}", str(values.pop("resource_id", "")))
        params = {key: values[key] for key in op.query if key in values}
        body = {key: values[key] for key in op.body if key in values} if op.body else None
        return await self._request(op.method, path, params=params or None, body=body)
