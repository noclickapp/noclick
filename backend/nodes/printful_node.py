"""Traditional Printful v1 catalog, bound-store metadata and unsubmitted drafts.

The fixed api.printful.com transport is separate from Printful Enterprise on
Printify. Closed projections omit recipients, charges, files and media URLs.
"""
from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE = "https://api.printful.com"
MAX_BYTES = 2 * 1024 * 1024
FAMILIES = {"printful_private_token", "printful_oauth_access_token"}


def _text(value, *, maximum=250):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("A nonempty bounded text value is required.")
    return value.strip()


def _id(value):
    if type(value) is int and 0 < value <= 9223372036854775807:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) and int(value) <= 9223372036854775807:
        return int(value)
    raise ValueError("Use a positive numeric Printful ID, without a URL or external-ID alias.")


def _token(value):
    value = _text(value, maximum=4096)
    if any(c.isspace() for c in value) or value.lower().startswith(("bearer", "basic", "http:", "https:")):
        raise ValueError("Enter only the issued token, without a header or URL.")
    return value


def _expiry(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,11}", str(value)):
        raise ValueError("Token expiry must be its issued UNIX timestamp in seconds.")
    return str(value)


class _Binding(BaseModel):
    store_id: int = Field(..., title="Bound Store ID", description="The explicitly selected store authorized by this token. This binding cannot be overridden by operation inputs.")
    model_config = ConfigDict(hide_input_in_errors=True)
    _store_id = field_validator("store_id", mode="before")(_id)


class PrintfulPrivateTokenCredential(_Binding):
    credential_type: Literal["printful_private_token"] = Field("printful_private_token", json_schema_extra={"ui:hidden": True})
    private_token: str = Field(..., title="Private Token", repr=False, json_schema_extra={"ui:widget": "password"})
    access_level: Literal["store", "account"] = Field(..., title="Issued Access Level", description="Use the actual token access level. Account tokens send X-PF-Store-Id; store tokens use their issued store context.")
    expires_at: str | None = Field(None, title="Issued Expiry (UNIX seconds)", description="Private tokens cannot refresh. If known, supply the actual expiry; absent means unknown, not perpetual.")
    _private_token = field_validator("private_token", mode="before")(_token)
    _expires_at = field_validator("expires_at", mode="before")(_expiry)
    model_config = ConfigDict(title="Printful Private Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.printful.com/tokens",
        "x-credential-instructions": "Use an already issued traditional Printful token with the required scopes. Store metadata requires stores_list. Read scopes do not authorize writes. No token is created here.",
    })


class PrintfulOAuthAccessTokenCredential(_Binding):
    credential_type: Literal["printful_oauth_access_token"] = Field("printful_oauth_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Already Issued Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    token_type: Literal["bearer"] = Field(..., title="Issued Token Type")
    expires_at: str = Field(..., title="Issued Expiry (UNIX seconds)", description="Public App access tokens expire after one hour. This manual credential does not exchange or refresh them.")
    _access_token = field_validator("access_token", mode="before")(_token)
    _expires_at = field_validator("expires_at", mode="before")(_expiry)
    model_config = ConfigDict(title="Printful Issued OAuth Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.printful.com/apps",
        "x-credential-instructions": "Manual already-issued store-level Public App access only. Copy actual bearer token type and expires_at. OAuth installation, client credentials and rotating refresh are not implemented here.",
    })


PrintfulCredential = Union[PrintfulPrivateTokenCredential, PrintfulOAuthAccessTokenCredential]
_CREDENTIAL = TypeAdapter(Annotated[PrintfulCredential, Field(discriminator="credential_type")])


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") not in FAMILIES:
        raise ValueError("A current Printful credential family is required.")
    forbidden = ("refresh_token", "client_secret", "api_key", "password", "base_url", "host", "shop_token", "account_switch")
    if any(raw.get(k) is not None for k in forbidden):
        raise ValueError("Unsupported token, refresh or target fields in Printful credential.")
    if raw["credential_type"] == "printful_private_token" and any(raw.get(k) is not None for k in ("access_token", "token_type")):
        raise ValueError("Private and Public App token families cannot be mixed.")
    if raw["credential_type"] == "printful_oauth_access_token" and any(raw.get(k) is not None for k in ("private_token", "access_level")):
        raise ValueError("Public App tokens have store-level access only.")
    credential = _CREDENTIAL.validate_python(raw)
    if credential.expires_at is not None and int(credential.expires_at) <= time.time():
        raise ValueError("Printful token is expired; replace this manual credential.")
    return credential.model_dump()


def _op(name, category, label):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-category": category, "x-is-trigger": False, "x-display-name": label})


def _picker(name, depends=None):
    options = {"field_name": name, "allow_custom": True, "searchable": True}
    if depends:
        options["depends_on"] = depends
    return {"x-dynamic-options": options, "x-resource-type": "printful_" + name}


class _Config(BaseModel):
    # Saved canvas metadata is compatible; dispatch constructs closed requests.
    model_config = ConfigDict(hide_input_in_errors=True)


class GetTokenScopes(_Config):
    operation: Literal["get_token_scopes"] = _op("get_token_scopes", "Access", "Get Token Scopes")


class ListStores(_Config):
    operation: Literal["list_stores"] = _op("list_stores", "Store", "List Bound Store")


class GetStore(_Config):
    operation: Literal["get_store"] = _op("get_store", "Store", "Get Bound Store")


class ListCatalogProducts(_Config):
    operation: Literal["list_catalog_products"] = _op("list_catalog_products", "Catalog", "List Catalog Products")
    category_id: int | None = Field(None, title="Category", json_schema_extra=_picker("category_id"))
    @field_validator("category_id", mode="before")
    @classmethod
    def check_category(cls, value):
        return None if value is None else _id(value)


class _Product(_Config):
    catalog_product_id: int = Field(..., title="Catalog Product", json_schema_extra=_picker("catalog_product_id"))
    _product = field_validator("catalog_product_id", mode="before")(_id)


class GetCatalogProduct(_Product):
    operation: Literal["get_catalog_product"] = _op("get_catalog_product", "Catalog", "Get Catalog Product")


class ListCatalogVariants(_Product):
    operation: Literal["list_catalog_variants"] = _op("list_catalog_variants", "Catalog", "List Product Variants")


class GetCatalogVariant(_Product):
    operation: Literal["get_catalog_variant"] = _op("get_catalog_variant", "Catalog", "Get Product Variant")
    catalog_variant_id: int = Field(..., title="Catalog Variant", json_schema_extra=_picker("catalog_variant_id", "catalog_product_id"))
    _variant = field_validator("catalog_variant_id", mode="before")(_id)


class ListCatalogCategories(_Config):
    operation: Literal["list_catalog_categories"] = _op("list_catalog_categories", "Catalog", "List Catalog Categories")


class GetCatalogCategory(_Config):
    operation: Literal["get_catalog_category"] = _op("get_catalog_category", "Catalog", "Get Catalog Category")
    category_id: int = Field(..., title="Category", json_schema_extra=_picker("category_id"))
    _category = field_validator("category_id", mode="before")(_id)


class _Page(_Config):
    offset: int = Field(0, ge=0, le=1000000, title="Offset")
    limit: int = Field(25, ge=1, le=100, title="Page Size")


class ListSyncProducts(_Page):
    operation: Literal["list_sync_products"] = _op("list_sync_products", "Ecommerce Sync", "List Ecommerce Sync Products")
    status: Literal["all", "synced", "unsynced", "ignored", "imported", "discontinued", "out_of_stock"] = "all"


class _Sync(_Config):
    sync_product_id: int = Field(..., title="Ecommerce Sync Product", json_schema_extra=_picker("sync_product_id"))
    _sync = field_validator("sync_product_id", mode="before")(_id)


class GetSyncProduct(_Sync):
    operation: Literal["get_sync_product"] = _op("get_sync_product", "Ecommerce Sync", "Get Ecommerce Sync Product")


class ListSyncVariants(_Sync):
    operation: Literal["list_sync_variants"] = _op("list_sync_variants", "Ecommerce Sync", "List Ecommerce Sync Variants")


class ListManualProducts(_Config):
    operation: Literal["list_manual_products"] = _op("list_manual_products", "Manual Store", "List Manual Store Products")
    status: Literal["all", "synced", "unsynced", "ignored", "imported", "discontinued", "out_of_stock"] = "all"


class _Manual(_Config):
    manual_product_id: int = Field(..., title="Manual Store Product", json_schema_extra=_picker("manual_product_id"))
    _manual = field_validator("manual_product_id", mode="before")(_id)


class GetManualProduct(_Manual):
    operation: Literal["get_manual_product"] = _op("get_manual_product", "Manual Store", "Get Manual Store Product")


class ListOrders(_Page):
    operation: Literal["list_orders"] = _op("list_orders", "Orders", "List Order Metadata")
    status: Literal["draft", "failed", "inreview", "pending", "canceled", "onhold", "inprocess", "partial", "fulfilled"] | None = None


class _Order(_Config):
    order_id: int = Field(..., title="Order", json_schema_extra=_picker("order_id"))
    _order = field_validator("order_id", mode="before")(_id)


class GetOrder(_Order):
    operation: Literal["get_order"] = _op("get_order", "Orders", "Get Order Metadata")


class GetOrderStatus(_Order):
    operation: Literal["get_order_status"] = _op("get_order_status", "Orders", "Get Order Status")


class DraftRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(..., repr=False)
    address1: str = Field(..., repr=False)
    city: str = Field(..., repr=False)
    country_code: str
    zip: str = Field(..., repr=False)
    state_code: str | None = None
    _recipient_text = field_validator("name", "address1", "city", "zip", mode="before")(_text)
    @field_validator("country_code", mode="before")
    @classmethod
    def country(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}", value) or value == "BR":
            raise ValueError("Use a two-letter country code; Brazil's required tax-number contract is outside this draft subset.")
        return value
    @field_validator("state_code", mode="before")
    @classmethod
    def codes(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9-]{2,6}", value):
            raise ValueError("Use the documented country/state code.")
        return value


class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    sync_product_id: int = Field(..., description="Local parent check; never sent in the order item.")
    sync_variant_id: int
    quantity: int = Field(1, ge=1, le=1000, strict=True)
    _item_ids = field_validator("sync_product_id", "sync_variant_id", mode="before")(_id)


class CreateDraftOrder(_Config):
    operation: Literal["create_draft_order"] = _op("create_draft_order", "Draft Writes", "Create Unsubmitted Draft Order")
    allow_writes: bool = Field(False, strict=True, title="Allow Draft Creation", description="Creates an actual recipient-bearing order draft. Confirmation is always false. This is not a sandbox or a fulfillment action.")
    external_id: str = Field(..., title="Unique External Reference")
    recipient: DraftRecipient = Field(..., repr=False)
    items: list[DraftItem] = Field(..., min_length=1, max_length=50)
    _external_id = field_validator("external_id", mode="before")(_text)
    @model_validator(mode="after")
    def distinct_items(self):
        if len({item.sync_variant_id for item in self.items}) != len(self.items):
            raise ValueError("Use each sync variant once per draft.")
        return self


class UpdateDraftReference(_Order):
    operation: Literal["update_draft_reference"] = _op("update_draft_reference", "Draft Writes", "Update Draft External Reference")
    allow_writes: bool = Field(False, strict=True, title="Allow Draft Metadata Update")
    external_id: str = Field(..., title="External Reference")
    _external_id = field_validator("external_id", mode="before")(_text)


class UpdateManualProductName(_Manual):
    operation: Literal["update_manual_product_name"] = _op("update_manual_product_name", "Manual Store", "Update Manual Product Name")
    allow_writes: bool = Field(False, strict=True, title="Allow Product Metadata Update", description="Changes an existing native/API store product name. No variant, file, price or fulfillment update is submitted.")
    name: str = Field(..., title="Product Name")
    _name = field_validator("name", mode="before")(_text)


PrintfulConfig = Annotated[Union[GetTokenScopes, ListStores, GetStore, ListCatalogProducts, GetCatalogProduct,
    ListCatalogVariants, GetCatalogVariant, ListCatalogCategories, GetCatalogCategory, ListSyncProducts,
    GetSyncProduct, ListSyncVariants, ListManualProducts, GetManualProduct, ListOrders, GetOrder,
    GetOrderStatus, CreateDraftOrder, UpdateDraftReference, UpdateManualProductName], Field(discriminator="operation")]


class PrintfulNodeConfig(NodeConfig[PrintfulConfig, PrintfulCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {"get_token_scopes", "list_stores", "get_store", "list_catalog_products", "get_catalog_product",
    "list_catalog_variants", "get_catalog_variant", "list_catalog_categories", "get_catalog_category",
    "list_sync_products", "get_sync_product", "list_sync_variants", "list_manual_products", "get_manual_product",
    "list_orders", "get_order", "get_order_status", "create_draft_order", "update_draft_reference", "update_manual_product_name"}
CATALOG = {op for op in OPERATIONS if "catalog" in op}
WRITES = {"create_draft_order", "update_draft_reference", "update_manual_product_name"}
REQUIREMENTS = {op: (() if op in CATALOG or op == "get_token_scopes" else ("stores_list",)) for op in OPERATIONS}
for _operation in ("list_sync_products", "get_sync_product", "list_sync_variants", "list_manual_products", "get_manual_product"):
    REQUIREMENTS[_operation] += ("sync_products/read",)
for _operation in ("list_orders", "get_order", "get_order_status"):
    REQUIREMENTS[_operation] += ("orders/read",)
for _operation in ("create_draft_order", "update_draft_reference"):
    REQUIREMENTS[_operation] += ("orders",)
REQUIREMENTS["create_draft_order"] += ("sync_products/read",)
REQUIREMENTS["update_manual_product_name"] += ("sync_products",)


class _Failure(ValueError):
    def __init__(self, message, *, status=None, credential_failure=False, uncertain=False):
        super().__init__(message)
        self.status = status
        self.credential_failure = credential_failure
        self.uncertain = uncertain


class _Session:
    def __init__(self, raw):
        self.raw = raw
        self.credential = _credential(raw)
        self.store_id = self.credential["store_id"]
        self.token = self.credential.get("private_token") or self.credential["access_token"]
        self.mutation_attempted = False

    async def request(self, method, path, *, params=None, body=None, store_context=False):
        _credential(self.credential)
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if store_context and self.credential.get("access_level") == "account":
            headers["X-PF-Store-Id"] = str(self.store_id)
        if method != "GET":
            self.mutation_attempted = True
        try:
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, BASE + path, headers=headers, params=params, json=body) as response:
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise _Failure("Printful response exceeded the local bound.", uncertain=self.mutation_attempted)
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    try:
                        data = json.loads(raw)
                    except (ValueError, UnicodeError):
                        data = None
                    if response.status_code != 200:
                        message = data.get("result") if isinstance(data, dict) else None
                        # Provider errors can contain submitted PII; only auth rejections are surfaced verbatim after redaction.
                        if method == "GET" and response.status_code in (401, 403) and isinstance(message, str):
                            message = message.replace(self.token, "[redacted]")[:500]
                        else:
                            message = f"Printful rejected the request (HTTP {response.status_code}); no automatic retry."
                        raise _Failure(message, status=response.status_code, credential_failure=response.status_code == 401,
                                       uncertain=self.mutation_attempted)
                    if (not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 200
                            or "result" not in data or self.token in raw.decode("utf-8", errors="replace")
                            or json.dumps(self.token)[1:-1] in raw.decode("utf-8", errors="replace")):
                        raise _Failure("Printful response contract could not be verified.", uncertain=self.mutation_attempted)
                    return data
        except (httpx.HTTPError, OSError):
            raise _Failure("Printful could not be reached; outcome unknown and no automatic retry.", uncertain=self.mutation_attempted) from None

    async def scopes(self):
        data = (await self.request("GET", "/oauth/scopes"))["result"]
        rows = data.get("scopes") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) > 100:
            raise _Failure("Printful token scope response could not be verified.")
        scopes = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("scope"), str) or not re.fullmatch(r"[a-z_]+(?:/read)?", row["scope"]):
                raise _Failure("Printful token scope response could not be verified.")
            scopes.add(row["scope"])
        return scopes

    async def authorize(self, operation):
        scopes = await self.scopes()
        expanded = scopes | {s + "/read" for s in scopes if not s.endswith("/read")}
        if not set(REQUIREMENTS[operation]).issubset(expanded):
            raise _Failure("The current Printful token does not grant this operation's required scopes.", status=403)
        return scopes


def _record(raw, keys, expected=None):
    if not isinstance(raw, dict):
        raise _Failure("Printful record shape could not be verified.")
    identifier = _id(raw.get("id"))
    if expected is not None and identifier != expected:
        raise _Failure("Printful returned a different resource ID.")
    out = {"id": identifier}
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if key in {"name", "title", "type", "type_name", "brand", "model", "status", "size", "color", "color_code", "availability_status"} and not isinstance(value, str):
            raise _Failure("Printful text metadata shape could not be verified.")
        if key in {"store", "product_id", "sync_product_id", "variant_id", "main_category_id"} and (type(value) is not int or value <= 0):
            raise _Failure("Printful resource parent shape could not be verified.")
        if key in {"created", "updated", "parent_id", "variant_count", "variants"} and (type(value) is not int or value < 0):
            raise _Failure("Printful count or timestamp shape could not be verified.")
        if key in {"is_discontinued", "is_ignored", "in_stock"} and type(value) is not bool:
            raise _Failure("Printful boolean metadata shape could not be verified.")
        if key == "synced" and (("variant_id" in keys and type(value) is not bool) or ("variant_id" not in keys and (type(value) is not int or value < 0))):
            raise _Failure("Printful sync count or state shape could not be verified.")
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, str) and (len(value) > 500 or any(ord(c) < 32 for c in value)):
            raise _Failure("Printful metadata shape could not be verified.")
        out[key] = value
    return out


def _rows(raw, keys, maximum=2000):
    if not isinstance(raw, list) or len(raw) > maximum:
        raise _Failure("Printful list shape or local size bound could not be verified.")
    result = [_record(row, keys) for row in raw]
    if len({r["id"] for r in result}) != len(result):
        raise _Failure("Printful returned duplicate resource IDs.")
    return result


def _page(envelope, config, keys):
    rows = _rows(envelope["result"], keys, config.limit)
    paging = envelope.get("paging")
    if (not isinstance(paging, dict) or any(type(paging.get(k)) is not int or paging[k] < 0 for k in ("total", "offset", "limit"))
            or paging["offset"] != config.offset or not 1 <= paging["limit"] <= config.limit
            or len(rows) > paging["limit"] or rows and paging["total"] < config.offset + len(rows)):
        raise _Failure("Printful paging contract could not be verified.")
    more = config.offset + len(rows) < paging["total"]
    if more and not rows:
        raise _Failure("Printful returned an empty page before the documented total.")
    return {"items": rows, "paging": {k: paging[k] for k in ("total", "offset", "limit")},
            "next_page_token": str(config.offset + len(rows)) if more else None}


STORE_KEYS = ("name", "type")
PRODUCT_KEYS = ("title", "type", "type_name", "brand", "model", "variant_count", "is_discontinued", "main_category_id")
VARIANT_KEYS = ("name", "product_id", "size", "color", "color_code", "in_stock")
SYNC_KEYS = ("name", "variants", "synced", "is_ignored")
SYNC_VARIANT_KEYS = ("name", "sync_product_id", "variant_id", "synced", "is_ignored", "size", "color", "availability_status")
ORDER_KEYS = ("store", "status", "created", "updated")
ORDER_STATUSES = {"draft", "failed", "inreview", "pending", "canceled", "onhold", "inprocess", "partial", "fulfilled"}


async def _store(session):
    row = _record((await session.request("GET", f"/stores/{session.store_id}"))["result"], STORE_KEYS, session.store_id)
    if not isinstance(row.get("name"), str) or not row["name"]:
        raise _Failure("Printful bound-store identity could not be verified.")
    return row


async def _sync_detail(session, product_id, manual=False):
    path = "/store/products" if manual else "/sync/products"
    raw = (await session.request("GET", f"{path}/{product_id}", store_context=True))["result"]
    if not isinstance(raw, dict):
        raise _Failure("Printful sync detail shape could not be verified.")
    product = _record(raw.get("sync_product"), SYNC_KEYS, product_id)
    variants = _rows(raw.get("sync_variants"), SYNC_VARIANT_KEYS)
    if any(v.get("sync_product_id") != product_id for v in variants):
        raise _Failure("Printful sync variant belongs to a different product.")
    return product, variants


async def _order(session, identifier):
    raw = (await session.request("GET", f"/orders/{identifier}", store_context=True))["result"]
    row = _record(raw, ORDER_KEYS, identifier)
    if row.get("store") != session.store_id or row.get("status") not in ORDER_STATUSES:
        raise _Failure("Printful order store or status could not be verified.")
    return row


async def _dispatch(config, raw):
    session = _Session(raw)
    try:
        op = config.operation
        if op in WRITES and config.allow_writes is not True:
            raise _Failure("Enable the explicit write opt-in before this Printful mutation.")
        scopes = await session.authorize(op)
        if op == "get_token_scopes":
            return {"success": True, "data": {"scopes": sorted(scopes)}, "proves": "reachability"}
        store = None if op in CATALOG else await _store(session)
        if op == "get_store":
            data = {"store": store}
        elif op == "list_stores":
            rows = _rows((await session.request("GET", "/stores"))["result"], STORE_KEYS)
            data = {"items": [r for r in rows if r["id"] == session.store_id]}
            if len(data["items"]) != 1:
                raise _Failure("Printful bound store was not present in the accessible store list.")
        elif op == "list_catalog_products":
            params = {"category_id": config.category_id} if config.category_id else None
            data = {"items": _rows((await session.request("GET", "/products", params=params))["result"], PRODUCT_KEYS)}
        elif op in {"get_catalog_product", "list_catalog_variants"}:
            row = (await session.request("GET", f"/products/{config.catalog_product_id}"))["result"]
            if not isinstance(row, dict):
                raise _Failure("Printful catalog detail shape could not be verified.")
            product = _record(row.get("product"), PRODUCT_KEYS, config.catalog_product_id)
            variants = _rows(row.get("variants"), VARIANT_KEYS)
            if any(v.get("product_id") != config.catalog_product_id for v in variants):
                raise _Failure("Printful catalog variant belongs to a different product.")
            data = {"product": product, "variants": variants} if op == "get_catalog_product" else {"items": variants}
        elif op == "get_catalog_variant":
            raw_variant = (await session.request("GET", f"/products/variant/{config.catalog_variant_id}"))["result"]
            if not isinstance(raw_variant, dict):
                raise _Failure("Printful variant detail shape could not be verified.")
            variant = _record(raw_variant.get("variant"), VARIANT_KEYS, config.catalog_variant_id)
            product = _record(raw_variant.get("product"), PRODUCT_KEYS, config.catalog_product_id)
            if variant.get("product_id") != product["id"]:
                raise _Failure("Printful catalog variant parent differs from the selection.")
            data = {"variant": variant}
        elif op in {"list_catalog_categories", "get_catalog_category"}:
            path = "/categories" if op == "list_catalog_categories" else f"/categories/{config.category_id}"
            result = (await session.request("GET", path))["result"]
            data = {"items": _rows(result, ("parent_id", "title"))} if op == "list_catalog_categories" else {
                "category": _record(result, ("parent_id", "title"), config.category_id)}
        elif op in {"list_sync_products", "list_manual_products"}:
            manual = op == "list_manual_products"
            if manual and store.get("type") != "native":
                raise _Failure("Manual product routes require the documented native/API store type.")
            params = {"status": config.status}
            if not manual:
                params.update(offset=config.offset, limit=config.limit)
            envelope = await session.request("GET", "/store/products" if manual else "/sync/products", params=params, store_context=True)
            if manual:
                rows = _rows(envelope["result"], SYNC_KEYS)
                paging = envelope.get("paging")
                if paging is not None and (not isinstance(paging, dict) or any(type(paging.get(k)) is not int or paging[k] < 0 for k in ("total", "offset", "limit"))):
                    raise _Failure("Printful manual product paging shape could not be verified.")
                data = {"items": rows, "paging": {k: paging[k] for k in ("total", "offset", "limit")} if paging else None,
                        "pagination_supported": False, "next_page_token": None}
            else:
                data = _page(envelope, config, SYNC_KEYS)
        elif op in {"get_sync_product", "list_sync_variants", "get_manual_product", "update_manual_product_name"}:
            manual = op in {"get_manual_product", "update_manual_product_name"}
            if manual and store.get("type") != "native":
                raise _Failure("Manual product routes require the documented native/API store type.")
            identifier = config.manual_product_id if manual else config.sync_product_id
            product, variants = await _sync_detail(session, identifier, manual)
            data = {"product": product, "variants": variants} if op != "list_sync_variants" else {"items": variants}
            if op == "update_manual_product_name":
                envelope = await session.request("PUT", f"/store/products/{identifier}", body={"sync_product": {"name": config.name}}, store_context=True)
                result = envelope["result"]
                # Update returns a bare SyncProduct; GET independently verifies persisted name.
                _record(result, SYNC_KEYS, identifier)
                product, _ = await _sync_detail(session, identifier, True)
                if product.get("name") != config.name:
                    raise _Failure("Printful persisted name did not match; do not retry automatically.", uncertain=True)
                data = {"product": product, "persisted_readback_verified": True}
        elif op == "list_orders":
            params = {"offset": config.offset, "limit": config.limit}
            if config.status:
                params["status"] = config.status
            data = _page(await session.request("GET", "/orders", params=params, store_context=True), config, ORDER_KEYS)
            if any(row.get("store") != session.store_id or row.get("status") not in ORDER_STATUSES for row in data["items"]):
                raise _Failure("Printful returned an order from a different bound store.")
        elif op in {"get_order", "get_order_status", "update_draft_reference"}:
            order = await _order(session, config.order_id)
            if op == "update_draft_reference":
                if order["status"] != "draft":
                    raise _Failure("Only an unsubmitted draft may have its reference changed.")
                response = (await session.request("PUT", f"/orders/{config.order_id}", params={"confirm": "false"},
                    body={"external_id": config.external_id}, store_context=True))["result"]
                returned = _record(response, ORDER_KEYS, config.order_id)
                if returned.get("status") != "draft" or returned.get("store") != session.store_id or response.get("external_id") != config.external_id:
                    raise _Failure("Printful draft response could not be verified; no automatic retry.", uncertain=True)
                readback = (await session.request("GET", f"/orders/{config.order_id}", store_context=True))["result"]
                order = _record(readback, ORDER_KEYS, config.order_id)
                if order.get("status") != "draft" or order.get("store") != session.store_id or readback.get("external_id") != config.external_id:
                    raise _Failure("Printful persisted draft reference could not be verified.", uncertain=True)
            data = {"order": order}
            if op == "update_draft_reference":
                data["persisted_readback_verified"] = True
        elif op == "create_draft_order":
            manual = store.get("type") == "native"
            for item in config.items:
                _, variants = await _sync_detail(session, item.sync_product_id, manual)
                matches = [v for v in variants if v["id"] == item.sync_variant_id and v.get("synced") is True and v.get("is_ignored") is not True]
                if len(matches) != 1:
                    raise _Failure("Draft item is not a synced, active variant of the selected store product.")
            body = {"external_id": config.external_id, "recipient": config.recipient.model_dump(exclude_none=True),
                    "items": [{"sync_variant_id": i.sync_variant_id, "quantity": i.quantity} for i in config.items]}
            response = (await session.request("POST", "/orders", params={"confirm": "false", "update_existing": "false"}, body=body, store_context=True))["result"]
            order = _record(response, ORDER_KEYS)
            if order.get("store") != session.store_id or order.get("status") != "draft" or response.get("external_id") != config.external_id:
                raise _Failure("Printful draft response could not be verified; no automatic retry.", uncertain=True)
            readback = await _order(session, order["id"])
            if readback["status"] != "draft":
                raise _Failure("Printful persisted order is no longer a draft.", uncertain=True)
            data = {"order": readback, "persisted_readback_verified": True}
        else:
            raise _Failure("Unsupported Printful operation.")
        return {"success": True, "data": data, "store_id": session.store_id, "api_version": "v1"}
    except (_Failure, ValueError, TypeError, KeyError) as exc:
        failure = exc if isinstance(exc, _Failure) else _Failure("Printful resource shape or current authority could not be verified.")
        return {"success": False, "error": str(failure), "status_code": failure.status,
                "provider_credential_failure": failure.credential_failure,
                "mutation_outcome_unknown": session.mutation_attempted or failure.uncertain, "retry_attempted": False}


class PrintfulNode(WorkflowNode):
    integration_type = "automation-printful"
    credential_provider_labels = {"printful": "Printful"}
    workflow_credential_refresh = True  # Reload saved manual tokens; never mint or refresh.
    connection_evidence = ConnectionEvidence(operation="get_store", noun="stores", identity_operation="get_store", proves="account")
    scope_registry = ScopeRegistry(provider="printful", requirements={op: ScopeRequirement(scopes) for op, scopes in REQUIREMENTS.items()})

    @classmethod
    def get_config_model(cls):
        return PrintfulNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials") is not None:
            _credential(config_data["credentials"])
        return super().parse_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_id:
            if not user_id:
                raise ValueError("Stored Printful credential requires an authorized caller.")
            from utils.database_pool import get_native_pool
            from wss.handlers.workflow_handler import get_user_org_context
            from utils.credentials import resolve_accessible_credential_types, resolve_credential_with_owner_fallback

            pool = pool if pool is not None else get_native_pool()
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
            types = await resolve_accessible_credential_types([credential_id], user_id, pool, organization_id)
            current_type = types.get(credential_id)
            if current_type not in FAMILIES:
                raise ValueError("Current Printful credential is unavailable or has a different family.")
            credential_data = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id)
            if not credential_data or credential_data.get("credential_type") != current_type:
                raise ValueError("Printful credential unavailable, revoked or access denied.")
        return _credential(credential_data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        context = context or {}
        _credential(credential_data)
        fields = {
            "catalog_product_id": ("list_catalog_products", {}),
            "catalog_variant_id": ("list_catalog_variants", {"catalog_product_id": _id(context.get("catalog_product_id"))} if context.get("catalog_product_id") else {}),
            "category_id": ("list_catalog_categories", {}), "sync_product_id": ("list_sync_products", {}),
            "manual_product_id": ("list_manual_products", {}), "order_id": ("list_orders", {}),
        }
        if field_name not in fields:
            raise ValueError("Unsupported Printful picker.")
        op, args = fields[field_name]
        if field_name == "catalog_variant_id" and not args:
            raise ValueError("Select the parent catalog product before loading variants.")
        if page_token is not None:
            if op not in {"list_sync_products", "list_orders"}:
                raise ValueError("This documented Printful list has no offset parameter.")
            if not isinstance(page_token, str) or not re.fullmatch(r"[0-9]{1,7}", page_token):
                raise ValueError("Invalid Printful offset token.")
            args["offset"] = int(page_token)
        config = TypeAdapter(PrintfulConfig).validate_python({"operation": op, **args})
        result = await _dispatch(config, credential_data)
        if not result["success"]:
            raise _Failure(result["error"], status=result.get("status_code"), credential_failure=result.get("provider_credential_failure", False))
        rows = result["data"]["items"]
        options = [{"value": str(row["id"]), "label": str(row.get("name") or row.get("title") or ("Order " + str(row["id"])))} for row in rows]
        if search:
            needle = _text(search, maximum=100).casefold()
            options = [row for row in options if needle in row["label"].casefold()]
        return {"options": options, "next_page_token": result["data"].get("next_page_token")}

    async def execute(self, input_data):
        raw = (self.node_data or {}).get("credentials")
        if "credentials" not in (self.node_data or {}) and self.config.credentials is not None:
            raw = self.config.credentials.model_dump()
        raw = await self.freshen_credential(raw, pool=(self.node_data or {}).get("_approval_pool"),
            user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"))
        config = self.config.config
        return await _dispatch(config, raw)
