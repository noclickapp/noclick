"""Zeplin API v1: personal-token design handoff and collaboration operations.

Contract: zeplin/openapi a599682d15da3d38c233d3c6f97cad28158869d9, v1.43.0.
Each operation issues one request. Lists return one explicit offset page; writes
are never automatically retried, including after an ambiguous network failure.
"""
from __future__ import annotations

import re

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.zeplin.dev"
CREDENTIAL_TYPE = "zeplin_personal_token"
ResourceId = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{24}$", description="Zeplin's 24-character hexadecimal resource ID.")]


class ZeplinPersonalTokenCredential(BaseModel):
    model_config = ConfigDict(title="Zeplin Personal Access Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.zeplin.io/profile/developer",
            "x-credential-instructions": "Create a personal access token in your Zeplin profile's Developer tab, then paste it here without the Bearer prefix. It acts with your account's permissions. See https://docs.zeplin.dev/reference/introduction."})
    credential_type: Literal["zeplin_personal_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    personal_access_token: str = Field(..., title="Personal Access Token", min_length=1, max_length=8192,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("personal_access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the personal access token")
        value = clean_secret(value, field_name="Personal access token")
        if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value):
            raise ValueError("Paste the personal access token without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(30, ge=1, le=100, strict=True, title="Page Size")
    offset: int = Field(0, ge=0, strict=True, title="Offset", description="Use next_offset from the preceding page. Zeplin defaults to 30 items per page.")


class _Project(_Input):
    project_id: ResourceId = Field(..., title="Project ID")


class _Screen(_Project):
    screen_id: ResourceId = Field(..., title="Screen ID")


class _Note(_Screen):
    note_id: ResourceId = Field(..., title="Note ID")


class _Comment(_Note):
    comment_id: ResourceId = Field(..., title="Comment ID")


class _Styleguide(_Input):
    styleguide_id: ResourceId = Field(..., title="Styleguide ID")


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class ListProjects(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})


class UpdateProject(_Project):
    operation: Literal["update_project"] = Field("update_project", title="Update Project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Project Name")
    description: str | None = Field(None, title="Description")


class ListProjectMembers(_Project, _Page):
    operation: Literal["list_project_members"] = Field("list_project_members", title="List Project Members", json_schema_extra={"ui:hidden": True})


class ListScreens(_Project, _Page):
    operation: Literal["list_screens"] = Field("list_screens", title="List Screens", json_schema_extra={"ui:hidden": True})


class GetScreen(_Screen):
    operation: Literal["get_screen"] = Field("get_screen", title="Get Screen", json_schema_extra={"ui:hidden": True})


class UpdateScreen(_Screen):
    operation: Literal["update_screen"] = Field("update_screen", title="Update Screen", json_schema_extra={"ui:hidden": True})
    description: str = Field(..., title="Description")


class ListNotes(_Screen, _Page):
    operation: Literal["list_notes"] = Field("list_notes", title="List Notes", json_schema_extra={"ui:hidden": True})


class GetNote(_Note):
    operation: Literal["get_note"] = Field("get_note", title="Get Note", json_schema_extra={"ui:hidden": True})


class CreateNote(_Screen):
    operation: Literal["create_note"] = Field("create_note", title="Create Note", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1, title="First Comment")
    x: float = Field(..., ge=0, le=1, allow_inf_nan=False, title="Horizontal Position", description="Normalized coordinate from 0 to 1.")
    y: float = Field(..., ge=0, le=1, allow_inf_nan=False, title="Vertical Position", description="Normalized coordinate from 0 to 1.")
    color: Literal["yellow", "orange", "peach", "green", "turquoise", "cornflower_blue", "deep_purple"] = Field("yellow", title="Note Color")


class UpdateNote(_Note):
    operation: Literal["update_note"] = Field("update_note", title="Update Note", json_schema_extra={"ui:hidden": True})
    status: Literal["open", "resolved"] = Field(..., title="Note Status")


class DeleteNote(_Note):
    operation: Literal["delete_note"] = Field("delete_note", title="Delete Note", json_schema_extra={"ui:hidden": True})


class CreateComment(_Note):
    operation: Literal["create_comment"] = Field("create_comment", title="Create Comment", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1, title="Comment")


class UpdateComment(_Comment):
    operation: Literal["update_comment"] = Field("update_comment", title="Update Comment", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1, title="Comment")


class DeleteComment(_Comment):
    operation: Literal["delete_comment"] = Field("delete_comment", title="Delete Comment", json_schema_extra={"ui:hidden": True})


class ListScreenVersions(_Screen, _Page):
    operation: Literal["list_screen_versions"] = Field("list_screen_versions", title="List Screen Versions", json_schema_extra={"ui:hidden": True})


class GetLatestScreenVersion(_Screen):
    operation: Literal["get_latest_screen_version"] = Field("get_latest_screen_version", title="Get Latest Screen Version", json_schema_extra={"ui:hidden": True})


class ListProjectColors(_Project, _Page):
    operation: Literal["list_project_colors"] = Field("list_project_colors", title="List Project Colors", json_schema_extra={"ui:hidden": True})


class ListProjectTextStyles(_Project, _Page):
    operation: Literal["list_project_text_styles"] = Field("list_project_text_styles", title="List Project Text Styles", json_schema_extra={"ui:hidden": True})


class ListStyleguides(_Page):
    operation: Literal["list_styleguides"] = Field("list_styleguides", title="List Styleguides", json_schema_extra={"ui:hidden": True})


class GetStyleguide(_Styleguide):
    operation: Literal["get_styleguide"] = Field("get_styleguide", title="Get Styleguide", json_schema_extra={"ui:hidden": True})


class UpdateStyleguide(_Styleguide):
    operation: Literal["update_styleguide"] = Field("update_styleguide", title="Update Styleguide", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Styleguide Name")
    description: str | None = Field(None, title="Description")


class ListStyleguideColors(_Styleguide, _Page):
    operation: Literal["list_styleguide_colors"] = Field("list_styleguide_colors", title="List Styleguide Colors", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetCurrentUser, ListProjects, GetProject, UpdateProject, ListProjectMembers, ListScreens, GetScreen, UpdateScreen, ListNotes, GetNote, CreateNote, UpdateNote, DeleteNote, CreateComment, UpdateComment, DeleteComment, ListScreenVersions, GetLatestScreenVersion, ListProjectColors, ListProjectTextStyles, ListStyleguides, GetStyleguide, UpdateStyleguide, ListStyleguideColors], Field(discriminator="operation")]


class ZeplinNodeConfig(NodeConfig[Operation, ZeplinPersonalTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'get_current_user': ('GET', '/v1/users/me', {}),
 'list_projects': ('GET', '/v1/projects', {}),
 'get_project': ('GET', '/v1/projects/{project_id}', {}),
 'update_project': ('PATCH', '/v1/projects/{project_id}', {'name': 'name', 'description': 'description'}),
 'list_project_members': ('GET', '/v1/projects/{project_id}/members', {}),
 'list_screens': ('GET', '/v1/projects/{project_id}/screens', {}),
 'get_screen': ('GET', '/v1/projects/{project_id}/screens/{screen_id}', {}),
 'update_screen': ('PATCH', '/v1/projects/{project_id}/screens/{screen_id}', {'description': 'description'}),
 'list_notes': ('GET', '/v1/projects/{project_id}/screens/{screen_id}/notes', {}),
 'get_note': ('GET', '/v1/projects/{project_id}/screens/{screen_id}/notes/{note_id}', {}),
 'create_note': ('POST',
                 '/v1/projects/{project_id}/screens/{screen_id}/notes',
                 {'content': 'content', 'color': 'color', 'position': {'x': 'x', 'y': 'y'}}),
 'update_note': ('PATCH', '/v1/projects/{project_id}/screens/{screen_id}/notes/{note_id}', {'status': 'status'}),
 'delete_note': ('DELETE', '/v1/projects/{project_id}/screens/{screen_id}/notes/{note_id}', {}),
 'create_comment': ('POST',
                    '/v1/projects/{project_id}/screens/{screen_id}/notes/{note_id}/comments',
                    {'content': 'content'}),
 'update_comment': ('PATCH',
                    '/v1/projects/{project_id}/screens/{screen_id}/notes/{note_id}/comments/{comment_id}',
                    {'content': 'content'}),
 'delete_comment': ('DELETE',
                    '/v1/projects/{project_id}/screens/{screen_id}/notes/{note_id}/comments/{comment_id}',
                    {}),
 'list_screen_versions': ('GET', '/v1/projects/{project_id}/screens/{screen_id}/versions', {}),
 'get_latest_screen_version': ('GET', '/v1/projects/{project_id}/screens/{screen_id}/versions/latest', {}),
 'list_project_colors': ('GET', '/v1/projects/{project_id}/colors', {}),
 'list_project_text_styles': ('GET', '/v1/projects/{project_id}/text_styles', {}),
 'list_styleguides': ('GET', '/v1/styleguides', {}),
 'get_styleguide': ('GET', '/v1/styleguides/{styleguide_id}', {}),
 'update_styleguide': ('PATCH', '/v1/styleguides/{styleguide_id}', {'name': 'name', 'description': 'description'}),
 'list_styleguide_colors': ('GET', '/v1/styleguides/{styleguide_id}/colors', {})}


class ZeplinNode(WorkflowNode):
    integration_type = "automation-zeplin"
    connection_evidence = ConnectionEvidence(noun="Zeplin account", identity_operation="get_current_user",
        identity_keys=("username", "email"))

    @classmethod
    def get_config_model(cls):
        return ZeplinNodeConfig

    async def execute(self, inputs):
        cfg = self.config
        if not isinstance(cfg, ZeplinNodeConfig) or cfg.credentials is None:
            return {"status": "error", "error": "Connect a Zeplin personal access token"}
        op = cfg.config
        method, template, fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        route = template.format(**{k: quote(str(v), safe="") for k, v in values.items() if k.endswith("_id")})
        params = {k: values[k] for k in ("limit", "offset") if k in values}
        def body_value(mapping):
            return {key: body_value(field) if isinstance(field, dict) else values[field]
                    for key, field in mapping.items() if isinstance(field, dict) or field in values}
        body = body_value(fields) if fields else None
        token = cfg.credentials.personal_access_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route, headers=headers, params=params,
                    **({"json": body} if body is not None else {}))
            expected = 204 if method in {"PATCH", "DELETE"} else 201 if method == "POST" else 200
            if response.status_code != expected:
                message = "Zeplin request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"].replace(token, "[redacted]")[:2000]
                except (ValueError, TypeError):
                    pass
                return {"status": "error", "error": message, "http_status": response.status_code}
            if expected == 204:
                return {"status": "success", "operation": op.operation, "http_status": expected}
            if len(response.content) > 10_000_000:
                return {"status": "error", "error": "Zeplin response exceeds the supported size"}
            result = response.json()
            if "limit" in params:
                if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                    return {"status": "error", "error": "Expected a Zeplin resource list"}
                more = len(result) == op.limit
                return {"status": "success", "items": result, "has_more": more,
                    "next_offset": op.offset + len(result) if more else None}
            if not isinstance(result, dict) or "message" in result:
                return {"status": "error", "error": "Expected a Zeplin resource object"}
            return {"status": "success", "data": result}
        except (httpx.HTTPError, OSError, SSRFError):
            return {"status": "error", "error": "Zeplin request did not complete; inspect Zeplin before retrying a write"}
        except ValueError:
            return {"status": "error", "error": "Zeplin returned invalid JSON"}
