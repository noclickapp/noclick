"""ApptiveGrid REST API 2.4.1348: account, spaces, grids and entries.

Provider contract: https://raw.githubusercontent.com/ApptiveGrid/docs/main/openapi.json
API keys use Basic authentication; each operation issues exactly one request.
Collections return one page with the provider's pagination metadata intact.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.apptivegrid.de"
CREDENTIAL_TYPE = "apptivegrid_api_key"


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Paste a single ApptiveGrid resource ID, without a URL")
    return value


class ApptivegridAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Apptivegrid API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.apptivegrid.de/settings/credentials",
            "x-credential-instructions": "In Profile & Settings → API credentials, create a key. Paste its key and the secret shown once. Use Admin for writes or Read only for reads. Paste your user ID from the Location header of GET /api/users/me with Basic authentication. See https://docs.apptivegrid.de/api/authentifizierung.html.",
        },
    )
    credential_type: Literal["apptivegrid_api_key"] = Field(
        "apptivegrid_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    api_secret: str = Field(
        ...,
        title="API secret",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    user_id: str = Field(
        ...,
        title="User ID",
        description="Your account ID from /api/users/me's Location header, for example 64f1a2b3c4d5e6f708091a2b.",
    )
    _user = field_validator("user_id", mode="before")(_identifier)

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key or secret")
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError(
                "Paste the key or secret without a Basic prefix, spaces or colon"
            )
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Space(_Input):
    space_id: str = Field(..., title="Space ID")
    _space = field_validator("space_id", mode="before")(_identifier)


class _Grid(_Space):
    grid_id: str = Field(..., title="Grid ID")
    _grid = field_validator("grid_id", mode="before")(_identifier)


class _Entity(_Grid):
    entity_id: str = Field(..., title="Entry ID")
    _entity = field_validator("entity_id", mode="before")(_identifier)


class _Page(_Input):
    page_index: int = Field(
        1,
        ge=1,
        le=1000000,
        title="Page index",
        description="One-based page; collections return one page at a time.",
    )
    page_size: int = Field(100, ge=1, le=300, title="Page size")


Layout = Literal["field", "indexed", "keyAndField", "key", "property"]


class _Values(_Input):
    values: dict[str, Any] = Field(
        ...,
        title="Entry values",
        description='JSON object matching the grid schema. For indexed layout use {"fields": ["value", null]}; otherwise use field IDs, keys or names as selected by layout.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )

    @field_validator("values")
    @classmethod
    def finite_json(cls, value):
        try:
            if len(json.dumps(value, allow_nan=False)) > 1000000:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise ValueError("Entry values must be a JSON object under 1 MB") from None
        return value


class _GridList(_Space, _Page):
    pass


class _EntryList(_Grid, _Page):
    pass


class _CreateEntry(_Grid, _Values):
    pass


class _UpdateEntry(_Entity, _Values):
    pass


class ApptivegridGetUserConfig(_Input):
    """Get user."""

    operation: Literal["get_user"] = Field(
        "get_user", json_schema_extra={"ui:hidden": True, "x-display-name": "Get User"}
    )


class ApptivegridListSpacesConfig(_Page):
    """List spaces."""

    operation: Literal["list_spaces"] = Field(
        "list_spaces",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Spaces"},
    )
    matching: str | None = Field(
        None, description="Provider key-value matching expression."
    )


class ApptivegridCreateSpaceConfig(_Input):
    """Create space."""

    operation: Literal["create_space"] = Field(
        "create_space",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Create Space"},
    )
    name: str = Field(..., min_length=1, max_length=500)


class ApptivegridGetSpaceConfig(_Space):
    """Get space."""

    operation: Literal["get_space"] = Field(
        "get_space",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Space"},
    )


class ApptivegridRenameSpaceConfig(_Space):
    """Rename space."""

    operation: Literal["rename_space"] = Field(
        "rename_space",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Rename Space"},
    )
    name: str = Field(..., min_length=1, max_length=500)


class ApptivegridDeleteSpaceConfig(_Space):
    """Delete a space and its contents."""

    operation: Literal["delete_space"] = Field(
        "delete_space",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Space"},
    )


class ApptivegridListGridsConfig(_GridList):
    """List grids."""

    operation: Literal["list_grids"] = Field(
        "list_grids",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Grids"},
    )
    grid_type: Literal["persistent", "virtual"] | None = None


class ApptivegridCreateGridConfig(_Space):
    """Create grid."""

    operation: Literal["create_grid"] = Field(
        "create_grid",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Create Grid"},
    )
    name: str = Field(..., min_length=1, max_length=500)
    create_view: bool = True


class ApptivegridGetGridConfig(_Grid):
    """Get grid."""

    operation: Literal["get_grid"] = Field(
        "get_grid", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Grid"}
    )


class ApptivegridRenameGridConfig(_Grid):
    """Rename grid."""

    operation: Literal["rename_grid"] = Field(
        "rename_grid",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Rename Grid"},
    )
    name: str = Field(..., min_length=1, max_length=500)


class ApptivegridDeleteGridConfig(_Grid):
    """Delete a grid and its contents."""

    operation: Literal["delete_grid"] = Field(
        "delete_grid",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Grid"},
    )


class ApptivegridGetGridSchemaConfig(_Grid):
    """Get grid schema."""

    operation: Literal["get_grid_schema"] = Field(
        "get_grid_schema",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Grid Schema"},
    )


class ApptivegridListEntriesConfig(_EntryList):
    """List entries."""

    operation: Literal["list_entries"] = Field(
        "list_entries",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Entries"},
    )
    layout: Layout = "field"
    view_id: str | None = None
    filter: dict[str, Any] | None = Field(
        None, description="Provider filter object; NoClick URL-encodes its JSON."
    )
    sorting: dict[str, Any] | list[dict[str, Any]] | None = Field(
        None, description="Provider sorting JSON; ascending or descending $order."
    )
    compose: bool | None = None


class ApptivegridCreateEntryConfig(_CreateEntry):
    """Create entry."""

    operation: Literal["create_entry"] = Field(
        "create_entry",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Create Entry"},
    )
    layout: Layout = "field"
    view_id: str | None = None


class ApptivegridGetEntryConfig(_Entity):
    """Get entry."""

    operation: Literal["get_entry"] = Field(
        "get_entry",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Entry"},
    )
    layout: Layout = "field"
    view_id: str | None = None


class ApptivegridUpdateEntryConfig(_UpdateEntry):
    """Update supplied fields; omitted fields are preserved in keyed layouts."""

    operation: Literal["update_entry"] = Field(
        "update_entry",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Update Entry"},
    )
    layout: Layout = "field"
    view_id: str | None = None


class ApptivegridPartialUpdateEntryConfig(_UpdateEntry):
    """Update fields by ID or key (the provider always uses keyAndField layout)."""

    operation: Literal["partial_update_entry"] = Field(
        "partial_update_entry",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Partial Update Entry"},
    )


class ApptivegridDeleteEntryConfig(_Entity):
    """Delete entry."""

    operation: Literal["delete_entry"] = Field(
        "delete_entry",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Entry"},
    )


class ApptivegridListViewsConfig(_EntryList):
    """List views."""

    operation: Literal["list_views"] = Field(
        "list_views",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Views"},
    )
    nested: bool | None = None


class ApptivegridListFormsConfig(_EntryList):
    """List forms."""

    operation: Literal["list_forms"] = Field(
        "list_forms",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Forms"},
    )


ApptivegridOperation = Annotated[
    Union[
        ApptivegridGetUserConfig,
        ApptivegridListSpacesConfig,
        ApptivegridCreateSpaceConfig,
        ApptivegridGetSpaceConfig,
        ApptivegridRenameSpaceConfig,
        ApptivegridDeleteSpaceConfig,
        ApptivegridListGridsConfig,
        ApptivegridCreateGridConfig,
        ApptivegridGetGridConfig,
        ApptivegridRenameGridConfig,
        ApptivegridDeleteGridConfig,
        ApptivegridGetGridSchemaConfig,
        ApptivegridListEntriesConfig,
        ApptivegridCreateEntryConfig,
        ApptivegridGetEntryConfig,
        ApptivegridUpdateEntryConfig,
        ApptivegridPartialUpdateEntryConfig,
        ApptivegridDeleteEntryConfig,
        ApptivegridListViewsConfig,
        ApptivegridListFormsConfig,
    ],
    Field(discriminator="operation"),
]


class ApptivegridNodeConfig(
    NodeConfig[ApptivegridOperation, ApptivegridAPIKeyCredential]
):
    pass


ROUTES = {
    "get_user": ("GET", ""),
    "list_spaces": ("GET", "/spaces"),
    "create_space": ("POST", "/spaces"),
    "get_space": ("GET", "/spaces/{space_id}"),
    "rename_space": ("POST", "/spaces/{space_id}/Rename"),
    "delete_space": ("DELETE", "/spaces/{space_id}"),
    "list_grids": ("GET", "/spaces/{space_id}/grids"),
    "create_grid": ("POST", "/spaces/{space_id}/grids"),
    "get_grid": ("GET", "/spaces/{space_id}/grids/{grid_id}"),
    "rename_grid": ("POST", "/spaces/{space_id}/grids/{grid_id}/Rename"),
    "delete_grid": ("DELETE", "/spaces/{space_id}/grids/{grid_id}"),
    "get_grid_schema": ("GET", "/spaces/{space_id}/grids/{grid_id}/schema"),
    "list_entries": ("GET", "/spaces/{space_id}/grids/{grid_id}/entities"),
    "create_entry": ("POST", "/spaces/{space_id}/grids/{grid_id}/entities"),
    "get_entry": ("GET", "/spaces/{space_id}/grids/{grid_id}/entities/{entity_id}"),
    "update_entry": ("PUT", "/spaces/{space_id}/grids/{grid_id}/entities/{entity_id}"),
    "partial_update_entry": (
        "POST",
        "/spaces/{space_id}/grids/{grid_id}/entities/{entity_id}/update",
    ),
    "delete_entry": (
        "DELETE",
        "/spaces/{space_id}/grids/{grid_id}/entities/{entity_id}",
    ),
    "list_views": ("GET", "/spaces/{space_id}/grids/{grid_id}/sviews"),
    "list_forms": ("GET", "/spaces/{space_id}/grids/{grid_id}/forms"),
}


def _redact(value, credential):
    secrets = (
        credential.api_key,
        credential.api_secret,
        base64.b64encode(
            f"{credential.api_key}:{credential.api_secret}".encode()
        ).decode(),
    )
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, dict):
        return {
            _redact(key, credential): _redact(item, credential)
            for key, item in value.items()
        }
    return value


class ApptivegridNode(WorkflowNode):
    integration_type = "automation-apptivegrid"
    connection_evidence = ConnectionEvidence(
        noun="account",
        identity_operation="get_user",
        label_keys=("name", "email", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return ApptivegridNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Apptivegrid API key and secret")
        credential = self.config.credentials
        op = self.config.config
        method, suffix = ROUTES[op.operation]
        fields = op.model_dump()
        route = (
            "/api/users/" + _identifier(credential.user_id) + suffix.format(**fields)
        )
        query = {}
        aliases = {
            "page_index": "pageIndex",
            "page_size": "pageSize",
            "view_id": "viewId",
            "grid_type": "type",
        }
        for field in (
            "page_index",
            "page_size",
            "matching",
            "grid_type",
            "view_id",
            "layout",
            "filter",
            "sorting",
            "compose",
            "nested",
        ):
            value = getattr(op, field, None)
            if value is not None:
                if field in {"filter", "sorting"}:
                    value = json.dumps(value, separators=(",", ":"), allow_nan=False)
                elif isinstance(value, bool):
                    value = "true" if value else "false"
                query[aliases.get(field, field)] = value
        body = None
        if hasattr(op, "name"):
            body = {"name": op.name}
            if op.operation == "create_grid":
                body["createView"] = op.create_view
        if hasattr(op, "values"):
            body = op.values
            if (
                op.operation != "partial_update_entry"
                and op.layout == "indexed"
                and (set(body) != {"fields"} or not isinstance(body["fields"], list))
            ):
                raise ValueError(
                    'Indexed layout requires {"fields": [...]} in grid field order'
                )
        encoded = base64.b64encode(
            f"{credential.api_key}:{credential.api_secret}".encode()
        ).decode()
        headers = {
            "Authorization": "Basic " + encoded,
            "Accept": "application/vnd.apptivegrid.hal;version=2",
        }
        expected = (
            201
            if op.operation in {"create_space", "create_grid", "create_entry"}
            else 200
        )
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + route,
                    headers=headers,
                    params=query,
                    **({"json": body} if body is not None else {}),
                )
        except (httpx.HTTPError, OSError):
            return {
                "status": "error",
                "action": op.operation,
                "message": "Apptivegrid request did not complete; inspect the resource before retrying a write",
                "write_outcome": "unverified" if method != "GET" else None,
            }
        if response.status_code != expected:
            return _redact(
                {
                    "status": "error",
                    "action": op.operation,
                    "http_status": response.status_code,
                    "message": response.text[:2000]
                    or "Apptivegrid rejected the request",
                    "write_outcome": "unverified" if method != "GET" else None,
                },
                credential,
            )
        if len(response.content) > 10 * 1024 * 1024:
            raise ValueError("Apptivegrid response exceeds 10 MB; use a smaller page")
        if expected == 201:
            # These endpoints explicitly return text/plain, not JSON. Do not
            # follow Location: it is an acknowledgement, not a second operation.
            data = {
                "location": response.headers.get("location"),
                "message": response.text,
            }
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Apptivegrid returned invalid JSON") from None
            if isinstance(data, dict) and (data.get("error") or data.get("errors")):
                return _redact(
                    {"status": "error", "action": op.operation, "data": data},
                    credential,
                )
            if op.operation.startswith("list_") and (
                not isinstance(data, dict) or not isinstance(data.get("items"), list)
            ):
                raise ValueError("Apptivegrid returned an invalid collection")
        output = {
            "status": "success",
            "action": op.operation,
            "http_status": response.status_code,
            "data": data,
        }
        if op.operation.startswith("list_"):
            page, pages = data.get("page"), data.get("numberOfPages")
            output["next_page_index"] = (
                page + 1
                if type(page) is int
                and type(pages) is int
                and page < pages
                and data["items"]
                else None
            )
        return _redact(output, credential)
