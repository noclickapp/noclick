"""Strale REST operations pinned to its published 1.0.0 OpenAPI contract.

Each action sends one request; async executions return their transaction ID for polling.
"""
from __future__ import annotations
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.strale.io"
TYPE = "strale_api_key"
Slug = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Identifier = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]
Cap = Annotated[int, Field(ge=0, le=2147483647)]
Label = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f-\x9f]+$")]


class StraleAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Strale API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://strale.io/docs",
            "x-credential-instructions": "Paste your Strale API key from your account. Use the primary key for API key management, disputes and audit tokens. Executions spend your prepaid EUR balance up to the price limit you supply."})
    credential_type: Literal["strale_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste one API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ExecuteCapability(_Input):
    """Execute a named capability with a maximum EUR-cent price. Poll pending transactions separately."""
    operation: Literal["execute_capability"] = "execute_capability"
    capability_slug: Slug
    inputs: dict = Field(..., description="Input object from the selected capability's input_schema.")
    max_price_cents: int = Field(..., ge=1, le=2000)
    timeout_seconds: int = Field(30, ge=5, le=60)
    dry_run: bool = False


class ExecuteBatch(_Input):
    """Run one capability on up to 100 input objects within a total price limit."""
    operation: Literal["execute_batch"] = "execute_batch"
    capability_slug: Slug
    inputs: list[dict] = Field(..., min_length=1, max_length=100)
    max_total_price_cents: int = Field(..., ge=1, le=10000)
    timeout_seconds: float = Field(30, gt=0)
    dry_run: bool = False


class ExecuteSolution(_Input):
    """Execute a solution using its documented inputs and a maximum EUR-cent price."""
    operation: Literal["execute_solution"] = "execute_solution"
    slug: Slug
    inputs: dict
    max_price_cents: int = Field(..., ge=1)


class ListCapabilities(_Input):
    """Read the capability catalogue and input schemas."""
    operation: Literal["list_capabilities"] = "list_capabilities"


class GetCapability(_Input):
    """Read one capability's inputs, price and limits."""
    operation: Literal["get_capability"] = "get_capability"
    slug: Slug


class ListSolutions(_Input):
    """Read the solution catalogue, optionally filtered by category."""
    operation: Literal["list_solutions"] = "list_solutions"
    category: str | None = None


class GetSolution(_Input):
    """Read one solution and its input schema."""
    operation: Literal["get_solution"] = "get_solution"
    slug: Slug


class GetWalletBalance(_Input):
    """Read your prepaid wallet's EUR balance."""
    operation: Literal["get_wallet_balance"] = "get_wallet_balance"


class ListWalletTransactions(_Input):
    """Read wallet ledger entries as returned by Strale."""
    operation: Literal["list_wallet_transactions"] = "list_wallet_transactions"


class ListTransactions(_Input):
    """Read capability execution transactions as returned by Strale."""
    operation: Literal["list_transactions"] = "list_transactions"


class GetTransaction(_Input):
    """Read one transaction, including pending async execution status and output."""
    operation: Literal["get_transaction"] = "get_transaction"
    id: Identifier


class GetDispute(_Input):
    """Read a transaction's dispute status."""
    operation: Literal["get_dispute"] = "get_dispute"
    id: Identifier


class CreateDispute(_Input):
    """Submit a transaction dispute for human review using the primary API key."""
    operation: Literal["create_dispute"] = "create_dispute"
    id: Identifier
    reason: str = Field(..., min_length=1)
    affected_field: str | None = None
    contact_email: str | None = Field(None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class CreateAuditToken(_Input):
    """Issue a shareable audit token for a transaction you own; requires the primary key."""
    operation: Literal["create_audit_token"] = "create_audit_token"
    id: Identifier
    expires_in_days: int = Field(90, ge=1, le=365)


class DeleteTransaction(_Input):
    """Redact a transaction using the provider's deletion endpoint."""
    operation: Literal["delete_transaction"] = "delete_transaction"
    id: Identifier


class ListAPIKeys(_Input):
    """List active additional keys and spending; requires the primary key."""
    operation: Literal["list_api_keys"] = "list_api_keys"


class CreateAPIKey(_Input):
    """Create an additional API key; the new secret is returned once. Requires the primary key."""
    operation: Literal["create_api_key"] = "create_api_key"
    label: Label
    max_spend_per_hour_cents: Cap | None = None
    max_spend_total_cents: Cap | None = None


class UpdateAPIKey(_Input):
    """Update an additional key. Omit caps to retain them; explicitly set null to remove them."""
    operation: Literal["update_api_key"] = "update_api_key"
    id: Identifier
    label: Label | None = None
    max_spend_per_hour_cents: Cap | None = None
    max_spend_total_cents: Cap | None = None

    @model_validator(mode="after")
    def changes(self):
        if not (self.model_fields_set - {"operation", "id"}):
            raise ValueError("Supply a label or spending cap to update")
        if "label" in self.model_fields_set and self.label is None:
            raise ValueError("Label cannot be null")
        return self


class RevokeAPIKey(_Input):
    """Revoke an additional key; requires the primary key, which cannot be revoked here."""
    operation: Literal["revoke_api_key"] = "revoke_api_key"
    id: Identifier


class SuggestCapabilities(_Input):
    """Find capabilities using a natural-language task description."""
    operation: Literal["suggest_capabilities"] = "suggest_capabilities"
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(3, ge=1, le=10)


class SearchCatalogue(_Input):
    """Search the capability and solution catalogue with geography and type filters."""
    operation: Literal["search_catalogue"] = "search_catalogue"
    q: str = Field(..., min_length=2, max_length=200)
    limit: int = Field(6, ge=1, le=10)
    geo: str | None = None
    type: Literal["capability", "solution"] | None = None


Operation = Annotated[Union[ExecuteCapability, ExecuteBatch, ExecuteSolution, ListCapabilities,
    GetCapability, ListSolutions, GetSolution, GetWalletBalance, ListWalletTransactions,
    ListTransactions, GetTransaction, GetDispute, CreateDispute, CreateAuditToken,
    DeleteTransaction, ListAPIKeys, CreateAPIKey, UpdateAPIKey, RevokeAPIKey,
    SuggestCapabilities, SearchCatalogue], Field(discriminator="operation")]


class StraleConfig(NodeConfig[Operation, StraleAPIKeyCredential]):
    pass


ROUTES = {
    "execute_capability": ("POST", "/v1/do"),
    "execute_batch": ("POST", "/v1/do/batch"),
    "execute_solution": ("POST", "/v1/solutions/{slug}/execute"),
    "list_capabilities": ("GET", "/v1/capabilities"),
    "get_capability": ("GET", "/v1/capabilities/{slug}"),
    "list_solutions": ("GET", "/v1/solutions"),
    "get_solution": ("GET", "/v1/solutions/{slug}"),
    "get_wallet_balance": ("GET", "/v1/wallet/balance"),
    "list_wallet_transactions": ("GET", "/v1/wallet/transactions"),
    "list_transactions": ("GET", "/v1/transactions"),
    "get_transaction": ("GET", "/v1/transactions/{id}"),
    "get_dispute": ("GET", "/v1/transactions/{id}/dispute"),
    "create_dispute": ("POST", "/v1/transactions/{id}/dispute"),
    "create_audit_token": ("POST", "/v1/transactions/{id}/audit-token"),
    "delete_transaction": ("DELETE", "/v1/transactions/{id}"),
    "list_api_keys": ("GET", "/v1/api-keys"),
    "create_api_key": ("POST", "/v1/api-keys"),
    "update_api_key": ("PATCH", "/v1/api-keys/{id}"),
    "revoke_api_key": ("DELETE", "/v1/api-keys/{id}"),
    "suggest_capabilities": ("POST", "/v1/suggest"),
    "search_catalogue": ("GET", "/v1/suggest/typeahead"),
}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class StraleNode(WorkflowNode):
    integration_type = "automation-strale"
    connection_evidence = ConnectionEvidence(noun="wallets", operation="get_wallet_balance",
        label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return StraleConfig

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Strale API key")
        method, template = ROUTES[config.operation]
        path = template.format(**{k: quote(str(getattr(config, k)), safe="")
            for k in ("id", "slug") if hasattr(config, k)})
        values = config.model_dump(exclude={"operation", "id", "slug"}, exclude_none=True)
        if isinstance(config, UpdateAPIKey):
            values = config.model_dump(exclude={"operation", "id"}, exclude_unset=True)
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} else {}
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, BASE + path, headers=headers, **kwargs) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 16 * 1024 * 1024:
                        raise ValueError("Strale response exceeds the supported size")
                try:
                    data = _redact(json.loads(raw), credential.api_key)
                except (ValueError, UnicodeError):
                    raise ValueError(f"Strale returned an unreadable response (HTTP {response.status_code})") from None
                if not 200 <= response.status_code < 300:
                    return {"status": "error", "http_status": response.status_code, "error": data}
                if not isinstance(data, (dict, list)):
                    raise ValueError("Strale returned an unexpected response shape")
                if isinstance(data, dict) and data.get("error_code"):
                    return {"status": "error", "http_status": response.status_code, "error": data}
                result = {"status": "success", "http_status": response.status_code, "data": data}
                if isinstance(config, GetWalletBalance):
                    if not isinstance(data, dict) or type(data.get("balance_cents")) is not int or not isinstance(data.get("currency"), str):
                        raise ValueError("Strale did not return a wallet balance")
                    result["items"] = [{"name": f"{data['balance_cents'] / 100:.2f} {data['currency']} wallet"}]
                return result
