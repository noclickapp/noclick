"""Cin7 Core Inventory v2: one documented request per operation.

Lists return one page and its provider pagination. Writes are never retried;
acknowledgement does not claim downstream fulfilment or a verified readback.
Contract: https://coreapi.cin7.com/openapi.yaml, version 2.0.0.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://inventory.dearsystems.com/ExternalApi/v2"


class Cin7CoreAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cin7 Core API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://inventory.dearsystems.com/ExternalAPI",
            "x-credential-instructions": "In Cin7 Core, open Integrations > API and create an API application. Paste its Account ID and API Application Key. Each company has a different Account ID; both values are secret. The connection reads your company from GET /me. Enable access to the resources your workflow reads or changes."
        })
    credential_type: Literal["cin7_core_api_key"] = Field("cin7_core_api_key", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., title="Account ID", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    application_key: str = Field(..., title="API Application Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("account_id", "application_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Cin7 Core credential")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the credential value without headers or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class NewStockLineModel(Input):
    product_id: UUID | None = Field(None, alias='ProductID', description='Product identifier referenced by this Line. Required if `SKU` is empty.')
    sku: str | None = Field(None, alias='SKU', description='Product SKU referenced by this Line. Required if `ProductID` is empty.', max_length=50, min_length=1)
    quantity: float = Field(..., alias='Quantity', description='New value for QuantityOnHand', strict=True, allow_inf_nan=False)
    unit_cost: float = Field(..., alias='UnitCost', description='Cost of 1 product unit.', strict=True, allow_inf_nan=False)
    location_id: UUID | None = Field(None, alias='LocationID', description='Id of location on which stock changes will be done. Required if `Location` is empty.')
    location: str | None = Field(None, alias='Location', description='Name of location on which stock changes will be done. Required if `LocationID` is empty.', max_length=256, min_length=1)
    batch_sn: str | None = Field(None, alias='BatchSN', description="Batch Serial Number. Required if Product's Costing Method is not `FIFO`.", max_length=50, min_length=1)
    expiry_date: datetime | None = Field(None, alias='ExpiryDate', description="Date when Batch expires. Required if Product's Costing Method is `FESN`")
    received_date: datetime | None = Field(None, alias='ReceivedDate', description='Date when new stock is received')
    comments: str | None = Field(None, alias='Comments', description='Comment', max_length=256)

    @model_validator(mode="after")
    def selectors(self):
        if not (self.product_id or self.sku) or not (self.location_id or self.location):
            raise ValueError("Each stock line needs a product ID or SKU and a location ID or name")
        return self


class SupplierContactModel(Input):
    id: UUID | None = Field(None, alias='ID', description='If passed in `PUT` method, entry will be searched by id, found entry will be updated, otherwise created.')
    name: str = Field(..., alias='Name', description='Name of Contact.', max_length=256, min_length=1)
    phone: str | None = Field(None, alias='Phone', description='Phone', max_length=50)
    mobile_phone: str | None = Field(None, alias='MobilePhone', description='Mobile Phone', max_length=50)
    fax: str | None = Field(None, alias='Fax', description='Fax', max_length=50)
    email: str | None = Field(None, alias='Email', description='Email', max_length=256)
    website: str | None = Field(None, alias='Website', description='Website', max_length=256)
    comment: str | None = Field(None, alias='Comment', description='Comment', max_length=256)
    default: bool | None = Field(None, alias='Default', description='Points that Contact is used as default. `False` as default.', strict=True)
    include_in_email: bool | None = Field(None, alias='IncludeInEmail', description='Points that Contact is included in Email. `false` as default.', strict=True)
    marketing_consent: int | None = Field(None, ge=1, le=3, alias='MarketingConsent', description='Customer’s consent to receive marketing emails and communications. Available values are 1 - Unknown, 2 - Opt in, 3 - Opt out.', strict=True)

class SupplierAddressModel(Input):
    id: UUID | None = Field(None, alias='ID', description='If passed in `PUT` method, entry will be searched by id, found entry will be updated, otherwise created.')
    line1: str = Field(..., alias='Line1', description='Address Line 1.', max_length=256, min_length=1)
    line2: str | None = Field(None, alias='Line2', description='Address Line 2.', max_length=256)
    city: str | None = Field(None, alias='City', description='City / Suburb.', max_length=256)
    state: str | None = Field(None, alias='State', description='State / Province.', max_length=256)
    postcode: str | None = Field(None, alias='Postcode', description='Zip / PostCode.', max_length=20)
    country: str = Field(..., alias='Country', description='Country name', min_length=1)
    type: Literal['Billing', 'Business', 'Shipping'] = Field(..., alias='Type', description='Address Type. Should be one of the following values: `Billing`, `Business` or `Shipping`.', min_length=1)
    default_for_type: bool | None = Field(None, alias='DefaultForType', description='Points that Address is used as default for chosen Type. `False` as default.', strict=True)

class GetMeConfig(Input):
    """GET Me. """
    operation: Literal['get_me'] = Field('get_me', json_schema_extra={"ui:hidden": True})

class ListProductsConfig(Input):
    """GET Product. Returns one provider page."""
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None)
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    name: str | None = Field(None)
    sku: str | None = Field(None)
    modified_since: date | None = Field(None)
    include_deprecated: bool | None = Field(None, strict=True)
    include_bom: bool | None = Field(None, strict=True)
    include_suppliers: bool | None = Field(None, strict=True)
    include_movements: bool | None = Field(None, strict=True)
    include_attachments: bool | None = Field(None, strict=True)
    include_reorder_levels: bool | None = Field(None, strict=True)
    include_custom_prices: bool | None = Field(None, strict=True)

class CreateProductConfig(Input):
    """POST Product. """
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    sku: str = Field(..., description='Product SKU must be unique.', max_length=50, min_length=1)
    name: str = Field(..., description='Product name. Quickbooks Online limitations: maximum length is 100 characters and must be unique', max_length=256, min_length=1)
    category: str = Field(..., description='Category name', max_length=256, min_length=1)
    brand: str | None = Field(None, description='Brand name', max_length=50)
    type: Literal['Stock', 'Service'] = Field(..., description='Product Type. Valid values: `Stock` or `Service`. Read-only for PUT.', min_length=1)
    costing_method: str = Field(..., description='Valid values: `FIFO`, `Special - Batch`, `Special - Serial Number`, `FIFO - Serial Number`, `FIFO - Batch`, `FEFO - Batch`, `FEFO - Serial Number`', max_length=50, min_length=1)
    uom: str = Field(..., description='Product Unit of Measure (A unit of measure with this name must exist in reference books under units)', max_length=50, min_length=1)
    status: Literal['Active', 'Setup required', 'Deprecated'] = Field(..., description='The only valid values are `Active`, `Setup required` and `Deprecated`', min_length=1)
    quantity_to_produce: float = Field(..., description='Specify how many products will be assembled as per Bill of Materials.  Required if `BillOfMaterial` is `true`', strict=True, allow_inf_nan=False)
    assembly_cost_estimation_method: str = Field(..., description='.Required if `BillOfMaterial` is `true`', max_length=256, min_length=1)
    barcode: str | None = Field(None, description='Product barcode', max_length=256)
    default_location: str | None = Field(None, description='Name of the default Location for product. (Location with this name must exist in reference books under locations)', max_length=50)
    price_tier1: float | None = Field(None, description='Product Sale Price used when Price Tier 1 is selected in Sale Task. Up to 4 decimal places.', strict=True, allow_inf_nan=False)
    short_description: str | None = Field(None, description='Multiline short description of the product', max_length=500)
    description: str | None = Field(None, description='Multiline description of the product')
    minimum_before_reorder: float | None = Field(None, description='Minimum available product quantity for this product to appear on Reorder report/forms. Defaults to 0', strict=True, allow_inf_nan=False)
    reorder_quantity: float | None = Field(None, description='Default quantity to put into purchase order when reordering this product. Not applicable to reorder backordered form. Defaults to 0', strict=True, allow_inf_nan=False)
    sellable: bool | None = Field(None, description='Value for field `I am selling this product` on product page. Available values for this field: `true`, `false`. If value of field is not specified then `true` will be accepted by default.', strict=True)

class UpdateProductConfig(Input):
    """PUT Product. """
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Ignored by POST action. Required for PUT action')
    sku: str = Field(..., description='Product SKU must be unique.', max_length=50, min_length=1)
    name: str = Field(..., description='Product name. Quickbooks Online limitations: maximum length is 100 characters and must be unique', max_length=256, min_length=1)
    category: str = Field(..., description='Category name', max_length=256, min_length=1)
    brand: str | None = Field(None, description='Brand name', max_length=50)
    type: Literal['Stock', 'Service'] = Field(..., description='Product Type. Valid values: `Stock` or `Service`. Read-only for PUT.', min_length=1)
    costing_method: str = Field(..., description='Valid values: `FIFO`, `Special - Batch`, `Special - Serial Number`, `FIFO - Serial Number`, `FIFO - Batch`, `FEFO - Batch`, `FEFO - Serial Number`', max_length=50, min_length=1)
    uom: str = Field(..., description='Product Unit of Measure (A unit of measure with this name must exist in reference books under units)', max_length=50, min_length=1)
    status: Literal['Active', 'Setup required', 'Deprecated'] = Field(..., description='The only valid values are `Active`, `Setup required` and `Deprecated`', min_length=1)
    quantity_to_produce: float = Field(..., description='Specify how many products will be assembled as per Bill of Materials.  Required if `BillOfMaterial` is `true`', strict=True, allow_inf_nan=False)
    assembly_cost_estimation_method: str = Field(..., description='.Required if `BillOfMaterial` is `true`', max_length=256, min_length=1)
    barcode: str | None = Field(None, description='Product barcode', max_length=256)
    default_location: str | None = Field(None, description='Name of the default Location for product. (Location with this name must exist in reference books under locations)', max_length=50)
    price_tier1: float | None = Field(None, description='Product Sale Price used when Price Tier 1 is selected in Sale Task. Up to 4 decimal places.', strict=True, allow_inf_nan=False)
    short_description: str | None = Field(None, description='Multiline short description of the product', max_length=500)
    description: str | None = Field(None, description='Multiline description of the product')
    minimum_before_reorder: float | None = Field(None, description='Minimum available product quantity for this product to appear on Reorder report/forms. Defaults to 0', strict=True, allow_inf_nan=False)
    reorder_quantity: float | None = Field(None, description='Default quantity to put into purchase order when reordering this product. Not applicable to reorder backordered form. Defaults to 0', strict=True, allow_inf_nan=False)
    sellable: bool | None = Field(None, description='Value for field `I am selling this product` on product page. Available values for this field: `true`, `false`. If value of field is not specified then `true` will be accepted by default.', strict=True)

class ListCustomersConfig(Input):
    """GET Customer. Returns one provider page."""
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    id: UUID | None = Field(None)
    name: str | None = Field(None)
    contact_filter: str | None = Field(None)
    modified_since: datetime | None = Field(None)
    include_deprecated: bool | None = Field(None, strict=True)
    include_product_prices: bool | None = Field(None, strict=True)

class CreateCustomerConfig(Input):
    """POST Customer. """
    operation: Literal['create_customer'] = Field('create_customer', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Customer name. Must be unique.', max_length=256, min_length=1)
    display_name: str | None = Field(None, description='Preferred customer name. Unlike `Name`, multiple customers can use this `DisplayName`. It does not need to be unique.', max_length=256)
    status: Literal['Active', 'Deprecated'] = Field(..., description='Points that Customer is Active. Available values are `Active` and `Deprecated`. Required for POST')
    currency: str = Field(..., description='Currency code of Customer.', min_length=1)
    payment_term: str = Field(..., description='Payment term.', min_length=1)
    account_receivable: str = Field(..., description='Account receivable code of Customer.', min_length=1)
    revenue_account: str = Field(..., description='Sale account code of Customer.', min_length=1)
    tax_rule: str = Field(..., description='Tax rule name.', min_length=1)
    price_tier: str | None = Field(None, description='Price tier.')
    carrier: str | None = Field(None, description='Carrier name.')
    sales_representative: str | None = Field(None, description='Sales representative.')
    location: str | None = Field(None, description='Location.')
    discount: int | None = Field(None, description='Discount must be between 0% and 100%.', strict=True, ge=0, le=100)
    comments: str | None = Field(None, description='Comments.', max_length=2000)
    credit_limit: int | None = Field(None, description='Credit limit.', strict=True)
    tags: str | None = Field(None, description='Tags string.')
    addresses: list[SupplierAddressModel] | None = Field(None, description='List of addresses.')
    contacts: list[SupplierContactModel] | None = Field(None, description='List of contacts.')

class UpdateCustomerConfig(Input):
    """PUT Customer. """
    operation: Literal['update_customer'] = Field('update_customer', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Unique Customer ID.')
    name: str = Field(..., description='Customer name. Must be unique.', max_length=256, min_length=1)
    display_name: str | None = Field(None, description='Preferred customer name. Unlike `Name`, multiple customers can use this `DisplayName`. It does not need to be unique.', max_length=256)
    status: Literal['Active', 'Deprecated'] = Field(..., description='Points that Customer is Active. Available values are `Active` and `Deprecated`. Required for POST')
    currency: str = Field(..., description='Currency code of Customer.', min_length=1)
    payment_term: str = Field(..., description='Payment term.', min_length=1)
    account_receivable: str = Field(..., description='Account receivable code of Customer.', min_length=1)
    revenue_account: str = Field(..., description='Sale account code of Customer.', min_length=1)
    tax_rule: str = Field(..., description='Tax rule name.', min_length=1)
    price_tier: str | None = Field(None, description='Price tier.')
    carrier: str | None = Field(None, description='Carrier name.')
    sales_representative: str | None = Field(None, description='Sales representative.')
    location: str | None = Field(None, description='Location.')
    discount: int | None = Field(None, description='Discount must be between 0% and 100%.', strict=True, ge=0, le=100)
    comments: str | None = Field(None, description='Comments.', max_length=2000)
    credit_limit: int | None = Field(None, description='Credit limit.', strict=True)
    tags: str | None = Field(None, description='Tags string.')
    addresses: list[SupplierAddressModel] | None = Field(None, description='List of addresses.')
    contacts: list[SupplierContactModel] | None = Field(None, description='List of contacts.')

class ListSuppliersConfig(Input):
    """GET Supplier. Returns one provider page."""
    operation: Literal['list_suppliers'] = Field('list_suppliers', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    id: UUID | None = Field(None)
    name: str | None = Field(None)
    modified_since: datetime | None = Field(None)
    include_deprecated: bool | None = Field(None, strict=True)

class CreateSupplierConfig(Input):
    """POST Supplier. """
    operation: Literal['create_supplier'] = Field('create_supplier', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Name of Supplier.', max_length=256, min_length=1)
    currency: str = Field(..., description='Currency code of Supplier.', min_length=1)
    payment_term: str = Field(..., description='PaymentTerm name.', min_length=1)
    account_payable: str = Field(..., description='AccountPayable code of Supplier.', min_length=1)
    tax_rule: str = Field(..., description='TaxRule name.', min_length=1)
    status: str = Field(..., description='Points that Supplier is Active. Can be `Active` or `Deprecated`', min_length=1)
    discount: int | None = Field(None, description='Discount must be between 0% and 100%. 0% used as default.', strict=True, ge=0, le=100)
    comments: str | None = Field(None, description='Comments.', max_length=256)
    addresses: list[SupplierAddressModel] | None = Field(None, description='List of addresses.')
    contacts: list[SupplierContactModel] | None = Field(None, description='List of contacts.')

class UpdateSupplierConfig(Input):
    """PUT Supplier. """
    operation: Literal['update_supplier'] = Field('update_supplier', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Unique Supplier ID.')
    name: str = Field(..., description='Name of Supplier.', max_length=256, min_length=1)
    currency: str = Field(..., description='Currency code of Supplier.', min_length=1)
    payment_term: str = Field(..., description='PaymentTerm name.', min_length=1)
    account_payable: str = Field(..., description='AccountPayable code of Supplier.', min_length=1)
    tax_rule: str = Field(..., description='TaxRule name.', min_length=1)
    status: str = Field(..., description='Points that Supplier is Active. Can be `Active` or `Deprecated`', min_length=1)
    discount: int | None = Field(None, description='Discount must be between 0% and 100%. 0% used as default.', strict=True, ge=0, le=100)
    comments: str | None = Field(None, description='Comments.', max_length=256)
    addresses: list[SupplierAddressModel] | None = Field(None, description='List of addresses.')
    contacts: list[SupplierContactModel] | None = Field(None, description='List of contacts.')

class ListProductAvailabilityConfig(Input):
    """GET Product Availability. Returns one provider page."""
    operation: Literal['list_product_availability'] = Field('list_product_availability', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    id: UUID | None = Field(None)
    name: str | None = Field(None)
    sku: str | None = Field(None)
    location: str | None = Field(None)
    batch: str | None = Field(None)
    category: str | None = Field(None)
    non_zero_products_only: bool | None = Field(None, strict=True)

class ListLocationsConfig(Input):
    """GET Location. Returns one provider page."""
    operation: Literal['list_locations'] = Field('list_locations', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None)
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    deprecated: bool | None = Field(None, strict=True)
    name: str | None = Field(None)

class ListSalesConfig(Input):
    """GET Sale List. Returns one provider page."""
    operation: Literal['list_sales'] = Field('list_sales', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    search: str | None = Field(None)
    created_since: datetime | None = Field(None)
    updated_since: datetime | None = Field(None)
    updated_until: datetime | None = Field(None)
    ship_by: datetime | None = Field(None)
    quote_status: str | None = Field(None)
    order_status: str | None = Field(None)
    combined_pick_status: str | None = Field(None)
    combined_pack_status: str | None = Field(None)
    combined_shipp_status: str | None = Field(None)
    combined_shipping_status: str | None = Field(None)
    combined_invoice_status: str | None = Field(None)
    credit_note_status: str | None = Field(None)
    external_id: str | None = Field(None)
    status: str | None = Field(None)
    ready_for_shipping: bool | None = Field(None, strict=True)
    customer_id: str | None = Field(None)
    order_location_id: UUID | None = Field(None)

class GetSaleConfig(Input):
    """GET Sale. """
    operation: Literal['get_sale'] = Field('get_sale', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1)
    combine_additional_charges: bool | None = Field(None, strict=True)
    hide_inventory_movements: bool | None = Field(None, strict=True)
    include_transactions: bool | None = Field(None, strict=True)
    country_format: str | None = Field(None)

class ListPurchasesConfig(Input):
    """GET Purchase List. Returns one provider page."""
    operation: Literal['list_purchases'] = Field('list_purchases', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    search: str | None = Field(None)
    required_by: datetime | None = Field(None)
    updated_since: datetime | None = Field(None)
    updated_until: datetime | None = Field(None)
    order_status: str | None = Field(None)
    stock_received_status: str | None = Field(None)
    restock_received_status: str | None = Field(None)
    invoice_status: str | None = Field(None)
    credit_note_status: str | None = Field(None)
    unstock_status: str | None = Field(None)
    status: str | None = Field(None)
    drop_ship_task_id: UUID | None = Field(None)

class GetPurchaseConfig(Input):
    """GET Purchase. """
    operation: Literal['get_purchase'] = Field('get_purchase', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1)
    combine_additional_charges: bool | None = Field(None, strict=True)

class ListStockAdjustmentsConfig(Input):
    """GET Stock Adjustment List. Returns one provider page."""
    operation: Literal['list_stock_adjustments'] = Field('list_stock_adjustments', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    status: str | None = Field(None)

class GetStockAdjustmentConfig(Input):
    """GET Stock Adjustment. """
    operation: Literal['get_stock_adjustment'] = Field('get_stock_adjustment', json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1)

class CreateStockAdjustmentConfig(Input):
    """POST Stock Adjustment. """
    operation: Literal['create_stock_adjustment'] = Field('create_stock_adjustment', json_schema_extra={"ui:hidden": True})
    effective_date: datetime = Field(..., description='Date of transaction')
    status: Literal['DRAFT', 'COMPLETED'] = Field(..., description='Status of stock adjustment. Available values are `DRAFT`,`COMPLETED`.')
    account: str | None = Field(None, description='Expense account for inventory adjustment')
    reference: str | None = Field(None, description='Custom reference')
    comment: str | None = Field(None, description='Comment')
    update_on_hand: bool | None = Field(None, description='If `true`, adjusts on hand quantity, otherwise adjusts available quantity. If `UpdateOnHand` is not provided, it will be treated as false by default.', strict=True)
    lines: list[NewStockLineModel] = Field(..., min_length=1, max_length=1000)

class UpdateStockAdjustmentConfig(Input):
    """PUT Stock Adjustment. """
    operation: Literal['update_stock_adjustment'] = Field('update_stock_adjustment', json_schema_extra={"ui:hidden": True})
    task_id: UUID = Field(..., description='Unique Cin7 Core Stock Adjustment ID. Required for PUT')
    effective_date: datetime = Field(..., description='Date of transaction')
    status: Literal['DRAFT', 'COMPLETED'] = Field(..., description='Status of stock adjustment. Available values are `DRAFT`,`COMPLETED`.')
    account: str | None = Field(None, description='Expense account for inventory adjustment')
    reference: str | None = Field(None, description='Custom reference')
    comment: str | None = Field(None, description='Comment')
    update_on_hand: bool | None = Field(None, description='If `true`, adjusts on hand quantity, otherwise adjusts available quantity. If `UpdateOnHand` is not provided, it will be treated as false by default.', strict=True)
    lines: list[NewStockLineModel] = Field(..., min_length=1, max_length=1000)

class ListCategoriesConfig(Input):
    """GET Product Category. Returns one provider page."""
    operation: Literal['list_categories'] = Field('list_categories', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1)
    limit: int | None = Field(None, strict=True, ge=1, le=1000)
    name: str | None = Field(None)

class CreateCategoryConfig(Input):
    """POST Product Category. """
    operation: Literal['create_category'] = Field('create_category', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Category name for product', max_length=50, min_length=1)

class UpdateCategoryConfig(Input):
    """PUT Product Category. """
    operation: Literal['update_category'] = Field('update_category', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Required for PUT, Ignored for POST operations')
    name: str = Field(..., description='Category name for product', max_length=50, min_length=1)


Cin7CoreConfig = Annotated[Union[
    GetMeConfig, ListProductsConfig, CreateProductConfig, UpdateProductConfig, ListCustomersConfig, CreateCustomerConfig, UpdateCustomerConfig, ListSuppliersConfig, CreateSupplierConfig, UpdateSupplierConfig, ListProductAvailabilityConfig, ListLocationsConfig, ListSalesConfig, GetSaleConfig, ListPurchasesConfig, GetPurchaseConfig, ListStockAdjustmentsConfig, GetStockAdjustmentConfig, CreateStockAdjustmentConfig, UpdateStockAdjustmentConfig, ListCategoriesConfig, CreateCategoryConfig, UpdateCategoryConfig
], Field(discriminator="operation")]


class Cin7CoreFullConfig(NodeConfig[Cin7CoreConfig, Cin7CoreAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {'get_me': ('GET', '/me', {}),
 'list_products': ('GET',
                   '/product',
                   {'id': 'ID',
                    'page': 'Page',
                    'limit': 'Limit',
                    'name': 'Name',
                    'sku': 'Sku',
                    'modified_since': 'ModifiedSince',
                    'include_deprecated': 'IncludeDeprecated',
                    'include_bom': 'IncludeBOM',
                    'include_suppliers': 'IncludeSuppliers',
                    'include_movements': 'IncludeMovements',
                    'include_attachments': 'IncludeAttachments',
                    'include_reorder_levels': 'IncludeReorderLevels',
                    'include_custom_prices': 'IncludeCustomPrices'}),
 'create_product': ('POST',
                    '/product',
                    {'sku': 'SKU',
                     'name': 'Name',
                     'category': 'Category',
                     'brand': 'Brand',
                     'type': 'Type',
                     'costing_method': 'CostingMethod',
                     'uom': 'UOM',
                     'status': 'Status',
                     'quantity_to_produce': 'QuantityToProduce',
                     'assembly_cost_estimation_method': 'AssemblyCostEstimationMethod',
                     'barcode': 'Barcode',
                     'default_location': 'DefaultLocation',
                     'price_tier1': 'PriceTier1',
                     'short_description': 'ShortDescription',
                     'description': 'Description',
                     'minimum_before_reorder': 'MinimumBeforeReorder',
                     'reorder_quantity': 'ReorderQuantity',
                     'sellable': 'Sellable'}),
 'update_product': ('PUT',
                    '/product',
                    {'id': 'ID',
                     'sku': 'SKU',
                     'name': 'Name',
                     'category': 'Category',
                     'brand': 'Brand',
                     'type': 'Type',
                     'costing_method': 'CostingMethod',
                     'uom': 'UOM',
                     'status': 'Status',
                     'quantity_to_produce': 'QuantityToProduce',
                     'assembly_cost_estimation_method': 'AssemblyCostEstimationMethod',
                     'barcode': 'Barcode',
                     'default_location': 'DefaultLocation',
                     'price_tier1': 'PriceTier1',
                     'short_description': 'ShortDescription',
                     'description': 'Description',
                     'minimum_before_reorder': 'MinimumBeforeReorder',
                     'reorder_quantity': 'ReorderQuantity',
                     'sellable': 'Sellable'}),
 'list_customers': ('GET',
                    '/customer',
                    {'page': 'Page',
                     'limit': 'Limit',
                     'id': 'ID',
                     'name': 'Name',
                     'contact_filter': 'ContactFilter',
                     'modified_since': 'ModifiedSince',
                     'include_deprecated': 'IncludeDeprecated',
                     'include_product_prices': 'IncludeProductPrices'}),
 'create_customer': ('POST',
                     '/customer',
                     {'name': 'Name',
                      'display_name': 'DisplayName',
                      'status': 'Status',
                      'currency': 'Currency',
                      'payment_term': 'PaymentTerm',
                      'account_receivable': 'AccountReceivable',
                      'revenue_account': 'RevenueAccount',
                      'tax_rule': 'TaxRule',
                      'price_tier': 'PriceTier',
                      'carrier': 'Carrier',
                      'sales_representative': 'SalesRepresentative',
                      'location': 'Location',
                      'discount': 'Discount',
                      'comments': 'Comments',
                      'credit_limit': 'CreditLimit',
                      'tags': 'Tags',
                      'addresses': 'Addresses',
                      'contacts': 'Contacts'}),
 'update_customer': ('PUT',
                     '/customer',
                     {'id': 'ID',
                      'name': 'Name',
                      'display_name': 'DisplayName',
                      'status': 'Status',
                      'currency': 'Currency',
                      'payment_term': 'PaymentTerm',
                      'account_receivable': 'AccountReceivable',
                      'revenue_account': 'RevenueAccount',
                      'tax_rule': 'TaxRule',
                      'price_tier': 'PriceTier',
                      'carrier': 'Carrier',
                      'sales_representative': 'SalesRepresentative',
                      'location': 'Location',
                      'discount': 'Discount',
                      'comments': 'Comments',
                      'credit_limit': 'CreditLimit',
                      'tags': 'Tags',
                      'addresses': 'Addresses',
                      'contacts': 'Contacts'}),
 'list_suppliers': ('GET',
                    '/supplier',
                    {'page': 'Page',
                     'limit': 'Limit',
                     'id': 'ID',
                     'name': 'Name',
                     'modified_since': 'ModifiedSince',
                     'include_deprecated': 'IncludeDeprecated'}),
 'create_supplier': ('POST',
                     '/supplier',
                     {'name': 'Name',
                      'currency': 'Currency',
                      'payment_term': 'PaymentTerm',
                      'account_payable': 'AccountPayable',
                      'tax_rule': 'TaxRule',
                      'status': 'Status',
                      'discount': 'Discount',
                      'comments': 'Comments',
                      'addresses': 'Addresses',
                      'contacts': 'Contacts'}),
 'update_supplier': ('PUT',
                     '/supplier',
                     {'id': 'ID',
                      'name': 'Name',
                      'currency': 'Currency',
                      'payment_term': 'PaymentTerm',
                      'account_payable': 'AccountPayable',
                      'tax_rule': 'TaxRule',
                      'status': 'Status',
                      'discount': 'Discount',
                      'comments': 'Comments',
                      'addresses': 'Addresses',
                      'contacts': 'Contacts'}),
 'list_product_availability': ('GET',
                               '/ref/productavailability',
                               {'page': 'Page',
                                'limit': 'Limit',
                                'id': 'ID',
                                'name': 'Name',
                                'sku': 'Sku',
                                'location': 'Location',
                                'batch': 'Batch',
                                'category': 'Category',
                                'non_zero_products_only': 'NonZeroProductsOnly'}),
 'list_locations': ('GET',
                    '/ref/location',
                    {'id': 'ID',
                     'page': 'Page',
                     'limit': 'Limit',
                     'deprecated': 'Deprecated',
                     'name': 'Name'}),
 'list_sales': ('GET',
                '/saleList',
                {'page': 'Page',
                 'limit': 'Limit',
                 'search': 'Search',
                 'created_since': 'CreatedSince',
                 'updated_since': 'UpdatedSince',
                 'updated_until': 'UpdatedUntil',
                 'ship_by': 'ShipBy',
                 'quote_status': 'QuoteStatus',
                 'order_status': 'OrderStatus',
                 'combined_pick_status': 'CombinedPickStatus',
                 'combined_pack_status': 'CombinedPackStatus',
                 'combined_shipp_status': 'CombinedShippStatus',
                 'combined_shipping_status': 'CombinedShippingStatus',
                 'combined_invoice_status': 'CombinedInvoiceStatus',
                 'credit_note_status': 'CreditNoteStatus',
                 'external_id': 'ExternalID',
                 'status': 'Status',
                 'ready_for_shipping': 'ReadyForShipping',
                 'customer_id': 'CustomerID',
                 'order_location_id': 'OrderLocationID'}),
 'get_sale': ('GET',
              '/sale',
              {'id': 'ID',
               'combine_additional_charges': 'CombineAdditionalCharges',
               'hide_inventory_movements': 'HideInventoryMovements',
               'include_transactions': 'IncludeTransactions',
               'country_format': 'CountryFormat'}),
 'list_purchases': ('GET',
                    '/purchaseList',
                    {'page': 'Page',
                     'limit': 'Limit',
                     'search': 'Search',
                     'required_by': 'RequiredBy',
                     'updated_since': 'UpdatedSince',
                     'updated_until': 'UpdatedUntil',
                     'order_status': 'OrderStatus',
                     'stock_received_status': 'StockReceivedStatus',
                     'restock_received_status': 'RestockReceivedStatus',
                     'invoice_status': 'InvoiceStatus',
                     'credit_note_status': 'CreditNoteStatus',
                     'unstock_status': 'UnstockStatus',
                     'status': 'Status',
                     'drop_ship_task_id': 'DropShipTaskID'}),
 'get_purchase': ('GET',
                  '/purchase',
                  {'id': 'ID', 'combine_additional_charges': 'CombineAdditionalCharges'}),
 'list_stock_adjustments': ('GET',
                            '/stockadjustmentList',
                            {'page': 'Page', 'limit': 'Limit', 'status': 'Status'}),
 'get_stock_adjustment': ('GET', '/stockadjustment', {'task_id': 'TaskID'}),
 'create_stock_adjustment': ('POST',
                             '/stockadjustment',
                             {'effective_date': 'EffectiveDate',
                              'status': 'Status',
                              'account': 'Account',
                              'reference': 'Reference',
                              'comment': 'Comment',
                              'update_on_hand': 'UpdateOnHand',
                              'lines': 'Lines'}),
 'update_stock_adjustment': ('PUT',
                             '/stockadjustment',
                             {'task_id': 'TaskID',
                              'effective_date': 'EffectiveDate',
                              'status': 'Status',
                              'account': 'Account',
                              'reference': 'Reference',
                              'comment': 'Comment',
                              'update_on_hand': 'UpdateOnHand',
                              'lines': 'Lines'}),
 'list_categories': ('GET', '/ref/category', {'page': 'Page', 'limit': 'Limit', 'name': 'Name'}),
 'create_category': ('POST', '/ref/category', {'name': 'Name'}),
 'update_category': ('PUT', '/ref/category', {'id': 'ID', 'name': 'Name'})}


COLLECTIONS = {
    **{op: "Products" for op in ("list_products", "create_product", "update_product")},
    **{op: "CustomerList" for op in ("list_customers", "create_customer", "update_customer")},
    **{op: "SupplierList" for op in ("list_suppliers", "create_supplier", "update_supplier")},
    "list_product_availability": "ProductAvailabilityList", "list_locations": "LocationList",
    "list_sales": "SaleList", "list_purchases": "PurchaseList",
    "list_stock_adjustments": "StockAdjustmentList", "list_categories": "CategoryList",
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class Cin7CoreNode(WorkflowNode):
    integration_type = "automation-cin7-core"
    connection_evidence = ConnectionEvidence(identity_operation="get_me", identity_keys=("Company",), noun="Cin7 Core company")

    @classmethod
    def get_config_model(cls):
        return Cin7CoreFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, Cin7CoreFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Cin7 Core API key")
        credential = self.config.credentials
        config = self.config.config
        method, path, fields = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, by_alias=True, exclude={"operation"})
        wire = {target: values[key] for key, target in fields.items() if key in values}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in wire.items()} if method == "GET" else None
        secrets = [credential.account_id, credential.application_key]
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    json=wire if method != "GET" else None,
                    headers={"api-auth-accountid": credential.account_id,
                        "api-auth-applicationkey": credential.application_key, "Accept": "application/json"})
        except (httpx.HTTPError, OSError):
            raise ValueError("Cin7 Core request did not complete; inspect the resource before retrying a write") from None
        if response.status_code != 200:
            message = "Cin7 Core rejected the request"
            try:
                error = response.json()
                if isinstance(error, list):
                    message = "; ".join(str(row.get("Exception", row.get("Message", ""))) for row in error if isinstance(row, dict)) or message
                elif isinstance(error, dict):
                    message = str(error.get("Exception", error.get("Message", message)))
            except ValueError:
                pass
            return {"status": "error", "success": False, "error": _redact(message[:2000], secrets), "http_status": response.status_code}
        if len(response.content) > 10_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Expected bounded Cin7 Core JSON")
        payload = response.json()
        if not isinstance(payload, dict) or any(key in payload for key in ("Error", "Errors", "Exception", "ErrorCode")):
            raise ValueError("Invalid Cin7 Core response envelope")
        if config.operation == "get_me" and (not isinstance(payload.get("Company"), str) or not payload["Company"].strip()):
            raise ValueError("Cin7 Core did not return a company identity")
        collection = COLLECTIONS.get(config.operation)
        if collection:
            rows = payload.get(collection)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid Cin7 Core collection envelope")
            if type(payload.get("Total")) is not int or payload["Total"] < 0 or type(payload.get("Page")) is not int or payload["Page"] < 1:
                raise ValueError("Invalid Cin7 Core pagination")
        elif config.operation != "get_me":
            identity = "TaskID" if "stock_adjustment" in config.operation else "ID"
            if not isinstance(payload.get(identity), str) or not payload[identity]:
                raise ValueError("Cin7 Core did not return the resource identity")
        result = {"status": "success", "success": True, "operation": config.operation,
            "http_status": response.status_code, "data": _redact(payload, secrets)}
        if method != "GET":
            result["acknowledged"] = True
        await self.emit(result)
        return result
