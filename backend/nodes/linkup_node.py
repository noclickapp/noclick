"""Linkup v1 web search, page retrieval and asynchronous research.

Contract: https://api.linkup.so/v1/openapi.json (1.0).
Authentication: https://docs.linkup.so/pages/documentation/platform/authentication
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class LinkupAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Linkup API Key",
        json_schema_extra={
            "x-credential-url": "https://app.linkup.so",
            "x-credential-instructions": "Copy your API key from the Linkup dashboard and paste it here. NoClick sends it as a Bearer token to api.linkup.so. Extract is a closed-beta feature that requires access from Linkup.",
        },
    )
    credential_type: Literal["linkup_api_key"] = Field("linkup_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})


class LinkupInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class LinkupQueryInput(LinkupInput):
    q: str = Field(..., min_length=1, title="Query")
    outputType: Literal["sourcedAnswer", "structured"] = Field("sourcedAnswer", title="Output type")
    structuredOutputSchema: str | None = Field(None, title="Structured output schema", description="JSON schema string with an object root; required for structured output.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    includeDomains: list[str] | None = Field(None, max_length=100, title="Include domains")
    excludeDomains: list[str] | None = Field(None, title="Exclude domains")
    fromDate: date | None = Field(None, title="From date")
    toDate: date | None = Field(None, title="To date")

    @model_validator(mode="after")
    def validate_query(self):
        if self.outputType == "structured" and not self.structuredOutputSchema:
            raise ValueError("Structured output requires structuredOutputSchema")
        if self.fromDate and self.toDate and self.fromDate >= self.toDate:
            raise ValueError("From date must be before to date")
        return self


class LinkupSearchInput(LinkupQueryInput):
    outputType: Literal["searchResults", "sourcedAnswer", "structured"] = Field("searchResults", title="Output type")
    depth: Literal["deep", "fast", "flash", "standard"] = Field("fast", title="Search depth")
    includeImages: bool | None = Field(None, title="Include images")
    includeInlineCitations: bool | None = Field(None, title="Include inline citations")
    includeSources: bool | None = Field(None, title="Include sources")
    maxResults: float | None = Field(None, ge=1, title="Maximum results")


class LinkupFetchInput(LinkupInput):
    url: str = Field(..., min_length=1, title="Page URL", json_schema_extra={"format": "uri"})
    mode: Literal["standard", "pro"] = Field("standard", title="Fetch mode")
    renderJs: bool | None = Field(None, title="Render JavaScript")
    extractImages: bool | None = Field(None, title="Extract images")
    includeRawContent: bool | None = Field(None, title="Include raw content")
    instructions: str | None = Field(None, title="Extraction instructions")
    extraction_schema: dict[str, Any] | None = Field(None, alias="schema", title="Extraction schema")

    @model_validator(mode="after")
    def validate_instructions(self):
        if self.instructions and self.extraction_schema is None:
            raise ValueError("Extraction instructions require a schema")
        return self


class LinkupResearchInput(LinkupQueryInput):
    mode: Literal["answer", "auto", "investigate", "research"] = Field("auto", title="Research mode")
    reasoningDepth: Literal["L", "M", "S", "XL"] = Field("L", title="Reasoning depth")


class LinkupExtractInput(LinkupInput):
    q: str = Field(..., min_length=1, title="Extraction query")
    url: str = Field(..., min_length=1, title="Seed URL", json_schema_extra={"format": "uri"})
    extraction_schema: dict[str, Any] | None = Field(None, alias="schema", title="Row schema")
    verifyUrls: bool = Field(False, title="Verify URLs")


class LinkupSearchTask(LinkupInput):
    type: Literal["search"] = "search"
    input: LinkupSearchInput


class LinkupFetchTask(LinkupInput):
    type: Literal["fetch"] = "fetch"
    input: LinkupFetchInput


class LinkupResearchTask(LinkupInput):
    type: Literal["research"] = "research"
    input: LinkupResearchInput


class LinkupExtractTask(LinkupInput):
    type: Literal["extract"] = "extract"
    input: LinkupExtractInput


LinkupTask = Annotated[Union[LinkupSearchTask, LinkupFetchTask, LinkupResearchTask, LinkupExtractTask], Field(discriminator="type")]


class LinkupGetCreditBalanceConfig(LinkupInput):
    """Read the current account's remaining credits without spending credits."""
    operation: Literal["get_credit_balance"] = "get_credit_balance"


class LinkupSearchConfig(LinkupSearchInput):
    """Search the web and return sources, a sourced answer or structured data."""
    operation: Literal["search"] = "search"


class LinkupFetchConfig(LinkupFetchInput):
    """Fetch a public web page as markdown with optional structured extraction."""
    operation: Literal["fetch"] = "fetch"


class LinkupCreateExtractConfig(LinkupExtractInput):
    """Create a closed-beta extraction task returning structured rows."""
    operation: Literal["create_extract"] = "create_extract"


class LinkupCreateResearchConfig(LinkupResearchInput):
    """Start an asynchronous web research task; poll with Get Research."""
    operation: Literal["create_research"] = "create_research"


class LinkupCreateTasksConfig(LinkupInput):
    """Submit up to 100 search, fetch, research or extract tasks in one batch."""
    operation: Literal["create_tasks"] = "create_tasks"
    tasks: list[LinkupTask] = Field(..., min_length=1, max_length=100, title="Tasks")


class LinkupListInput(LinkupInput):
    page: int = Field(1, ge=1, title="Page")
    pageSize: int = Field(10, ge=1, le=100, title="Page size")
    sortBy: Literal["createdAt", "updatedAt"] | None = Field(None, title="Sort by")
    sortDirection: Literal["asc", "desc"] = Field("asc", title="Sort direction")


class LinkupListExtractConfig(LinkupListInput):
    """List the organization's extraction tasks, one page at a time."""
    operation: Literal["list_extract"] = "list_extract"


class LinkupListResearchConfig(LinkupListInput):
    """List the organization's research tasks, one page at a time."""
    operation: Literal["list_research"] = "list_research"


class LinkupListTasksConfig(LinkupListInput):
    """List the organization's tasks with optional type and status filters."""
    operation: Literal["list_tasks"] = "list_tasks"
    type: list[Literal["extract", "fetch", "research", "search"]] | None = Field(None, title="Task types")
    status: list[Literal["completed", "failed", "pending", "processing"]] | None = Field(None, title="Task statuses")


class LinkupGetInput(LinkupInput):
    id: str = Field(..., min_length=1, title="Task ID")


class LinkupGetExtractConfig(LinkupGetInput):
    """Retrieve one extraction task and its output download information."""
    operation: Literal["get_extract"] = "get_extract"


class LinkupGetResearchConfig(LinkupGetInput):
    """Retrieve one research task, including its status and completed output."""
    operation: Literal["get_research"] = "get_research"


class LinkupGetTaskConfig(LinkupGetInput):
    """Retrieve a batch task's status and output without polling in a loop."""
    operation: Literal["get_task"] = "get_task"


class LinkupResponseMessage(LinkupInput):
    role: Literal["user", "assistant", "developer"]
    content: str


class LinkupResponseText(LinkupInput):
    format: str | dict[str, Any]


class LinkupCreateResponseConfig(LinkupInput):
    """Generate a web-grounded answer using Linkup's Responses-compatible API."""
    operation: Literal["create_response"] = "create_response"
    input: str | list[LinkupResponseMessage] = Field(..., title="Input")
    model: Literal["linkup-deep", "linkup-standard"] = Field("linkup-standard", title="Model")
    instructions: str | None = Field(None, title="Instructions")
    text: LinkupResponseText | None = Field(None, title="Response text format")


class LinkupRewindSearchConfig(LinkupInput):
    """Search web revisions visible on a specific UTC day."""
    operation: Literal["rewind_search"] = "rewind_search"
    q: str = Field(..., min_length=1, title="Query")
    asOf: date = Field(..., title="As of date")


class LinkupRewindFetchConfig(LinkupInput):
    """Retrieve a URL's stored revision visible on a specific UTC day."""
    operation: Literal["rewind_fetch"] = "rewind_fetch"
    url: str = Field(..., min_length=1, title="Exact stored URL", json_schema_extra={"format": "uri"})
    asOf: date = Field(..., title="As of date")


LinkupConfig = Annotated[Union[
    LinkupGetCreditBalanceConfig, LinkupSearchConfig, LinkupFetchConfig,
    LinkupCreateExtractConfig, LinkupListExtractConfig, LinkupGetExtractConfig,
    LinkupCreateTasksConfig, LinkupListTasksConfig, LinkupGetTaskConfig,
    LinkupCreateResponseConfig, LinkupCreateResearchConfig, LinkupListResearchConfig,
    LinkupGetResearchConfig, LinkupRewindSearchConfig, LinkupRewindFetchConfig,
], Field(discriminator="operation")]


class LinkupFullConfig(NodeConfig[LinkupConfig, LinkupAPIKeyCredential]):
    pass


ROUTES = {
    "get_credit_balance": ("GET", "/v1/credits/balance"),
    "search": ("POST", "/v1/search"),
    "fetch": ("POST", "/v1/fetch"),
    "create_extract": ("POST", "/v1/extract"),
    "list_extract": ("GET", "/v1/extract"),
    "get_extract": ("GET", "/v1/extract/{id}"),
    "create_tasks": ("POST", "/v1/tasks"),
    "list_tasks": ("GET", "/v1/tasks"),
    "get_task": ("GET", "/v1/tasks/{id}"),
    "create_response": ("POST", "/v1/responses"),
    "create_research": ("POST", "/v1/research"),
    "list_research": ("GET", "/v1/research"),
    "get_research": ("GET", "/v1/research/{id}"),
    "rewind_search": ("POST", "/v1/rewind/search"),
    "rewind_fetch": ("POST", "/v1/rewind/fetch"),
}


class LinkupNode(WorkflowNode):
    integration_type = "automation-linkup"
    connection_evidence = ConnectionEvidence(
        operation="get_credit_balance", noun="Linkup credit balance", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return LinkupFullConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Linkup API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        kwargs: dict[str, Any] = {}
        if method == "POST":
            kwargs["json"] = values["tasks"] if config.operation == "create_tasks" else values
        elif values:
            kwargs["params"] = values
        async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.linkup.so" + path,
                headers={"Authorization": f"Bearer {credential.api_key}", "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Linkup returned an unexpected JSON response")
        return {"status": "success", "data": body}
