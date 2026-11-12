"""OneSignal messaging, audience, journey, and organization REST actions."""

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.onesignal_operations import OPERATIONS


API_BASE = "https://api.onesignal.com"


class OneSignalCredential(BaseModel):
    credential_type: Literal["onesignal_api_key"] = Field(
        "onesignal_api_key", json_schema_extra={"ui:hidden": True}
    )
    app_id: Optional[str] = Field(None, title="OneSignal App ID")
    app_api_key: Optional[str] = Field(
        None, title="App API Key", json_schema_extra={"ui:widget": "password"}
    )
    organization_api_key: Optional[str] = Field(
        None, title="Organization API Key", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(title="OneSignal API Key", json_schema_extra={
        "x-credential-url": "https://dashboard.onesignal.com/",
        "x-credential-instructions": "Find your App ID and App API Key under Settings → Keys & IDs. Organization actions additionally require the Organization API Key from Organizations → Keys & IDs. OneSignal's REST API uses API keys rather than an end-user OAuth authorization flow.",
    })


# OneSignal's own MCP server: agents get its tools through a person's OneSignal sign-in.
OnesignalMcpCredential = mcp_credential("onesignal", "https://api.onesignal.com/mcp/oauth", app="OneSignal")


def _field_name(name: str, prefix: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()


def _make_config(name: str, op: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for variable in re.findall(r"\{([^}]+)\}", op["path"]):
        if variable != "app_id":
            fields[_field_name(variable, "path")] = (
                str, Field(..., title=variable.replace("_", " ").title())
            )
        elif op["auth"] == "organization" and name != "test_connection":
            fields["path_app_id"] = (
                Optional[str], Field(None, title="Target App ID",
                                     description="Defaults to the App ID in the credential."),
            )
    if name == "copy_template_to_another_app":
        fields["query_app_id"] = (
            Optional[str], Field(None, title="Destination App ID",
                                 description="App to receive the copied template. Defaults to the App ID in the credential."),
        )
    for param in op["query_params"]:
        title = param["name"].replace("_", " ").title()
        fields[_field_name(param["name"], "query")] = (
            str if param["required"] else Optional[str],
            Field(... if param["required"] else None, title=title,
                  description=param["description"]),
        )
    for param in op["header_params"]:
        fields[_field_name(param["name"], "header")] = (
            str if param["required"] else Optional[str],
            Field(... if param["required"] else None, title=param["name"]),
        )
    if op["query_params"]:
        fields["query_json"] = (
            Optional[str], Field(None, title="Other Query Parameters JSON",
                                 description="Optional additional query parameters as a JSON object.",
                                 json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}),
        )
    if op["body_type"]:
        required = op["method"] in {"POST", "PUT", "PATCH"}
        fields["body_input"] = (
            str if required else Optional[str],
            Field(... if required else None, title="Request Body JSON",
                  description="OneSignal request body as a JSON object. The configured App ID is inserted when the API expects app_id.",
                  json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}),
        )
    return create_model(
        "OneSignal" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op["category"], "x-is-trigger": False,
                               "x-display-name": op["label"]},
        )),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
OneSignalConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class OneSignalNodeConfig(NodeConfig[OneSignalConfig, Union[OneSignalCredential, OnesignalMcpCredential]]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


class OneSignalNode(WorkflowNode):
    integration_type = "automation-onesignal"
    credential_provider_labels = {"onesignal": "OneSignal Account"}
    connection_evidence = ConnectionEvidence(identity_operation="test_connection", noun="OneSignal app")
    edit_examples = [
        "Send a push notification through OneSignal",
        "Create a OneSignal user with an external ID",
        "List OneSignal message templates",
        "Start a customer journey in OneSignal",
    ]

    @classmethod
    def get_config_model(cls):
        return OneSignalNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, OneSignalNodeConfig):
            raise ValueError("OneSignal configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect OneSignal credentials")
        config = self.config.config
        op = OPERATIONS[config.operation]
        auth = op["auth"]
        path = op["path"]
        if config.operation == "test_connection" and not (credential.app_api_key and credential.app_id):
            if credential.organization_api_key:
                auth, path = "organization", "/apps"
            else:
                raise ValueError("Provide an App API Key or Organization API Key")
        key = {"app": credential.app_api_key,
               "organization": credential.organization_api_key}.get(auth)
        if auth != "none" and not key:
            raise ValueError(f"OneSignal {auth.title()} API Key is required")

        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for variable in re.findall(r"\{([^}]+)\}", path):
            value = (values.pop("path_app_id", None) or credential.app_id) if variable == "app_id" else values.pop(_field_name(variable, "path"))
            if not value:
                raise ValueError("OneSignal App ID is required")
            path = path.replace("{" + variable + "}", quote(str(value), safe=""))

        params: dict[str, Any] = {}
        for param, value in op["query_template"].items():
            if not value.startswith("{"):
                params[param] = value
        for param in op["query_params"]:
            value = values.pop(_field_name(param["name"], "query"), None)
            if value is not None:
                params[param["name"]] = value
        if "app_id" in op["query_template"]:
            app_id = values.pop("query_app_id", None) or credential.app_id
            if not app_id:
                raise ValueError("OneSignal App ID is required")
            params["app_id"] = app_id
        query_raw = values.pop("query_json", None)
        if query_raw:
            params.update(_json_object(query_raw, "Other Query Parameters JSON"))

        headers = {"Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Key {key}"
        for param in op["header_params"]:
            value = values.pop(_field_name(param["name"], "header"), None)
            if value is not None:
                headers[param["name"]] = value
        request: dict[str, Any] = {}
        raw_body = values.pop("body_input", None)
        if raw_body is not None:
            body = _json_object(raw_body, "Request Body JSON")
            if op["body_app_id"] and credential.app_id:
                body.setdefault("app_id", credential.app_id)
            request["json"] = body
            headers["Content-Type"] = "application/json"
        elif op["body_required"]:
            raise ValueError("Request Body JSON is required")

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(op["method"], API_BASE + path,
                                            params=params or None, headers=headers, **request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        if response.is_error or response.is_redirect:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:300]
            raise ValueError(f"OneSignal API error {response.status_code}: {str(detail)[:400]}")
        if not response.content:
            data: Any = {"ok": True}
        elif "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            data = response.json()
        else:
            data = {"text": response.text}
        if isinstance(data, list):
            data = {"items": [item if isinstance(item, dict) else {"value": item} for item in data]}
        return {"status": "success", "operation": config.operation,
                "status_code": response.status_code, "data": data,
                "timing_ms": {"api_request": elapsed_ms}}
