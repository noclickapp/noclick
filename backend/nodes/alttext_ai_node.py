"""AltText.ai v1 account and image automation. Contract: https://alttext.ai/openapi.yml."""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class AlttextAiCredential(BaseModel):
    model_config = ConfigDict(title="Alttext.ai API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://alttext.ai/account/api_keys",
        "x-credential-instructions": "Paste an API key from your AltText.ai account. NoClick sends it in X-API-Key. Key-management reads require a full-access key. Connect checks your account."})
    credential_type: Literal["alttext_ai_api_key"] = Field("alttext_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without headers or whitespace")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetAccount(Input):
    operation: Literal["get_account"] = "get_account"

class UpdateAccount(Input):
    operation: Literal["update_account"] = "update_account"
    name: str | None = Field(None, max_length=512)
    webhook_url: str | None = Field(None, max_length=1024)
    notification_email: str | None = None

class ListImages(Input):
    operation: Literal["list_images"] = "list_images"
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    url: str | None = None

class SearchImages(Input):
    operation: Literal["search_images"] = "search_images"
    q: str = Field(..., min_length=1, max_length=256)
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)

class Asset(Input):
    asset_id: str = Field(..., min_length=1, max_length=128)
    @field_validator("asset_id")
    @classmethod
    def asset(cls, value):
        if any(c in value for c in '?&#\\/%<>+') or value in {'.', '..'}:
            raise ValueError("Use an AltText.ai asset ID without reserved characters")
        return value

class GetImage(Asset):
    operation: Literal["get_image"] = "get_image"

class DeleteImage(Asset):
    operation: Literal["delete_image"] = "delete_image"

class UpdateImage(Asset):
    operation: Literal["update_image"] = "update_image"
    alt_text: str = Field(..., max_length=1024)
    metadata: dict | None = None
    lang: str | None = None
    overwrite: bool = False

class CreateImage(Input):
    operation: Literal["create_image"] = "create_image"
    url: str = Field(..., min_length=1, description="Public image URL to send to AltText.ai")
    asset_id: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None
    lang: str | None = None
    keywords: list[str] | None = Field(None, max_length=6)
    negative_keywords: list[str] | None = Field(None, max_length=6)
    gpt_prompt: str | None = Field(None, max_length=768)
    max_chars: int | None = Field(None, ge=80, le=500)
    overwrite: bool = False

class ScrapePage(Input):
    operation: Literal["scrape_page"] = "scrape_page"
    url: str = Field(..., min_length=1)
    lang: str | None = None
    include_existing: bool = False
    keywords: list[str] | None = Field(None, max_length=6)
    negative_keywords: list[str] | None = Field(None, max_length=6)

class ListApiKeys(Input):
    operation: Literal["list_api_keys"] = "list_api_keys"
    status: Literal["active", "revoked", "all"] = "active"
    q: str | None = None
    after: str | None = None
    limit: int = Field(20, ge=1, le=100)

class GetApiKey(Input):
    operation: Literal["get_api_key"] = "get_api_key"
    id: int = Field(..., ge=1)
    detail: Literal["full"] | None = None

class GetApiKeyHistory(Input):
    operation: Literal["get_api_key_history"] = "get_api_key_history"
    id: int = Field(..., ge=1)
    after: str | None = None
    limit: int = Field(20, ge=1, le=100)

# AltText.ai's own MCP server: agents get its tools through a person's AltText.ai sign-in.
AlttextAiMcpCredential = mcp_credential("alttext_ai", "https://mcp.alttext.ai/mcp", app="AltText.ai")


AlttextAiConfig = Annotated[Union[GetAccount, UpdateAccount, ListImages, SearchImages,
    CreateImage, GetImage, UpdateImage, DeleteImage, ScrapePage, ListApiKeys, GetApiKey, GetApiKeyHistory], Field(discriminator="operation")]

class AlttextAiFullConfig(NodeConfig[AlttextAiConfig, Union[AlttextAiCredential, AlttextAiMcpCredential]]):
    pass

class AlttextAiNode(WorkflowNode):
    integration_type = "automation-alttext-ai"
    credential_provider_labels = {"alttext_ai": "AltText.ai Account"}
    connection_evidence = ConnectionEvidence(identity_operation="get_account", noun="account", label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return AlttextAiFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an AltText.ai API key")
        c = self.config.config
        op = c.operation
        data = c.model_dump(exclude={"operation"}, exclude_none=True)
        method, path, params, body = "GET", "/account", {}, None
        if op == "update_account":
            method, body = "PUT", {"account": data}
        elif op in {"list_images", "search_images"}:
            path, params = ("/images/search" if op == "search_images" else "/images"), data
        elif op == "create_image":
            method, path = "POST", "/images"
            image = {k: data.pop(k) for k in ("url", "asset_id", "tags", "metadata") if k in data}
            body = {"image": image, **data}
        elif op in {"get_image", "update_image", "delete_image"}:
            path = "/images/" + quote(data.pop("asset_id"), safe="")
            if op == "delete_image":
                method = "DELETE"
            elif op == "update_image":
                method = "PUT"
                params = {k: data.pop(k) for k in ("lang", "overwrite") if k in data}
                body = {"image": data}
        elif op == "scrape_page":
            method, path = "POST", "/images/page_scrape"
            body = {"page_scrape": {"url": data.pop("url")}, **data}
        elif op == "list_api_keys":
            path, params = "/api_keys", data
        elif op in {"get_api_key", "get_api_key_history"}:
            path = "/api_keys/" + str(data.pop("id")) + ("/history" if op == "get_api_key_history" else "")
            params = data
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        async with guarded_async_client(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, "https://alttext.ai/api/v1" + path,
                headers={"X-API-Key": self.config.credentials.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            # Preserve provider rejection text for the connection verdict.
            return {"status": "error", "http_status": response.status_code, "error": response.text.replace(self.config.credentials.api_key, "[redacted]")}
        response.raise_for_status()
        result = response.json() if response.content else {}
        if isinstance(result, dict) and (result.get("error") or result.get("errors")):
            return {"status": "error", "error": result}
        # API key read responses can contain tokens; keep them out of workflow output.
        def redact(value):
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k not in {"token", "raw"}}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value.replace(self.config.credentials.api_key, "[redacted]") if isinstance(value, str) else value
        output = {"status": "success", "operation": op, "data": redact(result)}
        await self.emit(output)
        return output
