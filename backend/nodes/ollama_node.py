"""Ollama native HTTP API: non-streaming inference and model administration.

Cloud inference uses a pasted Ollama key. Model administration needs a reachable
Ollama server, optionally behind an HTTPS bearer-auth proxy. Localhost is not
the user's Mac when a workflow runs remotely. Every operation makes one provider request.
References: https://docs.ollama.com/api/introduction and /api/authentication.
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client


class OllamaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Ollama API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://ollama.com/settings/keys",
        "x-credential-instructions": "Create an Ollama API key in Settings → Keys and paste it here for cloud inference, usage and balance. Model management requires an Ollama Server connection instead. Connection testing first reads your authenticated cloud balance, then lists available models. The public model catalog proves reachability only; it does not name your account."})
    credential_type: Literal["ollama_api_key"] = Field("ollama_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class OllamaServerCredential(BaseModel):
    model_config = ConfigDict(title="Ollama Server", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.ollama.com/api/introduction",
        "x-credential-instructions": "Enter your publicly reachable Ollama server origin without /api. Hosted workflows cannot reach localhost or a private LAN. Local Ollama itself needs no authentication; if you expose it through an authenticated HTTPS proxy, paste that proxy's bearer token. Tokens require HTTPS. Cloud usage and balance require the Ollama API Key connection instead. Connection testing lists this server's models and proves reachability."})
    credential_type: Literal["ollama_server"] = Field("ollama_server", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., min_length=1, title="Server URL", description="Public HTTP(S) origin without /api. Use HTTPS when sending a proxy token.")
    api_key: str | None = Field(None, title="Proxy API Key", repr=False, json_schema_extra={"ui:widget": "password"}, description="Optional bearer token for your own HTTPS proxy.")

    @field_validator("server_url", mode="before")
    @classmethod
    def origin(cls, value):
        return https_origin(value)

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        return None if value is None or value == "" else OllamaAPIKeyCredential.token(value)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class _ModelInput(_Input):
    model: str = Field(..., min_length=1, description="Exact Ollama model name, including tag or namespace when needed.", json_schema_extra={"x-dynamic-options": {"field_name": "model", "allow_custom": True, "searchable": True}})


class OllamaToolFunction(_Input):
    name: str = Field(..., min_length=1)
    description: str | None = None
    parameters: dict[str, Any]


class OllamaTool(_Input):
    type: Literal["function"] = "function"
    function: OllamaToolFunction


class OllamaToolCallFunction(_Input):
    name: str = Field(..., min_length=1)
    description: str | None = None
    arguments: dict[str, Any] | None = None


class OllamaToolCall(_Input):
    function: OllamaToolCallFunction


class OllamaMessage(_Input):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    images: list[str] | None = Field(None, description="Base64 image inputs for vision models.")
    tool_calls: list[OllamaToolCall] | None = None


class _Inference(_ModelInput):
    format: Literal["json"] | dict[str, Any] | None = Field(None, description="JSON output or a JSON schema.")
    options: dict[str, Any] | None = Field(None, description="Ollama model runtime options, such as temperature or num_ctx.")
    think: StrictBool | str | None = Field(None, description="Thinking setting supported by the selected model.")
    keep_alive: str | float | None = Field(None, description="Model keep-alive duration, or 0 to unload after the request.")


class OllamaGenerateConfig(_Inference):
    """Generate text; returns the complete response and usage metrics."""
    operation: Literal["generate_response"] = Field("generate_response", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., description="Text prompt to complete.")
    system: str | None = None
    suffix: str | None = None
    images: list[str] | None = None
    raw: StrictBool | None = None


class OllamaChatConfig(_Inference):
    """Generate the next assistant message; tool calls are returned, not executed."""
    operation: Literal["generate_chat"] = Field("generate_chat", json_schema_extra={"ui:hidden": True})
    messages: list[OllamaMessage] = Field(..., min_length=1)
    tools: list[OllamaTool] | None = Field(None, description="Ollama function tool definitions.")


class OllamaEmbedConfig(_ModelInput):
    """Generate vector embeddings for one text or a batch."""
    operation: Literal["generate_embeddings"] = Field("generate_embeddings", json_schema_extra={"ui:hidden": True})
    input: str | list[str] = Field(..., description="Text or array of texts to embed.")
    truncate: StrictBool | None = None
    dimensions: int | None = Field(None, ge=1)
    keep_alive: str | None = None
    options: dict[str, Any] | None = None


class OllamaListModelsConfig(_Input):
    """List models available from the selected endpoint."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})


class OllamaListRunningConfig(_Input):
    """List models currently loaded on the Ollama server."""
    operation: Literal["list_running_models"] = Field("list_running_models", json_schema_extra={"ui:hidden": True})


class OllamaShowConfig(_ModelInput):
    """Show a model's metadata, capabilities and template."""
    operation: Literal["show_model"] = Field("show_model", json_schema_extra={"ui:hidden": True})
    verbose: StrictBool | None = None


class OllamaCreateConfig(_ModelInput):
    """Create a model from an existing model on your own Ollama server."""
    operation: Literal["create_model"] = Field("create_model", json_schema_extra={"ui:hidden": True})
    from_model: str = Field(..., alias="from", min_length=1, title="Base model")
    system: str | None = None
    template: str | None = None
    parameters: dict[str, Any] | None = None
    messages: list[OllamaMessage] | None = None
    license: str | list[str] | None = None
    quantize: str | None = None


class OllamaCopyConfig(_Input):
    """Copy a model to a new name on your own Ollama server."""
    operation: Literal["copy_model"] = Field("copy_model", json_schema_extra={"ui:hidden": True})
    source: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)


class OllamaPullConfig(_ModelInput):
    """Download a model onto your own Ollama server."""
    operation: Literal["pull_model"] = Field("pull_model", json_schema_extra={"ui:hidden": True})


class OllamaPushConfig(_ModelInput):
    """Publish a model from your own server, signed in with publishing permission."""
    operation: Literal["push_model"] = Field("push_model", json_schema_extra={"ui:hidden": True})


class OllamaDeleteConfig(_ModelInput):
    """Delete a model from your own Ollama server."""
    operation: Literal["delete_model"] = Field("delete_model", json_schema_extra={"ui:hidden": True})


class OllamaVersionConfig(_Input):
    """Get the Ollama server version."""
    operation: Literal["get_version"] = Field("get_version", json_schema_extra={"ui:hidden": True})


class OllamaUsageConfig(_Input):
    """Read Ollama cloud account usage; team scope requires team admin access."""
    operation: Literal["get_usage"] = Field("get_usage", json_schema_extra={"ui:hidden": True})
    range: Literal["24h", "7d", "30d"] = "7d"
    scope: Literal["self", "team"] = "self"
    group_by: Literal["model"] | None = None


class OllamaBalanceConfig(_Input):
    """Read the Ollama cloud account's included and purchased credit balance."""
    operation: Literal["get_balance"] = Field("get_balance", json_schema_extra={"ui:hidden": True})


OllamaConfig = Annotated[Union[OllamaGenerateConfig, OllamaChatConfig, OllamaEmbedConfig,
    OllamaListModelsConfig, OllamaListRunningConfig, OllamaShowConfig, OllamaCreateConfig,
    OllamaCopyConfig, OllamaPullConfig, OllamaPushConfig, OllamaDeleteConfig,
    OllamaVersionConfig, OllamaUsageConfig, OllamaBalanceConfig], Field(discriminator="operation")]


class OllamaFullConfig(NodeConfig[OllamaConfig, Union[OllamaAPIKeyCredential, OllamaServerCredential]]):
    pass


ROUTES = {
    "generate_response": ("POST", "/api/generate"),
    "generate_chat": ("POST", "/api/chat"),
    "generate_embeddings": ("POST", "/api/embed"),
    "list_models": ("GET", "/api/tags"),
    "list_running_models": ("GET", "/api/ps"),
    "show_model": ("POST", "/api/show"),
    "create_model": ("POST", "/api/create"),
    "copy_model": ("POST", "/api/copy"),
    "pull_model": ("POST", "/api/pull"),
    "push_model": ("POST", "/api/push"),
    "delete_model": ("DELETE", "/api/delete"),
    "get_version": ("GET", "/api/version"),
    "get_usage": ("GET", "/api/usage"),
    "get_balance": ("GET", "/api/balance"),
}
STREAMING = {"generate_response", "generate_chat", "create_model", "pull_model", "push_model"}


class OllamaNode(WorkflowNode):
    integration_type = "automation-ollama"
    credential_provider_labels = {"ollama": "Ollama"}
    connection_evidence = ConnectionEvidence(field="model", noun="available models", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OllamaFullConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "model":
            return []
        if page_token is not None:
            raise ValueError("Ollama model lists do not use page tokens")
        from nodes.core.registry import NodeFactory
        credential = TypeAdapter(Union[OllamaAPIKeyCredential, OllamaServerCredential]).validate_python(credential_data)
        async def read(operation):
            node = NodeFactory.create_node(node_id="ollama-options", node_type=cls.integration_type,
                node_data={"config": {"operation": operation}, "credentials": credential.model_dump()})
            result = await node.execute({})
            if result.get("status") != "success":
                raise ValueError(f"Ollama {result.get('http_status')}: {result.get('error')}")
            return result["data"]
        # Cloud tags are public. An authenticated account read must accept the
        # key before public catalog rows can be shown as connection evidence.
        if isinstance(credential, OllamaAPIKeyCredential):
            await read("get_balance")
        data = await read("list_models")
        query = (search or "").casefold()
        return [{"value": row["name"], "label": row["name"]} for row in data["models"]
            if isinstance(row, dict) and isinstance(row.get("name"), str) and query in row["name"].casefold()]

    async def execute(self, input_data):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Ollama API key")
        op = self.config.config
        operation = op.operation
        method, path = ROUTES[operation]
        cloud = isinstance(credential, OllamaAPIKeyCredential)
        server_url = "https://ollama.com" if cloud else credential.server_url
        if operation in {"get_usage", "get_balance"} and not cloud:
            raise ValueError("Cloud usage and balance need an Ollama API Key connection")
        if operation in {"create_model", "copy_model", "pull_model", "push_model", "delete_model", "list_running_models", "get_version"} and cloud:
            raise ValueError("This operation needs an Ollama Server connection")
        if credential.api_key and urlsplit(server_url).scheme != "https":
            raise ValueError("Bearer tokens require HTTPS")
        fields = op.model_dump(by_alias=True, exclude={"operation"}, exclude_none=True)
        if operation in STREAMING:
            fields["stream"] = False
        kwargs = {"params": fields} if method == "GET" else {"json": fields}
        async with guarded_async_client(timeout=300, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, server_url + path,
                headers={"Accept": "application/json", **({"Authorization": "Bearer " + credential.api_key} if credential.api_key else {})}, **kwargs)
        if response.status_code != 200:
            # Preserve provider error text for rejected-credential evidence, redact the key.
            try:
                message = response.json().get("error")
            except (ValueError, AttributeError):
                message = None
            message = message if isinstance(message, str) else "Ollama request failed"
            message = (message.replace(credential.api_key, "[redacted]") if credential.api_key else message)[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message}
        # /api/copy and /api/delete can acknowledge with an empty 200 body.
        if operation in {"copy_model", "delete_model"} and not response.content:
            return {"status": "success", "data": {}, "http_status": 200}
        if len(response.content) > 20_000_000:
            raise ValueError("Ollama response exceeds the JSON size limit")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected an Ollama JSON object")
        if "error" in body:
            message = (str(body["error"]).replace(credential.api_key, "[redacted]") if credential.api_key else str(body["error"]))[:2000]
            return {"status": "error", "http_status": 200, "error": message}
        if operation in {"list_models", "list_running_models"}:
            if not isinstance(body.get("models"), list):
                raise ValueError("Expected the Ollama models array")
        if operation in {"generate_response", "generate_chat"} and body.get("done") is not True:
            raise ValueError("Ollama returned an incomplete generation")
        if operation in {"create_model", "pull_model", "push_model"} and body.get("status") != "success":
            raise ValueError("Ollama did not acknowledge completion")
        return {"status": "success", "data": body, "http_status": 200}
