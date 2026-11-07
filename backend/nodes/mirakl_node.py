"""Mirakl Platform marketplace metadata and explicit single-offer imports.

Supplied Mirakl Authentication System Bearer tokens only. Connect, Catalog,
Ads, Payout, bulk files, order controls and customer content are excluded.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-mirakl"
FAMILIES = {"mirakl_mas_token"}
MAX_BYTES = 2_097_152
Code = Annotated[StrictStr, Field(min_length=1, max_length=200, pattern=r"^[^,|/\\?#\s]+$")]
PositiveId = Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=1000)]

def _dynamic(field_name):
    return {"x-dynamic-options": {"field_name": field_name, "allow_custom": True, "searchable": True}}

def _origin(value):
    try:
        if not isinstance(value, str) or value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value) or any(c in value for c in "\\\\?#%"):
            raise ValueError
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.path not in ("", "/") or not host or host.endswith("."):
            raise ValueError
        host = host.encode("idna").decode("ascii")
        if len(host) > 253 or "." not in host or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        return "https://" + host
    except (ValueError, UnicodeError):
        raise ValueError("Use the public HTTPS marketplace origin from the issued MAS token response") from None

class MiraklMASCredential(BaseModel):
    model_config = ConfigDict(title="Mirakl Platform", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "api_key",
            "x-credential-url": "https://developer.mirakl.com/"})
    credential_type: Literal["mirakl_mas_token"] = Field("mirakl_mas_token", json_schema_extra={"ui:hidden": True})
    access_token: StrictStr = Field(..., min_length=1, max_length=16384, repr=False, title="MAS Access Token",
        description="Already issued Mirakl Authentication System OAuth2 access token. Bearer header only; legacy API keys and Connect tokens are not supported.",
        json_schema_extra={"ui:widget": "password"})
    marketplace_url: StrictStr = Field(..., title="Marketplace URL", description="Exact public HTTPS origin from the MAS token response; not the Connect or auth service.")
    marketplace_id: Code = Field(..., title="Marketplace ID", description="Tenant ID from the same MAS token response. This supplied value is a binding, not an independently proved account identity.")
    role: Literal["seller", "operator"] = Field(..., description="Role of the granted Platform resource. Seller operations use the token's single selected shop.")
    shop_id: PositiveId = Field(..., title="Bound Shop ID", description="Seller: exact shop_id from MAS. Operator: one existing shop to restrict order and product-offer reads.")
    expires_at: Optional[StrictInt] = Field(None, ge=1, title="Expiry (Unix Seconds)", description="Optional actual expiry from the issued grant. No TTL is guessed; expired supplied tokens must be replaced. This node does not mint or refresh grants.")
    @field_validator("marketplace_url")
    @classmethod
    def origin(cls, value):
        return _origin(value)
    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        if value != value.strip() or is_placeholder(value) or is_url_shaped(value) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use an existing MAS access token without a header prefix or whitespace")
        return value

def _credential(raw):
    if isinstance(raw, MiraklMASCredential):
        return raw
    if not isinstance(raw, dict) or raw.get("credential_type") not in (None, *FAMILIES):
        raise ValueError("Connect Mirakl MAS supplied-token credentials")
    return MiraklMASCredential.model_validate(raw)

class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    @field_validator("offer_id", mode="before", check_fields=False)
    @classmethod
    def picker_identifier(cls, value):
        # The canonical socket FieldOption stores strings; preserve strict IDs.
        if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value):
            return int(value)
        return value
    @field_validator("*", mode="after")
    @classmethod
    def plain(cls, value):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use bounded plain metadata")
        return value
class _Page(_Config):
    limit: StrictInt = Field(50, ge=1, le=100, description="One bounded Mirakl max page.")
    offset: StrictInt = Field(0, ge=0, le=1000000)
class GetAccessScope(_Config):
    operation: Literal["get_access_scope"] = "get_access_scope"
class GetShop(_Config):
    operation: Literal["get_shop"] = "get_shop"
class ListCategories(_Config):
    operation: Literal["list_categories"] = "list_categories"
    hierarchy: Optional[Code] = Field(None, description="Existing parent category code; empty retrieves the root.")
    max_level: StrictInt = Field(1, ge=0, le=3)
class ListProductAttributes(_Config):
    operation: Literal["list_product_attributes"] = "list_product_attributes"
    hierarchy: Code = Field(..., json_schema_extra=_dynamic("hierarchy"))
    max_level: StrictInt = Field(0, ge=0, le=3)
class ListChannels(_Config):
    operation: Literal["list_channels"] = "list_channels"
class ListCurrencies(_Config):
    operation: Literal["list_currencies"] = "list_currencies"
class ListLocales(_Config):
    operation: Literal["list_locales"] = "list_locales"
class ListOfferStates(_Config):
    operation: Literal["list_offer_states"] = "list_offer_states"
class GetValuesList(_Config):
    operation: Literal["get_values_list"] = "get_values_list"
    code: Code
class ProductReference(_Config):
    type: Code = Field(..., description="Operator reference type such as EAN or UPC. SKU and SHOP_SKU are invalid for P31.")
    value: Code
    @field_validator("type")
    @classmethod
    def type_code(cls, value):
        if value in {"SKU", "SHOP_SKU"}:
            raise ValueError("P31 requires an operator product reference type")
        return value
class GetProducts(_Config):
    operation: Literal["get_products"] = "get_products"
    references: list[ProductReference] = Field(..., min_length=1, max_length=20)
class ListShopOffers(_Page):
    operation: Literal["list_shop_offers"] = "list_shop_offers"
    sku: Optional[Code] = None
class GetOffer(_Config):
    operation: Literal["get_offer"] = "get_offer"
    offer_id: PositiveId = Field(..., json_schema_extra=_dynamic("offer_id"))
    product_sku: Code = Field(..., description="Existing product SKU used to verify the selected offer belongs to the bound shop.")
class ListOrders(_Page):
    operation: Literal["list_orders"] = "list_orders"
    order_id: Optional[Code] = None
class _OfferBody(_Config):
    shop_sku: Code
    state_code: Code = Field(..., json_schema_extra=_dynamic("state_code"))
    price: Annotated[StrictFloat, Field(ge=0, le=1000000000, allow_inf_nan=False)]
    quantity: StrictInt = Field(..., ge=0, le=2147483647, description="Available stock; zero is not a documented draft state.")
    description: Optional[Name] = None
    internal_description: Optional[Name] = None
    product_tax_code: Optional[Code] = None
class CreateOffer(_OfferBody):
    operation: Literal["create_offer"] = "create_offer"
    product_id: Code
    product_id_type: Code = Field(..., description="Operator product reference type such as EAN or UPC. SKU and SHOP_SKU are unsupported by this node's P31 parent check.")
    @field_validator("product_id_type")
    @classmethod
    def reference_type(cls, value):
        if value in {"SKU", "SHOP_SKU"}:
            raise ValueError("Use an operator product reference type for the native parent check")
        return value
class ReplaceOffer(_OfferBody):
    operation: Literal["replace_offer"] = "replace_offer"
    offer_id: PositiveId = Field(..., json_schema_extra=_dynamic("offer_id"))
    acknowledge_field_resets: Literal[True] = Field(..., description="Full OF24 replacement resets omitted prices, discounts, availability, custom fields and other options. This is not a partial metadata patch.")
class DeleteOffer(_Config):
    operation: Literal["delete_offer"] = "delete_offer"
    offer_id: PositiveId = Field(..., json_schema_extra=_dynamic("offer_id"))
    shop_sku: Code
class GetOfferImport(_Config):
    operation: Literal["get_offer_import"] = "get_offer_import"
    import_id: PositiveId

MiraklConfig = Annotated[Union[GetAccessScope, GetShop, ListCategories, ListProductAttributes,
    ListChannels, ListCurrencies, ListLocales, ListOfferStates, GetValuesList, GetProducts,
    ListShopOffers, GetOffer, ListOrders, CreateOffer, ReplaceOffer, DeleteOffer, GetOfferImport],
    Field(discriminator="operation")]
class MiraklNodeConfig(NodeConfig):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    config: MiraklConfig
    credentials: Optional[MiraklMASCredential] = None

class CredentialValidationUnavailable(ValueError):
    """The saved Mirakl grant or its current access changed."""


@dataclass
class _Authority:
    credential_id: str
    actor: str
    pool: object = field(repr=False)
    workflow_id: Optional[str] = None
    snapshot: object = field(default=None, repr=False)
    credential: object = field(default=None, repr=False)

    async def load(self):
        from repositories.credentials import credential_access_predicate
        from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
        from utils.encryption import get_encryption
        from wss.handlers.workflow_handler import get_user_org_context
        async def fetch(conn, user, org):
            return await conn.fetchrow(f"""
                SELECT c.credential, c.credential_type, c.owner_id, c.revoked_at,
                       c.token_version, c.updated_at, c.approval_revision
                FROM credentials c
                WHERE c.id = $1 AND {credential_access_predicate()}
            """, self.credential_id, user, org)
        async with self.pool.acquire() as conn:
            actor_org = await get_user_org_context(conn, self.actor)
            principal, principal_org = self.actor, actor_org
            row = await fetch(conn, principal, principal_org)
        if row is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if owner and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id):
                principal = owner
                async with self.pool.acquire() as conn:
                    principal_org = await get_user_org_context(conn, owner)
                    row = await fetch(conn, owner, principal_org)
        if row is None or row["revoked_at"] is not None or row["credential_type"] not in FAMILIES:
            raise CredentialValidationUnavailable("Mirakl credential is unavailable or access denied")
        if type(row["token_version"]) is not int or row["token_version"] < 1:
            raise CredentialValidationUnavailable("Mirakl saved credential version is invalid")
        snapshot = (actor_org, principal, principal_org, *(row[k] for k in ("owner_id", "credential_type", "token_version", "updated_at", "approval_revision")))
        try:
            raw = get_encryption().decrypt_credential(row["credential"])
            credential = _credential({**raw, "credential_type": row["credential_type"]})
        except Exception:
            raise CredentialValidationUnavailable("Mirakl saved credential is invalid") from None
        if self.snapshot is not None and (self.snapshot != snapshot or self.credential != credential):
            raise CredentialValidationUnavailable("Mirakl credential authority or marketplace binding changed; retry")
        self.snapshot, self.credential = snapshot, credential
        return credential.model_dump()

    async def revalidate(self):
        await self.load()


async def _current_authority(*, credential_id, user_id, pool, workflow_id=None):
    if not user_id or pool is None:
        raise CredentialValidationUnavailable("Mirakl credential authority is unavailable")
    authority = _Authority(credential_id, user_id, pool, workflow_id)
    await authority.load()
    return authority


_ACTIVE_AUTHORITY: ContextVar[Optional[_Authority]] = ContextVar("mirakl_authority", default=None)
_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("mirakl_private_request", default=False)


class _PrivateRequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "utils.ssrf"):
    logging.getLogger(_logger).addFilter(_PrivateRequestLogFilter())


class _AuthRefused(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Mirakl returned duplicate JSON properties")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Mirakl returned non-finite JSON")

def _contains_token(raw, token):
    pending = [raw]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and token in item:
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _text(value, maximum=1000):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Mirakl returned invalid text metadata")
    return value


class _BoundCredential(dict):
    """Private in-process authority binding, never a caller-supplied JSON flag."""
    def __init__(self, credential, authority):
        super().__init__(credential.model_dump() if isinstance(credential, MiraklMASCredential) else credential)
        self.authority = authority



def _id(value):
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise ValueError("Mirakl returned an invalid integer identifier")
    return value

def _record(raw, kind, *, expected=None, shop_id=None, require_shop=False):
    if not isinstance(raw, dict):
        raise ValueError("Mirakl returned invalid record metadata")
    ids = {"shop": "shop_id", "offer": "offer_id", "order": "order_id", "category": "code",
        "attribute": "code", "channel": "code", "currency": "code", "locale": "code", "state": "code",
        "values": "code", "product": "product_sku", "import": "import_id"}
    key = ids[kind]
    value = _id(raw.get(key)) if key.endswith("_id") and kind != "order" else _text(raw.get(key), 200)
    if expected is not None and value != expected:
        raise ValueError("Mirakl returned a different selected record")
    if require_shop and raw.get("shop_id") is None or raw.get("shop_id") is not None and shop_id is not None and _id(raw["shop_id"]) != shop_id:
        raise ValueError("Mirakl returned metadata outside the bound shop")
    fields = {
        "shop": ("shop_name", "shop_state", "model", "currency_iso_code", "date_created", "last_updated_date", "offers_count", "orders_count"),
        "offer": ("shop_sku", "product_sku", "product_title", "category_code", "category_label", "state_code", "active", "quantity"),
        "order": ("shop_id", "shop_name", "order_state", "created_date", "last_updated_date", "has_incident"),
        "category": ("label", "parent_code", "level"),
        "attribute": ("label", "hierarchy_code", "type", "requirement_level", "variant", "unique_code", "locale"),
        "channel": ("label",), "currency": ("label", "platform_default"), "locale": ("label", "platform_default"),
        "state": ("label",), "values": ("label",),
        "product": ("product_title", "product_id", "product_id_type", "category_code", "category_label"),
        "import": ("status", "mode", "date_created", "lines_in_error", "lines_in_pending", "lines_in_success", "lines_read",
            "offer_deleted", "offer_inserted", "offer_updated", "has_error_report"),
    }[kind]
    out = {key: value}
    for name in fields:
        if name not in raw:
            continue
        item = raw[name]
        if item is None or item == "":
            out[name] = item
        elif name in {"active", "has_incident", "platform_default", "has_error_report", "variant"}:
            if type(item) is not bool:
                raise ValueError("Mirakl returned invalid boolean metadata")
            out[name] = item
        elif name == "shop_id":
            out[name] = _id(item)
        elif name.endswith("_count") or name.startswith("lines_") or name in {"quantity", "level", "offer_deleted", "offer_inserted", "offer_updated"}:
            if type(item) is not int or not 0 <= item <= 1000000000:
                raise ValueError("Mirakl returned invalid count metadata")
            out[name] = item
        else:
            out[name] = _text(item, 1000)
    return out

def _collection(raw, key, kind, *, limit=500, offset=None, shop_id=None, require_shop=False):
    if not isinstance(raw, dict) or not isinstance(raw.get(key), list) or len(raw[key]) > limit:
        raise ValueError("Mirakl returned an invalid bounded collection")
    rows = [_record(row, kind, shop_id=shop_id, require_shop=require_shop) for row in raw[key]]
    identifier = {"offer": "offer_id", "order": "order_id", "category": "code", "attribute": "code",
        "channel": "code", "currency": "code", "locale": "code", "state": "code", "values": "code",
        "product": "product_sku"}[kind]
    # P31 can return multiple reference matches for a product; preserve each row.
    identities = ([(row[identifier], row.get("product_id_type"), row.get("product_id")) for row in rows] if kind == "product"
        else [(row.get("unique_code") or row[identifier], row.get("hierarchy_code"), row.get("locale")) for row in rows] if kind == "attribute"
        else [row[identifier] for row in rows])
    if len(set(identities)) != len(rows):
        raise ValueError("Mirakl returned duplicate record identifiers")
    if offset is None:
        return {"items": rows, "returned_count": len(rows)}
    count = raw.get("total_count")
    if type(count) is not int or not 0 <= count <= 1000000000 or rows and count < offset + len(rows):
        raise ValueError("Mirakl returned an invalid pagination total")
    more = offset + len(rows) < count
    nxt = offset + len(rows) if more and rows and offset + len(rows) <= 1000000 else None
    return {"items": rows, "returned_count": len(rows), "limit": limit, "offset": offset,
        "total_count": count, "next_offset": nxt, "pagination_complete": not more,
        "continuation_blocked": more and nxt is None}

class _Session:
    def __init__(self, credential):
        self.credential = credential

    async def request(self, method, path, *, params=None, body=None, expected_status=(200,)):
        routes = {"/api/account", "/api/hierarchies", "/api/products/attributes", "/api/channels",
            "/api/currencies", "/api/locales", "/api/offers/states", "/api/values_lists",
            "/api/products", "/api/products/offers", "/api/offers", "/api/orders"}
        if not (method == "GET" and (path in routes or re.fullmatch(r"/api/offers/[1-9][0-9]{0,18}", path)
                or re.fullmatch(r"/api/offers/imports/[1-9][0-9]{0,18}", path))
                or method == "POST" and path == "/api/offers" and self.credential.role == "seller"):
            raise ValueError("Unsupported Mirakl request")
        if params and set(params) - {"shop_id", "shop_ids", "max", "offset", "sku", "product_id",
                "product_ids", "product_references", "hierarchy", "max_level", "code", "order_ids", "all_offers"}:
            raise ValueError("Unsupported Mirakl query")
        if params and ("shop_id" in params and params["shop_id"] != self.credential.shop_id
                or "shop_ids" in params and params["shop_ids"] != str(self.credential.shop_id)):
            raise ValueError("Mirakl request is outside the bound shop")
        if body is not None and len(json.dumps(body, allow_nan=False).encode()) > 65536:
            raise ValueError("Mirakl request exceeds the bounded limit")
        if self.credential.expires_at is not None and datetime.now(timezone.utc).timestamp() >= self.credential.expires_at:
            raise _AuthRefused("Mirakl invalid_token: supplied MAS access token has expired; reconnect with an issued token")
        authority = _ACTIVE_AUTHORITY.get()
        if authority and _credential(await authority.load()) != self.credential:
            raise CredentialValidationUnavailable("Mirakl credential or marketplace binding changed; retry")
        private = _PRIVATE_REQUEST.set(True)
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=20.0) as client:
                async with client.stream(method, self.credential.marketplace_url + path,
                        headers={"Authorization": "Bearer " + self.credential.access_token, "Accept": "application/json"},
                        params=params, json=body) as response:
                    if response.status_code in (401, 403):
                        raise _AuthRefused("Mirakl token or permission was rejected (HTTP " + str(response.status_code) + ")")
                    if response.status_code == 429:
                        raise ValueError("Mirakl rate limit reached; retry later")
                    if response.status_code not in expected_status:
                        raise ValueError("Mirakl request failed with HTTP " + str(response.status_code))
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Mirakl returned an unsupported metadata format")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError("Mirakl response exceeds the bounded limit")
                    try:
                        raw = json.loads(data, object_pairs_hook=_unique, parse_constant=_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("Mirakl returned invalid JSON metadata") from None
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Mirakl public HTTPS request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(private)
        if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors", "error_code")):
            raise ValueError("Mirakl returned a failed provider response")
        if _contains_token(raw, self.credential.access_token):
            raise ValueError("Mirakl returned credential material in metadata")
        return raw
class MiraklNode(WorkflowNode):
    integration_type = "automation-mirakl"
    connection_evidence = ConnectionEvidence(noun="shop or order metadata", operation="get_access_scope", label_keys=("shop_name", "order_id"), proves="account")
    @classmethod
    def get_config_model(cls):
        return MiraklNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credential_id"):
            return super().parse_config({**config_data, "credentials": None})
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if raw is not None:
            _credential(raw)
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_id:
            # The loader receives trusted workflow context after this hook.
            # Defer loading so staging's authorized owner fallback can use it.
            if pool is None:
                from utils.database_pool import get_native_pool
                pool = get_native_pool()
            return _BoundCredential(credential_data, _Authority(credential_id, user_id, pool))
        return _credential(credential_data).model_dump()
    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging supplies the decrypted grant to this hook. Stored-operation
        # admission stays in the shared runner; do not require a PR-only context.
        try:
            credential = _credential(credential_data)
        except ValueError:
            return {"valid": False, "error": "Use a valid Mirakl MAS token and marketplace binding"}
        try:
            await cls._execute(_Session(credential), GetAccessScope())
            return {"valid": True}
        except _AuthRefused:
            return {"valid": False, "error": "Mirakl token or access was rejected"}
        except ValueError:
            return {"valid": None, "error": "Mirakl protected metadata could not be verified"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        kinds = {"hierarchy": ListCategories, "state_code": ListOfferStates, "offer_id": ListShopOffers}
        if field_name not in kinds:
            raise ValueError("Unsupported Mirakl picker")
        if search is not None and (not isinstance(search, str) or len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise ValueError("Use a bounded metadata search")
        offset = 0
        if page_token is not None:
            if field_name != "offer_id" or not isinstance(page_token, str) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", page_token) or int(page_token) > 1000000:
                raise ValueError("Use a bounded Mirakl offset for an offer picker")
            offset = int(page_token)
        authority = credential_data.authority if isinstance(credential_data, _BoundCredential) else None
        if authority and authority.snapshot is None:
            authority.workflow_id = (context or {}).get("_workflow_id")
        binding = _ACTIVE_AUTHORITY.set(authority)
        try:
            credential = _credential(await authority.load()) if authority else _credential(credential_data)
            config = kinds[field_name](limit=50, offset=offset) if field_name == "offer_id" else kinds[field_name]()
            result = await cls._execute(_Session(credential), config)
            options = [{"value": str(row["offer_id"]) if field_name == "offer_id" else row["code"],
                "label": row.get("shop_sku") or row.get("label") or str(row.get("offer_id", row.get("code")))}
                for row in result["items"]]
            if search:
                options = [row for row in options if search.casefold() in row["label"].casefold()]
            if authority:
                await authority.revalidate()
            return {"options": options, "next_page_token": str(result["next_offset"]) if result.get("next_offset") is not None else None}
        finally:
            _ACTIVE_AUTHORITY.reset(binding)

    async def execute(self, inputs):
        if not isinstance(self.config, MiraklNodeConfig) or (self.config.credentials is None and not self.node_data.get("credential_id")):
            raise ValueError("Connect Mirakl account API credentials")
        credential, authority = self.config.credentials, None
        if self.node_data.get("credential_id"):
            pool = self.node_data.get("_approval_pool")
            if pool is None:
                from utils.database_pool import get_native_pool
                pool = get_native_pool()
            authority = await _current_authority(credential_id=self.node_data["credential_id"], user_id=self.user_id, pool=pool, workflow_id=self.workflow_id)
            credential = _credential(await authority.load())
        token = _ACTIVE_AUTHORITY.set(authority)
        try:
            result = await self._execute(_Session(credential), self.config.config)
            if authority:
                await authority.revalidate()
            return {"status": "success", "data": result}
        finally:
            _ACTIVE_AUTHORITY.reset(token)


    @staticmethod
    def _seller(session):
        if session.credential.role != "seller":
            raise ValueError("This operation requires a MAS seller token bound to its selected shop")

    @classmethod
    async def _shop(cls, session):
        cls._seller(session)
        raw = await session.request("GET", "/api/account", params={"shop_id": session.credential.shop_id})
        row = _record(raw, "shop", expected=session.credential.shop_id)
        if not row.get("shop_name"):
            raise ValueError("Mirakl did not return the selected shop name")
        return row

    @staticmethod
    async def _sku_offer(session, sku):
        raw = await session.request("GET", "/api/offers", params={"shop_id": session.credential.shop_id, "sku": sku, "max": 2, "offset": 0})
        result = _collection(raw, "offers", "offer", limit=2, offset=0)
        if any(row.get("shop_sku") != sku for row in result["items"]) or result["total_count"] > 1:
            raise ValueError("Mirakl did not return one matching offer SKU in the selected shop")
        return result["items"][0] if result["items"] else None

    @staticmethod
    async def _product_offers(session, product_sku):
        raw = await session.request("GET", "/api/products/offers", params={
            "product_ids": product_sku, "shop_ids": str(session.credential.shop_id), "max": 100, "offset": 0, "all_offers": "true"})
        if not isinstance(raw.get("products"), list) or len(raw["products"]) != 1:
            raise ValueError("The selected product is unavailable in this marketplace")
        product = raw["products"][0]
        if not isinstance(product, dict) or product.get("product_sku") != product_sku or not isinstance(product.get("offers"), list) or len(product["offers"]) > 100:
            raise ValueError("Mirakl returned invalid product-offer parent metadata")
        rows = [_record(row, "offer", shop_id=session.credential.shop_id, require_shop=True) for row in product["offers"]]
        if len({row["offer_id"] for row in rows}) != len(rows):
            raise ValueError("Mirakl returned duplicate offers")
        return rows

    @classmethod
    async def _execute(cls, session, config):
        op, credential = config.operation, session.credential
        seller_ops = {"get_shop", "list_shop_offers", "create_offer", "replace_offer", "delete_offer", "get_offer_import"}
        if op in seller_ops:
            cls._seller(session)
        shop = await cls._shop(session) if credential.role == "seller" else None
        seller_params = {"shop_id": credential.shop_id} if shop else {}
        if op == "get_shop" or op == "get_access_scope" and shop:
            return {"items": [shop], "returned_count": 1, "shop_verified": True,
                "marketplace_id": credential.marketplace_id, "marketplace_id_verified": False}
        if op == "get_access_scope":
            raw = await session.request("GET", "/api/orders", params={"shop_ids": str(credential.shop_id), "max": 1, "offset": 0})
            result = _collection(raw, "orders", "order", limit=1, offset=0, shop_id=credential.shop_id, require_shop=True)
            return {**result, "shop_verified": False, "marketplace_id": credential.marketplace_id,
                "marketplace_id_verified": False, "access_probe": "protected_order_metadata"}
        if op == "list_categories":
            params = {**seller_params, "max_level": config.max_level}
            if config.hierarchy is not None:
                params["hierarchy"] = config.hierarchy
            raw = await session.request("GET", "/api/hierarchies", params=params)
            return _collection(raw, "hierarchies", "category")
        if op == "list_product_attributes":
            # The hierarchy value is checked through the native category contract.
            categories = await session.request("GET", "/api/hierarchies", params={**seller_params, "hierarchy": config.hierarchy, "max_level": 0})
            parents = _collection(categories, "hierarchies", "category")
            if not any(row["code"] == config.hierarchy for row in parents["items"]):
                raise ValueError("The selected category is unavailable in this marketplace")
            raw = await session.request("GET", "/api/products/attributes", params={**seller_params, "hierarchy": config.hierarchy, "max_level": config.max_level})
            return _collection(raw, "attributes", "attribute")
        static = {"list_channels": ("/api/channels", "channels", "channel"),
            "list_currencies": ("/api/currencies", "currencies", "currency"),
            "list_locales": ("/api/locales", "locales", "locale"),
            "list_offer_states": ("/api/offers/states", "offer_states", "state")}
        if op in static:
            path, key, kind = static[op]
            return _collection(await session.request("GET", path, params=seller_params), key, kind)
        if op == "get_values_list":
            raw = await session.request("GET", "/api/values_lists", params={**seller_params, "code": config.code})
            result = _collection(raw, "values_lists", "values", limit=1)
            if len(result["items"]) != 1 or result["items"][0]["code"] != config.code:
                raise ValueError("The selected values list is unavailable")
            values = raw["values_lists"][0].get("values")
            if not isinstance(values, list) or len(values) > 500:
                raise ValueError("Mirakl returned an unbounded values list")
            result["items"][0]["values"] = [_record(row, "values") for row in values]
            return result
        if op == "get_products":
            references = {(row.type, row.value) for row in config.references}
            if len(references) != len(config.references):
                raise ValueError("Use distinct product references")
            raw = await session.request("GET", "/api/products", params={**seller_params,
                "product_references": ",".join(row.type + "|" + row.value for row in config.references)})
            result = _collection(raw, "products", "product", limit=100)
            if any((row.get("product_id_type"), row.get("product_id")) not in references for row in result["items"]):
                raise ValueError("Mirakl returned an unrequested product reference")
            return result
        if op == "list_shop_offers":
            params = {**seller_params, "max": config.limit, "offset": config.offset}
            if config.sku is not None:
                params["sku"] = config.sku
            result = _collection(await session.request("GET", "/api/offers", params=params),
                "offers", "offer", limit=config.limit, offset=config.offset)
            if config.sku is not None and any(row.get("shop_sku") != config.sku for row in result["items"]):
                raise ValueError("Mirakl returned an unrequested offer SKU")
            return result
        if op == "get_offer":
            # P11 explicitly accepts shop_ids for either role. Do not expose a
            # direct operator OF22 record before this native shop-parent check.
            parents = await cls._product_offers(session, config.product_sku)
            if not any(row["offer_id"] == config.offer_id for row in parents):
                raise ValueError("The selected offer is not in the bounded product/shop result")
            row = _record(await session.request("GET", "/api/offers/" + str(config.offer_id), params=seller_params),
                "offer", expected=config.offer_id)
            if row.get("product_sku") != config.product_sku:
                raise ValueError("Mirakl returned a different offer product")
            return row
        if op == "list_orders":
            params = {**seller_params, "max": config.limit, "offset": config.offset}
            if not shop:
                params["shop_ids"] = str(credential.shop_id)
            if config.order_id:
                params["order_ids"] = config.order_id
            result = _collection(await session.request("GET", "/api/orders", params=params),
                "orders", "order", limit=config.limit, offset=config.offset,
                shop_id=credential.shop_id, require_shop=not bool(shop))
            if config.order_id and any(row["order_id"] != config.order_id for row in result["items"]):
                raise ValueError("Mirakl returned a different order")
            return result
        if op in {"create_offer", "replace_offer", "delete_offer"}:
            existing = await cls._sku_offer(session, config.shop_sku)
            if op == "create_offer":
                if existing is not None:
                    raise ValueError("An offer already exists for this shop SKU")
                refs = GetProducts(references=[ProductReference(type=config.product_id_type, value=config.product_id)])
                if not (await cls._execute(session, refs))["items"]:
                    raise ValueError("The selected product reference is unavailable")
            elif existing is None or existing["offer_id"] != config.offer_id:
                raise ValueError("The selected offer and SKU are unavailable in the bound shop")
            if op == "delete_offer":
                offer = {"shop_sku": config.shop_sku, "update_delete": "delete"}
            else:
                states = _collection(await session.request("GET", "/api/offers/states", params=seller_params), "offer_states", "state")
                if not any(row["code"] == config.state_code for row in states["items"]):
                    raise ValueError("The selected offer condition is unavailable")
                offer = {key: getattr(config, key) for key in ("shop_sku", "state_code", "price", "quantity",
                    "description", "internal_description", "product_tax_code") if getattr(config, key) is not None}
                offer["update_delete"] = "update"
                if op == "create_offer":
                    offer.update(product_id=config.product_id, product_id_type=config.product_id_type)
            raw = await session.request("POST", "/api/offers", params=seller_params, body={"offers": [offer]}, expected_status=(201,))
            return {"import_id": _id(raw.get("import_id")), "shop_id": credential.shop_id, "operation": op,
                "accepted": True, "completed": False, "readback_verified": False,
                "effect": "offer_deletion" if op == "delete_offer" else "offer_import_with_pricing_and_stock",
                "omitted_fields_reset": op == "replace_offer"}
        if op == "get_offer_import":
            raw = await session.request("GET", "/api/offers/imports/" + str(config.import_id), params=seller_params)
            return {**_record(raw, "import", expected=config.import_id), "readback_verified": False,
                "note": "Import statistics are not a separate offer readback"}
        raise ValueError("Unsupported Mirakl operation")
