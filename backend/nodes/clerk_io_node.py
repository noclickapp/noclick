"""Closed Clerk.io v2 catalog and recommendation transport.

Store keys belong in documented query parameters or JSON bodies. Local HTTP
log filters and a request-scoped instrumentation boundary protect those keys.
"""
from contextvars import ContextVar
from contextlib import contextmanager
import json
import logging
import math
import re
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from utils.ssrf import guarded_async_client

ORIGIN = "https://api.clerk.io/v2"
MAX_BODY = 2 * 1024 * 1024
ATTRIBUTES = ("id", "name", "price", "list_price", "sku", "brand", "categories",
              "stock", "on_sale", "index", "created_at")
PUBLIC_READS = {
    "check_public_connection": "/recommendations/popular",
    "get_products": "/product/attributes", "search_products": "/search/search",
    "search_categories": "/search/categories",
    "popular_products": "/recommendations/popular",
    "trending_products": "/recommendations/trending",
    "new_products": "/recommendations/new",
    "complementary_products": "/recommendations/complementary",
    "substituting_products": "/recommendations/substituting",
    "category_popular_products": "/recommendations/category/popular",
}
WRITES = {
    "upsert_products": ("POST", "/products", "products"),
    "patch_products": ("PATCH", "/products", "products"),
    "remove_products": ("DELETE", "/products", "products"),
    "upsert_categories": ("POST", "/categories", "categories"),
    "patch_categories": ("PATCH", "/categories", "categories"),
    "upsert_customers": ("POST", "/customers", "customers"),
    "patch_customers": ("PATCH", "/customers", "customers"),
    "remove_customers": ("DELETE", "/customers", "customers"),
    "upsert_orders": ("POST", "/orders", "orders"),
    "patch_orders": ("PATCH", "/orders", "orders"),
    "remove_orders": ("DELETE", "/orders", "orders"),
}
_SECRETS = ContextVar("clerk_io_request_secrets", default=())
_URL = re.compile(r'https?://[^\s\'"<>]+')


class ClerkIOError(ValueError):
    """A fixed, credential-safe provider refusal or unknown response."""


def _log_url(match):
    try:
        url = urlsplit(match.group())
        return urlunsplit((url.scheme, url.netloc, url.path, "[REDACTED]" if url.query else "", ""))
    except ValueError:
        return "[REDACTED URL]"


class _RequestLogFilter(logging.Filter):
    def filter(self, record):
        secrets = _SECRETS.get()
        if not secrets:
            return True
        # Only these HTTP transport loggers are filtered, and only in this
        # request's async context. Unrelated diagnostics keep their contents.
        message = _URL.sub(_log_url, record.getMessage())
        for secret in secrets:
            for variant in (secret, quote(secret, safe=""), quote_plus(secret),
                            json.dumps(secret)[1:-1], repr(secret)[1:-1]):
                message = message.replace(variant, "[REDACTED]")
        record.msg, record.args = message, ()
        if record.exc_info:
            # A transport traceback can contain the complete keyed URL.
            message += " [transport exception: " + record.exc_info[0].__name__ + "]"
            record.msg, record.exc_info, record.exc_text = message, None, None
        record.stack_info = None
        return True


_FILTER = _RequestLogFilter()


@contextmanager
def _private_request_logs(keys):
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2",
             "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in logging.Logger.manager.loggerDict if name.startswith("httpcore."))
    for name in names:
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
    token = _SECRETS.set(tuple(keys))
    try:
        # The server also uses OutboundTraceProvider. This narrow boundary
        # protects non-server callers with a different HTTPX instrumentor.
        with suppress_http_instrumentation():
            yield
    finally:
        _SECRETS.reset(token)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClerkIOError("Clerk.io returned ambiguous JSON.")
        result[key] = value
    return result


def _invalid_number(_value):
    raise ClerkIOError("Clerk.io returned invalid JSON numbers.")


def _key_echo(value, secrets):
    if isinstance(value, str):
        return any(secret in value for secret in secrets)
    if isinstance(value, dict):
        return any(_key_echo(key, secrets) or _key_echo(item, secrets) for key, item in value.items())
    if isinstance(value, list):
        return any(_key_echo(item, secrets) for item in value)
    return False


async def request(credential, operation, values):
    """Send one bounded request to the fixed provider API."""
    if operation == "check_connection":
        method, path = "GET", "/audiences/list"
        fields = {"key": credential["public_key"], "private_key": credential["private_key"]}
    elif operation in PUBLIC_READS:
        method, path = "GET", PUBLIC_READS[operation]
        fields = {"key": credential["public_key"], **values}
    elif operation in WRITES:
        method, path, resource = WRITES[operation]
        fields = {"key": credential["public_key"], "private_key": credential["private_key"],
                  resource: values[resource]}
    else:
        raise ClerkIOError("Unsupported Clerk.io operation.")
    secrets = (credential["public_key"], credential["private_key"])
    try:
        with _private_request_logs(secrets):
            async with guarded_async_client(timeout=30.0,
                                            follow_redirects=False, trust_env=False) as client:
                # GET/DELETE arrays are encoded once as JSON, as documented.
                arguments = {"json": fields} if method in {"POST", "PATCH"} else {
                    "params": {key: json.dumps(value, separators=(",", ":"), allow_nan=False)
                               if isinstance(value, (dict, list)) else value for key, value in fields.items()}}
                async with client.stream(method, ORIGIN + path, headers={"Accept": "application/json"}, **arguments) as response:
                    if response.status_code in {401, 403}:
                        raise ClerkIOError("Clerk.io authentication failed or store access was refused (401/403).")
                    if response.status_code == 429:
                        raise ClerkIOError("Clerk.io rate limit reached (429); no request was retried.")
                    if response.status_code != 200:
                        raise ClerkIOError("Clerk.io request did not return a supported success response.")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "application/json":
                        raise ClerkIOError("Clerk.io returned an unsupported response format.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            raise ClerkIOError("Clerk.io response exceeded the bounded response size.")
                    try:
                        data = json.loads(body, object_pairs_hook=_pairs, parse_constant=_invalid_number)
                    except (UnicodeError, json.JSONDecodeError, RecursionError):
                        raise ClerkIOError("Clerk.io returned malformed JSON.") from None
                    if isinstance(data, dict) and data.get("status") == "error":
                        if data.get("type") == "AuthenticationError":
                            raise ClerkIOError("Clerk.io authentication failed or store access was refused.")
                        raise ClerkIOError("Clerk.io returned an application error; provider error details were omitted.")
                    if _key_echo(data, secrets):
                        raise ClerkIOError("Clerk.io returned credential-bearing data; output was withheld.")
    except ClerkIOError:
        raise
    except (httpx.HTTPError, ValueError, OSError, RecursionError):
        raise ClerkIOError("Clerk.io transport or response validation failed; a submitted write may already have applied.") from None
    return data


def _identifier(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and 0 < len(value) <= 256 and not any(ord(c) < 32 for c in value):
        return value
    raise ClerkIOError("Clerk.io returned an invalid resource identifier.")


def _identity(value):
    return (type(value), _identifier(value))


def products(data, *, requested=None, limit=100):
    if not isinstance(data, list) or len(data) > limit:
        raise ClerkIOError("Clerk.io returned an invalid product metadata collection.")
    seen, rows = set(), []
    allowed = {_identity(value) for value in requested} if requested is not None else None
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            raise ClerkIOError("Clerk.io product metadata did not identify its product.")
        identity = _identity(item["id"])
        if identity in seen or (allowed is not None and identity not in allowed):
            raise ClerkIOError("Clerk.io product metadata crossed the requested product boundary.")
        seen.add(identity)
        row = {"id": item["id"]}
        for key in ATTRIBUTES[1:]:
            if key not in item:
                continue
            value = item[key]
            if key in {"name", "sku", "brand"}:
                valid = isinstance(value, str) and len(value) <= 4096
            elif key in {"price", "list_price"}:
                valid = type(value) in {int, float} and math.isfinite(value)
            elif key in {"stock", "created_at"}:
                valid = type(value) is int
            elif key in {"index", "on_sale"}:
                valid = type(value) is bool
            else:
                valid = isinstance(value, list) and len(value) <= 1000
                if valid:
                    value = [_identifier(v) for v in value]
            if not valid:
                raise ClerkIOError("Clerk.io returned an invalid documented product attribute.")
            row[key] = value
        rows.append(row)
    return rows


def results(data, *, limit, categories=False, search=False):
    if not isinstance(data, dict) or data.get("status") != "ok" or not isinstance(data.get("result"), list):
        raise ClerkIOError("Clerk.io did not return a documented result collection.")
    identifiers = [_identifier(value) for value in data["result"]]
    if len(identifiers) > limit or len({_identity(v) for v in identifiers}) != len(identifiers):
        raise ClerkIOError("Clerk.io result identifiers exceeded the requested boundary.")
    output = {"result": identifiers, "returned_count": len(identifiers), "complete_export": False}
    if categories:
        rows = data.get("categories")
        if not isinstance(rows, list) or len(rows) > limit:
            raise ClerkIOError("Clerk.io returned invalid category metadata.")
        projected, seen = [], set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or len(row["name"]) > 4096:
                raise ClerkIOError("Clerk.io returned invalid category metadata.")
            identity = _identity(row.get("id"))
            if identity in seen or identity not in {_identity(v) for v in identifiers}:
                raise ClerkIOError("Clerk.io category metadata crossed the returned result boundary.")
            seen.add(identity)
            projected.append({"id": row["id"], "name": row["name"]})
        output["categories"] = projected
        output["metadata_complete"] = len(projected) == len(identifiers)
    elif "product_data" in data:
        output["products"] = products(data["product_data"], requested=identifiers, limit=limit)
        output["metadata_complete"] = len(output["products"]) == len(identifiers)
    else:
        output["products"], output["metadata_complete"] = [], not identifiers
    if search:
        for source, target in (("count", "reported_count"), ("hits", "reported_hits")):
            if source in data:
                if type(data[source]) is not int or data[source] < 0:
                    raise ClerkIOError("Clerk.io returned invalid search counts.")
                output[target] = data[source]
        if "no_exact_match" in data:
            if type(data["no_exact_match"]) is not bool:
                raise ClerkIOError("Clerk.io returned invalid search metadata.")
            output["no_exact_match"] = data["no_exact_match"]
    return output


def acknowledged(data):
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise ClerkIOError("Clerk.io did not return a documented acknowledgment; a write may already have applied.")
    return {"acknowledged": True, "applied": None, "readback_verified": False}


import sys
api = sys.modules[__name__]

"""Native Clerk.io ecommerce catalog and recommendation actions.

This provider uses store public/private keys, independently of Clerk identity.
Writes change personalization data; their acknowledgment is not a readback.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit

from pydantic import (BaseModel, ConfigDict, Discriminator, Field, StrictBool,
                      StrictInt, StrictStr, TypeAdapter, field_validator,
                      model_serializer, model_validator)

from nodes.core.base import WorkflowNode, NodeConfig, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import normalize_https_origin

KIND = "clerk_io_store_keys"
ResourceID = Union[Annotated[StrictInt, Field(ge=0)], Annotated[StrictStr, Field(min_length=1, max_length=256)]]
ReadProductID = Annotated[StrictInt, Field(ge=0, le=2147483647)]
Text = Annotated[StrictStr, Field(min_length=1, max_length=4096)]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]


class ClerkIOStoreCredential(BaseModel):
    model_config = ConfigDict(title="Clerk.io Store Keys", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://my.clerk.io/",
        "x-credential-instructions": "Use public and private API keys from the same Clerk.io store. Private audience-list access is checked separately from public recommendations.",
    })
    credential_type: Literal["clerk_io_store_keys"] = Field(KIND, json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., title="Store Public Key", repr=False,
                            description="Store Settings → API Keys. Public reads do not verify the private key.")
    private_key: str = Field(..., title="Store Private Key", repr=False,
                             description="The private key for the same Clerk.io store.",
                             json_schema_extra={"ui:widget": "password"})

    @field_validator("public_key", "private_key", mode="before")
    @classmethod
    def supplied_key(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a nonempty printable Clerk.io store key without whitespace.")
        return value

    @model_serializer(mode="wrap")
    def tagged_shape(self, handler):
        return {**handler(self), "credential_type": KIND}


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type", KIND) != KIND:
        raise ValueError("Supply a Clerk.io store-key credential.")
    try:
        return ClerkIOStoreCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Supply valid public and private Clerk.io store keys.") from None


class _Values(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("id", "customerid", "customer", "email", check_fields=False)
    @classmethod
    def identifier_text(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Resource identifiers cannot contain control characters.")
        return value

    @field_validator("image", "url", check_fields=False)
    @classmethod
    def catalog_link(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value)
        normalize_https_origin("https://" + parsed.netloc)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or any(c.isspace() for c in value):
            raise ValueError("Catalog links must be ordinary public HTTPS URLs.")
        # These are metadata for Clerk.io; NoClick never downloads their bytes.
        return value


class Product(_Values):
    id: ResourceID
    name: Text
    description: Annotated[StrictStr, Field(max_length=20000)]
    price: Money
    image: Annotated[StrictStr, Field(max_length=2048)]
    url: Annotated[StrictStr, Field(max_length=2048)]
    categories: Annotated[list[ResourceID], Field(max_length=100)]
    created_at: Annotated[StrictInt, Field(ge=0)]
    index: StrictBool = Field(False, description="False excludes this product from indexed results; history and models can still be affected.")
    list_price: Optional[Money] = None
    brand: Optional[Text] = None
    sku: Optional[Text] = None
    stock: Optional[Annotated[StrictInt, Field(ge=0)]] = None
    on_sale: Optional[StrictBool] = None


class ProductPatch(_Values):
    id: ResourceID
    name: Optional[Text] = None
    price: Optional[Money] = None
    list_price: Optional[Money] = None
    brand: Optional[Text] = None
    sku: Optional[Text] = None
    stock: Optional[Annotated[StrictInt, Field(ge=0)]] = None
    on_sale: Optional[StrictBool] = None
    index: Optional[StrictBool] = None

    @model_validator(mode="after")
    def changed_values(self):
        if not any(getattr(self, key) is not None for key in self.model_fields_set - {"id"}):
            raise ValueError("Provide at least one documented product value to patch.")
        return self


class Category(_Values):
    id: ResourceID
    name: Text
    url: Annotated[StrictStr, Field(max_length=2048)]
    subcategories: Annotated[list[ResourceID], Field(max_length=100)]


class CategoryPatch(_Values):
    id: ResourceID
    name: Optional[Text] = None
    url: Optional[Annotated[StrictStr, Field(max_length=2048)]] = None
    subcategories: Optional[Annotated[list[ResourceID], Field(max_length=100)]] = None

    @model_validator(mode="after")
    def changed_values(self):
        if not any(getattr(self, key) is not None for key in self.model_fields_set - {"id"}):
            raise ValueError("Provide at least one documented category value to patch.")
        return self


class Customer(_Values):
    customerid: Optional[ResourceID] = Field(None, title="Customer ID")
    email: Optional[Annotated[StrictStr, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]] = None
    name: Optional[Text] = None
    subscribed: Literal[False] = Field(False, description="This action never opts a customer into marketing.")
    zip: Optional[Annotated[StrictStr, Field(max_length=64)]] = None
    is_b2b: Optional[StrictBool] = None

    @field_validator("subscribed", mode="before")
    @classmethod
    def quiet_subscription(cls, value):
        if value is not False:
            raise ValueError("Marketing opt-in is excluded from these customer actions.")
        return value

    @model_validator(mode="after")
    def supplied_identity(self):
        if self.customerid is None and self.email is None:
            raise ValueError("Supply an existing customer ID or email; identifiers cannot be renamed.")
        return self


class CustomerPatch(Customer):
    @model_validator(mode="after")
    def changed_values(self):
        if not any(getattr(self, key) is not None for key in self.model_fields_set - {"customerid", "email"}):
            raise ValueError("Provide a documented customer value to patch.")
        return self


class OrderProduct(_Values):
    id: ResourceID
    quantity: Annotated[StrictInt, Field(ge=1, le=1000000)]
    price: Money


OrderStatus = Literal["CONFIRMED", "SENT", "DELIVERED", "RETURNED", "CANCELLED"]


class Order(_Values):
    id: ResourceID
    customer: ResourceID
    products: Annotated[list[OrderProduct], Field(min_length=1, max_length=100)]
    time: Annotated[StrictInt, Field(ge=0)]
    email: Optional[Annotated[StrictStr, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]] = None
    status: Optional[OrderStatus] = None


class OrderPatch(_Values):
    id: ResourceID
    status: OrderStatus


def action(value, label, category, effect):
    return Field(value, json_schema_extra={"const": value, "displayName": label,
                 "category": category, "isTrigger": False, "description": effect})


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class CheckConnection(_Config):
    operation: Literal["check_connection"] = action("check_connection", "Check Private Store Access", "Connection", "Read the documented audience-list acknowledgment with both store keys. No account identity or write permission proof.")


class CheckPublicConnection(_Config):
    operation: Literal["check_public_connection"] = action("check_public_connection", "Check Public Store Reachability", "Connection", "Read at most one popular product. The private key is not sent or verified.")


class GetProducts(_Config):
    operation: Literal["get_products"] = action("get_products", "Get Product Attributes", "Catalog", "Read closed product metadata for up to 50 numeric int32 IDs.")
    products: Annotated[list[ReadProductID], Field(min_length=1, max_length=50)]


class _Limited(_Config):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 20


class _Offset(_Limited):
    offset: Annotated[StrictInt, Field(ge=0, le=100000)] = 0


class SearchProducts(_Offset):
    operation: Literal["search_products"] = action("search_products", "Search Products", "Search", "One bounded page; no tracking parameters or invented pagination totals.")
    query: Annotated[StrictStr, Field(min_length=1, max_length=1000)]


class SearchCategories(_Config):
    operation: Literal["search_categories"] = action("search_categories", "Search Categories", "Search", "Up to 10 category results. This endpoint has no documented offset.")
    query: Annotated[StrictStr, Field(max_length=1000)] = ""
    limit: Annotated[StrictInt, Field(ge=1, le=10)] = 10


class PopularProducts(_Offset):
    operation: Literal["popular_products"] = action("popular_products", "Popular Products", "Recommendations", "Read a bounded recommendation page without visitor tracking.")


class TrendingProducts(_Offset):
    operation: Literal["trending_products"] = action("trending_products", "Trending Products", "Recommendations", "Read a bounded recommendation page without visitor tracking.")


class NewProducts(_Limited):
    operation: Literal["new_products"] = action("new_products", "New Products", "Recommendations", "The documented endpoint has no offset; results are not creation events.")


class ComplementaryProducts(_Limited):
    operation: Literal["complementary_products"] = action("complementary_products", "Complementary Products", "Recommendations", "Recommend products for the supplied product IDs; no cart event is recorded.")
    products: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=256)]], Field(min_length=1, max_length=50)]


class SubstitutingProducts(ComplementaryProducts):
    operation: Literal["substituting_products"] = action("substituting_products", "Substitute Products", "Recommendations", "Recommend alternatives to supplied product IDs; no tracking event is recorded.")


class CategoryPopularProducts(_Offset):
    operation: Literal["category_popular_products"] = action("category_popular_products", "Popular Products in Category", "Recommendations", "Provider category selection includes its subcategories. No independent category ancestry proof.")
    category: Annotated[StrictStr, Field(min_length=1, max_length=256)]


class UpsertProducts(_Config):
    operation: Literal["upsert_products"] = action("upsert_products", "Add or Update Products", "Catalog Writes", "Upsert catalog records; existing IDs can be overwritten. Indexing and personalization can change.")
    products: Annotated[list[Product], Field(min_length=1, max_length=20)]


class PatchProducts(_Config):
    operation: Literal["patch_products"] = action("patch_products", "Patch Products", "Catalog Writes", "Patch documented fields; no conditional update or automatic retry.")
    products: Annotated[list[ProductPatch], Field(min_length=1, max_length=20)]


class RemoveProducts(_Config):
    operation: Literal["remove_products"] = action("remove_products", "Remove Products", "Catalog Writes", "Delete selected catalog IDs; not proof of historical data erasure.")
    products: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=256)]], Field(min_length=1, max_length=20)]


class UpsertCategories(_Config):
    operation: Literal["upsert_categories"] = action("upsert_categories", "Add or Update Categories", "Catalog Writes", "Upsert category names, URLs and subcategory membership; no create-only condition.")
    categories: Annotated[list[Category], Field(min_length=1, max_length=20)]


class PatchCategories(_Config):
    operation: Literal["patch_categories"] = action("patch_categories", "Patch Categories", "Catalog Writes", "Patch category fields. The current contract has no category DELETE action.")
    categories: Annotated[list[CategoryPatch], Field(min_length=1, max_length=20)]


class UpsertCustomers(_Config):
    operation: Literal["upsert_customers"] = action("upsert_customers", "Add or Update Customers", "Customer Writes", "Upsert customer profiles; audience segmentation can change. Marketing opt-in is excluded.")
    customers: Annotated[list[Customer], Field(min_length=1, max_length=20)]


class PatchCustomers(_Config):
    operation: Literal["patch_customers"] = action("patch_customers", "Patch Customers", "Customer Writes", "Patch existing customer profiles; supplied ID/email identify the record and are not renamed.")
    customers: Annotated[list[CustomerPatch], Field(min_length=1, max_length=20)]


class RemoveCustomers(_Config):
    operation: Literal["remove_customers"] = action("remove_customers", "Remove Customers", "Customer Writes", "Delete selected profiles; not proof of erasure from history, audiences or downstream systems.")
    customers: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=256)]], Field(min_length=1, max_length=20)]


class UpsertOrders(_Config):
    operation: Literal["upsert_orders"] = action("upsert_orders", "Add or Update Order Data", "Order Writes", "Import Clerk.io analytics order records; can change recommendation models, audiences and configured Auto Email.")
    orders: Annotated[list[Order], Field(min_length=1, max_length=20)]


class PatchOrders(_Config):
    operation: Literal["patch_orders"] = action("patch_orders", "Patch Order Status Data", "Order Writes", "Patch imported analytics order status. This does not dispatch or fulfill an ecommerce order.")
    orders: Annotated[list[OrderPatch], Field(min_length=1, max_length=20)]


class RemoveOrders(_Config):
    operation: Literal["remove_orders"] = action("remove_orders", "Remove Order Data", "Order Writes", "Delete analytics order records; personalization and sales history can change.")
    orders: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=256)]], Field(min_length=1, max_length=20)]


ClerkIOConfig = Annotated[Union[CheckConnection, CheckPublicConnection, GetProducts, SearchProducts,
    SearchCategories, PopularProducts, TrendingProducts, NewProducts, ComplementaryProducts,
    SubstitutingProducts, CategoryPopularProducts, UpsertProducts, PatchProducts, RemoveProducts,
    UpsertCategories, PatchCategories, UpsertCustomers, PatchCustomers, RemoveCustomers,
    UpsertOrders, PatchOrders, RemoveOrders], Discriminator("operation")]


class ClerkIONodeConfig(NodeConfig[ClerkIOConfig, ClerkIOStoreCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True,
                              json_schema_extra={"x-agent-tool-provider": True})


class ClerkIONode(WorkflowNode):
    integration_type = "automation-clerk-io"
    config: ClerkIONodeConfig
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="store API access", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ClerkIONodeConfig

    @classmethod
    def parse_config(cls, data):
        supplied = data.get("credentials") if isinstance(data, dict) else None
        if isinstance(supplied, dict):
            credential(supplied)  # Reject foreign tags before shared reconciliation.
        try:
            return TypeAdapter(ClerkIONodeConfig).validate_python(runtime_config_view(data, ClerkIONodeConfig))
        except Exception:
            raise ValueError("Invalid Clerk.io operation, bounds or store credential; check the selected action fields.") from None

    @classmethod
    def validate_credential(cls, data):
        return credential(data)

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials")
        if raw is None and self.config.credentials is not None:
            raw = self.config.credentials.model_dump()
        if raw is None:
            raise ValueError("Connect public and private keys for the same Clerk.io store.")
        current = credential(raw)
        operation = cfg.operation
        values = cfg.model_dump(exclude={"operation"}, exclude_none=True)
        if operation in api.WRITES and api.WRITES[operation][0] == "PATCH":
            resource = api.WRITES[operation][2]
            values[resource] = [row.model_dump(exclude_unset=True, exclude_none=True) for row in getattr(cfg, resource)]
        # Batch selectors stay typed and bounded; duplicate writes are refused.
        for field in ("products", "categories", "customers", "orders"):
            if field in values:
                identities = [(type(v.get("customerid", v.get("id", v.get("email")))), v.get("customerid", v.get("id", v.get("email")))) if isinstance(v, dict)
                              else (type(v), v) for v in values[field]]
                if len(set(identities)) != len(identities):
                    raise ValueError("Clerk.io batches cannot repeat a resource identifier.")
        if operation == "check_public_connection":
            values = {"limit": 1, "attributes": list(api.ATTRIBUTES)}
        elif operation in api.PUBLIC_READS and operation != "search_categories":
            values["attributes"] = list(api.ATTRIBUTES)
        data = await api.request(current, operation, values)
        if operation == "check_connection":
            api.acknowledged(data)
            return {"private_key_accepted": True, "public_key_accepted": True,
                    "verified_endpoint": "/audiences/list", "proves": "reachability", "identity_verified": False,
                    "write_permissions_verified": False}
        if operation == "get_products":
            rows = api.products(data, requested=cfg.products, limit=len(cfg.products))
            found = {api._identity(row["id"]) for row in rows}
            return {"products": rows, "requested_count": len(cfg.products), "returned_count": len(rows),
                    "missing_ids": [v for v in cfg.products if api._identity(v) not in found],
                    "private_key_verified": False}
        if operation in api.PUBLIC_READS:
            output = api.results(data, limit=values["limit"], categories=operation == "search_categories",
                                 search=operation == "search_products")
            output["private_key_verified"] = False
            if "offset" in values:
                output["requested_offset"] = values["offset"]
            if operation == "category_popular_products":
                output["requested_category"] = cfg.category
            if operation == "check_public_connection":
                return {"public_key_accepted": True, "private_key_accepted": None, "identity_verified": False,
                        "proves": "reachability", "returned_count": output["returned_count"]}
            return output
        output = api.acknowledged(data)
        _, _, resource = api.WRITES[operation]
        return {**output, "resource": resource, "submitted_count": len(values[resource]),
                "effect": "Personalization catalog, audience or order analytics data may have changed."}
