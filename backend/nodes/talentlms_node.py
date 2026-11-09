"""TalentLMS Public API v2 operations (published OpenAPI version 1.0.0).

Each operation sends exactly one documented request. Lists expose one page;
mutations return the provider acknowledgement and are never retried.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class TalentLMSAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="TalentLMS API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.talentlms.com/hc/en-us/articles/9651527213468-Can-I-integrate-my-site-with-TalentLMS-Do-you-offer-an-API",
            "x-credential-instructions": "In TalentLMS, open Account & Settings > Integrations > API. Enable API access and paste your API key. Enter your TalentLMS portal subdomain or its HTTPS address, such as https://example.talentlms.com. The key inherits the API user's permissions; writes require permission to change the selected resources."
        })
    credential_type: Literal["talentlms_api_key"] = Field("talentlms_api_key", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., title="Portal address", description="Your portal subdomain or https://example.talentlms.com.")
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("domain", mode="before")
    @classmethod
    def portal(cls, value):
        return normalize_provider_https_origin(value, "talentlms.com", field_name="Portal address")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("password", check_fields=False)
    @classmethod
    def password_strength(cls, value):
        if value is not None and (len(value) < 8 or not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"[0-9]", value)):
            raise ValueError("Use at least eight characters with uppercase, lowercase and a digit")
        return value

    @model_validator(mode="after")
    def required_changes(self):
        if self.operation == "update_user" and not self.model_dump(exclude_none=True, exclude={"operation", "user_id"}):
            raise ValueError("Provide at least one user field to update")
        if self.operation == "enroll_user" and self.user_id is None and self.user_email is None:
            raise ValueError("Provide a user ID or user email")
        return self


class ListUsersConfig(Input):
    """Get users."""
    operation: Literal['list_users'] = Field('list_users', json_schema_extra={"ui:hidden": True})
    status_eq: Literal['active', 'inactive'] | None = Field(None, description='Filter by user status')
    login_eq: str | None = Field(None, description='Filter by exact login match')
    email_eq: str | None = Field(None, description='Filter by exact email match')
    keyword_like: str | None = Field(None, description='Search across name, surname, login, and email')
    last_updated_gte: datetime | None = Field(None, description='Filter users updated on or after this date (ISO 8601)')
    last_updated_lte: datetime | None = Field(None, description='Filter users updated on or before this date (ISO 8601)')
    branch_id_eq: int | None = Field(None, strict=True, description='Filter users belonging to a specific branch')
    group_id_eq: int | None = Field(None, strict=True, description='Filter users belonging to a specific group')
    integration_eq: str | None = Field(None, description='Filter users linked to a specific integration')
    custom_field_value_eq: str | None = Field(None, description='Filter users by a custom field value')
    page_number: int | None = Field(None, strict=True, ge=1, description='Page number (1-based)')
    page_size: int | None = Field(None, strict=True, ge=1, le=100, description='Page size (maximum 100)')
    sort: str | None = Field(None, description='Sort field. Allowed: name, surname, login, email, type, registration, last_login, status, last_updated. Prefix with - for descending.')

class GetUserConfig(Input):
    """Get a user."""
    operation: Literal['get_user'] = Field('get_user', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user')
    resources: str | None = Field(None, pattern=r"^(all|branches|groups|courses|certificates)(,(branches|groups|courses|certificates))*$", description='Optional related resources to include in the response. Accepts a single value or a comma-separated list. Allowed values: branches, groups, courses, certificates, all (expands to all four).')

class CreateUserConfig(Input):
    """Create a user."""
    operation: Literal['create_user'] = Field('create_user', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    surname: str = Field(..., min_length=1)
    login: str = Field(..., min_length=1, description='Must be unique')
    email: EmailStr = Field(..., description='Must be unique')
    password: str = Field(..., min_length=8, description='At least 8 characters with upper, lower, and digit', json_schema_extra={"ui:widget": "password"})
    status: Literal['active', 'inactive'] | None = Field(None)
    user_type_id: int | None = Field(None, strict=True, ge=1)
    email_notifications: StrictBool | None = Field(None)
    timezone: str | None = Field(None)
    locale: str | None = Field(None)
    description: str | None = Field(None)
    credits: float | None = Field(None, ge=0)
    deactivation_date: date | None = Field(None)
    branch_id: int | None = Field(None, strict=True, ge=1, description='Optional branch to assign after create')

class UpdateUserConfig(Input):
    """Update a user."""
    operation: Literal['update_user'] = Field('update_user', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user')
    name: str | None = Field(None, max_length=191)
    surname: str | None = Field(None, max_length=191)
    login: str | None = Field(None, max_length=191, description='Must be unique')
    email: EmailStr | None = Field(None, max_length=191, description='Must be unique')
    password: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    description: str | None = Field(None)
    timezone: str | None = Field(None, description='A supported timezone name')
    locale: str | None = Field(None)
    email_notifications: StrictBool | None = Field(None)
    user_type_id: int | None = Field(None, strict=True, ge=1)
    status: Literal['active', 'inactive'] | None = Field(None, description='Omit to keep the current status')
    deactivation_date: str | None = Field(None, pattern='^([0-9]{4}-[0-9]{2}-[0-9]{2})?$', description='Format YYYY-MM-DD. Cannot be in the past. Send an empty string to clear it')
    credits: float | None = Field(None, ge=0)

class DeleteUserConfig(Input):
    """Delete a user."""
    operation: Literal['delete_user'] = Field('delete_user', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user')
    permanent: StrictBool | None = Field(None, description='Whether to permanently delete the user instead of archiving them')

class ListCoursesConfig(Input):
    """List all courses."""
    operation: Literal['list_courses'] = Field('list_courses', json_schema_extra={"ui:hidden": True})
    page_number: int | None = Field(None, strict=True, ge=1, description='The page number')
    page_size: int | None = Field(None, strict=True, ge=1, le=100, description='The page size')
    sort: str | None = Field(None, description='Comma-separated list of fields to sort by. Prefix a field with `-` for descending order. Allowed fields: `code`, `name`, `category`, `price`, `last_updated_on`.')
    keyword_like: str | None = Field(None, description='Search across course name, category name, code, description, and price')
    name_like: str | None = Field(None, description='Search by course name')
    code_like: str | None = Field(None, description='Search by course code')
    category_like: str | None = Field(None, description='Search by category name')
    description_like: str | None = Field(None, description='Search by course description')
    status_eq: Literal['active', 'inactive'] | None = Field(None, description='Filter by course status')
    branch_id_eq: int | None = Field(None, strict=True, ge=1, description='Filter courses that belong to a specific branch')
    group_id_eq: int | None = Field(None, strict=True, ge=1, description='Filter courses that belong to a specific group')
    custom_field_value_eq: str | None = Field(None, description='Filter courses that have a custom field with this exact value')

class GetCourseConfig(Input):
    """Get a course."""
    operation: Literal['get_course'] = Field('get_course', json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., strict=True, ge=1, description='The ID of the course')

class CreateCourseConfig(Input):
    """Create course."""
    operation: Literal['create_course'] = Field('create_course', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    code: str | None = Field(None)
    description: str | None = Field(None)
    category_id: int | None = Field(None, strict=True, ge=1)
    price: float | None = Field(None, ge=0)
    capacity: int | None = Field(None, strict=True, ge=1)
    level: int | None = Field(None, strict=True, ge=1)
    time_limit: int | None = Field(None, strict=True, ge=1)
    start_datetime: int | None = Field(None, strict=True, description='Unix timestamp; must be in the future')
    expiration_datetime: int | None = Field(None, strict=True, description='Unix timestamp; must be after start_datetime when both set')
    is_active: StrictBool | None = Field(None)

class DeleteCourseConfig(Input):
    """Delete a course."""
    operation: Literal['delete_course'] = Field('delete_course', json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., strict=True, ge=1, description='The ID of the course')

class EnrollUserConfig(Input):
    """Enroll user to course."""
    operation: Literal['enroll_user'] = Field('enroll_user', json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., strict=True, ge=1, description='The ID of the course')
    user_id: int | None = Field(None, strict=True, ge=1, description='The ID of the user. Required unless `user_email` is provided. Takes precedence over `user_email`. A `null` value is treated as not provided.')
    user_email: EmailStr | None = Field(None, description='The email address of the user. Required unless `user_id` is provided. Ignored when `user_id` is provided.')
    role: Literal['learner', 'instructor'] | None = Field(None, description='The course role to enroll the user with. Optional. When omitted or null, the default role of the user type is used.')

class UnenrollUserConfig(Input):
    """Delete a user from a course."""
    operation: Literal['unenroll_user'] = Field('unenroll_user', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user to unenroll')
    course_id: int = Field(..., strict=True, ge=1, description='The ID of the course')

class GetCourseProgressConfig(Input):
    """Get user's course progress."""
    operation: Literal['get_course_progress'] = Field('get_course_progress', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1)
    course_id: int = Field(..., strict=True, ge=1)

class ResetCourseProgressConfig(Input):
    """Reset user's course progress."""
    operation: Literal['reset_course_progress'] = Field('reset_course_progress', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user')
    course_id: int = Field(..., strict=True, ge=1, description='The ID of the course')
    remove_certificate: StrictBool | None = Field(None, description='Whether to also remove the course certificate')

class ListGroupsConfig(Input):
    """List all groups."""
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={"ui:hidden": True})

class GetGroupConfig(Input):
    """Get a group."""
    operation: Literal['get_group'] = Field('get_group', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., strict=True, ge=1, description='The ID of the group')

class CreateGroupConfig(Input):
    """Create a group."""
    operation: Literal['create_group'] = Field('create_group', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=79)
    description: str | None = Field(None, max_length=500)
    key: str | None = Field(None, min_length=6, max_length=20)
    max_key_redemptions: int | None = Field(None, strict=True, ge=1)
    price: float | None = Field(None, gt=0)
    auto_sync: StrictBool | None = Field(None)

class DeleteGroupConfig(Input):
    """Delete a group."""
    operation: Literal['delete_group'] = Field('delete_group', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., strict=True, ge=1, description='The ID of the group')

class AddGroupMemberConfig(Input):
    """Add a user to a group."""
    operation: Literal['add_group_member'] = Field('add_group_member', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., strict=True, ge=1)
    user_id: int = Field(..., strict=True, ge=1)
    enroll_to_courses: StrictBool | None = Field(None, description="Whether to force synchronous enrollment in the group's active courses")

class RemoveGroupMemberConfig(Input):
    """Remove user from a group."""
    operation: Literal['remove_group_member'] = Field('remove_group_member', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user to remove')
    group_id: int = Field(..., strict=True, ge=1, description='The ID of the group')

class ListBranchesConfig(Input):
    """List all branches."""
    operation: Literal['list_branches'] = Field('list_branches', json_schema_extra={"ui:hidden": True})

class GetBranchConfig(Input):
    """Get a branch."""
    operation: Literal['get_branch'] = Field('get_branch', json_schema_extra={"ui:hidden": True})
    branch_id: int = Field(..., strict=True, ge=1, description='The ID of the branch')

class ListCategoriesConfig(Input):
    """List all categories."""
    operation: Literal['list_categories'] = Field('list_categories', json_schema_extra={"ui:hidden": True})

class GetCategoryConfig(Input):
    """Get a category."""
    operation: Literal['get_category'] = Field('get_category', json_schema_extra={"ui:hidden": True})
    category_id: int = Field(..., strict=True, ge=1, description='The ID of the category')

class ListCourseUsersConfig(Input):
    """Get course users."""
    operation: Literal['list_course_users'] = Field('list_course_users', json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., strict=True, ge=1, description='The ID of the course')

class ListUserCoursesConfig(Input):
    """Get user courses."""
    operation: Literal['list_user_courses'] = Field('list_user_courses', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., strict=True, ge=1, description='The ID of the user')


TalentLMSConfig = Annotated[Union[
    ListUsersConfig,
    GetUserConfig,
    CreateUserConfig,
    UpdateUserConfig,
    DeleteUserConfig,
    ListCoursesConfig,
    GetCourseConfig,
    CreateCourseConfig,
    DeleteCourseConfig,
    EnrollUserConfig,
    UnenrollUserConfig,
    GetCourseProgressConfig,
    ResetCourseProgressConfig,
    ListGroupsConfig,
    GetGroupConfig,
    CreateGroupConfig,
    DeleteGroupConfig,
    AddGroupMemberConfig,
    RemoveGroupMemberConfig,
    ListBranchesConfig,
    GetBranchConfig,
    ListCategoriesConfig,
    GetCategoryConfig,
    ListCourseUsersConfig,
    ListUserCoursesConfig
], Field(discriminator="operation")]


class TalentLMSFullConfig(NodeConfig[TalentLMSConfig, TalentLMSAPIKeyCredential]):
    pass


# Method, path, query field mapping, JSON body fields, successful status codes.
OPERATIONS = {'list_users': ('GET',
                '/api/v2/users',
                {'status_eq': 'filter[status][eq]',
                 'login_eq': 'filter[login][eq]',
                 'email_eq': 'filter[email][eq]',
                 'keyword_like': 'filter[keyword][like]',
                 'last_updated_gte': 'filter[last_updated][gte]',
                 'last_updated_lte': 'filter[last_updated][lte]',
                 'branch_id_eq': 'filter[branch_id][eq]',
                 'group_id_eq': 'filter[group_id][eq]',
                 'integration_eq': 'filter[integration][eq]',
                 'custom_field_value_eq': 'filter[custom_field_value][eq]',
                 'page_number': 'page[number]',
                 'page_size': 'page[size]',
                 'sort': 'sort'},
                [],
                (200,)),
 'get_user': ('GET', '/api/v2/users/{user_id}', {'resources': 'resources'}, [], (200,)),
 'create_user': ('POST',
                 '/api/v2/users',
                 {},
                 ['name',
                  'surname',
                  'login',
                  'email',
                  'password',
                  'status',
                  'user_type_id',
                  'email_notifications',
                  'timezone',
                  'locale',
                  'description',
                  'credits',
                  'deactivation_date',
                  'branch_id'],
                 (200,)),
 'update_user': ('PATCH',
                 '/api/v2/users/{user_id}',
                 {},
                 ['name',
                  'surname',
                  'login',
                  'email',
                  'password',
                  'description',
                  'timezone',
                  'locale',
                  'email_notifications',
                  'user_type_id',
                  'status',
                  'deactivation_date',
                  'credits'],
                 (204,)),
 'delete_user': ('DELETE', '/api/v2/users/{user_id}', {'permanent': 'permanent'}, [], (204,)),
 'list_courses': ('GET',
                  '/api/v2/courses',
                  {'page_number': 'page[number]',
                   'page_size': 'page[size]',
                   'sort': 'sort',
                   'keyword_like': 'filter[keyword][like]',
                   'name_like': 'filter[name][like]',
                   'code_like': 'filter[code][like]',
                   'category_like': 'filter[category][like]',
                   'description_like': 'filter[description][like]',
                   'status_eq': 'filter[status][eq]',
                   'branch_id_eq': 'filter[branch_id][eq]',
                   'group_id_eq': 'filter[group_id][eq]',
                   'custom_field_value_eq': 'filter[custom_field_value][eq]'},
                  [],
                  (200,)),
 'get_course': ('GET', '/api/v2/courses/{course_id}', {}, [], (200,)),
 'create_course': ('POST',
                   '/api/v2/courses',
                   {},
                   ['name',
                    'code',
                    'description',
                    'category_id',
                    'price',
                    'capacity',
                    'level',
                    'time_limit',
                    'start_datetime',
                    'expiration_datetime',
                    'is_active'],
                   (200,)),
 'delete_course': ('DELETE', '/api/v2/courses/{course_id}', {}, [], (204,)),
 'enroll_user': ('POST', '/api/v2/enrollments', {}, ['course_id', 'user_id', 'user_email', 'role'], (200,)),
 'unenroll_user': ('DELETE', '/api/v2/enrollments', {}, ['user_id', 'course_id'], (204,)),
 'get_course_progress': ('GET',
                         '/api/v2/course-progress',
                         {'user_id': 'user_id', 'course_id': 'course_id'},
                         [],
                         (200,)),
 'reset_course_progress': ('DELETE',
                           '/api/v2/course-progress',
                           {'user_id': 'user_id',
                            'course_id': 'course_id',
                            'remove_certificate': 'remove-certificate'},
                           [],
                           (204,)),
 'list_groups': ('GET', '/api/v2/groups', {}, [], (200,)),
 'get_group': ('GET', '/api/v2/groups/{group_id}', {}, [], (200,)),
 'create_group': ('POST',
                  '/api/v2/groups',
                  {},
                  ['name', 'description', 'key', 'max_key_redemptions', 'price', 'auto_sync'],
                  (200,)),
 'delete_group': ('DELETE', '/api/v2/groups/{group_id}', {}, [], (204,)),
 'add_group_member': ('POST',
                      '/api/v2/group-memberships',
                      {},
                      ['group_id', 'user_id', 'enroll_to_courses'],
                      (204,)),
 'remove_group_member': ('DELETE', '/api/v2/group-memberships', {}, ['user_id', 'group_id'], (204,)),
 'list_branches': ('GET', '/api/v2/branches', {}, [], (200,)),
 'get_branch': ('GET', '/api/v2/branches/{branch_id}', {}, [], (200,)),
 'list_categories': ('GET', '/api/v2/categories', {}, [], (200,)),
 'get_category': ('GET', '/api/v2/categories/{category_id}', {}, [], (200,)),
 'list_course_users': ('GET', '/api/v2/courses/{course_id}/users', {}, [], (200,)),
 'list_user_courses': ('GET', '/api/v2/users/{user_id}/courses', {}, [], (200,))}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class TalentLMSNode(WorkflowNode):
    integration_type = "automation-talentlms"
    connection_evidence = ConnectionEvidence(operation="list_users", noun="TalentLMS users")

    @classmethod
    def get_config_model(cls):
        return TalentLMSFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, TalentLMSFullConfig) or not self.config.credentials:
            raise ValueError("Connect a TalentLMS API key")
        credential = self.config.credentials
        config = self.config.config
        method, path, query_fields, body_fields, statuses = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + field + "}", str(values.pop(field)))
        params = {wire: str(values[name]).lower() if isinstance(values[name], bool) else values[name]
            for name, wire in query_fields.items() if name in values}
        body = {name: values[name] for name in body_fields if name in values} if body_fields else None
        secrets = [credential.api_key]
        if values.get("password"):
            secrets.append(values["password"])
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, credential.domain + path, params=params, json=body,
                    headers={"X-API-Key": credential.api_key, "Accept": "application/json"})
        except (httpx.HTTPError, OSError):
            raise ValueError("TalentLMS request did not complete; inspect the resource before retrying a write") from None
        if response.status_code not in statuses:
            message = "TalentLMS rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("error", error)
                    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                        message = detail["message"][:2000]
            except ValueError:
                pass
            return {"status": "error", "success": False, "error": _redact(message, secrets),
                "http_status": response.status_code}
        result = {"status": "success", "success": True, "operation": config.operation,
            "http_status": response.status_code}
        if response.status_code == 204:
            result["acknowledged"] = True
        else:
            if len(response.content) > 10_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Expected bounded TalentLMS JSON")
            payload = response.json()
            if not isinstance(payload, dict) or "error" in payload or "_data" not in payload:
                raise ValueError("Invalid TalentLMS response envelope")
            data = payload["_data"]
            if config.operation == "list_user_courses":
                if not isinstance(data, dict) or not isinstance(data.get("courses"), list):
                    raise ValueError("Invalid TalentLMS user courses envelope")
                data = data["courses"]
            if config.operation.startswith("list_"):
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Invalid TalentLMS list")
            elif not isinstance(data, dict):
                raise ValueError("Invalid TalentLMS resource")
            result["data"] = _redact(data, secrets)
            if "_meta" in payload:
                result["pagination"] = _redact(payload["_meta"], secrets)
            if "_links" in payload:
                # Return pagination links as metadata; never fetch a response-supplied URL.
                result["links"] = _redact(payload["_links"], secrets)
        await self.emit(result)
        return result
