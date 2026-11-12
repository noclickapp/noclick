"""Clay Public API workflow node.

API reference: https://developers.clay.com/openapi.json
The Public API uses a ``clay-api-key`` header. Clay's OAuth flow is for its
separate MCP endpoint and does not authorize these Public API operations.
"""

import json
import time
from typing import Annotated, Any, ClassVar, Literal, Union
from urllib.parse import quote

import httpx
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from pydantic import BaseModel, ConfigDict, Discriminator, Field

CLAY_API_BASE = "https://api.clay.com/public/v0"


def _op(name: str, category: str, display: str) -> dict[str, Any]:
    return {
        "const": name,
        "ui:hidden": True,
        "x-category": category,
        "x-display-name": display,
        "x-is-trigger": False,
    }


class ClayApiKeyCredential(BaseModel):
    credential_type: Literal["clay_api_key"] = Field(
        "clay_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Clay Public API key from API and CLI → API keys.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.clay.com/"}
    )


class ClayGetMeConfig(BaseModel):
    operation: Literal["get_me"] = Field(
        "get_me",
        title="Get Authenticated User",
        json_schema_extra=_op("get_me", "Workspace", "Get Authenticated User"),
    )


class ClayGetCreditBalanceConfig(BaseModel):
    operation: Literal["get_credit_balance"] = Field(
        "get_credit_balance",
        title="Get Credit Balance",
        json_schema_extra=_op("get_credit_balance", "Workspace", "Get Credit Balance"),
    )


class ClayCreateSearchConfig(BaseModel):
    operation: Literal["create_search"] = Field(
        "create_search",
        title="Create Search",
        json_schema_extra=_op("create_search", "Searches", "Create Search"),
    )
    query: str = Field(
        ...,
        min_length=1,
        title="Clay Search Query",
        description="Advanced Clay search query. Returns a search ID for paging results.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ClayGetSearchResultsConfig(BaseModel):
    operation: Literal["get_search_results"] = Field(
        "get_search_results",
        title="Get Search Results",
        json_schema_extra=_op("get_search_results", "Searches", "Get Search Results"),
    )
    search_id: str = Field(..., min_length=1, title="Search ID")
    limit: int = Field(20, ge=1, le=500, title="Page Size")


class ClayRunRoutineConfig(BaseModel):
    operation: Literal["run_routine"] = Field(
        "run_routine",
        title="Run Routine",
        json_schema_extra=_op("run_routine", "Routines", "Run Routine"),
    )
    routine_id: str = Field(..., min_length=1, max_length=64, title="Routine ID")
    items_json: str = Field(
        ...,
        title="Items (JSON)",
        description='Array of 1–100 objects, each with an id and inputs object, e.g. [{"id":"lead-1","inputs":{"domain":"example.com"}}].',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ClayGetRoutineResultsConfig(BaseModel):
    operation: Literal["get_routine_results"] = Field(
        "get_routine_results",
        title="Get Routine Results",
        json_schema_extra=_op("get_routine_results", "Routines", "Get Routine Results"),
    )
    routine_run_id: str = Field(
        ..., min_length=1, max_length=64, title="Routine Run ID"
    )
    cursor: str | None = Field(None, title="Cursor")
    limit: int = Field(20, ge=1, le=100, title="Page Size")


class ClayQueryTablesConfig(BaseModel):
    operation: Literal["query_tables"] = Field(
        "query_tables",
        title="Query Tables",
        json_schema_extra=_op("query_tables", "Tables", "Query Tables"),
    )
    query_json: str = Field(
        ...,
        title="Structured Query (JSON)",
        description='Clay structured query, e.g. {"tables":[{"id":"table-id"}]}. Enterprise plan required; tables are read-only.',
        json_schema_extra={"ui:widget": "textarea"},
    )
    cursor: str | None = Field(None, title="Cursor")
    limit: int = Field(50, ge=1, le=100, title="Page Size")


# Clay's own MCP server: agents get its tools through a person's Clay sign-in.
ClayMcpCredential = mcp_credential("clay", "https://api.clay.com/v3/mcp", app="Clay")
ClayCredential = Union[ClayApiKeyCredential, ClayMcpCredential]


ClayConfig = Annotated[
    Union[
        ClayGetMeConfig,
        ClayGetCreditBalanceConfig,
        ClayCreateSearchConfig,
        ClayGetSearchResultsConfig,
        ClayRunRoutineConfig,
        ClayGetRoutineResultsConfig,
        ClayQueryTablesConfig,
    ],
    Discriminator("operation"),
]


class ClayNodeConfig(NodeConfig[ClayConfig, ClayCredential]):
    pass


def _json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _routine_items(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Items must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError("Items must be a JSON array of 1–100 objects")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not item["id"]
        or not isinstance(item.get("inputs"), dict)
        for item in value
    ):
        raise ValueError("Each item needs a non-empty string id and an inputs object")
    return value


class ClayNode(WorkflowNode):
    """Search GTM data, run enrichments, and read Clay table data."""
    integration_type = "automation-clay"
    credential_provider_labels = {"clay": "Clay Account"}
    auto_select_credential = False

    edit_examples: ClassVar[list[str]] = [
        "Search Clay for companies matching our ideal customer profile",
        "Run a Clay enrichment function against incoming leads",
        "Fetch the results of a Clay routine run",
        "Read rows from an Enterprise Clay table",
    ]
    connection_evidence = ConnectionEvidence(
        identity_operation="get_me", noun="Clay workspace"
    )

    @classmethod
    def get_config_model(cls):
        return ClayNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ClayNodeConfig):
            raise TypeError("Valid Clay configuration is required")
        credential = self.config.credentials
        if not credential or not credential.api_key:
            raise ValueError("Clay Public API key is required")

        config = self.config.config
        operation = config.operation
        params = None
        body = None
        if isinstance(config, ClayGetMeConfig):
            method, path = "GET", "/me"
        elif isinstance(config, ClayGetCreditBalanceConfig):
            method, path = "GET", "/credits/balance"
        elif isinstance(config, ClayCreateSearchConfig):
            method, path = "POST", "/search/query-mode"
            body = {"query": config.query}
        elif isinstance(config, ClayGetSearchResultsConfig):
            method, path = (
                "POST",
                f"/search/query-mode/{quote(config.search_id, safe='')}/run",
            )
            body = {"limit": config.limit}
        elif isinstance(config, ClayRunRoutineConfig):
            method, path = "POST", f"/routines/{quote(config.routine_id, safe='')}/run"
            body = {"items": _routine_items(config.items_json)}
        elif isinstance(config, ClayGetRoutineResultsConfig):
            method, path = (
                "GET",
                f"/routines/run/{quote(config.routine_run_id, safe='')}/results",
            )
            params = {
                "limit": config.limit,
                **({"cursor": config.cursor} if config.cursor else {}),
            }
        elif isinstance(config, ClayQueryTablesConfig):
            method, path = "POST", "/tables/query"
            query = _json_object(config.query_json, "Structured query")
            if not isinstance(query.get("tables"), list) or not query["tables"]:
                raise ValueError(
                    "Structured query must include a non-empty tables array"
                )
            body = {"query": query, "limit": config.limit}
            if config.cursor:
                body["cursor"] = config.cursor
        else:
            raise TypeError(f"Unsupported Clay operation: {operation}")

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    f"{CLAY_API_BASE}{path}",
                    headers={
                        "clay-api-key": credential.api_key,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    params=params,
                    json=body,
                )
        except httpx.RequestError as exc:
            return {
                "status": "error",
                "action": operation,
                "error": f"Clay request failed: {type(exc).__name__}",
                "timing_ms": {
                    "api_request": round((time.monotonic() - start) * 1000, 2)
                },
            }

        elapsed = round((time.monotonic() - start) * 1000, 2)
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:500]}
        if response.status_code >= 400:
            message = (
                payload.get("message") or payload.get("error")
                if isinstance(payload, dict)
                else str(payload)
            )
            return {
                "status": "error",
                "action": operation,
                "error": str(message),
                "status_code": response.status_code,
                "timing_ms": {"api_request": elapsed},
            }
        return {
            "status": "success",
            "action": operation,
            "data": payload,
            "status_code": response.status_code,
            "timing_ms": {"api_request": elapsed},
        }
