"""SwarmSync marketplace operations, pinned to the provider's OpenAPI 1.0.

Agent API keys act as one agent and expire after 30 days. This node never
registers accounts or rotates credentials; reconnect with a renewed key.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.swarmsync.ai"
CREDENTIAL_TYPE = "swarmsyncai_api_key"


class SwarmsyncaiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Swarmsyncai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://swarmsync.ai/docs",
            "x-credential-instructions": "Paste the agentApiKey issued when you registered your SwarmSync agent. The key acts as that agent, including after a human claims it. Keys expire after 30 days; paste a renewed key when needed. Human-only billing and payout routes are not included.",
        })
    credential_type: Literal["swarmsyncai_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Agent API Key", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Agent API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the agent API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_ids(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if not value or value in {".", ".."} or any(c in value for c in "/\\%?#") or any(ord(c) < 33 for c in value):
                raise ValueError("Use a single SwarmSync resource ID")
        return value


class GetIdentity(_Input):
    """Identify the agent behind the supplied key."""
    operation: Literal["get_identity"] = Field("get_identity", title="Get Connected Identity", json_schema_extra={"ui:hidden": True})


class ListAgents(_Input):
    operation: Literal["list_agents"] = Field("list_agents", title="List Agents", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    category: str | None = None
    tag: str | None = None
    limit: int = Field(50, ge=1, le=100, description="Number of agents for this page.")
    offset: int = Field(0, ge=0)


class _Agent(_Input):
    agent_id: str = Field(..., min_length=1, title="Agent ID")


class GetAgent(_Agent):
    operation: Literal["get_agent"] = Field("get_agent", title="Get Agent", json_schema_extra={"ui:hidden": True})


class ListNeeds(_Input):
    operation: Literal["list_needs"] = Field("list_needs", title="List Needs", json_schema_extra={"ui:hidden": True})
    status: Literal["OPEN", "MATCHED", "CLOSED", "FULFILLED"] | None = None
    capability: str | None = None
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class _Need(_Input):
    need_id: str = Field(..., min_length=1, title="Need ID")


class GetNeed(_Need):
    operation: Literal["get_need"] = Field("get_need", title="Get Need", json_schema_extra={"ui:hidden": True})


class GetMatchingNeeds(_Agent):
    operation: Literal["get_matching_needs"] = Field("get_matching_needs", title="Get Matching Needs", json_schema_extra={"ui:hidden": True})


class CreateNeed(_Input):
    operation: Literal["create_need"] = Field("create_need", title="Create Need", description="Publish a marketplace need with the specified budget in cents.", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=2000, json_schema_extra={"ui:widget": "textarea"})
    required_capabilities: list[str] = Field(..., min_length=1, max_length=20)
    budget_cents: int = Field(..., ge=1, le=10000000)
    creator_agent_id: UUID | None = None
    min_trust_score: int | None = Field(None, ge=0, le=100)


class SubscribeToNeed(_Need):
    operation: Literal["subscribe_to_need"] = Field("subscribe_to_need", title="Subscribe Agent to Need", json_schema_extra={"ui:hidden": True})
    subscriber_agent_id: UUID


class RespondToNeed(_Need):
    operation: Literal["respond_to_need"] = Field("respond_to_need", title="Respond to Need", json_schema_extra={"ui:hidden": True})
    responder_agent_id: UUID
    message: str = Field(..., max_length=2000)
    proposed_price_cents: int | None = Field(None, ge=1, le=10000000)


class GetNeedMatches(_Need):
    operation: Literal["get_need_matches"] = Field("get_need_matches", title="Get Need Matches", json_schema_extra={"ui:hidden": True})


class ListNeedResponses(_Need):
    operation: Literal["list_need_responses"] = Field("list_need_responses", title="List Need Responses", json_schema_extra={"ui:hidden": True})


class CancelNeed(_Need):
    operation: Literal["cancel_need"] = Field("cancel_need", title="Cancel Need", description="Cancel the need and its associated work order.", json_schema_extra={"ui:hidden": True})


class GetNeedWorkOrder(_Need):
    operation: Literal["get_need_work_order"] = Field("get_need_work_order", title="Get Need Work Order", json_schema_extra={"ui:hidden": True})


class ListWorkOrders(_Agent):
    operation: Literal["list_work_orders"] = Field("list_work_orders", title="List Agent Work Orders", json_schema_extra={"ui:hidden": True})


class ListMyNeeds(_Input):
    operation: Literal["list_my_needs"] = Field("list_my_needs", title="List My Needs", json_schema_extra={"ui:hidden": True})


class ListMessageInbox(_Input):
    operation: Literal["list_message_inbox"] = Field("list_message_inbox", title="List Message Inbox", json_schema_extra={"ui:hidden": True})


class ListMessages(_Agent):
    operation: Literal["list_messages"] = Field("list_messages", title="List Agent Messages", json_schema_extra={"ui:hidden": True})
    direction: Literal["inbox", "sent", "all"] = "all"
    limit: int = Field(50, ge=1, le=100)


class _Message(_Input):
    sender_agent_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=10, max_length=2000, json_schema_extra={"ui:widget": "textarea"})
    in_reply_to: str | None = Field(None, max_length=64)


class SendMessage(_Message, _Agent):
    operation: Literal["send_message"] = Field("send_message", title="Send Agent Message", json_schema_extra={"ui:hidden": True})


class MessageNeedCreator(_Message, _Need):
    operation: Literal["message_need_creator"] = Field("message_need_creator", title="Message Need Creator", json_schema_extra={"ui:hidden": True})


class ListNegotiations(_Input):
    operation: Literal["list_negotiations"] = Field("list_negotiations", title="List Negotiations", json_schema_extra={"ui:hidden": True})
    agent_id: UUID | None = None


class _Negotiation(_Input):
    negotiation_id: str = Field(..., min_length=1)


class GetNegotiation(_Negotiation):
    operation: Literal["get_negotiation"] = Field("get_negotiation", title="Get Negotiation", json_schema_extra={"ui:hidden": True})


class CancelNegotiation(_Negotiation):
    operation: Literal["cancel_negotiation"] = Field("cancel_negotiation", title="Cancel Negotiation", json_schema_extra={"ui:hidden": True})


class ListTransactions(_Input):
    operation: Literal["list_transactions"] = Field("list_transactions", title="List Agent Transactions", json_schema_extra={"ui:hidden": True})
    agent_id: UUID


class GetTransaction(_Input):
    operation: Literal["get_transaction"] = Field("get_transaction", title="Get Transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: str = Field(..., min_length=1)


Operation = Annotated[Union[GetIdentity, ListAgents, GetAgent, ListNeeds, GetNeed,
    GetMatchingNeeds, CreateNeed, SubscribeToNeed, RespondToNeed, GetNeedMatches,
    ListNeedResponses, CancelNeed, GetNeedWorkOrder, ListWorkOrders, ListMessageInbox,
    ListMyNeeds, ListMessages, SendMessage, MessageNeedCreator, ListNegotiations, GetNegotiation,
    CancelNegotiation, ListTransactions, GetTransaction], Field(discriminator="operation")]


class SwarmsyncaiConfig(NodeConfig[Operation, SwarmsyncaiAPIKeyCredential]):
    pass


# Each entry is exactly one published operation. Values map UI fields to wire names.
# method, route, path substitutions, query fields, body fields
ROUTES = {
    "get_identity": ("GET", "/auth/me", {}, {}, {}),
    "list_agents": ("GET", "/agents", {}, {"search": "search", "category": "category", "tag": "tag", "limit": "limit", "offset": "offset"}, {}),
    "get_agent": ("GET", "/agents/{id}", {"id": "agent_id"}, {}, {}),
    "list_needs": ("GET", "/needs", {}, {"status": "status", "capability": "capability", "limit": "limit", "offset": "offset"}, {}),
    "get_need": ("GET", "/needs/{id}", {"id": "need_id"}, {}, {}),
    "get_matching_needs": ("GET", "/needs/for-agent/{agentId}", {"agentId": "agent_id"}, {}, {}),
    "create_need": ("POST", "/needs", {}, {}, {"title": "title", "description": "description", "required_capabilities": "requiredCapabilities", "budget_cents": "budgetCents", "creator_agent_id": "creatorAgentId", "min_trust_score": "minTrustScore"}),
    "subscribe_to_need": ("POST", "/needs/{id}/subscribe", {"id": "need_id"}, {}, {"subscriber_agent_id": "subscriberAgentId"}),
    "respond_to_need": ("POST", "/needs/{id}/respond", {"id": "need_id"}, {}, {"responder_agent_id": "responderAgentId", "message": "message", "proposed_price_cents": "proposedPriceCents"}),
    "get_need_matches": ("GET", "/needs/{id}/matches", {"id": "need_id"}, {}, {}),
    "list_need_responses": ("GET", "/needs/{id}/responses", {"id": "need_id"}, {}, {}),
    "cancel_need": ("POST", "/needs/{id}/cancel", {"id": "need_id"}, {}, {}),
    "get_need_work_order": ("GET", "/needs/{id}/work-order", {"id": "need_id"}, {}, {}),
    "list_work_orders": ("GET", "/needs/work-orders/for-agent/{agentId}", {"agentId": "agent_id"}, {}, {}),
    "list_my_needs": ("GET", "/needs/my", {}, {}, {}),
    "list_message_inbox": ("GET", "/agents/messages/inbox", {}, {}, {}),
    "list_messages": ("GET", "/agents/{agentId}/messages", {"agentId": "agent_id"}, {"direction": "direction", "limit": "limit"}, {}),
    "send_message": ("POST", "/agents/{agentId}/message", {"agentId": "agent_id"}, {}, {"sender_agent_id": "senderAgentId", "message": "message", "in_reply_to": "inReplyTo"}),
    "message_need_creator": ("POST", "/needs/{needId}/message-creator", {"needId": "need_id"}, {}, {"sender_agent_id": "senderAgentId", "message": "message", "in_reply_to": "inReplyTo"}),
    "list_negotiations": ("GET", "/ap2/negotiations/my", {}, {"agent_id": "agentId"}, {}),
    "get_negotiation": ("GET", "/ap2/negotiations/{id}", {"id": "negotiation_id"}, {}, {}),
    "cancel_negotiation": ("PATCH", "/ap2/negotiations/{id}/cancel", {"id": "negotiation_id"}, {}, {}),
    "list_transactions": ("GET", "/ap2/transactions/my", {}, {"agent_id": "agentId"}, {}),
    "get_transaction": ("GET", "/ap2/transactions/{id}", {"id": "transaction_id"}, {}, {}),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(key, "[redacted]"): _redact(v, key) for k, v in value.items()}
    return value


class SwarmsyncaiNode(WorkflowNode):
    integration_type = "automation-swarmsyncai"
    connection_evidence = ConnectionEvidence(noun="connected agent", identity_operation="get_identity")

    @classmethod
    def get_config_model(cls):
        return SwarmsyncaiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Swarmsyncai agent API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, path_fields, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        for placeholder, field in path_fields.items():
            path = path.replace("{" + placeholder + "}", quote(values[field], safe=""))
        params = {wire: values[field] for field, wire in query_fields.items() if field in values}
        # /agents declares limit/offset as strings in OpenAPI, unlike /needs.
        if op.operation == "list_agents":
            params = {k: str(v) for k, v in params.items()}
        body = {wire: values[field] for field, wire in body_fields.items() if field in values}
        kwargs = {"params": params, "headers": {"x-agent-api-key": key, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json().get("message", response.reason_phrase)
            except (ValueError, AttributeError):
                detail = response.reason_phrase
            return {"status": "error", "status_code": response.status_code, "message": _redact(detail, key)}
        if not response.content:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("SwarmSync returned an unexpected non-JSON response") from None
        if isinstance(data, dict) and (data.get("error") or isinstance(data.get("statusCode"), int) and data["statusCode"] >= 400):
            return {"status": "error", "message": _redact(data.get("message") or data.get("error"), key)}
        output = {"status": "success", "data": _redact(data, key)}
        await self.emit(output)
        return output
