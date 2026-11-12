"""iClosed v1 account automation using a person-supplied API key.

Each operation sends one published endpoint request; paginated reads return one
page and an explicit next page, without replaying writes or following redirects.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, EmailStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://public.api.iclosed.io"
CREDENTIAL_TYPE = "iclosed_api_key"


class IClosedAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="ICLOSED API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.iclosed.io/settings",
            "x-credential-instructions": "In iClosed, open Settings → Developer → API Keys. Create a key and paste the complete key, including its iclosed_ prefix, without Bearer. The key acts as its user and account. Connection checks read your contacts; write permissions are checked by iClosed when used."})
    credential_type: Literal["iclosed_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the complete iClosed API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def semantics(self):
        values = self.model_dump(exclude_none=True)
        for name, value in values.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Numbers must be finite")
            if name in {"timeFrom", "timeTo", "joinedTime", "dateTime", "time"} and isinstance(value, str):
                try:
                    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if date.tzinfo is None: raise ValueError()
                except ValueError:
                    raise ValueError("Use an ISO 8601 date-time with a timezone") from None
            if name == "timeZone":
                try: ZoneInfo(value)
                except (ZoneInfoNotFoundError, ValueError):
                    raise ValueError("Use an IANA time zone such as America/New_York") from None
        if "orderBy" in values or "orderColumn" in values:
            if (values.get("orderBy") is None) != (values.get("orderColumn") is None):
                raise ValueError("Supply both orderBy and orderColumn")
        if values.get("operation") == "get_event" and not (values.get("id") is not None or values.get("linkPrefix")):
            raise ValueError("Supply id or linkPrefix")
        if values.get("operation") == "create_deal" and not (values.get("productId") is not None or values.get("productName")):
            raise ValueError("Supply productId or productName")
        if values.get("operation") == "create_call":
            if values.get("contactId") is None and not (values.get("email") or values.get("phoneNumber")):
                raise ValueError("Supply contactId, email or phoneNumber")
            if values.get("eventId") is None and not values.get("linkPrefix"):
                raise ValueError("Supply eventId or linkPrefix")
        for low, high in (("timeFrom", "timeTo"), ("dateFrom", "dateTo"), ("createdAtStart", "createdAtEnd")):
            if values.get(low) and values.get(high) and values[low] > values[high]:
                raise ValueError("Range end must not precede start")
        return self


class Guest(_Input):
    email: EmailStr
    name: str | None = Field(None, max_length=500)


class SecondaryAnswer(_Input):
    customFieldId: int | None = Field(None, ge=0, le=2147483647)
    identifier: str | None = Field(None, min_length=1)
    answer: list[str]

    @model_validator(mode="after")
    def identifier_required(self):
        if self.customFieldId is None and not self.identifier:
            raise ValueError("Supply customFieldId or identifier for each answer")
        return self


class IClosedListContacts(_Input):
    'Get Contacts. '
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    userId: int | None = Field(None, ge=1, le=2147483647, description='Return only contacts assigned to this user ID.')
    search: str | None = Field(None, description='Case-insensitive single search value matched across firstName, lastName, email, and phoneNumber (not comma-separated values).')
    limit: int = Field(20, ge=1, le=100, description='Maximum contacts returned per page (1 to 100). Default is 20.')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    timeFrom: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Lower bound for joinedTime filtering, in ISO 8601 date-time format.')
    timeTo: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Upper bound for joinedTime filtering, in ISO 8601 date-time format. Use with timeFrom for ranges.')
    orderBy: Literal['asc', 'desc'] | None = Field(None)
    orderColumn: Literal['id', 'createdAt', 'updatedAt', 'joinedTime', 'firstName', 'lastName', 'email'] | None = Field(None)


class IClosedCreateContact(_Input):
    'Create Contact. '
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    firstName: str | None = Field(None, max_length=25)
    lastName: str | None = Field(None, max_length=25)
    email: EmailStr | None = Field(None, max_length=255)
    phoneNumber: str | None = Field(None, max_length=16, description='International (E.164) phone: optional + and up to 15 digits.')
    status: Literal['POTENTIAL', 'QUALIFIED', 'DISQUALIFIED'] | None = Field(None)
    tag: str | None = Field(None, max_length=100)
    joinedTime: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Date and time when the contact joined, in ISO 8601 format (for example, 2024-01-15T10:00:00.000Z).')
    linkPrefix: str | None = Field(None, max_length=255)
    utm: str | None = Field(None, max_length=1000)
    country: str | None = Field(None, max_length=2, description='Two-letter ISO 3166-1 alpha-2 country code (for example, US or GB).')
    timeZone: str | None = Field(None, max_length=50, description='IANA time zone identifier (for example, America/New_York, Asia/Karachi, or Etc/UTC).')
    ipAddress: str | None = Field(None, max_length=45)
    referrerUrl: str | None = Field(None, json_schema_extra={'format': 'uri'}, max_length=500)


class IClosedUpdateContact(_Input):
    'Update Contact. '
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=0, le=2147483647, description='Contact ID to update.')
    firstName: str | None = Field(None, max_length=25)
    lastName: str | None = Field(None, max_length=25)
    email: EmailStr | None = Field(None, max_length=255, description='Updated primary email address.')
    secondary_email: EmailStr | None = Field(None, max_length=255, description='Updated secondary email address.')
    phoneNumber: str | None = Field(None, max_length=16, description='Updated primary phone number in E.164 format.')
    secondary_phoneNumber: str | None = Field(None, max_length=16, description='Updated secondary phone number in E.164 format.')
    status: Literal['POTENTIAL', 'QUALIFIED', 'DISQUALIFIED'] | None = Field(None, description='Updated contact status.')
    referrerUrl: str | None = Field(None, json_schema_extra={'format': 'uri'}, max_length=500, description='Updated referrer URL.')


class IClosedGetContact(_Input):
    'Get contact by ID. '
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contactId: int = Field(..., ge=1, le=2147483647, description='Contact ID to fetch details for.')
    includeUtms: StrictBool = Field(False, description='When true, include UTMs in a flat `utms` array (with eventCallId per row).')


class IClosedListContactNotes(_Input):
    'Get contact notes. '
    operation: Literal['list_contact_notes'] = Field('list_contact_notes', json_schema_extra={"ui:hidden": True})
    contactId: int = Field(..., ge=1, le=2147483647, description='Contact ID whose notes should be returned.')
    limit: int = Field(20, ge=1, le=100, description='Maximum notes returned per page. Default is 20.')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")


class IClosedCreateContactNote(_Input):
    'Create contact note. '
    operation: Literal['create_contact_note'] = Field('create_contact_note', json_schema_extra={"ui:hidden": True})
    contactId: int = Field(..., ge=1, le=2147483647, description='Contact ID. The contact to attach the note to.')
    note: str = Field(..., min_length=1, max_length=10000, description='Note body content. Supports plain text or HTML.')


class IClosedListDeals(_Input):
    'Get deals. '
    operation: Literal['list_deals'] = Field('list_deals', json_schema_extra={"ui:hidden": True})
    contactId: int | None = Field(None, ge=0, le=2147483647, description='Filter deals linked to this contact id.')
    userIds: str | None = Field(None, description='Comma-separated user ids; resolved to account user ids for filtering deals by assignee.')
    productIds: str | None = Field(None, description='Comma-separated product ids; filters deals by productId in that set.')
    transactionType: Literal['WON', 'RECURRING', 'DEPOSIT'] | None = Field(None)
    contactStatuses: str | None = Field(None, description='Comma-separated contact status values (POTENTIAL, QUALIFIED, DISQUALIFIED, STRATEGY_CALL_BOOKED, DISCOVERY_CALL_BOOKED); filters deals whose contact status is in the list.')
    eventIds: str | None = Field(None, description='Comma-separated event ids; filters deals with an eventCall tied to one of those events.')
    search: str | None = Field(None, description='Case-insensitive search across provider, product name, and contact fields.')
    limit: int = Field(20, ge=1, le=200, description='Maximum deals per page (1–200). Default 20.')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    orderBy: Literal['asc', 'desc'] | None = Field(None)
    orderColumn: Literal['id', 'time', 'value', 'firstName', 'lastName', 'email', 'phoneNumber'] | None = Field(None)
    timeFrom: str | None = Field(None, description='Inclusive lower bound for deal time (ISO date, e.g. 2026-03-31T00:00:00.000Z).')
    timeTo: str | None = Field(None, description='Inclusive upper bound for deal time (ISO date, e.g. 2026-03-31T23:59:59.999Z).')


class IClosedCreateDeal(_Input):
    'Create a new deal. '
    operation: Literal['create_deal'] = Field('create_deal', json_schema_extra={"ui:hidden": True})
    eventCallId: int = Field(..., ge=0, le=2147483647, description='Event call / booking this deal is created from.')
    productId: int | None = Field(None, ge=0, le=2147483647, description='Existing product id (validated for the account).')
    productName: str | None = Field(None, description='Product name when creating without productId (at least one of productId or productName required).')
    value: float | None = Field(None, description='Deal value amount.')
    time: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Deal time as ISO 8601 datetime; must be in the future when provided.')
    transactionType: Literal['WON', 'RECURRING', 'DEPOSIT'] | None = Field(None, description='Initial transaction type when set.')
    transactionIds: list[Annotated[int, Field(..., ge=0, le=2147483647)]] | None = Field(None, description='Existing transaction ids to associate with the new deal.')


class IClosedUpdateDeal(_Input):
    'Update a deal. '
    operation: Literal['update_deal'] = Field('update_deal', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=0, le=2147483647, description='Deal id to update.')
    value: float | None = Field(None, description='Updated deal value.')
    recurring: StrictBool | None = Field(None, description='Whether the deal is recurring.')
    transactionType: Literal['WON', 'RECURRING', 'DEPOSIT'] | None = Field(None, description='Updated transaction type.')
    productId: int | None = Field(None, ge=0, le=2147483647, description='Reassign deal to another product.')
    closerId: int | None = Field(None, ge=0, le=2147483647, description='User id of the closer (assignee).')
    time: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Updated deal time as ISO 8601 datetime; must be in the future when provided.')
    transactionIds: list[Annotated[int, Field(..., ge=0, le=2147483647)]] | None = Field(None, description='Transaction ids to link or sync with this deal.')
    type: Literal['DEAL', 'TRANSACTION'] | None = Field(None, description='Deal vs transaction classification.')
    email: EmailStr | None = Field(None, description='Email context for the update when required by the service.')


class IClosedCreateCall(_Input):
    'Create Call. '
    operation: Literal['create_call'] = Field('create_call', json_schema_extra={"ui:hidden": True})
    contactId: int | None = Field(None, ge=0, le=2147483647, description='Contact ID (optional if email or phoneNumber is provided)')
    email: EmailStr | None = Field(None, max_length=255, description='Invitee email (required when contactId is not provided); must be valid when provided')
    phoneNumber: str | None = Field(None, description='Invitee phone (required when contactId is not provided); must be valid when provided')
    firstName: str | None = Field(None, description='Invitee first name')
    lastName: str | None = Field(None, description='Invitee last name')
    eventId: int | None = Field(None, ge=0, le=2147483647, description='Event ID (optional if linkPrefix is provided)')
    linkPrefix: str | None = Field(None, min_length=1, description='Event link prefix (e.g. "company/meeting"); resolved to eventId when provided')
    dateTime: str = Field(..., json_schema_extra={'format': 'date-time'}, min_length=1, description='ISO 8601 date-time in UTC (e.g. 2026-02-27T12:00:00.000Z)')
    timeZone: str = Field(..., min_length=1, description='IANA time zone for the booking. Also considered for conditional routing (Timezone rules).')
    conditionalUsers: str | None = Field(None, description='Optional comma-separated host user IDs. Echo from inviteeAnswers.conditionalUsers, or from eventDates.appliedHostIds when the SPECIFIC_HOSTS_TEAMS waterfall widened the pool.')
    routingGroupIds: str | None = Field(None, description='Matched EventLogicGroup ids (comma-separated). Echo from inviteeAnswers.routingGroupIds. Required for PRIORITIZE_BY_AVAILABILITY so team arrangement priority is preserved; also selects SPECIFIC_HOSTS_TEAMS waterfall fallbacks.')
    useSecondaryQuestionsForConditionalRouting: StrictBool | None = Field(None, description='Optional flag to use secondary questions for conditional routing. Only works when conditionalUsers are not provided. If true and no conditional users are available at the given dateTime, the API throws "No closer available for this slot."')
    secondaryQuestionsAnswer: list[SecondaryAnswer] = Field(..., description='Optional secondary custom field answers to attach when creating the booking')
    additionalGuests: list[Guest] | None = Field(None, max_length=5, description='Optional extra attendees when the event has allowInviteeAdditionalGuests (max 5); merged with internal host list server-side')


class IClosedListCalls(_Input):
    'Get Calls. '
    operation: Literal['list_calls'] = Field('list_calls', json_schema_extra={"ui:hidden": True})
    ids: str | None = Field(None, description='Comma-separated event call IDs to include')
    contactId: int | None = Field(None, gt=0, le=2147483647, description='Filter by contact ID')
    eventType: Literal['PAST', 'UPCOMING', 'ALL'] | None = Field(None)
    search: str | None = Field(None, description='Free-text search across invitee/contact name, email, and phone')
    dateFrom: str | None = Field(None, description='Start of date range filter (inclusive)')
    dateTo: str | None = Field(None, description='End of date range filter (inclusive)')
    createdAtStart: str | None = Field(None, description='Start of creation date range filter (inclusive)')
    createdAtEnd: str | None = Field(None, description='End of creation date range filter (inclusive)')
    location: str | None = Field(None, description='Comma-separated location filter values (e.g. PHONE_CALL,GOOGLE_MEET)')
    orderColumn: Literal['createdAt', 'dateTime', 'updatedAt', 'id'] | None = Field(None)
    orderBy: Literal['asc', 'desc'] | None = Field(None)
    limit: int = Field(20, ge=1, le=100, description='Maximum number of records per page')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    userIds: str | None = Field(None, description='Comma-separated assigned user IDs')
    eventIds: str | None = Field(None, description='Comma-separated event template IDs')
    types: str | None = Field(None)
    inviteeEmails: str | None = Field(None, description='Comma-separated invitee email addresses')
    outcomes: str | None = Field(None)
    noSaleReason: str | None = Field(None)
    utmKeys: str | None = Field(None, description='Comma-separated UTM parameter keys to filter by')
    utmValues: str | None = Field(None, description='Comma-separated UTM parameter values to filter by')
    callTypes: str | None = Field(None)
    setterIds: str | None = Field(None, description='Comma-separated setter user IDs linked via SettedClaim')


class IClosedRescheduleCall(_Input):
    'Reschedule Call. '
    operation: Literal['reschedule_call'] = Field('reschedule_call', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, description='Event call ID to reschedule')
    dateTime: str = Field(..., min_length=1, description='ISO 8601 date-time in UTC (e.g. 2026-02-27T12:00:00.000Z)')
    timeZone: str = Field(..., min_length=1, description='IANA time zone used to interpret the new dateTime')
    rescheduleReason: str | None = Field(None, description='Reason provided for rescheduling the event call')
    notes: str | None = Field(None, description='Optional internal notes for this reschedule action')
    userId: int | None = Field(None, gt=0, le=2147483647, description='Optional reassigned closer user ID')
    additionalGuests: list[Guest] | None = Field(None, max_length=5, description='Optional replacement list of invitee-supplied extra guests when the event allows (max 5); omit to keep prior invitee extras out of merge')


class IClosedCancelCall(_Input):
    'Cancel Call. Cancellation removes the booking.'
    operation: Literal['cancel_call'] = Field('cancel_call', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=0, le=2147483647, description='Event call ID')
    cancelReason: str | None = Field(None, description='Reason for cancellation')


class IClosedListEvents(_Input):
    'Get Events. '
    operation: Literal['list_events'] = Field('list_events', json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=500, description='Maximum number of events returned per page')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    search: str | None = Field(None, description='Free-text search on event name, description, internal description, link prefix, and vanity paths (e.g. eve-2 or e/dev/eve-2)')
    userId: int | None = Field(None, gt=0, le=2147483647, description='Filter by owner/host user ID')
    eventType: Literal['STRATEGY_EVENT', 'DISCOVERY_EVENT'] | None = Field(None)
    latestFirst: str | None = Field(None, description='When true, events are ordered by createdAt (direction from sort when provided, else newest first)')
    sort: Literal['asc', 'desc'] | None = Field(None)
    showFeatureStatuses: Literal['true', 'false'] | None = Field(None)


class IClosedGetEvent(_Input):
    'Get Event By ID. '
    operation: Literal['get_event'] = Field('get_event', json_schema_extra={"ui:hidden": True})
    id: int | None = Field(None, ge=0, le=2147483647, description='Event ID')
    linkPrefix: str | None = Field(None, description='Event link prefix')


class IClosedUpdateEventStatus(_Input):
    'Update Event Status. '
    operation: Literal['update_event_status'] = Field('update_event_status', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, description='Event ID')
    status: Literal['ACTIVATED', 'DEACTIVATED'] = Field(..., description='Event status')


class IClosedListProducts(_Input):
    'Get Products. '
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description='Case-insensitive product name search term.')
    limit: int = Field(20, ge=1, le=200, description='Maximum number of records returned per page (1-200).')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    orderBy: Literal['asc', 'desc'] | None = Field(None)
    orderColumn: Literal['id', 'name', 'createdAt', 'updatedAt', 'deals'] | None = Field(None)


class IClosedCreateProduct(_Input):
    'Create a new product. '
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=40, description='Name for the new product (max 40 chars).')
    description: str | None = Field(None, description='Optional description for the new product.')


class IClosedUpdateProduct(_Input):
    'Update a product. '
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    productId: int = Field(..., ge=0, le=2147483647, description='Identifier of the product to update.')
    name: str | None = Field(None, min_length=1, max_length=40, description='New product name (max 40 chars).')
    description: str | None = Field(None, description='Updated product description.')


class IClosedListTransactions(_Input):
    'Get transactions. '
    operation: Literal['list_transactions'] = Field('list_transactions', json_schema_extra={"ui:hidden": True})
    id: int | None = Field(None, ge=0, le=2147483647, description='Filter by transaction ID.')
    synced: Literal['true', 'false'] | None = Field(None)
    search: str | None = Field(None, description='Search in name, email, phoneNumber, or value.')
    source: Literal['Zapier', 'Stripe', 'Make', 'Other'] | None = Field(None)
    timeFrom: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Filter transactions created on or after this time (ISO 8601).')
    timeTo: str | None = Field(None, json_schema_extra={'format': 'date-time'}, description='Filter by createdAt on or before this time (ISO 8601).')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    limit: int = Field(20, ge=1, le=100)
    sort: Literal['asc', 'desc'] | None = Field(None)
    sortByAmount: Literal['ascAmount', 'descAmount'] | None = Field(None)


class IClosedCreateTransaction(_Input):
    'Create a transaction. '
    operation: Literal['create_transaction'] = Field('create_transaction', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='Contact or transaction name.')
    email: EmailStr | None = Field(None, max_length=255)
    phoneNumber: str | None = Field(None, max_length=16, pattern='^\\+?[1-9]\\d{1,14}$')
    description: str | None = Field(None, max_length=1000, description='Transaction description (max 1000 chars).')
    value: float = Field(..., description='Transaction value (required).')
    source: Literal['Zapier', 'Stripe', 'Make', 'Other'] | None = Field(None, description='Source of the transaction (e.g. "Zapier").')
    updatedBy: str | None = Field(None, description='Identifier of who is creating/updating.')


class IClosedUpdateTransaction(_Input):
    'Update a transaction. '
    operation: Literal['update_transaction'] = Field('update_transaction', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=0, le=2147483647, description='Transaction ID to update (required).')
    name: str | None = Field(None, description='Contact or transaction name.')
    email: EmailStr | None = Field(None, max_length=255)
    phoneNumber: str | None = Field(None, max_length=16, pattern='^\\+?[1-9]\\d{1,14}$')
    description: str | None = Field(None, max_length=1000, description='Transaction description (max 1000 chars).')
    value: float | None = Field(None, description='Transaction value.')
    source: Literal['Zapier', 'Stripe', 'Make', 'Other'] | None = Field(None, description='Source of the transaction (e.g. "Zapier").')


class IClosedDeleteTransaction(_Input):
    'Delete a transaction. '
    operation: Literal['delete_transaction'] = Field('delete_transaction', json_schema_extra={"ui:hidden": True})
    id: int = Field(...)


class IClosedListUsers(_Input):
    'List account users. '
    operation: Literal['list_users'] = Field('list_users', json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, ge=1, le=100, description='Number of users per page. Default is 20; maximum is 100.')
    page: int = Field(0, ge=0, le=2147483647, description="Zero-based page index; use next_page from the preceding result.")
    search: str | None = Field(None, description='Optional text query that matches user name and email fields.')
    ids: str | None = Field(None, description='Optional comma-separated user IDs to include in results.')


# iClosed's own MCP server: agents get its tools through a person's iClosed sign-in.
IclosedMcpCredential = mcp_credential("iclosed", "https://mcp.iclosed.io/mcp", app="iClosed")
IClosedCredential = Union[IClosedAPIKeyCredential, IclosedMcpCredential]


IClosedOperation = Annotated[Union[
    IClosedListContacts,
    IClosedCreateContact,
    IClosedUpdateContact,
    IClosedGetContact,
    IClosedListContactNotes,
    IClosedCreateContactNote,
    IClosedListDeals,
    IClosedCreateDeal,
    IClosedUpdateDeal,
    IClosedCreateCall,
    IClosedListCalls,
    IClosedRescheduleCall,
    IClosedCancelCall,
    IClosedListEvents,
    IClosedGetEvent,
    IClosedUpdateEventStatus,
    IClosedListProducts,
    IClosedCreateProduct,
    IClosedUpdateProduct,
    IClosedListTransactions,
    IClosedCreateTransaction,
    IClosedUpdateTransaction,
    IClosedDeleteTransaction,
    IClosedListUsers
], Field(discriminator="operation")]


class IClosedNodeConfig(NodeConfig[IClosedOperation, IClosedCredential]):
    pass


ROUTES = {'list_contacts': ('GET', '/v1/contacts'), 'create_contact': ('POST', '/v1/contacts'), 'update_contact': ('PUT', '/v1/contacts'), 'get_contact': ('GET', '/v1/contacts/detail'), 'list_contact_notes': ('GET', '/v1/contacts/notes'), 'create_contact_note': ('POST', '/v1/contacts/notes'), 'list_deals': ('GET', '/v1/deals'), 'create_deal': ('POST', '/v1/deals'), 'update_deal': ('PUT', '/v1/deals'), 'create_call': ('POST', '/v1/eventCalls'), 'list_calls': ('GET', '/v1/eventCalls'), 'reschedule_call': ('PUT', '/v1/eventCalls/reschedule'), 'cancel_call': ('PUT', '/v1/eventCalls/cancel'), 'list_events': ('GET', '/v1/events'), 'get_event': ('GET', '/v1/events/detail'), 'update_event_status': ('PUT', '/v1/events/status'), 'list_products': ('GET', '/v1/products'), 'create_product': ('POST', '/v1/products'), 'update_product': ('PUT', '/v1/products'), 'list_transactions': ('GET', '/v1/transactions'), 'create_transaction': ('POST', '/v1/transactions'), 'update_transaction': ('PUT', '/v1/transactions'), 'delete_transaction': ('DELETE', '/v1/transactions'), 'list_users': ('GET', '/v1/users')}


# Paths in list envelopes differ across iClosed resources.
LIST_KEYS = {"list_contacts": "contacts", "list_deals": "deals", "list_calls": "eventCalls",
             "list_products": "products", "list_users": "users"}


def _redact(value, secret):
    if isinstance(value, str): return value.replace(secret, "[redacted]")
    if isinstance(value, dict): return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list): return [_redact(v, secret) for v in value]
    return value


class IClosedNode(WorkflowNode):
    integration_type = "automation-iclosed"
    credential_provider_labels = {"iclosed": "iClosed"}
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts",
        label_keys=("email", "firstName", "id"))

    @classmethod
    def get_config_model(cls):
        return IClosedNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an iClosed API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        query = method in {"GET", "DELETE"}
        # Query booleans use the provider's lowercase wire spelling.
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()} if query else None
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
                    params=params, json=None if query else values)
        except httpx.RequestError:
            raise ValueError("iClosed could not be reached; a write may have completed. Inspect iClosed before retrying a write.") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("iClosed returned an unexpected non-JSON response; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            message = payload.get("message", "iClosed request failed") if isinstance(payload, dict) else "iClosed request failed"
            output = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": str(message), "details": payload}
        else:
            if not isinstance(payload, dict):
                raise ValueError("iClosed returned an unexpected response envelope")
            if payload.get("success") is False or (isinstance(payload.get("status"), (int, float)) and payload["status"] >= 400):
                raise ValueError(_redact(str(payload.get("message", "iClosed rejected the request")), secret))
            output = {"status": "success", "success": True, "http_status": response.status_code,
                      "data": payload.get("data", payload)}
            if op.operation.startswith("list_"):
                envelope = payload.get("data", {}) if op.operation in LIST_KEYS else payload
                rows = envelope.get(LIST_KEYS[op.operation]) if op.operation in LIST_KEYS and isinstance(envelope, dict) else envelope.get("data") if isinstance(envelope, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("iClosed returned an unexpected list envelope")
                count = envelope.get("count")
                if count is not None and (isinstance(count, bool) or not isinstance(count, (int, float)) or count < 0):
                    raise ValueError("iClosed returned an invalid list count")
                output.update(data=rows, count=count, page=op.page, limit=op.limit)
                # No total means no claim of completeness; use a full page as the continuation signal.
                more = (op.page + 1) * op.limit < count if count is not None else len(rows) == op.limit
                output.update(has_more=more, next_page=op.page + 1 if more else None)
        output = _redact(output, secret)
        await self.emit(output)
        return output
