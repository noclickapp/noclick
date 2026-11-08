"""DocsBot Chat API operations, pinned to the provider's OpenAPI 0.1 contract."""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class DocsbotAiApiKey(BaseModel):
    model_config = ConfigDict(title="DocsBot AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docsbot.ai/app/api",
            "x-credential-instructions": "Paste your user API key from the DocsBot dashboard API Keys section. Its permissions match your user account. NoClick sends it as a Bearer token to api.docsbot.ai.",
        })
    credential_type: Literal["docsbot_ai_api_key"] = Field("docsbot_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Bot(_Input):
    team_id: str = Field(..., min_length=1, title="Team ID")
    bot_id: str = Field(..., min_length=1, title="Bot ID")

    @field_validator("team_id", "bot_id", "conv_id", "answer_id", "job_id", check_fields=False)
    @classmethod
    def path_identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a DocsBot resource ID")
        return value


class _Conversation(_Bot):
    conv_id: str = Field(..., min_length=1, title="Conversation ID")


class _Answer(_Bot):
    answer_id: str = Field(..., min_length=1, title="Answer ID")


class _ResearchJob(_Bot):
    job_id: str = Field(..., min_length=1, title="Research Job ID")


class ListLibraries(_Input):
    operation: Literal["list_libraries"] = Field("list_libraries", title="List Searchable Libraries", json_schema_extra={"ui:hidden": True})


class Chat(_Bot):
    operation: Literal["chat"] = Field("chat", title="Ask a Question", json_schema_extra={"ui:hidden": True})
    question: str = Field(..., min_length=1)
    history: list[list[str]] | None = None
    format: Literal["markdown", "text", "html"] = "markdown"
    full_source: bool = False
    metadata: dict[str, Any] | None = None
    testing: bool = False
    context_items: int = Field(5, gt=0, le=32)


class ChatAgent(_Bot):
    operation: Literal["chat_agent"] = Field("chat_agent", title="Chat with Agent", json_schema_extra={"ui:hidden": True})
    question: str = Field(..., min_length=1)
    conversationId: str = Field(..., min_length=1, title="Conversation ID", description="Use a new UUID to start a conversation; reuse it to continue.")
    format: Literal["markdown", "text", "html"] = "markdown"
    full_source: bool = False
    metadata: dict[str, Any] | None = None
    testing: bool = False
    document_retriever: bool = True
    web_search: Union[bool, Literal["live"]] = False
    image_urls: list[str] | None = None
    default_language: str | None = None
    context_items: int = Field(5, gt=0, le=32)


class Search(_Bot):
    operation: Literal["search"] = Field("search", title="Search Documentation", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1)
    alpha: float = Field(0.5, ge=0, le=1)
    use_glossary: bool = False
    tags: list[str] | None = None
    include_untagged: bool = True


class FetchDocument(_Bot):
    operation: Literal["fetch_document"] = Field("fetch_document", title="Fetch Document", json_schema_extra={"ui:hidden": True})
    fileId: str = Field(..., min_length=1, title="File ID", description="Use fileId from a search result.")


class RateAnswer(_Answer):
    operation: Literal["rate_answer"] = Field("rate_answer", title="Rate Answer", json_schema_extra={"ui:hidden": True})
    rating: int = Field(..., ge=-1, le=1)


class LogSupport(_Answer):
    operation: Literal["log_support"] = Field("log_support", title="Log Answer Support Escalation", json_schema_extra={"ui:hidden": True})


class EscalateConversation(_Conversation):
    operation: Literal["escalate_conversation"] = Field("escalate_conversation", title="Escalate Conversation", description="Marks the conversation as escalated and triggers the provider's escalation webhook.", json_schema_extra={"ui:hidden": True})


class UpdateConversation(_Conversation):
    operation: Literal["update_conversation"] = Field("update_conversation", title="Update Conversation Metadata", json_schema_extra={"ui:hidden": True})
    metadata: dict[str, Any]
    fullChange: bool = Field(False, title="Replace All Metadata")


class CaptureLead(_Conversation):
    operation: Literal["capture_lead"] = Field("capture_lead", title="Capture Conversation Lead", json_schema_extra={"ui:hidden": True})
    metadata: dict[str, Any]


class SummarizeConversation(_Conversation):
    operation: Literal["summarize_conversation"] = Field("summarize_conversation", title="Summarize Conversation", json_schema_extra={"ui:hidden": True})


class CreateTicket(_Conversation):
    operation: Literal["create_ticket"] = Field("create_ticket", title="Generate Conversation Ticket", description="Returns a ticket subject and message for a downstream help desk step.", json_schema_extra={"ui:hidden": True})


class StartResearch(_Bot):
    operation: Literal["start_research"] = Field("start_research", title="Start Deep Research", json_schema_extra={"ui:hidden": True})
    question: str = Field(..., min_length=1)
    model: Literal["gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-sol", "gpt-6-luna", "gpt-5.4-mini", "gpt-5.5", "gpt-5.6-sol", "gpt-5.6-luna", "o3", "o4-mini"] = "gpt-6-luna"
    web_search: bool = False
    code_interpreter: bool = False
    docs_search: bool = True
    question_history: bool = False
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    include_untagged: bool = True


class ContinueResearch(_ResearchJob):
    operation: Literal["continue_research"] = Field("continue_research", title="Continue Deep Research", json_schema_extra={"ui:hidden": True})
    answers: str = Field(..., min_length=1)
    web_search: bool | None = None
    code_interpreter: bool | None = None
    docs_search: bool | None = None
    question_history: bool | None = None


class GetResearch(_ResearchJob):
    operation: Literal["get_research"] = Field("get_research", title="Get Research Status", json_schema_extra={"ui:hidden": True})


class CancelResearch(_ResearchJob):
    operation: Literal["cancel_research"] = Field("cancel_research", title="Cancel Research", json_schema_extra={"ui:hidden": True})


DocsbotAiConfig = Annotated[Union[ListLibraries, Chat, ChatAgent, Search, FetchDocument, RateAnswer,
    LogSupport, EscalateConversation, UpdateConversation, CaptureLead, SummarizeConversation,
    CreateTicket, StartResearch, ContinueResearch, GetResearch, CancelResearch], Field(discriminator="operation")]


class DocsbotAiNodeConfig(NodeConfig[DocsbotAiConfig, DocsbotAiApiKey]):
    pass


ROUTES = {
    "list_libraries": ("GET", "/libraries"),
    "chat": ("POST", "/chat"),
    "chat_agent": ("POST", "/chat-agent"),
    "search": ("POST", "/search"),
    "fetch_document": ("POST", "/fetch"),
    "rate_answer": ("PUT", "/rate/{answer_id}"),
    "log_support": ("PUT", "/support/{answer_id}"),
    "escalate_conversation": ("PUT", "/conversations/{conv_id}/escalate"),
    "update_conversation": ("PUT", "/conversations/{conv_id}"),
    "capture_lead": ("POST", "/conversations/{conv_id}/lead"),
    "summarize_conversation": ("GET", "/conversations/{conv_id}/summarize"),
    "create_ticket": ("GET", "/conversations/{conv_id}/ticket"),
    "start_research": ("POST", "/research"),
    "continue_research": ("POST", "/research/{job_id}"),
    "get_research": ("GET", "/research/{job_id}"),
    "cancel_research": ("DELETE", "/research/{job_id}"),
}
PATH_FIELDS = {"team_id", "bot_id", "answer_id", "conv_id", "job_id"}


class DocsbotAiNode(WorkflowNode):
    integration_type = "automation-docsbot-ai"
    connection_evidence = ConnectionEvidence(noun="searchable bot libraries", operation="list_libraries")

    @classmethod
    def get_config_model(cls):
        return DocsbotAiNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a DocsBot AI API key")
        config = self.config.config
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path_values = {key: quote(values[key], safe="") for key in PATH_FIELDS if key in values}
        path = route.format(**path_values)
        if config.operation != "list_libraries":
            path = "/teams/{team_id}/bots/{bot_id}".format(**path_values) + path
        body = {key: value for key, value in values.items() if key not in PATH_FIELDS | {"operation"}}
        if config.operation == "chat_agent":
            body["stream"] = False
        async with guarded_async_client(timeout=120, follow_redirects=False) as client:
            response = await client.request(method, "https://api.docsbot.ai" + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"},
                **({"json": body} if body else {}))
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise ValueError("DocsBot returned an unexpected redirect")
        data = response.json()
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            message = str(data.get("error") or data["errors"])
            raise ValueError(message.replace(self.config.credentials.api_key, "[redacted]"))
        if config.operation == "list_libraries":
            if not isinstance(data, dict) or not isinstance(data.get("libraries"), list):
                raise ValueError("DocsBot returned an invalid libraries response")
            return {"libraries": data["libraries"], "data": data["libraries"]}
        return {"data": data}
