"""Conversion Tools file and task automation against its published v1 API.

Each operation issues one provider request. Conversions remain asynchronous so
workflows can poll explicitly and pass result files to subsequent nodes.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.conversiontools.io/v1"


class ConversionToolsAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Conversion Tools API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://conversiontools.io/profile",
            "x-credential-instructions": "Copy the API token from your Conversion Tools Profile and paste it here. NoClick sends it as a Bearer token to api.conversiontools.io and checks your account with GET /auth. Creating tasks uses your quota unless options include sandbox: true. Retention changes and deleting task files may require a paid plan.",
        },
    )
    credential_type: Literal["conversion_tools_api_token"] = Field(
        "conversion_tools_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token",
                           json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API token")
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# Conversion Tools's own MCP server: agents get its tools through a person's Conversion Tools sign-in.
ConversionToolsMcpCredential = mcp_credential("conversion_tools", "https://mcp.conversiontools.io/mcp", app="Conversion Tools")
ConversionToolsCredential = Union[ConversionToolsAPITokenCredential, ConversionToolsMcpCredential]


Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")]


class UploadFile(Input):
    """Upload arbitrary file bytes as multipart data without consuming task quota."""
    operation: Literal["upload_file"] = Field("upload_file", json_schema_extra={"ui:hidden": True})
    file_base64: str = Field(..., min_length=1, max_length=70_000_000, title="File contents (base64)",
        json_schema_extra={"contentEncoding": "base64", "contentMediaType": "application/octet-stream"},
        description="Base64-encoded file bytes, without a data URL prefix. Maximum decoded size is 50 MiB; the provider plan may allow less.")
    filename: str = Field("input.bin", max_length=255, pattern=r"^[^/\\\r\n]+$", title="File name")

    @field_validator("file_base64")
    @classmethod
    def file_bytes(cls, value):
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Use valid base64 file contents") from None
        if not data or len(data) > 50 * 1024 * 1024:
            raise ValueError("File must contain 1 byte to 50 MiB")
        return value


class DownloadFile(Input):
    """Download source or converted bytes using a file ID."""
    operation: Literal["download_file"] = Field("download_file", json_schema_extra={"ui:hidden": True})
    file_id: Identifier


class GetFileInfo(Input):
    """Read file size, name and available text preview."""
    operation: Literal["get_file_info"] = Field("get_file_info", json_schema_extra={"ui:hidden": True})
    file_id: Identifier


class CreateTask(Input):
    """Start a conversion; the returned task ID can be polled separately."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    conversion_type: Identifier = Field(..., description="Type from List conversions, e.g. convert.xml_to_excel.")
    options_json: str = Field(..., title="Conversion options (JSON)",
        description='JSON object from the conversion definition, including file_id or url. Add "sandbox": true for free sandbox testing. Multi-file conversions use their documented file input keys.',
        json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    callback_url: str | None = Field(None, title="Completion webhook URL", description="Optional HTTP(S) URL for the provider to notify when the task completes.")

    @field_validator("options_json")
    @classmethod
    def options(cls, value):
        try:
            parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, RecursionError):
            raise ValueError("Conversion options must be a JSON object") from None
        if not isinstance(parsed, dict):
            raise ValueError("Conversion options must be a JSON object")
        return value

    @field_validator("callback_url")
    @classmethod
    def callback(cls, value):
        if value is None:
            return value
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError("Use an HTTP(S) webhook URL without embedded credentials")
        return value


class ListTasks(Input):
    """List up to the 50 most recent account tasks; no pagination is documented."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    status: Literal["PENDING", "RUNNING", "SUCCESS", "ERROR"] | None = None


class GetTaskStatus(Input):
    """Poll one task; SUCCESS provides a file ID, ERROR includes the failure."""
    operation: Literal["get_task_status"] = Field("get_task_status", json_schema_extra={"ui:hidden": True})
    task_id: Identifier


class UpdateTaskRetention(Input):
    """Change artifact lifetime; 15-minute retention requires a paid plan."""
    operation: Literal["update_task_retention"] = Field("update_task_retention", json_schema_extra={"ui:hidden": True})
    task_id: Identifier
    retention_mode: Literal["standard_24h", "ttl_15m"] = Field(..., title="Retention mode")


class DeleteTaskFiles(Input):
    """Schedule irreversible removal of source, result and artifact files (paid)."""
    operation: Literal["delete_task_files"] = Field("delete_task_files", json_schema_extra={"ui:hidden": True})
    task_id: Identifier


class GetConfig(Input):
    """Read custom and published AI Studio converters enabled for the account."""
    operation: Literal["get_config"] = Field("get_config", json_schema_extra={"ui:hidden": True})


class ListConversions(Input):
    """Browse the public conversion catalog and supported format options."""
    operation: Literal["list_conversions"] = Field("list_conversions", json_schema_extra={"ui:hidden": True})
    input_format: str | None = Field(None, title="Input format", description="Format or alias such as xml or pdf.")
    output_format: str | None = Field(None, title="Output format", description="Format or alias such as excel or xlsx.")
    ai: bool | None = Field(None, description="Yes: AI conversions only; No: exclude AI; Default: both.")


class GetConversion(Input):
    """Read a public conversion definition, options and multi-file inputs."""
    operation: Literal["get_conversion"] = Field("get_conversion", json_schema_extra={"ui:hidden": True})
    conversion_type: Identifier


class GetAuthInfo(Input):
    """Read the authenticated account email to verify the pasted token."""
    operation: Literal["get_auth_info"] = Field("get_auth_info", json_schema_extra={"ui:hidden": True})


ConversionToolsConfig = Annotated[Union[
    UploadFile, DownloadFile, GetFileInfo, CreateTask, ListTasks, GetTaskStatus,
    UpdateTaskRetention, DeleteTaskFiles, GetConfig, ListConversions,
    GetConversion, GetAuthInfo,
], Field(discriminator="operation")]


class ConversionToolsNodeConfig(NodeConfig[ConversionToolsConfig, ConversionToolsCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class ConversionToolsNode(WorkflowNode):
    integration_type = "automation-conversion-tools"
    credential_provider_labels = {"conversion_tools": "Conversion Tools Account"}
    connection_evidence = ConnectionEvidence(noun="Conversion Tools account", identity_operation="get_auth_info")

    @classmethod
    def get_config_model(cls):
        return ConversionToolsNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Conversion Tools API token")
        config = self.config.config
        action = config.operation
        token = self.config.credentials.api_token
        method, path, params, body, files = "GET", "", None, None, None
        if action == "upload_file":
            method, path = "POST", "/files"
            files = {"file": (config.filename, base64.b64decode(config.file_base64, validate=True), "application/octet-stream")}
        elif action in {"download_file", "get_file_info"}:
            path = "/files/" + quote(config.file_id, safe="") + ("/info" if action == "get_file_info" else "")
        elif action == "create_task":
            method, path = "POST", "/tasks"
            body = {"type": config.conversion_type, "options": json.loads(config.options_json)}
            if config.callback_url is not None:
                body["callbackUrl"] = config.callback_url
        elif action == "list_tasks":
            path = "/tasks"
            params = {"status": config.status} if config.status else None
        elif action in {"get_task_status", "update_task_retention", "delete_task_files"}:
            path = "/tasks/" + quote(config.task_id, safe="")
            if action == "update_task_retention":
                method, path, body = "PATCH", path + "/retention", {"retentionMode": config.retention_mode}
            elif action == "delete_task_files":
                method, path = "POST", path + "/delete"
        elif action == "get_config":
            path = "/config"
        elif action == "list_conversions":
            path = "/conversions"
            params = {key: value for key, value in {"input": config.input_format, "output": config.output_format,
                "ai": str(config.ai).lower() if config.ai is not None else None}.items() if value is not None}
        elif action == "get_conversion":
            path = "/conversions/" + quote(config.conversion_type, safe="")
        elif action == "get_auth_info":
            path = "/auth"
        else:
            raise ValueError("Unsupported Conversion Tools operation")
        headers = {"Accept": "application/octet-stream" if action == "download_file" else "application/json"}
        if action not in {"list_conversions", "get_conversion"}:
            headers["Authorization"] = "Bearer " + token
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body, files=files)
        except httpx.HTTPError:
            raise ValueError("Conversion Tools request could not be completed; inspect task history before retrying a write") from None
        expected_status = 202 if action == "delete_task_files" else 200
        if response.status_code != expected_status:
            # Keep the provider's JSON rejection for the shared connect seam,
            # while refusing HTML, redirects and responses that echo our token.
            try:
                message = response.json().get("error")
            except (ValueError, AttributeError):
                message = None
            message = message.replace(token, "[redacted]")[:500] if isinstance(message, str) else "Request was not accepted"
            raise ValueError(f"Conversion Tools HTTP {response.status_code}: {message}")
        if action == "download_file":
            return {"operation": action, "file": BinaryOutput(data=response.content,
                content_type=response.headers.get("content-type", "application/octet-stream"), filename=config.file_id + ".bin")}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Conversion Tools returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("Conversion Tools returned an invalid response envelope")
        # A failed conversion is a documented task state for downstream branches.
        # Other error envelopes must fail connection and ordinary reads.
        if data.get("error") and not (action == "get_task_status" and data.get("status") == "ERROR"):
            message = str(data["error"]).replace(token, "[redacted]")[:500]
            raise ValueError("Conversion Tools: " + message)
        required = {"upload_file": ("file_id", str), "create_task": ("task_id", str),
            "list_tasks": ("data", list), "get_task_status": ("status", str),
            "get_file_info": ("name", str), "get_auth_info": ("email", str),
            "get_config": ("conversions", list), "list_conversions": ("conversions", list),
            "get_conversion": ("conversion", dict), "update_task_retention": ("retentionMode", str),
            "delete_task_files": ("message", str)}
        key, kind = required[action]
        if not isinstance(data.get(key), kind) or (kind is str and not data[key]):
            raise ValueError("Conversion Tools response is missing " + key)
        if action == "get_task_status" and data["status"] not in {"PENDING", "RUNNING", "SUCCESS", "ERROR"}:
            raise ValueError("Conversion Tools returned an unknown task status")
        output = {"operation": action, "data": data, "http_status": response.status_code}
        if action == "list_tasks":
            output["history_limit"] = 50
        if action == "delete_task_files":
            output["deletion_scheduled"] = True
        return output
