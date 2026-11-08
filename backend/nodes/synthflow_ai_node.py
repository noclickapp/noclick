"""Synthflow v2 calls, agents, contacts, knowledge bases and actions.

Each operation makes one documented request. Pagination and provider response
metadata are retained so workflows can explicitly request the next page.
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


class SynthflowAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Synthflow AI API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.synthflow.ai/getting-started-with-your-api",
            "x-credential-instructions": "Paste your Synthflow API key from the dashboard. Select the region where your account's data is stored. The key is sent as a Bearer token only to that region's Synthflow API."})
    credential_type: Literal["synthflow_ai_api_key"] = Field("synthflow_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    region: Literal["global", "us", "eu"] = Field("global", title="Data Region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def path_ids(cls, value, info):
        if info.field_name in {"model_id", "call_id", "contact_id", "knowledge_base_id", "action_id", "phone_number_slug"}:
            if not value or len(value) > 256 or value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
                raise ValueError("Use a single Synthflow resource ID")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, description="Records per page. This operation returns one page.")
    offset: int = Field(0, ge=0, description="Index of the first record; advance explicitly for subsequent pages.")


class ListAgents(_Page):
    operation: Literal["list_agents"] = "list_agents"


class GetAgent(_Input):
    operation: Literal["get_agent"] = "get_agent"
    model_id: str = Field(..., min_length=1, title="Agent ID")
    include_actions: bool = False


class ListCalls(_Page):
    operation: Literal["list_calls"] = "list_calls"
    model_id: str = Field(..., min_length=1, title="Agent ID")
    from_date: int | None = Field(None, description="Start timestamp in milliseconds since epoch.")
    to_date: int | None = Field(None, description="End timestamp in milliseconds since epoch.")
    call_status: str | None = None
    lead_phone_number: str | None = None
    include_all_actions: bool = False


class GetCall(_Input):
    operation: Literal["get_call"] = "get_call"
    call_id: str = Field(..., min_length=1)
    include_all_actions: bool = False


class CustomVariable(_Input):
    key: str
    value: str


class MakeCall(_Input):
    """Start an outbound call to the supplied recipient. This can incur provider charges."""
    operation: Literal["make_call"] = "make_call"
    model_id: str = Field(..., min_length=1, title="Agent ID")
    phone: str = Field(..., min_length=1, description="Recipient phone number, preferably E.164.")
    name: str = Field(..., min_length=1, title="Recipient Name")
    from_phone_number: str | None = None
    custom_variables: list[CustomVariable] | None = None
    lead_email: str | None = None
    lead_timezone: str | None = None
    prompt: str | None = None
    greeting: str | None = None


class ListContacts(_Input):
    operation: Literal["list_contacts"] = "list_contacts"
    search: str | None = Field(None, description="Search by contact phone number.")


class GetContact(_Input):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: str = Field(..., min_length=1)


class ContactMetadata(_Input):
    company: str | None = None


class CreateContact(_Input):
    operation: Literal["create_contact"] = "create_contact"
    name: str = Field(..., min_length=1)
    phone_number: str = Field(..., min_length=1)
    email: str | None = None
    contact_metadata: ContactMetadata | None = None


class UpdateContact(_Input):
    operation: Literal["update_contact"] = "update_contact"
    contact_id: str = Field(..., min_length=1)
    name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    contact_metadata: ContactMetadata | None = None


class DeleteContact(GetContact):
    operation: Literal["delete_contact"] = "delete_contact"


class ListKnowledgeBases(_Page):
    operation: Literal["list_knowledge_bases"] = "list_knowledge_bases"
    limit: int = Field(25, ge=1)


class GetKnowledgeBase(_Input):
    operation: Literal["get_knowledge_base"] = "get_knowledge_base"
    knowledge_base_id: str = Field(..., min_length=1)


class CreateKnowledgeBase(_Input):
    operation: Literal["create_knowledge_base"] = "create_knowledge_base"
    name: str = Field(..., min_length=1)
    rag_use_condition: str | None = Field(None, description="When the agent should use this knowledge base.")


class UpdateKnowledgeBase(GetKnowledgeBase):
    operation: Literal["update_knowledge_base"] = "update_knowledge_base"
    name: str | None = None
    rag_use_condition: str | None = None


class DeleteKnowledgeBase(GetKnowledgeBase):
    operation: Literal["delete_knowledge_base"] = "delete_knowledge_base"


class ListActions(_Page):
    operation: Literal["list_actions"] = "list_actions"


class GetAction(_Input):
    operation: Literal["get_action"] = "get_action"
    action_id: str = Field(..., min_length=1)
    include_assistants: bool = False


class DeleteAction(_Input):
    operation: Literal["delete_action"] = "delete_action"
    action_id: str = Field(..., min_length=1)


class ListPhoneNumbers(_Page):
    operation: Literal["list_phone_numbers"] = "list_phone_numbers"
    workspace: str = Field(..., min_length=1, title="Workspace ID")
    is_available: bool | None = None


class GetPhoneNumber(_Input):
    operation: Literal["get_phone_number"] = "get_phone_number"
    phone_number_slug: str = Field(..., min_length=1, description="Phone number without the leading +.")
    workspace: str = Field(..., min_length=1, title="Workspace ID")


SynthflowAiConfig = Annotated[Union[ListAgents, GetAgent, ListCalls, GetCall, MakeCall,
    ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact,
    ListKnowledgeBases, GetKnowledgeBase, CreateKnowledgeBase, UpdateKnowledgeBase, DeleteKnowledgeBase,
    ListActions, GetAction, DeleteAction, ListPhoneNumbers, GetPhoneNumber], Field(discriminator="operation")]


class SynthflowAiFullConfig(NodeConfig[SynthflowAiConfig, SynthflowAiAPIKeyCredential]):
    pass


# Each entry is exactly one method/path in https://docs.synthflow.ai/openapi.json.
ROUTES = {
    "list_agents": ("GET", "/assistants/", None),
    "get_agent": ("GET", "/assistants/{model_id}", "model_id"),
    "list_calls": ("GET", "/calls", None),
    "get_call": ("GET", "/calls/{call_id}", "call_id"),
    "make_call": ("POST", "/calls", None),
    "list_contacts": ("GET", "/contacts", None),
    "get_contact": ("GET", "/contacts/{contact_id}", "contact_id"),
    "create_contact": ("POST", "/contacts", None),
    "update_contact": ("PATCH", "/contacts/{contact_id}", "contact_id"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}", "contact_id"),
    "list_knowledge_bases": ("GET", "/knowledge_base", None),
    "get_knowledge_base": ("GET", "/knowledge_base/{knowledge_base_id}", "knowledge_base_id"),
    "create_knowledge_base": ("POST", "/knowledge_base", None),
    "update_knowledge_base": ("PUT", "/knowledge_base/{knowledge_base_id}", "knowledge_base_id"),
    "delete_knowledge_base": ("DELETE", "/knowledge_base/{knowledge_base_id}", "knowledge_base_id"),
    "list_actions": ("GET", "/actions", None),
    "get_action": ("GET", "/actions/{action_id}", "action_id"),
    "delete_action": ("DELETE", "/actions/{action_id}", "action_id"),
    "list_phone_numbers": ("GET", "/numbers", None),
    "get_phone_number": ("GET", "/numbers/{phone_number_slug}", "phone_number_slug"),
}
BASES = {"global": "https://api.synthflow.ai/v2", "us": "https://api.us.synthflow.ai/v2", "eu": "https://api.eu.synthflow.ai/v2"}


class SynthflowAiNode(WorkflowNode):
    integration_type = "automation-synthflow-ai"
    connection_evidence = ConnectionEvidence(noun="agents", operation="list_agents")

    @classmethod
    def get_config_model(cls):
        return SynthflowAiFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Synthflow AI API key")
        credential = self.config.credentials
        config = self.config.config
        method, path, id_field = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if id_field:
            path = path.replace("{" + id_field + "}", quote(values.pop(id_field), safe=""))
        kwargs = {"params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}} if method == "GET" else {"json": values} if method in {"POST", "PUT", "PATCH"} else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASES[credential.region] + path,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **kwargs)
            if len(response.content) > 10_000_000:
                raise ValueError("Synthflow response exceeds the JSON size limit")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json":
                raise ValueError("Expected a Synthflow JSON response")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a Synthflow JSON object")
            # Retain the provider envelope, including pagination and acknowledgement-only writes.
            if response.status_code >= 300 or str(body.get("status", "")).lower() in {"error", "failed", "failure"}:
                message = body.get("message") or body.get("error") or body.get("detail") or "Synthflow rejected the request"
                return {"status": "error", "http_status": response.status_code, "error": str(message).replace(credential.api_key, "[redacted]")}
            # Phone-number detail is a bare record, unlike the other v2 envelopes.
            if config.operation == "get_phone_number":
                if not isinstance(body.get("slug"), str) or not body["slug"]:
                    raise ValueError("Synthflow phone-number response is missing its slug")
            elif not isinstance(body.get("status"), str) or not body["status"]:
                raise ValueError("Synthflow response is missing its status")
            return {"status": "success", "http_status": response.status_code, "data": _redact(body, credential.api_key)}
        except ValueError:
            return {"status": "error", "error": "Synthflow returned an invalid JSON response; inspect the provider before retrying writes"}
        except httpx.HTTPError:
            return {"status": "error", "error": "Synthflow request could not be completed; inspect the provider before retrying writes"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value
