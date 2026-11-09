"""Coassemble headless API operations using a pasted workspace API key.

Each operation sends one documented request and preserves its JSON response.
Lists expose an explicit page boundary; writes report acknowledgement only.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.coassemble.com/api/v1/headless"


class CoassembleAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Coassemble API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://coassemble.com/dashboard/developer?tab=overview&setup=1",
            "x-credential-instructions": "Copy your workspace API key from Coassemble's developer setup guide. Paste the complete COASSEMBLE:<workspaceId>:<token> value without the Authorization header name. NoClick sends it only to api.coassemble.com. Course access verifies this connection; it does not verify every write permission.",
        },
    )
    credential_type: Literal["coassemble_api_key"] = Field("coassemble_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Paste the complete API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    length: int = Field(100, ge=1, le=100, description="Maximum records on this page (up to 100).")
    page: int = Field(0, ge=0, le=1000000, description="Zero-indexed page. Use next_page to request another page when this page is full.")


class _OwnerFilters(_Page):
    identifier: str | None = Field(None, min_length=1, max_length=512, description="Filter by the owner's stable user identifier.")
    client_identifier: str | None = Field(None, min_length=1, max_length=512, description="Filter by stable client identifier.")
    deleted: bool = Field(False, description="Include soft-deleted resources.")


class _Client(_Input):
    identifier: str = Field(..., min_length=1, max_length=512, description="Your stable client identifier. Avoid personal data: this identifier is retained after deletion.")

    @field_validator("identifier")
    @classmethod
    def path_identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a stable identifier without dot segments or control characters")
        return value


class _User(_Input):
    identifier: str = Field(..., min_length=1, max_length=512, description="Your stable user identifier.")

    @field_validator("identifier")
    @classmethod
    def path_identifier(cls, value):
        return _Client.path_identifier(value)


class _Course(_Input):
    course_id: int = Field(..., ge=1, description="Coassemble course ID.")


class _Collection(_Input):
    collection_id: int = Field(..., ge=1, description="Coassemble collection ID.")


class _CollectionFields(_Input):
    title: str | None = Field(None, min_length=1, max_length=2000)
    description: str | None = Field(None, max_length=20000)
    identifier: str | None = Field(None, min_length=1, max_length=512, description="Stable collection owner identifier.")
    client_identifier: str | None = Field(None, min_length=1, max_length=512)
    theme_id: int | None = Field(None, ge=1)
    identified: bool | None = Field(None, description="Require learner identification on the share link. Does not apply to embeds.")
    private: bool | None = Field(None, description="Restrict the share link to invited emails. Does not apply to embeds.")
    domain: bool | None = Field(None, description="Restrict the share link to approved email domains. Does not apply to embeds.")
    domains: list[str] | None = Field(None, max_length=1000)
    emails: list[str] | None = Field(None, max_length=1000)


class CoassembleListClientsConfig(_Page):
    """List workspace clients, one page at a time."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})


class CoassembleGetClientConfig(_Client):
    """Get a client by its stable identifier."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})


class CoassembleUpdateClientConfig(_Client):
    """Update metadata attached to a client."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    metadata: dict[str, Any] = Field(..., description="Metadata to attach to the client.")


class CoassembleListUsersConfig(_Page):
    """List users with an optional client filter."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    client_identifier: str | None = Field(None, min_length=1, max_length=512)


class CoassembleGetUserConfig(_User):
    """Get a user by the stable user identifier."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})


class CoassembleUpdateUserConfig(_User):
    """Update a user profile, metadata or client association."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=2000)
    avatar: str | None = Field(None, max_length=4096, description="Avatar URL.")
    metadata: dict[str, Any] | None = None
    client_identifier: str | None = Field(None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("name", "avatar", "metadata", "client_identifier")):
            raise ValueError("Provide at least one user field to update")
        return self


class CoassembleListCoursesConfig(_OwnerFilters):
    """List courses with owner, client and title filters."""
    operation: Literal["list_courses"] = Field("list_courses", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, min_length=1, max_length=2000)


class CoassembleGetCourseConfig(_Course):
    """Get a course with its sections and screens."""
    operation: Literal["get_course"] = Field("get_course", json_schema_extra={"ui:hidden": True})
    identifier: str | None = Field(None, min_length=1, max_length=512)
    client_identifier: str | None = Field(None, min_length=1, max_length=512)


class CoassembleDeleteCourseConfig(_Course):
    """Soft-delete a course. Restore it with restore_course."""
    operation: Literal["delete_course"] = Field("delete_course", json_schema_extra={"ui:hidden": True})


class CoassembleRestoreCourseConfig(_Course):
    """Restore a soft-deleted course."""
    operation: Literal["restore_course"] = Field("restore_course", json_schema_extra={"ui:hidden": True})


class CoassemblePublishCourseConfig(_Course):
    """Publish the current draft of a course."""
    operation: Literal["publish_course"] = Field("publish_course", json_schema_extra={"ui:hidden": True})


class CoassembleDuplicateCourseConfig(_Course):
    """Duplicate a course, optionally overriding its owner and client."""
    operation: Literal["duplicate_course"] = Field("duplicate_course", json_schema_extra={"ui:hidden": True})
    identifier: str | None = Field(None, min_length=1, max_length=512)
    client_identifier: str | None = Field(None, min_length=1, max_length=512)


class CoassembleListCollectionsConfig(_OwnerFilters):
    """List collections with optional owner and client filters."""
    operation: Literal["list_collections"] = Field("list_collections", json_schema_extra={"ui:hidden": True})


class CoassembleGetCollectionConfig(_Collection):
    """Get one collection and its courses."""
    operation: Literal["get_collection"] = Field("get_collection", json_schema_extra={"ui:hidden": True})


class CoassembleCreateCollectionConfig(_CollectionFields):
    """Create a collection with an ordered list of initial courses."""
    operation: Literal["create_collection"] = Field("create_collection", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=2000)
    course_ids: list[int] | None = Field(None, max_length=1000, description="Initial course IDs in display order.")


class CoassembleUpdateCollectionConfig(_CollectionFields):
    """Update a collection and its share-link access settings."""
    operation: Literal["update_collection"] = Field("update_collection", json_schema_extra={"ui:hidden": True})
    collection_id: int = Field(..., ge=1)

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "collection_id"}):
            raise ValueError("Provide at least one collection field to update")
        return self


class CoassembleDeleteCollectionConfig(_Collection):
    """Soft-delete a collection. Restore it with restore_collection."""
    operation: Literal["delete_collection"] = Field("delete_collection", json_schema_extra={"ui:hidden": True})


class CoassembleRestoreCollectionConfig(_Collection):
    """Restore a soft-deleted collection."""
    operation: Literal["restore_collection"] = Field("restore_collection", json_schema_extra={"ui:hidden": True})


class CoassembleListTrackingsConfig(_Page):
    """List learner tracking records for one course."""
    operation: Literal["list_trackings"] = Field("list_trackings", json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., ge=1)
    identifier: str | None = Field(None, min_length=1, max_length=512)
    client_identifier: str | None = Field(None, min_length=1, max_length=512)
    start: str | None = Field(None, description="Earliest tracking timestamp, ISO 8601.")
    end: str | None = Field(None, description="Latest tracking timestamp, ISO 8601.")


class CoassembleGetTrackingConfig(_Input):
    """Get one learner tracking record by tracking ID."""
    operation: Literal["get_tracking"] = Field("get_tracking", json_schema_extra={"ui:hidden": True})
    tracking_id: int = Field(..., ge=1)


class CoassembleListThemesConfig(_Input):
    """List available workspace themes up to the requested limit."""
    operation: Literal["list_themes"] = Field("list_themes", json_schema_extra={"ui:hidden": True})
    length: int = Field(100, ge=1, le=100)


class CoassembleGetThemeConfig(_Input):
    """Get the settings of one workspace theme."""
    operation: Literal["get_theme"] = Field("get_theme", json_schema_extra={"ui:hidden": True})
    theme_id: int = Field(..., ge=1)


CoassembleOperation = Annotated[Union[
    CoassembleListClientsConfig,
    CoassembleGetClientConfig,
    CoassembleUpdateClientConfig,
    CoassembleListUsersConfig,
    CoassembleGetUserConfig,
    CoassembleUpdateUserConfig,
    CoassembleListCoursesConfig,
    CoassembleGetCourseConfig,
    CoassembleDeleteCourseConfig,
    CoassembleRestoreCourseConfig,
    CoassemblePublishCourseConfig,
    CoassembleDuplicateCourseConfig,
    CoassembleListCollectionsConfig,
    CoassembleGetCollectionConfig,
    CoassembleCreateCollectionConfig,
    CoassembleUpdateCollectionConfig,
    CoassembleDeleteCollectionConfig,
    CoassembleRestoreCollectionConfig,
    CoassembleListTrackingsConfig,
    CoassembleGetTrackingConfig,
    CoassembleListThemesConfig,
    CoassembleGetThemeConfig,
], Field(discriminator="operation")]


class CoassembleNodeConfig(NodeConfig[CoassembleOperation, CoassembleAPIKeyCredential]):
    model_config = ConfigDict(title="Coassemble Node Configuration", hide_input_in_errors=True)


ROUTES = {
    "list_clients": ("GET", "/clients"),
    "get_client": ("GET", "/client/{identifier}"),
    "update_client": ("PUT", "/client/{identifier}"),
    "list_users": ("GET", "/users"),
    "get_user": ("GET", "/user/{identifier}"),
    "update_user": ("PUT", "/user/{identifier}"),
    "list_courses": ("GET", "/courses"),
    "get_course": ("GET", "/courses/{course_id}"),
    "delete_course": ("DELETE", "/course/{course_id}"),
    "restore_course": ("POST", "/course/{course_id}/restore"),
    "publish_course": ("POST", "/course/{course_id}/publish"),
    "duplicate_course": ("POST", "/course/{course_id}/duplicate"),
    "list_collections": ("GET", "/collections"),
    "get_collection": ("GET", "/collections/{collection_id}"),
    "create_collection": ("POST", "/collection"),
    "update_collection": ("PUT", "/collection/{collection_id}"),
    "delete_collection": ("DELETE", "/collection/{collection_id}"),
    "restore_collection": ("POST", "/collection/{collection_id}/restore"),
    "list_trackings": ("GET", "/trackings"),
    "get_tracking": ("GET", "/tracking/{tracking_id}"),
    "list_themes": ("GET", "/themes"),
    "get_theme": ("GET", "/themes/{theme_id}"),
}

WIRE_NAMES = {"client_identifier": "clientIdentifier", "theme_id": "themeId", "course_ids": "courseIds"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class CoassembleNode(WorkflowNode):
    integration_type = "automation-coassemble"
    connection_evidence = ConnectionEvidence(noun="courses", operation="list_courses", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return CoassembleNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Coassemble API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        values = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        if config.operation == "list_trackings":
            values["id"] = values.pop("course_id")
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()} if method == "GET" else None
        body = values if method in {"POST", "PUT"} and values else None
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": secret, "Accept": "application/json"},
                    params=params, json=body)
        except (httpx.HTTPError, OSError):
            # Never include transport exceptions: they may embed request secrets.
            raise ValueError("Coassemble request did not complete; inspect the resource before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Coassemble rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("message") or error.get("error") or message
            except ValueError:
                pass
            return {"success": False, "status": "error", "http_status": response.status_code,
                    "error": _redact(message, secret), "operation": config.operation}
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError("Coassemble returned an invalid JSON response") from None
        boolean_write = config.operation in {"delete_course", "restore_course", "delete_collection", "restore_collection"}
        if boolean_write and not isinstance(data, bool):
            raise ValueError("Coassemble returned an invalid write acknowledgement")
        if method != "GET" and not boolean_write and not isinstance(data, dict):
            raise ValueError("Coassemble returned an invalid write response")
        if config.operation.startswith("list_") and not isinstance(data, list):
            raise ValueError("Coassemble returned an invalid list response")
        if config.operation.startswith("get_") and not isinstance(data, dict):
            raise ValueError("Coassemble returned an invalid resource response")
        if isinstance(data, dict) and (data.get("success") is False or data.get("error")):
            return {"success": False, "status": "error", "error": _redact(data, secret), "operation": config.operation}
        result = {"success": True, "status": "success", "operation": config.operation,
                  "http_status": response.status_code, "data": _redact(data, secret)}
        if isinstance(config, _Page):
            # A full page is only a reason to try the next page, not a total count.
            result["pagination"] = {"page": config.page, "length": config.length,
                "page_full": len(data) >= config.length,
                "next_page": config.page + 1 if len(data) >= config.length else None}
        if method != "GET":
            result["acknowledged"] = data is True if isinstance(data, bool) else True
            if data is False:
                result.update(success=False, status="unconfirmed",
                              message="Coassemble returned false; the write was not acknowledged.")
        await self.emit(result)
        return result
