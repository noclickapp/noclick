"""Blackboard Learn REST operations, pinned to the public 4001.4.0 contract.

Use an existing, site-bound bearer token. Tokens normally expire after one hour;
this manual credential deliberately does not create or renew an application token.
Each operation makes exactly one request. List operations return one offset page.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

TYPE = "blackboard_access_token"
DOCS = "https://docs.blackboard.com/docs/blackboard/rest-apis/getting-started/basic-authentication"
V1 = "/learn/api/public/v1"
V3 = "/learn/api/public/v3"
OPERATIONS = {
    "list_users": ("GET", V1 + "/users", 200),
    "get_user": ("GET", V1 + "/users/{user_id}", 200),
    "list_courses": ("GET", V3 + "/courses", 200),
    "get_course": ("GET", V3 + "/courses/{course_id}", 200),
    "create_course": ("POST", V3 + "/courses", 201),
    "update_course": ("PATCH", V3 + "/courses/{course_id}", 200),
    "list_memberships": ("GET", V1 + "/courses/{course_id}/users", 200),
    "get_membership": ("GET", V1 + "/courses/{course_id}/users/{user_id}", 200),
    "create_membership": ("PUT", V1 + "/courses/{course_id}/users/{user_id}", 201),
    "update_membership": ("PATCH", V1 + "/courses/{course_id}/users/{user_id}", 200),
    "delete_membership": ("DELETE", V1 + "/courses/{course_id}/users/{user_id}", 204),
    "list_announcements": ("GET", V1 + "/courses/{course_id}/announcements", 200),
    "get_announcement": ("GET", V1 + "/courses/{course_id}/announcements/{announcement_id}", 200),
    "create_announcement": ("POST", V1 + "/courses/{course_id}/announcements", 201),
    "update_announcement": ("PATCH", V1 + "/courses/{course_id}/announcements/{announcement_id}", 200),
    "delete_announcement": ("DELETE", V1 + "/courses/{course_id}/announcements/{announcement_id}", 204),
}


class BlackboardAccessTokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Blackboard Access Token",
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Paste your Blackboard Learn HTTPS site URL and an existing bearer access token for that site, without the Bearer prefix. Ask your Blackboard administrator for a token from an already registered REST integration with the permissions your operations need. Blackboard tokens expire after one hour; replace an expired token here. NoClick does not create or refresh tokens. Connection testing lists courses and does not verify all write permissions."})
    credential_type: Literal["blackboard_access_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    site_url: str = Field(..., title="Blackboard site URL", description="Your institution's public HTTPS Blackboard Learn origin, for example https://school.blackboard.com.")
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("site_url", mode="before")
    @classmethod
    def site(cls, value):
        if not isinstance(value, str) or not value.isascii() or len(value) > 512 or any(c.isspace() for c in value):
            raise ValueError("Use your public HTTPS Blackboard site origin")
        try:
            p = urlsplit(value)
            host = p.hostname
            if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in {None, 443} or p.path not in {"", "/"} or p.query or p.fragment:
                raise ValueError()
            if not host or host.endswith(".") or any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.split(".")):
                raise ValueError()
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError()
        except ValueError:
            raise ValueError("Use a public HTTPS Blackboard hostname without a path, query, credentials or custom port") from None
        return "https://" + host.lower()

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Paste the bearer token without a prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("course_id", "user_id", "announcement_id", mode="before", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or value in {".", ".."} or any(ord(c) < 33 or ord(c) == 127 or c in "/\\?#%" for c in value):
            raise ValueError("Use a Blackboard ID or documented prefixed ID as one path segment")
        return value


class _Page(_Input):
    limit: int = Field(100, ge=1, le=200, description="Maximum rows in this single page.")
    offset: int = Field(0, ge=0, le=2147483647, description="Rows to skip. Use the offset in the returned paging.nextPage for another page; NoClick never follows that URL.")


class ListUsers(_Page):
    operation: Literal["list_users"] = "list_users"
    user_name: str | None = Field(None, max_length=256, description="Exact Blackboard userName filter.")


class GetUser(_Input):
    operation: Literal["get_user"] = "get_user"
    user_id: str


class ListCourses(_Page):
    operation: Literal["list_courses"] = "list_courses"
    name: str | None = Field(None, max_length=333)
    course_code: str | None = Field(None, max_length=100, description="Blackboard's courseId query filter.")


class GetCourse(_Input):
    operation: Literal["get_course"] = "get_course"
    course_id: str


class CreateCourse(_Input):
    operation: Literal["create_course"] = "create_course"
    course_code: str = Field(..., min_length=1, max_length=100, description="Unique courseId for the new course.")
    name: str = Field(..., min_length=1, max_length=333)
    description: str | None = Field(None, max_length=100000)
    available: Literal["Yes", "No"] = Field("No", description="Whether students may access this course.")


class UpdateCourse(_Input):
    operation: Literal["update_course"] = "update_course"
    course_id: str
    name: str | None = Field(None, min_length=1, max_length=333)
    description: str | None = Field(None, max_length=100000)
    available: Literal["Yes", "No"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, f) is None for f in ("name", "description", "available")):
            raise ValueError("Provide at least one course field to update")
        return self


class ListMemberships(_Page):
    operation: Literal["list_memberships"] = "list_memberships"
    course_id: str


class GetMembership(_Input):
    operation: Literal["get_membership"] = "get_membership"
    course_id: str
    user_id: str


Role = Literal["Instructor", "BbFacilitator", "TeachingAssistant", "CourseBuilder", "Grader", "Student", "Guest", "BbSpectator"]


class CreateMembership(_Input):
    operation: Literal["create_membership"] = "create_membership"
    course_id: str
    user_id: str
    course_role: Role = Field("Student", description="courseRoleId: role granted in this course.")
    available: Literal["Yes", "No"] = "Yes"


class UpdateMembership(_Input):
    operation: Literal["update_membership"] = "update_membership"
    course_id: str
    user_id: str
    course_role: Role | None = None
    available: Literal["Yes", "No"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.course_role is None and self.available is None:
            raise ValueError("Provide a course role or availability to update")
        return self


class DeleteMembership(_Input):
    operation: Literal["delete_membership"] = "delete_membership"
    course_id: str
    user_id: str


class ListAnnouncements(_Page):
    operation: Literal["list_announcements"] = "list_announcements"
    course_id: str
    title: str | None = Field(None, max_length=1000)


class GetAnnouncement(_Input):
    operation: Literal["get_announcement"] = "get_announcement"
    course_id: str
    announcement_id: str


class CreateAnnouncement(_Input):
    operation: Literal["create_announcement"] = "create_announcement"
    course_id: str
    title: str = Field(..., min_length=1, max_length=1000)
    body: str | None = Field(None, max_length=100000, description="Announcement text in Blackboard BbML/HTML format.")
    draft: StrictBool = Field(True, description="Keep as a draft; false makes the announcement available according to Blackboard's defaults.")


class UpdateAnnouncement(_Input):
    operation: Literal["update_announcement"] = "update_announcement"
    course_id: str
    announcement_id: str
    title: str | None = Field(None, min_length=1, max_length=1000)
    body: str | None = Field(None, max_length=100000, description="Announcement text in Blackboard BbML/HTML format.")
    draft: StrictBool | None = Field(None, description="False releases a draft according to Blackboard's availability defaults.")

    @model_validator(mode="after")
    def changes(self):
        if self.title is None and self.body is None and self.draft is None:
            raise ValueError("Provide at least one announcement field to update")
        return self


class DeleteAnnouncement(_Input):
    operation: Literal["delete_announcement"] = "delete_announcement"
    course_id: str
    announcement_id: str


BlackboardConfig = Annotated[Union[ListUsers, GetUser, ListCourses, GetCourse, CreateCourse, UpdateCourse,
    ListMemberships, GetMembership, CreateMembership, UpdateMembership, DeleteMembership,
    ListAnnouncements, GetAnnouncement, CreateAnnouncement, UpdateAnnouncement, DeleteAnnouncement], Field(discriminator="operation")]


class BlackboardNodeConfig(NodeConfig[BlackboardConfig, BlackboardAccessTokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items() if key.lower() not in {"password", "access_token", "refresh_token", "client_secret"}}
    return value


class BlackboardNode(WorkflowNode):
    integration_type = "automation-blackboard"
    connection_evidence = ConnectionEvidence(noun="courses", operation="list_courses", label_keys=("name", "courseId", "id"))

    @classmethod
    def get_config_model(cls):
        return BlackboardNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Blackboard site and access token")
        op, cred = self.config.config, self.config.credentials
        method, template, expected = OPERATIONS[op.operation]
        path = template.format(**{k: quote(getattr(op, k), safe="") for k in ("course_id", "user_id", "announcement_id") if "{" + k + "}" in template})
        params, body = {}, None
        if op.operation.startswith("list_"):
            params = {"limit": op.limit, "offset": op.offset}
            for field, wire in (("user_name", "userName"), ("course_code", "courseId"), ("name", "name"), ("title", "title")):
                if getattr(op, field, None) is not None:
                    params[wire] = getattr(op, field)
        elif method in {"POST", "PUT", "PATCH"}:
            body = {}
            for field, wire in (("course_code", "courseId"), ("name", "name"), ("description", "description"), ("course_role", "courseRoleId"), ("title", "title"), ("body", "body"), ("draft", "draft")):
                if getattr(op, field, None) is not None:
                    body[wire] = getattr(op, field)
            if getattr(op, "available", None) is not None:
                body["availability"] = {"available": op.available}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, cred.site_url + path, params=params,
                    headers={"Authorization": "Bearer " + cred.access_token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Blackboard request could not be completed" + ("; write outcome is unknown, inspect the resource before retrying" if method != "GET" else "")) from None
        if response.status_code != expected:
            message = ""
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = ": " + error["message"][:500]
            except ValueError:
                pass
            raise ValueError(_redact(f"Blackboard HTTP {response.status_code}" + message + ("; write outcome unverified" if method != "GET" else ""), cred.access_token))
        if expected == 204:
            output = {"status": "success", "operation": op.operation, "http_status": expected, "deletion_acknowledged": True}
        else:
            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError()
                if op.operation.startswith("list_") and (not isinstance(data.get("results"), list) or any(not isinstance(row, dict) for row in data["results"])):
                    raise ValueError()
            except ValueError:
                raise ValueError("Blackboard returned an invalid JSON response" + ("; write outcome unverified" if method != "GET" else "")) from None
            output = {"status": "success", "operation": op.operation, "http_status": expected, "data": data}
        output = _redact(output, cred.access_token)
        await self.emit(output)
        return output
