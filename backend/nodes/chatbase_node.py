"""Chatbase API v2: one documented request per workflow operation.

Contract: https://www.chatbase.co/docs/api-v2-openapi.json (2.0.0).
Lists return a single page and the provider's pagination cursor unchanged.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://www.chatbase.co/api/v2"


class ChatbaseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Chatbase API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.chatbase.co/dashboard",
            "x-credential-instructions": "In Chatbase, open Workspace settings → API keys and create an API key. Paste it here without the Bearer prefix. API access requires an eligible Chatbase plan. NoClick verifies the key by listing your agents.",
        })
    credential_type: Literal["chatbase_api_key"] = Field("chatbase_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Agent(_Input):
    agent_id: str = Field(..., min_length=1, max_length=512, title="Agent ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "agent_id", "searchable": True, "allow_custom": True}})


class _Page(_Input):
    cursor: str | None = Field(None, max_length=4096, description="Use pagination.cursor from the preceding page, keeping filters unchanged.")
    limit: int = Field(20, ge=1, le=100)


class _AgentPage(_Agent, _Page):
    pass


class _Conversation(_Agent):
    conversation_id: str = Field(..., min_length=1, max_length=512)


class _Source(_Agent):
    source_id: str = Field(..., min_length=1, max_length=512)


class _Ticket(_Agent):
    ticket_number: int = Field(..., gt=0, le=2147483647)


class ListAgents(_Page):
    """List one page of agents owned by this API key."""
    operation: Literal["list_agents"] = "list_agents"


class CreateAgent(_Input):
    """Create an agent. Any returned pendingSteps still require attention."""
    operation: Literal["create_agent"] = "create_agent"
    name: str = Field(..., min_length=1, max_length=100)
    instructions: str | None = Field(None, max_length=30000)
    temp: float | None = Field(None, ge=0, le=1)
    visibility: Literal["public", "private"] = "private"


class GetAgent(_Agent):
    operation: Literal["get_agent"] = "get_agent"


class UpdateAgent(_Agent):
    """Update the agent's name and optionally instructions and visibility."""
    operation: Literal["update_agent"] = "update_agent"
    name: str = Field(..., min_length=1, max_length=100)
    instructions: str | None = Field(None, max_length=30000)
    temp: float | None = Field(None, ge=0, le=1)
    visibility: Literal["public", "private"] | None = None


class DeleteAgent(_Agent):
    """Permanently delete the selected agent."""
    operation: Literal["delete_agent"] = "delete_agent"


class Chat(_Agent):
    """Send a message, consuming Chatbase credits; returns JSON without streaming."""
    operation: Literal["chat"] = "chat"
    message: str = Field(..., min_length=1)
    conversationId: str | None = None
    userId: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")


class ListConversations(_AgentPage):
    operation: Literal["list_conversations"] = "list_conversations"
    startDate: str | None = Field(None, description="YYYY-MM-DD or ISO 8601; inclusive UTC lower bound.")
    endDate: str | None = Field(None, description="YYYY-MM-DD or ISO 8601; inclusive UTC upper bound.")


class SearchConversations(_AgentPage):
    operation: Literal["search_conversations"] = "search_conversations"
    limit: int = Field(25, ge=1, le=25)
    query: str = Field(..., min_length=1, max_length=512)
    startDate: str | None = None
    endDate: str | None = None
    sentiment: str | None = Field(None, description="Comma-separated positive, neutral, negative, unspecified.")
    topic: str | None = None
    source: str | None = None


class GetConversation(_Conversation):
    operation: Literal["get_conversation"] = "get_conversation"


class UpdateConversation(_Conversation):
    operation: Literal["update_conversation"] = "update_conversation"
    status: Literal["ongoing", "paused", "ended"]


class DeleteConversation(_Conversation):
    operation: Literal["delete_conversation"] = "delete_conversation"


class ListConversationMessages(_Conversation, _Page):
    operation: Literal["list_conversation_messages"] = "list_conversation_messages"


class ListUserConversations(_AgentPage):
    operation: Literal["list_user_conversations"] = "list_user_conversations"
    user_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")


class GetSourcesSummary(_Agent):
    operation: Literal["get_sources_summary"] = "get_sources_summary"


class ListSources(_AgentPage):
    operation: Literal["list_sources"] = "list_sources"
    type: str | None = Field(None, description="Comma-separated link, file, qna, notionPage, text.")
    name: str | None = Field(None, description="Case-insensitive partial name filter.")


class CreateTextSource(_Agent):
    """Create a text knowledge source; training state remains provider reported."""
    operation: Literal["create_text_source"] = "create_text_source"
    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=1048576, json_schema_extra={"ui:widget": "textarea"})


class GetSource(_Source):
    operation: Literal["get_source"] = "get_source"


class DeleteSource(_Source):
    operation: Literal["delete_source"] = "delete_source"


class UpdateTextSource(_Source):
    """Replace a text source's content and optionally its name."""
    operation: Literal["update_text_source"] = "update_text_source"
    name: str | None = Field(None, min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=1048576, json_schema_extra={"ui:widget": "textarea"})


class ListTicketStatuses(_Agent):
    operation: Literal["list_ticket_statuses"] = "list_ticket_statuses"


class SearchTickets(_Agent):
    """Find support tickets by text in their messages."""
    operation: Literal["search_tickets"] = "search_tickets"
    query: str = Field(..., min_length=1, max_length=512)
    limit: int = Field(20, ge=1, le=50)


class GetTicket(_Ticket):
    operation: Literal["get_ticket"] = "get_ticket"


class CreateTicket(_Agent):
    """Create a support ticket with the first customer message."""
    operation: Literal["create_ticket"] = "create_ticket"
    subject: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=10000)
    customer_email: str = Field(..., json_schema_extra={"format": "email"})
    customer_name: str | None = Field(None, max_length=255)
    statusCategory: Literal["new", "on_you", "on_customer", "on_hold", "closed", "cancelled"] | None = None
    priority: Literal["none", "low", "normal", "high", "urgent"] | None = None


class UpdateTicket(_Ticket):
    """Change ticket status and optionally priority."""
    operation: Literal["update_ticket"] = "update_ticket"
    statusCategory: Literal["new", "on_you", "on_customer", "on_hold", "closed", "cancelled"]
    priority: Literal["none", "low", "normal", "high", "urgent"] | None = None


class ListTicketMessages(_Ticket, _Page):
    operation: Literal["list_ticket_messages"] = "list_ticket_messages"
    types: str = Field("reply,note", description="Comma-separated reply, note, event.")
    order: Literal["asc", "desc"] = "asc"


# Chatbase's own MCP server: agents get its tools through a person's Chatbase sign-in.
ChatbaseMcpCredential = mcp_credential("chatbase", "https://mcp.chatbase.co/api/mcp", app="Chatbase")
ChatbaseCredential = Union[ChatbaseAPIKeyCredential, ChatbaseMcpCredential]


Operation = Annotated[Union[ListAgents, CreateAgent, GetAgent, UpdateAgent, DeleteAgent, Chat,
    ListConversations, SearchConversations, GetConversation, UpdateConversation, DeleteConversation,
    ListConversationMessages, ListUserConversations, GetSourcesSummary, ListSources, CreateTextSource,
    GetSource, DeleteSource, UpdateTextSource, ListTicketStatuses, SearchTickets, GetTicket, CreateTicket,
    UpdateTicket, ListTicketMessages], Field(discriminator="operation")]


class ChatbaseConfig(NodeConfig[Operation, ChatbaseCredential]):
    pass


# method, fixed provider path, query fields, JSON fields
ROUTES = {
    "list_agents": ("GET", "/agents", ("cursor", "limit"), ()),
    "create_agent": ("POST", "/agents", (), ("name", "instructions", "temp", "visibility")),
    "get_agent": ("GET", "/agents/{agent_id}", (), ()),
    "update_agent": ("PUT", "/agents/{agent_id}", (), ("name", "instructions", "temp", "visibility")),
    "delete_agent": ("DELETE", "/agents/{agent_id}", (), ()),
    "chat": ("POST", "/agents/{agent_id}/chat", (), ("message", "conversationId", "userId")),
    "list_conversations": ("GET", "/agents/{agent_id}/conversations", ("cursor", "limit", "startDate", "endDate"), ()),
    "search_conversations": ("GET", "/agents/{agent_id}/conversations/search", ("cursor", "limit", "query", "startDate", "endDate", "sentiment", "topic", "source"), ()),
    "get_conversation": ("GET", "/agents/{agent_id}/conversations/{conversation_id}", (), ()),
    "update_conversation": ("PATCH", "/agents/{agent_id}/conversations/{conversation_id}", (), ("status",)),
    "delete_conversation": ("DELETE", "/agents/{agent_id}/conversations/{conversation_id}", (), ()),
    "list_conversation_messages": ("GET", "/agents/{agent_id}/conversations/{conversation_id}/messages", ("cursor", "limit"), ()),
    "list_user_conversations": ("GET", "/agents/{agent_id}/users/{user_id}/conversations", ("cursor", "limit"), ()),
    "get_sources_summary": ("GET", "/agents/{agent_id}/sources/summary", (), ()),
    "list_sources": ("GET", "/agents/{agent_id}/sources", ("cursor", "limit", "type", "name"), ()),
    "create_text_source": ("POST", "/agents/{agent_id}/sources", (), ("name", "content")),
    "get_source": ("GET", "/agents/{agent_id}/sources/{source_id}", (), ()),
    "delete_source": ("DELETE", "/agents/{agent_id}/sources/{source_id}", (), ()),
    "update_text_source": ("PUT", "/agents/{agent_id}/sources/{source_id}", (), ("name", "content")),
    "list_ticket_statuses": ("GET", "/agents/{agent_id}/helpdesk/ticket-statuses", (), ()),
    "search_tickets": ("POST", "/agents/{agent_id}/helpdesk/tickets/search", (), ("query", "limit")),
    "get_ticket": ("GET", "/agents/{agent_id}/helpdesk/tickets/{ticket_number}", (), ()),
    "create_ticket": ("POST", "/agents/{agent_id}/helpdesk/tickets", (), ("subject", "description", "statusCategory", "priority")),
    "update_ticket": ("PATCH", "/agents/{agent_id}/helpdesk/tickets/{ticket_number}", (), ("statusCategory", "priority")),
    "list_ticket_messages": ("GET", "/agents/{agent_id}/helpdesk/tickets/{ticket_number}/messages", ("cursor", "limit", "types", "order"), ()),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class ChatbaseNode(WorkflowNode):
    integration_type = "automation-chatbase"
    credential_provider_labels = {"chatbase": "Chatbase Account"}
    connection_evidence = ConnectionEvidence(field="agent_id", noun="Chatbase agents")

    @classmethod
    def get_config_model(cls):
        return ChatbaseConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, *, page_token=None, search=None):
        if field_name != "agent_id":
            raise ValueError("Unknown Chatbase choice field")
        from nodes.core.registry import NodeFactory
        credential = ChatbaseAPIKeyCredential.model_validate(credential_data)
        node = NodeFactory.create_node(node_id="chatbase-options", node_type=cls.integration_type,
            node_data={"config": {"operation": "list_agents", "limit": 100, "cursor": page_token}, "credentials": credential.model_dump()})
        result = await node.execute({})
        if result.get("status") != "success":
            raise ValueError(result.get("error", "Chatbase agents could not be read"))
        payload = result["data"]
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"]}
                for row in payload["data"] if not search or search.casefold() in (row.get("name") or row["id"]).casefold()],
            "next_page_token": payload["pagination"]["cursor"]}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Chatbase API key")
        config = self.config.config
        key = self.config.credentials.api_key
        values = config.model_dump(mode="json", exclude_none=True)
        method, route, query_fields, body_fields = ROUTES[config.operation]
        for name in ("agent_id", "conversation_id", "source_id", "user_id", "ticket_number"):
            if "{" + name + "}" in route:
                value = str(values[name])
                if value in {".", ".."} or any(c in value for c in "/\\?#"):
                    raise ValueError("Use a single Chatbase resource ID")
                route = route.replace("{" + name + "}", quote(value, safe=""))
        params = {name: values[name] for name in query_fields if name in values}
        body = {name: values[name] for name in body_fields if name in values}
        if config.operation == "chat":
            body["stream"] = False
        if config.operation == "create_text_source":
            body["type"] = "text"
        if config.operation == "create_ticket":
            body["customer"] = {"email": config.customer_email, **({"name": config.customer_name} if config.customer_name is not None else {})}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, params=params,
                    **({"json": body} if method in {"POST", "PUT", "PATCH"} else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 10_000_000:
                            raise ValueError("Chatbase response exceeds the supported size")
                    status = response.status_code
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        payload = None
                    if not 200 <= status < 300:
                        error = payload.get("error") if isinstance(payload, dict) else None
                        message = error.get("message") if isinstance(error, dict) else error
                        output = {"status": "error", "status_code": status,
                            "error": message if isinstance(message, str) else "Chatbase request rejected"}
                    else:
                        media = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        if media != "application/json" or not isinstance(payload, (dict, list)):
                            raise ValueError("Expected a JSON response from Chatbase")
                        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors") or payload.get("success") is False):
                            raise ValueError("Chatbase reported an unsuccessful operation")
                        if config.operation == "list_agents" and (not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not isinstance(payload.get("pagination"), dict)):
                            raise ValueError("Chatbase did not return an agent page")
                        output = {"status": "success", "data": payload}
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Chatbase request did not complete; inspect the provider before retrying a write") from None
        output = _redact(output, key)
        await self.emit(output)
        return output
