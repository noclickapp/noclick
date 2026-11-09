"""CYPHER Learning API v3: users, classes, enrollments and collaboration groups.

Contract: https://www.neolms.com/api/v3/openapi.json (version 3.0).
Each operation makes one request; list operations return one explicit page.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


def _origin(value):
    """CYPHER supports branded portal domains, so require a public HTTPS origin."""
    if not isinstance(value, str):
        raise ValueError("Enter your CYPHER portal HTTPS origin")
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (parts.scheme != "https" or parts.username is not None or parts.password is not None
                or parts.port is not None or parts.path or parts.query or parts.fragment
                or len(host) > 253 or "." not in host or host.endswith(".")
                or all(c.isdigit() or c == "." for c in host)
                or not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.split("."))):
            raise ValueError()
    except ValueError:
        raise ValueError("Use your public HTTPS portal origin without a path, port or query") from None
    return "https://" + host.lower()


class CypherLearningAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="CYPHER Learning API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.neolms.com/api/v3/openapi.json",
            "x-credential-instructions": "Paste your portal's API key and HTTPS portal origin (for example https://school.neolms.com). The key is sent in the x-api-key header. Your key must allow the selected operations; connecting reads one page of your classes."})
    credential_type: Literal["cypher_learning_api_key"] = Field("cypher_learning_api_key", json_schema_extra={"ui:hidden": True})
    portal_url: str = Field(..., title="Portal URL", description="Your CYPHER portal HTTPS origin, including a custom domain if configured.")
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    _portal = field_validator("portal_url", mode="before")(_origin)

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def workflow_metadata(cls, value):
        # Older workflow saves carried attachment metadata inside config.
        if isinstance(value, dict) and "credentialIds" in value:
            return {key: item for key, item in value.items() if key != "credentialIds"}
        return value


ResourceID = Annotated[int, Field(gt=0, le=9223372036854775807)]


class _Page(_Input):
    limit: int = Field(10, ge=1, le=100, description="Number of records in this page; CYPHER's maximum is 100.")
    offset: int = Field(0, ge=0, le=2147483647, description="Skip this many records. Use next_offset for a possible next page.")


class ListUsersConfig(_Page):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class GetUserConfig(_Input):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: ResourceID


class CreateUserConfig(_Input):
    """Create user."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=500)
    last_name: str = Field(..., min_length=1, max_length=500)
    roles: list[str] = Field(..., min_length=1, max_length=20, description="Portal role names, for example student.")
    userid: str | None = Field(None, max_length=500, title="Login ID")
    email: str | None = Field(None, max_length=500)
    organization_id: ResourceID | None = None
    send_login_instructions: bool = Field(False, description="Send an email with login instructions to the new user.")


class UpdateUserConfig(_Input):
    """Update user."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    user_id: ResourceID
    first_name: str | None = Field(None, min_length=1, max_length=500)
    last_name: str | None = Field(None, min_length=1, max_length=500)
    email: str | None = Field(None, max_length=500)
    organization_id: ResourceID | None = None
    archived: bool | None = None
    tags: list[str] | None = None


class ListClassesConfig(_Page):
    """List classes."""
    operation: Literal["list_classes"] = Field("list_classes", json_schema_extra={"ui:hidden": True})


class GetClassConfig(_Input):
    """Get class."""
    operation: Literal["get_class"] = Field("get_class", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID


class ListClassStudentsConfig(_Page):
    """List class students."""
    operation: Literal["list_class_students"] = Field("list_class_students", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID


class GetClassStudentConfig(_Input):
    """Get class student."""
    operation: Literal["get_class_student"] = Field("get_class_student", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID
    user_id: ResourceID


class AddClassStudentConfig(_Input):
    """Enroll a student in a class, with explicit notification and re-enrollment options."""
    operation: Literal["add_class_student"] = Field("add_class_student", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID
    user_id: ResourceID
    send_notification: bool = Field(False, description="Notify the learner of enrollment.")
    reenroll: Literal["never", "only_completed", "always"] = "never"
    increment_seats: bool = Field(False, description="Add a seat when no seats remain.")


class UpdateClassStudentConfig(_Input):
    """Update enrollment status or final score; status changes run as provider background jobs."""
    operation: Literal["update_class_student"] = Field("update_class_student", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID
    user_id: ResourceID
    completed: bool | None = None
    deactivated: bool | None = None
    unenrolled: bool | None = None
    override_percent: float | None = None
    override_comment: str | None = None


class RemoveClassStudentConfig(_Input):
    """Remove class student."""
    operation: Literal["remove_class_student"] = Field("remove_class_student", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID
    user_id: ResourceID


class ListGroupsConfig(_Page):
    """List groups."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})


class GetGroupConfig(_Input):
    """Get group."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID


class CreateGroupConfig(_Input):
    """Create group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    private: bool | None = None
    team: bool | None = None
    tags: list[str] | None = None


class UpdateGroupConfig(_Input):
    """Update group."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID
    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    private: bool | None = None
    tags: list[str] | None = None


class ListGroupMembersConfig(_Page):
    """List group members."""
    operation: Literal["list_group_members"] = Field("list_group_members", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID


class AddGroupMemberConfig(_Input):
    """Add group member."""
    operation: Literal["add_group_member"] = Field("add_group_member", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID
    user_id: ResourceID


class RemoveGroupMemberConfig(_Input):
    """Remove group member."""
    operation: Literal["remove_group_member"] = Field("remove_group_member", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID
    user_id: ResourceID


class ListOrganizationsConfig(_Page):
    """List organizations."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})


class GetOrganizationConfig(_Input):
    """Get organization."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceID


class ListClassAssignmentsConfig(_Page):
    """List class assignments."""
    operation: Literal["list_class_assignments"] = Field("list_class_assignments", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID


class ListAssignmentGradesConfig(_Page):
    """List assignment grades."""
    operation: Literal["list_assignment_grades"] = Field("list_assignment_grades", json_schema_extra={"ui:hidden": True})
    class_id: ResourceID
    assignment_id: ResourceID


CypherLearningOperation = Annotated[Union[
    ListUsersConfig,
    GetUserConfig,
    CreateUserConfig,
    UpdateUserConfig,
    ListClassesConfig,
    GetClassConfig,
    ListClassStudentsConfig,
    GetClassStudentConfig,
    AddClassStudentConfig,
    UpdateClassStudentConfig,
    RemoveClassStudentConfig,
    ListGroupsConfig,
    GetGroupConfig,
    CreateGroupConfig,
    UpdateGroupConfig,
    ListGroupMembersConfig,
    AddGroupMemberConfig,
    RemoveGroupMemberConfig,
    ListOrganizationsConfig,
    GetOrganizationConfig,
    ListClassAssignmentsConfig,
    ListAssignmentGradesConfig
], Field(discriminator="operation")]


class CypherLearningConfig(NodeConfig[CypherLearningOperation, CypherLearningAPIKeyCredential]):
    pass


# Every entry maps to exactly one published API v3 operation.
ROUTES = {
    "list_users": ("GET", "/users"),
    "get_user": ("GET", "/users/{user_id}"),
    "create_user": ("POST", "/users"),
    "update_user": ("PATCH", "/users/{user_id}"),
    "list_classes": ("GET", "/classes"),
    "get_class": ("GET", "/classes/{class_id}"),
    "list_class_students": ("GET", "/classes/{class_id}/students"),
    "get_class_student": ("GET", "/classes/{class_id}/students/{user_id}"),
    "add_class_student": ("POST", "/classes/{class_id}/students"),
    "update_class_student": ("PATCH", "/classes/{class_id}/students/{user_id}"),
    "remove_class_student": ("DELETE", "/classes/{class_id}/students/{user_id}"),
    "list_groups": ("GET", "/groups"),
    "get_group": ("GET", "/groups/{group_id}"),
    "create_group": ("POST", "/groups"),
    "update_group": ("PATCH", "/groups/{group_id}"),
    "list_group_members": ("GET", "/groups/{group_id}/members"),
    "add_group_member": ("POST", "/groups/{group_id}/members"),
    "remove_group_member": ("DELETE", "/groups/{group_id}/members/{user_id}"),
    "list_organizations": ("GET", "/organizations"),
    "get_organization": ("GET", "/organizations/{organization_id}"),
    "list_class_assignments": ("GET", "/classes/{class_id}/assignments"),
    "list_assignment_grades": ("GET", "/classes/{class_id}/assignments/{assignment_id}/grades"),
}


class CypherLearningNode(WorkflowNode):
    integration_type = "automation-cypher-learning"
    connection_evidence = ConnectionEvidence(noun="classes", operation="list_classes")

    @classmethod
    def get_config_model(cls):
        return CypherLearningConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CYPHER Learning API key")
        credential = self.config.credentials
        op = self.config.config
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path_fields = set(re.findall(r"{([^}]+)}", template))
        path = template.format(**{key: values[key] for key in path_fields})
        params = {}
        body = None
        if isinstance(op, _Page):
            params = {"$limit": op.limit, "$offset": op.offset}
        elif method in {"POST", "PATCH"}:
            body = {key: value for key, value in values.items() if key not in path_fields | {"operation"}}
            options = {}
            if op.operation == "create_user":
                options = {"send_login_instructions": body.pop("send_login_instructions")}
            elif op.operation == "add_class_student":
                options = {key: body.pop(key) for key in ("send_notification", "reenroll", "increment_seats")}
            if options:
                params["$options"] = json.dumps(options, separators=(",", ":"))
            if method == "PATCH" and not body:
                raise ValueError("Supply at least one field to update")
        # Public DNS/IP pinning and redirects disabled protect keys on custom portal hosts.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, _origin(credential.portal_url) + "/api/v3" + path,
                params=params, headers={"x-api-key": credential.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        expected = 204 if method == "DELETE" else 201 if method == "POST" else 200
        if response.status_code != expected:
            message = "CYPHER Learning request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        if method == "DELETE":
            return {"status": "success", "deleted": True}
        if len(response.content) > 10_000_000:
            raise ValueError("CYPHER Learning response exceeds 10 MB")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("CYPHER Learning returned invalid JSON") from None
        if isinstance(op, _Page):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("CYPHER Learning returned an invalid list")
            # A full page may have a successor; no total count is implied.
            return {"status": "success", "data": data, "offset": op.offset,
                "next_offset": op.offset + len(data) if len(data) == op.limit else None,
                "may_have_more": len(data) == op.limit}
        if not isinstance(data, dict) or "message" in data or "error" in data:
            raise ValueError("CYPHER Learning returned an invalid resource")
        return {"status": "success", "data": data,
            **({"status_change_pending": True} if op.operation == "update_class_student"
                and any(key in values for key in ("completed", "deactivated", "unenrolled")) else {})}
