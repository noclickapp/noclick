"""Creem catalog/customer management and protected status metadata."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

FAMILY = "creem_api_key"
ROOTS = {"test": "https://test-api.creem.io/v1", "prod": "https://api.creem.io/v1"}
MAX_BYTES = 2_000_000
MAX_PAGE = 2_147_483_647


class CreemError(ValueError):
    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code, self.retry_after = status_code, retry_after


def text(value, maximum=255, empty=False):
    if not isinstance(value, str) or (not value and not empty) or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter text without edge whitespace or control characters")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Enter the exact Creem identifier without a URL or path")
    return value


def guard(data, stored=False):
    if not isinstance(data, dict) or ((stored or "credential_type" in data) and data.get("credential_type") != FAMILY):
        raise ValueError("Select a native Creem API key")


class CreemAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Creem API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.creem.io/api-reference/introduction", "x-credential-instructions": "Use an already issued account-scoped API key. Select Test or Live explicitly; their keys and data are separate. No token is minted or renewed."})
    credential_type: Literal["creem_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    environment: Literal["test", "prod"] = Field("test", title="Environment", description="Test uses test-api.creem.io; Live uses api.creem.io.")
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = text(value, 4096)
        if not value.isascii() or any(c.isspace() for c in value) or "://" in value:
            raise ValueError("Paste the issued API key without a header prefix or URL")
        return value


def credential(data):
    guard(data)
    try:
        return CreemAPIKeyCredential.model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Check the native Creem API key and environment") from None


def picker(field, parent=None):
    value = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        value["depends_on"] = parent
    return {"x-dynamic-options": value, "x-resource-type": "creem_" + field.removesuffix("_id")}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("product_id", "customer_id", "subscription_id", "license_id", mode="before", check_fields=False)
    @classmethod
    def validate_ids(cls, value):
        return identifier(value)

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def validate_name(cls, value):
        return text(value) if value is not None else value

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def validate_description(cls, value):
        return text(value, 4096, empty=True) if value is not None else value

    @field_validator("external_id", mode="before", check_fields=False)
    @classmethod
    def validate_external_id(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value)):
            raise ValueError("External ID must contain letters, digits, underscores or hyphens")
        return value


class Page(Config):
    page_number: int = Field(1, ge=1, le=MAX_PAGE, strict=True)
    page_size: int = Field(10, ge=1, le=100, strict=True, description="Local page bound of 100; the provider documents no maximum.")


class ListProducts(Page):
    operation: Literal["list_products"] = Field("list_products")
    status: Literal["active", "archived"] | None = None


class GetProduct(Config):
    operation: Literal["get_product"] = Field("get_product")
    product_id: str = Field(..., json_schema_extra=picker("product_id"))


class Write(Config):
    confirm_record_change: Literal[True] = Field(..., title="Confirm Record Change", description="Changes Creem catalog or customer records. Product creation makes a product purchasable; archiving stops new purchases. Notification behavior is not verified.")


class CreateProduct(Write):
    operation: Literal["create_product"] = Field("create_product")
    name: str
    description: str
    price: int = Field(..., ge=0, strict=True, title="Price in Cents", json_schema_extra={"anyOf": [{"const": 0}, {"type": "integer", "minimum": 100}]})
    currency: Literal["EUR", "USD"]
    tax_mode: Literal["inclusive", "exclusive"] = "inclusive"
    tax_category: Literal["saas", "digital-goods-service", "ebooks"] = "saas"

    @field_validator("price")
    @classmethod
    def validate_price(cls, value):
        if 0 < value < 100:
            raise ValueError("Price must be zero or at least 100 cents")
        return value


class UpdateProduct(Write):
    operation: Literal["update_product"] = Field("update_product")
    product_id: str = Field(..., json_schema_extra=picker("product_id"))
    name: str | None = None
    description: str | None = None
    clear_description: bool = False

    @model_validator(mode="after")
    def changes(self):
        if self.clear_description and self.description is not None:
            raise ValueError("Choose a description or Clear Description")
        if self.name is None and self.description is None and not self.clear_description:
            raise ValueError("Enter a name or description change")
        return self


class ArchiveProduct(Write):
    operation: Literal["archive_product"] = Field("archive_product")
    product_id: str = Field(..., json_schema_extra=picker("product_id"))


class ListCustomers(Page):
    operation: Literal["list_customers"] = Field("list_customers")
    page_size: int = Field(50, ge=1, le=100, strict=True)


class GetCustomer(Config):
    operation: Literal["get_customer"] = Field("get_customer")
    customer_id: str = Field(..., json_schema_extra=picker("customer_id"))


class CreateCustomer(Write):
    operation: Literal["create_customer"] = Field("create_customer")
    email: str = Field(..., json_schema_extra={"format": "email"}, description="Creates a customer record using this email; no checkout or billing request is made.")
    name: str
    external_id: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value):
        value = text(value, 254)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid customer email")
        return value


class UpdateCustomer(Write):
    operation: Literal["update_customer"] = Field("update_customer")
    customer_id: str = Field(..., json_schema_extra=picker("customer_id"))
    name: str | None = None
    external_id: str | None = None
    clear_external_id: bool = False

    @model_validator(mode="after")
    def changes(self):
        if self.clear_external_id and self.external_id is not None:
            raise ValueError("Choose an external ID or Clear External ID")
        if self.name is None and self.external_id is None and not self.clear_external_id:
            raise ValueError("Enter a name or external ID change")
        return self


class ListSubscriptions(Page):
    operation: Literal["list_subscriptions"] = Field("list_subscriptions")


class GetSubscription(Config):
    operation: Literal["get_subscription"] = Field("get_subscription")
    customer_id: str = Field(..., json_schema_extra=picker("customer_id"))
    subscription_id: str = Field(..., json_schema_extra=picker("subscription_id", "customer_id"))


class CustomerPage(Page):
    customer_id: str = Field(..., json_schema_extra=picker("customer_id"))


class ListCustomerSubscriptions(CustomerPage):
    operation: Literal["list_customer_subscriptions"] = Field("list_customer_subscriptions")


class ListCustomerOrders(CustomerPage):
    operation: Literal["list_customer_orders"] = Field("list_customer_orders")


class ListCustomerLicenses(CustomerPage):
    operation: Literal["list_customer_licenses"] = Field("list_customer_licenses")


class ListLicenseInstances(CustomerPage):
    operation: Literal["list_license_instances"] = Field("list_license_instances")
    license_id: str = Field(..., json_schema_extra=picker("license_id", "customer_id"))
    license_page: int = Field(1, ge=1, le=MAX_PAGE, strict=True, description="The customer-license page containing this license, checked with page size 100 before reading instances.")


CreemConfig = Annotated[Union[ListProducts, GetProduct, CreateProduct, UpdateProduct, ArchiveProduct, ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, ListSubscriptions, GetSubscription, ListCustomerSubscriptions, ListCustomerOrders, ListCustomerLicenses, ListLicenseInstances], Field(discriminator="operation")]


class CreemNodeConfig(NodeConfig[CreemConfig, CreemAPIKeyCredential]):
    pass


async def freshen(data, **kwargs):
    """Validate the credential supplied by staging's credential loader.

    API keys do not rotate; authorization and stored-row lookup belong to the
    existing shared loader rather than a provider-specific authority store.
    """
    return credential(data)


async def current_authority(data):
    guard(data, stored=True)


async def request(data, method, route, *, query=None, body=None):
    await current_authority(data)
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.request(method, ROOTS[data["environment"]] + "/" + route, headers={"x-api-key": data["api_key"], "Accept": "application/json"}, params=query, json=body)
    except (SSRFError, httpx.RequestError):
        raise CreemError("Creem could not be reached; the request is unverified") from None
    if response.status_code != 200:
        words = {400: "request was invalid", 401: "authentication was refused", 403: "authentication or permission was refused", 404: "resource was not found", 409: "record conflicts with an existing value", 429: "request rate limit reached"}
        delay = response.headers.get("Retry-After")
        retry = int(delay) if delay and delay.isascii() and delay.isdecimal() and len(delay) <= 8 else None
        raise CreemError(f"Creem HTTP {response.status_code}: {words.get(response.status_code, 'response was not accepted')}", response.status_code, retry)
    if len(response.content) > MAX_BYTES:
        raise CreemError("Creem response exceeds the supported size")
    try:
        payload = response.json()
    except ValueError:
        raise CreemError("Creem returned unreadable JSON") from None
    if not isinstance(payload, dict) or any(k in payload for k in ("error", "errors")) or payload.get("success", True) is not True or (type(payload.get("status")) in (int, float) and payload["status"] >= 400):
        raise CreemError("Creem returned an unsuccessful or unreadable response")
    return payload


def safe_text(value, data, maximum=4096, multiline=False):
    if not isinstance(value, str) or len(value) > maximum or any((ord(c) < 32 and not (multiline and c in "\n\t")) or ord(c) == 127 for c in value) or data["api_key"] in value:
        raise CreemError("Creem returned unreadable or protected metadata")
    return value


def protected_id(value, data):
    try:
        result = identifier(value)
    except ValueError:
        raise CreemError("Creem returned unreadable identifier metadata") from None
    if data["api_key"] in result:
        raise CreemError("Creem returned protected identifier metadata")
    return result


def resource(raw, data):
    if not isinstance(raw, dict) or not isinstance(raw.get("mode"), str) or raw.get("mode") not in ({"prod"} if data["environment"] == "prod" else {"test", "sandbox"}):
        raise CreemError("Creem returned a malformed resource or different environment")
    out = {"id": protected_id(raw.get("id"), data), "mode": raw["mode"]}
    if not isinstance(raw.get("object"), str) or not raw["object"]:
        raise CreemError("Creem returned unreadable resource metadata")
    if "created_at" not in raw:
        raise CreemError("Creem returned unreadable resource timestamps")
    for key in ("created_at", "updated_at"):
        if key in raw:
            out[key] = safe_text(raw[key], data, 64)
    return out


def enum(raw, key, values):
    if not isinstance(raw.get(key), str) or raw.get(key) not in values:
        raise CreemError("Creem returned an unreadable status or enum")
    return raw[key]


def number(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not 0 <= value <= MAX_PAGE or int(value) != value:
        raise CreemError("Creem returned unreadable numeric metadata")
    return int(value)


def product(raw, data):
    out = resource(raw, data)
    for key in ("name", "description"):
        out[key] = safe_text(raw.get(key), data, multiline=key == "description")
    out.update(price=number(raw.get("price")), currency=enum(raw, "currency", {"EUR", "USD"}), billing_type=enum(raw, "billing_type", {"onetime", "recurring"}), status=enum(raw, "status", {"active", "archived"}))
    return out


def customer(raw, data):
    out = resource(raw, data)
    for key in ("name", "external_id", "country"):
        out[key] = safe_text(raw[key], data) if raw.get(key) is not None else None
    return out


def relation(value, data):
    return resource(value, data)["id"] if isinstance(value, dict) else protected_id(value, data)


def subscription(raw, data):
    out = resource(raw, data)
    out.update(product_id=relation(raw.get("product"), data), customer_id=relation(raw.get("customer"), data), status=enum(raw, "status", {"active", "canceled", "unpaid", "paused", "trialing", "scheduled_cancel", "past_due"}))
    for key in ("current_period_start_date", "current_period_end_date", "canceled_at"):
        if key in raw:
            out[key] = safe_text(raw[key], data, 64) if raw[key] is not None else None
    return out


def order(raw, data):
    out = resource(raw, data)
    out.update(product_id=protected_id(raw.get("product"), data), customer_id=protected_id(raw["customer"], data) if raw.get("customer") is not None else None, status=enum(raw, "status", {"pending", "paid"}), type=enum(raw, "type", {"onetime", "recurring"}))
    return out


def license_metadata(raw, data):
    out = resource(raw, data)
    out.update(product_id=protected_id(raw.get("product_id"), data), status=enum(raw, "status", {"inactive", "active", "expired", "disabled"}), activation=number(raw.get("activation")), activation_limit=number(raw.get("activation_limit"), nullable=True))
    out["expires_at"] = safe_text(raw["expires_at"], data, 64) if raw.get("expires_at") is not None else None
    return out


def instance(raw, data):
    out = resource(raw, data)
    out["status"] = enum(raw, "status", {"active", "deactivated"})
    return out


def page(payload, project, data, requested, size, parent=None):
    if not isinstance(payload.get("items"), list) or len(payload["items"]) > size or not isinstance(payload.get("pagination"), dict):
        raise CreemError("Creem returned unreadable page metadata")
    p = payload["pagination"]
    out = {k: number(p.get(k), nullable=k in {"next_page", "prev_page"}) for k in ("total_records", "total_pages", "current_page", "next_page", "prev_page")}
    if any(k not in p for k in out) or out["current_page"] != requested or out["total_records"] < len(payload["items"]) or (out["next_page"] is not None and not requested < out["next_page"] <= out["total_pages"]) or (out["prev_page"] is not None and not 1 <= out["prev_page"] < requested):
        raise CreemError("Creem returned inconsistent pagination")
    rows = [project(x, data) for x in payload["items"]]
    if len({r["id"] for r in rows}) != len(rows) or (parent and any(r.get("customer_id") not in (None, parent) for r in rows)):
        raise CreemError("Creem returned duplicate identifiers or a different customer binding")
    return {"items": rows, "pagination": out, **({"requested_customer_id": parent} if parent else {})}


async def get_customer(data, cid):
    result = customer(await request(data, "GET", "customers", query={"customer_id": cid}), data)
    if result["id"] != cid:
        raise CreemError("Creem returned a different customer")
    return result


async def listing(data, route, project, requested=1, size=10, extra=None, parent=None):
    return page(await request(data, "GET", route, query={"page_number": requested, "page_size": size, **(extra or {})}), project, data, requested, size, parent)


class CreemNode(WorkflowNode):
    integration_type = "automation-creem"
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products", label_keys=("name",), proves="account")
    edit_examples = ["List my Creem products", "Create a one-time catalog product", "Update a customer name", "Check a customer's subscription or license status"]

    @classmethod
    def get_config_model(cls):
        return CreemNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            raise ConfigValidationError("Select a native Creem API key") from None
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["Select a native Creem API key"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return "Check the native Creem connection and operation fields"

    @classmethod
    async def validate_credential(cls, data, *, validation_context=None):
        if validation_context is not None:
            result = await validation_context.run_operation("list_products", {})
            await validation_context.accept(result)
            return {"valid": True}
        try:
            await listing(await freshen(data), "products/search", product)
            return {"valid": True}
        except CreemError as exc:
            return {"valid": False if exc.status_code in {401, 403} else None, "error": str(exc)}
        except (ValueError, TypeError, KeyError):
            return {"valid": False, "error": "Check the native Creem API key"}

    @classmethod
    async def validate_credential_access(cls, data, *, validation_context=None):
        return await cls.validate_credential(data, validation_context=validation_context)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        parent = identifier((context or {}).get("customer_id")) if field_name in {"subscription_id", "license_id"} else None
        if field_name not in {"product_id", "customer_id", "subscription_id", "license_id"}:
            raise ValueError("Unknown native Creem picker")
        data = await freshen(credential_data)
        await current_authority(data)
        query = text(search, 255) if search else ""
        scope = hashlib.sha256(json.dumps([field_name, parent, query, data["environment"], data["api_key"]], sort_keys=True).encode()).hexdigest()
        requested = 1
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 512:
                    raise ValueError()
                cursor = json.loads(base64.urlsafe_b64decode(page_token.encode("ascii")))
                if not isinstance(cursor, dict) or set(cursor) != {"scope", "page"} or cursor["scope"] != scope or type(cursor["page"]) is not int or not 1 <= cursor["page"] <= MAX_PAGE:
                    raise ValueError()
                requested = cursor["page"]
            except Exception:
                raise ValueError("Creem picker continuation belongs to a different connection, parent or search") from None
        if parent:
            await get_customer(data, parent)
        route, project = {"product_id": ("products/search", product), "customer_id": ("customers/list", customer), "subscription_id": (f"customers/{parent}/subscriptions", subscription), "license_id": (f"customers/{parent}/licenses", license_metadata)}[field_name]
        result = await listing(data, route, project, requested, 100, parent=parent)
        options = [{"value": r["id"], "label": (r.get("name") or r["id"]) + (" · " + r["status"] if r.get("status") else "")} for r in result["items"]]
        if query:
            options = [x for x in options if query.casefold() in x["label"].casefold()]
        nxt = result["pagination"]["next_page"]
        token = base64.urlsafe_b64encode(json.dumps({"scope": scope, "page": nxt}, separators=(",", ":")).encode()).decode() if nxt else None
        return {"options": options, "next_page_token": token}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a native Creem API key")
        config = self.config.config
        try:
            nested = self.node_data.get("config") or {}
            cid = self.node_data.get("credential_id")
            if isinstance(nested, dict) and nested.get("credential_id"):
                if cid and cid != nested["credential_id"]:
                    raise CreemError("Creem credential selection is ambiguous")
                cid = nested["credential_id"]
            data = await freshen(self.config.credentials.model_dump(mode="json"), credential_id=cid, pool=self.node_data.get("_approval_pool"), user_id=self.user_id, organization_id=self.organization_id, workflow_id=self.workflow_id)
            return {"status": "success", "action": config.operation, "data": await self._operation(data, config)}
        except CreemError as exc:
            return {"status": "error", "action": config.operation, "error": str(exc), "status_code": exc.status_code, "retry_after": exc.retry_after}
        except (ValueError, TypeError, KeyError):
            return {"status": "error", "action": config.operation, "error": "Creem credential or response could not be validated"}

    async def _operation(self, data, config):
        op = config.operation
        if op == "list_products":
            return await listing(data, "products/search", product, config.page_number, config.page_size, {"status": config.status} if config.status else None)
        if op == "get_product":
            result = product(await request(data, "GET", "products/" + config.product_id), data)
            if result["id"] != config.product_id:
                raise CreemError("Creem returned a different product")
            return result
        if op == "list_customers":
            return await listing(data, "customers/list", customer, config.page_number, config.page_size)
        if op == "get_customer":
            return await get_customer(data, config.customer_id)
        if op == "list_subscriptions":
            return await listing(data, "subscriptions/search", subscription, config.page_number, config.page_size)
        if op == "get_subscription":
            await get_customer(data, config.customer_id)
            result = subscription(await request(data, "GET", "subscriptions", query={"subscription_id": config.subscription_id}), data)
            if result["id"] != config.subscription_id or result["customer_id"] != config.customer_id:
                raise CreemError("Creem returned a different subscription or customer binding")
            return result
        if op in {"list_customer_subscriptions", "list_customer_orders", "list_customer_licenses", "list_license_instances"}:
            await get_customer(data, config.customer_id)
            if op == "list_license_instances":
                licenses = await listing(data, f"customers/{config.customer_id}/licenses", license_metadata, config.license_page, 100)
                if not any(r["id"] == config.license_id for r in licenses["items"]):
                    raise CreemError("Selected license was not found on the specified customer-license page")
                result = await listing(data, f"licenses/{config.license_id}/instances", instance, config.page_number, config.page_size)
                return {**result, "requested_customer_id": config.customer_id, "requested_license_id": config.license_id, "membership_page": config.license_page}
            tail, project = {"list_customer_subscriptions": ("subscriptions", subscription), "list_customer_orders": ("orders", order), "list_customer_licenses": ("licenses", license_metadata)}[op]
            return await listing(data, f"customers/{config.customer_id}/{tail}", project, config.page_number, config.page_size, parent=config.customer_id)
        if op in {"create_product", "update_product", "archive_product"}:
            route = "products" + ("/" + config.product_id if op != "create_product" else "")
            body = None
            if op == "create_product":
                body = {k: getattr(config, k) for k in ("name", "description", "price", "currency", "tax_mode", "tax_category")}
                body.update(billing_type="onetime", abandoned_cart_recovery_enabled=False)
            elif op == "update_product":
                body = {k: getattr(config, k) for k in ("name", "description") if getattr(config, k) is not None}
                if config.clear_description:
                    body["description"] = ""
            result = product(await request(data, {"create_product": "POST", "update_product": "PATCH", "archive_product": "DELETE"}[op], route, body=body), data)
            if op != "create_product" and result["id"] != config.product_id or op == "archive_product" and result["status"] != "archived":
                raise CreemError("Creem returned a different product or unconfirmed archive status")
        else:
            body = {k: getattr(config, k) for k in ("name", "external_id") if getattr(config, k) is not None}
            if op == "create_customer":
                body["email"] = config.email
            else:
                body["customer_id"] = config.customer_id
                if config.clear_external_id:
                    body["external_id"] = None
            result = customer(await request(data, "POST" if op == "create_customer" else "PATCH", "customers", body=body), data)
            if op == "update_customer" and result["id"] != config.customer_id:
                raise CreemError("Creem returned a different customer")
        return {"resource": result, "write_acknowledged": True, "verified_readback": None}
