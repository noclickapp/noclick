"""Directus Content API node for self-hosted and cloud projects.

Directus creates REST endpoints for each collection. This node combines those
content endpoints with the schema, file, and folder APIs. It uses a static user
token, which Directus documents for server-to-server integrations.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class DirectusStaticTokenCredential(BaseModel):
    """A static token from the Directus Data Studio user's settings."""

    credential_type: Literal["directus_static_token"] = Field(
        "directus_static_token", json_schema_extra={"ui:hidden": True}
    )
    instance_url: str = Field(
        ...,
        title="Directus URL",
        description="Root URL of your Directus project, for example https://cms.example.com",
        json_schema_extra={"placeholder": "https://cms.example.com"},
    )
    static_token: str = Field(
        ...,
        title="Static Access Token",
        description="Create a static token in Data Studio > User Directory > your user",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Directus Static Token",
        json_schema_extra={
            "x-credential-url": "https://directus.io/docs/guides/authentication/tokens-cookies"
        }
    )


# operation, label, category, method, path, visible fields
_SPECS = [
    ("get_current_user", "Get Current User", "Account", "GET", "/users/me", ()),
    (
        "list_users",
        "List Users",
        "Account",
        "GET",
        "/users",
        ("limit", "offset", "search"),
    ),
    ("list_collections", "List Collections", "Schema", "GET", "/collections", ()),
    (
        "get_collection",
        "Get Collection",
        "Schema",
        "GET",
        "/collections/{collection}",
        ("collection",),
    ),
    (
        "create_collection",
        "Create Collection",
        "Schema",
        "POST",
        "/collections",
        ("collection_name", "payload_json"),
    ),
    (
        "update_collection",
        "Update Collection",
        "Schema",
        "PATCH",
        "/collections/{collection}",
        ("collection", "payload_json"),
    ),
    (
        "delete_collection",
        "Delete Collection",
        "Schema",
        "DELETE",
        "/collections/{collection}",
        ("collection",),
    ),
    (
        "list_fields",
        "List Fields",
        "Schema",
        "GET",
        "/fields/{collection}",
        ("collection",),
    ),
    (
        "get_field",
        "Get Field",
        "Schema",
        "GET",
        "/fields/{collection}/{field_name}",
        ("collection", "field_name"),
    ),
    (
        "create_field",
        "Create Field",
        "Schema",
        "POST",
        "/fields/{collection}",
        ("collection", "field_name", "field_type", "payload_json"),
    ),
    (
        "update_field",
        "Update Field",
        "Schema",
        "PATCH",
        "/fields/{collection}/{field_name}",
        ("collection", "field_name", "payload_json"),
    ),
    (
        "delete_field",
        "Delete Field",
        "Schema",
        "DELETE",
        "/fields/{collection}/{field_name}",
        ("collection", "field_name"),
    ),
    (
        "list_items",
        "List Items",
        "Content",
        "GET",
        "/items/{collection}",
        ("collection", "limit", "offset", "search", "sort", "fields", "filter_json"),
    ),
    (
        "get_item",
        "Get Item",
        "Content",
        "GET",
        "/items/{collection}/{item_id}",
        ("collection", "item_id", "fields"),
    ),
    (
        "create_item",
        "Create Item",
        "Content",
        "POST",
        "/items/{collection}",
        ("collection", "payload_json"),
    ),
    (
        "update_item",
        "Update Item",
        "Content",
        "PATCH",
        "/items/{collection}/{item_id}",
        ("collection", "item_id", "payload_json"),
    ),
    (
        "delete_item",
        "Delete Item",
        "Content",
        "DELETE",
        "/items/{collection}/{item_id}",
        ("collection", "item_id"),
    ),
    (
        "list_files",
        "List Files",
        "Files",
        "GET",
        "/files",
        ("limit", "offset", "search"),
    ),
    ("get_file", "Get File", "Files", "GET", "/files/{file_id}", ("file_id",)),
    (
        "upload_file",
        "Upload File",
        "Files",
        "POST",
        "/files",
        ("file_name", "mime_type", "content_base64"),
    ),
    (
        "update_file",
        "Update File",
        "Files",
        "PATCH",
        "/files/{file_id}",
        ("file_id", "payload_json"),
    ),
    ("delete_file", "Delete File", "Files", "DELETE", "/files/{file_id}", ("file_id",)),
    (
        "list_folders",
        "List Folders",
        "Files",
        "GET",
        "/folders",
        ("limit", "offset", "search"),
    ),
    (
        "get_folder",
        "Get Folder",
        "Files",
        "GET",
        "/folders/{folder_id}",
        ("folder_id",),
    ),
    ("create_folder", "Create Folder", "Files", "POST", "/folders", ("folder_name",)),
    (
        "update_folder",
        "Update Folder",
        "Files",
        "PATCH",
        "/folders/{folder_id}",
        ("folder_id", "folder_name"),
    ),
    (
        "delete_folder",
        "Delete Folder",
        "Files",
        "DELETE",
        "/folders/{folder_id}",
        ("folder_id",),
    ),
]


def _field(name: str, operation: str):
    """Build a field shared by the generated operation-specific forms."""
    if name == "collection":
        return str, Field(
            ...,
            title="Collection",
            description="Collection to operate on",
            json_schema_extra={
                "x-dynamic-options": {
                    "field_name": "collection",
                    "placeholder": "Select a collection",
                    "searchable": True,
                    "allow_custom": True,
                }
            },
        )
    required = {
        "item_id": ("Item ID", "Primary key of the item"),
        "field_name": ("Field Name", "Field key in the collection"),
        "field_type": (
            "Field Type",
            "Directus field type, such as string, integer, or boolean",
        ),
        "file_id": ("File ID", "UUID of the file"),
        "folder_id": ("Folder ID", "UUID of the folder"),
        "folder_name": ("Folder Name", "Name of the folder"),
        "collection_name": ("Collection Name", "Name of the collection to create"),
        "file_name": ("File Name", "Name for the uploaded file"),
        "content_base64": (
            "File Content (Base64)",
            "Base64-encoded file contents, up to 8 MB",
        ),
    }
    if name in required:
        title, description = required[name]
        extra = (
            {"ui:widget": "textarea", "format": "byte"}
            if name == "content_base64"
            else None
        )
        return str, Field(
            ..., title=title, description=description, json_schema_extra=extra
        )
    if name == "payload_json":
        required = operation in {
            "create_item",
            "update_item",
            "update_collection",
            "update_field",
            "update_file",
        }
        return (str if required else Optional[str]), Field(
            ... if required else None,
            title="JSON Data",
            description="JSON object with the item's fields or additional Directus schema/metadata",
            json_schema_extra={
                "ui:widget": "textarea",
                "placeholder": '{"title":"Example"}',
            },
        )
    if name == "filter_json":
        return Optional[str], Field(
            None,
            title="Filter (JSON)",
            description='Directus filter object, for example {"status":{"_eq":"published"}}',
            json_schema_extra={"ui:widget": "textarea"},
        )
    titles = {
        "limit": "Limit",
        "offset": "Offset",
        "search": "Search",
        "sort": "Sort",
        "fields": "Fields",
        "mime_type": "MIME Type",
    }
    descriptions = {
        "limit": "Maximum results to return",
        "offset": "Results to skip",
        "search": "Search across indexed fields",
        "sort": "Comma-separated fields; prefix - for descending",
        "fields": "Comma-separated field names to return",
        "mime_type": "Optional content type of the upload",
    }
    return Optional[str], Field(
        None, title=titles[name], description=descriptions[name]
    )


_MODELS = {}
_RUNTIME = {}
for _name, _display, _category, _method, _path, _fields in _SPECS:
    _declarations = {
        "operation": (
            Literal[_name],
            Field(
                _name,
                title=_display,
                json_schema_extra={
                    "const": _name,
                    "ui:hidden": True,
                    "x-category": _category,
                    "x-is-trigger": False,
                    "x-display-name": _display,
                },
            ),
        )
    }
    _declarations.update({name: _field(name, _name) for name in _fields})
    _MODELS[_name] = create_model(
        "Directus" + "".join(part.title() for part in _name.split("_")) + "Config",
        **_declarations,
    )
    _RUNTIME[_name] = (_method, _path)

DirectusConfig = Annotated[Union[tuple(_MODELS.values())], Discriminator("operation")]


class DirectusNodeConfig(NodeConfig[DirectusConfig, DirectusStaticTokenCredential]):
    pass


def _url(credential: DirectusStaticTokenCredential) -> str:
    url = credential.instance_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Directus URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Directus URL cannot contain credentials, query, or fragment")
    return url


def _json_object(raw: Optional[str], *, required: bool = False) -> Dict[str, Any]:
    if not raw:
        if required:
            raise ValueError("JSON Data must be a JSON object")
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("JSON Data must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON Data must be a JSON object")
    return value


def _request_parts(operation: str, config: BaseModel):
    method, template = _RUNTIME[operation]
    values = config.model_dump(exclude_none=True)
    if operation in {
        "list_items",
        "get_item",
        "create_item",
        "update_item",
        "delete_item",
    }:
        if values["collection"].startswith("directus_"):
            raise ValueError("Content operations require a user collection")
    if operation == "create_collection" and values["collection_name"].startswith(
        "directus_"
    ):
        raise ValueError("Collection names beginning with directus_ are reserved")
    path = re.sub(
        r"\{(\w+)\}",
        lambda match: quote(str(values[match.group(1)]), safe=""),
        template,
    )
    params = {
        key: values[key]
        for key in ("limit", "offset", "search", "sort", "fields")
        if key in values
    }
    if operation in {"get_current_user", "list_users"}:
        # Directus admin responses otherwise include the static token and other
        # authentication fields, which must never enter workflow output.
        params["fields"] = "id,email,first_name,last_name,role,status"
    if "filter_json" in values:
        params["filter"] = json.dumps(_json_object(values["filter_json"]))
    body = None
    if operation == "create_collection":
        body = {"collection": values["collection_name"], "schema": {}}
        body.update(_json_object(values.get("payload_json")))
    elif operation == "create_field":
        body = {"field": values["field_name"], "type": values["field_type"]}
        body.update(_json_object(values.get("payload_json")))
    elif operation in {
        "create_item",
        "update_item",
        "update_collection",
        "update_field",
        "update_file",
    }:
        body = _json_object(values.get("payload_json"), required=True)
    elif operation in {"create_folder", "update_folder"}:
        body = {"name": values["folder_name"]}
    return method, path, params, body


async def _call(
    credential: DirectusStaticTokenCredential,
    operation: str,
    config: BaseModel,
) -> Dict[str, Any]:
    method, path, params, body = _request_parts(operation, config)
    headers = {"Authorization": f"Bearer {credential.static_token}"}
    kwargs: Dict[str, Any] = {"headers": headers, "params": params or None}
    if operation == "upload_file":
        try:
            raw = base64.b64decode(config.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("File Content must be valid base64") from exc
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("File Content exceeds the 8 MB node limit")
        kwargs["files"] = {
            "file": (
                config.file_name,
                raw,
                config.mime_type or "application/octet-stream",
            )
        }
    elif body is not None:
        kwargs["json"] = body

    started = time.monotonic()
    async with guarded_async_client(timeout=30.0) as client:
        try:
            response = await client.request(method, _url(credential) + path, **kwargs)
        except httpx.HTTPError as exc:
            return {"status": "error", "action": operation, "error": str(exc)}
    elapsed = round((time.monotonic() - started) * 1000, 2)
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"message": response.text[:500]}
    if response.is_error:
        errors = payload.get("errors") if isinstance(payload, dict) else None
        message = (
            errors[0].get("message")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict)
            else None
        )
        return {
            "status": "error",
            "action": operation,
            "status_code": response.status_code,
            "error": message or f"Directus returned HTTP {response.status_code}",
            "timing_ms": {"api_request": elapsed},
        }
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if operation in {"get_current_user", "list_users"}:
        allowed = {"id", "email", "first_name", "last_name", "role", "status"}
        if isinstance(data, dict):
            data = {key: value for key, value in data.items() if key in allowed}
        elif isinstance(data, list):
            data = [
                {key: value for key, value in row.items() if key in allowed}
                for row in data
                if isinstance(row, dict)
            ]
    if method == "DELETE" and not data:
        data = {"deleted": True}
    return {
        "status": "success",
        "action": operation,
        "data": data,
        "meta": payload.get("meta") if isinstance(payload, dict) else None,
        "timing_ms": {"api_request": elapsed},
    }


class DirectusNode(WorkflowNode):
    """Read and mutate content, schema, and files in a Directus project."""

    integration_type = "automation-directus"

    edit_examples = [
        "List my Directus collections",
        "Create an item in the articles collection",
        "Update an article and read it back",
        "Upload a file to Directus",
    ]
    connection_evidence = ConnectionEvidence(
        field="collection", noun="collections", identity_operation="get_current_user"
    )

    @classmethod
    def get_config_model(cls):
        return DirectusNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "collection":
            return {"options": []}
        credential = DirectusStaticTokenCredential.model_validate(credential_data)
        result = await _call(
            credential, "list_collections", _MODELS["list_collections"]()
        )
        if result["status"] != "success":
            return {"options": []}
        items = result["data"] if isinstance(result["data"], list) else []
        options = [
            {"value": row["collection"], "label": row["collection"]}
            for row in items
            if isinstance(row, dict)
            and isinstance(row.get("collection"), str)
            and not row["collection"].startswith("directus_")
            and (not search or search.lower() in row["collection"].lower())
        ]
        return {"options": options}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if (
            not isinstance(self.config, DirectusNodeConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect a Directus static token")
        config = self.config.config
        return await _call(self.config.credentials, config.operation, config)
