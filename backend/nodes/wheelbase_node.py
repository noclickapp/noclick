"""Wheelbase Partner API v1: explicit, single-request rental workflow operations.

Contract: https://api.wheelbasepro.com/v1/openapi.json (1.0.0).
List operations return a single page; use page/page_size to continue. Tokens
are pasted, never minted or rotated by this node. Writes are never retried.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.wheelbasepro.com"
CREDENTIAL_TYPE = "wheelbase_api_token"


class WheelbaseAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Wheelbase API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.wheelbasepro.com/docs",
            "x-credential-instructions": "Paste an existing Wheelbase Partner API bearer token. Use a production token for api.wheelbasepro.com, without the Bearer prefix. The token needs the read/write scopes for your selected operations; dealer-only operations also need a dealer-scoped token. NoClick does not mint or refresh tokens. Replace an expired or revoked token here. Connection checks read only the current credential at /v1/me.",
        })
    credential_type: Literal["wheelbase_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API Token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the bearer token without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    @model_validator(mode="after")
    def date_order(self):
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start is not None and end is not None and start >= end:
            raise ValueError("End date must be after start date")
        return self

class WheelbaseAddonInput(_Input):
    id: int = Field(..., gt=0)
    quantity: int | None = Field(1, gt=0, le=100)


class WheelbaseDeliveryAddress(_Input):
    line_1: str = Field(..., min_length=1)
    line_2: str | None = Field(None)
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    zip: str = Field(..., min_length=1)
    country: str | None = Field(None, description='Defaults to US.')


class WheelbaseDeliveryInput(_Input):
    address: WheelbaseDeliveryAddress = Field(...)
    lat: float | None = Field(None, description='Optional; skips geocoding when both lat/lng are set.')
    lng: float | None = Field(None)
    stationary: bool | None = Field(None, description='True when the vehicle stays parked at the delivery address (no return trip).')
    comment: str | None = Field(None, max_length=500, description='Note for the dealer about the delivery.')


class WheelbaseCreateBookingCustomer(_Input):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr = Field(...)
    phone: str | None = Field(None, min_length=1, max_length=30)
    birthdate: date | None = Field(None)








class WheelbaseCustomerAddress(_Input):
    line_1: str | None = Field(None)
    line_2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None)
    zip: str | None = Field(None)
    country: str | None = Field(None)



class WheelbaseGetAccount(_Input):
    'Get current credential. Returns the identity and metadata for the credential authenticating this request. Useful for verifying an integration is wired up correctly ("is my token being accepted, and as whom?"). No scope required.'
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True})


class WheelbaseListListings(_Input):
    'Search listings. Returns a page of listings matching the supplied filters. Backed by an eventually-consistent search index; use GET /v1/listings/{id} for source-of-truth state.'
    operation: Literal['list_listings'] = Field('list_listings', json_schema_extra={"ui:hidden": True})
    location: str | None = Field(None, description='Free-text location search (city, address, or place name).')
    start_date: date | None = Field(None, description='ISO date (YYYY-MM-DD).')
    end_date: date | None = Field(None, description='ISO date (YYYY-MM-DD).')
    guests: int | None = Field(None, gt=0)
    instant_book: bool | None = Field(None)
    vehicle_type: str | None = Field(None)
    page: int | None = Field(1, gt=0)
    page_size: int | None = Field(20, gt=0, le=150)


class WheelbaseGetListing(_Input):
    "Get listing detail. Returns source-of-truth detail for a single listing. Use this for read-modify-write flows — the search index is eventually consistent.\n\nDealer credentials (with `owner_ids`) can only view listings in their own fleet; other listings return 404 (same as if the listing didn't exist, to avoid confirming other dealers' listing IDs). Marketplace credentials (empty `owner_ids`) can view any listing."
    operation: Literal['get_listing'] = Field('get_listing', json_schema_extra={"ui:hidden": True})
    listing_id: int = Field(..., gt=0)


class WheelbaseUpdateListing(_Input):
    'Update a listing. Partially update a listing. Only whitelisted fields (`name`, `description`, `price_per_day`, `instant_book`) are accepted; anything else is silently dropped. The authenticated user must have owner-equivalent rights on the listing.'
    operation: Literal['update_listing'] = Field('update_listing', json_schema_extra={"ui:hidden": True})
    listing_id: int = Field(..., gt=0)
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=20000)
    price_per_day: int | None = Field(None, gt=0, description='Nightly rate in minor units (cents) — matches `price_per_day.value` from GET responses.')
    instant_book: bool | None = Field(None)

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, key) is not None for key in ('name', 'description', 'price_per_day', 'instant_book')):
            raise ValueError("Supply at least one field to update")
        return self


class WheelbaseListListingAddons(_Input):
    "List a listing's add-ons. Returns the optional add-ons bookable on this listing (account-wide and listing-specific, filtered to what applies at its location and vehicle type). Apply them via `addons: [{id, quantity}]` on POST /v1/quotes or booking create/update.\n\nRequired items (prep fees etc.) are attached to bookings automatically and are not listed here."
    operation: Literal['list_listing_addons'] = Field('list_listing_addons', json_schema_extra={"ui:hidden": True})
    listing_id: int = Field(..., gt=0)


class WheelbaseGetListingAvailability(_Input):
    "Get a listing's availability. Returns the date ranges that cannot be booked within the window — existing bookings, owner blocks, and turnaround buffer days, merged into anonymous ranges. Dates not listed are available.\n\nThis reads the booking source of truth (not the search index) and reflects the same rules booking creation enforces."
    operation: Literal['get_listing_availability'] = Field('get_listing_availability', json_schema_extra={"ui:hidden": True})
    listing_id: int = Field(..., gt=0)
    from_date: date | None = Field(None, description='Window start (inclusive). Defaults to today.')
    to_date: date | None = Field(None, description='Window end (inclusive). Defaults to 12 months from `from`. Max window: 24 months.')


class WheelbaseListInsuranceOptions(_Input):
    'List a listing’s insurance options. The insurance/protection options (tiers) offered on a listing — price per day, deductible, coverage summary, and feature list. Dealer credentials get dealer-priced options; other credentials get marketplace pricing.'
    operation: Literal['list_insurance_options'] = Field('list_insurance_options', json_schema_extra={"ui:hidden": True})
    listing_id: int = Field(..., gt=0)


class WheelbaseCreateQuote(_Input):
    'Get a quote. Returns a non-destructive full price breakdown for a listing and date range. Quote calculation does not reserve availability or create a booking.'
    operation: Literal['create_quote'] = Field('create_quote', json_schema_extra={"ui:hidden": True})
    listing_id: int = Field(..., gt=0)
    start_date: date = Field(...)
    end_date: date = Field(...)
    addons: list[WheelbaseAddonInput] | None = Field(None, max_length=50, description='Optional add-ons to include (ids from GET /v1/listings/{id}/addons). Each shows up in line_items with its cost and tax.')
    insurance_option_id: str | None = Field(None, description='Insurance/protection option to price into the quote (id from GET /v1/listings/{id}/insurance-options). Omit to use the listing default.')
    delivery: WheelbaseDeliveryInput | None = Field(None, description='Deliver to an address instead of lot pickup. The platform geocodes it and prices the delivery fee (tiered mileage vs minimum), returned as a `delivery` line item. Omit for lot pickup.')


class WheelbaseListBookings(_Input):
    "List bookings. Returns bookings the credential participates in — either as renter (bookings where renter_id = credential user_id) or as owner (bookings on rentals in the credential's owner_ids)."
    operation: Literal['list_bookings'] = Field('list_bookings', json_schema_extra={"ui:hidden": True})
    status: str | None = Field(None, description='Filter by booking status (e.g. `negotiating`, `confirmed`).')
    customer_id: int | None = Field(None, gt=0, description="Only this customer's bookings (find the id via GET /v1/customers). Dealer credentials only.")
    start_date_from: date | None = Field(None, description='Only return bookings whose start_date is on/after this date.')
    start_date_to: date | None = Field(None)
    page: int | None = Field(1, gt=0)
    page_size: int | None = Field(20, gt=0, le=150)


class WheelbaseCreateBooking(_Input):
    'Create a booking. Creates a booking in `negotiating` status.\n\nSend an `Idempotency-Key` header to make retries safe — repeating a request with the same key returns the original response instead of creating a duplicate booking. Without the header, every request creates a new booking.\n\nPayment collection (Stripe client_secret) is not yet wired here; a dedicated endpoint will be added for that.'
    operation: Literal['create_booking'] = Field('create_booking', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r'^[\x20-\x7e]+$', description='Optional but strongly recommended in production. Any unique string per logical create; retrying with the same key returns the original response instead of creating a duplicate booking.')
    listing_id: int = Field(..., gt=0)
    start_date: date = Field(...)
    end_date: date = Field(...)
    guests: int | None = Field(None, gt=0)
    customer_id: int | None = Field(None, gt=0)
    customer: WheelbaseCreateBookingCustomer | None = Field(None)
    discount_code: str | None = Field(None)
    insurance: str | None = Field(None, description='Insurance coverage tier (legacy string). Prefer `insurance_option_id`.')
    insurance_option_id: str | None = Field(None, description='Insurance/protection option to apply (id from GET /v1/listings/{id}/insurance-options). Omit to use the listing default.')
    delivery: WheelbaseDeliveryInput | None = Field(None, description='Deliver to an address instead of lot pickup. The platform geocodes it and prices the delivery fee (tiered mileage vs minimum), returned as a `delivery` line item. Omit for lot pickup.')
    addons: list[WheelbaseAddonInput] | None = Field(None, max_length=50, description='Optional add-ons (ids from GET /v1/listings/{id}/addons). Required items (prep fees etc.) are attached automatically — do not send them.')

    @model_validator(mode="after")
    def one_customer(self):
        if self.customer_id is not None and self.customer is not None:
            raise ValueError("Supply either a customer ID or a new customer, not both")
        return self


class WheelbaseGetBooking(_Input):
    'Get a booking. Returns a single booking. Only accessible to the renter or the owner of the associated listing.'
    operation: Literal['get_booking'] = Field('get_booking', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)


class WheelbaseUpdateBooking(_Input):
    "Modify a booking. Partially update a booking. Only dates, guests, discount code, and insurance can be modified. Go api rejects updates once a booking is confirmed — you'll see a 400 with an upstream reason."
    operation: Literal['update_booking'] = Field('update_booking', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)
    start_date: date | None = Field(None)
    end_date: date | None = Field(None)
    guests: int | None = Field(None, gt=0)
    discount_code: str | None = Field(None)
    insurance: str | None = Field(None)
    insurance_option_id: str | None = Field(None, description='Change the insurance/protection option (id from GET /v1/listings/{id}/insurance-options).')
    delivery: WheelbaseDeliveryInput | None = Field(None, description='Deliver to an address instead of lot pickup. The platform geocodes it and prices the delivery fee (tiered mileage vs minimum), returned as a `delivery` line item. Omit for lot pickup.')
    addons: list[WheelbaseAddonInput] | None = Field(None, max_length=50, description='The full optional add-on set for the booking (a replace, not a delta). Send the complete desired list (ids from GET /v1/listings/{id}/addons) — any add-on you leave out is removed, and `[]` removes all. Omit this field entirely to leave add-ons unchanged. Required items (prep fees, etc.) are managed automatically — do not send them.')

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, key) is not None for key in ('start_date', 'end_date', 'guests', 'discount_code', 'insurance', 'insurance_option_id', 'delivery', 'addons')):
            raise ValueError("Supply at least one field to update")
        return self


class WheelbaseApproveBooking(_Input):
    "Approve a booking. Approves the booking from the calling credential's side (renter if user_id = renter_id, owner otherwise). Both sides approving triggers payment capture / confirmation.\n\n**Sending a quote:** when a dealer creates a booking on behalf of a customer and then calls approve, the platform marks the owner side approved and emails the customer their quote with a link to review and pay. Include `reason` to add a personal message to that email and the conversation thread."
    operation: Literal['approve_booking'] = Field('approve_booking', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)
    reason: str | None = Field(None, max_length=500, description="Optional free-text note. On approve it's delivered to the customer as a message (and included in the quote email).")
    notify: bool | None = Field(True, description='Set false to suppress the platform email for this transition — e.g. when you send the customer a checkout link through your own channel (see POST /v1/bookings/{id}/links).')


class WheelbaseDeclineBooking(_Input):
    'Decline a booking. Declines a pre-confirmation booking. Returns 409 if the booking is already confirmed (use /cancel instead).'
    operation: Literal['decline_booking'] = Field('decline_booking', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)
    reason: str | None = Field(None, max_length=500, description="Optional free-text note. On approve it's delivered to the customer as a message (and included in the quote email).")
    notify: bool | None = Field(True, description='Set false to suppress the platform email for this transition — e.g. when you send the customer a checkout link through your own channel (see POST /v1/bookings/{id}/links).')


class WheelbaseCancelBooking(_Input):
    "Cancel a booking. Cancels a confirmed booking. Returns 409 if the booking has not been confirmed (use /decline instead). Cancellation may trigger refund logic per the listing's cancel policy."
    operation: Literal['cancel_booking'] = Field('cancel_booking', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)
    reason: str | None = Field(None, max_length=500, description="Optional free-text note. On approve it's delivered to the customer as a message (and included in the quote email).")
    notify: bool | None = Field(True, description='Set false to suppress the platform email for this transition — e.g. when you send the customer a checkout link through your own channel (see POST /v1/bookings/{id}/links).')


class WheelbaseCreateBookingLink(_Input):
    'Create a shareable checkout link. Mints a single-use-style deep link the customer can open without a password — resolving it signs them in and lands them on the booking\'s checkout or payment step. Send it through your own channel (SMS, email).\n\nOnly available when the booking\'s customer is one of **your** customers (`managed_by: "dealer"`) — marketplace customers have their own accounts and cannot be signed in via links. Links expire after ~3 days; mint a fresh one per send.\n\nTypical flow for a dealer-sent quote: create the booking → `POST /{id}/approve` with `notify: false` → create a `payment` link → send it to the customer yourself.'
    operation: Literal['create_booking_link'] = Field('create_booking_link', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)
    type: Literal['booking', 'payment'] = Field(..., description='`booking` — lands the customer in the checkout flow for the booking. `payment` — jumps straight to the payment step (or the make-a-payment section on a confirmed booking).')


class WheelbaseListBookingDocuments(_Input):
    "List a booking's documents. Returns the booking's documents: platform-generated PDFs (receipt, contract, e-sign receipt, departure/return forms) and uploaded files (driver documents, message attachments). Fetch on demand — availability of generated documents changes with booking state (e.g. the receipt appears once the booking is approved)."
    operation: Literal['list_booking_documents'] = Field('list_booking_documents', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)


class WheelbaseListBookingPayments(_Input):
    "List a booking's payments. Returns the booking's money movement, newest first, in two groups:\n\n- `payments` — the customer timeline: settled charges and refunds plus scheduled/pending future charges (e.g. the remainder auto-charge). `scheduled: true` entries carry a `due_date`; refund entries carry `original_payment_id`.\n- `payouts` — money paid out to your account for this booking, with expected/actual bank deposit dates.\n\nComplements the `payment` block on booking detail: that block is the summary (total paid / balance / plan); this is the itemized history behind it."
    operation: Literal['list_booking_payments'] = Field('list_booking_payments', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)


class WheelbaseGetBookingMessages(_Input):
    "Get a booking's message thread. Returns the full renter conversation attached to a booking, oldest message first. Authors are normalized to renter/dealer/system. Reading does NOT mark the thread read in the Wheelbase dashboard."
    operation: Literal['get_booking_messages'] = Field('get_booking_messages', json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., gt=0)


class WheelbaseListCustomers(_Input):
    'Search customers. Searches the dealer\'s customers — both dealer-managed records and marketplace guests who have booked with the dealer.\n\nMarketplace customers (`managed_by: "marketplace"`) have `email` and `phone` masked (empty strings) in search results, regardless of booking history. Use `GET /v1/customers/{id}` to read contact info once a confirmed booking exists.'
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description='Matches name, email, phone, or customer id.')
    location_ids: str | None = Field(None, pattern='^\\d+(,\\d+)*$')
    repeat_guest: bool | None = Field(None, description='Only customers with more than one booking.')
    active_guest: bool | None = Field(None, description='Only customers with a current or upcoming booking.')
    page: int | None = Field(1, gt=0)
    page_size: int | None = Field(50, gt=0, le=200)


class WheelbaseCreateCustomer(_Input):
    'Create a customer. Creates a dealer-managed customer. Find-or-create semantics by email: if a customer with this email already exists in your account, that record is updated and returned instead of creating a duplicate.\n\nCreated customers are `managed_by: "dealer"` and fully editable. You cannot create a customer using your own account email.'
    operation: Literal['create_customer'] = Field('create_customer', json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr = Field(...)
    phone: str | None = Field(None, max_length=30)
    birthdate: date | None = Field(None)
    address: WheelbaseCustomerAddress | None = Field(None)
    location_ids: list[Annotated[int, Field(gt=0)]] | None = Field(None, description='Dealer locations to associate the customer with.')


class WheelbaseGetCustomer(_Input):
    'Get a customer. Returns a single customer.\n\nDealer-managed customers (`managed_by: "dealer"`) return all fields. Marketplace customers are only readable when they have an interaction with your account (booking or conversation) — otherwise 404 — and their `email`/`phone` are populated only once a confirmed booking exists. `birthdate` is never available for marketplace customers.'
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., gt=0)


class WheelbaseUpdateCustomer(_Input):
    'Update a customer. Partially update a dealer-managed customer. Marketplace customers (`managed_by: "marketplace"`) are managed by the marketplace and cannot be edited — attempts return 403.'
    operation: Literal['update_customer'] = Field('update_customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., gt=0)
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = Field(None)
    phone: str | None = Field(None, max_length=30)
    birthdate: date | None = Field(None)
    address: WheelbaseCustomerAddress | None = Field(None)

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, key) is not None for key in ('first_name', 'last_name', 'email', 'phone', 'birthdate', 'address')):
            raise ValueError("Supply at least one field to update")
        return self


class WheelbaseListLocations(_Input):
    "List locations. Returns the dealer's pickup/drop-off locations with address and weekly hours. Use the ids with the `location_ids` filters on vehicle/booking reports and customer search — and to tie a booking or vehicle to its pickup location's hours."
    operation: Literal['list_locations'] = Field('list_locations', json_schema_extra={"ui:hidden": True})


class WheelbaseListMessageThreads(_Input):
    "List message threads. Returns the credential's renter message threads, newest activity first. Each row carries the follow-up signals — last_message_at, last_message_author, unread — so a queue can skip renters who already replied. Reading threads does NOT mark them read in the Wheelbase dashboard."
    operation: Literal['list_message_threads'] = Field('list_message_threads', json_schema_extra={"ui:hidden": True})
    unread_only: Literal['true', 'false'] | None = Field(None, description='Only threads with unread renter activity.')
    page: int | None = Field(1, gt=0)
    page_size: int | None = Field(20, gt=0, le=100)


WheelbaseOperation = Annotated[Union[
    WheelbaseGetAccount,
    WheelbaseListListings,
    WheelbaseGetListing,
    WheelbaseUpdateListing,
    WheelbaseListListingAddons,
    WheelbaseGetListingAvailability,
    WheelbaseListInsuranceOptions,
    WheelbaseCreateQuote,
    WheelbaseListBookings,
    WheelbaseCreateBooking,
    WheelbaseGetBooking,
    WheelbaseUpdateBooking,
    WheelbaseApproveBooking,
    WheelbaseDeclineBooking,
    WheelbaseCancelBooking,
    WheelbaseCreateBookingLink,
    WheelbaseListBookingDocuments,
    WheelbaseListBookingPayments,
    WheelbaseGetBookingMessages,
    WheelbaseListCustomers,
    WheelbaseCreateCustomer,
    WheelbaseGetCustomer,
    WheelbaseUpdateCustomer,
    WheelbaseListLocations,
    WheelbaseListMessageThreads,
], Field(discriminator="operation")]


class WheelbaseNodeConfig(NodeConfig[WheelbaseOperation, WheelbaseAPITokenCredential]):
    pass


# operation -> method, fixed route, path field, parameter bindings, JSON fields, success status
OPERATIONS = {'get_account': ['GET', '/v1/me', None, {}, [], 200],
 'list_listings': ['GET',
                   '/v1/listings',
                   None,
                   {'location': ['query', 'location'],
                    'start_date': ['query', 'start_date'],
                    'end_date': ['query', 'end_date'],
                    'guests': ['query', 'guests'],
                    'instant_book': ['query', 'instant_book'],
                    'vehicle_type': ['query', 'vehicle_type'],
                    'page': ['query', 'page'],
                    'page_size': ['query', 'page_size']},
                   [],
                   200],
 'get_listing': ['GET', '/v1/listings/{id}', 'listing_id', {'listing_id': ['path', 'id']}, [], 200],
 'update_listing': ['PATCH',
                    '/v1/listings/{id}',
                    'listing_id',
                    {'listing_id': ['path', 'id']},
                    ['name', 'description', 'price_per_day', 'instant_book'],
                    200],
 'list_listing_addons': ['GET',
                         '/v1/listings/{id}/addons',
                         'listing_id',
                         {'listing_id': ['path', 'id']},
                         [],
                         200],
 'get_listing_availability': ['GET',
                              '/v1/listings/{id}/availability',
                              'listing_id',
                              {'listing_id': ['path', 'id'],
                               'from_date': ['query', 'from'],
                               'to_date': ['query', 'to']},
                              [],
                              200],
 'list_insurance_options': ['GET',
                            '/v1/listings/{id}/insurance-options',
                            'listing_id',
                            {'listing_id': ['path', 'id']},
                            [],
                            200],
 'create_quote': ['POST',
                  '/v1/quotes',
                  None,
                  {},
                  ['listing_id', 'start_date', 'end_date', 'addons', 'insurance_option_id', 'delivery'],
                  200],
 'list_bookings': ['GET',
                   '/v1/bookings',
                   None,
                   {'status': ['query', 'status'],
                    'customer_id': ['query', 'customer_id'],
                    'start_date_from': ['query', 'start_date_from'],
                    'start_date_to': ['query', 'start_date_to'],
                    'page': ['query', 'page'],
                    'page_size': ['query', 'page_size']},
                   [],
                   200],
 'create_booking': ['POST',
                    '/v1/bookings',
                    None,
                    {'idempotency_key': ['header', 'idempotency-key']},
                    ['listing_id',
                     'start_date',
                     'end_date',
                     'guests',
                     'customer_id',
                     'customer',
                     'discount_code',
                     'insurance',
                     'insurance_option_id',
                     'delivery',
                     'addons'],
                    201],
 'get_booking': ['GET', '/v1/bookings/{id}', 'booking_id', {'booking_id': ['path', 'id']}, [], 200],
 'update_booking': ['PATCH',
                    '/v1/bookings/{id}',
                    'booking_id',
                    {'booking_id': ['path', 'id']},
                    ['start_date',
                     'end_date',
                     'guests',
                     'discount_code',
                     'insurance',
                     'insurance_option_id',
                     'delivery',
                     'addons'],
                    200],
 'approve_booking': ['POST',
                     '/v1/bookings/{id}/approve',
                     'booking_id',
                     {'booking_id': ['path', 'id']},
                     ['reason', 'notify'],
                     200],
 'decline_booking': ['POST',
                     '/v1/bookings/{id}/decline',
                     'booking_id',
                     {'booking_id': ['path', 'id']},
                     ['reason', 'notify'],
                     200],
 'cancel_booking': ['POST',
                    '/v1/bookings/{id}/cancel',
                    'booking_id',
                    {'booking_id': ['path', 'id']},
                    ['reason', 'notify'],
                    200],
 'create_booking_link': ['POST',
                         '/v1/bookings/{id}/links',
                         'booking_id',
                         {'booking_id': ['path', 'id']},
                         ['type'],
                         201],
 'list_booking_documents': ['GET',
                            '/v1/bookings/{id}/documents',
                            'booking_id',
                            {'booking_id': ['path', 'id']},
                            [],
                            200],
 'list_booking_payments': ['GET',
                           '/v1/bookings/{id}/payments',
                           'booking_id',
                           {'booking_id': ['path', 'id']},
                           [],
                           200],
 'get_booking_messages': ['GET',
                          '/v1/bookings/{id}/messages',
                          'booking_id',
                          {'booking_id': ['path', 'id']},
                          [],
                          200],
 'list_customers': ['GET',
                    '/v1/customers',
                    None,
                    {'search': ['query', 'search'],
                     'location_ids': ['query', 'location_ids'],
                     'repeat_guest': ['query', 'repeat_guest'],
                     'active_guest': ['query', 'active_guest'],
                     'page': ['query', 'page'],
                     'page_size': ['query', 'page_size']},
                    [],
                    200],
 'create_customer': ['POST',
                     '/v1/customers',
                     None,
                     {},
                     ['first_name',
                      'last_name',
                      'email',
                      'phone',
                      'birthdate',
                      'address',
                      'location_ids'],
                     201],
 'get_customer': ['GET', '/v1/customers/{id}', 'customer_id', {'customer_id': ['path', 'id']}, [], 200],
 'update_customer': ['PATCH',
                     '/v1/customers/{id}',
                     'customer_id',
                     {'customer_id': ['path', 'id']},
                     ['first_name', 'last_name', 'email', 'phone', 'birthdate', 'address'],
                     200],
 'list_locations': ['GET', '/v1/locations', None, {}, [], 200],
 'list_message_threads': ['GET',
                          '/v1/messages/threads',
                          None,
                          {'unread_only': ['query', 'unread_only'],
                           'page': ['query', 'page'],
                           'page_size': ['query', 'page_size']},
                          [],
                          200]}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class WheelbaseNode(WorkflowNode):
    integration_type = "automation-wheelbase"
    connection_evidence = ConnectionEvidence(
        noun="Wheelbase account", identity_operation="get_account", identity_keys=("name", "client_id"),
    )
    edit_examples = ["Find upcoming bookings", "Create a customer", "Get a price quote for this vehicle"]

    @classmethod
    def get_config_model(cls):
        return WheelbaseNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wheelbase API token")
        token = self.config.credentials.api_token
        op = self.config.config
        method, path, path_field, bindings, body_fields, expected = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        if path_field:
            path = path.replace("{id}", str(values[path_field]))
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        params = {}
        for field, (location, name) in bindings.items():
            if field not in values:
                continue
            if location == "header":
                headers[name] = values[field]
            elif location == "query":
                value = values[field]
                params[name] = str(value).lower() if isinstance(value, bool) else value
        body = {key: values[key] for key in body_fields if key in values}
        # A configured write is issued exactly once. In particular, timeouts do
        # not cause another booking; the caller can reuse its idempotency key.
        kwargs = {"json": body} if body_fields else {}
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(30.0)) as client:
                async with client.stream(method, BASE + path, params=params, headers=headers, **kwargs) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("Wheelbase response exceeds 8 MiB")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("Wheelbase returned a non-JSON response") from None
                    if response.status_code != expected or (isinstance(payload, dict) and payload.get("error")):
                        error = payload.get("error", {}) if isinstance(payload, dict) else {}
                        message = error.get("message") if isinstance(error, dict) else error
                        result = {"status": "error", "success": False, "http_status": response.status_code,
                            "message": message if isinstance(message, str) else "Wheelbase rejected the request",
                            "retry_after": response.headers.get("Retry-After")}
                    else:
                        if not isinstance(payload, dict):
                            raise ValueError("Wheelbase returned an unexpected JSON shape")
                        result = {"status": "success", "success": True, "http_status": response.status_code,
                            **(payload if "data" in payload else {"data": payload})}
        except httpx.HTTPError:
            raise ValueError("Wheelbase request did not complete; check the provider before retrying a write") from None
        result = _redact(result, token)
        await self.emit(result)
        return result
