"""Loyverse v1.0 personal-token operations.

Contract: https://developer.loyverse.com/docs/API-Reference__v1.0.yaml
Lists return one page and the provider cursor; writes never retry automatically.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.loyverse.com/v1.0"

class LoyverseTokenCredential(BaseModel):
    model_config = ConfigDict(title="Loyverse Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://r.loyverse.com/dashboard/#/integrations/tokens",
        "x-credential-instructions": "Create a personal access token in Loyverse Back Office → Integrations → Access tokens. Paste the token only. Grant read access for the resources you use and write access for customer, category or supplier saves. Store reads verify access to your account; they do not verify write permissions."})
    credential_type: Literal["loyverse_token"] = Field("loyverse_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class ListCustomersConfig(Input):
    """GET /customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    customer_ids: Optional[str] = Field(None, description='Return only customers specified by a comma-separated list of IDs')
    email: Optional[str] = Field(None, description='Filter customers by email')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')

class GetCustomerConfig(Input):
    """GET /customers/{customer_id}."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: UUID

class ListItemsConfig(Input):
    """GET /items."""
    operation: Literal["list_items"] = Field("list_items", json_schema_extra={"ui:hidden": True})
    items_ids: Optional[str] = Field(None, description='Return only items specified by a comma-separated list of IDs')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class GetItemConfig(Input):
    """GET /items/{item_id}."""
    operation: Literal["get_item"] = Field("get_item", json_schema_extra={"ui:hidden": True})
    item_id: UUID

class ListVariantsConfig(Input):
    """GET /variants."""
    operation: Literal["list_variants"] = Field("list_variants", json_schema_extra={"ui:hidden": True})
    variants_ids: Optional[str] = Field(None, description='Return only variants specified by a comma-separated list of IDs')
    items_ids: Optional[str] = Field(None, description='Return only variants attached to specified item ids')
    sku: Optional[str] = Field(None, description='Filter variants by sku')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class GetVariantConfig(Input):
    """GET /variants/{variant_id}."""
    operation: Literal["get_variant"] = Field("get_variant", json_schema_extra={"ui:hidden": True})
    variant_id: UUID

class ListReceiptsConfig(Input):
    """GET /receipts."""
    operation: Literal["list_receipts"] = Field("list_receipts", json_schema_extra={"ui:hidden": True})
    receipt_numbers: Optional[str] = Field(None, description='Return only receipts specified by a comma-separated list of receipt numbers')
    since_receipt_number: Optional[str] = Field(None, description='Show receipts since date which is equal to created_at date of the receipt with specified number')
    before_receipt_number: Optional[str] = Field(None, description='Show receipts up to date which is equal to created_at date of the receipt with specified number')
    store_id: Optional[str] = Field(None, description='Show receipts only for specified store')
    order: Optional[str] = Field(None, description='Filter receipts by order')
    source: Optional[str] = Field(None, description='The name of the the source this receipt comes from')
    updated_at_min: Optional[str] = Field(None, description='Show receipts updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)', json_schema_extra={"format": "date-time"})
    updated_at_max: Optional[str] = Field(None, description='Show receipts updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)', json_schema_extra={"format": "date-time"})
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')

class GetReceiptConfig(Input):
    """GET /receipts/{receipt_number}."""
    operation: Literal["get_receipt"] = Field("get_receipt", json_schema_extra={"ui:hidden": True})
    receipt_number: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class ListStoresConfig(Input):
    """GET /stores."""
    operation: Literal["list_stores"] = Field("list_stores", json_schema_extra={"ui:hidden": True})
    store_ids: Optional[str] = Field(None, description='Return only store specified by a comma-separated list of IDs')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class GetStoreConfig(Input):
    """GET /stores/{store_id}."""
    operation: Literal["get_store"] = Field("get_store", json_schema_extra={"ui:hidden": True})
    store_id: UUID

class ListCategoriesConfig(Input):
    """GET /categories."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})
    categories_ids: Optional[str] = Field(None, description='Return only categories specified by a comma-separated list of IDs')
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class GetCategoryConfig(Input):
    """GET /categories/{category_id}."""
    operation: Literal["get_category"] = Field("get_category", json_schema_extra={"ui:hidden": True})
    category_id: UUID

class ListSuppliersConfig(Input):
    """GET /suppliers/."""
    operation: Literal["list_suppliers"] = Field("list_suppliers", json_schema_extra={"ui:hidden": True})
    suppliers_ids: Optional[str] = Field(None, description='Return only suppliers specified by a comma-separated list of IDs')
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class GetSupplierConfig(Input):
    """GET /suppliers/{supplier_id}."""
    operation: Literal["get_supplier"] = Field("get_supplier", json_schema_extra={"ui:hidden": True})
    supplier_id: UUID

class ListInventoryConfig(Input):
    """GET /inventory."""
    operation: Literal["list_inventory"] = Field("list_inventory", json_schema_extra={"ui:hidden": True})
    store_ids: Optional[str] = Field(None, description='Show inventory levels only for specified stores')
    variant_ids: Optional[str] = Field(None, description='Show inventory levels only for specified variants')
    updated_at_min: Optional[str] = Field(None, description='Show inventory levels updated at or after specified date', json_schema_extra={"format": "date-time"})
    updated_at_max: Optional[str] = Field(None, description='Show inventory levels updated at or before specified date', json_schema_extra={"format": "date-time"})
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')

class ListEmployeesConfig(Input):
    """GET /employees."""
    operation: Literal["list_employees"] = Field("list_employees", json_schema_extra={"ui:hidden": True})
    employee_ids: Optional[str] = Field(None, description='Return only employees specified by a comma-separated list of IDs')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')
    limit: Optional[int] = Field(50, ge=1, le=250, description='Used for pagination')
    cursor: Optional[str] = Field(None, description='Used for pagination')

class ListPaymentTypesConfig(Input):
    """GET /payment_types."""
    operation: Literal["list_payment_types"] = Field("list_payment_types", json_schema_extra={"ui:hidden": True})
    payment_type_ids: Optional[str] = Field(None, description='Return only payment types specified by a comma-separated list of IDs')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class ListTaxesConfig(Input):
    """GET /taxes."""
    operation: Literal["list_taxes"] = Field("list_taxes", json_schema_extra={"ui:hidden": True})
    tax_ids: Optional[str] = Field(None, description='Return only taxes specified by a comma-separated list of IDs')
    created_at_min: Optional[str] = Field(None, description='Show resources created after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    created_at_max: Optional[str] = Field(None, description='Show resources created before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n', json_schema_extra={"format": "date-time"})
    updated_at_min: Optional[str] = Field(None, description='Show resources updated after date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    updated_at_max: Optional[str] = Field(None, description='Show resources updated before date (ISO 8601 format, e.g: 2020-03-30T18:30:00.000Z)\n')
    show_deleted: Optional[bool] = Field(False, description='Show deleted modifiers and modifier options')

class GetMerchantConfig(Input):
    """GET /merchant/."""
    operation: Literal["get_merchant"] = Field("get_merchant", json_schema_extra={"ui:hidden": True})

class SaveCustomerConfig(Input):
    """POST /customers — omit id to create, supply id to update."""
    operation: Literal["save_customer"] = Field("save_customer", json_schema_extra={"ui:hidden": True})
    id: Optional[str] = Field(None, description='The customer id. If included in the POST request it will cause an update instead of a creating a new object.')
    name: str = Field(..., max_length=64, description="The customer's name")
    email: Optional[str] = Field(None, max_length=100, description="The customer's email")
    phone_number: Optional[str] = Field(None, max_length=15, description="The customer's phone number")
    address: Optional[str] = Field(None, max_length=192, description="The customer's address")
    city: Optional[str] = Field(None, max_length=64, description="The customer's city, town, or village.")
    region: Optional[str] = Field(None, max_length=64, description='The customer’s region name. Typically a province, a state, or a prefecture.')
    postal_code: Optional[str] = Field(None, max_length=20, description='The customer’s postal code, also known as zip, postcode, Eircode, etc.')
    country_code: Optional[str] = Field(None, description="The two-letter country code corresponding to the customer's country in ISO 3166-1-alpha-2 format.")
    customer_code: Optional[str] = Field(None, max_length=40)
    note: Optional[str] = Field(None, max_length=255, description='The note about the customer')
    total_points: Optional[float] = Field(None, description='Actual customer points balance')

class SaveCategoryConfig(Input):
    """POST /categories — omit id to create, supply id to update."""
    operation: Literal["save_category"] = Field("save_category", json_schema_extra={"ui:hidden": True})
    id: Optional[str] = Field(None, description='The category id. If included in the POST request it will cause an update instead of a creating a new object.')
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[Literal['GREY', 'RED', 'PINK', 'ORANGE', 'GREEN', 'BLUE', 'PURPLE']] = Field(None)

class SaveSupplierConfig(Input):
    """POST /suppliers/ — omit id to create, supply id to update."""
    operation: Literal["save_supplier"] = Field("save_supplier", json_schema_extra={"ui:hidden": True})
    id: Optional[str] = Field(None, description='The supplier id. If included in the POST request it will cause an update instead of a creating a new object.')
    name: str = Field(..., min_length=1, max_length=64, description='The supplier company name')
    contact: Optional[str] = Field(None, min_length=1, max_length=64, description='The supplier contact person name')
    email: Optional[str] = Field(None, min_length=1, max_length=100, description='The supplier email')
    phone_number: Optional[str] = Field(None, min_length=1, max_length=15)
    website: Optional[str] = Field(None, description='The supplier website page')
    address_1: Optional[str] = Field(None, max_length=192, description='The supplier address')
    address_2: Optional[str] = Field(None, max_length=192, description='The supplier address')
    city: Optional[str] = Field(None, max_length=64, description='The supplier city, town, or village.')
    region: Optional[str] = Field(None, max_length=64, description='The supplier’s region name. Typically a province, a state, or a prefecture.')
    postal_code: Optional[str] = Field(None, max_length=20, description='The supplier’s postal code, also known as zip, postcode, Eircode, etc.')
    country_code: Optional[str] = Field(None, description='The two-letter country code corresponding to the supplier country in ISO 3166-1-alpha-2 format.')
    note: Optional[str] = Field(None, max_length=500)

LoyverseOperation = Annotated[Union[ListCustomersConfig, GetCustomerConfig, ListItemsConfig, GetItemConfig, ListVariantsConfig, GetVariantConfig, ListReceiptsConfig, GetReceiptConfig, ListStoresConfig, GetStoreConfig, ListCategoriesConfig, GetCategoryConfig, ListSuppliersConfig, GetSupplierConfig, ListInventoryConfig, ListEmployeesConfig, ListPaymentTypesConfig, ListTaxesConfig, GetMerchantConfig, SaveCustomerConfig, SaveCategoryConfig, SaveSupplierConfig], Field(discriminator="operation")]

class LoyverseConfig(NodeConfig[LoyverseOperation, LoyverseTokenCredential]):
    pass

ROUTES = {'list_customers': ('GET', '/customers', None), 'get_customer': ('GET', '/customers/{customer_id}', 'customer_id'), 'list_items': ('GET', '/items', None), 'get_item': ('GET', '/items/{item_id}', 'item_id'), 'list_variants': ('GET', '/variants', None), 'get_variant': ('GET', '/variants/{variant_id}', 'variant_id'), 'list_receipts': ('GET', '/receipts', None), 'get_receipt': ('GET', '/receipts/{receipt_number}', 'receipt_number'), 'list_stores': ('GET', '/stores', None), 'get_store': ('GET', '/stores/{store_id}', 'store_id'), 'list_categories': ('GET', '/categories', None), 'get_category': ('GET', '/categories/{category_id}', 'category_id'), 'list_suppliers': ('GET', '/suppliers/', None), 'get_supplier': ('GET', '/suppliers/{supplier_id}', 'supplier_id'), 'list_inventory': ('GET', '/inventory', None), 'list_employees': ('GET', '/employees', None), 'list_payment_types': ('GET', '/payment_types', None), 'list_taxes': ('GET', '/taxes', None), 'get_merchant': ('GET', '/merchant/', None), 'save_customer': ('POST', '/customers', None), 'save_category': ('POST', '/categories', None), 'save_supplier': ('POST', '/suppliers/', None)}

class LoyverseNode(WorkflowNode):
    integration_type = "automation-loyverse"
    connection_evidence = ConnectionEvidence(noun="stores", operation="list_stores", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return LoyverseConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Loyverse personal access token")
        op = self.config.config
        method, path, identifier = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude_unset=method == "POST", exclude={"operation"})
        if identifier:
            path = path.replace("{" + identifier + "}", quote(values.pop(identifier), safe=""))
        token = self.config.credentials.access_token
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": values} if method == "POST" else {"params": values}))
        except httpx.HTTPError:
            raise ValueError("Loyverse request failed; inspect any write before retrying") from None
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code,
                    "error": "Loyverse rejected or could not complete the request",
                    "write_outcome": "unverified" if method == "POST" else None}
        try:
            body = response.json()
            if not isinstance(body, dict) or "errors" in body:
                raise ValueError()
            if op.operation.startswith("list_"):
                key = op.operation[5:]
                if key == "inventory": key = "inventory_levels"
                if not isinstance(body.get(key), list): raise ValueError()
                cursor = body.get("cursor")
                if cursor is not None and not isinstance(cursor, str): raise ValueError()
                result = {"items": body[key], "next_cursor": cursor, "has_more": bool(cursor)}
            else:
                result = {"data": body}
            # Never echo the secret even when upstream includes it in an error or data.
            def redact(value):
                if isinstance(value, str): return value.replace(token, "[redacted]")
                if isinstance(value, list): return [redact(item) for item in value]
                if isinstance(value, dict): return {redact(key): redact(item) for key, item in value.items()}
                return value
            result = redact(result)
        except (ValueError, TypeError):
            raise ValueError("Loyverse returned an unexpected response; inspect any write before retrying") from None
        output = {"status": "success", "http_status": 200, **result}
        await self.emit(output)
        return output
