"""
Perplexity AI automation node.

Provides workflow integration with the Perplexity API for operations including:
- Chat: search-grounded chat completions (Sonar), streaming, async submit/list/get,
  academic & SEC search modes, structured JSON output
- Search: raw ranked web search results
- Agent: frontier model + Perplexity web-search tools with structured output
- Embeddings: standard and contextualized vector embeddings
- Models: list available models
- Auth Tokens: generate / revoke account API keys
- Analytics: computer usage analytics

Authentication: API Key (Bearer token). No OAuth, no webhooks.
API Base URL: https://api.perplexity.ai
Documentation: https://docs.perplexity.ai
"""

import json
import logging
import os
import time
from decimal import Decimal
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

PERPLEXITY_API_BASE = "https://api.perplexity.ai"

# Models available on the Sonar chat-completions surface.
SONAR_MODELS = ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]

from nodes.core.platform_billing import platform_keyed_operation, require_platform_key

# Runs on NoClick's Perplexity key when no credential is attached (nodes/core/platform_billing.py).
PLATFORM_KEYED = platform_keyed_operation("PERPLEXITY_API_KEY", byok=True)

# Synchronous ops that may run on NoClick's platform key with no user credential,
# mapped to how their provider cost is determined: "usage_cost" reads the
# response's in-band usage.cost.total_cost (chat-completions surface);
# "flat_search" charges the published per-request Search API price (its response
# carries no cost object). Async jobs, /v1/agent, embeddings, and account ops
# stay BYOK-only — their cost isn't knowable at the call, or they're account-scoped.
PLATFORM_METERED_OPERATIONS = {
    "chat_completion": "usage_cost",
    "academic_search": "usage_cost",
    "sec_search": "usage_cost",
    "structured_output": "usage_cost",
    "search": "flat_search",
}


# ============================================================================
# Credential Schema
# ============================================================================


class PerplexityApiKeyCredential(BaseModel):
    """API Key credential for Perplexity."""

    credential_type: Literal["perplexity_api_key"] = Field(
        "perplexity_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Perplexity API key (starts with pplx-) from console.perplexity.ai → Settings → API",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://console.perplexity.ai"}
    )


PerplexityCredential = PerplexityApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class PerplexityChatCompletionConfig(BaseModel):
    """Generate a search-grounded model answer for a chat conversation."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["chat_completion"] = Field(
        "chat_completion",
        json_schema_extra={
            "const": "chat_completion",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Create Chat Completion",
        },
        title="Create Chat Completion",
    )
    model: str = Field(
        "sonar",
        title="Model",
        description="Sonar model to use",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "model",
                "placeholder": "Select a model...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a model name",
            },
            "enum": SONAR_MODELS,
            "x-enum-searchable": True,
            "x-resource-type": "perplexity_model",
        },
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The user message / question to answer",
        json_schema_extra={"ui:widget": "textarea"},
    )
    system_prompt: Optional[str] = Field(
        None,
        title="System Prompt",
        description="Optional system instructions to steer the model",
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_tokens: Optional[str] = Field(
        None, title="Max Tokens", description="Maximum number of completion tokens"
    )
    temperature: Optional[str] = Field(
        None, title="Temperature", description="Sampling temperature (0-2)"
    )
    search_recency_filter: Optional[str] = Field(
        None,
        title="Recency Filter",
        description="Restrict grounding to recent results",
        json_schema_extra={
            "enum": ["", "hour", "day", "week", "month", "year"],
            "enumNames": ["Any", "Past hour", "Past day", "Past week", "Past month", "Past year"],
            "x-enum-searchable": True,
        },
    )
    search_domain_filter: Optional[str] = Field(
        None,
        title="Domain Filter",
        description="Limit grounding to these domains, comma-separated (max 20)",
    )


class PerplexityCreateAsyncCompletionConfig(BaseModel):
    """Submit a long-running (e.g. deep-research) completion as a background job."""

    operation: Literal["create_async_completion"] = Field(
        "create_async_completion",
        json_schema_extra={
            "const": "create_async_completion",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Create Async Chat Completion",
        },
        title="Create Async Chat Completion",
    )
    model: str = Field(
        "sonar-deep-research",
        title="Model",
        description="Model to use (deep-research models are best run async)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "model",
                "placeholder": "Select a model...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a model name",
            },
            "enum": SONAR_MODELS,
            "x-enum-searchable": True,
            "x-resource-type": "perplexity_model",
        },
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The user message / question to answer",
        json_schema_extra={"ui:widget": "textarea"},
    )
    system_prompt: Optional[str] = Field(
        None,
        title="System Prompt",
        description="Optional system instructions",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PerplexityListAsyncCompletionsConfig(BaseModel):
    """List all async chat-completion jobs for the account."""

    operation: Literal["list_async_completions"] = Field(
        "list_async_completions",
        json_schema_extra={
            "const": "list_async_completions",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "List Async Chat Completions",
        },
        title="List Async Chat Completions",
    )


class PerplexityGetAsyncCompletionConfig(BaseModel):
    """Poll the status and retrieve a specific async completion job."""

    operation: Literal["get_async_completion"] = Field(
        "get_async_completion",
        json_schema_extra={
            "const": "get_async_completion",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Get Async Chat Completion",
        },
        title="Get Async Chat Completion",
    )
    request_id: str = Field(
        ..., title="Request ID", description="The async job request_id to poll"
    )


class PerplexitySearchConfig(BaseModel):
    """Get raw, ranked web search results (title, URL, snippet)."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search the Web",
        },
        title="Search the Web",
    )
    query: str = Field(
        ..., title="Query", description="The search query"
    )
    max_results: Optional[str] = Field(
        "10", title="Max Results", description="Number of results to return (1-20)"
    )
    search_recency_filter: Optional[str] = Field(
        None,
        title="Recency Filter",
        description="Restrict results by recency",
        json_schema_extra={
            "enum": ["", "hour", "day", "week", "month", "year"],
            "enumNames": ["Any", "Past hour", "Past day", "Past week", "Past month", "Past year"],
            "x-enum-searchable": True,
        },
    )
    search_domain_filter: Optional[str] = Field(
        None,
        title="Domain Filter",
        description="Limit to these domains, comma-separated (max 20)",
    )
    search_language_filter: Optional[str] = Field(
        None,
        title="Language Filter",
        description="Limit to these languages, comma-separated (max 20)",
    )


class PerplexityAgentResponseConfig(BaseModel):
    """Run a frontier model with Perplexity web-search tools and filters."""

    operation: Literal["agent_response"] = Field(
        "agent_response",
        json_schema_extra={
            "const": "agent_response",
            "ui:hidden": True,
            "x-category": "Agent",
            "x-is-trigger": False,
            "x-display-name": "Create Agent Response",
        },
        title="Create Agent Response",
    )
    model: str = Field(
        "openai/gpt-5.5",
        title="Model",
        description="Provider/model identifier, e.g. openai/gpt-5.5, perplexity/sonar (built-in web search)",
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The instruction / question for the agent",
        json_schema_extra={"ui:widget": "textarea"},
    )
    instructions: Optional[str] = Field(
        None,
        title="Instructions",
        description="Optional system-level instructions to steer the agent",
        json_schema_extra={"ui:widget": "textarea"},
    )
    reasoning_effort: Optional[str] = Field(
        None,
        title="Reasoning Effort",
        description="Reasoning depth",
        json_schema_extra={
            "enum": ["", "low", "medium", "high", "xhigh", "max"],
            "enumNames": ["Default", "Low", "Medium", "High", "Extra high", "Max"],
            "x-enum-searchable": True,
        },
    )


class PerplexityCreateEmbeddingsConfig(BaseModel):
    """Generate vector embeddings for text."""

    operation: Literal["create_embeddings"] = Field(
        "create_embeddings",
        json_schema_extra={
            "const": "create_embeddings",
            "ui:hidden": True,
            "x-category": "Embeddings",
            "x-is-trigger": False,
            "x-display-name": "Create Embeddings",
        },
        title="Create Embeddings",
    )
    model: str = Field(
        "pplx-embed-v1-4b",
        title="Model",
        description="Embeddings model (pplx-embed-v1-0.6b or pplx-embed-v1-4b)",
    )
    input_text: str = Field(
        ...,
        title="Input",
        description="Text to embed. For multiple inputs, separate with newlines",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PerplexityCreateContextualizedEmbeddingsConfig(BaseModel):
    """Generate context-aware embeddings (document + surrounding context)."""

    operation: Literal["create_contextualized_embeddings"] = Field(
        "create_contextualized_embeddings",
        json_schema_extra={
            "const": "create_contextualized_embeddings",
            "ui:hidden": True,
            "x-category": "Embeddings",
            "x-is-trigger": False,
            "x-display-name": "Create Contextualized Embeddings",
        },
        title="Create Contextualized Embeddings",
    )
    model: str = Field(
        "pplx-embed-context-v1-4b",
        title="Model",
        description="Contextualized embeddings model (pplx-embed-context-v1-0.6b or pplx-embed-context-v1-4b)",
    )
    input_text: str = Field(
        ...,
        title="Input",
        description="Documents to embed, one per line (each line is embedded as a document)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PerplexityListModelsConfig(BaseModel):
    """List the models available to the account."""

    operation: Literal["list_models"] = Field(
        "list_models",
        json_schema_extra={
            "const": "list_models",
            "ui:hidden": True,
            "x-category": "Models",
            "x-is-trigger": False,
            "x-display-name": "List Models",
        },
        title="List Models",
    )


class PerplexityGenerateAuthTokenConfig(BaseModel):
    """Programmatically create a new API key/token for the account."""

    operation: Literal["generate_auth_token"] = Field(
        "generate_auth_token",
        json_schema_extra={
            "const": "generate_auth_token",
            "ui:hidden": True,
            "x-category": "Auth Tokens",
            "x-is-trigger": False,
            "x-display-name": "Generate Auth Token",
        },
        title="Generate Auth Token",
    )
    token_name: Optional[str] = Field(
        None, title="Token Name", description="Optional label for the new token"
    )


class PerplexityRevokeAuthTokenConfig(BaseModel):
    """Revoke an existing API key/token (rotation)."""

    operation: Literal["revoke_auth_token"] = Field(
        "revoke_auth_token",
        json_schema_extra={
            "const": "revoke_auth_token",
            "ui:hidden": True,
            "x-category": "Auth Tokens",
            "x-is-trigger": False,
            "x-display-name": "Revoke Auth Token",
        },
        title="Revoke Auth Token",
    )
    token: str = Field(
        ..., title="Token", description="The API key/token to revoke"
    )


class PerplexityUsageAnalyticsConfig(BaseModel):
    """Retrieve account usage/analytics data."""

    operation: Literal["usage_analytics"] = Field(
        "usage_analytics",
        json_schema_extra={
            "const": "usage_analytics",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Computer Usage Analytics",
        },
        title="Computer Usage Analytics",
    )
    dataset: str = Field(
        "credit_usage",
        title="Dataset",
        description="Which usage dataset to retrieve",
        json_schema_extra={
            "enum": ["credit_usage", "connectors", "artifacts", "skills", "spaces", "workflows", "task_durations"],
            "x-enum-searchable": True,
        },
    )
    start_time: str = Field(
        ...,
        title="Start Time (unix seconds)",
        description="Window start as a Unix timestamp in seconds UTC (e.g. 1750000000)",
    )
    end_time: Optional[str] = Field(
        None, title="End Time (unix seconds)", description="Optional window end (Unix seconds UTC)"
    )
    bucket_width: Optional[str] = Field(
        None,
        title="Bucket Width",
        description="Aggregation bucket size",
        json_schema_extra={
            "enum": ["", "1d", "1h"],
            "enumNames": ["Default", "Daily", "Hourly"],
            "x-enum-searchable": True,
        },
    )


class PerplexityAcademicSearchConfig(BaseModel):
    """Chat completion grounded in scholarly sources (search_mode: academic)."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["academic_search"] = Field(
        "academic_search",
        json_schema_extra={
            "const": "academic_search",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Academic Search (Chat)",
        },
        title="Academic Search (Chat)",
    )
    model: str = Field(
        "sonar",
        title="Model",
        description="Sonar model to use",
        json_schema_extra={
            "enum": SONAR_MODELS,
            "x-enum-searchable": True,
        },
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The research question to answer from scholarly sources",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PerplexitySecSearchConfig(BaseModel):
    """Chat completion grounded in SEC filings (search_mode: sec)."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["sec_search"] = Field(
        "sec_search",
        json_schema_extra={
            "const": "sec_search",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "SEC Filings Search (Chat)",
        },
        title="SEC Filings Search (Chat)",
    )
    model: str = Field(
        "sonar",
        title="Model",
        description="Sonar model to use",
        json_schema_extra={
            "enum": SONAR_MODELS,
            "x-enum-searchable": True,
        },
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The question to answer from SEC filings",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PerplexityStructuredOutputConfig(BaseModel):
    """Chat completion with a JSON schema response_format for validated output."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["structured_output"] = Field(
        "structured_output",
        json_schema_extra={
            "const": "structured_output",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Structured JSON Output (Chat)",
        },
        title="Structured JSON Output (Chat)",
    )
    model: str = Field(
        "sonar",
        title="Model",
        description="Sonar model to use",
        json_schema_extra={
            "enum": SONAR_MODELS,
            "x-enum-searchable": True,
        },
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The question to answer",
        json_schema_extra={"ui:widget": "textarea"},
    )
    output_schema: str = Field(
        ...,
        title="JSON Schema",
        description="A JSON Schema object the response must conform to",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


PerplexityConfig = Annotated[
    Union[
        PerplexityChatCompletionConfig,
        PerplexityCreateAsyncCompletionConfig,
        PerplexityListAsyncCompletionsConfig,
        PerplexityGetAsyncCompletionConfig,
        PerplexitySearchConfig,
        PerplexityAgentResponseConfig,
        PerplexityCreateEmbeddingsConfig,
        PerplexityCreateContextualizedEmbeddingsConfig,
        PerplexityListModelsConfig,
        PerplexityGenerateAuthTokenConfig,
        PerplexityRevokeAuthTokenConfig,
        PerplexityUsageAnalyticsConfig,
        PerplexityAcademicSearchConfig,
        PerplexitySecSearchConfig,
        PerplexityStructuredOutputConfig,
    ],
    Discriminator("operation"),
]


class PerplexityNodeConfig(NodeConfig[PerplexityConfig, PerplexityCredential]):
    """Full configuration for the Perplexity node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _lines_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.splitlines() if p.strip()]
    return parts or None


def _build_messages(prompt: str, system_prompt: Optional[str]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def _as_number(value: Optional[str]):
    if value in (None, ""):
        return None
    try:
        if "." in str(value):
            return float(value)
        return int(value)
    except (TypeError, ValueError):
        return None


async def _perplexity_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Perplexity request and return a structured result."""
    url = f"{PERPLEXITY_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("error", err)
                    if isinstance(message, dict):
                        message = message.get("message", str(message))
                    elif not isinstance(message, str):
                        message = str(message)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[PerplexityNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[PerplexityNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class PerplexityNode(WorkflowNode):
    """Perplexity AI automation node (search-grounded chat, search, agent, embeddings)."""

    edit_examples = [
        "Answer a question with up-to-date web citations using Sonar",
        "Search the web for the latest news on a topic and return ranked results",
        "Run a deep-research report as an async job and poll for the result",
        "Ground an answer in academic papers or SEC filings",
        "Return structured JSON matching a schema from a search-grounded query",
    ]

    @classmethod
    def get_config_model(cls):
        return PerplexityNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (model dropdown)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "model":
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": [{"label": m, "value": m} for m in SONAR_MODELS]}
        result = await _perplexity_request(
            api_key, "GET", "/v1/models", action_name="list_models"
        )
        if result.get("status") != "success":
            return {"options": [{"label": m, "value": m} for m in SONAR_MODELS]}
        data = result.get("data") or {}
        models = data.get("data") if isinstance(data, dict) else data
        if not isinstance(models, list):
            return {"options": [{"label": m, "value": m} for m in SONAR_MODELS]}
        options = []
        for m in models:
            if isinstance(m, dict):
                mid = m.get("id") or m.get("name")
            else:
                mid = m
            if mid:
                options.append({"label": str(mid), "value": str(mid)})
        return {"options": options or [{"label": m, "value": m} for m in SONAR_MODELS]}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, PerplexityNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        platform_keyed = credentials is None and op.operation in PLATFORM_METERED_OPERATIONS
        if platform_keyed:
            if not self.user_id:
                raise ValueError("[PerplexityNode] No user context — cannot meter Perplexity usage.")
            api_key = self._get_platform_api_key()
            from billing.usage_tracker import usage_tracker

            await usage_tracker.enforce_credit_gate(
                self.user_id,
                organization_id=self.organization_id,
                sio=self.sio,
                sid=self.sid,
                user_resource=False,
                surface="perplexity",
            )
        elif credentials:
            api_key = credentials.api_key
        else:
            raise ValueError("Credentials are required. Add your Perplexity API key.")

        handlers = {
            "chat_completion": self._chat_completion,
            "create_async_completion": self._create_async_completion,
            "list_async_completions": self._list_async_completions,
            "get_async_completion": self._get_async_completion,
            "search": self._search,
            "agent_response": self._agent_response,
            "create_embeddings": self._create_embeddings,
            "create_contextualized_embeddings": self._create_contextualized_embeddings,
            "list_models": self._list_models,
            "generate_auth_token": self._generate_auth_token,
            "revoke_auth_token": self._revoke_auth_token,
            "usage_analytics": self._usage_analytics,
            "academic_search": self._academic_search,
            "sec_search": self._sec_search,
            "structured_output": self._structured_output,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        if platform_keyed and result.get("status") == "success":
            await self._track_platform_usage(op.operation, result)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Platform-keyed billing
    # ------------------------------------------------------------------
    @staticmethod
    def _get_platform_api_key() -> str:
        return require_platform_key("PERPLEXITY_API_KEY", "Perplexity", byok=True)

    async def _track_platform_usage(self, operation: str, result: Dict[str, Any]) -> None:
        """Bill a NoClick-keyed call. Cost source is declared per-op: the
        chat-completions surface must carry usage.cost.total_cost (hard error
        if absent — never book $0 silently); the Search API has no cost object,
        so it bills the published flat per-request price."""
        from billing.markup import (
            apply_perplexity_markup,
            round_up_to_credit_step,
        )
        from billing.pricing import PERPLEXITY_SEARCH_REQUEST_PRICE
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        cost_mode = PLATFORM_METERED_OPERATIONS[operation]
        if cost_mode == "flat_search":
            raw = PERPLEXITY_SEARCH_REQUEST_PRICE
        else:
            data = result.get("data")
            usage = data.get("usage") if isinstance(data, dict) else None
            cost_obj = usage.get("cost") if isinstance(usage, dict) else None
            cost = cost_obj.get("total_cost") if isinstance(cost_obj, dict) else None
            if cost is None:
                raise ValueError(
                    f"Perplexity response for '{operation}' has no usage.cost — "
                    "cannot meter platform-keyed usage"
                )
            raw = Decimal(str(cost))
        charged = round_up_to_credit_step(apply_perplexity_markup(raw))
        # Raw runner + org id; track_usage_event resolves the org owner
        # centrally (organization attribution policy choke point).
        await usage_tracker.track_usage_event(
            UsageEventData(
                user_id=self.user_id,
                total_cost=charged,
                usage_type="api_usage",
                usage_subtype="perplexity/api",
                quantity=Decimal("1"),
                unit_type="requests",
                user_resource=False,
                organization_id=self.organization_id,
                metadata={
                    "provider": "perplexity",
                    "operation": operation,
                    "cost_source": cost_mode,
                    "raw_cost_usd": float(raw),
                    "charged_cost_usd": float(charged),
                },
            ),
            sio=self.sio,
            sid=self.sid,
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _chat_completion(
        self, c: PerplexityChatCompletionConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "messages": _build_messages(c.prompt, c.system_prompt),
            "max_tokens": _as_number(c.max_tokens),
            "temperature": _as_number(c.temperature),
            "search_recency_filter": c.search_recency_filter or None,
            "search_domain_filter": _comma_list(c.search_domain_filter),
        }
        return await _perplexity_request(
            api_key, "POST", "/chat/completions", json_body=body, action_name="chat_completion"
        )

    async def _create_async_completion(
        self, c: PerplexityCreateAsyncCompletionConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "request": {
                "model": c.model,
                "messages": _build_messages(c.prompt, c.system_prompt),
            }
        }
        return await _perplexity_request(
            api_key, "POST", "/async/chat/completions", json_body=body,
            action_name="create_async_completion",
        )

    async def _list_async_completions(
        self, c: PerplexityListAsyncCompletionsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _perplexity_request(
            api_key, "GET", "/async/chat/completions",
            action_name="list_async_completions",
        )

    async def _get_async_completion(
        self, c: PerplexityGetAsyncCompletionConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _perplexity_request(
            api_key, "GET", f"/async/chat/completions/{c.request_id}",
            action_name="get_async_completion",
        )

    async def _search(self, c: PerplexitySearchConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "query": c.query,
            "max_results": _as_number(c.max_results),
            "search_recency_filter": c.search_recency_filter or None,
            "search_domain_filter": _comma_list(c.search_domain_filter),
            "search_language_filter": _comma_list(c.search_language_filter),
        }
        return await _perplexity_request(
            api_key, "POST", "/search", json_body=body, action_name="search"
        )

    async def _agent_response(
        self, c: PerplexityAgentResponseConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "input": c.prompt,
            "instructions": c.instructions or None,
            "reasoning": {"effort": c.reasoning_effort} if c.reasoning_effort else None,
        }
        return await _perplexity_request(
            api_key, "POST", "/v1/agent", json_body=body, action_name="agent_response"
        )

    async def _create_embeddings(
        self, c: PerplexityCreateEmbeddingsConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "input": _lines_list(c.input_text),
        }
        return await _perplexity_request(
            api_key, "POST", "/v1/embeddings", json_body=body, action_name="create_embeddings"
        )

    async def _create_contextualized_embeddings(
        self, c: PerplexityCreateContextualizedEmbeddingsConfig, api_key: str
    ) -> Dict[str, Any]:
        # Contextualized embeddings take `input` as a nested array — each document
        # is a list of chunks. We treat each non-empty line as a one-chunk document.
        lines = _lines_list(c.input_text) or []
        body = {
            "model": c.model,
            "input": [[line] for line in lines],
        }
        return await _perplexity_request(
            api_key, "POST", "/v1/contextualizedembeddings", json_body=body,
            action_name="create_contextualized_embeddings",
        )

    async def _list_models(
        self, c: PerplexityListModelsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _perplexity_request(
            api_key, "GET", "/v1/models", action_name="list_models"
        )

    async def _generate_auth_token(
        self, c: PerplexityGenerateAuthTokenConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"token_name": c.token_name or None}
        return await _perplexity_request(
            api_key, "POST", "/generate_auth_token", json_body=body,
            action_name="generate_auth_token",
        )

    async def _revoke_auth_token(
        self, c: PerplexityRevokeAuthTokenConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"auth_token": c.token}
        return await _perplexity_request(
            api_key, "POST", "/revoke_auth_token", json_body=body,
            action_name="revoke_auth_token",
        )

    async def _usage_analytics(
        self, c: PerplexityUsageAnalyticsConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            "dataset": c.dataset,
            "start_time": _as_number(c.start_time),
            "end_time": _as_number(c.end_time),
            "bucket_width": c.bucket_width or None,
        }
        return await _perplexity_request(
            api_key, "GET", "/v1/analytics/computer/usage", params=params,
            action_name="usage_analytics",
        )

    async def _academic_search(
        self, c: PerplexityAcademicSearchConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "messages": _build_messages(c.prompt, None),
            "search_mode": "academic",
        }
        return await _perplexity_request(
            api_key, "POST", "/chat/completions", json_body=body,
            action_name="academic_search",
        )

    async def _sec_search(
        self, c: PerplexitySecSearchConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "messages": _build_messages(c.prompt, None),
            "search_mode": "sec",
        }
        return await _perplexity_request(
            api_key, "POST", "/chat/completions", json_body=body,
            action_name="sec_search",
        )

    async def _structured_output(
        self, c: PerplexityStructuredOutputConfig, api_key: str
    ) -> Dict[str, Any]:
        try:
            schema = json.loads(c.output_schema)
        except (json.JSONDecodeError, TypeError) as e:
            return {
                "status": "error",
                "action": "structured_output",
                "error": f"Invalid JSON schema: {e}",
                "status_code": 400,
            }
        body = {
            "model": c.model,
            "messages": _build_messages(c.prompt, None),
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": schema},
            },
        }
        return await _perplexity_request(
            api_key, "POST", "/chat/completions", json_body=body,
            action_name="structured_output",
        )
