"""Parma v1 CRM operations using a person-supplied workspace API token.

Contract: https://developers.parma.ai/api-docs/v1/swagger.yaml
Each operation issues exactly one request; paginated reads return one page.
"""
from __future__ import annotations

from datetime import datetime as DateTime
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.parma.ai/api/v1"
ID = Annotated[int, Field(gt=0, le=2147483647, strict=True)]


class ParmaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Parma API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.parma.ai/api",
            "x-credential-instructions": "Open Parma's API page for your workspace and copy its API token. Paste the token here. It grants read and write access to that workspace; NoClick sends it only to app.parma.ai.",
        })
    credential_type: Literal["parma_api_token"] = Field("parma_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def shape_token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a Parma API token without spaces or control characters")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_write(self):
        if self.operation in {"update_relationship", "update_note"}:
            path_fields = {"operation", "relationship_id", "note_id"}
            if not any(v is not None for k, v in self.model_dump().items() if k not in path_fields):
                raise ValueError("Provide at least one field to update")
        value = getattr(self, "datetime", None)
        if value is not None:
            try:
                parsed = DateTime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Use an ISO 8601 date and time with a timezone") from None
            if parsed.tzinfo is None:
                raise ValueError("Include the timezone in the note date and time")
        return self


class ParmaListRelationshipsConfig(_Operation):
    operation: Literal["list_relationships"] = Field("list_relationships", title="List relationships")
    page: int = Field(1, ge=1, le=1000000)
    name: Optional[str] = Field(None, max_length=500)
    relationship_type: Optional[Literal["person", "company"]] = None
    email: Optional[str] = Field(None, max_length=500)


class ParmaGetRelationshipConfig(_Operation):
    operation: Literal["get_relationship"] = Field("get_relationship", title="Get relationship")
    relationship_id: ID


class ParmaCreateRelationshipConfig(_Operation):
    operation: Literal["create_relationship"] = Field("create_relationship", title="Create relationship")
    name: str = Field(..., min_length=1, max_length=1000)
    group_ids: list[ID] = Field(..., max_length=1000)
    relationship_type: Literal["person", "company"] = "person"
    company_id: Optional[ID] = None
    about: Optional[str] = Field(None, max_length=100000)


class ParmaUpdateRelationshipConfig(_Operation):
    operation: Literal["update_relationship"] = Field("update_relationship", title="Update relationship")
    relationship_id: ID
    name: Optional[str] = Field(None, min_length=1, max_length=1000)
    group_ids: Optional[list[ID]] = Field(None, max_length=1000)
    relationship_type: Optional[Literal["person", "company"]] = None
    company_id: Optional[ID] = None
    about: Optional[str] = Field(None, max_length=100000)


class ParmaDeleteRelationshipConfig(_Operation):
    operation: Literal["delete_relationship"] = Field("delete_relationship", title="Delete relationship")
    relationship_id: ID


class ParmaListNotesConfig(_Operation):
    operation: Literal["list_notes"] = Field("list_notes", title="List notes")
    page: int = Field(1, ge=1, le=1000000)


class ParmaListRelationshipNotesConfig(_Operation):
    operation: Literal["list_relationship_notes"] = Field("list_relationship_notes", title="List relationship notes")
    relationship_id: ID
    page: int = Field(1, ge=1, le=1000000)


class ParmaCreateNoteConfig(_Operation):
    operation: Literal["create_note"] = Field("create_note", title="Create note")
    body: str = Field(..., min_length=1, max_length=100000)
    relationship_ids: list[ID] = Field(..., min_length=1, max_length=1000)
    datetime: Optional[str] = Field(None, max_length=64)


class ParmaUpdateNoteConfig(_Operation):
    operation: Literal["update_note"] = Field("update_note", title="Update note")
    note_id: ID
    body: Optional[str] = Field(None, min_length=1, max_length=100000)
    relationship_ids: Optional[list[ID]] = Field(None, min_length=1, max_length=1000)
    datetime: Optional[str] = Field(None, max_length=64)


class ParmaListGroupsConfig(_Operation):
    operation: Literal["list_groups"] = Field("list_groups", title="List groups")
    query: Optional[str] = Field(None, max_length=500)


class ParmaListRelationshipGroupsConfig(_Operation):
    operation: Literal["list_relationship_groups"] = Field("list_relationship_groups", title="List relationship groups")
    relationship_id: ID


class ParmaAddRelationshipToGroupConfig(_Operation):
    operation: Literal["add_relationship_to_group"] = Field("add_relationship_to_group", title="Add relationship to group")
    relationship_id: ID
    group_id: ID


class ParmaRemoveRelationshipFromGroupConfig(_Operation):
    operation: Literal["remove_relationship_from_group"] = Field("remove_relationship_from_group", title="Remove relationship from group")
    relationship_id: ID
    relationship_group_id: ID = Field(..., description="Membership ID from List relationship groups; not the group ID")


class ParmaListDealsConfig(_Operation):
    operation: Literal["list_deals"] = Field("list_deals", title="List deals")
    page: int = Field(1, ge=1, le=1000000)


class ParmaGetDealConfig(_Operation):
    operation: Literal["get_deal"] = Field("get_deal", title="Get deal")
    deal_id: ID


class ParmaListPipelinesConfig(_Operation):
    operation: Literal["list_pipelines"] = Field("list_pipelines", title="List pipelines")


class ParmaGetPipelineConfig(_Operation):
    operation: Literal["get_pipeline"] = Field("get_pipeline", title="Get pipeline")
    pipeline_id: ID


class ParmaListStagesConfig(_Operation):
    operation: Literal["list_stages"] = Field("list_stages", title="List stages")


class ParmaGetStageConfig(_Operation):
    operation: Literal["get_stage"] = Field("get_stage", title="Get stage")
    stage_id: ID


class ParmaListUsersConfig(_Operation):
    operation: Literal["list_users"] = Field("list_users", title="List users")


class ParmaGetCurrentUserConfig(_Operation):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get current user")


ParmaConfig = Annotated[Union[
    ParmaListRelationshipsConfig,
    ParmaGetRelationshipConfig,
    ParmaCreateRelationshipConfig,
    ParmaUpdateRelationshipConfig,
    ParmaDeleteRelationshipConfig,
    ParmaListNotesConfig,
    ParmaListRelationshipNotesConfig,
    ParmaCreateNoteConfig,
    ParmaUpdateNoteConfig,
    ParmaListGroupsConfig,
    ParmaListRelationshipGroupsConfig,
    ParmaAddRelationshipToGroupConfig,
    ParmaRemoveRelationshipFromGroupConfig,
    ParmaListDealsConfig,
    ParmaGetDealConfig,
    ParmaListPipelinesConfig,
    ParmaGetPipelineConfig,
    ParmaListStagesConfig,
    ParmaGetStageConfig,
    ParmaListUsersConfig,
    ParmaGetCurrentUserConfig
], Field(discriminator="operation")]


class ParmaFullConfig(NodeConfig[ParmaConfig, ParmaAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed routes from the provider contract, never a caller-supplied URL.
ROUTES = {
    'list_relationships': ('GET', '/relationships'),
    'get_relationship': ('GET', '/relationships/{relationship_id}'),
    'create_relationship': ('POST', '/relationships'),
    'update_relationship': ('PATCH', '/relationships/{relationship_id}'),
    'delete_relationship': ('DELETE', '/relationships/{relationship_id}'),
    'list_notes': ('GET', '/notes'),
    'list_relationship_notes': ('GET', '/relationships/{relationship_id}/notes'),
    'create_note': ('POST', '/notes'),
    'update_note': ('PATCH', '/notes/{note_id}'),
    'list_groups': ('GET', '/groups'),
    'list_relationship_groups': ('GET', '/relationships/{relationship_id}/groups'),
    'add_relationship_to_group': ('POST', '/relationships/{relationship_id}/groups'),
    'remove_relationship_from_group': ('DELETE', '/relationships/{relationship_id}/groups/{relationship_group_id}'),
    'list_deals': ('GET', '/deals'),
    'get_deal': ('GET', '/deals/{deal_id}'),
    'list_pipelines': ('GET', '/pipelines'),
    'get_pipeline': ('GET', '/pipelines/{pipeline_id}'),
    'list_stages': ('GET', '/stages'),
    'get_stage': ('GET', '/stages/{stage_id}'),
    'list_users': ('GET', '/users'),
    'get_current_user': ('GET', '/users/me'),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class ParmaNode(WorkflowNode):
    integration_type = "automation-parma"
    connection_evidence = ConnectionEvidence(
        noun="users", operation="list_users", identity_operation="get_current_user",
        label_keys=("name", "email", "id"),
    )
    edit_examples = ["Find relationships by email", "Add a note to a relationship", "Add a relationship to a group"]

    @classmethod
    def get_config_model(cls):
        return ParmaFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Parma API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, route = ROUTES[config.operation]
        fields = config.model_dump(exclude={"operation"}, exclude_none=True)
        for key in tuple(fields):
            placeholder = "{" + key + "}"
            if placeholder in route:
                route = route.replace(placeholder, str(fields.pop(key)))
        if "relationship_type" in fields:
            fields["type"] = fields.pop("relationship_type")
        if "page" in fields:
            fields["page"] = str(fields["page"])
        kwargs = {"params": fields} if method == "GET" else ({"json": fields} if method != "DELETE" else {})
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except (httpx.HTTPError, ValueError):
            return {**output, "status": "error", "error": "Parma could not confirm the request", "write_outcome": "unknown" if method != "GET" else None}
        status = response.status_code
        if not 200 <= status < 300:
            return {**output, "status": "error", "http_status": status,
                "error": _redact(response.text[:2000], token) or "Parma rejected the request",
                "write_outcome": "unknown" if method != "GET" and (status >= 500 or status in {408, 429}) else None}
        if method == "DELETE":
            if status != 204:
                return {**output, "status": "error", "http_status": status, "error": "Parma did not acknowledge deletion", "write_outcome": "unknown"}
            return {**output, "status": "success", "http_status": status, "deletion_acknowledged": True}
        expected_status = 201 if config.operation in {"create_relationship", "create_note", "update_note", "add_relationship_to_group"} else 200
        if status != expected_status:
            return {**output, "status": "error", "http_status": status,
                "error": "Parma did not return the documented completion status",
                "write_outcome": "unknown" if method != "GET" else None}
        try:
            if len(response.content) > 5_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError()
            payload = response.json()
            if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
                raise ValueError()
            data = payload.get("data")
            if config.operation.startswith("list_"):
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError()
            elif not isinstance(data, dict):
                raise ValueError()
            if config.operation == "get_current_user" and not (
                isinstance(data.get("user"), dict) and isinstance(data.get("account"), dict)
                and data["user"].get("id") and data["account"].get("id")
            ):
                raise ValueError()
            result = {**output, "status": "success", "http_status": status, "data": data}
            if "meta" in payload:
                result["meta"] = payload["meta"]
            if hasattr(config, "page"):
                # The docs expose page numbers but no page size or next link.
                # A nonempty page may have a successor; only an empty one proves exhaustion.
                result.update(page=config.page, next_page=config.page + 1 if data and config.page < 1000000 else None,
                    pagination_complete=not data, bounded_stop=bool(data) and config.page == 1000000)
            return _redact(result, token)
        except (ValueError, TypeError):
            return {**output, "status": "error", "http_status": status, "error": "Parma returned an unexpected response", "write_outcome": "unknown" if method != "GET" else None}
