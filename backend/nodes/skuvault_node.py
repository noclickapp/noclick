"""Native SkuVault catalog and inventory metadata; fixed POST API routes.

Supplied tokens occur only in the documented outbound JSON authentication
fields. Pricing, supplier details, custom attributes, URLs and raw errors are
omitted. No login/token issuance, quantity adjustment or fulfillment action.
"""
from contextvars import ContextVar
from datetime import datetime
import json
import logging
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-skuvault"
FAMILIES = {"skuvault_api_tokens"}
MAX_BYTES, MAX_ROWS = 4_194_304, 10_000
Text = Annotated[StrictStr, Field(min_length=1, max_length=200)]
Strings = Annotated[list[Text], Field(min_length=1, max_length=50)]
WarehouseID = Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]
Utc = Annotated[StrictStr, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?Z$", min_length=20, max_length=28)]


class SkuVaultAPITokensCredential(BaseModel):
    """An existing approved TenantToken/UserToken pair; no login password."""
    model_config = ConfigDict(title="SkuVault API Tokens", extra="ignore", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://dev.skuvault.com/reference/gettokens"})
    credential_type: Literal["skuvault_api_tokens"] = Field("skuvault_api_tokens", json_schema_extra={"ui:hidden": True})
    tenant_token: StrictStr = Field(..., min_length=1, max_length=2048, repr=False, title="Tenant token", json_schema_extra={"ui:widget": "password"})
    user_token: StrictStr = Field(..., min_length=1, max_length=2048, repr=False, title="User token", json_schema_extra={"ui:widget": "password"})

    @field_validator("tenant_token", "user_token")
    @classmethod
    def secret(cls, value):
        if not value.isascii() or value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value) or is_placeholder(value) or is_url_shaped(value):
            raise ValueError("Supply existing SkuVault tokens without placeholders, URLs or whitespace")
        return value


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") not in FAMILIES:
        raise ValueError("Connect native SkuVault API tokens")
    try:
        return SkuVaultAPITokensCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply valid SkuVault API tokens") from None


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_metadata(cls, value, info):
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and (item != item.strip() or any(ord(c) < 32 or ord(c) == 127 for c in item)):
                raise ValueError("Supply metadata without edge whitespace or controls")
        if isinstance(value, list) and len(set(value)) != len(value):
            raise ValueError("Supply each filter value once")
        if info.field_name.endswith("_utc") and value is not None:
            try:
                datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
            except ValueError:
                raise ValueError("Supply a valid UTC timestamp ending in Z") from None
        return value


class _Page(_Config):
    page_number: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 0


class _Window(_Page):
    modified_after_utc: Optional[Utc] = None
    modified_before_utc: Optional[Utc] = None

    @model_validator(mode="after")
    def date_order(self):
        if self.modified_after_utc and self.modified_before_utc and datetime.fromisoformat(self.modified_after_utc.replace("Z", "+00:00")) > datetime.fromisoformat(self.modified_before_utc.replace("Z", "+00:00")):
            raise ValueError("The start timestamp must not follow the end timestamp")
        return self


class _SizedWindow(_Window):
    page_size: Annotated[StrictInt, Field(ge=1000, le=10000)] = Field(1000, description="Vendor minimum 1,000. One page only, with bounded response bytes.")


class SkuVaultListExternalWarehousesConfig(_Config):
    """Read external warehouse IDs, codes and names; no paging parameters."""
    operation: Literal["list_external_warehouses"] = "list_external_warehouses"


class SkuVaultListWarehousesConfig(_Page):
    """Read regular warehouse IDs/codes. Severe throttle: one call per minute."""
    operation: Literal["list_warehouses"] = "list_warehouses"


class SkuVaultListLocationsConfig(_Config):
    """Read location/warehouse metadata and current total quantity; no page fields."""
    operation: Literal["list_locations"] = "list_locations"


class SkuVaultListProductsConfig(_SizedWindow):
    """Read product identifiers/naming and inventory counts without cost or private fields."""
    operation: Literal["list_products"] = "list_products"
    skus: Optional[Strings] = None


class SkuVaultGetProductConfig(_Config):
    """Read a specific product by SKU through the Light-throttle route."""
    operation: Literal["get_product"] = "get_product"
    sku: Text


class SkuVaultListKitsConfig(_Window):
    """Read kit identifiers and bounded component definitions; cost/quantity expansion disabled."""
    operation: Literal["list_kits"] = "list_kits"
    modified_after_utc: Utc = Field(..., description="Required documented UTC window start")
    modified_before_utc: Utc = Field(..., description="Required documented UTC window end")
    skus: Optional[Strings] = None


class SkuVaultListBrandsConfig(_Page):
    """Read one 1,000-record page of brand names/enabled state."""
    operation: Literal["list_brands"] = "list_brands"


class SkuVaultListClassificationsConfig(_Page):
    """Read one 1,000-record page of classification names/enabled state; no custom values."""
    operation: Literal["list_classifications"] = "list_classifications"


class SkuVaultListInventoryByLocationConfig(_Page):
    """Read SKU location/warehouse/count rows with optional SKU filters."""
    operation: Literal["list_inventory_by_location"] = "list_inventory_by_location"
    page_size: Annotated[StrictInt, Field(ge=1000, le=10000)] = 1000
    skus: Optional[Strings] = None


class SkuVaultListItemQuantitiesConfig(_SizedWindow):
    """Read product count metadata; optional filters use product codes, not guessed SKU fields."""
    operation: Literal["list_item_quantities"] = "list_item_quantities"
    codes: Optional[Strings] = None


class SkuVaultListAvailableQuantitiesConfig(_Window):
    """Read available-to-sell counts with alternate SKU rows preserved."""
    operation: Literal["list_available_quantities"] = "list_available_quantities"
    page_size: Annotated[StrictInt, Field(ge=1000, le=5000)] = 1000


class SkuVaultListKitQuantitiesConfig(_Page):
    """Read one 10,000-kit page of available quantities. No undocumented before-date key."""
    operation: Literal["list_kit_quantities"] = "list_kit_quantities"
    modified_after_utc: Optional[Utc] = None


class SkuVaultListWarehouseItemQuantitiesConfig(_SizedWindow):
    """Read SKU quantities from the explicitly requested regular warehouse."""
    operation: Literal["list_warehouse_item_quantities"] = "list_warehouse_item_quantities"
    warehouse_id: WarehouseID = Field(..., description="Numeric regular warehouse ID from list_warehouses; external IDs are a separate family")


class SkuVaultGetWarehouseItemQuantityConfig(_Config):
    """Read total quantity for one SKU in the explicitly requested regular warehouse."""
    operation: Literal["get_warehouse_item_quantity"] = "get_warehouse_item_quantity"
    warehouse_id: WarehouseID
    sku: Text


class SkuVaultListExternalWarehouseQuantitiesConfig(_Page):
    """Read quantities for one external warehouse; total-FBA aggregation is disabled."""
    operation: Literal["list_external_warehouse_quantities"] = "list_external_warehouse_quantities"
    warehouse_id: WarehouseID = Field(..., description="Numeric external warehouse ID from list_external_warehouses; regular IDs are a separate family")
    page_size: Annotated[StrictInt, Field(ge=1000, le=10000)] = Field(1000, description="Node cap 10,000; documented vendor range 1,000–100,000")


class SkuVaultProductMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    description: Optional[Annotated[StrictStr, Field(min_length=1, max_length=1000)]] = None
    short_description: Optional[Annotated[StrictStr, Field(min_length=1, max_length=1000)]] = None
    part_number: Optional[Text] = None
    code: Optional[Text] = None
    brand: Optional[Text] = None
    classification: Optional[Text] = None

    @field_validator("*", mode="after")
    @classmethod
    def text(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use metadata without controls")
        return value


class SkuVaultCreateProductConfig(_Config):
    """Create a catalog product with existing classification/supplier/brand; no price or stock writes."""
    operation: Literal["create_product"] = "create_product"
    sku: Text
    classification: Text
    supplier: Text
    brand: Text
    metadata: Optional[SkuVaultProductMetadata] = None

    @model_validator(mode="after")
    def no_conflicting_parent(self):
        if self.metadata and (self.metadata.brand is not None or self.metadata.classification is not None):
            raise ValueError("Set the required brand/classification in their parent fields")
        return self


class SkuVaultUpdateProductConfig(_Config):
    """Update selected product metadata. Omitted fields stay untouched; explicit clear flags send blanks."""
    operation: Literal["update_product"] = "update_product"
    sku: Text
    metadata: Optional[SkuVaultProductMetadata] = None
    clear_description: StrictBool = False
    clear_short_description: StrictBool = False
    clear_part_number: StrictBool = False

    @model_validator(mode="after")
    def changes(self):
        fields = self.metadata.model_dump(exclude_none=True) if self.metadata else {}
        clearing = [name for name in ("description", "short_description", "part_number") if getattr(self, "clear_" + name)]
        if not fields and not clearing:
            raise ValueError("Supply metadata changes or explicit clear flags")
        if any(name in fields for name in clearing):
            raise ValueError("Choose a value or its clear flag, not both")
        return self


SkuVaultConfig = Annotated[Union[SkuVaultListExternalWarehousesConfig, SkuVaultListWarehousesConfig, SkuVaultListLocationsConfig, SkuVaultListProductsConfig, SkuVaultGetProductConfig, SkuVaultListKitsConfig, SkuVaultListBrandsConfig, SkuVaultListClassificationsConfig, SkuVaultListInventoryByLocationConfig, SkuVaultListItemQuantitiesConfig, SkuVaultListAvailableQuantitiesConfig, SkuVaultListKitQuantitiesConfig, SkuVaultListWarehouseItemQuantitiesConfig, SkuVaultGetWarehouseItemQuantityConfig, SkuVaultListExternalWarehouseQuantitiesConfig, SkuVaultCreateProductConfig, SkuVaultUpdateProductConfig], Field(discriminator="operation")]


class SkuVaultNodeConfig(NodeConfig):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    config: SkuVaultConfig
    credentials: Optional[SkuVaultAPITokensCredential] = Field(None, description="Use an existing approved tenant/user token pair.")


_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("skuvault_private_request", default=False)


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
            raise ValueError("SkuVault returned duplicate JSON properties")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("SkuVault returned non-finite JSON")


# Closed actual operation routes. The method is always POST, including reads.
ROUTES = {
    "list_external_warehouses": ("inventory/getExternalWarehouses", "Warehouses", "external_warehouse", None),
    "list_warehouses": ("inventory/getWarehouses", "Warehouses", "warehouse", None),
    "list_locations": ("inventory/getLocations", "Items", "location", None),
    "list_products": ("products/getProducts", "Products", "product", "configured"),
    "get_product": ("products/getProduct", "Product", "product", None),
    "list_kits": ("products/getKits", "Kits", "kit", None),
    "list_brands": ("products/getBrands", "Brands", "named", 1000),
    "list_classifications": ("products/getClassifications", "Classifications", "named", 1000),
    "list_inventory_by_location": ("inventory/getInventoryByLocation", "Items", "location_inventory", "configured"),
    "list_item_quantities": ("inventory/getItemQuantities", "Items", "item_quantity", "configured"),
    "list_available_quantities": ("inventory/getAvailableQuantities", "Items", "available_quantity", "configured"),
    "list_kit_quantities": ("inventory/getKitQuantities", "Kits", "kit_quantity", 10000),
    "list_warehouse_item_quantities": ("inventory/getWarehouseItemQuantities", "ItemQuantities", "warehouse_quantity", "configured"),
    "get_warehouse_item_quantity": ("inventory/getWarehouseItemQuantity", "TotalQuantityOnHand", "single_quantity", None),
    "list_external_warehouse_quantities": ("inventory/getExternalWarehouseQuantities", "Quantities", "external_quantity", "configured"),
    "create_product": ("products/createProduct", None, "write", None),
    "update_product": ("products/updateProduct", None, "write", None),
}
PRODUCT_FIELDS = ("Id", "Sku", "Code", "PrimarySku", "PartNumber", "Description", "ShortDescription", "Brand", "Classification", "CreatedDateUtc", "ModifiedDateUtc", "IsAlternateSKU", "IsAlternateCode", "QuantityOnHand", "QuantityOnHold", "QuantityPicked", "QuantityPending", "QuantityAvailable", "QuantityIncoming", "QuantityInbound", "QuantityTransfer", "QuantityInStock", "QuantityTotalFBA")
FIELDS = {
    "warehouse": ("Id", "Code"), "external_warehouse": ("Id", "Code", "Name"),
    "location": ("WarehouseCode", "WarehouseName", "LocationCode", "ContainerCode", "ParentLocation", "TotalQuantity"),
    "product": PRODUCT_FIELDS, "named": ("Name", "IsEnabled"),
    "kit": ("SKU", "Code", "Description", "LastModifiedDateTimeUtc"),
    "location_inventory": ("LocationCode", "Quantity", "Reserve", "WarehouseCode"),
    "item_quantity": ("Sku", "Code", "AvailableQuantity", "HeldQuantity", "PendingQuantity", "PickedQuantity", "TotalOnHand", "LastModifiedDateTimeUtc"),
    "available_quantity": ("Sku", "AvailableQuantity", "IsAlternateSku", "LastModifiedDateTimeUtc"),
    "kit_quantity": ("Sku", "AvailableQuantity", "LastModifiedDateTimeUtc"),
    "warehouse_quantity": ("Sku", "Quantity"),
    "external_quantity": ("Sku", "InStockQuantity", "InboundQuantity", "ReserveQuantity", "TotalQuantity", "TransferQuantity"),
}
BOOL_FIELDS = {"IsEnabled", "IsAlternateSKU", "IsAlternateSku", "IsAlternateCode", "Reserve"}
INT_FIELDS = {"Quantity", "TotalOnHand", "Combine"} | {key for fields in FIELDS.values() for key in fields if "Quantity" in key}


def _text(value, maximum=1000):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("SkuVault returned invalid text metadata")
    return value


def _integer(value):
    if type(value) is not int or not -9_007_199_254_740_991 <= value <= 9_007_199_254_740_991:
        raise ValueError("SkuVault returned invalid integer metadata")
    return value


def _project(raw, kind):
    if not isinstance(raw, dict):
        raise ValueError("SkuVault returned invalid record metadata")
    result = {}
    for key in FIELDS[kind]:
        value = raw.get(key)
        if value is None:
            continue
        if key in BOOL_FIELDS:
            if type(value) is not bool:
                raise ValueError("SkuVault returned invalid boolean metadata")
        elif key in INT_FIELDS:
            value = _integer(value)
        else:
            value = _text(value)
        result[key] = value
    identity = "Name" if kind == "named" else "SKU" if kind == "kit" else "Id" if "warehouse" in kind and kind in {"warehouse", "external_warehouse"} else "LocationCode" if kind in {"location", "location_inventory"} else "Sku"
    if not result.get(identity):
        raise ValueError("SkuVault returned metadata without its documented identifier")
    if kind == "kit":
        lines = raw.get("KitLines", [])
        if not isinstance(lines, list) or len(lines) > 100:
            raise ValueError("SkuVault returned unbounded kit lines")
        result["KitLines"] = []
        for line in lines:
            if not isinstance(line, dict) or not isinstance(line.get("Items"), list) or len(line["Items"]) > 100:
                raise ValueError("SkuVault returned invalid kit components")
            components = []
            for item in line["Items"]:
                if not isinstance(item, dict) or not item.get("SKU"):
                    raise ValueError("SkuVault returned an invalid kit component")
                components.append({key: _text(item[key]) for key in ("SKU", "Code", "Description") if item.get(key) is not None})
            result["KitLines"].append({"LineName": _text(line.get("LineName", "")), "Quantity": _integer(line.get("Quantity")), "Combine": _integer(line.get("Combine")), "Items": components})
    return result


class SkuVaultRateLimited(ValueError):
    def __init__(self, headers):
        values = {}
        for header, key in (("X-RateLimit-Reset", "retry_after_ms"), ("X-RateLimit-Limit", "limit_per_minute"), ("X-RateLimit-Remaining", "remaining")):
            raw = headers.get(header)
            if isinstance(raw, str) and raw.isdecimal() and len(raw) <= 12:
                values[key] = int(raw)
        self.metadata = values
        super().__init__("SkuVault rate limit reached; no automatic retry" + ("; wait " + str(values["retry_after_ms"]) + " milliseconds" if "retry_after_ms" in values else ""))


class _Client:
    def __init__(self, credential):
        self.credential = credential

    async def request(self, operation, body):
        if operation not in ROUTES or not isinstance(body, dict) or {"TenantToken", "UserToken"} & body.keys():
            raise ValueError("Unsupported SkuVault request")
        payload = {**body, "TenantToken": self.credential.tenant_token, "UserToken": self.credential.user_token}
        if len(json.dumps(payload, allow_nan=False).encode()) > 65_536:
            raise ValueError("SkuVault metadata request is too large")
        token = _PRIVATE_REQUEST.set(True)
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=25.0) as client:
                async with client.stream("POST", "https://app.skuvault.com/api/" + ROUTES[operation][0], json=payload, headers={"Accept": "application/json"}) as response:
                    if response.status_code in (401, 403, 404):
                        raise _AuthRefused(f"SkuVault authentication failed or permission denied (HTTP {response.status_code})")
                    if response.status_code == 429:
                        raise SkuVaultRateLimited(response.headers)
                    if response.status_code != 200:
                        raise ValueError(f"SkuVault request did not complete (HTTP {response.status_code}); no automatic retry")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("SkuVault returned an unsupported response format")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES:
                            raise ValueError("SkuVault response exceeds the bounded limit")
                        data.extend(chunk)
                    try:
                        raw = json.loads(data, object_pairs_hook=_unique, parse_constant=_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("SkuVault returned invalid JSON metadata") from None
        except (httpx.HTTPError, SSRFError):
            raise ValueError("SkuVault HTTPS metadata request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(token)
        if not isinstance(raw, dict) or ("Errors" in raw and (not isinstance(raw["Errors"], list) or raw["Errors"])) or ("Status" in raw and raw["Status"] != "OK") or any(raw.get(key) for key in ("Error", "ExceptionMessage")) or ("Success" in raw and raw["Success"] is not True):
            raise ValueError("SkuVault returned a failed provider response; no automatic retry")
        if operation in ("create_product", "update_product") and (raw.get("Status") != "OK" or raw.get("Errors") != []):
            raise ValueError("SkuVault did not acknowledge the metadata change")
        return raw


class SkuVaultNode(WorkflowNode):
    integration_type = NODE_TYPE
    connection_evidence = ConnectionEvidence(noun="external warehouses", operation="list_external_warehouses", label_keys=("Name", "Code"), proves="account")

    @classmethod
    def get_config_model(cls):
        return SkuVaultNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if raw is not None:
            _credential(raw)
        return super().parse_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Tokens do not rotate. Stored credentials are resolved by staging's
        # shared loaders before this hook or execute is called.
        return _credential(credential_data).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data):
        await _Client(_credential(credential_data)).request("list_external_warehouses", {})
        return {"valid": True}

    async def execute(self, inputs):
        if not isinstance(self.config, SkuVaultNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect SkuVault API credentials")
        credential = self.config.credentials
        result = await self._execute(_Client(credential), self.config.config)
        projected = json.dumps(result, ensure_ascii=False)
        if any(secret in projected for secret in (credential.tenant_token, credential.user_token)):
            raise ValueError("SkuVault returned credential material in metadata")
        return {"status": "success", "data": result}

    async def _execute(self, client, config):
        operation = config.operation
        body = {}
        for field_name, wire in (("page_number", "PageNumber"), ("page_size", "PageSize"), ("modified_after_utc", "ModifiedAfterDateTimeUtc"), ("modified_before_utc", "ModifiedBeforeDateTimeUtc"), ("warehouse_id", "WarehouseId"), ("sku", "ProductSKU")):
            value = getattr(config, field_name, None)
            if value is not None:
                body[wire] = value
        if operation == "list_warehouse_item_quantities":
            body["PageSize"] = str(config.page_size)  # This endpoint's current schema declares string.
        if operation == "get_warehouse_item_quantity":
            body["Sku"] = body.pop("ProductSKU")
        if getattr(config, "skus", None):
            body["KitSKUs" if operation == "list_kits" else "ProductSKUs"] = config.skus
        if getattr(config, "codes", None):
            body["ProductCodes"] = config.codes
        if operation == "list_inventory_by_location":
            body["IsReturnByCodes"] = False
        if operation == "list_available_quantities":
            body["ExpandAlternateSkus"] = False
        if operation == "list_external_warehouse_quantities":
            body["GetTotalFbaQuantities"] = False
        if operation == "list_kits":
            body.update({"GetAvailableQuantity": False, "IncludeKitCost": False})
        if operation in ("create_product", "update_product"):
            if operation == "update_product":
                existing = _project((await client.request("get_product", {"ProductSKU": config.sku})).get("Product"), "product")
                if existing["Sku"] != config.sku:
                    raise ValueError("SkuVault returned a different product")
            body = {"Sku": config.sku}
            if config.metadata:
                mapping = {"description": "Description", "short_description": "ShortDescription", "part_number": "PartNumber", "code": "Code", "brand": "Brand", "classification": "Classification"}
                body.update({mapping[key]: value for key, value in config.metadata.model_dump(exclude_none=True).items()})
            if operation == "create_product":
                body.update({"Classification": config.classification, "Supplier": config.supplier, "Brand": config.brand})
            else:
                for key, wire in (("description", "Description"), ("short_description", "ShortDescription"), ("part_number", "PartNumber")):
                    if getattr(config, "clear_" + key):
                        body[wire] = ""
            await client.request(operation, body)
            return {"sku": config.sku, "accepted": True, "http_status": 200, "readback_verified": False}
        raw = await client.request(operation, body)
        _, collection, kind, size = ROUTES[operation]
        value = raw.get(collection)
        if operation == "get_warehouse_item_quantity":
            return {"requested_warehouse_id": config.warehouse_id, "sku": config.sku, "TotalQuantityOnHand": _integer(value)}
        if operation == "get_product":
            record = _project(value, "product")
            if record["Sku"] != config.sku:
                raise ValueError("SkuVault returned a different product")
            return record
        if kind == "location_inventory":
            if not isinstance(value, dict) or len(value) > config.page_size:
                raise ValueError("SkuVault returned invalid or unbounded SKU-location metadata")
            records = []
            for sku, locations in value.items():
                _text(sku, 200)
                if not sku or not isinstance(locations, list) or len(locations) > MAX_ROWS:
                    raise ValueError("SkuVault returned invalid location metadata")
                for location in locations:
                    records.append({"Sku": sku, **_project(location, kind)})
                    if len(records) > MAX_ROWS:
                        raise ValueError("SkuVault location expansion exceeds the bounded limit")
            page_count = len(value)
        else:
            if not isinstance(value, list) or len(value) > MAX_ROWS:
                raise ValueError("SkuVault returned invalid or unbounded collection metadata")
            records = [_project(row, kind) for row in value]
            page_count = len(value)
        if getattr(config, "skus", None) and any(row.get("SKU", row.get("Sku")) not in config.skus for row in records):
            raise ValueError("SkuVault returned a product outside the requested SKU filter")
        if getattr(config, "codes", None) and any(row.get("Code") not in config.codes for row in records):
            raise ValueError("SkuVault returned a product outside the requested code filter")
        page_size = config.page_size if size == "configured" else size
        if isinstance(page_size, int) and page_count > page_size:
            raise ValueError("SkuVault returned more records than the documented page size")
        paged = hasattr(config, "page_number")
        has_more = False if not paged or page_count == 0 or isinstance(page_size, int) and page_count < page_size else None
        result = {"items": records, "returned_count": len(records), "page_record_count": page_count, "has_more": has_more, "next_page_number": config.page_number + 1 if paged and has_more is None else None}
        if paged:
            result["page_number"] = config.page_number
        if getattr(config, "warehouse_id", None) is not None:
            result["requested_warehouse_id"] = config.warehouse_id  # Body binding, not an identity proof.
        return result
