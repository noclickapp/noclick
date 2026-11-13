"""Printify / Printful Enterprise shop, catalog and product metadata.

This shared API is distinct from the traditional api.printful.com transport.
No publishing, orders, fulfillment, artwork, price or stock mutations.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, Discriminator, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

BASES = {
    "printify": "https://api.printify.com/v1",
    "printful_enterprise": "https://enterprise.printful.com/api/pfy/public/v1",
}
TYPES = ("printify_pat", "printify_oauth_access_token")
MAX_BYTES = 2 * 1024 * 1024
MAX_CATALOG = 1000


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError("Use a positive numeric Printify ID")
    return str(value)


def product_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Use the product ID returned by this shop; URLs and paths are unsupported")
    return value


NumericID = Annotated[str, BeforeValidator(positive_id)]
ProductID = Annotated[str, BeforeValidator(product_id)]
Brand = Literal["printify", "printful_enterprise"]


class PrintifyPATCredential(BaseModel):
    credential_type: Literal["printify_pat"] = Field("printify_pat", json_schema_extra={"ui:hidden": True})
    brand: Brand = Field("printify", title="API brand", description="Printful Enterprise uses this shared API; traditional Printful credentials use a different integration.")
    personal_access_token: str = Field(..., min_length=1, max_length=3000, repr=False, title="Personal Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore", json_schema_extra={
        "x-credential-url": "https://developers.printify.com/#create-a-personal-access-token",
        "x-credential-instructions": "Generate a personal token in Profile → Connections. Select shops.read and the catalog/product scopes needed by your operations. Personal tokens expire after one year. Token contents and actual granted scopes are not inferred.",
    })

    @model_validator(mode="before")
    @classmethod
    def shaped_family(cls, value):
        # The manual shaper selects this exact class from the authenticated
        # credential_type argument. Keep its hidden literal in exclude_unset.
        return {"credential_type": "printify_pat", **value} if isinstance(value, dict) else value

    @field_validator("personal_access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Use a token string")
        value = clean_secret(value)
        if re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Use a token without whitespace or controls")
        return value


class PrintifyOAuthAccessTokenCredential(BaseModel):
    credential_type: Literal["printify_oauth_access_token"] = Field("printify_oauth_access_token", json_schema_extra={"ui:hidden": True})
    brand: Brand = Field("printify", title="API brand")
    access_token: str = Field(..., min_length=1, max_length=3000, repr=False, title="OAuth Access Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., max_length=128, title="Token expiry", description="Actual expiry returned by the approved platform's token exchange, with timezone. Access tokens expire after six hours; replace the token when expired.")
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore", json_schema_extra={
        "x-credential-url": "https://developers.printify.com/#oauth-2-0",
        "x-credential-instructions": "Supply a current access token from your vendor-approved platform app. This connection does not register a platform app, authorize a merchant or refresh a token. Do not paste a refresh token or app ID as the access token. Requested scopes are distinct from actual grants.",
    })

    @model_validator(mode="before")
    @classmethod
    def shaped_family(cls, value):
        return {"credential_type": "printify_oauth_access_token", **value} if isinstance(value, dict) else value
    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        return PrintifyPATCredential.token(value)

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise ValueError("Use the actual expiry timestamp with a timezone") from None
        if parsed.tzinfo is None:
            raise ValueError("Token expiry must include its timezone")
        return parsed.isoformat()


# Plain credential union matches the actual credential UI's anyOf/$ref shape.
# Literal families and the raw/current-row gates prevent cross-family coercion.
Credential = Union[PrintifyPATCredential, PrintifyOAuthAccessTokenCredential]


def credential_value(raw, *, manual=False):
    from pydantic import TypeAdapter
    if isinstance(raw, (PrintifyPATCredential, PrintifyOAuthAccessTokenCredential)):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raise ValueError("Connect a typed Printify token")
    data = dict(raw)
    # The shared manual-connect shaper returns only supplied fields. Infer a
    # literal only at that unsaved shaping/loader boundary, never raw execution.
    if manual and not data.get("credential_type"):
        if data.get("personal_access_token") and not data.get("access_token"):
            data["credential_type"] = TYPES[0]
        elif data.get("access_token") and not data.get("personal_access_token"):
            data["credential_type"] = TYPES[1]
    if data.get("credential_type") not in TYPES:
        raise ValueError("The current credential family is not Printify")
    try:
        return TypeAdapter(Credential).validate_python(data)
    except ValueError:
        raise ValueError("Use a valid typed Printify token and fixed API brand") from None


def token_of(credential):
    if isinstance(credential, PrintifyOAuthAccessTokenCredential):
        if datetime.fromisoformat(credential.expires_at) <= datetime.now(timezone.utc):
            raise ValueError("Printify OAuth access token expired; replace it through your approved platform")
        return credential.access_token
    return credential.personal_access_token


def picker(field, parent=None):
    extra = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        extra["depends_on"] = parent
    return {"x-dynamic-options": extra}


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListShops(Operation):
    operation: Literal["list_shops"] = Field("list_shops", json_schema_extra={"const": "list_shops", "ui:hidden": True, "x-display-name": "List shops", "x-category": "Shops", "x-is-trigger": False})


class ListBlueprints(Operation):
    operation: Literal["list_blueprints"] = Field("list_blueprints", json_schema_extra={"const": "list_blueprints", "ui:hidden": True, "x-display-name": "List catalog blueprints", "x-category": "Catalog", "x-is-trigger": False})


class BlueprintOperation(Operation):
    blueprint_id: NumericID = Field(..., title="Blueprint", json_schema_extra=picker("blueprint_id"))


class GetBlueprint(BlueprintOperation):
    operation: Literal["get_blueprint"] = Field("get_blueprint", json_schema_extra={"const": "get_blueprint", "ui:hidden": True, "x-display-name": "Get blueprint", "x-category": "Catalog", "x-is-trigger": False})


class GetSizeGuide(BlueprintOperation):
    operation: Literal["get_size_guide"] = Field("get_size_guide", json_schema_extra={"const": "get_size_guide", "ui:hidden": True, "x-display-name": "Get blueprint size guide", "x-category": "Catalog", "x-is-trigger": False})


class ListBlueprintPrintProviders(BlueprintOperation):
    operation: Literal["list_blueprint_print_providers"] = Field("list_blueprint_print_providers", json_schema_extra={"const": "list_blueprint_print_providers", "ui:hidden": True, "x-display-name": "List blueprint print providers", "x-category": "Catalog", "x-is-trigger": False})


class ListPrintProviders(Operation):
    operation: Literal["list_print_providers"] = Field("list_print_providers", json_schema_extra={"const": "list_print_providers", "ui:hidden": True, "x-display-name": "List print providers", "x-category": "Catalog", "x-is-trigger": False})


class GetPrintProvider(Operation):
    operation: Literal["get_print_provider"] = Field("get_print_provider", json_schema_extra={"const": "get_print_provider", "ui:hidden": True, "x-display-name": "Get print provider", "x-category": "Catalog", "x-is-trigger": False})
    print_provider_id: NumericID = Field(..., title="Print provider", json_schema_extra=picker("print_provider_id"))


class ListVariants(BlueprintOperation):
    operation: Literal["list_variants"] = Field("list_variants", json_schema_extra={"const": "list_variants", "ui:hidden": True, "x-display-name": "List blueprint variants", "x-category": "Catalog", "x-is-trigger": False})
    blueprint_print_provider_id: NumericID = Field(..., title="Blueprint print provider", json_schema_extra=picker("blueprint_print_provider_id", "blueprint_id"))
    show_out_of_stock: bool = Field(False, title="Include out of stock variants")


class ShopOperation(Operation):
    shop_id: NumericID = Field(..., title="Shop", json_schema_extra=picker("shop_id"))


class ListProducts(ShopOperation):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"const": "list_products", "ui:hidden": True, "x-display-name": "List shop products", "x-category": "Products", "x-is-trigger": False})
    page: int = Field(1, ge=1, le=2147483647, title="Page")
    limit: int = Field(10, ge=1, le=50, title="Products per page")


class ProductOperation(ShopOperation):
    product_id: ProductID = Field(..., title="Product", json_schema_extra=picker("product_id", "shop_id"))


class GetProduct(ProductOperation):
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"const": "get_product", "ui:hidden": True, "x-display-name": "Get product metadata", "x-category": "Products", "x-is-trigger": False})


class UpdateProductMetadata(ProductOperation):
    operation: Literal["update_product_metadata"] = Field("update_product_metadata", json_schema_extra={"const": "update_product_metadata", "ui:hidden": True, "x-display-name": "Update product title / description", "x-category": "Products", "x-is-trigger": False, "x-operation-effect": "Changes shop product metadata. Does not call publish or alter prices, variants or artwork."})
    title: str | None = Field(None, min_length=1, max_length=1024, title="New title")
    description: str | None = Field(None, max_length=65535, title="New description", json_schema_extra={"ui:widget": "textarea"})
    clear_description: bool = Field(False, title="Clear description")

    @field_validator("title", "description")
    @classmethod
    def metadata_text(cls, value, info):
        if value is not None and (re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value) or info.field_name == "title" and not value.strip()):
            raise ValueError("Use metadata text without controls and a nonblank title")
        return value

    @model_validator(mode="after")
    def changes(self):
        if self.clear_description and self.description is not None:
            raise ValueError("Choose a description or clear description")
        if self.title is None and self.description is None and not self.clear_description:
            raise ValueError("Provide a title or description change")
        return self


OPERATIONS = (ListShops, ListBlueprints, GetBlueprint, GetSizeGuide, ListBlueprintPrintProviders, ListPrintProviders, GetPrintProvider, ListVariants, ListProducts, GetProduct, UpdateProductMetadata)
PrintifyOperation = Annotated[Union[ListShops, ListBlueprints, GetBlueprint, GetSizeGuide, ListBlueprintPrintProviders, ListPrintProviders, GetPrintProvider, ListVariants, ListProducts, GetProduct, UpdateProductMetadata], Discriminator("operation")]


class PrintifyNodeConfig(NodeConfig[PrintifyOperation, Credential]):
    model_config = ConfigDict(hide_input_in_errors=True)


PRINTIFY_SCOPES = ScopeRegistry("printify", {
    model.model_fields["operation"].default: ScopeRequirement(
        scopes=("shops.read",) if model is ListShops else ("shops.read", "products.read", "products.write") if model is UpdateProductMetadata else ("shops.read", "products.read") if model in (ListProducts, GetProduct) else ("print_providers.read",) if model in (ListPrintProviders, GetPrintProvider) else ("catalog.read",),
        credential_types=TYPES,
        note="Grant these scopes when creating the personal token or registering the approved platform. Supplied tokens do not expose verified scope grants locally.",
    ) for model in OPERATIONS
})


class PrintifyAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"Printify HTTP {status}: request was not confirmed" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


def finite_json(content):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def decimal(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result
    try:
        result = json.loads(bytes(content).decode("utf-8"), object_pairs_hook=pairs, parse_float=decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Printify returned malformed JSON; no partial result accepted") from None
    if not isinstance(result, (dict, list)) or isinstance(result, dict) and any(key in result for key in ("error", "errors")):
        raise ValueError("Printify returned an invalid or error envelope")
    return result


async def fetch(credential_data, method, route, *, params=None, body=None):
    credential = credential_value(credential_data)
    token = token_of(credential)
    if allow_private_hosts():
        raise ValueError("Printify private-host overrides are unsupported")
    if method not in {"GET", "PUT"} or not re.fullmatch(r"/(?:shops|catalog)/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.json|/shops\.json", route):
        raise ValueError("Use a native Printify route")
    try:
        async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, BASES[credential.brand] + route, params=params, headers={"Authorization": "Bearer " + token, "User-Agent": "NoClick Printify integration", "Accept": "application/json", "Content-Type": "application/json;charset=utf-8"}, **({"json": body} if body is not None else {})) as response:
                if response.status_code != 200:
                    retry = response.headers.get("retry-after", "")
                    raise PrintifyAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Printify response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Printify returned a non-JSON response")
                return finite_json(content)
    except SSRFError:
        raise ValueError("Printify destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Printify request could not be completed; no automatic retry") from None


def private_text(value, credential, maximum=1024, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("Printify returned invalid or oversized metadata text")
    token = token_of(credential)
    result = value.replace(token, "[redacted]").replace(quote(token, safe=""), "[redacted]")
    return re.sub(r"(?i)((?:access_token|api_key|token|secret|signature)=)[^\s&#]+", r"\1[redacted]", result)


def records(raw):
    if not isinstance(raw, list) or len(raw) > MAX_CATALOG or any(not isinstance(item, dict) for item in raw):
        raise ValueError("Printify catalog exceeds the 1000-row bound or has invalid records")
    return raw


def provider_id(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Printify returned an invalid numeric ID")
    return positive_id(value)


def strings(raw, credential, *, maximum=100, text_limit=1024):
    if not isinstance(raw, list) or len(raw) > maximum:
        raise ValueError("Printify returned invalid metadata entries")
    return [private_text(value, credential, text_limit) for value in raw]


def project(raw, credential, kind, *, shop=None):
    if not isinstance(raw, dict):
        raise ValueError("Printify returned invalid metadata")
    result = {"id": product_id(raw.get("id")) if kind == "product" else provider_id(raw.get("id")), "title": private_text(raw.get("title"), credential)}
    if kind == "shop":
        result["sales_channel"] = private_text(raw.get("sales_channel"), credential, 256)
    elif kind == "blueprint":
        for key in ("brand", "model"):
            if key in raw:
                result[key] = private_text(raw[key], credential, 256)
        for key in ("tags", "care_instructions"):
            if key in raw:
                result[key] = strings(raw[key], credential)
    elif kind == "provider":
        if "decoration_methods" in raw:
            result["decoration_methods"] = strings(raw["decoration_methods"], credential, maximum=20, text_limit=80)
        if "location" in raw:
            if not isinstance(raw["location"], dict):
                raise ValueError("Printify returned an invalid provider location")
            result["location"] = {key: private_text(raw["location"][key], credential, 256) for key in ("city", "region", "country") if key in raw["location"]}
    elif kind == "product":
        result["shop_id"] = provider_id(raw.get("shop_id"))
        if result["shop_id"] != shop:
            raise ValueError("Printify returned a product outside the selected shop")
        for key in ("blueprint_id", "print_provider_id"):
            if key in raw:
                result[key] = provider_id(raw[key])
        if "description" in raw:
            result["description"] = private_text(raw["description"], credential, 65535, nullable=True)
        if "tags" in raw:
            result["tags"] = strings(raw["tags"], credential)
        for key in ("visible", "is_locked"):
            if key in raw:
                if not isinstance(raw[key], bool):
                    raise ValueError("Printify returned invalid product status")
                result[key] = raw[key]
        for key in ("created_at", "updated_at"):
            if key in raw:
                result[key] = private_text(raw[key], credential, 80)
    return result


async def shops(credential):
    return [project(item, credential, "shop") for item in records(await fetch(credential, "GET", "/shops.json"))]


async def require_shop(credential, shop):
    if shop not in {item["id"] for item in await shops(credential)}:
        raise ValueError("Selected shop is not returned by the current connection")


async def blueprint_providers(credential, blueprint):
    return [project(item, credential, "provider") for item in records(await fetch(credential, "GET", f"/catalog/blueprints/{blueprint}/print_providers.json"))]


async def products_page(credential, config):
    await require_shop(credential, config.shop_id)
    raw = await fetch(credential, "GET", f"/shops/{config.shop_id}/products.json", params={"page": config.page, "limit": config.limit})
    if not isinstance(raw, dict):
        raise ValueError("Printify returned invalid product pagination")
    current, last = raw.get("current_page"), raw.get("last_page")
    if type(current) is not int or type(last) is not int or current != config.page or last < 1 or last > 2147483647 or current > last:
        raise ValueError("Printify did not confirm the requested product page")
    items = records(raw.get("data"))
    if len(items) > config.limit:
        raise ValueError("Printify product page exceeds the requested limit")
    return {"items": [project(item, credential, "product", shop=config.shop_id) for item in items], "page": current, "last_page": last, "next_page": current + 1 if current < last else None}


async def product_record(credential, shop, identity):
    result = project(await fetch(credential, "GET", f"/shops/{shop}/products/{identity}.json"), credential, "product", shop=shop)
    if result["id"] != identity:
        raise ValueError("Printify returned a different product")
    return result


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    if type(config) not in OPERATIONS:
        raise ValueError("Use a typed native Printify operation")
    PRINTIFY_SCOPES.enforce_credential_type(config.operation, credential.credential_type)
    if isinstance(config, ListShops):
        data = {"items": await shops(credential)}
    elif isinstance(config, (ListBlueprints, ListPrintProviders)):
        kind, resource = ("blueprint", "blueprints") if isinstance(config, ListBlueprints) else ("provider", "print_providers")
        data = {"items": [project(item, credential, kind) for item in records(await fetch(credential, "GET", f"/catalog/{resource}.json"))]}
    elif isinstance(config, (GetBlueprint, GetPrintProvider)):
        kind, resource, identity = ("blueprint", "blueprints", config.blueprint_id) if isinstance(config, GetBlueprint) else ("provider", "print_providers", config.print_provider_id)
        data = project(await fetch(credential, "GET", f"/catalog/{resource}/{identity}.json"), credential, kind)
        if data["id"] != identity:
            raise ValueError("Printify returned a different catalog resource")
    elif isinstance(config, ListBlueprintPrintProviders):
        data = {"items": await blueprint_providers(credential, config.blueprint_id)}
    elif isinstance(config, GetSizeGuide):
        raw = await fetch(credential, "GET", f"/catalog/blueprints/{config.blueprint_id}/size_guide.json")
        if not isinstance(raw, dict):
            raise ValueError("Printify returned an invalid size guide")
        sizes = strings(raw.get("sizes"), credential)
        types = []
        for item in records(raw.get("types")):
            ranges = records(item.get("ranges"))
            if len(ranges) != len(sizes):
                raise ValueError("Printify size guide does not align with sizes")
            types.append({"name": private_text(item.get("name"), credential, 256), "units": private_text(item.get("units"), credential, 20), "ranges": [{key: private_text(value.get(key), credential, 80, nullable=True) for key in ("from", "to")} for value in ranges]})
        data = {"blueprint_id": config.blueprint_id, "sizes": sizes, "types": types}
    elif isinstance(config, ListVariants):
        if config.blueprint_print_provider_id not in {item["id"] for item in await blueprint_providers(credential, config.blueprint_id)}:
            raise ValueError("Print provider does not belong to the selected blueprint")
        raw = await fetch(credential, "GET", f"/catalog/blueprints/{config.blueprint_id}/print_providers/{config.blueprint_print_provider_id}/variants.json", params={"show-out-of-stock": int(config.show_out_of_stock)})
        if not isinstance(raw, dict):
            raise ValueError("Printify returned invalid variants")
        if "id" in raw and provider_id(raw["id"]) != config.blueprint_print_provider_id:
            raise ValueError("Printify returned variants for a different provider")
        items = []
        for item in records(raw.get("variants")):
            result = project(item, credential, "variant")
            options = item.get("options")
            if not isinstance(options, dict) or len(options) > 3:
                raise ValueError("Printify returned invalid variant options")
            result["options"] = {private_text(key, credential, 80): private_text(value, credential, 256) for key, value in options.items()}
            result["decoration_methods"] = strings(item.get("decoration_methods", []), credential, maximum=20, text_limit=80)
            items.append(result)
        data = {"blueprint_id": config.blueprint_id, "print_provider_id": config.blueprint_print_provider_id, "items": items}
    elif isinstance(config, ListProducts):
        data = await products_page(credential, config)
    else:
        await require_shop(credential, config.shop_id)
        data = await product_record(credential, config.shop_id, config.product_id)
        if isinstance(config, UpdateProductMetadata):
            if data.get("is_locked") is not False:
                raise ValueError("Product is locked or lock state is unknown; metadata change refused")
            body = {key: getattr(config, key) for key in ("title", "description") if getattr(config, key) is not None}
            if config.clear_description:
                body["description"] = ""
            raw = await fetch(credential, "PUT", f"/shops/{config.shop_id}/products/{config.product_id}.json", body=body)
            data = project(raw, credential, "product", shop=config.shop_id)
            if data["id"] != config.product_id or any(data.get(key) != value for key, value in body.items()):
                raise ValueError("Product change was not confirmed; no automatic retry")
    return {"data": data}


class PrintifyNode(WorkflowNode):
    integration_type = "automation-printify"
    credential_provider_labels = {"printify": "Printify / Printful Enterprise Account"}
    auto_select_credential = False
    scope_registry = PRINTIFY_SCOPES
    # Native operation admission applies to saved credentials. No FIELD probe
    # or synthetic merchant identity; generic catalog rows never prove an account.
    connection_evidence = ConnectionEvidence(operation="list_shops", noun="shops")
    workflow_credential_refresh = True
    edit_examples = ["List my Printify shops", "List products in the selected shop", "Get a blueprint's available print providers", "Update a product description without publishing"]

    @classmethod
    def get_config_model(cls):
        return PrintifyNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("Use a native Printify configuration")
        credential_value(raw.get("credentials"))
        config = raw.get("config", {})
        controls = {"url", "endpoint", "headers", "method", "body", "params", "brand", "token", "api_key", "access_token"}
        if not isinstance(config, dict) or controls.intersection(config) or controls.intersection(raw):
            raise ValueError("Use typed Printify fields; arbitrary API controls and brand overrides are unsupported")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use a typed Printify credential and native fields"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_id:
            if not user_id:
                raise ValueError("Stored Printify credential requires an authorized caller")
            from utils.database_pool import get_native_pool
            from wss.handlers.workflow_handler import get_user_org_context
            from utils.credentials import (
                resolve_accessible_credential_types, resolve_credential_with_owner_fallback,
            )
            pool = pool if pool is not None else get_native_pool()
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
            types = await resolve_accessible_credential_types([credential_id], user_id, pool, organization_id)
            current_type = types.get(credential_id)
            if current_type not in TYPES:
                raise ValueError("Current Printify authority is unavailable or has a different family")
            credential_data = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id)
            if not credential_data or credential_data.get("credential_type") != current_type:
                raise ValueError("Printify credential unavailable, revoked or access denied")
        credential = credential_value(credential_data, manual=not credential_id)
        token_of(credential)
        return credential.model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential = credential_value(credential_data, manual=True)
            token_of(credential)
            await request_operation(credential, ListShops())
        except (ValueError, httpx.HTTPError) as exc:
            return {"valid": False, "error": str(exc)}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"shop_id", "blueprint_id", "print_provider_id", "blueprint_print_provider_id", "product_id"}:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        context = context if isinstance(context, dict) else {}
        parent = positive_id(context.get("shop_id")) if field_name == "product_id" else positive_id(context.get("blueprint_id")) if field_name == "blueprint_print_provider_id" else None
        query = normalize_search(search)
        prefix = hashlib.sha256(json.dumps([credential.brand, token_of(credential), field_name, parent, query], separators=(",", ":")).encode()).hexdigest()[:24] + ":"
        cursor = 1 if field_name == "product_id" else 0
        if page_token is not None:
            if not isinstance(page_token, str) or not page_token.startswith(prefix) or not re.fullmatch(r"[0-9]{1,10}", page_token[len(prefix):]):
                raise ValueError("Picker page belongs to a different connection, parent, field or search")
            cursor = int(page_token[len(prefix):])
        if field_name == "product_id":
            config = ListProducts(shop_id=parent, page=cursor, limit=50)
        else:
            config = ListShops() if field_name == "shop_id" else ListBlueprints() if field_name == "blueprint_id" else ListPrintProviders() if field_name == "print_provider_id" else ListBlueprintPrintProviders(blueprint_id=parent)
        data = (await request_operation(credential, config))["data"]
        options = filter_options_by_search([{"value": item["id"], "label": item["title"], "metadata": {}} for item in data["items"]], query)
        if field_name == "product_id":
            return {"options": options, "next_page_token": prefix + str(data["next_page"]) if data["next_page"] is not None else None}
        if cursor > len(options):
            raise ValueError("Picker offset exceeds the current bounded catalog")
        return {"options": options[cursor:cursor + 100], "next_page_token": prefix + str(cursor + 100) if cursor + 100 < len(options) else None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, PrintifyNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Printify token")
        # Direct callers can supply the validated config separately from node_data.
        # Still inspect any supplied raw fields before executing the typed model.
        self._require_raw({"credentials": self.config.credentials.model_dump(), "config": self.config.config.model_dump(), **(self.node_data or {})})
        credential = await self.freshen_credential(self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"))
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
