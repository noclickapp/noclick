"""Browserbase's published v1 browser infrastructure API. Each operation makes
one provider request; account projects also prove a pasted API key on connect.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

# Current API origin: https://docs.browserbase.com/reference/api/list-projects.md
# The pinned SDK contract still lists the old www origin.
BASE_URL = "https://api.browserbase.com"


class BrowserbaseToolApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Browserbase Tool API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.browserbase.com/settings",
            "x-credential-instructions": "Copy your Browserbase API key from Settings and paste it below."})
    credential_type: Literal["browserbase_tool_api_key"] = Field("browserbase_tool_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", description="Your Browserbase API key, sent in the X-BB-API-Key header.", repr=False, json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Project(_Input):
    project_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Project ID", description="Copy the project ID from Browserbase Settings.")


class _Session(_Input):
    session_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Session ID")


class _Context(_Input):
    context_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Context ID")


class _Extension(_Input):
    extension_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Extension ID")


class ListProjects(_Input):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})


class GetProjectUsage(_Project):
    operation: Literal["get_project_usage"] = Field("get_project_usage", title="Get Project Usage", json_schema_extra={"ui:hidden": True})


class ListSessions(_Input):
    operation: Literal["list_sessions"] = Field("list_sessions", title="List Sessions", json_schema_extra={"ui:hidden": True})
    status: Literal["RUNNING", "ERROR", "TIMED_OUT", "COMPLETED"] | None = Field(None, title="Status Filter")


class CreateSession(_Project):
    operation: Literal["create_session"] = Field("create_session", title="Create Session", json_schema_extra={"ui:hidden": True})
    timeout: int | None = Field(None, ge=60, le=21600, title="Timeout in Seconds")
    keep_alive: bool | None = Field(None, title="Keep Alive", description="Keep the browser running after disconnecting; plan restrictions apply.")
    region: Literal["us-west-2", "us-east-1", "eu-central-1", "ap-southeast-1"] | None = Field(None, title="Region")
    extension_id: str | None = Field(None, min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Extension ID")
    context_id: str | None = Field(None, min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Context ID")
    persist_context: bool = Field(False, title="Persist Context", description="Save browsing state into the selected context after the session.")
    record_session: bool | None = Field(None, title="Record Session")
    log_session: bool | None = Field(None, title="Log Session")
    block_ads: bool | None = Field(None, title="Block Ads")
    solve_captchas: bool | None = Field(None, title="Solve Captchas")
    proxies: bool | None = Field(None, title="Use Browserbase Proxy", description="Enabling the managed proxy can incur additional charges.")


class GetSession(_Session):
    operation: Literal["get_session"] = Field("get_session", title="Get Session", json_schema_extra={"ui:hidden": True})


class ReleaseSession(_Session, _Project):
    operation: Literal["release_session"] = Field("release_session", title="Release Session", json_schema_extra={"ui:hidden": True})


class GetSessionLiveUrls(_Session):
    operation: Literal["get_session_live_urls"] = Field("get_session_live_urls", title="Get Session Live URLs", json_schema_extra={"ui:hidden": True})


class GetSessionLogs(_Session):
    operation: Literal["get_session_logs"] = Field("get_session_logs", title="Get Session Logs", json_schema_extra={"ui:hidden": True})


class CreateContext(_Project):
    operation: Literal["create_context"] = Field("create_context", title="Create Context", json_schema_extra={"ui:hidden": True})


class GetContext(_Context):
    operation: Literal["get_context"] = Field("get_context", title="Get Context", json_schema_extra={"ui:hidden": True})


class GetExtension(_Extension):
    operation: Literal["get_extension"] = Field("get_extension", title="Get Extension", json_schema_extra={"ui:hidden": True})


class DeleteExtension(_Extension):
    operation: Literal["delete_extension"] = Field("delete_extension", title="Delete Extension", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListProjects, GetProject, GetProjectUsage, ListSessions, CreateSession, GetSession, ReleaseSession, GetSessionLiveUrls, GetSessionLogs, CreateContext, GetContext, GetExtension, DeleteExtension], Field(discriminator="operation")]


class BrowserbaseToolNodeConfig(NodeConfig[Operation, BrowserbaseToolApiKeyCredential]):
    pass


ROUTES = {'list_projects': ('GET', '/v1/projects'),
 'get_project': ('GET', '/v1/projects/{project_id}'),
 'get_project_usage': ('GET', '/v1/projects/{project_id}/usage'),
 'list_sessions': ('GET', '/v1/sessions'),
 'create_session': ('POST', '/v1/sessions'),
 'get_session': ('GET', '/v1/sessions/{session_id}'),
 'release_session': ('POST', '/v1/sessions/{session_id}'),
 'get_session_live_urls': ('GET', '/v1/sessions/{session_id}/debug'),
 'get_session_logs': ('GET', '/v1/sessions/{session_id}/logs'),
 'create_context': ('POST', '/v1/contexts'),
 'get_context': ('GET', '/v1/contexts/{context_id}'),
 'get_extension': ('GET', '/v1/extensions/{extension_id}'),
 'delete_extension': ('DELETE', '/v1/extensions/{extension_id}')}


class BrowserbaseToolNode(WorkflowNode):
    integration_type = "automation-browserbase-tool"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects")

    @classmethod
    def get_config_model(cls):
        return BrowserbaseToolNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Browserbase API key")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        operation = config.operation
        method, template = ROUTES[operation]
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params = {"status": config.status} if operation == "list_sessions" and config.status else {}
        body = None
        if operation in {"create_session", "create_context", "release_session"}:
            body = {"projectId": config.project_id}
        if operation == "release_session":
            body["status"] = "REQUEST_RELEASE"
        if operation == "create_session":
            for field, key in {"timeout": "timeout", "keep_alive": "keepAlive", "region": "region", "extension_id": "extensionId", "proxies": "proxies"}.items():
                if field in values:
                    body[key] = values[field]
            settings = {}
            for field, key in {"record_session": "recordSession", "log_session": "logSession", "block_ads": "blockAds", "solve_captchas": "solveCaptchas"}.items():
                if field in values:
                    settings[key] = values[field]
            if config.context_id:
                settings["context"] = {"id": config.context_id, "persist": config.persist_context}
            if settings:
                body["browserSettings"] = settings
        headers = {"X-BB-API-Key": self.config.credentials.api_key, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        if operation == "delete_extension":
            return {"status": "success", "deleted": True, "extension_id": config.extension_id}
        data = response.json()
        if operation in {"list_projects", "list_sessions", "get_session_logs"}:
            if not isinstance(data, list):
                raise ValueError("Browserbase returned an unexpected list response")
            return {"status": "success", "items": data}
        if not isinstance(data, dict):
            raise ValueError("Browserbase returned an unexpected object response")
        return {"status": "success", "data": data}
