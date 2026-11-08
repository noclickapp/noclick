"""Fullstory Server API v2 users, events and asynchronous imports.

Contract: fullstorydev/fullstory-node-sdk specs/users.sdk.swagger.json and
specs/events.swagger.json. Authentication: https://developer.fullstory.com/server/authentication/
Each operation makes one request; pagination and asynchronous job polling are explicit.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.fullstory.com"


class FullstoryAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Fullstory API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.fullstory.com/server/authentication/",
            "x-credential-instructions": "Paste a Fullstory API key from Settings > Integrations > API Keys. Use an Architect or Admin key for user reads and deletion, including the connection check. Standard keys can send users and events and manage imports. NoClick sends the key directly in the Authorization header to api.fullstory.com."})
    credential_type: Literal["fullstory_api_key"] = Field("fullstory_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without an Authorization prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class UserData(Input):
    uid: Optional[str] = Field(None, max_length=256)
    display_name: Optional[str] = Field(None, max_length=256)
    email: Optional[str] = Field(None, max_length=128)
    properties: Optional[dict[str, Any]] = Field(None, max_length=500)
    schema_: Optional[dict[str, Any]] = Field(None, alias="schema")


class BatchUserData(UserData):
    id: Optional[str] = None


class EventUser(Input):
    id: Optional[str] = None
    uid: Optional[str] = Field(None, max_length=256)

    @model_validator(mode="after")
    def single_identifier(self):
        if bool(self.id) == bool(self.uid):
            raise ValueError("Supply exactly one user id or uid")
        return self


class EventSession(Input):
    id: Optional[str] = None
    use_most_recent: Optional[StrictBool] = None

    @model_validator(mode="after")
    def single_session(self):
        if self.id and self.use_most_recent:
            raise ValueError("Use a session id or the most recent session")
        return self


class EventData(Input):
    name: str = Field(..., min_length=1)
    user: Optional[EventUser] = None
    session: Optional[EventSession] = None
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp; defaults to the Fullstory server time.")
    properties: Optional[dict[str, Any]] = None
    context: Optional[dict[str, Any]] = None
    schema_: Optional[dict[str, Any]] = Field(None, alias="schema")

    @model_validator(mode="after")
    def association(self):
        if self.session and self.session.id and self.user:
            raise ValueError("A session id identifies the user; omit user")
        if self.session and self.session.use_most_recent and not self.user:
            raise ValueError("The most recent session requires a user")
        return self


class Page(Input):
    page_token: Optional[str] = Field(None, description="Use next_page_token from the previous page with the same filters.")


class WithSchema(Input):
    include_schema: Optional[StrictBool] = None


class UserID(Input):
    id: str = Field(..., min_length=1, max_length=256, description="Fullstory-assigned user ID, not your application uid.")


class JobID(Input):
    job_id: str = Field(..., min_length=1, max_length=1024)


class Idempotent(Input):
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=256,
        description="Optional Idempotency-Key header. Reuse the same key only for an identical request.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if value and any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Use a printable ASCII idempotency key")
        return value


class ListUsers(Page, WithSchema):
    operation: Literal["list_users"] = "list_users"
    uid: Optional[str] = Field(None, max_length=256)
    email: Optional[str] = Field(None, max_length=128)
    display_name: Optional[str] = Field(None, max_length=256)
    is_identified: Optional[StrictBool] = None


class GetUser(UserID, WithSchema):
    operation: Literal["get_user"] = "get_user"


class CreateUser(UserData, Idempotent):
    operation: Literal["create_user"] = "create_user"


class UpdateUser(UserData, UserID):
    operation: Literal["update_user"] = "update_user"


class DeleteUser(UserID):
    """Request asynchronous deletion; a successful response does not prove erasure is complete."""
    operation: Literal["delete_user"] = "delete_user"


class DeleteUserByUID(Input):
    """Delete by your application uid; always send uid to avoid an unfiltered delete."""
    operation: Literal["delete_user_by_uid"] = "delete_user_by_uid"
    uid: str = Field(..., min_length=1, max_length=256)


class ImportUsers(Idempotent):
    operation: Literal["import_users"] = "import_users"
    requests: list[BatchUserData] = Field(..., min_length=1, max_length=10000)


class GetUserImport(JobID):
    operation: Literal["get_user_import"] = "get_user_import"


class ListUserImportErrors(JobID, Page):
    operation: Literal["list_user_import_errors"] = "list_user_import_errors"


class ListUserImports(JobID, Page, WithSchema):
    operation: Literal["list_user_imports"] = "list_user_imports"


class CreateEvent(EventData, Idempotent):
    operation: Literal["create_event"] = "create_event"


class ImportEvents(Idempotent):
    operation: Literal["import_events"] = "import_events"
    requests: list[EventData] = Field(..., min_length=1, max_length=10000)
    shared: Optional[dict[str, Any]] = Field(None, description="Shared context; events must omit their own context when shared.context is set.")

    @model_validator(mode="after")
    def shared_context(self):
        if self.shared and "context" in self.shared and any(r.context is not None for r in self.requests):
            raise ValueError("Use shared context or per-event context")
        return self


class GetEventImport(JobID):
    operation: Literal["get_event_import"] = "get_event_import"


class ListEventImportErrors(JobID, Page):
    operation: Literal["list_event_import_errors"] = "list_event_import_errors"


class ListEventImports(JobID, Page, WithSchema):
    operation: Literal["list_event_imports"] = "list_event_imports"


FullstoryConfig = Annotated[Union[ListUsers, GetUser, CreateUser, UpdateUser, DeleteUser,
    DeleteUserByUID, ImportUsers, GetUserImport, ListUserImportErrors, ListUserImports,
    CreateEvent, ImportEvents, GetEventImport, ListEventImportErrors, ListEventImports], Field(discriminator="operation")]


class FullstoryFullConfig(NodeConfig[FullstoryConfig, FullstoryAPIKeyCredential]):
    pass


# Fixed operations map one-to-one to published v2 endpoints (no v2beta aliases).
ROUTES = {
    "list_users": ("GET", "/v2/users"),
    "get_user": ("GET", "/v2/users/{id}"),
    "create_user": ("POST", "/v2/users"),
    "update_user": ("POST", "/v2/users/{id}"),
    "delete_user": ("DELETE", "/v2/users/{id}"),
    "delete_user_by_uid": ("DELETE", "/v2/users"),
    "import_users": ("POST", "/v2/users/batch"),
    "get_user_import": ("GET", "/v2/users/batch/{job_id}"),
    "list_user_import_errors": ("GET", "/v2/users/batch/{job_id}/errors"),
    "list_user_imports": ("GET", "/v2/users/batch/{job_id}/imports"),
    "create_event": ("POST", "/v2/events"),
    "import_events": ("POST", "/v2/events/batch"),
    "get_event_import": ("GET", "/v2/events/batch/{job_id}"),
    "list_event_import_errors": ("GET", "/v2/events/batch/{job_id}/errors"),
    "list_event_imports": ("GET", "/v2/events/batch/{job_id}/imports"),
}


class FullstoryNode(WorkflowNode):
    integration_type = "automation-fullstory"
    connection_evidence = ConnectionEvidence(noun="Fullstory users", operation="list_users")

    @classmethod
    def get_config_model(cls):
        return FullstoryFullConfig

    async def execute(self, inputs):
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Fullstory API key")
        method, path = ROUTES[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True)
        values.pop("operation")
        for key in ("id", "job_id"):
            if "{" + key + "}" in path:
                value = values.pop(key)
                if value in {".", ".."} or any(c in value for c in "/\\?#"):
                    raise ValueError("Use a single Fullstory resource ID")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        headers = {"Authorization": "Basic " + credential.api_key, "Accept": "application/json"}
        key = values.pop("idempotency_key", None)
        if key is not None:
            headers["Idempotency-Key"] = key
        params, body = None, None
        if method == "POST":
            body = values
        else:
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        allowed = {200, 202} if op.operation in {"list_user_import_errors", "list_user_imports", "list_event_import_errors", "list_event_imports"} else {200}
        if response.status_code not in allowed:
            # Preserve the provider's rejection for the shared connection verdict,
            # redacting the credential if an upstream error happens to echo it.
            message = "Fullstory request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "error": message, "http_status": response.status_code}
        if len(response.content) > 20_000_000:
            raise ValueError("Fullstory response exceeds the size limit")
        data = response.json()
        if not isinstance(data, dict) or "code" in data and "message" in data:
            raise ValueError("Unexpected Fullstory response")
        if response.status_code == 202:
            return {"status": "success", "http_status": 202, "pending": True, "data": data}
        if op.operation.startswith("list_"):
            if not isinstance(data.get("results"), list):
                raise ValueError("Fullstory response is missing results")
            token = data.get("next_page_token")
            if token is not None and not isinstance(token, str):
                raise ValueError("Unexpected Fullstory page token")
            return {"status": "success", "http_status": 200, "data": data,
                "results": data["results"], "next_page_token": token or None, "has_more": bool(token)}
        return {"status": "success", "http_status": 200, "data": data,
            **({"deletion_requested": True, "deletion_complete": False} if method == "DELETE" else {})}
