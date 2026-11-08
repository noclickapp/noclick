"""Anchor Browser REST operations, pinned to the provider's v1 OpenAPI contract.

Every operation makes one request. Pagination is explicit; actions and tasks
are never retried automatically because they can change third-party sites.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.anchorbrowser.io"


class AnchorBrowserAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Anchor Browser API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.anchorbrowser.io/api-keys",
            "x-credential-instructions": "Create an API key in Anchor Browser's API Keys page, then paste it here. NoClick sends it in the anchor-api-key header. Connecting reads your team's session history; browser actions and tasks may consume credits and change websites."})
    credential_type: Literal["anchor_browser_api_key"] = Field("anchor_browser_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Session(_Input):
    session_id: str = Field(..., min_length=1, max_length=512, title="Session ID", pattern=r"^[A-Za-z0-9_-]+$")


class _BrowserSession(_Input):
    session_id: UUID = Field(..., title="Session ID")


class ListSessions(_Input):
    operation: Literal["list_sessions"] = Field("list_sessions", title="List Sessions", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title="Page")
    limit: Literal[10, 20, 50] = Field(10, title="Page Size")
    sort_by: Literal["created_at", "session_id", "used_credits", "api_key_name"] = "created_at"
    sort_order: Literal["asc", "desc"] = "asc"
    search: str | None = Field(None, description="Comma-separated tag search terms.")
    status: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags; sessions must include all tags.")
    domains: str | None = Field(None, description="Comma-separated domains.")
    profile_name: str | None = None


class StartSession(_Input):
    operation: Literal["start_session"] = Field("start_session", title="Start Browser Session", json_schema_extra={"ui:hidden": True})
    initial_url: str | None = Field(None, title="Initial URL", json_schema_extra={"format": "uri"})
    profile_name: str | None = Field(None, title="Profile Name")
    persist_profile: bool = Field(False, description="Save changes to the named browser profile when the session ends.")
    headless: bool = False
    recording: bool = True
    max_duration: int = Field(10, ge=1, description="Maximum session duration in minutes.")
    idle_timeout: int = Field(5, ge=1, description="Idle timeout in minutes.")
    tags: list[str] | None = None


class GetSession(_Session):
    operation: Literal["get_session"] = Field("get_session", title="Get Browser Session", json_schema_extra={"ui:hidden": True})


class EndSession(_Session):
    operation: Literal["end_session"] = Field("end_session", title="End Browser Session", description="Terminates the selected running session.", json_schema_extra={"ui:hidden": True})


class ListSessionPages(_Session):
    operation: Literal["list_session_pages"] = Field("list_session_pages", title="List Session Pages", json_schema_extra={"ui:hidden": True})


class ListSessionDownloads(_Session):
    operation: Literal["list_session_downloads"] = Field("list_session_downloads", title="List Session Downloads", description="Returns download metadata and links, without downloading files.", json_schema_extra={"ui:hidden": True})


class ListSessionRecordings(_Session):
    operation: Literal["list_session_recordings"] = Field("list_session_recordings", title="List Session Recordings", json_schema_extra={"ui:hidden": True})


class ListProfiles(_Input):
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Profiles", json_schema_extra={"ui:hidden": True})


class _Profile(_Input):
    name: str = Field(..., min_length=1, max_length=512, title="Profile Name")

    @field_validator("name")
    @classmethod
    def name_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a profile name without control characters or dot segments")
        return value


class GetProfile(_Profile):
    operation: Literal["get_profile"] = Field("get_profile", title="Get Profile", json_schema_extra={"ui:hidden": True})


class CreateProfile(_Profile):
    operation: Literal["create_profile"] = Field("create_profile", title="Create Profile", json_schema_extra={"ui:hidden": True})
    session_id: UUID = Field(..., description="Running session to save as a profile after the session terminates.")
    dedicated_sticky_ip: bool = False


class DeleteProfile(_Profile):
    operation: Literal["delete_profile"] = Field("delete_profile", title="Delete Profile", description="Deletes the named persistent profile.", json_schema_extra={"ui:hidden": True})


class PerformWebTask(_Input):
    operation: Literal["perform_web_task"] = Field("perform_web_task", title="Perform Web Task", description="Run a natural-language task. The task may change websites and consume credits; inspect before retrying.", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, title="Task Prompt", json_schema_extra={"ui:widget": "textarea"})
    session_id: str | None = Field(None, title="Existing Session ID")
    url: str | None = Field(None, title="Starting URL")
    run_async: bool = Field(True, title="Run Asynchronously", description="Returns a workflow ID; use Get Web Task Status to poll.")
    max_steps: int | None = Field(None, ge=1)
    output_schema: dict | None = Field(None, title="Output JSON Schema")


class GetWebTaskStatus(_Input):
    operation: Literal["get_web_task_status"] = Field("get_web_task_status", title="Get Web Task Status", json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")


class ExecuteCode(_BrowserSession):
    operation: Literal["execute_code"] = Field("execute_code", title="Execute Code", description="Executes code against the selected browser session; it may change websites.", json_schema_extra={"ui:hidden": True})
    code: str = Field(..., min_length=1, title="Code", json_schema_extra={"ui:widget": "code_editor"})


class Navigate(_BrowserSession):
    operation: Literal["navigate"] = Field("navigate", title="Navigate to URL", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, title="URL")


class TypeText(_BrowserSession):
    operation: Literal["type_text"] = Field("type_text", title="Type Text", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., title="Text")
    delay: int | None = Field(None, ge=0, description="Delay between keystrokes in milliseconds.")


class KeyboardShortcut(_BrowserSession):
    operation: Literal["keyboard_shortcut"] = Field("keyboard_shortcut", title="Keyboard Shortcut", json_schema_extra={"ui:hidden": True})
    keys: list[str] = Field(..., min_length=1, title="Keys")
    hold_time: int | None = Field(None, ge=0, description="Hold time in milliseconds.")


class Click(_BrowserSession):
    operation: Literal["click"] = Field("click", title="Click Element", json_schema_extra={"ui:hidden": True})
    selector: str = Field(..., min_length=1, title="CSS Selector")
    button: Literal["left", "middle", "right"] = "left"
    timeout: int | None = Field(None, ge=0, description="Wait for the selector in milliseconds.")
    index: int | None = Field(None, ge=0, description="Zero-based index when several elements match.")


class Scroll(_BrowserSession):
    operation: Literal["scroll"] = Field("scroll", title="Scroll", json_schema_extra={"ui:hidden": True})
    x: int = Field(..., title="X Coordinate")
    y: int = Field(..., title="Y Coordinate")
    delta_y: int = Field(..., title="Vertical Scroll Amount")
    delta_x: int | None = Field(None, title="Horizontal Scroll Amount")
    steps: int | None = Field(None, ge=1)
    use_os: bool | None = None


class GetClipboard(_BrowserSession):
    operation: Literal["get_clipboard"] = Field("get_clipboard", title="Get Clipboard", json_schema_extra={"ui:hidden": True})


class SetClipboard(_BrowserSession):
    operation: Literal["set_clipboard"] = Field("set_clipboard", title="Set Clipboard", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., title="Text")


Operation = Annotated[Union[ListSessions, StartSession, GetSession, EndSession, ListSessionPages,
    ListSessionDownloads, ListSessionRecordings, ListProfiles, GetProfile, CreateProfile, DeleteProfile,
    PerformWebTask, GetWebTaskStatus, ExecuteCode, Navigate, TypeText, KeyboardShortcut, Click, Scroll,
    GetClipboard, SetClipboard], Field(discriminator="operation")]


class AnchorBrowserNodeConfig(NodeConfig[Operation, AnchorBrowserAPIKeyCredential]):
    pass


def _request_parts(op):
    """Map each typed operation to exactly one provider operation."""
    values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    if isinstance(op, ListSessions):
        return "GET", "/v1/sessions", values, None
    if isinstance(op, StartSession):
        session = {"recording": {"active": op.recording}, "timeout": {"max_duration": op.max_duration, "idle_timeout": op.idle_timeout}}
        for key in ("initial_url", "tags"):
            if key in values:
                session[key] = values[key]
        browser = {"headless": {"active": op.headless}}
        if op.profile_name is not None:
            browser["profile"] = {"name": op.profile_name, "persist": op.persist_profile}
        return "POST", "/v1/sessions", {}, {"session": session, "browser": browser}
    if isinstance(op, (ListProfiles, CreateProfile)):
        return ("POST", "/v1/profiles", {}, {"source": "session", **values}) if isinstance(op, CreateProfile) else ("GET", "/v1/profiles", {}, None)
    if isinstance(op, (GetProfile, DeleteProfile)):
        return "DELETE" if isinstance(op, DeleteProfile) else "GET", "/v1/profiles/" + quote(op.name, safe=""), {}, None
    if isinstance(op, PerformWebTask):
        session_id = values.pop("session_id", None)
        values["async"] = values.pop("run_async")
        return "POST", "/v1/tools/perform-web-task", {"sessionId": session_id} if session_id else {}, values
    if isinstance(op, GetWebTaskStatus):
        return "GET", "/v1/tools/perform-web-task/" + quote(op.workflow_id, safe="") + "/status", {}, None
    session_id = values.pop("session_id")
    if isinstance(op, ExecuteCode):
        return "POST", "/v1/tools/execute-code", {"sessionId": session_id}, values
    route = "/v1/sessions/" + quote(session_id, safe="")
    suffix = {"get_session": "", "end_session": "", "list_session_pages": "/pages", "list_session_downloads": "/downloads",
        "list_session_recordings": "/recordings", "navigate": "/goto", "type_text": "/keyboard/type",
        "keyboard_shortcut": "/keyboard/shortcut", "click": "/mouse/click", "scroll": "/scroll",
        "get_clipboard": "/clipboard", "set_clipboard": "/clipboard"}[op.operation]
    method = "DELETE" if isinstance(op, EndSession) else "GET" if isinstance(op, (GetSession, ListSessionPages, ListSessionDownloads, ListSessionRecordings, GetClipboard)) else "POST"
    for source, target in {"hold_time": "holdTime", "delta_y": "deltaY", "delta_x": "deltaX", "use_os": "useOs"}.items():
        if source in values:
            values[target] = values.pop(source)
    return method, route + suffix, {}, values if method == "POST" else None


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value


class AnchorBrowserNode(WorkflowNode):
    integration_type = "automation-anchor-browser"
    connection_evidence = ConnectionEvidence(noun="browser sessions", operation="list_sessions")

    @classmethod
    def get_config_model(cls):
        return AnchorBrowserNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Anchor Browser API key")
        credential, op = self.config.credentials, self.config.config
        method, route, params, body = _request_parts(op)
        output = {"operation": op.operation}
        try:
            async with guarded_async_client(timeout=httpx.Timeout(120.0), trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, BASE + route, headers={"anchor-api-key": credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("Anchor Browser response exceeds 8 MiB")
                    output["http_status"] = response.status_code
                    if not 200 <= response.status_code < 300:
                        message = "Anchor Browser rejected the request"
                        try:
                            failure = json.loads(raw)
                            error = failure.get("error", failure.get("message"))
                            if isinstance(error, dict):
                                error = error.get("message")
                            if isinstance(error, str) and error:
                                message = error
                        except (ValueError, AttributeError):
                            pass
                        return _redact({**output, "status": "error", "error": message}, credential.api_key)
                    payload = json.loads(raw)
            if not isinstance(payload, dict) or not payload:
                raise ValueError("Anchor Browser returned an unexpected JSON response")
            if payload.get("error") or payload.get("success") is False or payload.get("status") in {"error", "failed"}:
                return _redact({**output, "status": "error", "error": payload.get("error") or payload.get("message") or "Anchor Browser action failed"}, credential.api_key)
            data = payload.get("data", payload)
            if isinstance(op, ListSessions):
                if not isinstance(data, dict) or not isinstance(data.get("sessions"), list) or not all(k in data for k in ("page", "total_pages", "total")):
                    raise ValueError("Anchor Browser returned incomplete session pagination")
                return _redact({**output, "status": "success", "data": data, "items": data["sessions"],
                    "next_page": data["page"] + 1 if data["page"] < data["total_pages"] else None}, credential.api_key)
            return _redact({**output, "status": "success", "data": data}, credential.api_key)
        except (ValueError, TypeError, httpx.HTTPError, SSRFError, OSError):
            return {**output, "status": "error", "error": "Anchor Browser request did not complete or returned an unexpected response; inspect before retrying an action"}
