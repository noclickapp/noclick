"""Native API2Cart connected-store metadata and disposable catalog management.

Current official v1.1 OpenAPI: x-api-key/x-store-key headers, fixed server.
No connection installation, customer/order mutation or arbitrary API wrapper.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from repositories.credential_approvals import CredentialApprovalRepo

TYPE = "automation-api2cart"
FAMILY = "api2cart_api_key"
BASE = "https://api.api2cart.com/v1.1"
MAX_BYTES = 2 * 1024 * 1024
CURRENT_ORGANIZATION = object()
_private_request = ContextVar("api2cart_private_http", default=False)

class _HTTPFilter(logging.Filter):
    def filter(self, record):
        if _private_request.get():
            record.msg, record.args = "API2Cart HTTP exchange; details omitted", ()
            record.exc_info = record.exc_text = None
        return True


@contextmanager
def _private_http():
    filters = [(logging.getLogger(name), _HTTPFilter()) for name in (
        "httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2")]
    token = _private_request.set(True)
    try:
        for logger, projection in filters:
            logger.addFilter(projection)
        yield
    finally:
        for logger, projection in filters:
            logger.removeFilter(projection)
        _private_request.reset(token)



class _Current:
    def __init__(self, data, *, pool=None, user_id=None, credential_id=None, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.data = _credential(data)
        self.pool, self.user_id, self.credential_id = pool, user_id, credential_id
        self.organization_id, self.workflow_id = organization_id, workflow_id
        if credential_id and not user_id:
            raise ValueError("Saved API2Cart credentials require an authenticated actor")

    async def check(self):
        if self.credential_id:
            from utils.credentials import resolve_credential_with_owner_fallback
            from utils.database_pool import get_native_pool
            from repositories.organization import OrgRepo
            self.pool = self.pool if self.pool is not None else get_native_pool()
            org = self.organization_id
            if org is CURRENT_ORGANIZATION:
                async with self.pool.acquire() as conn:
                    org = await OrgRepo(self.pool).get_primary_org_id(conn, self.user_id)
            loaded = await resolve_credential_with_owner_fallback(
                self.credential_id, self.user_id, self.pool,
                org_id=org, workflow_id=self.workflow_id,
            )
            if loaded is None:
                raise ValueError("Saved API2Cart credential is unavailable")
            if _credential(loaded) != self.data:
                raise ValueError("Saved API2Cart authority changed; retry with the current credential")
        return dict(self.data)


def _text(value, maximum=200, *, allow_empty=False, multiline=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > maximum or any((ord(c) < 32 and not (multiline and c in "\n\r\t")) or ord(c) == 127 for c in value):
        raise ValueError("API2Cart identifier or metadata text is invalid")
    return value


class API2CartAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="API2Cart API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api2cart.com/docs/how-to-start-your-integration-with-api2cart/",
        "x-credential-instructions": "Use an existing API2Cart account API key and already connected store key. Enter the exact platform cart_id and selected stores_info store_id. NoClick does not install a bridge or connect a third-party store.",
        "x-credential-notice": "Manual server API key, not managed OAuth. Current official v1.1 uses x-api-key/x-store-key headers. Platform methods/parameters differ; no API plan entitlement or personal principal is inferred.",
        "x-sensitive-auth-diagnostics": True,
    })
    credential_type: Literal["api2cart_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API2Cart API key", json_schema_extra={"ui:widget": "password"})
    store_key: str = Field(..., title="Connected store key", json_schema_extra={"ui:widget": "password"})
    platform_id: str = Field(..., title="Platform cart ID", description="Exact cart_id from the existing API2Cart connection, for example Shopify")
    store_id: str = Field(..., title="Store ID", description="Exact selected stores_info store_id from cart.info; fixed parent scope")

    @field_validator("api_key", "store_key")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("API2Cart key is invalid")
        return value

    @field_validator("platform_id", "store_id")
    @classmethod
    def identity(cls, value): return _text(value)


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILY) != FAMILY:
        raise ValueError("This node requires an API2Cart API key")
    try: return API2CartAPIKeyCredential.model_validate(data).model_dump()
    except Exception: raise ValueError("API2Cart credential is invalid") from None


def _op(name, title, group):
    return Field(name, title=title, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": group, "x-is-trigger": False})


def _picker(name, title):
    return Field(..., title=title, json_schema_extra={"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, "placeholder": "Select " + title.lower()}})


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Config):
    page_size: int = Field(25, ge=1, le=100, title="Page size", description="NoClick bounds each page to100; provider documents maximum250")
    page_token: Optional[str] = Field(None, max_length=32768, title="Continuation")


class _Disposable(_Config):
    confirm_disposable: bool = Field(False, title="Confirm disposable catalog record", description="Required. Use an owned disposable record; no atomic precondition or notification-free guarantee is inferred")


class API2CartTestConnectionConfig(_Config):
    operation: Literal["test_connection"] = _op("test_connection", "Check Connected Store Access", "Connection")


class API2CartGetStoreConfig(_Config):
    operation: Literal["get_store"] = _op("get_store", "Get Selected Store Metadata", "Store")


class API2CartListStoresConfig(_Config):
    operation: Literal["list_stores"] = _op("list_stores", "List Connected Cart Stores", "Store")


class API2CartListSupportedMethodsConfig(_Config):
    operation: Literal["list_supported_methods"] = _op("list_supported_methods", "List Supported Native Methods", "Store")


class API2CartListProductsConfig(_Page):
    operation: Literal["list_products"] = _op("list_products", "List Product Metadata", "Products")
    category_id: Optional[str] = Field(None, max_length=200, title="Category filter", json_schema_extra={"x-dynamic-options": {"field_name": "category_id", "searchable": True, "allow_custom": True}})


class API2CartGetProductConfig(_Config):
    operation: Literal["get_product"] = _op("get_product", "Get Product Metadata", "Products")
    product_id: str = _picker("product_id", "Product")


class API2CartCreateProductConfig(_Disposable):
    operation: Literal["create_product"] = _op("create_product", "Create Disposable Product", "Products")
    name: str = Field(..., min_length=1, max_length=250, title="Name")
    model: str = Field(..., min_length=1, max_length=200, title="Model")
    description: str = Field(..., min_length=1, max_length=4096, title="Description")
    price: float = Field(..., ge=0, le=1000000000, allow_inf_nan=False, title="Required product price", description="Documented create field in the store's currency; no price default is inferred")


class API2CartUpdateProductConfig(_Disposable):
    operation: Literal["update_product"] = _op("update_product", "Update Disposable Product Profile", "Products")
    product_id: str = _picker("product_id", "Product")
    name: Optional[str] = Field(None, min_length=1, max_length=250, title="Name")
    description: Optional[str] = Field(None, min_length=1, max_length=4096, title="Description")


class API2CartDeleteProductConfig(_Disposable):
    operation: Literal["delete_product"] = _op("delete_product", "Delete Disposable Product", "Products")
    product_id: str = _picker("product_id", "Product")


class API2CartListCategoriesConfig(_Page):
    operation: Literal["list_categories"] = _op("list_categories", "List Category Metadata", "Categories")


class API2CartGetCategoryConfig(_Config):
    operation: Literal["get_category"] = _op("get_category", "Get Category Metadata", "Categories")
    category_id: str = _picker("category_id", "Category")


class API2CartCreateCategoryConfig(_Disposable):
    operation: Literal["create_category"] = _op("create_category", "Create Disposable Category", "Categories")
    name: str = Field(..., min_length=1, max_length=250, title="Name")
    description: Optional[str] = Field(None, min_length=1, max_length=4096, title="Description")
    parent_id: Optional[str] = Field(None, max_length=200, title="Parent category", json_schema_extra={"x-dynamic-options": {"field_name": "parent_id", "searchable": True, "allow_custom": True}})


class API2CartUpdateCategoryConfig(_Disposable):
    operation: Literal["update_category"] = _op("update_category", "Update Disposable Category Profile", "Categories")
    category_id: str = _picker("category_id", "Category")
    name: Optional[str] = Field(None, min_length=1, max_length=250, title="Name")
    description: Optional[str] = Field(None, min_length=1, max_length=4096, title="Description")


class API2CartDeleteCategoryConfig(_Disposable):
    operation: Literal["delete_category"] = _op("delete_category", "Delete Disposable Category", "Categories")
    category_id: str = _picker("category_id", "Category")


class API2CartListCustomersConfig(_Page):
    operation: Literal["list_customers"] = _op("list_customers", "List Customer Metadata", "Customers")


class API2CartGetCustomerConfig(_Config):
    operation: Literal["get_customer"] = _op("get_customer", "Get Customer Metadata", "Customers")
    customer_id: str = _picker("customer_id", "Customer")


class API2CartListOrdersConfig(_Page):
    operation: Literal["list_orders"] = _op("list_orders", "List Order Status Metadata", "Orders")


class API2CartGetOrderConfig(_Config):
    operation: Literal["get_order"] = _op("get_order", "Get Order Status Metadata", "Orders")
    order_id: str = _picker("order_id", "Order")


API2CartConfig = Annotated[Union[API2CartTestConnectionConfig, API2CartGetStoreConfig, API2CartListStoresConfig,
    API2CartListSupportedMethodsConfig, API2CartListProductsConfig, API2CartGetProductConfig, API2CartCreateProductConfig,
    API2CartUpdateProductConfig, API2CartDeleteProductConfig, API2CartListCategoriesConfig, API2CartGetCategoryConfig,
    API2CartCreateCategoryConfig, API2CartUpdateCategoryConfig, API2CartDeleteCategoryConfig, API2CartListCustomersConfig,
    API2CartGetCustomerConfig, API2CartListOrdersConfig, API2CartGetOrderConfig], Field(discriminator="operation")]


class API2CartNodeConfig(NodeConfig[API2CartConfig, API2CartAPIKeyCredential]):
    pass


OPERATIONS = ("test_connection", "get_store", "list_stores", "list_supported_methods", "list_products", "get_product", "create_product", "update_product", "delete_product",
    "list_categories", "get_category", "create_category", "update_category", "delete_category", "list_customers", "get_customer", "list_orders", "get_order")
SCOPES = ScopeRegistry("api2cart", {name: ScopeRequirement(credential_types=(FAMILY,), note="Existing account/store API key access and platform method support; no OAuth scope or caller permission claim inferred.") for name in OPERATIONS})
KINDS = {"products": ("product", "products_count"), "categories": ("category", "categories_count"), "customers": ("customer", "customers_count"), "orders": ("order", "orders_count")}
FIELDS = {"products": "id,type,u_model,u_sku,name,stores_ids,avail_sale,avail_view", "categories": "id,parent_id,name,stores_ids,avail", "customers": "id,status,is_guest,stores_ids", "orders": "id,order_id,store_id,status{id,name}"}
ROUTES = {"account.cart.list": "GET", "cart.info": "GET", "cart.methods": "GET", **{kind + suffix: "GET" for kind in ("product", "category", "customer", "order") for suffix in (".list", ".info")},
    "product.add": "POST", "product.update": "PUT", "product.delete": "DELETE", "category.add": "POST", "category.update": "PUT", "category.delete": "DELETE"}


class API2CartError(ValueError):
    def __init__(self, *, code=None, status=None):
        self.code, self.status = code, status
        category = {2: "API key rejected", 4: "Store access denied", 5: "API access denied", 6: "API key disabled", 7: "Store request limit", 10: "Account request limit", 100: "Connected store access failed", 101: "Connected store not found", 109: "Parameters unsupported or invalid", 110: "Connected platform rate limit", 112: "Item not found", 114: "Required parameter missing"}.get(code, "Provider request failed")
        super().__init__(f"API2Cart: {category}; return_code={code}, HTTP={status}; provider details omitted")


def _project(kind, raw, store_id, expected=None):
    if not isinstance(raw, dict): raise ValueError("API2Cart resource metadata is invalid")
    identity = _text(raw.get("id"))
    if expected is not None and identity != expected: raise ValueError("API2Cart returned a different resource")
    if raw.get("store_id") is not None and raw["store_id"] != store_id: raise ValueError("API2Cart resource belongs to a different store")
    stores = raw.get("stores_ids")
    if stores is not None:
        if not isinstance(stores, list) or len(stores) > 1000: raise ValueError("API2Cart store membership is invalid")
        for item in stores: _text(item)
        if stores and store_id not in stores: raise ValueError("API2Cart resource belongs to a different store")
    if raw.get("store_id") != store_id and (not stores or store_id not in stores):
        raise ValueError("API2Cart platform did not expose selected-store membership metadata")
    fields = {"products": ("type", "u_model", "u_sku", "name", "avail_sale", "avail_view"), "categories": ("parent_id", "name", "avail"),
        "customers": ("status", "is_guest"), "orders": ("order_id", "store_id")}[kind]
    result = {"id": identity}
    for field in fields:
        value = raw.get(field)
        if value is None: continue
        if field in {"avail", "avail_sale", "avail_view", "is_guest"}:
            if not isinstance(value, bool): raise ValueError("API2Cart boolean metadata is invalid")
        else: _text(value, 1000, allow_empty=field in {"u_model", "u_sku", "type", "status", "parent_id"})
        result[field] = value
    if kind == "orders" and raw.get("status") is not None:
        status = raw["status"]
        if not isinstance(status, dict): raise ValueError("API2Cart order status metadata is invalid")
        result["status"] = {key: _text(status[key], 1000) for key in ("id", "name") if status.get(key) is not None}
    return result


def _cursor(data, config, next_value=None):
    binding = hashlib.sha256(json.dumps([FAMILY, BASE, data["platform_id"], data["store_id"], {k: v for k, v in config.items() if k != "page_token"}], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    key = (data["api_key"] + ":" + data["store_key"]).encode()
    if next_value is not None:
        _text(next_value, 8192)
        raw = json.dumps({"v": 1, "b": binding, "p": next_value}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + hmac.new(key, raw, hashlib.sha256).hexdigest()
    if not config.get("page_token"): return None
    try:
        body, signature = config["page_token"].split(".")
        raw = base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True); value = json.loads(raw)
        if not hmac.compare_digest(signature, hmac.new(key, raw, hashlib.sha256).hexdigest()) or value.get("v") != 1 or value.get("b") != binding: raise ValueError()
        return _text(value["p"], 8192)
    except Exception: raise ValueError("API2Cart continuation does not match this key, connected store, platform, operation, filters and page size") from None


class _API:
    def __init__(self, current, client): self.current, self.client = current, client

    async def request(self, name, *, params=None, body=None):
        if name not in ROUTES: raise ValueError("Unsupported native API2Cart route")
        data = await self.current.check()
        headers = {"x-api-key": data["api_key"], "Accept": "application/json"}
        if name != "account.cart.list": headers["x-store-key"] = data["store_key"]
        try:
            with _private_http():
                async with self.client.stream(ROUTES[name], BASE + "/" + name + ".json", headers=headers, params=params, json=body) as response:
                    if response.status_code != 200: raise API2CartError(status=response.status_code)
                    if "json" not in response.headers.get("content-type", "").lower(): raise ValueError("API2Cart returned an unsupported response format")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES: raise ValueError("API2Cart response exceeds the metadata limit")
                        chunks.append(chunk)
                    try: raw = json.loads(b"".join(chunks))
                    except Exception: raise ValueError("API2Cart returned malformed JSON") from None
        except (httpx.HTTPError, OSError): raise ValueError("API2Cart transport failed; request details omitted") from None
        await self.current.check()
        if not isinstance(raw, dict) or type(raw.get("return_code")) is not int: raise ValueError("API2Cart response envelope is invalid")
        if raw["return_code"] != 0: raise API2CartError(code=raw["return_code"], status=200)
        if not isinstance(raw.get("result"), dict): raise ValueError("API2Cart result envelope is invalid")
        return raw

    async def scope(self, method=None):
        data = await self.current.check()
        connected = (await self.request("account.cart.list"))["result"]
        carts, count = connected.get("carts"), connected.get("carts_count")
        if not isinstance(carts, list) or len(carts) > 1000 or type(count) is not int or count != len(carts): raise ValueError("API2Cart connected-store association envelope is invalid")
        matches = [row for row in carts if isinstance(row, dict) and row.get("store_key") == data["store_key"]]
        if len(matches) != 1 or matches[0].get("cart_id") != data["platform_id"]: raise ValueError("API2Cart key does not verify the selected connected store and platform")
        row = matches[0]
        connection = {"id": _text(row.get("id")), "platform_id": _text(row["cart_id"])}
        if row.get("custom_label"): connection["custom_label"] = _text(row["custom_label"], 1000)
        info = (await self.request("cart.info", params={"response_fields": "{return_code,result{name,version,stores_info{store_id,name,language,timezone,active,root_category_id}}}"}))["result"]
        stores = info.get("stores_info")
        if not isinstance(stores, list) or len(stores) > 1000: raise ValueError("API2Cart stores_info metadata is invalid")
        projected = []
        for store in stores:
            if not isinstance(store, dict): raise ValueError("API2Cart store metadata is invalid")
            item = {"store_id": _text(store.get("store_id"))}
            for key in ("name", "language", "timezone", "root_category_id"):
                if store.get(key) is not None: item[key] = _text(store[key], 1000, allow_empty=True)
            if store.get("active") is not None:
                if not isinstance(store["active"], bool): raise ValueError("API2Cart store active metadata is invalid")
                item["active"] = store["active"]
            projected.append(item)
        selected = [store for store in projected if store["store_id"] == data["store_id"]]
        if len(selected) != 1: raise ValueError("API2Cart selected store is unavailable within this connected cart")
        methods = (await self.request("cart.methods"))["result"].get("method")
        if not isinstance(methods, list) or len(methods) > 1000 or any(not isinstance(item, str) or re.fullmatch(r"[a-z0-9_.]{1,100}", item) is None for item in methods):
            raise ValueError("API2Cart supported methods metadata is invalid")
        if method is not None and method not in methods: raise ValueError("API2Cart selected platform does not support this native method")
        return {"connection": connection, "store": selected[0], "stores": projected,
            "native_methods": sorted(set(methods) & set(ROUTES)), "parameter_support_verified": False}

    async def page(self, kind, config):
        await self.scope(KINDS[kind][0] + ".list")
        data = await self.current.check(); cursor = _cursor(data, config)
        singular, total_key = KINDS[kind]
        # Official current contract: cursor cannot coexist with filters/count.
        # The initial request carries its store/fields; server cursor retains it.
        params = {"page_cursor": cursor} if cursor is not None else {"count": config["page_size"], "store_id": data["store_id"],
            "response_fields": "{return_code,pagination{next,previous},result{" + total_key + "," + singular + "{" + FIELDS[kind] + "}}}"}
        if cursor is None and config.get("category_id") is not None:
            await self.info("categories", _text(config["category_id"]))
            params["category_id"] = config["category_id"]
        raw = await self.request(singular + ".list", params=params)
        rows, total = raw["result"].get(singular), raw["result"].get(total_key)
        if not isinstance(rows, list) or len(rows) > config["page_size"] or (total is not None and (type(total) is not int or total < len(rows))):
            raise ValueError("API2Cart list metadata is invalid")
        projected = [_project(kind, row, data["store_id"]) for row in rows]
        if len({row["id"] for row in projected}) != len(rows): raise ValueError("API2Cart page contains duplicate identifiers")
        pagination = raw.get("pagination")
        if pagination is not None and not isinstance(pagination, dict): raise ValueError("API2Cart pagination envelope is invalid")
        next_value = pagination.get("next") if pagination is not None else None
        if next_value is not None:
            _text(next_value, 8192)
            if not rows: raise ValueError("API2Cart empty page cannot support continuation")
        return {"results": projected, "count": total, "next_page_token": _cursor(data, config, next_value) if next_value else None}

    async def info(self, kind, identity, *, check_membership=True, readback_fields=False):
        singular = KINDS[kind][0]; identity = _text(identity)
        await self.scope(singular + ".info");data = await self.current.check()
        if check_membership:
            config = {"operation": "list_" + kind, "page_size": 100, "page_token": None}
            for _ in range(10):
                page = await self.page(kind, config)
                if any(row["id"] == identity for row in page["results"]): break
                if page["next_page_token"] is None: raise ValueError("API2Cart resource is unavailable under this store")
                config["page_token"] = page["next_page_token"]
            else: raise ValueError("API2Cart membership lookup exceeds the1,000-record bound")
        fields = FIELDS[kind] + (",description,price" if readback_fields and kind == "products" else ",description" if readback_fields and kind == "categories" else "")
        raw = (await self.request(singular + ".info", params={"id": identity, "store_id": data["store_id"], "response_fields": "{return_code,result{" + fields + "}}"}))["result"]
        return _project(kind, raw, data["store_id"], identity), raw

    async def write(self, kind, config):
        operation = config["operation"]
        if config.get("confirm_disposable") is not True: raise ValueError("API2Cart catalog write requires disposable confirmation")
        singular = KINDS[kind][0]; suffix = {"create": ".add", "update": ".update", "delete": ".delete"}[operation.split("_", 1)[0]]
        await self.scope(singular + suffix);data = await self.current.check()
        create = operation.startswith("create_"); delete = operation.startswith("delete_")
        identity = None if create else _text(config[singular + "_id"])
        if not create:
            prior, _ = await self.info(kind, identity)
            if (kind == "products" and (prior.get("avail_sale") is not False or prior.get("avail_view") is not False)) or (kind == "categories" and prior.get("avail") is not False):
                raise ValueError("API2Cart disposable record must have documented hidden/not-for-sale metadata before mutation")
        if delete:
            result = (await self.request(singular + suffix, params={"id": identity, "store_id": data["store_id"]}))["result"]
            value = result.get("delete_items")
            if not ((kind == "products" and type(value) is int and value == 1) or (kind == "categories" and value is True)):
                raise ValueError("API2Cart deletion did not confirm the documented single-item result")
            # Scope/permission failure is never evidence that the target vanished.
            # Only112 from this exact separate target-info response proves absence.
            await self.scope(singular + ".info")
            try:
                await self.request(singular + ".info", params={"id": identity, "store_id": data["store_id"], "response_fields": "{return_code,result{id}}"})
            except API2CartError as error:
                if error.code != 112: raise
            else: raise ValueError("API2Cart separate target readback did not confirm absence; do not retry automatically")
            return {"id": identity, "deleted": True, "readback": "separate_info_return_code112"}
        body = {"store_id": data["store_id"]}
        if identity is not None: body["id"] = identity
        for field in ("name", "description", "model"):
            if config.get(field) is not None: body[field] = _text(config[field], 4096 if field == "description" else 250, multiline=field == "description")
        if not create and len(body) == 2: raise ValueError("API2Cart profile update has no changed fields")
        if create and kind == "products": body.update(price=config["price"], available_for_sale=False, available_for_view=False)
        if create and kind == "categories":
            body["avail"] = "false"
            if config.get("parent_id") is not None:
                await self.info("categories", _text(config["parent_id"]));body["parent_id"] = config["parent_id"]
        raw = (await self.request(singular + suffix, body=body if kind == "products" else None, params=body if kind == "categories" else None))["result"]
        if create: identity = _text(raw.get(singular + "_id"))
        elif type(raw.get("updated_items")) is not int or raw["updated_items"] < 1: raise ValueError("API2Cart update did not confirm changed items")
        projected, readback = await self.info(kind, identity, readback_fields=True)
        expected = {key: value for key, value in body.items() if key in {"name", "description", "price", "parent_id"}}
        if "model" in body: expected["u_model"] = body["model"]
        if any(readback.get(key) != value for key, value in expected.items()): raise ValueError("API2Cart separate catalog readback differs; do not retry automatically")
        if create and ((kind == "products" and (projected.get("avail_sale") is not False or projected.get("avail_view") is not False)) or (kind == "categories" and projected.get("avail") is not False)):
            raise ValueError("API2Cart platform did not confirm hidden creation; write may already have succeeded, inspect without retry")
        return {"item": projected, "readback": "separate_info", "parameter_support_verified": False, "notification_free_verified": False}


class API2CartNode(WorkflowNode):
    integration_type = "automation-api2cart"
    workflow_credential_refresh = True
    scope_registry = SCOPES
    connection_evidence = ConnectionEvidence(noun="connected-store metadata", operation="test_connection", proves="reachability")

    @classmethod
    def get_config_model(cls): return API2CartNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"): _credential(config_data["credentials"])
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials"): _credential(config_data["credentials"])
        except ValueError: return {"valid": False, "errors": ["This node requires an API2Cart API key"], "satisfied_set": None}
        return super().validate_config(config_data)

    async def _prepare(self):
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials else {})
        self._current = _Current(raw, pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        await self._current.check();self._admitted = False

    async def run(self, inputs):
        await self._prepare()
        from utils.credential_approval import admit_node
        pending = await admit_node(self, inputs)
        if pending is not None: return pending
        self._admitted = True
        try: return await self.execute(inputs)
        finally: self._admitted = False

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging resolves access and lookup admission before this hook. API keys
        # do not rotate; preserve the resolved workflow/organization context.
        current = _Current(credential_data)
        if credential_id:
            from utils.database_pool import get_native_pool
            pool = pool if pool is not None else get_native_pool()
            if await CredentialApprovalRepo(pool).has_restrictions(credential_id):
                raise ValueError("Restricted API2Cart credentials require a mediated workflow; graph-free picker unavailable")
        return {**current.data, "_api2cart_current": current}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        from nodes.core.connection_evidence import collect_evidence
        evidence = await collect_evidence(node_type=TYPE, user_id="", credential_data=_credential(credential_data))
        return {"valid": evidence.reachable, "evidence": asdict(evidence)}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        kind = {"product_id": "products", "category_id": "categories", "parent_id": "categories", "customer_id": "customers", "order_id": "orders"}.get(field_name)
        if kind is None: return {"options": [], "next_page_token": None}
        current = credential_data.get("_api2cart_current") if isinstance(credential_data, dict) else None
        if not isinstance(current, _Current): raise ValueError("API2Cart picker requires an authenticated current-row loader")
        _credential(credential_data)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, trust_env=False) as client:
            page = await _API(current, client).page(kind, {"operation": "list_" + kind, "page_size": 100, "page_token": page_token})
        options = []
        for row in page["results"]:
            label = row.get("name") or row.get("order_id") or row["id"]
            if not search or search.casefold() in label.casefold(): options.append({"value": row["id"], "label": label})
        return {"options": options, "next_page_token": page["next_page_token"]}

    async def execute(self, inputs):
        if self.node_data.get("credential_id") and getattr(self, "_admitted", False) is not True: raise ValueError("Saved API2Cart operations require current credential admission")
        if not hasattr(self, "_current"): await self._prepare()
        config = self.config.config.model_dump();operation = config["operation"]
        data = await self._current.check()
        if operation.startswith("list_") and operation not in {"list_stores", "list_supported_methods"}: _cursor(data, config)
        if operation.startswith(("create_", "update_", "delete_")) and config.get("confirm_disposable") is not True: raise ValueError("API2Cart catalog write requires disposable confirmation")
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, trust_env=False) as client:
            api = _API(self._current, client)
            if operation in {"test_connection", "get_store", "list_stores", "list_supported_methods"}:
                scope = await api.scope()
                if operation == "test_connection": payload = {"reachable": True, "identity_verified": False, "connection": scope["connection"], "store": scope["store"]}
                elif operation == "get_store": payload = {"connection": scope["connection"], "store": scope["store"]}
                elif operation == "list_stores": payload = {"stores": scope["stores"]}
                else: payload = {"methods": scope["native_methods"], "parameter_support_verified": False}
            elif operation.startswith("list_"): payload = await api.page(operation[5:], config)
            elif operation.startswith("get_"):
                kind = {"product": "products", "category": "categories", "customer": "customers", "order": "orders"}[operation[4:]]
                item, _ = await api.info(kind, config[operation[4:] + "_id"]);payload = {"item": item}
            else:
                kind = "products" if operation.endswith("product") else "categories"
                payload = await api.write(kind, config)
        return {"status": "success", "action": operation, "data": payload}
