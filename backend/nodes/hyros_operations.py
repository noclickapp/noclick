"""Hyros REST API 1.46 operation models and fixed routes.

Contract: https://api-docs.hyros.com/specs/hyros-api.yaml
No arbitrary URLs, paths, query keys or JSON body fields are accepted.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Operation(_Closed):
    @model_validator(mode="after")
    def selectors(self):
        op = self.operation
        body = getattr(self, "body", None)
        if op in {"create_lead", "create_order", "create_subscription"}:
            if not (body.email or body.phoneNumbers):
                raise ValueError("Supply email or phoneNumbers")
        if op == "update_lead" and not (self.id or self.email or self.phone):
            raise ValueError("Select a lead using id, email or phone")
        if op == "add_lead_tags" and not (body.ids or body.emails):
            raise ValueError("Supply lead ids or emails")
        if op == "update_calls" and not (self.ids or self.externalIds):
            raise ValueError("Supply call ids or externalIds")
        if op == "create_source" and body.integrationType:
            required = ["adSourceId", "accountId"]
            if body.integrationType == "FACEBOOK": required.append("campaignId")
            if body.integrationType == "GOOGLE": required.append("adspendSubType")
            if any(not getattr(body, key) for key in required):
                raise ValueError("Supply " + ", ".join(required) + " for this integrationType")
        if op in {"create_product", "update_product"}:
            if body.name is not None and len(body.name.strip()) < 3:
                raise ValueError("Product name needs at least 3 characters")
            if body.price is not None and (not 0 <= body.price <= 99999999.99 or abs(round(body.price * 100) - body.price * 100) > 0.00001):
                raise ValueError("Product price needs at most 8 digits and 2 decimal places")
        if op == "update_product" and body.isRecurringSale and body.callProduct:
            raise ValueError("A product cannot be recurring and a call product")
        return self


class OrderItem(_Closed):
    name: str = Field(..., description='Name of the product.')
    price: float = Field(..., description='Product price per unit (costOfGoods included).')
    externalId: Optional[str] = Field(None, description='Unique identifier from the external integration.')
    quantity: Optional[float] = Field(None, description='Number of copies purchased. Defaults to 1.')
    sku: Optional[str] = Field(None, description='Unique product reference code.')
    costOfGoods: Optional[float] = Field(None, description='Cost per unit of manufacture. Must be included in the price. Defaults to 0.')
    taxes: Optional[float] = Field(None, description='Taxes applied to the item per unit. Defaults to 0.')
    itemDiscount: Optional[float] = Field(None, description='Discount applied to this specific line item.')
    packages: Optional[list[str]] = Field(None, description='Product packages this item belongs to (used for recurring sales attribution).')
    isRebill: Optional[bool] = Field(None, description="If true, the sale is marked as recurring even if it's the first one.")
    tag: Optional[str] = Field(None, description='Tag to create for the sale item.')
    categoryName: Optional[str] = Field(None, description='Links the sale to a product category.')

class GetUserInfo(_Operation):
    'Retrieve User Information.'
    operation: Literal['get_user_info'] = Field('get_user_info', json_schema_extra={"ui:hidden": True})

class ListLeads(_Operation):
    'Retrieve Leads.'
    operation: Literal['list_leads'] = Field('list_leads', json_schema_extra={"ui:hidden": True})
    ids: Optional[str] = Field(None, description='Array of lead ids. Maximum of 50 ids.')
    emails: Optional[str] = Field(None, description='Array of emails or email prefixes. Maximum of 50 emails.')
    phones: Optional[str] = Field(None, description='Array of phone numbers. Maximum of 50 phones.')
    tags: Optional[str] = Field(None, description='Array of tag names. Leads matching any of the provided tags will be retrieved. Tags are matched exactly, including any prefix (e.g. `!Tag1`). Maximum of 50 tags.')
    tagFromDate: Optional[str] = Field(None, description='ISO 8601 date. Only leads that had a tag applied on or after this date will be retrieved. Combined with `tags` it returns the leads that received one of those tags inside the period, so a lead tagged before it is left out even if it still holds the tag; on its own it matches any tag applied in the period. Leads whose tag assignment has no recorded date are not retrieved. A `tagFromDate` later than `tagToDate` is rejected with `400 Bad Request`. Cannot be later than `tagToDate`. If the date does not include a timezone, the configured account timezone will be assumed.\n')
    tagToDate: Optional[str] = Field(None, description='ISO 8601 date. Only leads that had a tag applied on or before this date will be retrieved. Cannot be earlier than `tagFromDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    stage: Optional[str] = Field(None, description='Array of stage names. Leads matching any of the provided stages will be retrieved. Stage names are matched case-insensitively. Maximum of 50 stages.')
    fromDate: Optional[str] = Field(None, description='ISO 8601 date. Only leads whose join date is more recent than this will be retrieved. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or later than toDate.')
    toDate: Optional[str] = Field(None, description='ISO 8601 date. Only leads whose join date is older than this will be retrieved. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or earlier than fromDate.')
    updatedFromDate: Optional[str] = Field(None, description='ISO 8601 date. Only leads updated on or after this date will be retrieved. Use it to fetch just the leads that changed since your last request. Cannot be later than `updatedToDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    updatedToDate: Optional[str] = Field(None, description='ISO 8601 date. Only leads updated on or before this date will be retrieved. Cannot be earlier than `updatedFromDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    pageSize: Optional[int] = Field(None, description='Maximum number of leads per page. Range 1-250.', ge=1, le=250)
    pageId: Optional[str] = Field(None, description='ID of the next page, taken from the `nextPageId` of a previous response. Omit it to fetch the first page. An invalid or expired pagination cursor is rejected with `400 Bad Request`.')

class CreateLeadBody(_Closed):
    email: Optional[str] = Field(None, description="Email of the lead. Required if no phone number is provided. If only a phone number is provided, a placeholder email `<phone>@hyrosapi.com` is generated and returned as the lead's email.")
    firstName: Optional[str] = Field(None)
    lastName: Optional[str] = Field(None)
    tags: Optional[list[str]] = Field(None, description='Tags to apply to the lead. Send a JSON array; a single tag may also be sent as a plain string, for clients whose form builder cannot send an array. An empty or blank string, like `null`, applies no tags. Any other shape, such as an object, is rejected with `400 Bad Request`.')
    tagsDate: Optional[str] = Field(None, description='Optional ISO-8601 date (`2023-05-01T10:00:00-03:00`) applied as the assignment date of **every** tag in `tags`, to backdate historical tags during imports, migrations or CRM syncs. Defaults to the current time when omitted. Cannot be in the future. To assign tags with different dates, send one request per date. If a tag generates a sale or a source attribution, those are backdated too. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    leadIps: Optional[list[str]] = Field(None, description='IPs of the lead for ad attribution.')
    phoneNumbers: Optional[Union[str, list[str]]] = Field(None, description='Phone numbers of the lead. Required if no email is provided. On an existing lead this replaces the stored numbers.')
    stage: Optional[str] = Field(None, description='Stage to apply to the lead. On create the stage is a plain string; on update (`PUT /leads`) it is set via the `leadStage` object (`{name, date}`) instead.')
    adOptimizationConsent: Optional[Literal['GRANTED', 'DENIED', 'UNSPECIFIED']] = Field(None, description='Optional. Sent blank it reads as UNSPECIFIED. Omitted, a new lead starts as UNSPECIFIED and an existing lead keeps the value it already had.')

class CreateLead(_Operation):
    'Create Lead.'
    operation: Literal['create_lead'] = Field('create_lead', json_schema_extra={"ui:hidden": True})
    body: CreateLeadBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class UpdateLeadBodyLeadstageFields(_Closed):
    name: str = Field(..., description='Stage name to apply. Required and cannot be empty or blank; the value is trimmed, and a missing, empty or whitespace-only name is rejected with `400 Bad Request` and message `The lead stage name cannot be empty`.')
    date: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**. A malformed date is rejected with `400 Bad Request` and message `Invalid date format.`.')

class UpdateLeadBody(_Closed):
    email: Optional[str] = Field(None, description='New email.')
    firstName: Optional[str] = Field(None)
    lastName: Optional[str] = Field(None)
    tags: Optional[list[str]] = Field(None, description='Tags to add to the lead. Send a JSON array; a single tag may also be sent as a plain string, for clients whose form builder cannot send an array. An empty or blank string, like `null`, applies no tags. Any other shape, such as an object, is rejected with `400 Bad Request`.')
    tagsDate: Optional[str] = Field(None, description='Optional ISO-8601 date applied as the assignment date of every tag in `tags` (defaults to now, cannot be in the future). Tags the lead already has are ignored, not re-dated. For tags with different dates, send one request per date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    removeTags: Optional[list[str]] = Field(None, description='Tags to remove from the lead. Send a JSON array; a single tag may also be sent as a plain string, for clients whose form builder cannot send an array. An empty or blank string, like `null`, removes no tags. Any other shape, such as an object, is rejected with `400 Bad Request`.')
    leadIps: Optional[list[str]] = Field(None)
    phoneNumbers: Optional[list[str]] = Field(None, description='Phone numbers to add to the lead. Existing numbers are kept.')
    adOptimizationConsent: Optional[Literal['GRANTED', 'DENIED', 'UNSPECIFIED']] = Field(None, description="Optional. Blank reads as UNSPECIFIED; omitted leaves the lead's current value unchanged.")
    leadStage: Optional[UpdateLeadBodyLeadstageFields] = Field(None, description='Stage to apply to the lead on update. Create (`POST /leads`) uses a plain `stage` string instead.')
    removeLeadStages: Optional[list[str]] = Field(None, description='Names of the stages to remove from the lead. Unknown names reject the request; stages the lead does not hold are ignored.')

class UpdateLead(_Operation):
    'Update Lead.'
    operation: Literal['update_lead'] = Field('update_lead', json_schema_extra={"ui:hidden": True})
    email: Optional[str] = Field(None, description='Email used to search for the lead to update.')
    id: Optional[str] = Field(None, description='ID used to search for the lead to update.')
    phone: Optional[str] = Field(None, description='Phone used to search for the lead to update.')
    body: UpdateLeadBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class AddLeadTagsBody(_Closed):
    ids: Optional[list[str]] = Field(None, description='Ids of the leads to tag, as `GET /leads` returns them. Send a JSON array; a single value may also be sent as a plain string. An empty or blank string is read as no value. Any other shape, such as an object, is rejected with `400 Bad Request`. Maximum of 50 ids.\n', max_length=50)
    emails: Optional[list[str]] = Field(None, description='Emails of the leads to tag, matched exactly. Send a JSON array; a single value may also be sent as a plain string. An empty or blank string is read as no value. Any other shape, such as an object, is rejected with `400 Bad Request`. Maximum of 50 emails.\n', max_length=50)
    tags: list[str] = Field(..., description='Tags to apply to every selected lead. A name prefixed with `$` is a sale tag, with `@` a source tag and with `!` an action tag; a name with no prefix defaults to an action tag. Send a JSON array; a single tag may also be sent as a plain string. An empty or blank string is read as no tags and answered with `Missing required field: tags`. Any other shape, such as an object, is rejected with `400 Bad Request`. Maximum of 50 tags.\n', max_length=50)
    tagsDate: Optional[str] = Field(None, description='Optional ISO-8601 date applied as the assignment date of every tag in this request, to backdate historical tags (defaults to now, cannot be in the future). Unlike `PUT /leads`, action tags (`!`) a lead already carries are re-dated to this date, so an existing assignment date is corrected; sale (`$`) and source (`@`) tags it already carries are left untouched. For tags with different dates, send one request per date. Without a time zone offset the date is stored as UTC; see **Date Formats**.\n')

class AddLeadTags(_Operation):
    'Add Tags to Leads.'
    operation: Literal['add_lead_tags'] = Field('add_lead_tags', json_schema_extra={"ui:hidden": True})
    body: AddLeadTagsBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class ListSales(_Operation):
    'Retrieve Sales.'
    operation: Literal['list_sales'] = Field('list_sales', json_schema_extra={"ui:hidden": True})
    ids: Optional[str] = Field(None, description='Array of sales ids. Maximum of 50 ids.')
    emails: Optional[str] = Field(None, description='Array of emails or prefixes. Maximum of 50 emails.')
    leadIds: Optional[str] = Field(None, description='Array of leadIds. Maximum of 50 lead ids.')
    productTags: Optional[str] = Field(None, description='Array of product tags. Maximum of 20 product tags.')
    firstSourceTags: Optional[str] = Field(None, description='Array of source tags to filter sales by. Only sales whose first source has any of these tags are returned. Tags must match exactly. When `lastSourceTags` is also provided, a sale must match both. Maximum of 50 source tags.\n')
    lastSourceTags: Optional[str] = Field(None, description='Array of source tags to filter sales by. Only sales whose last source has any of these tags are returned. Tags must match exactly. When `firstSourceTags` is also provided, a sale must match both. Maximum of 50 source tags.\n')
    isRecurringSale: Optional[Literal['RECURRING', 'NON_RECURRING', 'ALL']] = Field(None, description='Filter by recurring status.')
    saleRefundedState: Optional[Literal['REFUNDED', 'NON_REFUNDED', 'ALL']] = Field(None, description='Filter by refund status.')
    fromDate: Optional[str] = Field(None, description='ISO 8601 date. Only sales after this date will be retrieved. Bounds the date the sale was made, never the date of its refund. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or later than toDate.')
    toDate: Optional[str] = Field(None, description='ISO 8601 date. Only sales before this date will be retrieved. Bounds the date the sale was made, never the date of its refund. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or earlier than fromDate.')
    updatedFromDate: Optional[str] = Field(None, description='ISO 8601 date. Only sales modified on or after this date will be retrieved. Use it to fetch just the sales that changed since your last request. A sale is considered modified when one of its own fields changes — price, quantity, date, refund state, attribution or conversion state; changes to the lead it belongs to, such as its tags, do not count. Cannot be later than `updatedToDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    updatedToDate: Optional[str] = Field(None, description='ISO 8601 date. Only sales modified on or before this date will be retrieved. Cannot be earlier than `updatedFromDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    pageSize: Optional[int] = Field(None, description='Maximum number of sales per page. Range 1-250.', ge=1, le=250)
    pageId: Optional[str] = Field(None, description='ID of the next page, taken from the `nextPageId` of a previous response. Omit it to fetch the first page. An invalid or expired pagination cursor is rejected with `400 Bad Request`.')

class CreateOrderBody(_Closed):
    email: Optional[str] = Field(None, description='Email associated with the lead. Required if no phone number is provided.')
    parentEmail: Optional[str] = Field(None, description='Email of the origin lead. If present, the sale will be attributed to the origin lead.')
    firstName: Optional[str] = Field(None)
    lastName: Optional[str] = Field(None)
    leadIps: Optional[list[str]] = Field(None, description='IPs of the customer that made the purchase for ad attribution. Maximum of 3 ips.', max_length=3)
    stage: Optional[str] = Field(None)
    phoneNumbers: Optional[Union[str, list[str]]] = Field(None, description='Required if no email is provided.')
    orderId: Optional[str] = Field(None, description='Identifier by which sales will be grouped. Only letters, numbers, underscores, hyphens, periods, and colons. No spaces.')
    externalSubscriptionId: Optional[str] = Field(None)
    cartId: Optional[str] = Field(None)
    provider: Optional[str] = Field(None, description="Integration the order's sales are recorded under (e.g. `STRIPE`, `SHOPIFY`, `KONNEKTIVE`, `API`), the same values `integrationType` takes in **Update Order**. Case-sensitive. A value that is not an integration name is not rejected; the sales are recorded under `API`, as when the field is omitted.")
    date: Optional[str] = Field(None, description='ISO 8601 date when the transaction was processed. Defaults to current date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    shippingCost: Optional[float] = Field(None, description='Shipping cost distributed across items. Default is 0.')
    taxes: Optional[float] = Field(None, description='Order taxes distributed across items. Default is 0.')
    orderDiscount: Optional[float] = Field(None, description='Discount applied to the complete order, distributed evenly across all line items.')
    hardCost: Optional[float] = Field(None, description='A cost the merchant pays out of the order total, typically payment-processor fees (e.g. Stripe). Distributed evenly across the line items and reported as part of the sale hard cost, lowering net profit. Unlike `taxes` and `shippingCost` it is **not** added to the order revenue, because the buyer did not pay it. Must not be negative. Default is 0.')
    priceFormat: Optional[Literal['DECIMAL', 'INTEGER']] = Field(None, description='Format of the item prices. Defaults to `DECIMAL` when omitted, `null` or sent as an empty string.')
    currency: Optional[str] = Field(None, description='Currency code (e.g. EUR). Defaults to Hyros account setup.')
    items: list[OrderItem] = Field(..., min_length=1)

class CreateOrder(_Operation):
    'Create Order.'
    operation: Literal['create_order'] = Field('create_order', json_schema_extra={"ui:hidden": True})
    body: CreateOrderBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class UpdateOrderBody(_Closed):
    integrationType: Optional[str] = Field(None, description="External integration the order belongs to (e.g. STRIPE, SHOPIFY, KONNEKTIVE, API). Case-sensitive: any other value is rejected. When present, the path id is matched against an item externalId for that integration, or against the order id when no item matches, and only that integration's sales of the order are updated. When omitted, the path id is matched against the order id; if the order holds sales from more than one integration the request is rejected, and `integrationType` must be sent to choose one.\n")
    stage: Optional[str] = Field(None, description="Stage to apply to the customer's lead.")
    externalSubscriptionId: Optional[str] = Field(None)
    cartId: Optional[str] = Field(None)
    shippingCost: Optional[float] = Field(None, description='Shipping cost distributed across items. Default is 0.')
    taxes: Optional[float] = Field(None, description='Order taxes distributed across items. Default is 0.')
    orderDiscount: Optional[float] = Field(None, description='Discount applied to the complete order, distributed evenly across all line items.')
    hardCost: Optional[float] = Field(None, description="A cost the merchant pays out of the order total, typically payment-processor fees (e.g. Stripe). Distributed evenly across the line items and reported as part of the sale hard cost, lowering net profit; it is **not** added to the order revenue. If omitted, the value already stored on the order's sales is kept, so a later call can attach the fee without resending it. Send `0` to clear it. Must not be negative.")
    priceFormat: Optional[Literal['DECIMAL', 'INTEGER']] = Field(None, description='Format of the item prices. Defaults to `DECIMAL` when omitted, `null` or sent as an empty string.')
    currency: Optional[str] = Field(None, description='Currency code (e.g. EUR). Defaults to Hyros account setup.')
    items: list[OrderItem] = Field(..., description='New items list. The existing items of the order will be replaced by this list.', min_length=1)

class UpdateOrder(_Operation):
    'Update Order.'
    operation: Literal['update_order'] = Field('update_order', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description="Identifier of the order to update. By default this is the order id used during creation.\nWhen `integrationType` is provided in the body, this value is matched against the `externalId`\nof any item belonging to the order (the `id` of its `sale` events, as returned by\n`GET /api/v1.0/leads/journey` with `includeEvents=true`), or against the order id when no item\nof that integration carries it. Either way, only the order's sales from that integration are updated.\n")
    body: UpdateOrderBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class RefundOrder(_Operation):
    'Refund Order.'
    operation: Literal['refund_order'] = Field('refund_order', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Order id to be refunded.')
    refundedAmount: Optional[str] = Field(None, description='Amount to be refunded.')

class ListCalls(_Operation):
    'Retrieve Calls.'
    operation: Literal['list_calls'] = Field('list_calls', json_schema_extra={"ui:hidden": True})
    ids: Optional[str] = Field(None, description='Array of call ids. Maximum of 50 ids.')
    emails: Optional[str] = Field(None, description='Array of emails or prefixes. Maximum of 50 emails.')
    leadIds: Optional[str] = Field(None, description='Array of leadIds. Maximum of 50 lead ids.')
    productTags: Optional[str] = Field(None, description='Array of product tags. Maximum of 20 product tags.')
    firstSourceTags: Optional[str] = Field(None, description='Array of source tags to filter calls by. Only calls whose first source has any of these tags are returned. Tags must match exactly. When `lastSourceTags` is also provided, a call must match both. Maximum of 50 source tags.\n')
    lastSourceTags: Optional[str] = Field(None, description='Array of source tags to filter calls by. Only calls whose last source has any of these tags are returned. Tags must match exactly. When `firstSourceTags` is also provided, a call must match both. Maximum of 50 source tags.\n')
    fromDate: Optional[str] = Field(None, description='ISO 8601 date. Only calls after this date will be retrieved. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or later than toDate.')
    toDate: Optional[str] = Field(None, description='ISO 8601 date. Only calls before this date will be retrieved. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or earlier than fromDate.')
    updatedFromDate: Optional[str] = Field(None, description='ISO 8601 date. Only calls modified on or after this date will be retrieved. Use it to fetch just the calls that changed since your last request. A call is considered modified when one of its own fields changes — its date, qualification, attribution or conversion state; changes to the lead it belongs to, such as its tags, do not count. Cannot be later than `updatedToDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    updatedToDate: Optional[str] = Field(None, description='ISO 8601 date. Only calls modified on or before this date will be retrieved. Cannot be earlier than `updatedFromDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    pageSize: Optional[int] = Field(None, description='Maximum number of calls per page. Range 1-250.', ge=1, le=250)
    pageId: Optional[str] = Field(None, description='ID of the next page, taken from the `nextPageId` of a previous response. Omit it to fetch the first page. An invalid or expired pagination cursor is rejected with `400 Bad Request`.')
    qualified: Optional[bool] = Field(None, description='Filter by qualified status.')
    qualificationStages: Optional[str] = Field(None, description='Array of qualification stage names. Maximum of 50 qualification stages.')

class CreateCallBody(_Closed):
    name: str = Field(..., description='Name of the call.')
    email: str = Field(..., description='Email associated with the lead.')
    firstName: Optional[str] = Field(None)
    lastName: Optional[str] = Field(None)
    leadIps: Optional[list[str]] = Field(None)
    stage: Optional[str] = Field(None)
    phoneNumbers: Optional[Union[str, list[str]]] = Field(None)
    externalId: Optional[str] = Field(None, description='Unique identifier from the external integration. If a call with the same externalId exists, it will be updated.')
    id: Optional[str] = Field(None, description='DEPRECATED: Use externalId instead.')
    date: Optional[str] = Field(None, description='ISO 8601 date when the call was processed. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    qualified: Optional[bool] = Field(None, description='DEPRECATED: Use state instead.')
    qualification: Optional[str] = Field(None, description='Custom name of the qualification to apply to the call.')
    state: Optional[Literal['QUALIFIED', 'UNQUALIFIED', 'CANCELLED', 'NO_SHOW']] = Field(None, description='State to assign to the call. An empty value is treated as if the field was not sent, leaving the state unset.')

class CreateCall(_Operation):
    'Create Call.'
    operation: Literal['create_call'] = Field('create_call', json_schema_extra={"ui:hidden": True})
    body: CreateCallBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class UpdateCalls(_Operation):
    'Update Calls.'
    operation: Literal['update_calls'] = Field('update_calls', json_schema_extra={"ui:hidden": True})
    ids: Optional[str] = Field(None, description='Array of call ids to update. Provide either `ids` or `externalIds`, not both. Maximum of 50 ids.')
    externalIds: Optional[str] = Field(None, description='Array of call externalIds to update. Provide either `ids` or `externalIds`, not both. Maximum of 50 external ids.')
    name: str = Field(..., description='Call name to assign.')
    qualification: Optional[str] = Field(None, description='Call qualification to assign.')
    state: Optional[Literal['QUALIFIED', 'UNQUALIFIED', 'CANCELLED', 'NO_SHOW']] = Field(None, description='Call state to assign.')
    qualified: Optional[bool] = Field(None, description='DEPRECATED: Use state instead.')

class ListProducts(_Operation):
    'Retrieve Products.'
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, description='Filter products whose name equals this value (exact match).')
    tag: Optional[str] = Field(None, description='Filter products whose tag equals this value (exact match). The sale prefix "$" is added automatically when omitted.')
    category: Optional[str] = Field(None, description='Filter products by the name of their category.')
    isRecurringSale: Optional[Literal['RECURRING', 'NON_RECURRING', 'ALL']] = Field(None, description='Filter by recurring status.')
    pageSize: Optional[int] = Field(None, description='Maximum number of products per page. Range 1-250.', ge=1, le=250)
    pageId: Optional[str] = Field(None, description='ID of the next page. Returned in `nextPageId` of each response.')

class CreateProductBody(_Closed):
    name: str = Field(..., description='Name of the product. Must have at least 3 characters.')
    price: float = Field(..., description='Plain number only: up to 8 digits before the decimal point and up to 2 after (max 99999999.99). Currency symbols and separators are not accepted.')
    category: Optional[str] = Field(None)
    packages: Optional[list[str]] = Field(None, description='Product packages (used for recurring sales attribution).')

class CreateProduct(_Operation):
    'Create Product.'
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    body: CreateProductBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class UpdateProductBody(_Closed):
    name: Optional[str] = Field(None, description='Name of the product. Must have at least 3 characters.')
    price: Optional[float] = Field(None, description='Plain number only: up to 8 digits before the decimal point and up to 2 after (max 99999999.99). Currency symbols and separators are not accepted.')
    customCost: Optional[float] = Field(None, description='Cost of goods of the product, used in profit and ROAS reporting.')
    tag: Optional[str] = Field(None)
    sku: Optional[str] = Field(None)
    category: Optional[str] = Field(None)
    isRecurringSale: Optional[bool] = Field(None, description='Whether the product is a recurring sale. A product cannot be both a recurring sale and a call product.')
    callProduct: Optional[bool] = Field(None, description='Whether the product is a call product. A product cannot be both a recurring sale and a call product.')
    packages: Optional[list[str]] = Field(None, description='Product packages (used for recurring sales attribution). Omit to keep the current packages unchanged; send an empty array to remove the product from all packages.')
    updateHistoricalSales: Optional[bool] = Field(None, description="When true, a cost change is propagated to the product's existing sales, updating their profit and ROAS.")

class UpdateProduct(_Operation):
    'Update Product.'
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Product id (its tracking pixel, as returned by the products listing).')
    body: UpdateProductBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class DeleteProduct(_Operation):
    'Delete Product.'
    operation: Literal['delete_product'] = Field('delete_product', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Product id (its tracking pixel, as returned by the products listing) to be deleted.')

class ListSources(_Operation):
    'List all Sources.'
    operation: Literal['list_sources'] = Field('list_sources', json_schema_extra={"ui:hidden": True})
    adSourceIds: Optional[str] = Field(None, description='Array of ad source ids to retrieve. Maximum of 50 ad source ids.')
    includeOrganic: Optional[bool] = Field(None, description='Whether to include the sources flagged organic. Defaults to `true`, so an unfiltered response contains them. Note that the `hyros_get_sources` MCP tool defaults this to `false` instead.')
    includeDisregarded: Optional[bool] = Field(None, description='Whether to include disregarded sources. Defaults to `true`, so an unfiltered response contains them. Note that the `hyros_get_sources` MCP tool defaults this to `false` instead.')
    integrationType: Optional[Literal['FACEBOOK', 'GOOGLE', 'GOOGLE_V2', 'TIKTOK', 'SNAPCHAT', 'LINKEDIN', 'TWITTER', 'PINTEREST', 'BING', 'REDDIT', 'APPLOVIN', 'WHOP_ADS']] = Field(None)
    name: Optional[str] = Field(None, description='Source name, matched in full and ignoring case. Partial names do not match. Combined with `tag`, both have to match.')
    tag: Optional[str] = Field(None, description='Source tag, matched in full and ignoring case. A tag is unique within the account, so at most one source is returned. Combined with `name`, both have to match.')
    pageSize: Optional[int] = Field(None, description='Between 1 and 250.', ge=1, le=250)
    pageId: Optional[str] = Field(None)

class CreateSourceBody(_Closed):
    name: str = Field(...)
    category: Optional[str] = Field(None, description='Name of the source category, matched to an existing one ignoring case (an exact-case match takes precedence). Created if it does not exist. If several categories match and none can be told apart by case, a category with exactly that name that is not linked to an ad campaign is used, or created if there is none. With `integrationType` `FACEBOOK`, the name must instead match exactly a category linked to `campaignId` or to no campaign; otherwise one is created linked to `campaignId`.')
    goal: Optional[str] = Field(None)
    trafficSource: Optional[str] = Field(None)
    isDisregard: Optional[bool] = Field(None, description="Marks the source as disregarded, so it is de-prioritized when a sale is attributed: a non-disregarded source seen shortly before takes the credit instead. The source still appears on the lead's journey.")
    isOrganic: Optional[bool] = Field(None, description='Marks the source as organic, the same flag the Sources screen sets with "Mark as organic". It is independent of ad spend: leaving it `false` does not make the source paid, it only leaves it unflagged.')
    integrationType: Optional[Literal['GOOGLE', 'FACEBOOK', 'TIKTOK', 'SNAPCHAT', 'LINKEDIN']] = Field(None, description='Subset of `AdspendType` accepted when creating a source.')
    adSourceId: Optional[str] = Field(None, description='Id of the ad. Required if `integrationType` is present.\n- Facebook: adset id\n- Google: campaign id\n- TikTok: ad group id\n- Snapchat: ad squad id\n- LinkedIn: campaign id\n')
    accountId: Optional[str] = Field(None, description='Id of the ad account. Required if `integrationType` is present.')
    adspendSubType: Optional[Literal['DISPLAY', 'VIDEO']] = Field(None, description='Required when `integrationType` is GOOGLE.')
    campaignId: Optional[str] = Field(None, description='Required when `integrationType` is FACEBOOK.')

class CreateSource(_Operation):
    'Create Source.'
    operation: Literal['create_source'] = Field('create_source', json_schema_extra={"ui:hidden": True})
    body: CreateSourceBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class ListTags(_Operation):
    'List tags with lead counts.'
    operation: Literal['list_tags'] = Field('list_tags', json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, description='Exact tag name to filter by.')
    pageSize: Optional[int] = Field(None, description='Range 1-250.', ge=1, le=250)
    pageId: Optional[str] = Field(None)

class ListSubscriptions(_Operation):
    'Retrieve Subscriptions.'
    operation: Literal['list_subscriptions'] = Field('list_subscriptions', json_schema_extra={"ui:hidden": True})
    ids: Optional[str] = Field(None, description='Array of subscription ids. Maximum of 50 ids.')
    emails: Optional[str] = Field(None, description='Array of emails or prefixes. Maximum of 50 emails.')
    leadIds: Optional[str] = Field(None, description='Array of leadIds. Maximum of 50 lead ids.')
    productTags: Optional[str] = Field(None, description='Array of product tags. Maximum of 20 product tags.')
    subscriptionStates: Optional[list[Literal['ACTIVE', 'TRIALING', 'CANCELED', 'PAST_DUE', 'INCOMPLETE', 'INCOMPLETE_EXPIRED', 'UNPAID', 'COMPLETED', 'PAUSED', 'UNKNOWN']]] = Field(None, description="Filter by subscription status, comma separated. Defaults to all states. An unrecognized value is rejected with `Invalid subscriptionStates '<value>'. Accepted values: ACTIVE, TRIALING, CANCELED, PAST_DUE, INCOMPLETE, INCOMPLETE_EXPIRED, UNPAID, COMPLETED, PAUSED, UNKNOWN`.")
    fromDate: Optional[str] = Field(None, description='ISO 8601 date. Only subscriptions whose join date is more recent than this will be retrieved. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or later than toDate.')
    toDate: Optional[str] = Field(None, description='ISO 8601 date. Only subscriptions whose join date is older than this will be retrieved. If the date does not include a timezone, the configured account timezone will be assumed. Cannot be in a future month, or earlier than fromDate.')
    updatedFromDate: Optional[str] = Field(None, description='ISO 8601 date. Only subscriptions updated on or after this date will be retrieved. Use it to fetch just the subscriptions that changed since your last request. Cannot be later than `updatedToDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    updatedToDate: Optional[str] = Field(None, description='ISO 8601 date. Only subscriptions updated on or before this date will be retrieved. Cannot be earlier than `updatedFromDate`. If the date does not include a timezone, the configured account timezone will be assumed.')
    pageSize: Optional[int] = Field(None, description='Range 1-250.', ge=1, le=250)
    pageId: Optional[str] = Field(None, description='ID of the next page, taken from the `nextPageId` of a previous response. Omit it to fetch the first page. An invalid or expired pagination cursor is rejected with `400 Bad Request`.')

class CreateSubscriptionBody(_Closed):
    email: Optional[str] = Field(None, description='Required if no phone number is provided.')
    parentEmail: Optional[str] = Field(None)
    firstName: Optional[str] = Field(None)
    lastName: Optional[str] = Field(None)
    leadIps: Optional[list[str]] = Field(None)
    stage: Optional[str] = Field(None)
    phoneNumbers: Optional[Union[str, list[str]]] = Field(None, description='Required if no email is provided.')
    subscriptionId: Optional[str] = Field(None)
    name: Optional[str] = Field(None)
    status: Literal['ACTIVE', 'TRIALING', 'CANCELED', 'PAST_DUE', 'INCOMPLETE', 'INCOMPLETE_EXPIRED', 'UNPAID', 'COMPLETED', 'PAUSED'] = Field(..., description='The statuses a write accepts, which is every status except the UNKNOWN sentinel Hyros stores for a status it does not model.')
    startDate: str = Field(..., description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    endDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    cancelAtDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    trialStartDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    trialEndDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    planId: Optional[str] = Field(None)
    price: float = Field(...)
    periodicity: Literal['DAY', 'WEEK', 'MONTH', 'QUARTER', 'YEAR'] = Field(...)
    provider: Optional[str] = Field(None, description='Integration the subscription is recorded under (e.g. `STRIPE`, `SHOPIFY`, `KONNEKTIVE`, `API`). Case-sensitive. A value that is not an integration name is not rejected; the subscription is recorded under `API`, as when the field is omitted.')

class CreateSubscription(_Operation):
    'Create Subscription.'
    operation: Literal['create_subscription'] = Field('create_subscription', json_schema_extra={"ui:hidden": True})
    body: CreateSubscriptionBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class UpdateSubscriptionBody(_Closed):
    ids: list[str] = Field(..., description='Array of subscription ids. Maximum of 50 ids.', max_length=50)
    name: Optional[str] = Field(None)
    status: Optional[Literal['ACTIVE', 'TRIALING', 'CANCELED', 'PAST_DUE', 'INCOMPLETE', 'INCOMPLETE_EXPIRED', 'UNPAID', 'COMPLETED', 'PAUSED']] = Field(None, description='The statuses a write accepts, which is every status except the UNKNOWN sentinel Hyros stores for a status it does not model.')
    startDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    endDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    cancelAtDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    trialStartDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    trialEndDate: Optional[str] = Field(None, description='ISO 8601 date. Without a time zone offset the date is stored as UTC; see **Date Formats**.')
    price: Optional[float] = Field(None)

class UpdateSubscription(_Operation):
    'Update Subscription.'
    operation: Literal['update_subscription'] = Field('update_subscription', json_schema_extra={"ui:hidden": True})
    body: UpdateSubscriptionBody = Field(..., description="Documented JSON body. Writes are asynchronous: use get_request_status with the returned request_id; do not resend a pending write.")

class GetRequestStatus(_Operation):
    'Retrieve Request Status.'
    operation: Literal['get_request_status'] = Field('get_request_status', json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., description='The `request_id` returned when the original write request was accepted.')

HyrosOperation = Annotated[Union[
    GetUserInfo,
    ListLeads,
    CreateLead,
    UpdateLead,
    AddLeadTags,
    ListSales,
    CreateOrder,
    UpdateOrder,
    RefundOrder,
    ListCalls,
    CreateCall,
    UpdateCalls,
    ListProducts,
    CreateProduct,
    UpdateProduct,
    DeleteProduct,
    ListSources,
    CreateSource,
    ListTags,
    ListSubscriptions,
    CreateSubscription,
    UpdateSubscription,
    GetRequestStatus
], Field(discriminator="operation")]

ROUTES = {'get_user_info': ('GET', '/api/v1.0/user-info', ()), 'list_leads': ('GET', '/api/v1.0/leads', ('ids', 'emails', 'phones', 'tags', 'tagFromDate', 'tagToDate', 'stage', 'fromDate', 'toDate', 'updatedFromDate', 'updatedToDate', 'pageSize', 'pageId')), 'create_lead': ('POST', '/api/v1.0/leads', ()), 'update_lead': ('PUT', '/api/v1.0/leads', ('email', 'id', 'phone')), 'add_lead_tags': ('POST', '/api/v1.0/leads/tags', ()), 'list_sales': ('GET', '/api/v1.0/sales', ('ids', 'emails', 'leadIds', 'productTags', 'firstSourceTags', 'lastSourceTags', 'isRecurringSale', 'saleRefundedState', 'fromDate', 'toDate', 'updatedFromDate', 'updatedToDate', 'pageSize', 'pageId')), 'create_order': ('POST', '/api/v1.0/orders', ()), 'update_order': ('PUT', '/api/v1.0/orders/{id}', ()), 'refund_order': ('DELETE', '/api/v1.0/orders/{id}', ('refundedAmount',)), 'list_calls': ('GET', '/api/v1.0/calls', ('ids', 'emails', 'leadIds', 'productTags', 'firstSourceTags', 'lastSourceTags', 'fromDate', 'toDate', 'updatedFromDate', 'updatedToDate', 'pageSize', 'pageId', 'qualified', 'qualificationStages')), 'create_call': ('POST', '/api/v1.0/calls', ()), 'update_calls': ('PUT', '/api/v1.0/calls', ('ids', 'externalIds', 'name', 'qualification', 'state', 'qualified')), 'list_products': ('GET', '/api/v1.0/products', ('name', 'tag', 'category', 'isRecurringSale', 'pageSize', 'pageId')), 'create_product': ('POST', '/api/v1.0/products', ()), 'update_product': ('PUT', '/api/v1.0/products/{id}', ()), 'delete_product': ('DELETE', '/api/v1.0/products/{id}', ()), 'list_sources': ('GET', '/api/v1.0/sources', ('adSourceIds', 'includeOrganic', 'includeDisregarded', 'integrationType', 'name', 'tag', 'pageSize', 'pageId')), 'create_source': ('POST', '/api/v1.0/sources', ()), 'list_tags': ('GET', '/api/v1.0/tags/count', ('name', 'pageSize', 'pageId')), 'list_subscriptions': ('GET', '/api/v1.0/subscriptions', ('ids', 'emails', 'leadIds', 'productTags', 'subscriptionStates', 'fromDate', 'toDate', 'updatedFromDate', 'updatedToDate', 'pageSize', 'pageId')), 'create_subscription': ('POST', '/api/v1.0/subscriptions', ()), 'update_subscription': ('PUT', '/api/v1.0/subscriptions', ()), 'get_request_status': ('GET', '/api/v1.0/requests/{request_id}', ())}
