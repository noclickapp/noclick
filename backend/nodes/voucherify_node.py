"""Voucherify project-bound customer/catalog/promotion workflows.

Supplied server Application keys only. Validation does not redeem a discount,
but records validation history and consumes API quota. Metadata writes may
trigger project automation; an HTTP acknowledgement is not downstream proof.
"""
from contextvars import ContextVar
import json
import logging
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped

NODE_TYPE = "automation-voucherify"
FAMILIES = {"voucherify_application_keys"}
HOSTS = {"eu": "https://api.voucherify.io", "us": "https://us1.api.voucherify.io", "asia": "https://as1.api.voucherify.io"}
MAX_BYTES = 2_097_152


def _text(value):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use text without control characters")
    return value


def _segment(value):
    _text(value)
    if value != value.strip() or value in (".", "..") or any(c in value for c in "/\\%?#") or is_url_shaped(value):
        raise ValueError("Supply one canonical resource ID or voucher code, not a URL or path")
    return value


Identifier = Annotated[StrictStr, Field(min_length=1, max_length=200), AfterValidator(_segment)]
Text = Annotated[StrictStr, Field(min_length=1, max_length=200), AfterValidator(_text)]
Description = Annotated[StrictStr, Field(max_length=2000), AfterValidator(_text)]
Scalar = Union[StrictStr, StrictBool, StrictInt]


def _metadata(value):
    for key, item in value.items():
        if not key or len(key) > 100 or key != key.strip():
            raise ValueError("Use bounded metadata keys")
        _text(key)
        if isinstance(item, str):
            _text(item)
            if len(item) > 1000:
                raise ValueError("Metadata text is too long")
        elif type(item) is int and abs(item) > 9_007_199_254_740_991:
            raise ValueError("Metadata integer is too large")
    if len(json.dumps(value, allow_nan=False).encode()) > 16_384:
        raise ValueError("Metadata exceeds the bounded limit")
    return value


Metadata = Annotated[dict[StrictStr, Scalar], Field(min_length=1, max_length=50), AfterValidator(_metadata)]
Attributes = Annotated[dict[StrictStr, Scalar], Field(max_length=50), AfterValidator(_metadata)]
AttributeNames = Annotated[list[Text], Field(max_length=50)]


class VoucherifyApplicationKeysCredential(BaseModel):
    """Existing server Application keys for one shared-cluster project."""
    model_config = ConfigDict(title="Voucherify Application Keys", extra="ignore", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.voucherify.io/guides/authentication"})
    credential_type: Literal["voucherify_application_keys"] = Field("voucherify_application_keys", json_schema_extra={"ui:hidden": True})
    region: Literal["eu", "us", "asia"] = Field("eu", title="Project region", description="Europe, US, or Singapore shared cluster. Dedicated custom clusters are not supported.")
    application_id: StrictStr = Field(..., min_length=1, max_length=2048, repr=False, title="Application ID", description="Existing server Application ID. Client-side and management keys are separate families.", json_schema_extra={"ui:widget": "password"})
    application_secret: StrictStr = Field(..., min_length=1, max_length=4096, repr=False, title="Application secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("application_id", "application_secret")
    @classmethod
    def secret(cls, value):
        if not value.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or is_placeholder(value) or is_url_shaped(value):
            raise ValueError("Supply existing server Application keys without placeholders or whitespace")
        return value


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") not in FAMILIES:
        raise ValueError("Connect native Voucherify server Application keys")
    try:
        return VoucherifyApplicationKeysCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply valid Voucherify Application keys and region") from None


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one metadata field")
        return self


class VoucherifyCustomerChanges(_Body):
    name: Optional[Text] = None
    email: Optional[Text] = None
    description: Optional[Description] = None
    metadata: Optional[Metadata] = None


class VoucherifyNewCustomer(VoucherifyCustomerChanges):
    name: Text
    source_id: Text = Field(..., description="Your existing external customer identifier; provider matching may reuse an existing record.")


class VoucherifyProductChanges(_Body):
    name: Optional[Text] = None
    attributes: Optional[AttributeNames] = None
    metadata: Optional[Metadata] = None


class VoucherifyNewProduct(VoucherifyProductChanges):
    name: Text
    source_id: Optional[Text] = None


class VoucherifySKUChanges(_Body):
    sku: Optional[Text] = None
    attributes: Optional[Attributes] = None
    metadata: Optional[Metadata] = None


class VoucherifyNewSKU(VoucherifySKUChanges):
    sku: Text
    source_id: Optional[Text] = None


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("confirm_delete", "confirm_cascade_skus", mode="before", check_fields=False)
    @classmethod
    def confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirm deletion with the boolean true")
        return value


class _Page(_Config):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = Field(25, title="Page size", description="Read one bounded page; no automatic pagination.")
    page: Annotated[StrictInt, Field(ge=1, le=100)] = 1


class _Page99(_Page):
    page: Annotated[StrictInt, Field(ge=1, le=99)] = 1


class VoucherifyListCustomersConfig(_Page99):
    """Read customer IDs/names/email; addresses, phone and custom metadata are omitted."""
    operation: Literal["list_customers"] = "list_customers"


class VoucherifyGetCustomerConfig(_Config):
    """Read one canonical customer ID."""
    operation: Literal["get_customer"] = "get_customer"
    customer_id: Identifier


class VoucherifyCreateCustomerConfig(_Config):
    """Create or match customer metadata; may trigger project automation."""
    operation: Literal["create_customer"] = "create_customer"
    customer: VoucherifyNewCustomer


class VoucherifyUpdateCustomerConfig(_Config):
    """Update selected customer metadata; may trigger project automation."""
    operation: Literal["update_customer"] = "update_customer"
    customer_id: Identifier
    customer: VoucherifyCustomerChanges


class VoucherifyDeleteCustomerConfig(_Config):
    """Soft-delete a customer to the provider bin; not permanent deletion."""
    operation: Literal["delete_customer"] = "delete_customer"
    customer_id: Identifier
    confirm_delete: Literal[True] = Field(..., description="Confirm deleting this existing customer record.")


class VoucherifyListProductsConfig(_Page):
    """Read product metadata without prices, images or custom metadata."""
    operation: Literal["list_products"] = "list_products"


class VoucherifyGetProductConfig(_Config):
    """Read one canonical catalog product."""
    operation: Literal["get_product"] = "get_product"
    product_id: Identifier


class VoucherifyCreateProductConfig(_Config):
    """Create catalog metadata without setting a price or image URL."""
    operation: Literal["create_product"] = "create_product"
    product: VoucherifyNewProduct


class VoucherifyUpdateProductConfig(_Config):
    """Update a product's name, attribute names or metadata."""
    operation: Literal["update_product"] = "update_product"
    product_id: Identifier
    product: VoucherifyProductChanges


class VoucherifyDeleteProductConfig(_Config):
    """Move a product and ALL related SKUs to the provider bin; force permanent deletion is disabled."""
    operation: Literal["delete_product"] = "delete_product"
    product_id: Identifier
    confirm_delete: Literal[True] = Field(..., description="Confirm moving this catalog product to the bin.")
    confirm_cascade_skus: Literal[True] = Field(..., description="Confirm that ALL related SKUs, including concurrently added SKUs, will also move to the bin.")


class VoucherifyListSKUsConfig(_Page):
    """Read a page of SKUs and verify every product association."""
    operation: Literal["list_skus"] = "list_skus"
    product_id: Identifier


class VoucherifyGetSKUConfig(_Config):
    """Read a SKU using the global SKU endpoint and verify its product."""
    operation: Literal["get_sku"] = "get_sku"
    product_id: Identifier
    sku_id: Identifier


class VoucherifyCreateSKUConfig(_Config):
    """Create product-scoped SKU metadata without price, currency or image changes."""
    operation: Literal["create_sku"] = "create_sku"
    product_id: Identifier
    sku: VoucherifyNewSKU


class VoucherifyUpdateSKUConfig(VoucherifyGetSKUConfig):
    """Update a verified product-scoped SKU's ordinary metadata."""
    operation: Literal["update_sku"] = "update_sku"
    sku: VoucherifySKUChanges


class VoucherifyDeleteSKUConfig(VoucherifyGetSKUConfig):
    """Move a verified product-scoped SKU to the provider bin, with permanent deletion disabled."""
    operation: Literal["delete_sku"] = "delete_sku"
    confirm_delete: Literal[True] = Field(..., description="Confirm deletion of this catalog SKU.")


class VoucherifyListCampaignsConfig(_Page):
    """Read campaign names/types/status; no discount, balance or distribution data."""
    operation: Literal["list_campaigns"] = "list_campaigns"


class VoucherifyGetCampaignConfig(_Config):
    """Read one canonical campaign's selected metadata."""
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: Identifier


class VoucherifyUpdateCampaignMetadataConfig(VoucherifyGetCampaignConfig):
    """Update campaign metadata; may trigger asynchronous voucher updates or automation."""
    operation: Literal["update_campaign_metadata"] = "update_campaign_metadata"
    metadata: Metadata


class VoucherifyListVouchersConfig(_Page99):
    """Read vouchers in one verified campaign without balances, holders or assets."""
    operation: Literal["list_vouchers"] = "list_vouchers"
    campaign_id: Identifier


class VoucherifyGetVoucherConfig(_Config):
    """Read a voucher code and verify the campaign association."""
    operation: Literal["get_voucher"] = "get_voucher"
    campaign_id: Identifier
    voucher_code: Identifier = Field(..., description="Existing voucher code; a URL or path is not accepted.")


class VoucherifyUpdateVoucherMetadataConfig(VoucherifyGetVoucherConfig):
    """Update a verified voucher's custom metadata without changing discount or balance."""
    operation: Literal["update_voucher_metadata"] = "update_voucher_metadata"
    metadata: Metadata


class VoucherifyListPromotionTiersConfig(_Config):
    """Read the documented unpaged promotion-tier list for one campaign, bounded to 100 rows."""
    operation: Literal["list_promotion_tiers"] = "list_promotion_tiers"
    campaign_id: Identifier


class VoucherifyGetPromotionTierConfig(_Config):
    """Read a promotion tier and verify its campaign association."""
    operation: Literal["get_promotion_tier"] = "get_promotion_tier"
    campaign_id: Identifier
    promotion_tier_id: Identifier


class VoucherifyValidationRedeemable(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    object: Literal["voucher", "promotion_tier"]
    id: Identifier = Field(..., description="Voucher code or promotion-tier ID, as selected above.")
    campaign_id: Identifier = Field(..., description="Existing campaign association verified before validation.")


class VoucherifyValidateDiscountsConfig(_Config):
    """Validate existing discount coupons/tiers without redemption or a session lock. Records history and uses API quota."""
    operation: Literal["validate_discounts"] = "validate_discounts"
    redeemables: Annotated[list[VoucherifyValidationRedeemable], Field(min_length=1, max_length=10)]
    customer_id: Optional[Identifier] = None
    order_amount: Optional[Annotated[StrictInt, Field(gt=0, le=9_007_199_254_740_991)]] = Field(None, description="Order amount in the smallest currency unit, used only for validation calculation.")

    @model_validator(mode="after")
    def unique(self):
        if len({(r.object, r.id) for r in self.redeemables}) != len(self.redeemables):
            raise ValueError("Use unique redeemables")
        return self


VoucherifyConfig = Annotated[Union[
    VoucherifyListCustomersConfig, VoucherifyGetCustomerConfig, VoucherifyCreateCustomerConfig, VoucherifyUpdateCustomerConfig, VoucherifyDeleteCustomerConfig,
    VoucherifyListProductsConfig, VoucherifyGetProductConfig, VoucherifyCreateProductConfig, VoucherifyUpdateProductConfig, VoucherifyDeleteProductConfig,
    VoucherifyListSKUsConfig, VoucherifyGetSKUConfig, VoucherifyCreateSKUConfig, VoucherifyUpdateSKUConfig, VoucherifyDeleteSKUConfig,
    VoucherifyListCampaignsConfig, VoucherifyGetCampaignConfig, VoucherifyUpdateCampaignMetadataConfig,
    VoucherifyListVouchersConfig, VoucherifyGetVoucherConfig, VoucherifyUpdateVoucherMetadataConfig,
    VoucherifyListPromotionTiersConfig, VoucherifyGetPromotionTierConfig, VoucherifyValidateDiscountsConfig,
], Field(discriminator="operation")]


class VoucherifyNodeConfig(NodeConfig[VoucherifyConfig, VoucherifyApplicationKeysCredential]):
    credentials: Optional[VoucherifyApplicationKeysCredential] = Field(None, description="Connect supplied Voucherify server Application keys for the selected shared region; no environment credential fallback.")


_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("voucherify_private_request", default=False)


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
            raise ValueError("Voucherify returned duplicate JSON properties")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Voucherify returned non-finite JSON metadata")


def _id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise ValueError("Voucherify returned an invalid resource identifier")
    return _segment(value)


def _parent(raw, expected, *, embedded=False):
    candidates = [raw.get("campaign_id")]
    if embedded and raw.get("campaign") is not None:
        if not isinstance(raw["campaign"], dict):
            raise ValueError("Voucherify returned invalid campaign metadata")
        candidates.append(raw["campaign"].get("id"))
    values = [_id(v) for v in candidates if v is not None]
    if not values or any(v != expected for v in values):
        raise ValueError("Voucherify resource does not belong to the requested campaign")
    return expected


FIELDS = {
    "customer": ("source_id", "name", "email", "created_at", "updated_at", "object"),
    "product": ("source_id", "name", "created_at", "updated_at", "object"),
    "sku": ("source_id", "sku", "product_id", "created_at", "updated_at", "object"),
    "campaign": ("name", "campaign_type", "type", "active", "created_at", "updated_at", "start_date", "expiration_date", "creation_status", "vouchers_generation_status", "object"),
    "voucher": ("code", "campaign_id", "type", "active", "created_at", "updated_at", "start_date", "expiration_date", "is_referral_code", "object"),
    "promotion_tier": ("name", "active", "hierarchy", "created_at", "updated_at", "start_date", "expiration_date", "object"),
}


def _record(raw, resource, *, expected_id=None, product_id=None, campaign_id=None, code=None):
    if not isinstance(raw, dict):
        raise ValueError("Voucherify returned invalid resource metadata")
    identifier = _id(raw.get("id"))
    if expected_id is not None and identifier != expected_id:
        raise ValueError("Voucherify returned a different resource")
    if product_id is not None and _id(raw.get("product_id")) != product_id:
        raise ValueError("Voucherify SKU does not belong to the requested product")
    result = {"id": identifier}
    if campaign_id is not None:
        result["campaign_id"] = _parent(raw, campaign_id, embedded=resource == "promotion_tier")
    if code is not None and _id(raw.get("code")) != code:
        raise ValueError("Voucherify returned a different voucher code")
    for key in FIELDS[resource]:
        value = raw.get(key)
        if value is None:
            continue
        if key in ("active", "is_referral_code"):
            if type(value) is not bool:
                raise ValueError("Voucherify returned invalid boolean metadata")
        elif key == "hierarchy":
            if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
                raise ValueError("Voucherify returned invalid tier hierarchy")
        elif not isinstance(value, str) or len(value) > 512:
            raise ValueError("Voucherify returned invalid text metadata")
        else:
            _text(value)
            if key.endswith("_id") or key == "code":
                _id(value)
        result[key] = value
    return result


def _collection(raw, resource, config=None, *, product_id=None, campaign_id=None):
    field = {"customer": "customers", "product": "products", "sku": "skus", "campaign": "campaigns", "voucher": "vouchers", "promotion_tier": "tiers"}[resource]
    refs = {field, "data"} if resource == "sku" else {field}
    if not isinstance(raw, dict) or raw.get("object") != "list" or raw.get("data_ref") not in refs or not isinstance(raw.get(field), list):
        raise ValueError("Voucherify returned an invalid collection envelope")
    rows = raw[field]
    limit = config.limit if config is not None else 100
    total = raw.get("total")
    if len(rows) > limit or ("total" in raw and (type(total) is not int or total < len(rows))) or ("total" not in raw and resource in ("customer", "product", "sku")):
        raise ValueError("Voucherify returned an invalid or unbounded collection")
    records = [_record(row, resource, product_id=product_id, campaign_id=campaign_id) for row in rows]
    if len({row["id"] for row in records}) != len(records):
        raise ValueError("Voucherify returned duplicate resource IDs")
    explicit = raw.get("has_more")
    if "has_more" in raw and type(explicit) is not bool:
        raise ValueError("Voucherify returned invalid pagination metadata")
    has_more = explicit if "has_more" in raw else False if len(rows) < limit else None
    if config is None:
        # The campaign-scoped tier route declares no page or limit parameters.
        return {"items": records, "returned_count": len(records), "total": total, "has_more": explicit if "has_more" in raw else None, "pagination_supported": False}
    cap = 99 if resource in ("customer", "voucher") else 100
    at_cap = config.page == cap
    return {"items": records, "returned_count": len(records), "total": total, "page": config.page, "limit": limit, "has_more": has_more, "next_page": config.page + 1 if not at_cap and has_more is not False else None, "page_cap_reached": at_cap and has_more is not False}


ROUTES = {
    "customers": ("/v1/customers", 0, {"GET", "POST"}),
    "customer": ("/v1/customers/{}", 1, {"GET", "PUT", "DELETE"}),
    "products": ("/v1/products", 0, {"GET", "POST"}),
    "product": ("/v1/products/{}", 1, {"GET", "PUT", "DELETE"}),
    "product_skus": ("/v1/products/{}/skus", 1, {"GET", "POST"}),
    "sku": ("/v1/skus/{}", 1, {"GET"}),
    "product_sku": ("/v1/products/{}/skus/{}", 2, {"PUT", "DELETE"}),
    "campaigns": ("/v1/campaigns", 0, {"GET"}),
    "campaign": ("/v1/campaigns/{}", 1, {"GET", "PUT"}),
    "vouchers": ("/v1/vouchers", 0, {"GET"}),
    "voucher": ("/v1/vouchers/{}", 1, {"GET", "PUT"}),
    "campaign_tiers": ("/v1/promotions/{}/tiers", 1, {"GET"}),
    "promotion_tier": ("/v1/promotions/tiers/{}", 1, {"GET"}),
    "validation": ("/v1/validations", 0, {"POST"}),
}


class _Client:
    def __init__(self, credential):
        self.credential = credential

    async def request(self, method, route, *identifiers, body=None, params=None):
        if route not in ROUTES:
            raise ValueError("Unsupported Voucherify resource")
        template, count, methods = ROUTES[route]
        if method not in methods or len(identifiers) != count:
            raise ValueError("Unsupported Voucherify resource operation")
        path = template.format(*(quote(_id(v), safe="") for v in identifiers))
        if body is not None and len(json.dumps(body, allow_nan=False).encode()) > 32_768:
            raise ValueError("Voucherify metadata request exceeds the bounded limit")
        token = _PRIVATE_REQUEST.set(True)
        try:
            async with httpx.AsyncClient( follow_redirects=False, trust_env=False, timeout=25.0) as client:
                async with client.stream(method, HOSTS[self.credential.region] + path, headers={
                    "Accept": "application/json", "X-App-Id": self.credential.application_id,
                    "X-App-Token": self.credential.application_secret, "X-Voucherify-API-Version": "v2018-08-01",
                }, params=params, **({"json": body} if body is not None else {})) as response:
                    if response.status_code in (401, 403):
                        raise _AuthRefused("Voucherify authentication failed or permission denied")
                    expected = 204 if method == "DELETE" else 200
                    if response.status_code != expected:
                        raise ValueError(f"Voucherify request did not complete (HTTP {response.status_code}); no automatic retry")
                    if method != "DELETE" and response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Voucherify returned an unsupported response format")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES:
                            raise ValueError("Voucherify response exceeds the bounded limit")
                        data.extend(chunk)
                    if method == "DELETE":
                        if data:
                            raise ValueError("Voucherify returned an unexpected delete acknowledgement")
                        return None
                    try:
                        raw = json.loads(data, object_pairs_hook=_unique, parse_constant=_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("Voucherify returned invalid JSON metadata") from None
        except httpx.HTTPError:
            raise ValueError("Voucherify HTTPS request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(token)
        if not isinstance(raw, dict):
            raise ValueError("Voucherify returned an invalid response envelope")
        # Voucher codes are strings. Only an outer numeric error code is an API
        # failure; nested validation-rule errors are a normal business result.
        if type(raw.get("code")) is int and raw["code"] >= 400:
            if raw["code"] in (401, 403):
                raise _AuthRefused("Voucherify authentication failed or permission denied")
            raise ValueError("Voucherify returned a failed API response; no automatic retry")
        return raw


class VoucherifyNode(WorkflowNode):
    integration_type = "automation-voucherify"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns", operation_arguments={"limit": 5}, label_keys=("name",), proves="account")

    @classmethod
    def get_config_model(cls):
        return VoucherifyNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if raw is not None:
            _credential(raw)
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if not isinstance(self.config, VoucherifyNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect Voucherify server Application keys")
        credential = self.config.credentials
        result = await self._execute(_Client(credential), self.config.config)
        projected = json.dumps(result, ensure_ascii=False)
        if any(secret in projected for secret in (credential.application_id, credential.application_secret)):
            raise ValueError("Voucherify returned credential material in metadata")
        return {"status": "success", "data": result}

    async def _execute(self, client, config):
        op = config.operation
        if op == "validate_discounts":
            return await self._validate_discounts(client, config)
        resource = next((noun for noun in FIELDS if op.endswith("_" + noun) or op.endswith("_" + noun + "s") or op == "update_" + noun + "_metadata"), None)
        if op in ("list_skus", "get_sku", "create_sku", "update_sku", "delete_sku"):
            resource = "sku"
        if op in ("list_promotion_tiers", "get_promotion_tier"):
            resource = "promotion_tier"
        if resource is None:
            raise ValueError("Unsupported Voucherify operation")
        product = getattr(config, "product_id", None) if resource == "sku" else None
        campaign = getattr(config, "campaign_id", None) if resource in ("voucher", "promotion_tier") else None
        if product is not None:
            _record(await client.request("GET", "product", product), "product", expected_id=product)
        if campaign is not None:
            _record(await client.request("GET", "campaign", campaign), "campaign", expected_id=campaign)
        if op.startswith("list_"):
            route = "product_skus" if resource == "sku" else "campaign_tiers" if resource == "promotion_tier" else resource + "s"
            identifiers = (product,) if resource == "sku" else (campaign,) if resource == "promotion_tier" else ()
            params = None if resource == "promotion_tier" else {"limit": config.limit, "page": config.page}
            if resource == "voucher":
                params["campaign_id"] = campaign
            return _collection(await client.request("GET", route, *identifiers, params=params), resource, None if resource == "promotion_tier" else config, product_id=product, campaign_id=campaign)
        identifier = getattr(config, "voucher_code", None) if resource == "voucher" else getattr(config, resource + "_id", None)
        if op.startswith("get_"):
            return _record(await client.request("GET", resource, identifier), resource, expected_id=None if resource == "voucher" else identifier, product_id=product, campaign_id=campaign, code=identifier if resource == "voucher" else None)
        if op.startswith("create_"):
            route, ids = ("product_skus", (product,)) if resource == "sku" else (resource + "s", ())
            body = getattr(config, resource).model_dump(exclude_none=True)
            record = _record(await client.request("POST", route, *ids, body=body), resource, product_id=product)
            return {"record": record, "acknowledged": True, "readback_verified": False, "background_completion_verified": False}
        _record(await client.request("GET", resource, identifier), resource, expected_id=None if resource == "voucher" else identifier, product_id=product, campaign_id=campaign, code=identifier if resource == "voucher" else None)
        route, ids = ("product_sku", (product, identifier)) if resource == "sku" else (resource, (identifier,))
        if op.startswith("delete_"):
            await client.request("DELETE", route, *ids, params={"force": "false"} if resource in ("product", "sku") else None)
            return {"id": identifier, "acknowledged": True, "moved_to_bin": True, "absence_verified": False, "permanent_deletion": False, "related_skus_affected": resource == "product"}
        body = {"metadata": config.metadata} if op.endswith("_metadata") else getattr(config, resource).model_dump(exclude_none=True)
        record = _record(await client.request("PUT", route, *ids, body=body), resource, expected_id=None if resource == "voucher" else identifier, product_id=product, campaign_id=campaign, code=identifier if resource == "voucher" else None)
        return {"record": record, "acknowledged": True, "readback_verified": False, "background_completion_verified": False}

    async def _validate_discounts(self, client, config):
        accepted, body_rows, seen = {}, [], set()
        for requested in config.redeemables:
            campaign = _record(await client.request("GET", "campaign", requested.campaign_id), "campaign", expected_id=requested.campaign_id)
            if requested.object == "voucher":
                record = _record(await client.request("GET", "voucher", requested.id), "voucher", campaign_id=campaign["id"], code=requested.id)
                if record.get("type") != "DISCOUNT_VOUCHER":
                    raise ValueError("Validate only discount vouchers, not gift or loyalty balances")
            else:
                record = _record(await client.request("GET", "promotion_tier", requested.id), "promotion_tier", expected_id=requested.id, campaign_id=campaign["id"])
            identity = (requested.object, record["id"])
            if identity in seen:
                raise ValueError("Use distinct canonical redeemables")
            seen.add(identity)
            accepted[(requested.object, requested.id)] = identity
            accepted[identity] = identity
            body_rows.append({"object": requested.object, "id": requested.id})
        body = {"redeemables": body_rows}
        if config.customer_id is not None:
            _record(await client.request("GET", "customer", config.customer_id), "customer", expected_id=config.customer_id)
            body["customer"] = {"id": config.customer_id}
        if config.order_amount is not None:
            body["order"] = {"amount": config.order_amount}
        raw = await client.request("POST", "validation", body=body)
        if type(raw.get("valid")) is not bool or not isinstance(raw.get("redeemables"), list):
            raise ValueError("Voucherify returned an invalid validation result")
        result = {"valid": raw["valid"], "redemption_performed": False, "session_lock_requested": False}
        if raw.get("id") is not None:
            result["id"] = _id(raw["id"])
        returned = set()
        for field in ("redeemables", "skipped_redeemables", "inapplicable_redeemables"):
            if field not in raw:
                continue
            if not isinstance(raw[field], list) or len(raw[field]) > len(config.redeemables):
                raise ValueError("Voucherify returned an unbounded validation result")
            result[field] = []
            for row in raw[field]:
                if not isinstance(row, dict) or row.get("object") not in ("voucher", "promotion_tier") or row.get("status") not in ("APPLICABLE", "INAPPLICABLE", "SKIPPED"):
                    raise ValueError("Voucherify returned invalid redeemable validation metadata")
                key = (row["object"], _id(row.get("id")))
                if key not in accepted or accepted[key] in returned:
                    raise ValueError("Voucherify returned a different or duplicate validation resource")
                returned.add(accepted[key])
                item = {"object": key[0], "id": key[1], "status": row["status"]}
                detail = row.get("result")
                if not isinstance(detail, dict):
                    raise ValueError("Voucherify returned invalid redeemable validation details")
                error = detail.get("error")
                if error is not None:
                    if not isinstance(error, dict):
                        raise ValueError("Voucherify returned invalid validation error metadata")
                    item["error"] = {}
                    if type(error.get("code")) is int:
                        item["error"]["code"] = error["code"]
                    if isinstance(error.get("key"), str) and len(error["key"]) <= 200:
                        item["error"]["key"] = _text(error["key"])
                result[field].append(item)
        return result
