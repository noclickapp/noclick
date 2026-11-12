"""Insightly CRM v3.1 workflow node.

The operation paths and body semantics follow Insightly's published Swagger
document at https://api.na1.insightly.com/v3.1/swagger/docs/v3.1. Insightly
authenticates with each user's API key as the HTTP Basic username and an empty
password; it does not offer a third-party OAuth app for this API.
"""

from __future__ import annotations

import json
import re
from typing import Any, Annotated, Dict, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


_POD_RE = re.compile(r"[a-z][a-z0-9-]{0,14}[a-z0-9]$|[a-z]$")


class InsightlyApiKeyCredential(BaseModel):
    """API key and pod shown together under Insightly User Settings > API."""

    credential_type: Literal["insightly_api_key"] = Field(
        "insightly_api_key", json_schema_extra={"ui:hidden": True}
    )
    pod: str = Field(
        ..., title="API Pod", description="Pod from your Insightly API URL (for example na1).",
    )
    api_key: str = Field(
        ..., title="API Key", json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("pod")
    @classmethod
    def validate_pod(cls, pod: str) -> str:
        pod = pod.strip().lower()
        if not _POD_RE.fullmatch(pod):
            raise ValueError("Enter only the pod from your Insightly API URL, such as na1")
        return pod

    model_config = ConfigDict(title="Insightly API Key", json_schema_extra={
        "x-credential-url": "https://support.insight.ly/en-US/Knowledge/article/9549/Find_your_API_key_and_url/",
        "x-credential-instructions": "In Insightly, open User Settings and copy the API key and the pod shown in the API URL.",
    })


# Insightly's own MCP server: agents get its tools through a person's Insightly sign-in.
InsightlyMcpCredential = mcp_credential("insightly", "https://mcp.insightly.com/", app="Insightly")
InsightlyCredential = Union[InsightlyApiKeyCredential, InsightlyMcpCredential]


# These are the core CRM and post-sale objects, plus account-owned selectors.
# The CRUD paths are deliberate: Insightly PUTs a complete object to the
# collection route (with its *_ID in the body), not to /{id}.
_CRUD_RESOURCES = {
    "contact": ("Contacts", "CONTACT_ID"),
    "lead": ("Leads", "LEAD_ID"),
    "organisation": ("Organisations", "ORGANISATION_ID"),
    "opportunity": ("Opportunities", "OPPORTUNITY_ID"),
    "project": ("Projects", "PROJECT_ID"),
    "task": ("Tasks", "TASK_ID"),
}
_READ_RESOURCES = {
    "user": "Users",
    "pipeline": "Pipelines",
    "pipeline_stage": "PipelineStages",
}


def _op_field(op: str, display: str, category: str):
    return Field(
        op, title=display,
        json_schema_extra={
            "const": op, "ui:hidden": True, "x-display-name": display,
            "x-category": category, "x-is-trigger": False,
        },
    )


def _fields_for(action: str, resource: str, id_field: Optional[str]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if action in ("get", "delete"):
        fields["record_id"] = (int, Field(..., title="Record ID", ge=1))
    if action in ("list", "search", "search_by_tag"):
        fields["top"] = (int, Field(100, title="Page Size", ge=1, le=500))
        fields["skip"] = (int, Field(0, title="Records to Skip", ge=0))
    if action == "search":
        fields["field_name"] = (Optional[str], Field(None, title="Field Name"))
        fields["field_value"] = (Optional[str], Field(None, title="Field Value"))
        fields["updated_after_utc"] = (Optional[str], Field(None, title="Updated After (UTC)", description="ISO 8601 timestamp"))
    if action == "search_by_tag":
        fields["tag_name"] = (str, Field(..., title="Tag Name"))
    if action in ("create", "update"):
        instruction = (
            f"A JSON {resource} object using Insightly's uppercase API field names. "
            + (f"Include {id_field} when updating." if action == "update" else "")
        )
        fields["record_json"] = (str, Field(
            ..., title="Record JSON", description=instruction,
            json_schema_extra={"ui:widget": "textarea"},
        ))
    return fields


_SPECS: Dict[str, tuple[str, str, str, Optional[str]]] = {}
_CONFIG_MODELS = []


def _register(action: str, resource: str, endpoint: str, id_field: Optional[str] = None):
    op = f"{action}_{resource}"
    category = resource.replace("_", " ").title()
    display = f"{action.replace('_', ' ').title()} {category}"
    fields = {"operation": (Literal[op], _op_field(op, display, category))}
    fields.update(_fields_for(action, resource, id_field))
    model = create_model(
        f"Insightly{''.join(word.title() for word in op.split('_'))}Config",
        **fields,
    )
    _CONFIG_MODELS.append(model)
    method = {"list": "GET", "get": "GET", "search": "GET", "search_by_tag": "GET",
              "create": "POST", "update": "PUT", "delete": "DELETE"}[action]
    _SPECS[op] = (method, endpoint, action, id_field)


for _resource, (_endpoint, _id_field) in _CRUD_RESOURCES.items():
    for _action in ("list", "get", "search", "search_by_tag", "create", "update", "delete"):
        if _resource == "task" and _action == "search_by_tag":
            continue  # Insightly's Tasks resource has no SearchByTag route.
        _path = f"/{_endpoint}"
        if _action in ("get", "delete"):
            _path += "/{record_id}"
        elif _action == "search":
            _path += "/Search"
        elif _action == "search_by_tag":
            _path += "/SearchByTag"
        _register(_action, _resource, _path, _id_field)

for _resource, _endpoint in _READ_RESOURCES.items():
    _register("list", _resource, f"/{_endpoint}")
    _register("get", _resource, f"/{_endpoint}/{{record_id}}")

_register("list", "note", "/Notes")
_register("get", "note", "/Notes/{record_id}")
_register("search", "note", "/Notes/Search")
_register("update", "note", "/Notes", "NOTE_ID")
_register("delete", "note", "/Notes/{record_id}")

InsightlyConfig = Annotated[Union[tuple(_CONFIG_MODELS)], Discriminator("operation")]


class InsightlyNodeConfig(NodeConfig[InsightlyConfig, InsightlyCredential]):
    pass


def _parse_record(raw: str, id_field: Optional[str]) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Record JSON is invalid: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("Record JSON must be an object")
    if id_field and id_field not in data:
        raise ValueError(f"Record JSON must include {id_field} for updates")
    return data


class InsightlyNode(WorkflowNode):
    """Insightly CRM: contacts, leads, organisations, opportunities and projects."""

    integration_type = "automation-insightly"

    credential_provider_labels = {"insightly": "Insightly Account"}

    edit_examples = [
        "Create an Insightly contact from a form submission",
        "Find leads updated since yesterday",
        "Create a task after an opportunity changes",
        "List Insightly projects for a weekly report",
    ]
    connection_evidence = ConnectionEvidence(
        operation="list_user", noun="users", identity_operation="list_user"
    )

    @classmethod
    def get_config_model(cls):
        return InsightlyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not config or not isinstance(config, InsightlyNodeConfig):
            raise ValueError("Valid Insightly configuration is required")
        if not config.credentials:
            raise ValueError("Insightly API key and pod are required")

        operation = config.config.operation
        method, endpoint, action, id_field = _SPECS[operation]
        values = config.config.model_dump(exclude_none=True)
        if "record_id" in values:
            endpoint = endpoint.replace("{record_id}", str(values["record_id"]))
        params: Dict[str, Any] = {}
        for name in ("top", "skip", "field_name", "field_value", "updated_after_utc"):
            if name in values and values[name] not in (None, ""):
                params[name] = values[name]
        if action == "search_by_tag":
            params["tagName"] = values["tag_name"]
        body = _parse_record(values["record_json"], id_field if action == "update" else None) if action in ("create", "update") else None

        credentials = config.credentials
        url = f"https://api.{credentials.pod}.insightly.com/v3.1{endpoint}"
        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    method, url, auth=(credentials.api_key, ""),
                    headers={"Accept": "application/json"}, params=params or None,
                    json=body,
                )
        except httpx.TimeoutException:
            return {"status": "error", "action": operation, "error": "Insightly request timed out"}
        except httpx.RequestError as exc:
            return {"status": "error", "action": operation, "error": f"Insightly request failed: {exc}"}

        try:
            data = response.json() if response.content else {"success": response.is_success}
        except ValueError:
            data = {"raw": response.text}
        if response.is_error:
            detail = data.get("message") or data.get("Message") if isinstance(data, dict) else None
            return {
                "status": "error", "action": operation,
                "status_code": response.status_code,
                "error": detail or f"Insightly returned HTTP {response.status_code}",
                "data": data,
            }
        return {"status": "success", "action": operation, "status_code": response.status_code, "data": data}
