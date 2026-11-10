"""Wisboo v1 store automation against the published OpenAPI 1.0.0.

Each action makes one request. Lists return one page with provider metadata.
Writes are never automatically retried; reuse the same idempotency key when
retrying an inspected request.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.wisboo.com"
DOCS = "https://docs.wisboo.com/wisboo-api/introduction"


class WisbooAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Wisboo API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "In Wisboo, open Configuración → API Keys and create a key. Paste it without the Bearer prefix. Find the matching store ID under Tienda → Información. Public API access must be enabled for your plan.",
        })
    credential_type: Literal["wisboo_api_key"] = Field("wisboo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    store_id: str = Field(..., title="Store ID", min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Wisboo API key, without a header or prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page", description="One-based page number.")
    size: int = Field(50, ge=1, le=50, title="Page size", description="Returns one page. Use metadata.total_record_count to decide whether to request another.")


class _User(_Input):
    user_id: str = Field(..., min_length=1, title="User ID")


class _Access(_Input):
    access_id: str = Field(..., min_length=1, title="Product access ID")


class _Write(_Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[\x21-\x7e]+$", title="Idempotency key", description="Keep the same key when retrying this exact request. Use a new key for a different change.")


class _Profile(_Input):
    name: str | None = Field(None, title="First name")
    last_name: str | None = Field(None, title="Last name")
    phone: str | None = Field(None, title="Phone")
    country: str | None = Field(None, title="Country", description="ISO 3166 alpha-2 country code, for example AR.")
    language: str | None = Field(None, title="Language")
    external_id: str | None = Field(None, max_length=255, title="External ID")
    custom_fields: dict[str, Any] | None = Field(None, title="Custom fields", description="Field keys configured in your Wisboo store.")


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List users", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title="Name filter")
    email: EmailStr | None = Field(None, title="Email filter")


class CreateUser(_Profile, _Write):
    operation: Literal["create_user"] = Field("create_user", title="Create user", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="First name")
    email: EmailStr = Field(..., min_length=1, title="Email")
    language: Literal["ES", "PT", "EN"] | None = Field(None, title="Language")
    last_name: str = Field(..., min_length=1, title="Last name")
    avatar: HttpUrl | None = Field(None, title="Avatar URL")


class GetUser(_User):
    operation: Literal["get_user"] = Field("get_user", title="Get user", json_schema_extra={"ui:hidden": True})


class UpdateUser(_User, _Profile, _Write):
    operation: Literal["update_user"] = Field("update_user", title="Update user", json_schema_extra={"ui:hidden": True})


class UpdateUserEmail(_User, _Write):
    operation: Literal["update_user_email"] = Field("update_user_email", title="Update user email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, title="New email")


class GenerateMagicLink(_User, _Write):
    operation: Literal["generate_magic_link"] = Field("generate_magic_link", title="Generate user magic link", description="Creates a sign-in link for the selected user. Treat the returned link as a secret.", json_schema_extra={"ui:hidden": True})


class ListPurchases(_Page):
    operation: Literal["list_purchases"] = Field("list_purchases", title="List purchases", json_schema_extra={"ui:hidden": True})
    email: EmailStr | None = Field(None, title="Buyer email")
    product_id: str | None = Field(None, title="Product ID")
    user_id: str | None = Field(None, title="User ID")


class ListProductAccesses(_Page):
    operation: Literal["list_product_accesses"] = Field("list_product_accesses", title="List product accesses", json_schema_extra={"ui:hidden": True})
    product_id: str | None = Field(None, title="Product ID")
    user_id: str | None = Field(None, title="User ID")


class GrantProductAccess(_Write):
    operation: Literal["grant_product_access"] = Field("grant_product_access", title="Grant product access", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, title="User ID")
    product_id: str = Field(..., min_length=1, title="Product ID")


class UpdateProductAccess(_Access, _Write):
    operation: Literal["update_product_access"] = Field("update_product_access", title="Update product access", json_schema_extra={"ui:hidden": True})
    status: Literal["with_access", "without_access"] | None = Field(None, title="Access status")
    access_due_date: AwareDatetime | None = Field(None, title="Access due date", description="ISO 8601 date and time with timezone.")


class RevokeProductAccess(_Access, _Write):
    operation: Literal["revoke_product_access"] = Field("revoke_product_access", title="Revoke product access", description="Removes the user's access to this product.", json_schema_extra={"ui:hidden": True})


class ListProducts(_Page):
    operation: Literal["list_products"] = Field("list_products", title="List products", json_schema_extra={"ui:hidden": True})
    product_type: Literal["course_type", " bundle_type", "downloadable_type", "webinar_type"] | None = Field(None, title="Product type", description="The published v1 contract includes a leading space for bundle_type.")
    parent_id: str | None = Field(None, title="Parent bundle ID")


class GetProduct(_Input):
    operation: Literal["get_product"] = Field("get_product", title="Get product", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, title="Product ID")


class OnNewProductAccess(PollTriggerConfigBase):
    operation: Literal["on_new_product_access"] = Field("on_new_product_access", title="On new product access", description="Polls accesses newest first. Baselines existing accesses when armed. Supports at most 1,000 accesses in this scope; narrow with a user or product filter if needed.", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    user_id: str | None = Field(None, title="User ID filter")
    product_id: str | None = Field(None, title="Product ID filter")


WisbooOperation = Annotated[Union[
    ListUsers, CreateUser, GetUser, UpdateUser, UpdateUserEmail,
    GenerateMagicLink, ListPurchases, ListProductAccesses, GrantProductAccess,
    UpdateProductAccess, RevokeProductAccess, ListProducts, GetProduct, OnNewProductAccess,
], Field(discriminator="operation")]


class WisbooNodeConfig(NodeConfig[WisbooOperation, WisbooAPIKeyCredential]):
    pass


# Each entry maps to exactly one operation in OpenAPI version 1.0.0.
ROUTES = {
    "list_users": ("GET", "/users", None),
    "create_user": ("POST", "/users", None),
    "get_user": ("GET", "/users/{id}", "user_id"),
    "update_user": ("PUT", "/users/{id}", "user_id"),
    "update_user_email": ("PUT", "/users/{id}/email", "user_id"),
    "generate_magic_link": ("POST", "/users/{id}/magic_links", "user_id"),
    "list_purchases": ("GET", "/purchases", None),
    "list_product_accesses": ("GET", "/product_accesses", None),
    "grant_product_access": ("POST", "/product_accesses", None),
    "update_product_access": ("PUT", "/product_accesses/{id}", "access_id"),
    "revoke_product_access": ("DELETE", "/product_accesses/{id}", "access_id"),
    "list_products": ("GET", "/products", None),
    "get_product": ("GET", "/products/{id}", "product_id"),
}


def _path_id(value):
    if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use a Wisboo resource ID")
    return quote(value, safe="")


class WisbooNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-wisboo"
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products", label_keys=("name", "slug", "id"))

    @classmethod
    def get_config_model(cls):
        return WisbooNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_product_access":
            return bool(output.get("new_access_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        accesses = output.get("accesses") if isinstance(output, dict) else None
        if not isinstance(accesses, list):
            return super().resolve_agent_event(output)
        if not accesses:
            return None
        lines = []
        for access in accesses[:10]:
            user = access.get("user") or {}
            product = access.get("product") or {}
            who = " ".join(str(user.get(k) or "") for k in ("name", "last_name")).strip()
            lines.append(f"- {who or user.get('email') or user.get('id')} ({user.get('email')}; user {user.get('id')}) gained access to {product.get('name') or product.get('id')} (product {product.get('id')}; access {access.get('id')}) at {access.get('created_at')}; status {access.get('status')}.")
        if len(accesses) > 10:
            lines.append(f"- … and {len(accesses) - 10} more accesses in the output")
        return {"text": f"Wisboo: {len(accesses)} new product access(es):\n" + "\n".join(lines), "conversation_key": None}

    async def _poll_accesses(self, config):
        records = []
        for page in range(1, 21):
            listing = ListProductAccesses(page=page, size=50, user_id=config.user_id, product_id=config.product_id)
            result = await self._perform(listing)
            rows = result["data"]
            metadata = result["metadata"]
            if any(not isinstance(row.get("id"), str) or not row["id"] for row in rows):
                raise ValueError("Wisboo access is missing its ID")
            records.extend(rows)
            total = metadata.get("total_record_count")
            if type(total) is not int or total < len(records):
                raise ValueError("Wisboo returned invalid access pagination metadata")
            if len(records) >= total:
                break
            if len(rows) != 50:
                raise ValueError("Wisboo returned an incomplete access page")
        else:
            raise ValueError("More than 1,000 accesses; narrow the trigger with a user or product filter")
        if len({row["id"] for row in records}) != len(records):
            raise ValueError("Wisboo repeated an access across pages; retry the poll")
        fresh = await self._filter_unseen(records, lambda row: row["id"])
        return {"status": "success", "accesses": fresh, "new_access_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wisboo API key and store ID")
        config = self.config.config
        if isinstance(config, OnNewProductAccess):
            return await self._poll_accesses(config)
        return await self._perform(config)

    async def _perform(self, config):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wisboo API key and store ID")
        credential = self.config.credentials
        method, path, id_field = ROUTES[config.operation]
        data = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if id_field:
            path = path.replace("{id}", _path_id(data.pop(id_field)))
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        key = data.pop("idempotency_key", None)
        if key is not None:
            headers["X-Idempotency-Key"] = key
        if config.operation == "list_product_accesses":
            data = {k + "[]" if k in {"user_id", "product_id"} else k: v for k, v in data.items()}
        url = BASE_URL + "/v1/stores/" + _path_id(credential.store_id) + path
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, headers=headers,
                    **({"params": data} if method == "GET" else {"json": data} if data or method != "POST" else {}))
        except httpx.HTTPError:
            raise ValueError("Wisboo request did not complete; inspect writes before retrying") from None
        expected = 204 if config.operation == "revoke_product_access" else 201 if config.operation in {"create_user", "grant_product_access", "update_product_access", "generate_magic_link"} else 200
        if response.status_code != expected:
            detail = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Wisboo HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or (config.operation == "update_user_email" and response.status_code == 200 and not response.content):
            return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": None}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Wisboo returned a non-JSON response; inspect writes before retrying") from None
        if not isinstance(payload, dict):
            raise ValueError("Wisboo returned an unexpected response shape")
        if config.operation.startswith("list_"):
            if not isinstance(payload.get("data"), list) or any(not isinstance(row, dict) for row in payload["data"]):
                raise ValueError("Wisboo returned an invalid list response")
            return {"status": "success", "operation": config.operation, "http_status": response.status_code,
                "data": payload["data"], "metadata": payload.get("metadata", {})}
        return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": payload}
