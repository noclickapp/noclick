"""Tenant-bound Zuora Billing v1/Object Query metadata operations.

Client credentials are supplied by the credential owner. Token renewal repeats
client_credentials; Zuora does not issue a refresh token for this grant.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
import json
import logging
import math
import re
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, OAuthRefreshError
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin, guarded_async_client

FAMILY = "zuora_client_credentials"
VERSION = "2025-08-12"
MAX_BYTES = 2 * 1024 * 1024
_PRIVATE = ContextVar("zuora_private_transport", default=False)
Environment = Literal["us_dev", "us1_sandbox", "us2_sandbox", "us1_prod", "us2_prod", "eu_dev", "eu_sandbox", "eu_prod", "apac_dev", "apac_prod"]
ORIGINS = {
    "us_dev": "https://rest.test.zuora.com", "us1_sandbox": "https://rest.sandbox.na.zuora.com",
    "us2_sandbox": "https://rest.apisandbox.zuora.com", "us1_prod": "https://rest.na.zuora.com",
    "us2_prod": "https://rest.zuora.com", "eu_dev": "https://rest.test.eu.zuora.com",
    "eu_sandbox": "https://rest.sandbox.eu.zuora.com", "eu_prod": "https://rest.eu.zuora.com",
    "apac_dev": "https://rest.test.ap.zuora.com", "apac_prod": "https://rest.ap.zuora.com",
}
OPS = ("check_connection", "list_accounts", "get_account", "list_contacts", "get_contact", "list_products", "get_product", "list_product_rate_plans", "get_product_rate_plan", "list_subscriptions", "get_subscription", "list_invoices", "get_invoice", "update_account_metadata", "update_contact_name", "update_product_description", "update_subscription_notes")


def plain(value, maximum=256, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value) or not empty and not value.strip():
        raise ValueError("Zuora requires bounded plain text")
    return value.strip()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("Use the Zuora record ID, not a number, name or URL")
    return value


def same_id(left, right):
    return identifier(left).replace("-", "").lower() == identifier(right).replace("-", "").lower()


def scope_claims(value):
    value = plain(value, 8192)
    tokens = value.split(" ")
    if any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", item) for item in tokens) or len(tokens) != len(set(tokens)):
        raise ValueError("Zuora returned an invalid actual token scope")
    tenants = [t[7:] for t in tokens if t.startswith("tenant.")]
    users = [t[5:] for t in tokens if t.startswith("user.")]
    entities = [identifier(t[7:]).replace("-", "").lower() for t in tokens if t.startswith("entity.")]
    if len(tenants) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", tenants[0]) or len(users) != 1:
        raise ValueError("Zuora token must identify its actual tenant and dedicated API user grant")
    user = identifier(users[0]).replace("-", "").lower()
    if len(entities) != len(set(entities)): raise ValueError("Zuora returned duplicate entity grants")
    return " ".join(sorted(tokens)), tenants[0], user, sorted(entities)


class ZuoraClientCredentialsCredential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, title="Zuora OAuth Client", json_schema_extra={
        "x-credential-url": "https://developer.zuora.com/docs/get-started/oauth-client-setup-steps",
        "x-credential-instructions": "Use your existing dedicated API user's OAuth client for this exact Zuora tenant and environment. Client credentials mint a one-hour bearer token; there is no browser callback or refresh token. API roles and subscription features remain tenant controlled. Select an entity only when its actual grant permits it.",
    })
    credential_type: Literal["zuora_client_credentials"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    environment: Environment = Field(..., title="Tenant Environment", description="Select the existing tenant's documented regional REST endpoint; no automatic production fallback.")
    client_id: str = Field(..., title="Existing OAuth Client ID")
    client_secret: str = Field(..., title="Existing OAuth Client Secret", json_schema_extra={"ui:widget": "password"})
    entity_id: Optional[str] = Field(None, title="Entity ID (if needed)", description="Optional documented entity ID. A token with multiple entity grants requires an explicit selection.")
    access_token: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    expires_at: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    scope: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    token_type: Optional[Literal["bearer"]] = Field(None, json_schema_extra={"ui:hidden": True})
    tenant_id: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    api_user_id: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    entity_ids: Optional[list[str]] = Field(None, json_schema_extra={"ui:hidden": True})

    @field_validator("client_id", mode="before")
    @classmethod
    def client(cls, value):
        value = plain(value, 36)
        try:
            if len(value) != 36 or str(UUID(value)) != value.lower(): raise ValueError()
        except (ValueError, TypeError): raise ValueError("Use the 36-character Zuora OAuth client ID") from None
        return value

    @field_validator("client_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(plain(value, 42), field_name="Zuora OAuth client secret")
        if re.search(r"\s|[?&#]", value) or value.lower().startswith("bearer "): raise ValueError("Paste the OAuth client secret only")
        return value

    @field_validator("entity_id", mode="before")
    @classmethod
    def entity(cls, value): return None if value is None or value == "" else identifier(value).replace("-", "").lower()

    @model_validator(mode="before")
    @classmethod
    def native_shape(cls, value):
        if isinstance(value, dict):
            if any(k in value for k in ("refresh_token", "base_url", "api_url", "password", "api_key", "scope_requested")):
                raise ValueError("Use native Zuora tenant OAuth client credentials")
            if "credential_type" not in value: return {**value, "credential_type": FAMILY}
        return value

    @model_validator(mode="after")
    def grant(self):
        cached = (self.access_token, self.expires_at, self.scope, self.token_type, self.tenant_id, self.api_user_id, self.entity_ids)
        if all(v is None for v in cached): return self
        if any(v is None for v in cached): raise ValueError("Zuora cached token requires its complete actual grant and expiry")
        self.access_token = clean_secret(plain(self.access_token, 8192), field_name="Zuora access token")
        if re.search(r"\s", self.access_token): raise ValueError("Zuora cached token is invalid")
        try:
            stamp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            if stamp.tzinfo is None: raise ValueError()
        except (ValueError, AttributeError): raise ValueError("Zuora cached expiry requires a timezone") from None
        actual, tenant, user, entities = scope_claims(self.scope)
        if self.tenant_id != tenant or self.api_user_id != user or self.entity_ids != entities:
            raise ValueError("Zuora saved token claims do not match its actual scope")
        if self.entity_id is not None and self.entity_id not in entities or len(entities) > 1 and self.entity_id is None:
            raise ValueError("Choose an entity permitted by the actual Zuora token grant")
        self.scope = actual
        return self


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect native Zuora tenant OAuth client credentials")
    try: return ZuoraClientCredentialsCredential.model_validate(data).model_dump()
    except Exception: raise ValueError("Zuora credential shape or grant binding is invalid") from None


def operation(name, label, category="Metadata"):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def resource(kind, name, parent=None):
    loader = {"field_name": name, "searchable": True}
    if parent: loader["depends_on"] = parent
    return Field(..., json_schema_extra={"x-resource-type": "zuora_"+kind, "x-dynamic-options": loader})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Config):
    page_size: int = Field(25, strict=True, ge=1, le=99)
    cursor: Optional[str] = Field(None, description="Opaque Object Query nextPage token, not a URL.")
    @field_validator("cursor", mode="before")
    @classmethod
    def page(cls, value): return None if value is None else page_cursor(value)


class _Account(_Config):
    account_id: str = resource("account", "account_id")
    _id = field_validator("account_id", mode="before")(identifier)


class _Product(_Config):
    product_id: str = resource("product", "product_id")
    _id = field_validator("product_id", mode="before")(identifier)


class ZuoraCheckConnectionConfig(_Config):
    operation: Literal["check_connection"] = operation("check_connection", "Check Tenant Account Read Access", "Connection")
class ZuoraListAccountsConfig(_Page):
    operation: Literal["list_accounts"] = operation("list_accounts", "List Account Metadata", "Accounts")
class ZuoraGetAccountConfig(_Account):
    operation: Literal["get_account"] = operation("get_account", "Get Account Metadata", "Accounts")
class ZuoraListContactsConfig(_Account, _Page):
    operation: Literal["list_contacts"] = operation("list_contacts", "List Account Contact Names", "Contacts")
class ZuoraGetContactConfig(_Account):
    operation: Literal["get_contact"] = operation("get_contact", "Get Account Contact Name", "Contacts")
    contact_id: str = resource("contact", "contact_id", "account_id")
    _child = field_validator("contact_id", mode="before")(identifier)
class ZuoraListProductsConfig(_Page):
    operation: Literal["list_products"] = operation("list_products", "List Product Catalog Metadata", "Catalog")
class ZuoraGetProductConfig(_Product):
    operation: Literal["get_product"] = operation("get_product", "Get Product Metadata and Description", "Catalog")
class ZuoraListProductRatePlansConfig(_Product, _Page):
    operation: Literal["list_product_rate_plans"] = operation("list_product_rate_plans", "List Product Rate Plan Metadata", "Catalog")
class ZuoraGetProductRatePlanConfig(_Product):
    operation: Literal["get_product_rate_plan"] = operation("get_product_rate_plan", "Get Product Rate Plan Metadata", "Catalog")
    product_rate_plan_id: str = resource("product_rate_plan", "product_rate_plan_id", "product_id")
    _child = field_validator("product_rate_plan_id", mode="before")(identifier)
class ZuoraListSubscriptionsConfig(_Account, _Page):
    operation: Literal["list_subscriptions"] = operation("list_subscriptions", "List Account Subscription Metadata", "Subscriptions")
class ZuoraGetSubscriptionConfig(_Account):
    operation: Literal["get_subscription"] = operation("get_subscription", "Get Account Subscription Metadata", "Subscriptions")
    subscription_id: str = resource("subscription", "subscription_id", "account_id")
    _child = field_validator("subscription_id", mode="before")(identifier)
class ZuoraListInvoicesConfig(_Account, _Page):
    operation: Literal["list_invoices"] = operation("list_invoices", "List Account Invoice Metadata", "Invoices")
class ZuoraGetInvoiceConfig(_Account):
    operation: Literal["get_invoice"] = operation("get_invoice", "Get Account Invoice Metadata", "Invoices")
    invoice_id: str = resource("invoice", "invoice_id", "account_id")
    _child = field_validator("invoice_id", mode="before")(identifier)
class ZuoraUpdateAccountMetadataConfig(_Account):
    operation: Literal["update_account_metadata"] = operation("update_account_metadata", "Update Account Name or Notes", "Accounts")
    name: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=65535)
    @field_validator("name", "notes", mode="before")
    @classmethod
    def text(cls, value, info): return None if value is None else plain(value, 255 if info.field_name == "name" else 65535, empty=info.field_name == "notes")
    @model_validator(mode="after")
    def fields(self):
        if self.name is None and self.notes is None: raise ValueError("Choose an account name or notes update")
        return self
class ZuoraUpdateContactNameConfig(ZuoraGetContactConfig):
    operation: Literal["update_contact_name"] = operation("update_contact_name", "Update Contact Name", "Contacts")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def text(cls, value): return plain(value, 100)
class ZuoraUpdateProductDescriptionConfig(_Product):
    operation: Literal["update_product_description"] = operation("update_product_description", "Update Product Description", "Catalog")
    description: str = Field(..., max_length=500)
    @field_validator("description", mode="before")
    @classmethod
    def text(cls, value): return plain(value, 500, empty=True)
class ZuoraUpdateSubscriptionNotesConfig(ZuoraGetSubscriptionConfig):
    operation: Literal["update_subscription_notes"] = operation("update_subscription_notes", "Update Subscription Notes", "Subscriptions")
    notes: str = Field(..., max_length=1000, description="Notes only. The request explicitly keeps collect and runBilling false.")
    @field_validator("notes", mode="before")
    @classmethod
    def text(cls, value): return plain(value, 1000, empty=True)


ZuoraOperation = Annotated[Union[ZuoraCheckConnectionConfig, ZuoraListAccountsConfig, ZuoraGetAccountConfig, ZuoraListContactsConfig, ZuoraGetContactConfig, ZuoraListProductsConfig, ZuoraGetProductConfig, ZuoraListProductRatePlansConfig, ZuoraGetProductRatePlanConfig, ZuoraListSubscriptionsConfig, ZuoraGetSubscriptionConfig, ZuoraListInvoicesConfig, ZuoraGetInvoiceConfig, ZuoraUpdateAccountMetadataConfig, ZuoraUpdateContactNameConfig, ZuoraUpdateProductDescriptionConfig, ZuoraUpdateSubscriptionNotesConfig], Discriminator("operation")]
class ZuoraNodeConfig(NodeConfig[ZuoraOperation, ZuoraClientCredentialsCredential]):
    credentials: Optional[ZuoraClientCredentialsCredential] = None


async def current_credential(data):
    return credential(data)


class _Privacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get() and (record.name in {"httpx", "httpcore"} or record.name.startswith(("httpx.", "httpcore."))):
            record.msg, record.args = "Zuora private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _Privacy()
def _install_privacy():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names.update(n for n in logging.Logger.manager.loggerDict if n.startswith(("httpx.", "httpcore.")))
    for name in names: logging.getLogger(name).addFilter(_FILTER)
    for handler in logging.getLogger().handlers: handler.addFilter(_FILTER)


class ZuoraHTTPError(RuntimeError):
    def __init__(self, status):
        self.status_code = status
        super().__init__({401: "Zuora bearer authentication refused", 403: "Zuora tenant API role or feature access refused", 404: "Zuora record was not found", 429: "Zuora request limit reached", 202: "Zuora asynchronous acceptance does not establish a completed operation"}.get(status, "Zuora did not complete the native request")+f" (HTTP {status}); verify a write before retrying")


def _json(content):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError()
            out[k] = v
        return out
    try: return json.loads(content, object_pairs_hook=pairs, parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
    except Exception: raise RuntimeError("Zuora returned invalid native JSON") from None


async def _transport(data, method, path, *, params=None, body=None, token=False):
    base = ORIGINS[data["environment"]]
    async def exact(req): assert_exact_url_origin(str(req.url), base)
    headers = {"Accept": "application/json"}
    if not token:
        headers.update({"Authorization": "Bearer "+data["access_token"], "Zuora-Version": VERSION})
        if len(data["entity_ids"]) > 1: headers["Zuora-Entity-Ids"] = data["entity_id"]
    _install_privacy(); marker = _PRIVATE.set(True)
    try:
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False, event_hooks={"request": [exact]}) as client:
            kwargs = {"data": body} if token else {"json": body}
            async with client.stream(method, base+path, headers=headers, params=params, **kwargs) as response:
                if response.status_code != 200: raise ZuoraHTTPError(response.status_code)
                if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json": raise RuntimeError("Zuora returned an unexpected response media type")
                content = bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > MAX_BYTES: raise RuntimeError("Zuora response exceeded its local byte bound")
    except ZuoraHTTPError: raise
    except Exception: raise RuntimeError("Zuora transport could not complete; verify an attempted write before retrying") from None
    finally: _PRIVATE.reset(marker)
    payload = _json(content)
    if not isinstance(payload, dict): raise RuntimeError("Zuora returned an invalid native response envelope")
    if payload.get("success") is False or payload.get("Success") is False: raise RuntimeError("Zuora refused the native operation; no completion was established")
    return payload


async def mint(data):
    shaped = credential(data)
    payload = await _transport(shaped, "POST", "/oauth/token", body={"grant_type": "client_credentials", "client_id": shaped["client_id"], "client_secret": shaped["client_secret"]}, token=True)
    try:
        token = clean_secret(plain(payload.get("access_token"), 8192), field_name="Zuora access token")
        if re.search(r"\s", token) or not isinstance(payload.get("token_type"), str) or payload["token_type"].lower() != "bearer": raise ValueError()
        lifetime = payload.get("expires_in")
        if type(lifetime) not in (int, float) or not math.isfinite(lifetime) or not 0 < lifetime <= 3600: raise ValueError()
        scope, tenant, user, entities = scope_claims(payload.get("scope"))
        result = {"access_token": token, "expires_at": (datetime.now(timezone.utc)+timedelta(seconds=lifetime)).isoformat(), "scope": scope, "token_type": "bearer", "tenant_id": tenant, "api_user_id": user, "entity_ids": entities}
        if shaped["scope"] is not None and any(shaped[k] != result[k] for k in ("scope", "tenant_id", "api_user_id", "entity_ids")): raise ValueError()
        credential({**shaped, **result})
        return result
    except Exception: raise RuntimeError("Zuora returned an incomplete or changed actual tenant/user/entity token grant; reconnect") from None


def expired(data):
    if not data.get("access_token"): return True
    return expiry_expired(data["expires_at"])


def expiry_expired(value):
    if value is None: return True
    return datetime.fromisoformat(value.replace("Z", "+00:00")) <= datetime.now(timezone.utc)+timedelta(seconds=60)


def page_cursor(value):
    value = plain(value, 4096)
    if re.search(r"\s|[?&#]", value) or "://" in value: raise ValueError("Use the opaque Zuora Object Query cursor")
    return value


FIELDS = {
    "accounts": ("id", "name", "accountNumber", "status", "currency", "createdDate", "updatedDate"),
    "contacts": ("id", "accountId", "firstName", "lastName", "nickname"),
    "products": ("id", "name", "sKU", "productNumber", "category", "effectiveStartDate", "effectiveEndDate", "createdDate", "updatedDate"),
    "product-rate-plans": ("id", "productId", "name", "grade", "productRatePlanNumber", "effectiveStartDate", "effectiveEndDate", "createdDate", "updatedDate"),
    "subscriptions": ("id", "accountId", "name", "status", "isLatestVersion", "version", "revision", "termType", "currentTerm", "currentTermPeriodType", "subscriptionStartDate", "subscriptionEndDate", "termStartDate", "termEndDate", "contractEffectiveDate", "serviceActivationDate"),
    "invoices": ("id", "accountId", "invoiceNumber", "status", "currency", "invoiceDate", "dueDate", "targetDate", "createdDate", "updatedDate"),
}
PRODUCT_FIELDS = ("Id", "Name", "Description", "SKU", "Category", "EffectiveStartDate", "EffectiveEndDate", "CreatedDate", "UpdatedDate")
PARENTS = {"contacts": ("accounts", "account_id", "accountId"), "subscriptions": ("accounts", "account_id", "accountId"), "invoices": ("accounts", "account_id", "accountId"), "product-rate-plans": ("products", "product_id", "productId")}
IDS = {"accounts": "account_id", "contacts": "contact_id", "products": "product_id", "product-rate-plans": "product_rate_plan_id", "subscriptions": "subscription_id", "invoices": "invoice_id"}


def project(row, kind):
    if not isinstance(row, dict): raise RuntimeError("Zuora returned an invalid metadata record")
    try: rid = identifier(row.get("id"))
    except ValueError: raise RuntimeError("Zuora returned an invalid metadata ID") from None
    out = {"id": rid}
    for key in FIELDS[kind][1:]:
        if key not in row: continue
        value = row[key]
        if value is None: out[key] = None
        elif key in {"accountId", "productId"}:
            try: out[key] = identifier(value)
            except ValueError: raise RuntimeError("Zuora returned an invalid parent ID") from None
        elif key == "isLatestVersion":
            if type(value) is not bool: raise RuntimeError("Zuora returned invalid boolean metadata")
            out[key] = value
        elif key in {"version", "currentTerm", "grade"}:
            if type(value) is not int: raise RuntimeError("Zuora returned invalid integer metadata")
            out[key] = value
        elif isinstance(value, str) and len(value) <= 1000 and not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", value):
            if key.endswith("Date"):
                try:
                    if len(value) == 10: date.fromisoformat(value)
                    else: datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError: raise RuntimeError("Zuora returned invalid date metadata") from None
            out[key] = value
        else: raise RuntimeError("Zuora returned invalid allowlisted metadata")
    return out


async def request(data, method, path, *, params=None, body=None):
    shaped = await current_credential(data)
    if not shaped["access_token"] or expired(shaped): raise RuntimeError("Zuora bearer token is unavailable or expiring; reload the operation")
    read = method == "GET" and (re.fullmatch(r"/object-query/(?:accounts|contacts|products|product-rate-plans|subscriptions|invoices)(?:/[0-9a-fA-F-]{32,36})?", path) or re.fullmatch(r"/v1/object/product/[0-9a-fA-F-]{32,36}", path))
    write = method == "PUT" and re.fullmatch(r"/v1/(?:accounts|contacts|subscriptions|object/product)/[0-9a-fA-F-]{32,36}", path)
    if not read and not write: raise ValueError("Use a declared Zuora metadata endpoint")
    if write:
        allowed = {"name", "notes"} if path.startswith("/v1/accounts/") else {"firstName", "lastName"} if path.startswith("/v1/contacts/") else {"Description"} if path.startswith("/v1/object/product/") else {"notes", "collect", "runBilling"}
        if not isinstance(body, dict) or not body or set(body)-allowed or path.startswith("/v1/subscriptions/") and (body.get("collect") is not False or body.get("runBilling") is not False): raise ValueError("Zuora exposes only explicit ordinary metadata writes")
    payload = await _transport(shaped, method, path, params=params, body=body)
    await current_credential(data)
    return payload


async def get_record(data, kind, rid, config=None, *, notes=False):
    if kind in PARENTS:
        parent_kind, parent_key, field = PARENTS[kind]
        parent = identifier((config or {}).get(parent_key))
        await get_record(data, parent_kind, parent)
    fields = list(FIELDS[kind])+( ["notes"] if notes else [])
    payload = await request(data, "GET", f"/object-query/{kind}/{rid}", params={"fields[]": fields})
    projected = project(payload, kind)
    try:
        if not same_id(projected["id"], rid) or kind in PARENTS and not same_id(projected.get(field), parent): raise ValueError()
    except ValueError: raise RuntimeError("Zuora record or selected parent witness did not match") from None
    return payload, projected


async def get_product(data, rid):
    payload = await request(data, "GET", "/v1/object/product/"+rid, params={"fields": ",".join(PRODUCT_FIELDS)})
    row = {"id": payload.get("Id"), "name": payload.get("Name"), "sKU": payload.get("SKU"), "category": payload.get("Category"), "effectiveStartDate": payload.get("EffectiveStartDate"), "effectiveEndDate": payload.get("EffectiveEndDate"), "createdDate": payload.get("CreatedDate"), "updatedDate": payload.get("UpdatedDate")}
    projected = project(row, "products")
    try:
        if not same_id(projected["id"], rid): raise ValueError()
        description = payload.get("Description")
        if description is not None: projected["description"] = plain(description, 500, empty=True)
    except ValueError: raise RuntimeError("Zuora returned invalid product metadata or ID") from None
    return payload, projected


async def records(data, config):
    name = config["operation"]
    if name == "check_connection":
        payload = await request(data, "GET", "/object-query/accounts", params={"pageSize": 1, "fields[]": ["id"]})
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) > 1: raise RuntimeError("Zuora bounded protected read did not complete")
        for row in rows: project(row, "accounts")
        return {"reachable": True, "identity_verified": False, "proves": "reachability", "message": "Tenant account read accepted. Token claims bind the grant; they do not establish account identity, write roles or feature entitlement."}
    if name.startswith("list_"):
        kind = name[5:].replace("_", "-")
        parent = None
        if kind in PARENTS:
            parent_kind, parent_key, parent_field = PARENTS[kind]
            parent = identifier(config.get(parent_key))
            await get_record(data, parent_kind, parent)
        values = {"pageSize": config.get("page_size", 25), "fields[]": list(FIELDS[kind])}
        if config.get("cursor") is not None: values["cursor"] = page_cursor(config["cursor"])
        payload = await request(data, "GET", "/object-query/"+kind, params=values)
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) > values["pageSize"]: raise RuntimeError("Zuora returned an invalid bounded Object Query list")
        projected = [project(row, kind) for row in rows]
        if parent is not None:
            try: projected = [row for row in projected if same_id(row.get(parent_field), parent)]
            except ValueError: raise RuntimeError("Zuora returned missing or invalid child parent metadata") from None
        cursor = payload.get("nextPage")
        if cursor is not None:
            try: cursor = page_cursor(cursor)
            except ValueError: raise RuntimeError("Zuora returned an invalid Object Query cursor") from None
            if cursor == config.get("cursor"): raise RuntimeError("Zuora returned a repeated Object Query cursor")
        return {"records": projected, "next_page_token": cursor, "parent_filter": "local_page" if parent else None}
    if name.startswith("get_"):
        kind = {"account": "accounts", "contact": "contacts", "product": "products", "product_rate_plan": "product-rate-plans", "subscription": "subscriptions", "invoice": "invoices"}[name[4:]]
        rid = config[IDS[kind]]
        _raw, row = await get_product(data, rid) if kind == "products" else await get_record(data, kind, rid, config)
        return {"record": row}
    if name == "update_account_metadata":
        kind, rid = "accounts", config["account_id"]
        await get_record(data, kind, rid)
        body = {key: config[key] for key in ("name", "notes") if config.get(key) is not None}
        response = await request(data, "PUT", "/v1/accounts/"+rid, body=body)
    elif name == "update_contact_name":
        kind, rid = "contacts", config["contact_id"]
        await get_record(data, kind, rid, config)
        body = {"firstName": config["first_name"], "lastName": config["last_name"]}
        response = await request(data, "PUT", "/v1/contacts/"+rid, body=body)
        try:
            if not same_id(response.get("accountId"), config["account_id"]): raise ValueError()
        except ValueError: raise RuntimeError("Zuora contact write did not retain the selected account") from None
    elif name == "update_product_description":
        kind, rid = "products", config["product_id"]
        await get_product(data, rid)
        body = {"Description": config["description"]}
        response = await request(data, "PUT", "/v1/object/product/"+rid, params={"rejectUnknownFields": "true"}, body=body)
        try:
            if response.get("Success") is not True or not same_id(response.get("Id"), rid): raise ValueError()
        except ValueError: raise RuntimeError("Zuora product write did not establish matching completion") from None
    elif name == "update_subscription_notes":
        kind, rid = "subscriptions", config["subscription_id"]
        await get_record(data, kind, rid, config)
        body = {"notes": config["notes"], "collect": False, "runBilling": False}
        response = await request(data, "PUT", "/v1/subscriptions/"+rid, body=body)
        try:
            if not same_id(response.get("subscriptionId"), rid) or response.get("invoiceId") or response.get("paymentId"): raise ValueError()
        except ValueError: raise RuntimeError("Zuora subscription metadata completion is uncertain; inspect before retrying") from None
    else: raise ValueError("Unsupported native Zuora operation")
    if kind != "products" and response.get("success") is not True: raise RuntimeError("Zuora did not establish metadata write completion")
    raw, row = await get_product(data, rid) if kind == "products" else await get_record(data, kind, rid, config, notes="notes" in body)
    if any(raw.get(key) != value for key, value in body.items() if key not in {"collect", "runBilling"}): raise RuntimeError("Zuora metadata write readback did not match; inspect before retrying")
    return {"record": row, "mutation_completed": True, "readback_verified": True}


class ZuoraNode(WorkflowNode):
    integration_type = "automation-zuora"
    workflow_credential_refresh = True
    scope_registry = ScopeRegistry(provider="zuora", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})
    connection_evidence = ConnectionEvidence(operation="check_connection", proves="reachability", noun="Zuora tenant account API")
    edit_examples = ["List tenant account and catalog metadata", "Read subscription and invoice status for an existing account", "Update an account's notes", "Update product descriptions without changing prices"]
    @classmethod
    def get_config_model(cls): return ZuoraNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Connect valid native Zuora tenant client credentials"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        shaped = credential(credential_data)
        async def renew(secret):
            return await mint({**shaped, "client_secret": secret})
        try:
            await ensure_fresh_oauth_token(
                credential=shaped, pool=pool, user_id=user_id, credential_id=credential_id,
                refresh=renew, is_expired=expiry_expired, refresh_token_key="client_secret",
                stale=lambda data: not data.get("access_token"),
                additional_token_fields=("scope", "token_type", "tenant_id", "api_user_id", "entity_ids"),
                provider="Zuora", caller_path="freshen_credential")
        except OAuthRefreshError:
            raise RuntimeError("Zuora token renewal failed; retry or reconnect") from None
        result = credential(shaped)
        credential_data.update(result)
        return result
    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            data = await cls.freshen_credential(credential_data)
            await records(data, {"operation": "check_connection"})
            return {"valid": True, "identity_verified": False, "proves": "reachability"}
        except Exception:
            return {"valid": False, "error": "Zuora tenant account read could not be verified"}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        kinds = {value: kind for kind, value in IDS.items()}
        if field_name not in kinds: raise ValueError("Unsupported Zuora native picker")
        kind = kinds[field_name]
        values = {"operation": "list_"+kind.replace("-", "_"), "page_size": 50, "cursor": None if page_token is None else page_cursor(page_token)}
        if kind in PARENTS:
            _parent_kind, parent_key, _field = PARENTS[kind]
            values[parent_key] = identifier((context or {}).get(parent_key))
        await current_credential(credential_data)
        result = await records(credential_data, values)
        options = [{"value": row["id"], "label": str(row.get("name") or row.get("invoiceNumber") or row.get("firstName") or row["id"])} for row in result["records"]]
        return {"options": filter_options_by_search(options, normalize_search(search)), "next_page_token": result["next_page_token"]}
    async def execute(self, inputs):
        if not isinstance(self.config, ZuoraNodeConfig) or self.config.credentials is None: raise ValueError("Connect native Zuora tenant client credentials")
        raw = (self.node_data or {}).get("credentials")
        data = await self.freshen_credential(raw if raw is not None else self.config.credentials.model_dump(),
            pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"))
        return await records(data, self.config.config.model_dump())
