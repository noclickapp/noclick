"""Urable API v1: account reads and customer, item, job and calendar writes.

Contract: https://app.urable.com/docs/openapi.yaml (version 1.0).
Money is in cents; timestamps are Unix milliseconds. Each operation issues one
request. List operations return one page and a possible continuation ID.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.urable.com/api"


class UrableAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Urable API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.urable.com",
            "x-credential-instructions": "As an Urable admin, open Settings → Developer → API Keys, create a key and copy it here. Enable customers:read for the connection check, plus the read scopes for resources you use and customers:write, items:write, jobs:write or events:write for your writes. The full key is shown only once.",
        },
    )
    credential_type: Literal["urable_api_key"] = Field(
        "urable_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        return clean_secret(value, field_name="API key")


class UrableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank_strings(cls, value):
        if isinstance(value, str) and value and not value.strip():
            raise ValueError("Use text containing a non-space character")
        return value


class UrableLabeledValue(UrableInput):
    label: str | None = Field(None)
    value: str | None = Field(None)


class UrableAddress(UrableInput):
    line1: str | None = Field(None)
    line2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None)
    postalCode: str | None = Field(None)
    country: str | None = Field(
        None, description="ISO country code (US, CA, AU, GB, NZ, IE)."
    )


class UrableLocationValue(UrableInput):
    address: UrableAddress | None = Field(None)


class UrableLocation(UrableInput):
    label: str | None = Field(None)
    value: UrableLocationValue | None = Field(None)


class UrableCustomerInputColor(UrableInput):
    name: str | None = Field(None)
    hex: str | None = Field(None)


class UrableCustomerInput(UrableInput):
    type: Literal["person", "business"] | None = Field(None)
    status: Literal["new", "contacted", "existing"] | None = Field(None)
    firstName: str = Field(..., min_length=1, description="Required and non-blank.")
    lastName: str | None = Field(None)
    emails: list[UrableLabeledValue] | None = Field(None)
    phoneNumbers: list[UrableLabeledValue] | None = Field(None)
    locations: list[UrableLocation] | None = Field(None)
    origin: str | None = Field(None)
    taxExempt: bool | None = Field(None)
    color: UrableCustomerInputColor | None = Field(None)
    notes: str | None = Field(None)
    customData: list[dict] | None = Field(None)


class UrableCustomerUpdateInputColor(UrableInput):
    name: str | None = Field(None)
    hex: str | None = Field(None)


class UrableCustomerUpdateInput(UrableInput):
    type: Literal["person", "business"] | None = Field(None)
    status: Literal["new", "contacted", "existing"] | None = Field(None)
    firstName: str | None = Field(None, description="Non-blank if supplied.")
    lastName: str | None = Field(None)
    emails: list[UrableLabeledValue] | None = Field(None)
    phoneNumbers: list[UrableLabeledValue] | None = Field(None)
    locations: list[UrableLocation] | None = Field(None)
    origin: str | None = Field(None)
    taxExempt: bool | None = Field(None)
    color: UrableCustomerUpdateInputColor | None = Field(None)
    notes: str | None = Field(None)
    customData: list[dict] | None = Field(None)


class UrableItemInputDimensions(UrableInput):
    area: float | None = Field(None)
    length: float | None = Field(None)
    depth: float | None = Field(None)
    unitSystem: Literal["imperial", "metric"] | None = Field(None)


class UrableItemInput(UrableInput):
    customerId: str = Field(..., min_length=1)
    industry: str | None = Field(None)
    type: Literal["automotive", "marine", "aviation", "other"] | None = Field(None)
    name: str = Field(..., min_length=1)
    location: UrableLocation | None = Field(None)
    photoURL: str | None = Field(None)
    vins: list[str] | None = Field(None)
    licensePlates: list[str] | None = Field(None)
    stockNumbers: list[str] | None = Field(None)
    dimensions: UrableItemInputDimensions | None = Field(
        None,
        description="Lawn care only. Values are in the business's display units, named by unitSystem: sq ft / ft / in for imperial, m² / m / cm for metric (volume is cu yd or m³). A business can switch systems, so read unitSystem rather than assuming. Send unitSystem on a write to be rejected if it no longer matches; volume is read-only and derived from area x depth.",
    )
    notes: str | None = Field(None)
    customData: list[dict] | None = Field(None)


class UrableItemUpdateInputDimensions(UrableInput):
    area: float | None = Field(None)
    length: float | None = Field(None)
    depth: float | None = Field(None)
    unitSystem: Literal["imperial", "metric"] | None = Field(None)


class UrableItemUpdateInput(UrableInput):
    customerId: str | None = Field(None)
    industry: str | None = Field(None)
    type: Literal["automotive", "marine", "aviation", "other"] | None = Field(None)
    name: str | None = Field(None)
    location: UrableLocation | None = Field(None)
    photoURL: str | None = Field(None)
    vins: list[str] | None = Field(None)
    licensePlates: list[str] | None = Field(None)
    stockNumbers: list[str] | None = Field(None)
    dimensions: UrableItemUpdateInputDimensions | None = Field(
        None,
        description="Lawn care only. Values are in the business's display units, named by unitSystem: sq ft / ft / in for imperial, m² / m / cm for metric (volume is cu yd or m³). A business can switch systems, so read unitSystem rather than assuming. Send unitSystem on a write to be rejected if it no longer matches; volume is read-only and derived from area x depth.",
    )
    notes: str | None = Field(None)
    customData: list[dict] | None = Field(None)


class UrableJobInputColor(UrableInput):
    name: str = Field(
        ..., min_length=1, description='Label for the color, e.g. "Ceramic coating".'
    )
    hex: str = Field(..., min_length=1, description='Hex code, e.g. "#2fd2a8".')


class UrableLineItemInput(UrableInput):
    productServiceId: str = Field(..., min_length=1)
    quantity: float | None = Field(None)
    priceSku: str | None = Field(
        None, description="Which price variant to use; defaults to the first."
    )
    itemId: str | None = Field(
        None,
        description="Jobs only: which of the job's items (the property/vehicle) this line item is for. It must be one of the job's `itemIds`. Optional on a single-item job (the line item goes to that item); required on a job with more than one item. Ignored on orders.",
    )


class UrableAdjustmentInput(UrableInput):
    type: Literal[
        "tax",
        "fee",
        "discount",
        "subscription",
        "eGiftCard",
        "coupon",
        "credit",
        "referral",
    ] = Field(..., min_length=1)
    name: str | None = Field(None)
    value: float = Field(..., description="Cents, or a percentage when percent=true.")
    percent: bool | None = Field(None)
    taxable: bool | None = Field(
        None, description="For fees: whether the fee is itself taxed."
    )
    code: str | None = Field(None, description="Coupon / gift-card code.")
    ref: str | None = Field(
        None, description="Reference to the coupon / gift card / referral document."
    )
    productServiceIds: list[str] | None = Field(
        None, description="Restrict the adjustment to these product/service ids."
    )


class UrableJobInput(UrableInput):
    customerId: str = Field(..., min_length=1)
    industry: Literal["vehicleCare", "lawnCare", "flatGlass", "other"] = Field(
        ..., min_length=1, description="The industry the job belongs to."
    )
    itemIds: list[str] = Field(
        ..., description="The items/vehicles the job is for.", min_length=1
    )
    userIds: list[str] | None = Field(None, description="Assigned team members.")
    type: Literal["shop", "field"] | None = Field(None)
    status: Literal[
        "quote", "scheduled", "in progress", "completed", "archived", "canceled"
    ] | None = Field(None)
    name: str | None = Field(
        None, description="Defaults to the joined item names if omitted."
    )
    location: UrableLocation | None = Field(
        None,
        description="Where the work is performed. Applies to `field` jobs; ignored on `shop` jobs. Defaults to the customer's location when omitted, so a field job is rejected only if neither is present. `formattedAddress`, `geoPoint` and `timeZone` are derived from the address server-side.\n",
    )
    start: int | None = Field(None, description="Unix ms.")
    end: int | None = Field(None, description="Unix ms.")
    dropOff: int | None = Field(None, description="Unix ms.")
    completedAt: int | None = Field(
        None,
        description="Unix ms the work was finished. Set this when importing history: it is the date the earnings, profit, and product/service reports bucket a job on. Requires `status: completed` in the same request, since those reports only count completed jobs.",
    )
    canceledAt: int | None = Field(
        None,
        description="Unix ms the job was canceled. Set this when importing history so the canceled jobs list sorts on the original cancellation date. Requires `status: canceled` in the same request.",
    )
    allDay: bool | None = Field(None)
    color: UrableJobInputColor | None = Field(
        None,
        description="Calendar color for the job. `name` is the label shown for the color. Send `null` to clear it.",
    )
    lineItems: list[UrableLineItemInput] = Field(..., min_length=1)
    adjustments: list[UrableAdjustmentInput] | None = Field(None)
    taxExempt: bool | None = Field(None)
    autoTax: bool | None = Field(None, description="Fetch the tax rate from TaxJar.")
    notes: str | None = Field(None)
    deployScheduledMessage: bool | None = Field(
        None,
        description="Set true to send the customer the immediate 'job scheduled' confirmation message for this job; by default API-created jobs suppress it, so imports can't mass-message customers. The job's other reminders (appointment reminders, follow-ups) deploy normally either way. Even when true, the confirmation only sends when the account's scheduled-message auto-deploy preference is on and the job's `start` is in the future.",
    )


class UrableJobUpdateInputColor(UrableInput):
    name: str = Field(
        ..., min_length=1, description='Label for the color, e.g. "Ceramic coating".'
    )
    hex: str = Field(..., min_length=1, description='Hex code, e.g. "#2fd2a8".')


class UrableJobUpdateInput(UrableInput):
    customerId: str | None = Field(None)
    industry: Literal["vehicleCare", "lawnCare", "flatGlass", "other"] | None = Field(
        None, description="The industry the job belongs to."
    )
    itemIds: list[str] | None = Field(
        None,
        description="The items/vehicles the job is for. Replaces the job's items, so `lineItems` must be sent with it.",
        min_length=1,
    )
    userIds: list[str] | None = Field(None, description="Assigned team members.")
    type: Literal["shop", "field"] | None = Field(None)
    status: Literal[
        "quote", "scheduled", "in progress", "completed", "archived", "canceled"
    ] | None = Field(None)
    name: str | None = Field(None)
    location: UrableLocation | None = Field(
        None,
        description="Where the work is performed. Replaces the job's address outright, recomputing `formattedAddress`, `geoPoint` and `timeZone`. Ignored on `shop` jobs, and cleared when `type` changes to `shop`.\n",
    )
    start: int | None = Field(None, description="Unix ms.")
    end: int | None = Field(None, description="Unix ms.")
    dropOff: int | None = Field(None, description="Unix ms.")
    completedAt: int | None = Field(
        None,
        description="Unix ms the work was finished. Set this when importing history: it is the date the earnings, profit, and product/service reports bucket a job on. Requires the job to end up `completed`, either by sending `status: completed` here or because it already is.",
    )
    canceledAt: int | None = Field(
        None,
        description="Unix ms the job was canceled. Requires the job to end up `canceled`, either by sending `status: canceled` here or because it already is.",
    )
    allDay: bool | None = Field(None)
    color: UrableJobUpdateInputColor | None = Field(
        None,
        description="Calendar color for the job. `name` is the label shown for the color. Send `null` to clear it.",
    )
    lineItems: list[UrableLineItemInput] | None = Field(None, min_length=1)
    adjustments: list[UrableAdjustmentInput] | None = Field(None)
    taxExempt: bool | None = Field(None)
    autoTax: bool | None = Field(None, description="Fetch the tax rate from TaxJar.")
    notes: str | None = Field(None)


class UrableEventInputColor(UrableInput):
    name: str = Field(
        ..., min_length=1, description='Label for the color, e.g. "Team meeting".'
    )
    hex: str = Field(..., min_length=1, description='Hex code, e.g. "#2fd2a8".')


class UrableEventInput(UrableInput):
    type: Literal[
        "meeting", "consultation", "reminder", "time off", "closed", "other"
    ] | None = Field(None)
    jobType: Literal["shop", "field"] | None = Field(None)
    name: str = Field(..., min_length=1)
    customerId: str | None = Field(
        None, description="Optional customer associated with the event."
    )
    userIds: list[str] | None = Field(
        None, description="Assigned team members. Required when private=true."
    )
    start: int = Field(..., description="Unix ms.")
    end: int = Field(
        ..., description="Unix ms; must be greater than or equal to start."
    )
    allDay: bool | None = Field(None)
    color: UrableEventInputColor | None = Field(
        None,
        description="Calendar color for the event. `name` is the label shown for the color. Send `null` to clear it.",
    )
    private: bool | None = Field(None)
    notes: str | None = Field(None)
    customData: list[dict] | None = Field(None)


class UrablePage(UrableInput):
    limit: int = Field(
        10, ge=1, le=100, description="Page size; no total count is provided."
    )
    startAfter: str | None = Field(None, description="Last ID from the preceding page.")
    endBefore: str | None = Field(None, description="First ID for backward pagination.")

    @model_validator(mode="after")
    def one_direction(self):
        if self.startAfter and self.endBefore:
            raise ValueError("Choose startAfter or endBefore")
        return self


class UrableListCustomersConfig(UrablePage):
    "List customers. Requires scope `customers:read`."

    operation: Literal["list_customers"] = Field(
        "list_customers", json_schema_extra={"ui:hidden": True}
    )
    email: str | None = Field(
        None, description="Return customers matching this email (ignores pagination)."
    )


class UrableGetCustomerConfig(UrableInput):
    "Retrieve a customer. Requires scope `customers:read`."

    operation: Literal["get_customer"] = Field(
        "get_customer", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Customer ID")


class UrableCreateCustomerConfig(UrableCustomerInput):
    "Create a customer. Requires scope `customers:write`. `firstName` is required (and cannot be blank)."

    operation: Literal["create_customer"] = Field(
        "create_customer", json_schema_extra={"ui:hidden": True}
    )


class UrableUpdateCustomerConfig(UrableCustomerUpdateInput):
    "Update a customer. Requires scope `customers:write`. Only supplied fields are changed."

    operation: Literal["update_customer"] = Field(
        "update_customer", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Customer ID")


class UrableListItemsConfig(UrablePage):
    "List items. Requires scope `items:read`."

    operation: Literal["list_items"] = Field(
        "list_items", json_schema_extra={"ui:hidden": True}
    )
    vin: str | None = Field(
        None,
        description="Return items whose metadata.vins contains this VIN (ignores pagination).",
    )
    customerId: str | None = Field(
        None, description="Only items belonging to this customer."
    )


class UrableGetItemConfig(UrableInput):
    "Retrieve an item. Requires scope `items:read`."

    operation: Literal["get_item"] = Field(
        "get_item", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Item ID")


class UrableCreateItemConfig(UrableItemInput):
    "Create an item. Requires scope `items:write`. `customerId` (must exist) and `name` are required. For `lawnCare`, `location` is also required.\n"

    operation: Literal["create_item"] = Field(
        "create_item", json_schema_extra={"ui:hidden": True}
    )


class UrableUpdateItemConfig(UrableItemUpdateInput):
    "Update an item. Requires scope `items:write`. Only supplied fields are changed. Supply `customerId` to move the item to a different customer."

    operation: Literal["update_item"] = Field(
        "update_item", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Item ID")


class UrableListProductsConfig(UrablePage):
    "List products/services. Requires scope `products:read`."

    operation: Literal["list_products"] = Field(
        "list_products", json_schema_extra={"ui:hidden": True}
    )
    type: Literal["product", "service"] | None = Field(None)
    categoryRef: str | None = Field(
        None, description="Full document path of a category."
    )
    industry: str | None = Field(None)


class UrableGetProductConfig(UrableInput):
    "Retrieve a product/service. Requires scope `products:read`."

    operation: Literal["get_product"] = Field(
        "get_product", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Product ID")


class UrableListCategoriesConfig(UrablePage):
    "List categories. Requires scope `products:read`. Ordered the way the app lists them (by `num`), not newest-first."

    operation: Literal["list_categories"] = Field(
        "list_categories", json_schema_extra={"ui:hidden": True}
    )


class UrableListJobsConfig(UrablePage):
    "List jobs. Requires scope `jobs:read`. Note: ordering by `start`/`end` only returns jobs that have that field set (i.e. scheduled jobs).\n"

    operation: Literal["list_jobs"] = Field(
        "list_jobs", json_schema_extra={"ui:hidden": True}
    )
    status: Literal[
        "quote", "scheduled", "in progress", "completed", "archived", "canceled"
    ] | None = Field(None)
    customerId: str | None = Field(None)
    orderBy: Literal[
        "created", "modified", "completedAt", "paidAt", "start", "end"
    ] | None = Field(None)


class UrableGetJobConfig(UrableInput):
    "Retrieve a job. Requires scope `jobs:read`."

    operation: Literal["get_job"] = Field(
        "get_job", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Job ID")


class UrableCreateJobConfig(UrableJobInput):
    "Create a job. Requires scope `jobs:write`. Send line items as product/service references + quantities; the server looks up prices, embeds the products, and computes the invoice subtotal/tax/total. A sequential `num` is assigned. Requires a customer, an `industry`, at least one `itemId`, and at least one line item. A job's work is always tracked per item, so the invoice comes back with the line items grouped under `invoice.items` — keyed by item ref — rather than as a flat `invoice.lineItems` array. On a job with one item every line item belongs to it; on a job with several, each line item must name its `itemId`, and every item needs at least one line item. A `field` job is performed on site, so it also needs a `location`: send one, or omit it and the customer's location is copied onto the job. It is rejected only when neither exists. A `location` sent on a `shop` job is ignored. If `name` is omitted it defaults to the joined names of the referenced items (e.g. the vehicle names). Jobs are always created `unpaid`. To record an invoice that was already collected, create the job and then record the money with `POST /v1/payments`, which settles the invoice and derives the payment status. When importing history, set `completedAt` to the original completion date along with `status: completed` so the job reports in the right period. The earnings and profit reports only count completed jobs, so `completedAt` without that status is rejected rather than silently leaving the revenue out of every figure. Likewise `canceledAt` requires `status: canceled` in the same request. New jobs pick up the account's default reminders, but the immediate 'job scheduled' confirmation message is suppressed by default so imports can't mass-message customers — pass `deployScheduledMessage: true` to send it (future-dated jobs only, and only when the account's scheduled-message auto-deploy preference is on).\n"

    operation: Literal["create_job"] = Field(
        "create_job", json_schema_extra={"ui:hidden": True}
    )


class UrableUpdateJobConfig(UrableJobUpdateInput):
    "Update a job. Requires scope `jobs:write`. Only supplied fields are changed. If `lineItems` is supplied the invoice is recomputed; otherwise the existing invoice is preserved. Because a job's line items are grouped under the item they are for, `itemIds` and `lineItems` move together: send the line items alongside any change to `itemIds` (they are rebuilt against the new set, and items dropped from the job lose their line items). Payment status is derived from the invoice and cannot be set here; record money with `POST /v1/payments`. A supplied `location` replaces the job's address outright (the derived `formattedAddress`, `geoPoint` and `timeZone` are all recomputed). On a job that is or becomes `field` and has no location yet, the customer's is copied onto it; the request is rejected only when neither exists. Changing `type` to `shop` clears the job's location.\n"

    operation: Literal["update_job"] = Field(
        "update_job", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Job ID")


class UrableListEventsConfig(UrablePage):
    "List events. Requires scope `events:read`."

    operation: Literal["list_events"] = Field(
        "list_events", json_schema_extra={"ui:hidden": True}
    )
    type: Literal[
        "meeting", "consultation", "reminder", "time off", "closed", "other"
    ] | None = Field(None)
    customerId: str | None = Field(None)
    userId: str | None = Field(None, description="Events assigned to this user.")
    orderBy: Literal["created", "modified", "start", "end"] | None = Field(None)


class UrableGetEventConfig(UrableInput):
    "Retrieve an event. Requires scope `events:read`."

    operation: Literal["get_event"] = Field(
        "get_event", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Event ID")


class UrableCreateEventConfig(UrableEventInput):
    "Create an event. Requires scope `events:write`. `name`, `start`, and `end` are required."

    operation: Literal["create_event"] = Field(
        "create_event", json_schema_extra={"ui:hidden": True}
    )


class UrableListOrdersConfig(UrablePage):
    "List orders. Requires scope `orders:read`."

    operation: Literal["list_orders"] = Field(
        "list_orders", json_schema_extra={"ui:hidden": True}
    )
    status: Literal["placed", "paid", "fulfilled"] | None = Field(None)
    customerId: str | None = Field(None)
    orderBy: Literal["created", "modified", "fulfilledAt", "paidAt"] | None = Field(
        None
    )


class UrableGetOrderConfig(UrableInput):
    "Retrieve an order. Requires scope `orders:read`."

    operation: Literal["get_order"] = Field(
        "get_order", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Order ID")


class UrableListPaymentsConfig(UrablePage):
    "List payments. Requires scope `payments:read`. Filter by `jobId`, `orderId`, or `subscriptionId` to find the payments applied to a specific record.\n"

    operation: Literal["list_payments"] = Field(
        "list_payments", json_schema_extra={"ui:hidden": True}
    )
    status: Literal[
        "paid",
        "pending",
        "processing",
        "failed",
        "refunded",
        "partial refund",
        "voided",
        "past due",
    ] | None = Field(None)
    customerId: str | None = Field(None)
    jobId: str | None = Field(None, description="Payments applied to this job.")
    orderId: str | None = Field(None, description="Payments applied to this order.")
    subscriptionId: str | None = Field(
        None, description="Payments applied to this subscription."
    )


class UrableGetPaymentConfig(UrableInput):
    "Retrieve a payment. Requires scope `payments:read`."

    operation: Literal["get_payment"] = Field(
        "get_payment", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Payment ID")


class UrableListProposalsConfig(UrablePage):
    "List proposals. Requires scope `proposals:read`. Proposals are read-only via the API. Use `createdAfter` or `updatedAfter` (Unix ms) to poll for new/changed proposals cheaply instead of paging through the full history; supplying either overrides `orderBy` to match the filtered field.\n"

    operation: Literal["list_proposals"] = Field(
        "list_proposals", json_schema_extra={"ui:hidden": True}
    )
    status: Literal[
        "draft", "pending", "finalized", "converted", "declined", "voided"
    ] | None = Field(None)
    customerId: str | None = Field(None)
    createdAfter: int | None = Field(
        None, description="Unix ms. Only proposals created at or after this time."
    )
    updatedAfter: int | None = Field(
        None, description="Unix ms. Only proposals modified at or after this time."
    )
    orderBy: Literal["created", "modified"] | None = Field(None)


class UrableGetProposalConfig(UrableInput):
    "Retrieve a proposal. Requires scope `proposals:read`."

    operation: Literal["get_proposal"] = Field(
        "get_proposal", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1, title="Proposal ID")


class UrableListUsersConfig(UrableInput):
    "List users. Requires scope `users:read`. Returns every team member on the account (not paginated). Users are read-only via the API.\n"

    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"ui:hidden": True}
    )


UrableConfig = Annotated[
    Union[
        UrableListCustomersConfig,
        UrableGetCustomerConfig,
        UrableCreateCustomerConfig,
        UrableUpdateCustomerConfig,
        UrableListItemsConfig,
        UrableGetItemConfig,
        UrableCreateItemConfig,
        UrableUpdateItemConfig,
        UrableListProductsConfig,
        UrableGetProductConfig,
        UrableListCategoriesConfig,
        UrableListJobsConfig,
        UrableGetJobConfig,
        UrableCreateJobConfig,
        UrableUpdateJobConfig,
        UrableListEventsConfig,
        UrableGetEventConfig,
        UrableCreateEventConfig,
        UrableListOrdersConfig,
        UrableGetOrderConfig,
        UrableListPaymentsConfig,
        UrableGetPaymentConfig,
        UrableListProposalsConfig,
        UrableGetProposalConfig,
        UrableListUsersConfig,
    ],
    Field(discriminator="operation"),
]


class UrableFullConfig(NodeConfig[UrableConfig, UrableAPIKeyCredential]):
    pass


OPERATIONS = {
    "list_customers": ("GET", "/v1/customers"),
    "get_customer": ("GET", "/v1/customers/{id}"),
    "create_customer": ("POST", "/v1/customers"),
    "update_customer": ("PATCH", "/v1/customers/{id}"),
    "list_items": ("GET", "/v1/items"),
    "get_item": ("GET", "/v1/items/{id}"),
    "create_item": ("POST", "/v1/items"),
    "update_item": ("PATCH", "/v1/items/{id}"),
    "list_products": ("GET", "/v1/products"),
    "get_product": ("GET", "/v1/products/{id}"),
    "list_categories": ("GET", "/v1/categories"),
    "list_jobs": ("GET", "/v1/jobs"),
    "get_job": ("GET", "/v1/jobs/{id}"),
    "create_job": ("POST", "/v1/jobs"),
    "update_job": ("PATCH", "/v1/jobs/{id}"),
    "list_events": ("GET", "/v1/events"),
    "get_event": ("GET", "/v1/events/{id}"),
    "create_event": ("POST", "/v1/events"),
    "list_orders": ("GET", "/v1/orders"),
    "get_order": ("GET", "/v1/orders/{id}"),
    "list_payments": ("GET", "/v1/payments"),
    "get_payment": ("GET", "/v1/payments/{id}"),
    "list_proposals": ("GET", "/v1/proposals"),
    "get_proposal": ("GET", "/v1/proposals/{id}"),
    "list_users": ("GET", "/v1/users"),
}


def _validate_write(op, body):
    if op.operation.startswith("update_") and not body:
        raise ValueError("Supply at least one field to update")
    if "firstName" in body and not body["firstName"].strip():
        raise ValueError("First name cannot be blank")
    if (
        op.operation in {"create_item", "update_item"}
        and body.get("industry") == "lawnCare"
        and not body.get("location")
    ):
        raise ValueError("Lawn care items require a location")
    if op.operation in {"create_job", "update_job"}:
        if "itemIds" in body and "lineItems" not in body:
            raise ValueError("Send lineItems with itemIds")
        items = body.get("itemIds")
        if items:
            for line in body.get("lineItems", []):
                item = line.get("itemId")
                if (item is not None and item not in items) or (
                    len(items) > 1 and not item
                ):
                    raise ValueError("Assign each line item to an item in itemIds")
        for field, status in (("completedAt", "completed"), ("canceledAt", "canceled")):
            if (
                field in body
                and op.operation == "create_job"
                and body.get("status") != status
            ):
                raise ValueError(f"{field} requires status {status}")
    if "start" in body and "end" in body and body["end"] < body["start"]:
        raise ValueError("End must be at or after start")
    if (
        op.operation == "create_event"
        and body.get("private")
        and not body.get("userIds")
    ):
        raise ValueError("Private events require assigned userIds")


class UrableNode(WorkflowNode):
    integration_type = "automation-urable"
    connection_evidence = ConnectionEvidence(
        noun="customers", operation="list_customers"
    )

    @classmethod
    def get_config_model(cls):
        return UrableFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Urable API key")
        op = self.config.config
        method, path = OPERATIONS[op.operation]
        raw = op.model_dump(exclude_none=True)
        raw.pop("operation")
        if "{id}" in path:
            identifier = raw.pop("id")
            if identifier in {".", ".."} or any(c in identifier for c in "/\\?#"):
                raise ValueError("Use a single Urable resource ID")
            path = path.replace("{id}", quote(identifier, safe=""))
        if method != "GET":
            _validate_write(op, raw)
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers={
                    "Authorization": "Bearer " + credential.api_key,
                    "Accept": "application/json",
                },
                **({"params": raw} if method == "GET" else {"json": raw}),
            )
        if response.status_code != 200:
            # Keep the response attached so the connection seam can classify the
            # provider's rejection without mistaking a timeout for a bad key.
            response.raise_for_status()
            raise ValueError("Unexpected Urable response status")
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            message = body.get("error") if isinstance(body, dict) else None
            raise ValueError(
                str(message or "Urable did not confirm success").replace(
                    credential.api_key, "[redacted]"
                )
            )
        data = body.get("data")
        listing = op.operation.startswith("list_")
        if listing:
            if not isinstance(data, list) or any(
                not isinstance(row, dict) for row in data
            ):
                raise ValueError("Urable returned an invalid list")
        elif not isinstance(data, dict):
            raise ValueError("Urable returned an invalid resource")
        result = {"success": True, "data": data}
        # A full page suggests another page; Urable has no has_more/total field.
        if listing and hasattr(op, "limit"):
            filtered = bool(raw.get("email") or raw.get("vin"))
            full_page = len(data) == op.limit and not filtered
            result["possible_next_start_after"] = (
                data[-1].get("id") if full_page and not raw.get("endBefore") else None
            )
            result["possible_previous_end_before"] = (
                data[0].get("id") if full_page and raw.get("endBefore") else None
            )
        return result
