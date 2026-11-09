"""HelloAsso v5 organization, fundraising, checkout and payment operations.

Each operation sends one request to the public contract. An existing bearer
access token is pasted by hand; this node never creates or refreshes tokens.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.helloasso.com/v5"
CREDENTIAL_TYPE = "helloasso_access_token"


class HelloAssoAccessToken(BaseModel):
    model_config = ConfigDict(title="HelloAsso Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.helloasso.com/reference/obtenir-un-access_token",
            "x-credential-instructions": "Paste an existing HelloAsso access_token without the Bearer prefix. Access tokens expire after 30 minutes: replace an expired token here. NoClick does not request or refresh tokens. Organization clients can access their own organization; partner tokens need authorization for private organization data. Enable AccessPublicData for the connection check and the privileges and roles required by each operation."
        })
    credential_type: Literal["helloasso_access_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class CheckoutBody(_Input):
    model_config = ConfigDict(extra="forbid")
    totalAmount: int = Field(..., ge=0, le=2147483647, description="Total amount in cents. This single-payment checkout requires totalAmount = initialAmount.")
    initialAmount: int = Field(..., ge=0, le=2147483647, description="Initial payment in cents.")
    itemName: str = Field(..., min_length=1, max_length=250)
    backUrl: str = Field(..., min_length=1)
    errorUrl: str = Field(..., min_length=1)
    returnUrl: str = Field(..., min_length=1)
    containsDonation: bool
    metadata: dict | None = None

    @model_validator(mode="after")
    def single_payment(self):
        if self.totalAmount != self.initialAmount:
            raise ValueError("For a single-payment checkout, totalAmount must equal initialAmount")
        return self


class EventTier(_Input):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    price: int = Field(0, ge=0, le=2147483647, description="Price in cents.")


class EventBody(_Input):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1)
    description: str | None = None
    tierList: list[EventTier] | None = None
    startDate: datetime | None = None
    endDate: datetime | None = None
    saleStartDate: datetime | None = None
    saleEndDate: datetime | None = None
    privateTitle: str | None = None
    generateTickets: bool = Field(False, description="Ask HelloAsso to issue and email tickets to participants.")


class FormStateBody(_Input):
    model_config = ConfigDict(extra="forbid")
    state: Literal["Public", "Private", "Draft", "Deleted", "Disabled"]


class HelloAssoListMyOrganizationsConfig(_Input):
    """Get my organizations"""
    operation: Literal["list_my_organizations"] = Field("list_my_organizations", json_schema_extra={"ui:hidden": True})


class HelloAssoGetOrganizationConfig(_Input):
    """Get Organization details"""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization Slug')


class HelloAssoListFormsConfig(_Input):
    """Get the forms of a specific organization"""
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization Slug')
    states: list[Literal['Public', 'Private', 'Draft', 'Deleted', 'Disabled']] | None = Field(None, description='States to filter\n\nAvailable values:\n* `Public` - The form is publicly visible and findable on search engines\n* `Private` - The form is visible only with the URL, you cannot find it on search engines\n* `Draft` - The form is not yet published but visible if you have admin rights\n* `Disabled` - The form is disabled and can be reenabled by changing state to public or private')
    form_types: list[Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop']] | None = Field(None, description='Types to filter')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')


class HelloAssoListFormTypesConfig(_Input):
    """Get a list of formTypes for an organization"""
    operation: Literal["list_form_types"] = Field("list_form_types", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization Slug')
    states: list[Literal['Public', 'Private', 'Draft', 'Deleted', 'Disabled']] | None = Field(None, description="List of Form States to filter with. If none specified, it won't filter results.\n\nAvailable values:\n* `Public` - The form is publicly visible and findable on search engines\n* `Private` - The form is visible only with the URL, you cannot find it on search engines\n* `Draft` - The form is not yet published but visible if you have admin rights\n* `Disabled` - The form is disabled and can be reenabled by changing state to public or private")


class HelloAssoGetFormConfig(_Input):
    """Get detailed public data about a specific form"""
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    form_type: Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop'] = Field(...)
    form_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class HelloAssoGetFormStatsConfig(_Input):
    """Get Stats for the form"""
    operation: Literal["get_form_stats"] = Field("get_form_stats", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    form_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    form_type: Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop'] = Field(...)


class HelloAssoListOrganizationOrdersConfig(_Input):
    """Get a list of orders within a specific organization"""
    operation: Literal["list_organization_orders"] = Field("list_organization_orders", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization slug')
    from_date: datetime | None = Field(None, description='First Date Filter')
    to_date: datetime | None = Field(None, description='End Date Filter (exclusive)')
    user_search_key: str | None = Field(None, description='Filter results on user or payer first name, last name or email')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')
    form_types: list[Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop']] | None = Field(None, description='The type of the form CrowdFunding, Membership, Event, Donation, PaymentForm, Checkout, Shop')
    with_details: bool = Field(False, description='Set to true to return CustomFields')
    sort_order: Literal['Asc', 'Desc'] | None = Field(None, description='Sort organizations orders by ascending or descending order. Default is descending')


class HelloAssoListFormOrdersConfig(_Input):
    """Get form orders"""
    operation: Literal["list_form_orders"] = Field("list_form_orders", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization slug')
    form_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The form slug')
    form_type: Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop'] = Field(..., description='The form type CrowdFunding, Membership, Event, Donation, PaymentForm, Checkout, Shop')
    from_date: datetime | None = Field(None, description='First Date Filter')
    to_date: datetime | None = Field(None, description='End Date Filter (exclusive)')
    user_search_key: str | None = Field(None, description='Filter results on user or payer first name, last name or email')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')
    with_details: bool = Field(False, description='Set to true to return CustomFields')
    sort_order: Literal['Asc', 'Desc'] | None = Field(None, description='Sort forms orders by ascending or descending order. Default is descending')


class HelloAssoGetOrderConfig(_Input):
    """Get detailed information about a specific order"""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, le=2147483647, description='The order ID')
    with_form_data: bool = Field(False, description='Set to true to include form data in the response')
    check_payments_refund_eligibility: bool = Field(False, description='Set to true to check if payments are eligible to refund or not')


class HelloAssoListOrganizationPaymentsConfig(_Input):
    """Get information about payments made to a specific organization"""
    operation: Literal["list_organization_payments"] = Field("list_organization_payments", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization Slug')
    from_date: datetime | None = Field(None, description='First Date Filter')
    to_date: datetime | None = Field(None, description='End Date Filter (exclusive)')
    user_search_key: str | None = Field(None, description='Filter results on user or payer first name, last name or email')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')
    states: list[Literal['Pending', 'Authorized', 'Refused', 'Unknown', 'Registered', 'Error', 'Refunded', 'Refunding', 'Waiting', 'Canceled', 'Contested', 'WaitingBankValidation', 'WaitingBankWithdraw', 'Abandoned', 'WaitingAuthentication', 'AuthorizedPreprod', 'Corrected', 'Deleted', 'Inconsistent', 'NoDonation', 'Init']] | None = Field(None, description='The payment states\n\nAvailable values:\n* `Pending` - A payment scheduled at a later date, not yet processed.\n* `Authorized` - The payment has been authorized, validated, processed.\n* `Refused` - The payment has been refused by the bank.\n* `Unknown`\n* `Registered` - Represents a payment made offline.\n            Probably for an item of type\n* `Refunded` - The payment has been refunded.\n* `Refunding` - The payment is being refunded.\n* `Contested` - Payment has been contested by the contributor\n* `WaitingBankValidation` - The payment is pending validation from the bank (used by SEPA direct debit).')
    sort_order: Literal['Asc', 'Desc'] | None = Field(None, description='Sort payments by ascending or descending order. Default is descending')
    sort_field: Literal['Date', 'UpdateDate', 'CreationDate'] | None = Field(None, description='Sort payments by a specific field (Date or UpdateDate). Default is date')


class HelloAssoListFormPaymentsConfig(_Input):
    """Get information about payments made in a specific form"""
    operation: Literal["list_form_payments"] = Field("list_form_payments", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization slug')
    form_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The form slug')
    form_type: Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop'] = Field(..., description='The form type CrowdFunding, Membership, Event, Donation, PaymentForm, Checkout, Shop')
    from_date: datetime | None = Field(None, description='First Date Filter')
    to_date: datetime | None = Field(None, description='End Date Filter (exclusive)')
    user_search_key: str | None = Field(None, description='Filter results on user or payer first name, last name or email')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')
    states: list[Literal['Pending', 'Authorized', 'Refused', 'Unknown', 'Registered', 'Error', 'Refunded', 'Refunding', 'Waiting', 'Canceled', 'Contested', 'WaitingBankValidation', 'WaitingBankWithdraw', 'Abandoned', 'WaitingAuthentication', 'AuthorizedPreprod', 'Corrected', 'Deleted', 'Inconsistent', 'NoDonation', 'Init']] | None = Field(None, description='Filter results by states of payments\n\nAvailable values:\n* `Pending` - A payment scheduled at a later date, not yet processed.\n* `Authorized` - The payment has been authorized, validated, processed.\n* `Refused` - The payment has been refused by the bank.\n* `Unknown`\n* `Registered` - Represents a payment made offline.\n            Probably for an item of type\n* `Refunded` - The payment has been refunded.\n* `Refunding` - The payment is being refunded.\n* `Contested` - Payment has been contested by the contributor\n* `WaitingBankValidation` - The payment is pending validation from the bank (used by SEPA direct debit).')
    sort_order: Literal['Asc', 'Desc'] | None = Field(None, description='Sort payments by ascending or descending order. Default is descending')
    sort_field: Literal['Date', 'UpdateDate', 'CreationDate'] | None = Field(None, description='Sort payments by a specific field (Date or UpdateDate). Default is date')


class HelloAssoGetPaymentConfig(_Input):
    """Get detailed information about a specific payment."""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    payment_id: int = Field(..., ge=1, le=2147483647, description='The payment identifier.')
    with_failed_refund_operation: bool = Field(False, description="True to retrieve the refund operation in the states 'ABORTED', 'CANCELED', 'ERROR', 'REFUSED'.")


class HelloAssoListOrganizationItemsConfig(_Input):
    """Get a list of items sold by an organization"""
    operation: Literal["list_organization_items"] = Field("list_organization_items", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization slug')
    from_date: datetime | None = Field(None, description='First Date Filter')
    to_date: datetime | None = Field(None, description='End Date Filter (exclusive)')
    user_search_key: str | None = Field(None, description='Filter results on user or payer first name, last name or email')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')
    tier_types: list[Literal['Donation', 'Payment', 'Registration', 'Membership', 'MonthlyDonation', 'MonthlyPayment', 'OfflineDonation', 'Contribution', 'Bonus', 'Product', 'Insurance']] | None = Field(None, description='The type of tiers Donation, Payment, Registration, Membership, MonthlyDonation, MonthlyPayment, OfflineDonation, Contribution, Bonus')
    item_states: list[Literal['Waiting', 'Processed', 'Registered', 'Deleted', 'Unknown', 'Canceled', 'Refused', 'Abandoned']] | None = Field(None, description='The item states\n\nAvailable values:\n* `Processed` - The item is paid and is valid\n* `Registered` - The item has been registered manually by the organization and is valid\n* `Unknown`\n* `Canceled` - The item has been canceled, and is no longer valid')
    tier_name: str | None = Field(None, description='The name of a tier')
    with_details: bool = Field(False, description='Set to true to return CustomFields and Options')
    sort_order: Literal['Asc', 'Desc'] | None = Field(None, description='Sort organizations items by ascending or descending order. Default is descending')
    sort_field: Literal['Date', 'UpdateDate', 'CreationDate'] | None = Field(None, description='Sort organizations items by a specific field (Date or UpdateDate). Default is date')


class HelloAssoListFormItemsConfig(_Input):
    """Get a list of items "sold" in a form"""
    operation: Literal["list_form_items"] = Field("list_form_items", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization slug')
    form_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The form slug')
    form_type: Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop'] = Field(..., description='The form type CrowdFunding, Membership, Event, Donation, PaymentForm, Checkout, Shop')
    from_date: datetime | None = Field(None, description='First Date Filter')
    to_date: datetime | None = Field(None, description='End Date Filter (exclusive)')
    user_search_key: str | None = Field(None, description='Filter results on user or payer first name, last name or email')
    page_index: int = Field(1, ge=1, le=2147483647, description='The page of results to retrieve')
    page_size: int = Field(20, ge=1, le=100, description='The number of items per page')
    continuation_token: str | None = Field(None, description='Continuation Token from which we wish to retrieve results')
    tier_types: list[Literal['Donation', 'Payment', 'Registration', 'Membership', 'MonthlyDonation', 'MonthlyPayment', 'OfflineDonation', 'Contribution', 'Bonus', 'Product', 'Insurance']] | None = Field(None, description='The type of tiers')
    item_states: list[Literal['Waiting', 'Processed', 'Registered', 'Deleted', 'Unknown', 'Canceled', 'Refused', 'Abandoned']] | None = Field(None, description='The item states\n\nAvailable values:\n* `Processed` - The item is paid and is valid\n* `Registered` - The item has been registered manually by the organization and is valid\n* `Unknown`\n* `Canceled` - The item has been canceled, and is no longer valid')
    tier_name: str | None = Field(None, description='The name of a tier')
    with_details: bool = Field(False, description='Set to true to return CustomFields and Options')
    sort_order: Literal['Asc', 'Desc'] | None = Field(None, description='Sort forms items by ascending or descending order. Default is descending')
    sort_field: Literal['Date', 'UpdateDate', 'CreationDate'] | None = Field(None, description='Sort forms items by a specific field (Date or UpdateDate). Default is date')


class HelloAssoGetItemConfig(_Input):
    """Get the detail of an item contained in an order"""
    operation: Literal["get_item"] = Field("get_item", json_schema_extra={"ui:hidden": True})
    item_id: int = Field(..., ge=1, le=2147483647, description='The item ID')
    with_details: bool = Field(False, description='Set to true to return CustomFields and Options')


class HelloAssoGetCheckoutIntentConfig(_Input):
    """Retrieve a checkout intent, with the order if the payment has been authorized."""
    operation: Literal["get_checkout_intent"] = Field("get_checkout_intent", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    checkout_intent_id: int = Field(..., ge=1, le=2147483647)
    with_failed_refund_operation: bool = Field(False)


class HelloAssoCreateCheckoutIntentConfig(_Input):
    """Init a checkout."""
    operation: Literal["create_checkout_intent"] = Field("create_checkout_intent", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    body: CheckoutBody = Field(..., description="HelloAsso request body.")


class HelloAssoCreateEventConfig(_Input):
    """Create a simplified event for an Organism"""
    operation: Literal["create_event"] = Field("create_event", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description='The organization Slug')
    form_type: Literal["Event"] = Field("Event", description='The form type to create - only Event type is supported')
    body: EventBody = Field(..., description="HelloAsso request body.")


class HelloAssoUpdateFormStateConfig(_Input):
    """Update a form state"""
    operation: Literal["update_form_state"] = Field("update_form_state", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    form_slug: str = Field(..., min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    form_type: Literal['CrowdFunding', 'Membership', 'Event', 'Donation', 'PaymentForm', 'Checkout', 'Shop'] = Field(...)
    body: FormStateBody = Field(..., description="HelloAsso request body.")


class HelloAssoCancelOrderConfig(_Input):
    """Cancels future payments for an order, no refunds will be given."""
    operation: Literal["cancel_order"] = Field("cancel_order", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, le=2147483647, description='The order identifier.')


class HelloAssoRefundPaymentConfig(_Input):
    """Refund a payment."""
    operation: Literal["refund_payment"] = Field("refund_payment", json_schema_extra={"ui:hidden": True})
    payment_id: int = Field(..., ge=1, le=2147483647, description='The payment identifier.')
    comment: str | None = Field(None, description='The comment about this refund.')
    cancel_order: bool = Field(False, description='Whether the future payments and linked items of this order must be canceled (possible only if the payment is fully refunded)')
    send_refund_mail: bool = Field(True, description='Whether a refund mail must be sent or not.')
    amount: int = Field(0, ge=0, le=2147483647, description='The amount in cents to refund. Enter this amount only for a partial refund for stripe. If not filled in then the entire payment is refunded')
    x_mfa_access_authorization: str | None = Field(None, json_schema_extra={"ui:widget": "password"}, description='Must be filled only if AuthorizationErrors.MFA.AccessTokenRequired error code was returned previously.')
    x_mfa_sms_access_authorization: str | None = Field(None, json_schema_extra={"ui:widget": "password"}, description='Must be filled only if AuthorizationErrors.MFA.AccessOtpSmsRequired error code was returned previously.')
    x_mfa_password_authorization: str | None = Field(None, json_schema_extra={"ui:widget": "password"}, description='Must be filled only if AuthorizationErrors.MFA.AccessPasswordTokenRequired error code was returned previously.')


HelloAssoConfig = Annotated[Union[
    HelloAssoListMyOrganizationsConfig,
    HelloAssoGetOrganizationConfig,
    HelloAssoListFormsConfig,
    HelloAssoListFormTypesConfig,
    HelloAssoGetFormConfig,
    HelloAssoGetFormStatsConfig,
    HelloAssoListOrganizationOrdersConfig,
    HelloAssoListFormOrdersConfig,
    HelloAssoGetOrderConfig,
    HelloAssoListOrganizationPaymentsConfig,
    HelloAssoListFormPaymentsConfig,
    HelloAssoGetPaymentConfig,
    HelloAssoListOrganizationItemsConfig,
    HelloAssoListFormItemsConfig,
    HelloAssoGetItemConfig,
    HelloAssoGetCheckoutIntentConfig,
    HelloAssoCreateCheckoutIntentConfig,
    HelloAssoCreateEventConfig,
    HelloAssoUpdateFormStateConfig,
    HelloAssoCancelOrderConfig,
    HelloAssoRefundPaymentConfig
], Field(discriminator="operation")]


class HelloAssoFullConfig(NodeConfig[HelloAssoConfig, HelloAssoAccessToken]):
    pass


# Fixed routes and parameter locations from the pinned public v5 contract.
ROUTES = {'list_my_organizations': ('GET', '/users/me/organizations'),
 'get_organization': ('GET', '/organizations/{organizationSlug}'),
 'list_forms': ('GET', '/organizations/{organizationSlug}/forms'),
 'list_form_types': ('GET', '/organizations/{organizationSlug}/formTypes'),
 'get_form': ('GET', '/organizations/{organizationSlug}/forms/{formType}/{formSlug}/public'),
 'get_form_stats': ('GET', '/organizations/{organizationSlug}/forms/{formType}/{formSlug}/stats'),
 'list_organization_orders': ('GET', '/organizations/{organizationSlug}/orders'),
 'list_form_orders': ('GET',
                      '/organizations/{organizationSlug}/forms/{formType}/{formSlug}/orders'),
 'get_order': ('GET', '/orders/{orderId}'),
 'list_organization_payments': ('GET', '/organizations/{organizationSlug}/payments'),
 'list_form_payments': ('GET',
                        '/organizations/{organizationSlug}/forms/{formType}/{formSlug}/payments'),
 'get_payment': ('GET', '/payments/{paymentId}'),
 'list_organization_items': ('GET', '/organizations/{organizationSlug}/items'),
 'list_form_items': ('GET', '/organizations/{organizationSlug}/forms/{formType}/{formSlug}/items'),
 'get_item': ('GET', '/items/{itemId}'),
 'get_checkout_intent': ('GET',
                         '/organizations/{organizationSlug}/checkout-intents/{checkoutIntentId}'),
 'create_checkout_intent': ('POST', '/organizations/{organizationSlug}/checkout-intents'),
 'create_event': ('POST', '/organizations/{organizationSlug}/forms/{formType}/action/quick-create'),
 'update_form_state': ('PUT',
                       '/organizations/{organizationSlug}/forms/{formType}/{formSlug}/state'),
 'cancel_order': ('POST', '/orders/{orderId}/cancel'),
 'refund_payment': ('POST', '/payments/{paymentId}/refund')}

PARAMETERS = {'list_my_organizations': {},
 'get_organization': {'organization_slug': ('path', 'organizationSlug')},
 'list_forms': {'organization_slug': ('path', 'organizationSlug'),
                'states': ('query', 'states'),
                'form_types': ('query', 'formTypes'),
                'page_index': ('query', 'pageIndex'),
                'page_size': ('query', 'pageSize'),
                'continuation_token': ('query', 'continuationToken')},
 'list_form_types': {'organization_slug': ('path', 'organizationSlug'),
                     'states': ('query', 'states')},
 'get_form': {'organization_slug': ('path', 'organizationSlug'),
              'form_type': ('path', 'formType'),
              'form_slug': ('path', 'formSlug')},
 'get_form_stats': {'organization_slug': ('path', 'organizationSlug'),
                    'form_slug': ('path', 'formSlug'),
                    'form_type': ('path', 'formType')},
 'list_organization_orders': {'organization_slug': ('path', 'organizationSlug'),
                              'from_date': ('query', 'from'),
                              'to_date': ('query', 'to'),
                              'user_search_key': ('query', 'userSearchKey'),
                              'page_index': ('query', 'pageIndex'),
                              'page_size': ('query', 'pageSize'),
                              'continuation_token': ('query', 'continuationToken'),
                              'form_types': ('query', 'formTypes'),
                              'with_details': ('query', 'withDetails'),
                              'sort_order': ('query', 'sortOrder')},
 'list_form_orders': {'organization_slug': ('path', 'organizationSlug'),
                      'form_slug': ('path', 'formSlug'),
                      'form_type': ('path', 'formType'),
                      'from_date': ('query', 'from'),
                      'to_date': ('query', 'to'),
                      'user_search_key': ('query', 'userSearchKey'),
                      'page_index': ('query', 'pageIndex'),
                      'page_size': ('query', 'pageSize'),
                      'continuation_token': ('query', 'continuationToken'),
                      'with_details': ('query', 'withDetails'),
                      'sort_order': ('query', 'sortOrder')},
 'get_order': {'order_id': ('path', 'orderId'),
               'with_form_data': ('query', 'withFormData'),
               'check_payments_refund_eligibility': ('query', 'checkPaymentsRefundEligibility')},
 'list_organization_payments': {'organization_slug': ('path', 'organizationSlug'),
                                'from_date': ('query', 'from'),
                                'to_date': ('query', 'to'),
                                'user_search_key': ('query', 'userSearchKey'),
                                'page_index': ('query', 'pageIndex'),
                                'page_size': ('query', 'pageSize'),
                                'continuation_token': ('query', 'continuationToken'),
                                'states': ('query', 'states'),
                                'sort_order': ('query', 'sortOrder'),
                                'sort_field': ('query', 'sortField')},
 'list_form_payments': {'organization_slug': ('path', 'organizationSlug'),
                        'form_slug': ('path', 'formSlug'),
                        'form_type': ('path', 'formType'),
                        'from_date': ('query', 'from'),
                        'to_date': ('query', 'to'),
                        'user_search_key': ('query', 'userSearchKey'),
                        'page_index': ('query', 'pageIndex'),
                        'page_size': ('query', 'pageSize'),
                        'continuation_token': ('query', 'continuationToken'),
                        'states': ('query', 'states'),
                        'sort_order': ('query', 'sortOrder'),
                        'sort_field': ('query', 'sortField')},
 'get_payment': {'payment_id': ('path', 'paymentId'),
                 'with_failed_refund_operation': ('query', 'withFailedRefundOperation')},
 'list_organization_items': {'organization_slug': ('path', 'organizationSlug'),
                             'from_date': ('query', 'from'),
                             'to_date': ('query', 'to'),
                             'user_search_key': ('query', 'userSearchKey'),
                             'page_index': ('query', 'pageIndex'),
                             'page_size': ('query', 'pageSize'),
                             'continuation_token': ('query', 'continuationToken'),
                             'tier_types': ('query', 'tierTypes'),
                             'item_states': ('query', 'itemStates'),
                             'tier_name': ('query', 'tierName'),
                             'with_details': ('query', 'withDetails'),
                             'sort_order': ('query', 'sortOrder'),
                             'sort_field': ('query', 'sortField')},
 'list_form_items': {'organization_slug': ('path', 'organizationSlug'),
                     'form_slug': ('path', 'formSlug'),
                     'form_type': ('path', 'formType'),
                     'from_date': ('query', 'from'),
                     'to_date': ('query', 'to'),
                     'user_search_key': ('query', 'userSearchKey'),
                     'page_index': ('query', 'pageIndex'),
                     'page_size': ('query', 'pageSize'),
                     'continuation_token': ('query', 'continuationToken'),
                     'tier_types': ('query', 'tierTypes'),
                     'item_states': ('query', 'itemStates'),
                     'tier_name': ('query', 'tierName'),
                     'with_details': ('query', 'withDetails'),
                     'sort_order': ('query', 'sortOrder'),
                     'sort_field': ('query', 'sortField')},
 'get_item': {'item_id': ('path', 'itemId'), 'with_details': ('query', 'withDetails')},
 'get_checkout_intent': {'organization_slug': ('path', 'organizationSlug'),
                         'checkout_intent_id': ('path', 'checkoutIntentId'),
                         'with_failed_refund_operation': ('query', 'withFailedRefundOperation')},
 'create_checkout_intent': {'organization_slug': ('path', 'organizationSlug')},
 'create_event': {'organization_slug': ('path', 'organizationSlug'),
                  'form_type': ('path', 'formType')},
 'update_form_state': {'organization_slug': ('path', 'organizationSlug'),
                       'form_slug': ('path', 'formSlug'),
                       'form_type': ('path', 'formType')},
 'cancel_order': {'order_id': ('path', 'orderId')},
 'refund_payment': {'payment_id': ('path', 'paymentId'),
                    'comment': ('query', 'comment'),
                    'cancel_order': ('query', 'cancelOrder'),
                    'send_refund_mail': ('query', 'sendRefundMail'),
                    'amount': ('query', 'amount'),
                    'x_mfa_access_authorization': ('header', 'x-mfa-access-authorization'),
                    'x_mfa_sms_access_authorization': ('header', 'x-mfa-sms-access-authorization'),
                    'x_mfa_password_authorization': ('header', 'x-mfa-password-authorization')}}


class HelloAssoNode(WorkflowNode):
    integration_type = "automation-helloasso"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_my_organizations")

    @classmethod
    def get_config_model(cls):
        return HelloAssoFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a HelloAsso access token")
        config = self.config.config
        operation = config.operation
        method, path = ROUTES[operation]
        headers = {"Authorization": "Bearer " + self.config.credentials.access_token, "Accept": "application/json"}
        params = []
        values = config.model_dump(mode="json", exclude_none=True)
        for field, (location, wire) in PARAMETERS[operation].items():
            if field not in values:
                continue
            value = values[field]
            if location == "path":
                path = path.replace("{" + wire + "}", quote(str(value), safe=""))
            elif location == "header":
                headers[wire] = value
            else:
                # OpenAPI form/explode arrays are repeated query parameters.
                for item in value if isinstance(value, list) else [value]:
                    params.append((wire, str(item).lower() if isinstance(item, bool) else str(item)))
        kwargs = {"headers": headers, "params": params}
        if "body" in values:
            kwargs["json"] = values["body"]
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        # Preserve the provider rejection text for connection verification.
        if not 200 <= response.status_code < 300:
            return {"status": "error", "operation": operation, "http_status": response.status_code,
                    "error": response.text}
        if not response.content:
            if operation not in {"cancel_order", "update_form_state"}:
                raise ValueError("HelloAsso returned an empty response for a data operation")
            return {"status": "success", "operation": operation, "data": None}
        body = response.json()
        if operation == "list_my_organizations" and not isinstance(body, list):
            raise ValueError("HelloAsso organizations response must be an array")
        # Keep the provider envelope, including pagination.continuationToken.
        # List operations fetch exactly one page; they never imply completeness.
        return {"status": "success", "operation": operation, "data": body}
