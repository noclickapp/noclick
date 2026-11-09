"""Automate Convolo Ai (Brightcall) Dialer using its published external API.

Each operation sends one documented request; responses retain provider pagination
and version information so workflows can continue pages and make guarded edits.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.dialer.brightcall.ai"
DOCS = BASE + "/convolo-external-api-json"
NODE_TYPE = "automation-convolo-ai"


class ConvoloAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Convolo Ai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.brightcall.ai/",
            "x-credential-instructions": "Paste your Brightcall Dialer API key. For connection evidence allow dialer.projects:read. Allow dialer.contacts:read/write, dialer.ai-agent:read/write, dialer.numbers:read and dialer.ai:read for the operations you use. NoClick sends the key in the api-key header only to api.dialer.brightcall.ai.",
        })
    credential_type: Literal["convolo_ai_api_key"] = Field("convolo_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Operation):
    page: int = Field(1, ge=1, description="One page per run; increment to read the next page.")
    items_per_page: int = Field(50, ge=1, le=500)
    search: str | None = None


class Project(Operation):
    project_id: int = Field(..., ge=1, description="Brightcall Dialer project ID")


class ListProjects(Page):
    operation: Literal["list_projects"] = "list_projects"
    archive: Literal["archived", "nonArchived"] | None = None


class GetProject(Project):
    operation: Literal["get_project"] = "get_project"


class ListContacts(Page, Project):
    operation: Literal["list_contacts"] = "list_contacts"
    state: Literal["ready", "paused", "finished", "failed", "called"] | None = None


class Contact(Project):
    contact_id: int = Field(..., ge=1)


class GetContact(Contact):
    operation: Literal["get_contact"] = "get_contact"


class ListProjectColumns(Project):
    operation: Literal["list_project_columns"] = "list_project_columns"


class AddContact(Project):
    operation: Literal["add_contact"] = "add_contact"
    contact: dict[str, str | int | float] = Field(..., min_length=1,
        description="Map exact column names from List Project Columns to values. Include the project's main phone column; unknown names and empty values are silently dropped by Brightcall.")
    add_duplicates: bool = False


class ContactValue(Operation):
    columnId: int = Field(..., ge=1, title="Column ID")
    value: str


class UpdateContact(Contact):
    operation: Literal["update_contact"] = "update_contact"
    contact_data: list[ContactValue] = Field(..., min_length=1, description="Column IDs and values to update.")


class ListAiAgents(Operation):
    operation: Literal["list_ai_agents"] = "list_ai_agents"


class GetAiAgent(Project):
    operation: Literal["get_ai_agent"] = "get_ai_agent"


class PromptChanges(Operation):
    script: str | None = Field(None, max_length=100000)
    instructions: str | None = Field(None, max_length=100000)
    knowledgeBase: str | None = Field(None, max_length=100000)
    personalityStart: str | None = Field(None, max_length=20000)
    personalityEnd: str | None = Field(None, max_length=20000)


class GreetingChanges(Operation):
    default: str | None = Field(None, max_length=2000)
    inbound: str | None = Field(None, max_length=2000)
    outbound: str | None = Field(None, max_length=2000)
    delaySeconds: int | None = Field(None, ge=0, le=60)


class Versioned(Project):
    version: str = Field(..., min_length=1, max_length=512, description="Current version returned by Get AI Agent. A stale version is rejected without saving.")
    dry_run: bool = Field(False, description="Validate without saving.")
    comment: str | None = Field(None, max_length=500)


class UpdateAiAgent(Versioned):
    operation: Literal["update_ai_agent"] = "update_ai_agent"
    prompt: PromptChanges | None = None
    greeting: GreetingChanges | None = None
    language: str | None = None
    voice: str | None = Field(None, max_length=100)


class ListAiAgentHistory(Project):
    operation: Literal["list_ai_agent_history"] = "list_ai_agent_history"
    limit: int = Field(20, ge=1, le=50)


class AgentVersion(Project):
    version_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    before: bool = False


class GetAiAgentVersion(AgentVersion):
    operation: Literal["get_ai_agent_version"] = "get_ai_agent_version"


class RevertAiAgent(Versioned, AgentVersion):
    operation: Literal["revert_ai_agent"] = "revert_ai_agent"


class ListAiAgentCalls(Project):
    operation: Literal["list_ai_agent_calls"] = "list_ai_agent_calls"
    limit: int = Field(20, ge=1, le=50)
    cursor: str | None = Field(None, max_length=4096, description="nextCursor from the previous response.")


class GetAiAgentCall(Project):
    operation: Literal["get_ai_agent_call"] = "get_ai_agent_call"
    call_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class ListNumbers(Page):
    operation: Literal["list_numbers"] = "list_numbers"


class ListInboundCallTrees(Operation):
    operation: Literal["list_inbound_call_trees"] = "list_inbound_call_trees"
    search: str | None = None


class ListOutboundCallTrees(Operation):
    operation: Literal["list_outbound_call_trees"] = "list_outbound_call_trees"


class SetProjectAutoplay(Project):
    operation: Literal["set_project_autoplay"] = "set_project_autoplay"
    enabled: bool = Field(..., description="Start or stop automatic calling. Starting stops other projects using the same AI agent.")


ConvoloAiOperation = Annotated[Union[
    ListProjects, GetProject, ListContacts, GetContact, ListProjectColumns,
    AddContact, UpdateContact, ListAiAgents, GetAiAgent, UpdateAiAgent,
    ListAiAgentHistory, GetAiAgentVersion, RevertAiAgent, ListAiAgentCalls,
    GetAiAgentCall, ListNumbers, ListInboundCallTrees, ListOutboundCallTrees,
    SetProjectAutoplay,
], Field(discriminator="operation")]


class ConvoloAiNodeConfig(NodeConfig[ConvoloAiOperation, ConvoloAiAPIKeyCredential]):
    pass


# One operation maps to one provider method/path, including the API's singular project route.
ROUTES = {
    "list_projects": ("GET", "/api/v3/projects"),
    "get_project": ("GET", "/api/v3/project/{project_id}"),
    "list_contacts": ("GET", "/api/v1/project-contacts/{project_id}"),
    "get_contact": ("GET", "/api/v1/project-contacts/{project_id}/{contact_id}"),
    "list_project_columns": ("GET", "/api/v1/project-columns/{project_id}"),
    "add_contact": ("POST", "/api/v1/project-contacts/{project_id}/add"),
    "update_contact": ("PATCH", "/api/v1/project-contacts/{project_id}/{contact_id}"),
    "list_ai_agents": ("GET", "/api/v1/ai-agents"),
    "get_ai_agent": ("GET", "/api/v1/ai-agents/{project_id}"),
    "update_ai_agent": ("PATCH", "/api/v1/ai-agents/{project_id}"),
    "list_ai_agent_history": ("GET", "/api/v1/ai-agents/{project_id}/history"),
    "get_ai_agent_version": ("GET", "/api/v1/ai-agents/{project_id}/history/{version_id}"),
    "revert_ai_agent": ("POST", "/api/v1/ai-agents/{project_id}/revert/{version_id}"),
    "list_ai_agent_calls": ("GET", "/api/v1/ai-agents/{project_id}/calls"),
    "get_ai_agent_call": ("GET", "/api/v1/ai-agents/{project_id}/calls/{call_id}"),
    "list_numbers": ("GET", "/api/v1/sip-numbers"),
    "list_inbound_call_trees": ("GET", "/api/v1/call-trees-inbound"),
    "list_outbound_call_trees": ("GET", "/api/v1/call-trees-outbound"),
    "set_project_autoplay": ("PUT", "/api/v1/projects/autoplay/{project_id}/{autoplay_status}"),
}


def request_parts(op):
    method, template = ROUTES[op.operation]
    fields = op.model_dump()
    fields["autoplay_status"] = int(op.enabled) if isinstance(op, SetProjectAutoplay) else 0
    path = template.format_map({k: quote(str(v), safe="") for k, v in fields.items()})
    params, body = {}, None
    if isinstance(op, Page):
        params.update(page=op.page, itemsPerPage=op.items_per_page)
    if getattr(op, "search", None) is not None:
        params["searchString"] = op.search
    for field in ("archive", "state", "limit", "cursor"):
        if getattr(op, field, None) is not None:
            params[field] = getattr(op, field)
    if isinstance(op, GetAiAgentVersion):
        params["before"] = str(op.before).lower()
    if isinstance(op, AddContact):
        params["addDuplicates"] = str(op.add_duplicates).lower()
        body = op.contact
    elif isinstance(op, UpdateContact):
        body = {"contactData": [item.model_dump() for item in op.contact_data]}
    elif isinstance(op, Versioned):
        body = {"version": op.version, "dryRun": op.dry_run}
        if op.comment is not None:
            body["comment"] = op.comment
        if isinstance(op, RevertAiAgent):
            body["before"] = op.before
        else:
            # exclude_unset keeps omitted settings; explicit null clears a setting.
            for key in ("language", "voice", "prompt", "greeting"):
                if key in op.model_fields_set:
                    value = getattr(op, key)
                    if key in {"prompt", "greeting"}:
                        if value is not None:
                            body[key] = value.model_dump(exclude_unset=True)
                    else:
                        body[key] = value
    return method, path, params, body


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {redact(k, secret): redact(v, secret) for k, v in value.items()}
    return value


class ConvoloAiNode(WorkflowNode):
    integration_type = "automation-convolo-ai"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ConvoloAiNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Convolo Ai API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path, params, body = request_parts(op)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"api-key": secret, "Accept": "application/json"}, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Convolo Ai request could not complete; inspect the provider before retrying a write") from None
        if not 200 <= response.status_code < 300:
            return {"status": "error", "success": False, "http_status": response.status_code,
                "message": redact(response.text[:2000], secret)}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Convolo Ai returned a non-JSON response") from None
        if not isinstance(data, dict) or not isinstance(data.get("success"), bool):
            raise ValueError("Convolo Ai returned an unexpected response envelope")
        if not data["success"]:
            return {"status": "error", "success": False, "http_status": response.status_code, "data": redact(data, secret)}
        extra = {}
        if isinstance(op, AddContact):
            count = data.get("savedContactsCount")
            if type(count) is not int or count < 0:
                raise ValueError("Convolo Ai did not report how many contacts were saved")
            extra = {"contact_added": count > 0}
        return {"status": "success", "success": True, **extra, "action": op.operation,
            "http_status": response.status_code, "data": redact(data, secret)}
