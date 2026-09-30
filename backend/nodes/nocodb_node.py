"""NocoDB v3 workflow actions for records and base metadata.

The operation catalogue follows https://nocodb.com/apis/v3/swagger-v3.json.
NocoDB authenticates API requests with the ``xc-token`` header.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    create_model,
    field_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


class NocoDBTokenCredential(BaseModel):
    credential_type: Literal["nocodb_api_token"] = Field(
        "nocodb_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="A NocoDB API token with access to the bases used by this workflow.",
        json_schema_extra={"ui:widget": "password"},
    )
    base_url: str = Field(
        "https://app.nocodb.com",
        title="NocoDB URL",
        description="Your NocoDB Cloud or self-hosted HTTPS origin (no /api/v3 suffix).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.nocodb.com/account/tokens",
            "x-credential-instructions": "Create a scoped API token under Account settings → API Tokens. Grant read/write access for the operations you use.",
        }
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value.rstrip("/"))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise ValueError(
                "NocoDB URL must be an HTTPS origin without a path or query"
            )
        return value.rstrip("/")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    fields: str = ""
    body: str = ""
    query: bool = False


# Field names are the path parameters, followed by a JSON body or supported query
# parameters. Metadata bodies are passed through as documented by NocoDB so new
# field/view types remain usable without waiting for a NoClick release.
OPERATIONS: Dict[str, Operation] = {
    "list_workspaces": Operation("GET", "/meta/workspaces", "Workspace"),
    "get_workspace": Operation(
        "GET", "/meta/workspaces/{workspace_id}", "Workspace", "workspace_id"
    ),
    "create_workspace": Operation(
        "POST", "/meta/workspaces", "Workspace", body="payload"
    ),
    "update_workspace": Operation(
        "PATCH",
        "/meta/workspaces/{workspace_id}",
        "Workspace",
        "workspace_id",
        "payload",
    ),
    "delete_workspace": Operation(
        "DELETE", "/meta/workspaces/{workspace_id}", "Workspace", "workspace_id"
    ),
    "list_bases": Operation(
        "GET", "/meta/workspaces/{workspace_id}/bases", "Base", "workspace_id"
    ),
    "get_base": Operation("GET", "/meta/bases/{base_id}", "Base", "base_id"),
    "create_base": Operation(
        "POST",
        "/meta/workspaces/{workspace_id}/bases",
        "Base",
        "workspace_id",
        "payload",
    ),
    "update_base": Operation(
        "PATCH", "/meta/bases/{base_id}", "Base", "base_id", "payload"
    ),
    "delete_base": Operation("DELETE", "/meta/bases/{base_id}", "Base", "base_id"),
    "list_tables": Operation("GET", "/meta/bases/{base_id}/tables", "Table", "base_id"),
    "get_table": Operation(
        "GET", "/meta/bases/{base_id}/tables/{table_id}", "Table", "base_id table_id"
    ),
    "create_table": Operation(
        "POST", "/meta/bases/{base_id}/tables", "Table", "base_id", "payload"
    ),
    "update_table": Operation(
        "PATCH",
        "/meta/bases/{base_id}/tables/{table_id}",
        "Table",
        "base_id table_id",
        "payload",
    ),
    "delete_table": Operation(
        "DELETE", "/meta/bases/{base_id}/tables/{table_id}", "Table", "base_id table_id"
    ),
    "get_field": Operation(
        "GET", "/meta/bases/{base_id}/fields/{field_id}", "Field", "base_id field_id"
    ),
    "create_field": Operation(
        "POST",
        "/meta/bases/{base_id}/tables/{table_id}/fields",
        "Field",
        "base_id table_id",
        "payload",
    ),
    "update_field": Operation(
        "PATCH",
        "/meta/bases/{base_id}/fields/{field_id}",
        "Field",
        "base_id field_id",
        "payload",
    ),
    "delete_field": Operation(
        "DELETE", "/meta/bases/{base_id}/fields/{field_id}", "Field", "base_id field_id"
    ),
    "list_views": Operation(
        "GET",
        "/meta/bases/{base_id}/tables/{table_id}/views",
        "View",
        "base_id table_id",
    ),
    "get_view": Operation(
        "GET", "/meta/bases/{base_id}/views/{view_id}", "View", "base_id view_id"
    ),
    "create_view": Operation(
        "POST",
        "/meta/bases/{base_id}/tables/{table_id}/views",
        "View",
        "base_id table_id",
        "payload",
    ),
    "update_view": Operation(
        "PATCH",
        "/meta/bases/{base_id}/views/{view_id}",
        "View",
        "base_id view_id",
        "payload",
    ),
    "delete_view": Operation(
        "DELETE", "/meta/bases/{base_id}/views/{view_id}", "View", "base_id view_id"
    ),
    "list_records": Operation(
        "GET",
        "/data/{base_id}/{table_id}/records",
        "Record",
        "base_id table_id",
        query=True,
    ),
    "get_record": Operation(
        "GET",
        "/data/{base_id}/{table_id}/records/{record_id}",
        "Record",
        "base_id table_id record_id",
    ),
    "count_records": Operation(
        "GET",
        "/data/{base_id}/{table_id}/count",
        "Record",
        "base_id table_id",
        query=True,
    ),
    "create_records": Operation(
        "POST",
        "/data/{base_id}/{table_id}/records",
        "Record",
        "base_id table_id",
        "records",
    ),
    "update_records": Operation(
        "PATCH",
        "/data/{base_id}/{table_id}/records",
        "Record",
        "base_id table_id",
        "records",
    ),
    "delete_records": Operation(
        "DELETE",
        "/data/{base_id}/{table_id}/records",
        "Record",
        "base_id table_id",
        "records",
    ),
    "upsert_records": Operation(
        "POST",
        "/data/{base_id}/{table_id}/records/upsert",
        "Record",
        "base_id table_id",
        "payload",
    ),
    "list_links": Operation(
        "GET",
        "/data/{base_id}/{table_id}/links/{link_field_id}/{record_id}",
        "Link",
        "base_id table_id link_field_id record_id",
        query=True,
    ),
    "add_links": Operation(
        "POST",
        "/data/{base_id}/{table_id}/links/{link_field_id}/{record_id}",
        "Link",
        "base_id table_id link_field_id record_id",
        "payload",
    ),
    "delete_links": Operation(
        "DELETE",
        "/data/{base_id}/{table_id}/links/{link_field_id}/{record_id}",
        "Link",
        "base_id table_id link_field_id record_id",
        "payload",
    ),
    "list_hooks": Operation(
        "GET",
        "/meta/bases/{base_id}/tables/{table_id}/hooks",
        "Webhook",
        "base_id table_id",
    ),
    "get_hook": Operation(
        "GET", "/meta/bases/{base_id}/hooks/{hook_id}", "Webhook", "base_id hook_id"
    ),
    "create_hook": Operation(
        "POST",
        "/meta/bases/{base_id}/tables/{table_id}/hooks",
        "Webhook",
        "base_id table_id",
        "payload",
    ),
    "update_hook": Operation(
        "PATCH",
        "/meta/bases/{base_id}/hooks/{hook_id}",
        "Webhook",
        "base_id hook_id",
        "payload",
    ),
    "delete_hook": Operation(
        "DELETE", "/meta/bases/{base_id}/hooks/{hook_id}", "Webhook", "base_id hook_id"
    ),
    "list_comments": Operation(
        "GET",
        "/meta/bases/{base_id}/tables/{table_id}/records/{record_id}/comments",
        "Comment",
        "base_id table_id record_id",
    ),
    "create_comment": Operation(
        "POST",
        "/meta/bases/{base_id}/tables/{table_id}/records/{record_id}/comments",
        "Comment",
        "base_id table_id record_id",
        "payload",
    ),
    "update_comment": Operation(
        "PATCH",
        "/meta/bases/{base_id}/comments/{comment_id}",
        "Comment",
        "base_id comment_id",
        "payload",
    ),
    "delete_comment": Operation(
        "DELETE",
        "/meta/bases/{base_id}/comments/{comment_id}",
        "Comment",
        "base_id comment_id",
    ),
    "resolve_comment": Operation(
        "POST",
        "/meta/bases/{base_id}/comments/{comment_id}/resolve",
        "Comment",
        "base_id comment_id",
    ),
}


def _id_field(name: str):
    title = name.replace("_", " ").title()
    dynamic = {
        "field_name": name,
        "placeholder": f"Select a {title.lower()}…",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": f"Or paste a {title.lower()}",
    }
    if name == "table_id":
        dynamic["depends_on"] = "base_id"
    elif name in ("field_id", "view_id", "hook_id"):
        dynamic["depends_on"] = "table_id"
    return (
        str,
        Field(..., title=title, json_schema_extra={"x-dynamic-options": dynamic}),
    )


def _make_operation_model(name: str, spec: Operation):
    title = name.replace("_", " ").title()
    definitions: Dict[str, Any] = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=title,
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": spec.category,
                    "x-is-trigger": False,
                    "x-display-name": title,
                },
            ),
        )
    }
    for field_name in spec.fields.split():
        definitions[field_name] = _id_field(field_name)
    if spec.body:
        label = "Record Data" if spec.body == "records" else "JSON Body"
        description = (
            'JSON object or array of objects. Create: {"fields":{"Title":"Example"}}; '
            "update/delete: include each record's id."
            if spec.body == "records"
            else "JSON request body in NocoDB v3 API format."
        )
        definitions[spec.body] = (
            str,
            Field(
                ...,
                title=label,
                description=description,
                json_schema_extra={"ui:widget": "textarea"},
            ),
        )
    if spec.query:
        definitions["where"] = (
            Optional[str],
            Field(None, title="Where", description="NocoDB filter expression."),
        )
        definitions["sort"] = (
            Optional[str],
            Field(None, title="Sort", description="NocoDB sort expression."),
        )
        definitions["page_size"] = (
            Optional[int],
            Field(None, title="Page Size", ge=1, le=1000),
        )
        definitions["page"] = (Optional[int], Field(None, title="Page", ge=1))
        if name == "list_records":
            definitions["view_id"] = (Optional[str], Field(None, title="View ID"))
            definitions["fields"] = (
                Optional[str],
                Field(
                    None,
                    title="Fields",
                    description="Comma separated field names or IDs.",
                ),
            )
    return create_model(
        f"NocoDB{''.join(s.title() for s in name.split('_'))}Config",
        __config__=ConfigDict(title=title),
        **definitions,
    )


CONFIG_MODELS = tuple(
    _make_operation_model(name, spec) for name, spec in OPERATIONS.items()
)
NocoDBConfig = Annotated[Union[CONFIG_MODELS], Discriminator("operation")]


class NocoDBNodeConfig(NodeConfig[NocoDBConfig, NocoDBTokenCredential]):
    credentials: NocoDBTokenCredential = Field(..., description="NocoDB API token")


class NocoDBNode(WorkflowNode):
    """Read/write NocoDB records and administer workspaces, bases, tables and views."""

    connection_evidence = ConnectionEvidence(
        field="workspace_id", noun="workspaces", operation="list_workspaces"
    )
    edit_examples = [
        "Create a row in my NocoDB Customers table",
        "Find records in the Orders table that need follow up",
        "Update a NocoDB record and read it back",
    ]

    @classmethod
    def get_config_model(cls):
        return NocoDBNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ):
        context = context or {}
        endpoints = {
            "workspace_id": "/meta/workspaces",
            "table_id": "/meta/bases/{base_id}/tables",
            "view_id": "/meta/bases/{base_id}/tables/{table_id}/views",
            "hook_id": "/meta/bases/{base_id}/tables/{table_id}/hooks",
        }
        if field_name == "base_id":
            workspaces = await cls.load_field_options("workspace_id", credential_data)
            result = []
            for workspace in workspaces:
                result.extend(
                    await cls._load_options(
                        credential_data,
                        f"/meta/workspaces/{quote(workspace['value'], safe='')}/bases",
                    )
                )
            return result
        if field_name in ("field_id", "record_id"):
            base_id, table_id = context.get("base_id"), context.get("table_id")
            if not base_id or not table_id:
                return []
            base, table = quote(str(base_id), safe=""), quote(str(table_id), safe="")
            if field_name == "field_id":
                data = await cls._load_data(
                    credential_data, f"/meta/bases/{base}/tables/{table}"
                )
                items = data.get("fields", [])
            else:
                data = await cls._load_data(
                    credential_data, f"/data/{base}/{table}/records?pageSize=100"
                )
                items = data.get("records", [])
            return [
                {
                    "value": str(item["id"]),
                    "label": str(
                        item.get("title")
                        or item.get("fields", {}).get("Title")
                        or item["id"]
                    ),
                }
                for item in items
                if isinstance(item, dict) and item.get("id") is not None
            ]
        path = endpoints.get(field_name)
        if not path:
            return []
        for param in re.findall(r"\{(\w+)\}", path):
            if not context.get(param):
                return []
            path = path.replace("{" + param + "}", quote(str(context[param]), safe=""))
        return await cls._load_options(credential_data, path)

    @classmethod
    async def _load_options(cls, credential_data: Dict[str, Any], path: str):
        data = await cls._load_data(credential_data, path)
        items = data.get("list", []) if isinstance(data, dict) else data
        return [
            {
                "value": str(item["id"]),
                "label": str(item.get("title") or item.get("name") or item["id"]),
            }
            for item in items
            if isinstance(item, dict) and item.get("id")
        ]

    @classmethod
    async def _load_data(cls, credential_data: Dict[str, Any], path: str):
        url = f"{credential_data.get('base_url', 'https://app.nocodb.com').rstrip('/')}/api/v3{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                url, headers={"xc-token": credential_data["api_token"]}
            )
        response.raise_for_status()
        return response.json()

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, NocoDBNodeConfig):
            raise ValueError("NocoDB node requires a valid configuration")
        credentials = self.config.credentials
        config = self.config.config
        operation = config.operation
        spec = OPERATIONS[operation]
        path = spec.path
        for name in re.findall(r"\{(\w+)\}", path):
            path = path.replace(
                "{" + name + "}", quote(str(getattr(config, name)), safe="")
            )
        params: Dict[str, Any] = {}
        if spec.query:
            for key in ("where", "sort", "page", "page_size", "view_id", "fields"):
                value = getattr(config, key, None)
                if value is not None:
                    params[
                        {"page_size": "pageSize", "view_id": "viewId"}.get(key, key)
                    ] = value
        body = None
        if spec.body:
            try:
                body = json.loads(getattr(config, spec.body))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{spec.body} must be valid JSON: {exc.msg}") from exc
            if not isinstance(body, (dict, list)):
                raise ValueError(f"{spec.body} must be a JSON object or array")
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                spec.method,
                f"{credentials.base_url}/api/v3{path}",
                headers={"xc-token": credentials.api_token},
                params=params or None,
                json=body,
            )
        elapsed = round((time.monotonic() - start) * 1000, 2)
        try:
            data = response.json() if response.content else {"success": True}
        except ValueError:
            data = {"text": response.text}
        if response.is_error:
            message = (
                (
                    data.get("msg")
                    or data.get("message")
                    or data.get("error")
                    or str(data)
                )
                if isinstance(data, dict)
                else str(data)
            )
            return {
                "status": "error",
                "action": operation,
                "error": message,
                "status_code": response.status_code,
                "timing_ms": {"api_request": elapsed},
            }
        return {
            "status": "success",
            "action": operation,
            "data": data,
            "status_code": response.status_code,
            "timing_ms": {"api_request": elapsed},
        }
