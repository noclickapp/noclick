"""Sanity Content Lake workflow node.

Uses a project-scoped robot token to query content, mutate documents, upload
remote assets, and manage datasets through Sanity's documented HTTP APIs.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence


API_VERSION = "v2025-02-19"
DATASET_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "dataset",
        "placeholder": "Select a dataset...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or enter a dataset name",
    }
}


class SanityRobotTokenCredential(BaseModel):
    """Project robot token created under Sanity project API settings."""

    credential_type: Literal["sanity_robot_token"] = Field(
        "sanity_robot_token", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ..., title="Project ID", description="Eight-character ID in Sanity project settings."
    )
    api_token: str = Field(
        ..., title="Robot API token", description="Developer or Editor project API token.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="Sanity Robot Token", json_schema_extra={
        "x-credential-url": "https://www.sanity.io/manage",
    })


# Sanity's own MCP server: agents get its tools through a person's Sanity sign-in.
SanityMcpCredential = mcp_credential("sanity", "https://mcp.sanity.io", app="Sanity")
SanityCredential = Union[SanityRobotTokenCredential, SanityMcpCredential]


def _field(annotation: Any, default: Any, title: str, **kwargs: Any) -> tuple[Any, Any]:
    return annotation, Field(default, title=title, **kwargs)


DATASET = {"dataset": _field(str, "production", "Dataset", json_schema_extra=DATASET_OPTIONS)}
DOCUMENT_ID = {"document_id": _field(str, ..., "Document ID", min_length=1)}
JSON_TEXT = {"ui:widget": "textarea", "ui:placeholder": '{"title":"Example"}'}


def _config(name: str, category: str, fields: dict[str, tuple[Any, Any]], *,
            creates: Optional[tuple[str, str]] = None) -> type[BaseModel]:
    extra: dict[str, Any] = {
        "const": name,
        "ui:hidden": True,
        "x-category": category,
        "x-display-name": name.replace("_", " ").title(),
    }
    if creates:
        extra.update({
            "x-creates-resource": True,
            "x-resource-type": creates[0],
            "x-resource-id-path": creates[1],
        })
    return create_model(
        "Sanity" + "".join(part.title() for part in name.split("_")) + "Config",
        operation=(Literal[name], Field(name, title=extra["x-display-name"], json_schema_extra=extra)),
        **fields,
    )


_CONFIGS = [
    _config("list_datasets", "Datasets", {}),
    _config("create_dataset", "Datasets", {
        "name": _field(str, ..., "Dataset name", min_length=1),
        "visibility": _field(Literal["private", "public"], "private", "Visibility"),
    }, creates=("sanity_dataset", "data.datasetName")),
    _config("delete_dataset", "Datasets", {"name": _field(str, ..., "Dataset name", min_length=1)}),
    _config("query_documents", "Documents", {**DATASET,
        "query": _field(str, ..., "GROQ query", min_length=1, json_schema_extra={"ui:widget": "textarea"}),
        "params_json": _field(Optional[str], None, "Query parameters (JSON object)", json_schema_extra=JSON_TEXT),
        "perspective": _field(Literal["published", "drafts", "raw"], "published", "Perspective"),
    }),
    _config("get_document", "Documents", {**DATASET, **DOCUMENT_ID}),
    _config("create_document", "Documents", {**DATASET,
        "document_json": _field(str, ..., "Document (JSON object)", min_length=1, json_schema_extra=JSON_TEXT),
    }, creates=("sanity_document", "data.results.0.documentId")),
    _config("replace_document", "Documents", {**DATASET,
        "document_json": _field(str, ..., "Document with _id (JSON object)", min_length=1, json_schema_extra=JSON_TEXT),
    }, creates=("sanity_document", "data.results.0.documentId")),
    _config("patch_document", "Documents", {**DATASET, **DOCUMENT_ID,
        "set_json": _field(Optional[str], None, "Set fields (JSON object)", json_schema_extra=JSON_TEXT),
        "unset_json": _field(Optional[str], None, "Unset fields (JSON array)", json_schema_extra={"ui:widget": "textarea", "ui:placeholder": '["oldField"]'}),
    }),
    _config("delete_document", "Documents", {**DATASET, **DOCUMENT_ID}),
    _config("list_assets", "Assets", {**DATASET,
        "asset_type": _field(Literal["all", "images", "files"], "all", "Asset type"),
        "limit": _field(int, 100, "Limit", ge=1, le=1000),
    }),
    _config("upload_image_url", "Assets", {**DATASET,
        "url": _field(str, ..., "Public HTTPS image URL", min_length=1),
        "filename": _field(Optional[str], None, "Filename"),
        "title": _field(Optional[str], None, "Title"),
    }, creates=("sanity_asset", "data.document._id")),
    _config("upload_file_url", "Assets", {**DATASET,
        "url": _field(str, ..., "Public HTTPS file URL", min_length=1),
        "filename": _field(Optional[str], None, "Filename"),
        "title": _field(Optional[str], None, "Title"),
    }, creates=("sanity_asset", "data.document._id")),
]

SanityConfig = Annotated[Union[tuple(_CONFIGS)], Discriminator("operation")]


class SanityNodeConfig(NodeConfig[SanityConfig, SanityCredential]):
    pass


def _json(value: Optional[str], expected: type, field: str) -> Any:
    if not value:
        raise ValueError(f"{field} must be a JSON {expected.__name__}")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} is invalid JSON") from exc
    if not isinstance(parsed, expected):
        raise ValueError(f"{field} must be a JSON {expected.__name__}")
    return parsed


def _project(project_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{8}", project_id):
        raise ValueError("Sanity Project ID must be eight lowercase letters or digits")
    return project_id


def _segment(value: str) -> str:
    if not value or value in (".", ".."):
        raise ValueError("A resource ID or dataset name is required")
    return quote(value, safe="")


async def _request(token: str, method: str, url: str, *, params: Optional[dict[str, Any]] = None,
                   body: Optional[dict[str, Any]] = None, timeout: float = 30.0) -> Any:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json",
        }, params=params, json=body)
        if response.is_error:
            # Provider error bodies can contain customer content. Do not log them.
            raise ValueError(f"Sanity API returned HTTP {response.status_code} for {method} {urlsplit(url).path}")
        return response.json() if response.content else {}


class SanityNode(WorkflowNode):
    """Query, edit, and manage Sanity Content Lake data."""

    integration_type = "automation-sanity"

    credential_provider_labels = {"sanity": "Sanity Account"}

    edit_examples = [
        'Query published articles with GROQ and return their titles',
        'Create a Sanity article document from workflow data',
        'Patch a document title by ID, then read it back',
        'Upload an image from a public HTTPS URL',
    ]
    connection_evidence = ConnectionEvidence(field="dataset", noun="datasets")

    @classmethod
    def get_config_model(cls):
        return SanityNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> dict[str, Any]:
        if field_name != "dataset":
            return {"options": []}
        project = _project(credential_data["project_id"])
        token = credential_data["api_token"]
        data = await _request(token, "GET", f"https://api.sanity.io/{API_VERSION}/projects/{project}/datasets")
        options = [
            {"value": row["name"], "label": row["name"]}
            for row in data if isinstance(row, dict) and row.get("name")
            and (not search or search.lower() in row["name"].lower())
        ]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, SanityNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Sanity project robot token")
        credential = self.config.credentials
        project = _project(credential.project_id)
        token = credential.api_token
        config = self.config.config
        operation = config.operation
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        management = f"https://api.sanity.io/{API_VERSION}/projects/{project}/datasets"

        if operation == "list_datasets":
            data = await _request(token, "GET", management)
        elif operation == "create_dataset":
            data = await _request(token, "PUT", f"{management}/{_segment(values['name'])}",
                                  body={"aclMode": values["visibility"]})
        elif operation == "delete_dataset":
            data = await _request(token, "DELETE", f"{management}/{_segment(values['name'])}")
        else:
            dataset = values.pop("dataset", "production")
            # Dataset names are a single URL segment. A slash must never redirect
            # a caller-controlled name to another Content Lake endpoint.
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", dataset):
                raise ValueError("Invalid Sanity dataset name")
            base = f"https://{project}.api.sanity.io/{API_VERSION}"
            if operation == "query_documents":
                params = _json(values["params_json"], dict, "Query parameters") if values.get("params_json") else {}
                data = await _request(token, "POST", f"{base}/data/query/{dataset}",
                                      params={"perspective": values["perspective"]},
                                      body={"query": values["query"], "params": params})
            elif operation == "get_document":
                data = await _request(token, "GET", f"{base}/data/doc/{dataset}/{_segment(values['document_id'])}")
            elif operation in ("create_document", "replace_document", "patch_document", "delete_document"):
                if operation in ("create_document", "replace_document"):
                    document = _json(values["document_json"], dict, "Document")
                    if not isinstance(document.get("_type"), str) or not document["_type"]:
                        raise ValueError("Document must contain a nonempty _type")
                    if operation == "replace_document" and not document.get("_id"):
                        raise ValueError("Replace document requires _id")
                    mutation = {"create" if operation == "create_document" else "createOrReplace": document}
                elif operation == "patch_document":
                    patch: dict[str, Any] = {"id": values["document_id"]}
                    if values.get("set_json"):
                        patch["set"] = _json(values["set_json"], dict, "Set fields")
                    if values.get("unset_json"):
                        unset = _json(values["unset_json"], list, "Unset fields")
                        if not all(isinstance(item, str) for item in unset):
                            raise ValueError("Unset fields must contain only strings")
                        patch["unset"] = unset
                    if len(patch) == 1:
                        raise ValueError("Patch requires fields to set or unset")
                    mutation = {"patch": patch}
                else:
                    mutation = {"delete": {"id": values["document_id"]}}
                data = await _request(token, "POST", f"{base}/data/mutate/{dataset}",
                                      params={"returnIds": "true", "visibility": "sync"},
                                      body={"mutations": [mutation]})
            elif operation == "list_assets":
                type_filter = {"all": '["sanity.imageAsset","sanity.fileAsset"]',
                               "images": '["sanity.imageAsset"]',
                               "files": '["sanity.fileAsset"]'}[values["asset_type"]]
                query = f"*[_type in {type_filter}] | order(_createdAt desc)[0...{values['limit']}]"
                data = await _request(token, "POST", f"{base}/data/query/{dataset}", body={"query": query})
            elif operation in ("upload_image_url", "upload_file_url"):
                source = urlsplit(values["url"])
                if source.scheme != "https" or not source.hostname or source.username or source.password:
                    raise ValueError("Asset URL must be public HTTPS without embedded credentials")
                kind = "images" if operation == "upload_image_url" else "files"
                body = {"url": values["url"]}
                if values.get("filename"):
                    body["filename"] = values["filename"]
                params = {"title": values["title"]} if values.get("title") else None
                data = await _request(token, "POST", f"{base}/assets/{kind}/{dataset}/from-url",
                                      params=params, body=body, timeout=330.0)
            else:
                raise ValueError(f"Unsupported Sanity operation: {operation}")
        return {"status": "success", "action": operation, "data": data}
