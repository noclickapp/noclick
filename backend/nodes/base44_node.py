"""Base44 Apps API operations authenticated with a personal access token.

Each operation issues one documented request. Record fields stay intact so
workflows can use the custom data model of their own Base44 app.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class Base44TokenCredential(BaseModel):
    model_config = ConfigDict(title="Base44 Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.base44.com/Workspaces/Personal-access-tokens",
            "x-credential-instructions": "Create a personal access token in workspace Settings → Secrets. Choose Full access for writes, or Read-only for reads, and include the apps you want to automate. Paste only the token below. Base44's Apps API is in beta.",
        })
    credential_type: Literal["base44_token"] = Field("base44_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Personal access token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the personal access token, without Bearer or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _App(_Config):
    app_id: str = Field(..., min_length=1, max_length=128, title="App ID")

    @field_validator("app_id", "entity_name", "entity_id", "user_id", check_fields=False)
    @classmethod
    def segment(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a single Base44 resource ID or entity name")
        return value


class _Entity(_App):
    entity_name: str = Field(..., min_length=1, max_length=128, title="Entity name", description="Exact entity name from List entity schemas. Use the separate app user operations for User.")

    @field_validator("entity_name")
    @classmethod
    def non_user(cls, value):
        if value == "User":
            raise ValueError("Use app user operations for Base44's built-in User entity")
        return value


class _Record(_Entity):
    entity_id: str = Field(..., min_length=1, max_length=128, title="Record ID")


class _User(_App):
    user_id: str = Field(..., min_length=1, max_length=128, title="App user ID")


class _OffsetPage(_Config):
    limit: int = Field(100, ge=1, le=10000, description="Maximum items on this page.")
    skip: int = Field(0, ge=0, description="Offset; add limit to fetch the next page.")
    sort: str | None = Field(None, description="One field, optionally prefixed with - for descending.")


class ListApps(_OffsetPage):
    operation: Literal["list_apps"] = "list_apps"
    workspace_id: str | None = Field(None, description="Omit for the token's workspace.")
    search: str | None = None


class GetApp(_App):
    operation: Literal["get_app"] = "get_app"


class CreateApp(_Config):
    operation: Literal["create_app"] = "create_app"
    name: str = Field(..., min_length=1, max_length=500)
    user_description: str | None = None


class UpdateApp(_App):
    operation: Literal["update_app"] = "update_app"
    name: str = Field(..., min_length=1, max_length=500)
    user_description: str | None = Field(None, description="Omit to keep the description. Send an empty string to clear it.")


class ListEntitySchemas(_App):
    operation: Literal["list_entity_schemas"] = "list_entity_schemas"


class GetEntitySchema(_App):
    operation: Literal["get_entity_schema"] = "get_entity_schema"
    entity_name: str = Field(..., min_length=1, max_length=128)


class ListRecords(_Entity):
    operation: Literal["list_records"] = "list_records"
    limit: int = Field(100, ge=1, le=5000)
    cursor: str | None = Field(None, description="Use next_cursor from the previous page.")
    q: dict[str, Any] | None = Field(None, title="Filter", description="Base44 filter object, for example {\"status\": \"paid\"}.", json_schema_extra={"ui:widget": "state_editor"})
    sort: str | None = None
    fields: str | None = Field(None, description="Comma-separated record fields.")


class CountRecords(_Entity):
    operation: Literal["count_records"] = "count_records"
    q: dict[str, Any] | None = Field(None, title="Filter", json_schema_extra={"ui:widget": "state_editor"})


class GetRecord(_Record):
    operation: Literal["get_record"] = "get_record"


class CreateRecord(_Entity):
    operation: Literal["create_record"] = "create_record"
    data: dict[str, Any] = Field(..., title="Record fields", description="Flat object matching your entity's schema.", json_schema_extra={"ui:widget": "state_editor"})


class UpdateRecord(_Record):
    operation: Literal["update_record"] = "update_record"
    data: dict[str, Any] = Field(..., title="Record fields", description="Only fields to change, matching your entity's schema.", json_schema_extra={"ui:widget": "state_editor"})


class DeleteRecord(_Record):
    operation: Literal["delete_record"] = "delete_record"


class CreateRecords(_Entity):
    operation: Literal["create_records"] = "create_records"
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=1000, json_schema_extra={"ui:widget": "state_editor"})


class _RecordUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(..., min_length=1, max_length=128)


class UpdateRecords(_Entity):
    operation: Literal["update_records"] = "update_records"
    records: list[_RecordUpdate] = Field(..., min_length=1, max_length=1000, description="Each object needs id and the fields to change.", json_schema_extra={"ui:widget": "state_editor"})


class ListDeletedRecords(_Entity, _OffsetPage):
    operation: Literal["list_deleted_records"] = "list_deleted_records"
    q: dict[str, Any] | None = Field(None, title="Filter", json_schema_extra={"ui:widget": "state_editor"})


class RestoreRecord(_Record):
    operation: Literal["restore_record"] = "restore_record"


class ListAppUsers(_App, _OffsetPage):
    operation: Literal["list_app_users"] = "list_app_users"
    q: dict[str, Any] | None = Field(None, title="Filter", json_schema_extra={"ui:widget": "state_editor"})


class GetAppUser(_User):
    operation: Literal["get_app_user"] = "get_app_user"


class UpdateAppUser(_User):
    operation: Literal["update_app_user"] = "update_app_user"
    data: dict[str, Any] = Field(..., title="User fields", description="Fields to change; role can be user, admin, or an app-defined role.", json_schema_extra={"ui:widget": "state_editor"})


class DeleteAppUser(_User):
    operation: Literal["delete_app_user"] = "delete_app_user"


Base44Operation = Annotated[Union[
    ListApps, GetApp, CreateApp, UpdateApp, ListEntitySchemas, GetEntitySchema,
    ListRecords, CountRecords, GetRecord, CreateRecord, UpdateRecord, DeleteRecord,
    CreateRecords, UpdateRecords, ListDeletedRecords, RestoreRecord,
    ListAppUsers, GetAppUser, UpdateAppUser, DeleteAppUser,
], Field(discriminator="operation")]


class Base44Config(NodeConfig[Base44Operation, Base44TokenCredential]):
    pass


# Fixed templates make the one-to-one contract mapping explicit and auditable.
APP = "/api/apps/{app_id}"
ENTITY = APP + "/entities/{entity_name}"
RECORD = ENTITY + "/{entity_id}"
USER = APP + "/entities/User/{user_id}"
ROUTES = {
    "list_apps": ("GET", "/api/apps"),
    "get_app": ("GET", APP), "create_app": ("POST", "/api/apps"), "update_app": ("PUT", APP),
    "list_entity_schemas": ("GET", APP + "/entity-schemas"),
    "get_entity_schema": ("GET", APP + "/entity-schemas/{entity_name}"),
    "list_records": ("GET", ENTITY + "/v2/list"), "count_records": ("GET", ENTITY + "/count"),
    "get_record": ("GET", RECORD), "create_record": ("POST", ENTITY),
    "update_record": ("PUT", RECORD), "delete_record": ("DELETE", RECORD),
    "create_records": ("POST", ENTITY + "/bulk"), "update_records": ("PUT", ENTITY + "/bulk"),
    "list_deleted_records": ("GET", ENTITY + "/trash"), "restore_record": ("PUT", RECORD + "/restore"),
    "list_app_users": ("GET", APP + "/entities/User"), "get_app_user": ("GET", USER),
    "update_app_user": ("PUT", USER), "delete_app_user": ("DELETE", USER),
}


class Base44Node(WorkflowNode):
    integration_type = "automation-base44"
    connection_evidence = ConnectionEvidence(noun="apps", operation="list_apps")

    @classmethod
    def get_config_model(cls):
        return Base44Config

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Base44 personal access token")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        operation = values.pop("operation")
        method, template = ROUTES[operation]
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{key: quote(values.pop(key), safe="") for key in path_fields})
        body = None
        if operation in {"create_app", "update_app"}:
            body, values = values, {}
        elif operation in {"create_record", "update_record", "update_app_user"}:
            body = values.pop("data")
        elif operation in {"create_records", "update_records"}:
            body = values.pop("records")
        if "q" in values:
            values["q"] = json.dumps(values["q"], separators=(",", ":"), allow_nan=False)
        token = self.config.credentials.access_token
        kwargs = {"params": values, "headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
        if body is not None:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://app.base44.com" + path, **kwargs)
        # Keep provider rejections verbatim for the shared connection verdict.
        if not 200 <= response.status_code < 300:
            message = response.text[:2000].replace(token, "<redacted>")
            output = {"status": "error", "http_status": response.status_code, "error": message}
        else:
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("Expected a JSON response from Base44")
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Unexpected Base44 response shape")
            if isinstance(payload, dict) and ("error" in payload or payload.get("success") is False):
                output = {"status": "error", "http_status": response.status_code, "error": payload}
            else:
                output = {"status": "success", "http_status": response.status_code,
                          **({"items": payload} if isinstance(payload, list) else {"data": payload})}
        await self.emit(output)
        return output
