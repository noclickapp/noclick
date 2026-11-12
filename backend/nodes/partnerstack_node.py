"""PartnerStack vendor API: fixed operations using manually supplied API keys.

Contract: https://api.partnerstack.com/api/openapi?type=vendor (2.0.0).
Authentication: https://docs.partnerstack.com/reference/auth
List executions return one page; writes are never automatically retried.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.partnerstack.com/api"


class PartnerStackAPIKeys(BaseModel):
    model_config = ConfigDict(title="Partnerstack API Keys", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.partnerstack.com/settings/integrations",
            "x-credential-instructions": "In your vendor dashboard, open Settings → Integrations → PartnerStack API Keys. Paste the public and secret keys from the same test or production pair. Test keys work with test partners and customers; production keys perform live actions. NoClick sends these keys over HTTPS using Basic authentication.",
        })
    credential_type: Literal["partnerstack_api_keys"] = Field("partnerstack_api_keys", json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., title="Public Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., title="Secret Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("public_key", "secret_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the key without a Basic prefix, colon or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name == "close_date" and value is not None:
            date.fromisoformat(value)
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}", value) or value in {".", ".."}:
                raise ValueError("Use a single PartnerStack identifier, without slashes or URL encoding")
        return value

    @model_validator(mode="after")
    def writes_and_cursors(self):
        values = self.model_dump(exclude_none=True)
        if values.get("starting_after") and values.get("ending_before"):
            raise ValueError("Use either starting_after or ending_before")
        if self.operation.startswith("update_") and not (set(values) - {"operation", "customer_id", "lead_id", "deal_id", "partnership_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class _Page(_Input):
    limit: int = Field(10, ge=1, le=250, title="Page Size", description="Each execution returns one page, up to 250 records.")
    starting_after: str | None = Field(None, max_length=255, title="Starting After", description="Item key from the previous page; mutually exclusive with Ending Before.")
    ending_before: str | None = Field(None, max_length=255, title="Ending Before", description="Item key for reverse pagination; mutually exclusive with Starting After.")


class ListCustomers(_Page):
    """List all customers."""
    operation: Literal['list_customers'] = Field('list_customers', title='List Customers', json_schema_extra={"ui:hidden": True})
    partner_key: str | None = Field(None, title='Partner Key')
    partnership_key: str | None = Field(None, title='Partnership Key')
    group: str | None = Field(None, title='Group')
    min_created: int | None = Field(None, title='Min Created')
    max_created: int | None = Field(None, title='Max Created')
    min_updated: int | None = Field(None, title='Min Updated')
    max_updated: int | None = Field(None, title='Max Updated')


class GetCustomer(_Input):
    """Retrieve a customer."""
    operation: Literal['get_customer'] = Field('get_customer', title='Get Customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=255, title='Customer Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class CreateCustomer(_Input):
    """Create a customer."""
    operation: Literal['create_customer'] = Field('create_customer', title='Create Customer', json_schema_extra={"ui:hidden": True})
    customer_key: str = Field(..., title='Customer Key', description='External customer key that can be configured on creation.', min_length=1, max_length=255)
    partner_key: str = Field(..., title='Partner Key', description='The key of the partner that is responsible for the customer **(note: `partner_key` must belong to a partner in your program)**.', min_length=1, max_length=2000)
    email: str = Field(..., title='Email', json_schema_extra={"format": "email"}, description='The customers email, must be a valid email', min_length=4, max_length=255)
    name: str | None = Field(None, title='Name', description="Should be either the customer's name, or the company name", min_length=1, max_length=100)
    provider_key: str | None = Field(None, title='Provider Key', description='A unique identifier given by a payment provider (Stripe, Recurly, Chargebee etc)', min_length=1, max_length=255)
    member_key: str | None = Field(None, title='Member Key', description='The key of the member that is responsible for the customer **(note: `member_key` must belong to a team member of a partner in your program)**.', min_length=1, max_length=2000)
    meta: dict[str, object] | None = Field(None, title='Meta', description='Additional custom fields for the customer that is configured in your PartnerStack dashboard.')
    created_at: int | None = Field(None, title='Created At', description='The timestamp of the customer creation in epoch milliseconds.')


class UpdateCustomer(_Input):
    """Update a customer."""
    operation: Literal['update_customer'] = Field('update_customer', title='Update Customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=255, title='Customer Id', description="The existing resource key or documented external identifier; used only in the URL path.")
    customer_key: str | None = Field(None, title='Customer Key', description='External customer key that can be configured on creation.', min_length=1, max_length=255)
    email: str | None = Field(None, title='Email', json_schema_extra={"format": "email"}, description='The customers email, must be a valid email', min_length=4, max_length=255)
    name: str | None = Field(None, title='Name', description="Should be either the customer's name, or the company name", min_length=1, max_length=100)
    provider_key: str | None = Field(None, title='Provider Key', description='A unique identifier given by a payment provider (Stripe, Recurly, Chargebee etc)', min_length=1, max_length=255)
    member_key: str | None = Field(None, title='Member Key', description='The key of the member that is responsible for the customer **(note: `member_key` must belong to a team member of a partner in your program)**.', min_length=1, max_length=2000)
    meta: dict[str, object] | None = Field(None, title='Meta', description='Additional custom fields for the customer that is configured in your PartnerStack dashboard.')


class DeleteCustomer(_Input):
    """Delete a customer."""
    operation: Literal['delete_customer'] = Field('delete_customer', title='Delete Customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=255, title='Customer Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class ListLeads(_Page):
    """List all leads."""
    operation: Literal['list_leads'] = Field('list_leads', title='List Leads', json_schema_extra={"ui:hidden": True})
    partner_key: str | None = Field(None, title='Partner Key')
    group: str | None = Field(None, title='Group')
    min_created: int | None = Field(None, title='Min Created')
    max_created: int | None = Field(None, title='Max Created')
    min_updated: int | None = Field(None, title='Min Updated')
    max_updated: int | None = Field(None, title='Max Updated')


class GetLead(_Input):
    """Retrieve a lead."""
    operation: Literal['get_lead'] = Field('get_lead', title='Get Lead', json_schema_extra={"ui:hidden": True})
    lead_id: str = Field(..., min_length=1, max_length=255, title='Lead Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class LeadMeta(BaseModel):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    first_name: str = Field(..., min_length=1, title="First Name")
    last_name: str = Field(..., min_length=1, title="Last Name")
    company: str = Field(..., min_length=1, title="Company")
    email: str | None = Field(None, title="Email")


class CreateLead(_Input):
    """Create a lead."""
    operation: Literal['create_lead'] = Field('create_lead', title='Create Lead', json_schema_extra={"ui:hidden": True})
    external_key: str = Field(..., title='External Key', description='A unique key that identifies this lead in an external system. This key must be unique across all leads in your account. This key is used to identify leads when they are updated or deleted. Often provided as an email, but can be any unique string.', min_length=1, max_length=2000)
    partner_key: str = Field(..., title='Partner Key', description='The unique key of the partner who submitted this lead', min_length=1, max_length=255)
    meta: LeadMeta = Field(..., title='Meta', description='Key value pairs that store additional information about this lead. First and last name required. Other eligible keys are based on Lead forms created. Use the /leads/form-template to view field names')
    amount: int | None = Field(None, title='Amount', description='Lead amount in **cents**')
    status: Literal['open', 'closed', 'dead', 'closed won', 'closed lost'] | None = Field(None, title='Status', description="Current status of this lead. Must be one of either 'open', 'closed', 'dead', 'closed won', or 'closed lost'. Note that open = New, closed = Qualified and dead = Unqualified default stages in the PartnerStack dashboard.", min_length=1, max_length=2000)
    stage_api_name: str | None = Field(None, title='Stage Api Name', description='The api_name of the Stage this lead should be in. This is used to determine the current stage of the lead. If not provided, the lead will be placed in the first stage of the sales cycle.', min_length=1, max_length=2000)
    approved: bool | None = Field(None, title='Approved', description='Used to indicate whether this lead has been approved to move past the closed stage')

    @model_validator(mode="after")
    def stage_required(self):
        if not self.status and not self.stage_api_name:
            raise ValueError("Supply Status or Stage API Name")
        return self


class UpdateLead(_Input):
    """Update a lead."""
    operation: Literal['update_lead'] = Field('update_lead', title='Update Lead', json_schema_extra={"ui:hidden": True})
    lead_id: str = Field(..., min_length=1, max_length=255, title='Lead Id', description="The existing resource key or documented external identifier; used only in the URL path.")
    external_key: str | None = Field(None, title='External Key', description='A unique key that identifies this lead in an external system. This key must be unique across all leads in your account. This key is used to identify leads when they are updated or deleted. Often provided as an email, but can be any unique string.', min_length=1, max_length=2000)
    partner_key: str | None = Field(None, title='Partner Key', description='The unique key of the partner who submitted this lead', min_length=1, max_length=255)
    meta: dict[str, object] | None = Field(None, title='Meta', description='Key value pairs that store additional information about this lead. First and last name required. Other eligible keys are based on Lead forms created. Use the /leads/form-template to view field names')
    amount: int | None = Field(None, title='Amount', description='Lead amount in **cents**')
    status: Literal['open', 'closed', 'dead', 'closed won', 'closed lost'] | None = Field(None, title='Status', description="Current status of this lead. Must be one of either 'open', 'closed', 'dead', 'closed won', or 'closed lost. Note that open = New, closed = Qualified and dead = Unqualified default stages in the PartnerStack dashboard.'", min_length=1, max_length=2000)
    approved: bool | None = Field(None, title='Approved', description='Used to indicate whether this lead has been approved to move past the closed stage')
    customer_key: str | None = Field(None, title='Customer Key', description='Unique identifier to be used for Customer after a lead has been converted', min_length=1, max_length=2000)


class ArchiveLead(_Input):
    """Archive a lead."""
    operation: Literal['archive_lead'] = Field('archive_lead', title='Archive Lead', json_schema_extra={"ui:hidden": True})
    lead_id: str = Field(..., min_length=1, max_length=255, title='Lead Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class ListDeals(_Page):
    """List all deals."""
    operation: Literal['list_deals'] = Field('list_deals', title='List Deals', json_schema_extra={"ui:hidden": True})
    partner_key: str | None = Field(None, title='Partner Key')
    group: str | None = Field(None, title='Group')
    min_created: int | None = Field(None, title='Min Created')
    max_created: int | None = Field(None, title='Max Created')
    min_updated: int | None = Field(None, title='Min Updated')
    max_updated: int | None = Field(None, title='Max Updated')


class GetDeal(_Input):
    """Retrieve a deal."""
    operation: Literal['get_deal'] = Field('get_deal', title='Get Deal', json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., min_length=1, max_length=255, title='Deal Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class CreateDeal(_Input):
    """Create a deal."""
    operation: Literal['create_deal'] = Field('create_deal', title='Create Deal', json_schema_extra={"ui:hidden": True})
    account_name: str = Field(..., title='Account Name', description='Name of the account', min_length=1, max_length=255)
    contact_first_name: str = Field(..., title='Contact First Name', description="First name of the account's contact", min_length=1, max_length=255)
    contact_last_name: str = Field(..., title='Contact Last Name', description="Last name of the account's contact", min_length=1, max_length=255)
    amount: int = Field(..., title='Amount', description='Deal amount in **cents**')
    stage: str = Field(..., title='Stage', description='Current stage of this deal. Must appear in Deals Stage list found in group settings.', min_length=1, max_length=255)
    close_date: str = Field(..., title='Close Date', json_schema_extra={"format": "date"}, description='Expected close date of deal as YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS or full ISO 8601 with timezone', min_length=1, max_length=2000)
    customer_key: str | None = Field(None, title='Customer Key', description='The unique key of the customer to associate with this deal. The customer must belong to the specified partner.', min_length=1, max_length=2000)
    source: Literal['partner', 'vendor'] | None = Field(None, title='Source', description="Source of the deal, either 'partner' or 'vendor', defaults to 'partner' if not specified", min_length=1, max_length=2000)
    team_member_email: str | None = Field(None, title='Team Member Email', description='The email of the partner team member who submitted this deal. To select a team member, please pass either the personal_stack_key or the team_member_email. Partner source only.', min_length=1, max_length=2000)
    personal_stack_key: str | None = Field(None, title='Personal Stack Key', description='The unique personal stack_key of the partner team member who submitted this deal. To select a team member, please pass either the personal_stack_key or the team_member_email. Partner source only.', min_length=1, max_length=2000)
    meta: dict[str, object] | None = Field(None, title='Meta', description='Provider custom field values.')


    group_key: str | None = Field(None, title="Group Key", max_length=255, description="Supply either Group Key or Partner Key, exclusively.")
    partner_key: str | None = Field(None, title="Partner Key", max_length=255, description="Supply either Partner Key or Group Key, exclusively.")

    @model_validator(mode="after")
    def association_required(self):
        if bool(self.group_key) == bool(self.partner_key):
            raise ValueError("Supply exactly one of Group Key and Partner Key")
        return self


class UpdateDeal(_Input):
    """Update a deal."""
    operation: Literal['update_deal'] = Field('update_deal', title='Update Deal', json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., min_length=1, max_length=255, title='Deal Id', description="The existing resource key or documented external identifier; used only in the URL path.")
    account_name: str | None = Field(None, title='Account Name', description='Name of the account', min_length=1, max_length=255)
    contact_first_name: str | None = Field(None, title='Contact First Name', description="First name of the account's contact", min_length=1, max_length=255)
    contact_last_name: str | None = Field(None, title='Contact Last Name', description="Last name of the account's contact", min_length=1, max_length=255)
    amount: int | None = Field(None, title='Amount', description='Deal amount in **cents**')
    stage: str | None = Field(None, title='Stage', description='Current stage of this deal. Must appear in Deals Stage list found in group settings.', min_length=1, max_length=255)
    close_date: str | None = Field(None, title='Close Date', json_schema_extra={"format": "date"}, description='Expected close date of deal as YYYY-MM-DD', min_length=1, max_length=2000)
    customer_key: str | None = Field(None, title='Customer Key', description='The unique key of the customer associated with this deal.', min_length=1, max_length=2000)
    external_key: str | None = Field(None, title='External Key', description='Reference that can be used in place of the key.', min_length=1, max_length=2000)
    lost_reason: str | None = Field(None, title='Lost Reason', description='Reason for which the deal was lost.', min_length=1, max_length=2000)
    partner_key: str | None = Field(None, title='Partner Key', description='The unique key of the partner who owns this deal', min_length=1, max_length=255)
    meta: dict[str, object] | None = Field(None, title='Meta', description='Provider custom field values.')


class ArchiveDeal(_Input):
    """Archive a deal."""
    operation: Literal['archive_deal'] = Field('archive_deal', title='Archive Deal', json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., min_length=1, max_length=255, title='Deal Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class ListPartnerships(_Page):
    """List all partnerships."""
    operation: Literal['list_partnerships'] = Field('list_partnerships', title='List Partnerships', json_schema_extra={"ui:hidden": True})
    partnership_key: str | None = Field(None, title='Partnership Key')
    group: str | None = Field(None, title='Group')
    email: str | None = Field(None, title='Email')
    min_created: int | None = Field(None, title='Min Created')
    max_created: int | None = Field(None, title='Max Created')
    min_updated: int | None = Field(None, title='Min Updated')
    max_updated: int | None = Field(None, title='Max Updated')


class GetPartnership(_Input):
    """Retrieve a partnership."""
    operation: Literal['get_partnership'] = Field('get_partnership', title='Get Partnership', json_schema_extra={"ui:hidden": True})
    partnership_id: str = Field(..., min_length=1, max_length=255, title='Partnership Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class CreatePartnership(_Input):
    """Create a partnership."""
    operation: Literal['create_partnership'] = Field('create_partnership', title='Create Partnership', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title='Email', json_schema_extra={"format": "email"}, description='The email of the partner.', min_length=1, max_length=255)
    first_name: str | None = Field(None, title='First Name', description='The first name of the partner.', min_length=1, max_length=50)
    last_name: str | None = Field(None, title='Last Name', description='The last name of the partner.', min_length=1, max_length=50)
    partner_key: str | None = Field(None, title='Partner Key', description='The `partner_key` you wish to use for this partner. If included, **must** be unique to this partner. For more information on `partner_key` see PartnerStackJS. Note that the partner_key can only consist of letters, numbers, and underscores.', min_length=1, max_length=255)
    group_key: str | None = Field(None, title='Group Key', description='The key of the group within PartnerStack that you want this partner to be placed into.', min_length=1, max_length=255)
    notify_by_email: bool = Field(False, title='Notify By Email', description='Whether to send a verification email to the partner.')


class UpdatePartnership(_Input):
    """Update a partnership."""
    operation: Literal['update_partnership'] = Field('update_partnership', title='Update Partnership', json_schema_extra={"ui:hidden": True})
    partnership_id: str = Field(..., min_length=1, max_length=255, title='Partnership Id', description="The existing resource key or documented external identifier; used only in the URL path.")
    group_key: str | None = Field(None, title='Group Key', description='The key of the group within PartnerStack that you want this partner to be placed into.', min_length=1, max_length=255)
    manager_email: str | None = Field(None, title='Manager Email', description='The email of the partner manager that you would like to assign this partner.', min_length=1, max_length=255)
    partner_key: str | None = Field(None, title='Partner Key', description='The partner_key that you would like this partner to have.', min_length=1, max_length=255)
    tier_key: str | None = Field(None, title='Tier Key', description='The key of the tier within PartnerStack that you want this partner to be placed into.', min_length=1, max_length=255)


class ListGroups(_Page):
    """List all groups."""
    operation: Literal['list_groups'] = Field('list_groups', title='List Groups', json_schema_extra={"ui:hidden": True})
    min_created: int | None = Field(None, title='Min Created')
    max_created: int | None = Field(None, title='Max Created')
    min_updated: int | None = Field(None, title='Min Updated')
    max_updated: int | None = Field(None, title='Max Updated')


class ListTransactions(_Page):
    """List all transactions."""
    operation: Literal['list_transactions'] = Field('list_transactions', title='List Transactions', json_schema_extra={"ui:hidden": True})
    customer_key: str | None = Field(None, title='Customer Key')


class CreateTransaction(_Input):
    """Create a transaction."""
    operation: Literal['create_transaction'] = Field('create_transaction', title='Create Transaction', json_schema_extra={"ui:hidden": True})
    amount: int = Field(..., title='Amount', description='Transaction amount in cents for specified currency.', ge=-50000000000, le=50000000000)
    currency: str = Field(..., title='Currency', description='Transaction currency type. Note that the format is the three-letter ISO currency code.', min_length=3, max_length=3)
    customer_key: str = Field(..., title='Customer Key', description='Key of customer who made the transaction.', min_length=1, max_length=255)
    key: str | None = Field(None, title='Key', description='Key of transaction record in PartnerStack.', min_length=4, max_length=255)
    product_key: str | None = Field(None, title='Product Key', description='Key of transaction product.', min_length=1, max_length=255)
    category_key: str | None = Field(None, title='Category Key', description='Key of transaction category.', min_length=1, max_length=255)
    subscription_key: str | None = Field(None, title='Subscription Key', description='External identifier of the subscription/product associated with the transaction.', min_length=1, max_length=255)
    created_at: int | None = Field(None, title='Created At', description='The created_at date of the transaction in epoch (ms).')
    metadata: dict[str, object] | None = Field(None, title='Metadata', description='Additional data that can be provided for the transaction on creation. Note that you can only store a maximum of 25 metadata attributes. The value of each attribute cannot exceed 100 characters, and the name of each attribute cannot exceed 30 characters.')


class DeleteTransaction(_Input):
    """Delete a transaction."""
    operation: Literal['delete_transaction'] = Field('delete_transaction', title='Delete Transaction', json_schema_extra={"ui:hidden": True})
    transaction_id: str = Field(..., min_length=1, max_length=255, title='Transaction Id', description="The existing resource key or documented external identifier; used only in the URL path.")


class ListActions(_Page):
    """List all actions."""
    operation: Literal['list_actions'] = Field('list_actions', title='List Actions', json_schema_extra={"ui:hidden": True})
    partnership_key: str | None = Field(None, title='Partnership Key')
    customer_key: str | None = Field(None, title='Customer Key')
    action_type: str | None = Field(None, title='Action Type')
    min_created: int | None = Field(None, title='Min Created')
    max_created: int | None = Field(None, title='Max Created')
    min_updated: int | None = Field(None, title='Min Updated')
    max_updated: int | None = Field(None, title='Max Updated')


class RecordAction(_Input):
    """Record action."""
    operation: Literal['record_action'] = Field('record_action', title='Record Action', json_schema_extra={"ui:hidden": True})
    type: str = Field(..., title='Type', description='The type of action the partner or customer performed', min_length=1, max_length=2000)
    value: int = Field(..., title='Value', description='The number of times the action was performed', ge=1)
    target_type: Literal['partnership', 'customer'] = Field(..., title='Target Type', description='Whether to record an action under a partnership or customer', min_length=1, max_length=2000)
    target_key: str = Field(..., title='Target Key', description='The identifier of the target specified in `target_type`. For a customer, this is the customer key. For a partnership, it is their partner key.', min_length=1, max_length=2000)
    external_key: str | None = Field(None, title='External Key', description='The external key of the action record in PartnerStack', min_length=1, max_length=2000)
    created_at: int | None = Field(None, title='Created At', description='The created_at date of the action in epoch (ms).')


# PartnerStack's own MCP server: agents get its tools through a person's PartnerStack sign-in.
PartnerstackMcpCredential = mcp_credential("partnerstack", "https://mcp.partnerstack.com/mcp", app="PartnerStack")
PartnerStackCredential = Union[PartnerStackAPIKeys, PartnerstackMcpCredential]


Operation = Annotated[Union[ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, DeleteCustomer, ListLeads, GetLead, CreateLead, UpdateLead, ArchiveLead, ListDeals, GetDeal, CreateDeal, UpdateDeal, ArchiveDeal, ListPartnerships, GetPartnership, CreatePartnership, UpdatePartnership, ListGroups, ListTransactions, CreateTransaction, DeleteTransaction, ListActions, RecordAction], Field(discriminator="operation")]


class PartnerStackConfig(NodeConfig[Operation, PartnerStackCredential]):
    pass


ROUTES = {
    'list_customers': ('GET', '/v2/customers', None),
    'get_customer': ('GET', '/v2/customers/{customer_key}', 'customer_id'),
    'create_customer': ('POST', '/v2/customers', None),
    'update_customer': ('PATCH', '/v2/customers/{customer_key}', 'customer_id'),
    'delete_customer': ('DELETE', '/v2/customers/{customer_key}', 'customer_id'),
    'list_leads': ('GET', '/v2/leads', None),
    'get_lead': ('GET', '/v2/leads/{lead_key}', 'lead_id'),
    'create_lead': ('POST', '/v2/leads', None),
    'update_lead': ('PATCH', '/v2/leads/{lead_key}', 'lead_id'),
    'archive_lead': ('DELETE', '/v2/leads/{lead_key}', 'lead_id'),
    'list_deals': ('GET', '/v2/deals', None),
    'get_deal': ('GET', '/v2/deals/{deal_key}', 'deal_id'),
    'create_deal': ('POST', '/v2/deals', None),
    'update_deal': ('PATCH', '/v2/deals/{deal_key}', 'deal_id'),
    'archive_deal': ('DELETE', '/v2/deals/{deal_key}', 'deal_id'),
    'list_partnerships': ('GET', '/v2/partnerships', None),
    'get_partnership': ('GET', '/v2/partnerships/{unique_identifier}', 'partnership_id'),
    'create_partnership': ('POST', '/v2/partnerships', None),
    'update_partnership': ('PATCH', '/v2/partnerships/{partnership_key}', 'partnership_id'),
    'list_groups': ('GET', '/v2/groups', None),
    'list_transactions': ('GET', '/v2/transactions', None),
    'create_transaction': ('POST', '/v2/transactions', None),
    'delete_transaction': ('DELETE', '/v2/transactions/{transaction_key}', 'transaction_id'),
    'list_actions': ('GET', '/v2/actions', None),
    'record_action': ('POST', '/v2/actions', None),
}


class PartnerStackNode(WorkflowNode):
    integration_type = "automation-partnerstack"
    credential_provider_labels = {"partnerstack": "PartnerStack Account"}
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="partner groups", label_keys=("name", "slug", "key"))

    @classmethod
    def get_config_model(cls):
        return PartnerStackConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect PartnerStack vendor API keys")
        config = self.config.config
        method, template, path_field = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        if path_field:
            identifier = values.pop(path_field)
            path = re.sub(r"\{[^}]+\}", quote(identifier, safe=""), template)
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        secrets = (credential.public_key, credential.secret_key)
        def redact(value):
            if isinstance(value, str):
                for secret in secrets:
                    value = value.replace(secret, "[redacted]")
                return value
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {redact(k): redact(v) for k, v in value.items()}
            return value
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    auth=httpx.BasicAuth(credential.public_key, credential.secret_key),
                    headers={"Accept": "application/json"}, **kwargs)
            if len(response.content) > 10_000_000:
                raise ValueError("Response exceeds size limit")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            status = body.get("status")
            if response.is_error or response.is_redirect or body.get("error") or (isinstance(status, int) and status >= 400):
                return {"status": "error", "http_status": response.status_code,
                    "error": redact(str(body.get("message") or body.get("error") or "PartnerStack rejected the request"))}
            if not isinstance(status, int) or not isinstance(body.get("message"), str):
                raise ValueError("Incomplete PartnerStack response envelope")
            if "data" not in body and config.operation not in {"archive_lead", "archive_deal"}:
                raise ValueError("Missing PartnerStack response data")
            data = redact(body.get("data"))
            output = {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": data}
            if config.operation.startswith("list_"):
                if not isinstance(data, dict) or not isinstance(data.get("items"), list) or type(data.get("has_more")) is not bool:
                    raise ValueError("Incomplete PartnerStack list envelope")
                items = data["items"]
                if any(not isinstance(item, dict) for item in items):
                    raise ValueError("Invalid list record")
                output.update(items=items, has_more=data["has_more"],
                    next_starting_after=items[-1].get("key") if items and data["has_more"] else None)
            return output
        except httpx.HTTPError:
            return {"status": "error", "error": "PartnerStack request did not complete; check the account before retrying a write"}
        except ValueError:
            return {"status": "error", "error": "PartnerStack returned an invalid JSON response; check the account before retrying a write"}
