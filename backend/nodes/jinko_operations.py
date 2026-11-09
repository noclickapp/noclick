"""Typed request fields from Jinko Public API 0.112.0.

Contract: https://docs.gojinko.com/api-reference/public-api.yaml
Money values and opaque provider tokens are passed without reinterpretation.
"""
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class JinkoSearchFlightsAiConfig(_Input):
    'Search flights from one sentence, with follow-ups'
    operation: Literal['search_flights_ai'] = Field('search_flights_ai', json_schema_extra={"ui:hidden": True})
    text: str = Field(... , description="The traveller's request in one sentence, or the answer to the question asked in the previous turn.", min_length=1, max_length=2000, examples=['Paris to Tokyo 3–17 October 2027 for 4, at most one stop'])
    context_id: str | None = Field(None , description='The conversation to continue, from an earlier answer. Omit to start a new conversation.', min_length=1, max_length=100, examples=['ctx_example'])
    task_id: str | None = Field(None , description='The task of that conversation the message answers. Optional: without it, a message continues the task waiting for an answer, or starts a new one.', min_length=1, max_length=100, examples=['atk_example'])
    currency: str | None = Field(None , description='Currency of the prices (ISO 4217).', pattern='^[A-Za-z]{3}$', examples=['EUR'])
    effort: Literal['low', 'medium', 'high'] | None = Field(None , description='How much the search may do before it answers. `low` answers soonest; `high` checks the most and searches the most options. Defaults to `medium`.', examples=['medium'])
    timezone: str = Field(... , description='The traveller\'s IANA time zone. Relative dates such as "next weekend" or "in March" are computed in it.', examples=['Europe/Paris'])


class JinkoGetFlightSearchTaskConfig(_Input):
    'Read a flight AI search task'
    operation: Literal['get_flight_search_task'] = Field('get_flight_search_task', json_schema_extra={"ui:hidden": True})
    task_id: str = Field(... , min_length=1, max_length=100, examples=['tsk_example'])


class JinkoCancelFlightSearchTaskConfig(_Input):
    'Cancel a flight AI search task'
    operation: Literal['cancel_flight_search_task'] = Field('cancel_flight_search_task', json_schema_extra={"ui:hidden": True})
    task_id: str = Field(... , min_length=1, max_length=100, examples=['tsk_example'])


class JinkoSearchHotelsAiConfig(_Input):
    'Search hotels from one sentence, with follow-ups'
    operation: Literal['search_hotels_ai'] = Field('search_hotels_ai', json_schema_extra={"ui:hidden": True})
    text: str = Field(... , description="The traveller's request in one sentence, or the answer to the question asked in the previous turn.", min_length=1, max_length=2000, examples=['A hotel in Paris next weekend for 2 adults with breakfast included'])
    context_id: str | None = Field(None , description='The conversation to continue, from an earlier answer. Omit to start a new conversation.', min_length=1, max_length=100, examples=['ctx_example'])
    task_id: str | None = Field(None , description='The task of that conversation the message answers. Optional: without it, a message continues the task waiting for an answer, or starts a new one.', min_length=1, max_length=100, examples=['atk_example'])
    currency: str | None = Field(None , description='Currency of the prices (ISO 4217).', pattern='^[A-Za-z]{3}$', examples=['EUR'])
    guest_nationality: str | None = Field(None , description='Nationality of the guests (ISO 3166-1 alpha-2).', pattern='^[A-Za-z]{2}$', examples=['FR'])
    effort: Literal['low', 'medium', 'high'] | None = Field(None , description='How much the search may do before it answers. `low` answers soonest; `high` checks the most and searches the most options. Defaults to `medium`.', examples=['medium'])
    timezone: str = Field(... , description='The traveller\'s IANA time zone. Relative dates such as "next weekend" or "tonight" are computed in it.', examples=['Europe/Paris'])


class JinkoGetHotelSearchTaskConfig(_Input):
    'Read a hotel AI search task'
    operation: Literal['get_hotel_search_task'] = Field('get_hotel_search_task', json_schema_extra={"ui:hidden": True})
    task_id: str = Field(... , min_length=1, max_length=100, examples=['atk_example'])


class JinkoCancelHotelSearchTaskConfig(_Input):
    'Cancel a hotel AI search task'
    operation: Literal['cancel_hotel_search_task'] = Field('cancel_hotel_search_task', json_schema_extra={"ui:hidden": True})
    task_id: str = Field(... , min_length=1, max_length=100, examples=['atk_example'])


class JinkoCarGeo(_Input):
    latitude: float = Field(... , ge=-90, le=90, examples=[45.7256])
    longitude: float = Field(... , ge=-180, le=180, examples=[5.0811])
    range: int = Field(... , description='Search radius around the coordinates, in metres (minimum 50).', ge=50, examples=[5000])


class JinkoCarPickUp(_Input):
    date_time: str = Field(... , description='Pick-up date-time, branch-local, no timezone.', pattern='^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$', examples=['2026-09-12T10:00:00'])
    airport_code: str | None = Field(None , description='IATA airport code.', pattern='^[A-Za-z]{3}$', examples=['LYS'])
    place: str | None = Field(None , description="Free-text location in any language — a city, station, airport, landmark or address. Resolved server-side to the rental airport, station or whole city it names, or searched around its position (a landmark, an address); `resolved_place` says how. A region, or text that cannot be pinned down, returns `candidates` instead of offers — retry with a candidate's `place`.", min_length=1, examples=['Lyon city centre'])
    geo: JinkoCarGeo | None = Field(None)


class JinkoCarDropOff(_Input):
    date_time: str | None = Field(None , description='Drop-off date-time, branch-local. May instead be given as the top-level `drop_off_date_time`.', pattern='^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$')
    airport_code: str | None = Field(None , description='IATA airport code.', pattern='^[A-Za-z]{3}$', examples=['LYS'])
    place: str | None = Field(None , description="Free-text location in any language — a city, station, airport, landmark or address. Resolved server-side to the rental airport, station or whole city it names, or searched around its position (a landmark, an address); `resolved_place` says how. A region, or text that cannot be pinned down, returns `candidates` instead of offers — retry with a candidate's `place`.", min_length=1, examples=['Lyon city centre'])
    geo: JinkoCarGeo | None = Field(None)


class JinkoIntentInput(_Input):
    user_intent: str | None = Field(None , description="The user's natural-language intent: the Alpic PII-stripped paraphrase when available, else a best-effort fallback to the client-provided NL query.", examples=['find a cheap flight to Tokyo'])


class JinkoSearchCarsConfig(_Input):
    'Search live car rental offers'
    operation: Literal['search_cars'] = Field('search_cars', json_schema_extra={"ui:hidden": True})
    pick_up: JinkoCarPickUp = Field(...)
    drop_off: JinkoCarDropOff | None = Field(None)
    drop_off_date_time: str | None = Field(None , description='Drop-off date-time for a round trip, branch-local. Required when `drop_off` is omitted.', pattern='^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$', examples=['2026-09-15T10:00:00'])
    driver_age: int = Field(... , description="Driver's age at pick-up (18-99). Pricing and availability are age-dependent.", ge=18, le=99, examples=[30])
    residence_country: str = Field(... , description="Driver's country of residence, ISO 3166-1 alpha-2. Rates and inclusions vary by residence.", pattern='^[A-Za-z]{2}$', examples=['FR'])
    currency: str | None = Field(None , description='ISO 4217 display currency. Defaults to USD.', min_length=3, max_length=3, examples=['EUR'])
    lang: str | None = Field(None , description='BCP-47 language tag for vehicle and branch text.', examples=['en-gb'])
    max_results: int | None = Field(None , description='How many offers to return, in `sort` order (default 50, at most 500). `total_found` says how many the search found.', ge=1, le=500, examples=[50])
    sort: Literal['price'] | None = Field(None , description='Offer order. `price` (the default): `price.pay_now`, cheapest first.', examples=['price'])
    intent: JinkoIntentInput | None = Field(None)


class JinkoManageTripConfigAddItem(_Input):
    trip_item_token: str = Field(...)
    special_requests: list[str] | None = Field(None , description='HOTEL ITEMS ONLY. Free-text special requests for the property, one per entry — late arrival, quiet room, high floor, bedding preference, non-smoking room, baby cot, accessibility needs. They apply to the whole stay and are forwarded to the hotel supplier with the booking as REQUESTS ONLY: neither Jinko nor the supplier guarantees them, and a confirmed booking does not mean the hotel will honour them. At most 10 entries of 500 characters each and 1500 characters in total, counted after trimming; blank entries are dropped. Ignored on flight and ground items. Echoed back on the item as `special_requests`, trimmed and without the blank entries (JIN-2499).', max_length=10, examples=[['Expected arrival around 11:30 PM.', 'A quiet room on a high floor, if available.']])


class JinkoManageTripConfigRemoveItem(_Input):
    item_id: str = Field(...)


class JinkoFrequentFlyer(_Input):
    airline: str = Field(... , description='IATA code of the loyalty program issuer (e.g. `LH` for Lufthansa Miles & More), not necessarily the operating carrier — alliances credit miles on partner flights.', examples=['LH'])
    number: str = Field(... , description='Membership / account number for that loyalty program.', examples=['992100100'])


class JinkoTraveler(_Input):
    first_name: str = Field(... , description='For flights, the airline must be able to print the name on the ticket: Latin letters (accents allowed), spaces, hyphens and apostrophes only. The last name holds at most 29 characters (the airline cannot ticket a longer surname), and first, middle and last name together at most 63. Two travellers in one trip cannot share the same full name. A name that breaks these rules is refused at upsert_travelers or checkout with 400 BAD_REQUEST and `error.field` naming the traveller.')
    last_name: str = Field(... , description='For flights, the airline must be able to print the name on the ticket: Latin letters (accents allowed), spaces, hyphens and apostrophes only. The last name holds at most 29 characters (the airline cannot ticket a longer surname), and first, middle and last name together at most 63. Two travellers in one trip cannot share the same full name. A name that breaks these rules is refused at upsert_travelers or checkout with 400 BAD_REQUEST and `error.field` naming the traveller.')
    date_of_birth: str | None = Field(None , description="Date of birth (YYYY-MM-DD, nothing before or after it). Required for flights, and for a `child` or `infant` staying at a hotel; optional for an adult on a hotel-only trip. For flights it cannot be in the future and must agree with `traveler_type` on the trip's flight dates; otherwise upsert_travelers or checkout answers 400 BAD_REQUEST with `error.field` naming the traveller and field.", pattern='^\\d{4}-\\d{2}-\\d{2}$')
    gender: Literal['MALE', 'FEMALE'] | None = Field(None , description='Required for flights; optional for hotel-only trips. Accepted in either case (`male` reads as `MALE`).')
    traveler_type: Literal['adult', 'child', 'infant'] = Field(... , description="Accepted in either case (`Adult` reads as `adult`). For flights, the traveller's age on the date the booking ages travellers on decides the type — the trip's first flight, or for some bookings the return flight of a round trip: `adult` 12 or older, `child` 2 to 11, `infant` under 2, and an `infant` must still be under 2 on the trip's last flight. A type the `date_of_birth` contradicts is refused at upsert_travelers (once the trip holds the flight) or at checkout with 400 BAD_REQUEST and `error.field` naming the traveller. A flight searched for another party is re-priced for these travellers at checkout, on the same flights and fare family; when that fare is not sold for them, checkout answers 409 `OFFER_UNAVAILABLE`. Each hotel in the trip is booked with these travellers (a `room_bundle` hotel whose rooms `hotel_room_guests` names is booked for those room guests instead), so they cannot name more adults or more children than its rooms were priced for (the hotel_search `occupancies`: `adults` and `children_ages`), and each child's age at check-in must be one of the priced `children_ages`. The hotel counts a traveller by age at check-in, 18 or older being an adult, and a traveller with no `date_of_birth` as an adult. upsert_travelers or checkout answers 400 BAD_REQUEST naming the first traveller over a count or with an age the room was not priced for; search the hotel again for the party.")
    nationality: str | None = Field(None)
    passport_number: str | None = Field(None)
    passport_expiry: str | None = Field(None , description="Passport expiry (YYYY-MM-DD, nothing before or after it). For flights it cannot be before the trip's last flight; otherwise upsert_travelers or checkout answers 400 BAD_REQUEST with `error.field` naming the traveller.", pattern='^\\d{4}-\\d{2}-\\d{2}$')
    passport_country: str | None = Field(None)
    frequent_flyer: JinkoFrequentFlyer | None = Field(None)
    known_traveler_number: str | None = Field(None , description='US trusted-traveler Known Traveler Number (TSA PreCheck / Global Entry). Flights only; sent to the airline as Secure Flight data so PreCheck eligibility prints on the boarding pass.', examples=['998765432'])
    known_traveler_issuing_country: str | None = Field(None , description='ISO 3166-1 alpha-2 country that issued the Known Traveler Number. Defaults to `US` downstream; ignored without known_traveler_number.', examples=['US'])
    redress_number: str | None = Field(None , description='DHS redress control number (TRIP program). Flights only; sent to the airline as Secure Flight data.', examples=['1234567'])
    redress_issuing_country: str | None = Field(None , description='ISO 3166-1 alpha-2 country that issued the redress number. Defaults to `US` downstream; ignored without redress_number.', examples=['US'])


class JinkoContact(_Input):
    email: str = Field(... , description='Contact email for booking confirmations. A trip with a flight needs it before payment: without a contact email, checkout answers 422 `MISSING_CUSTOMER_DETAILS` with `email` in `missing_fields`.')
    phone: str = Field(... , description='Contact phone in international format: a leading `+` and country code, e.g. `+12025550147`. Spaces, hyphens, dots and parentheses are accepted and removed. A number without the leading `+` is rejected with `INVALID_PHONE_NUMBER`. Required to complete a booking.', examples=['+12025550147'])
    title: str | None = Field(None , description='Honorific of the booking contact (e.g. "mr", "ms", "mx"). Free text, resolved downstream per provider. Required to book a car rental; optional otherwise.', examples=['mr'])
    flight_number: str | None = Field(None , description="The driver's arriving flight for a CAR rental, as an IATA flight designator: a two- or three-character airline code then 1 to 4 digits and an optional letter (`BA472`, `AF1234`, `RUS1727`). Spaces and hyphens are accepted and removed; a value that is not a designator is rejected with `INVALID_FLIGHT_NUMBER`. Always optional — a car offer's `pick_up.requires_flight_number` says whether the rental desk asks for one, and a quote lists `flight_number` in that item's required details, but no branch policy blocks checkout without it. Supply it when you have it: the rental company can then hold the car for a delayed flight. Ignored by flights, hotels and ground.", examples=['BA472'])


class JinkoManageTripConfigUpsertTravelers(_Input):
    travelers: list[JinkoTraveler] = Field(... , description='Travelers on the trip (replaces all). Required to complete a booking; the first traveler also supplies the booking contact name.')
    contact: JinkoContact | None = Field(None)


class JinkoHotelRoomPrimaryGuest(_Input):
    occupancy_number: int = Field(... , description='Stable one-based room slot within the selected room bundle.', ge=1, examples=[1])
    first_name: str = Field(...)
    last_name: str = Field(...)
    email: str = Field(...)


class JinkoManageTripConfig(_Input):
    'Create and manage a trip: add or remove items and set travelers'
    operation: Literal['manage_trip'] = Field('manage_trip', json_schema_extra={"ui:hidden": True})
    trip_id: str | None = Field(None)
    add_item: JinkoManageTripConfigAddItem | None = Field(None)
    remove_item: JinkoManageTripConfigRemoveItem | None = Field(None)
    upsert_travelers: JinkoManageTripConfigUpsertTravelers | None = Field(None)
    hotel_room_guests: dict[str, list[JinkoHotelRoomPrimaryGuest]] | None = Field(None)
    intent: JinkoIntentInput | None = Field(None)


class JinkoGetTripConfig(_Input):
    'Fetch the full lifecycle state of a trip — items, travelers, quote, fulfillment, and any booking references'
    operation: Literal['get_trip'] = Field('get_trip', json_schema_extra={"ui:hidden": True})
    trip_id: str = Field(...)


class JinkoListTripAncillariesConfig(_Input):
    'List purchasable ancillaries for a trip (no checkout)'
    operation: Literal['list_trip_ancillaries'] = Field('list_trip_ancillaries', json_schema_extra={"ui:hidden": True})
    trip_id: str = Field(...)


class JinkoCheckoutTripConfig(_Input):
    'Checkout a trip — returns a checkout URL the user opens to pay, plus the Shared Payment Token params an agent can use to pay programmatically'
    operation: Literal['checkout_trip'] = Field('checkout_trip', json_schema_extra={"ui:hidden": True})
    trip_id: str = Field(... , examples=['trip_1048576'])
    intent: JinkoIntentInput | None = Field(None)


class JinkoGetHotelDetailsConfig(_Input):
    'Fetch rich metadata (gallery, facilities, policies, per-room details) for a single hotel'
    operation: Literal['get_hotel_details'] = Field('get_hotel_details', json_schema_extra={"ui:hidden": True})
    hotel_id: str = Field(... , description='The `hotel_id` of a hotel from hotel_search, passed exactly as received and URL-encoded as one path segment. It is opaque: do not parse or build it.', examples=['lp1d2c3'])
    checkin: str | None = Field(None)
    checkout: str | None = Field(None)


class JinkoGetHotelReviewsConfig(_Input):
    'Guest review summary and recent reviews for a single hotel'
    operation: Literal['get_hotel_reviews'] = Field('get_hotel_reviews', json_schema_extra={"ui:hidden": True})
    hotel_id: str = Field(... , description='The `hotel_id` of a hotel from hotel_search, or the `id` hotel_details returns, passed exactly as received and URL-encoded as one path segment. It is opaque: do not parse or build it.', examples=['lp1d2c3'])
    limit: int | None = Field(None , description='Reviews per page, 1 to 50. Default 10.', ge=1, le=50, examples=[10])
    offset: int | None = Field(None , description='Reviews to skip before this page. Default 0.', ge=0, le=2147483647, examples=[0])


class JinkoGetBookingConfig(_Input):
    'Retrieve booked item IDs and per-item servicing eligibility using the Jinko booking reference'
    operation: Literal['get_booking'] = Field('get_booking', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    check_eligibility: bool | None = Field(None , description='Whether to check now, with the airline or supplier, if each item can be voided, refunded or exchanged (`items[].servicing`). For a flight this asks the airline and can add several seconds. Send `false` to read the booking and its stored `fare_conditions` only; the eligibility fields are then left out of `items[].servicing`. Defaults to `true`; after a 180-day notice the default becomes `false`, so send `true` explicitly before cancelling or changing.', examples=[False])
    intent: JinkoIntentInput | None = Field(None)


class JinkoPreviewHotelCancelConfig(_Input):
    'Preview what cancelling a hotel booking would cost'
    operation: Literal['preview_hotel_cancel'] = Field('preview_hotel_cancel', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    booked_item_id: str | None = Field(None , description='The booked item, from get_booking items[].booked_item_id. Preserved across exchanges. Omit only when the booking has exactly one item of the requested domain; otherwise a 409 returns items to choose from.', pattern='^itm_[a-z2-7]+$', examples=['itm_aaaaaaaaaaaaafhuxsdxpbzrbfz5hm3a'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    intent: JinkoIntentInput | None = Field(None)


class JinkoCommitHotelCancelConfigAcknowledged(_Input):
    value: int = Field(... , description='Integer amount in MINOR units, always paired with decimal_places — divide by 10 ** decimal_places to display. Example: value 15977 with decimal_places 2 is 159.77 USD. Rendering this field directly shows prices 100x too high for 2-decimal currencies.', examples=[25000])
    currency: str = Field(... , description='ISO 4217 currency code.', min_length=1, examples=['USD'])
    decimal_places: int = Field(... , description='Scale of the integer value/amount: display = integer / 10 ** decimal_places. Always sent alongside minor-unit amounts. Usually the ISO 4217 digits of the currency (2 for USD/EUR/GBP, 0 for JPY/KRW, 3 for BHD/JOD/KWD) but currency-converted prices can carry a different scale — ALWAYS use the decimal_places sent with the amount, never a hardcoded 2. Only if the field is genuinely absent on a value-shaped object, fall back to the ISO digits for the currency.', examples=[2])


class JinkoCommitHotelCancelConfig(_Input):
    'Cancel a hotel booking against a quote the customer accepted'
    operation: Literal['commit_hotel_cancel'] = Field('commit_hotel_cancel', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    booked_item_id: str | None = Field(None , description='The booked item, from get_booking items[].booked_item_id. Preserved across exchanges. Omit only when the booking has exactly one item of the requested domain; otherwise a 409 returns items to choose from.', pattern='^itm_[a-z2-7]+$', examples=['itm_aaaaaaaaaaaaafhuxsdxpbzrbfz5hm3a'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    intent: JinkoIntentInput | None = Field(None)
    quote_id: str = Field(... , description='The `quote_id` from a preceding POST /v1/hotel_cancel_preview. Binds this commit to the figures that quote reported.', examples=['svq_01J7ZR3M8FKX2P9C'])
    acknowledged: JinkoCommitHotelCancelConfigAcknowledged = Field(... , description="The refund the customer was shown — copy the preview's `refund.amount_money` across. Copying the whole `refund` object, as older integrations do, is still accepted. All three of `value` (minor units), `currency` and `decimal_places` are REQUIRED: the platform compares this against the refund as it stands, and a figure whose scale is unstated cannot be compared. `amount` is not accepted in its place. Any other key, such as `display` or `basis`, is ignored. A mismatch against a still-live quote’s refund is answered 409 `quote_drift`. `retry_quote_id` is that same quote’s handle and `current.refund` its figure. Show it to the customer, then commit again with that handle and figure. Nothing is cancelled.")


class JinkoStatusHotelCancelConfig(_Input):
    'Check how a hotel cancellation ended'
    operation: Literal['status_hotel_cancel'] = Field('status_hotel_cancel', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    booked_item_id: str | None = Field(None , description='The booked item, from get_booking items[].booked_item_id. Preserved across exchanges. Omit only when the booking has exactly one item of the requested domain; otherwise a 409 returns items to choose from.', pattern='^itm_[a-z2-7]+$', examples=['itm_aaaaaaaaaaaaafhuxsdxpbzrbfz5hm3a'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    intent: JinkoIntentInput | None = Field(None)
    service_operation: str = Field(... , description='The "svc_…" handle from a commit, or from POST /v1/hotel_cancel.', examples=['svc_01J7ZR5Q2KME8V4T'])


class JinkoPreviewFlightRefundConfig(_Input):
    'Preview what cancelling a booked flight (every ticket on the item) would return to the customer'
    operation: Literal['preview_flight_refund'] = Field('preview_flight_refund', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    booked_item_id: str | None = Field(None , description='The booked item, from get_booking items[].booked_item_id. Preserved across exchanges. Omit only when the booking has exactly one item of the requested domain; otherwise a 409 returns items to choose from.', pattern='^itm_[a-z2-7]+$', examples=['itm_aaaaaaaaaaaaafhuxsdxpbzrbfz5hm3a'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    intent: JinkoIntentInput | None = Field(None)


class JinkoCommitFlightRefundConfigAcknowledged(_Input):
    value: int = Field(... , description='Integer amount in MINOR units, always paired with decimal_places — divide by 10 ** decimal_places to display. Example: value 15977 with decimal_places 2 is 159.77 USD. Rendering this field directly shows prices 100x too high for 2-decimal currencies.', examples=[25000])
    currency: str = Field(... , description='ISO 4217 currency code.', min_length=1, examples=['USD'])
    decimal_places: int = Field(... , description='Scale of the integer value/amount: display = integer / 10 ** decimal_places. Always sent alongside minor-unit amounts. Usually the ISO 4217 digits of the currency (2 for USD/EUR/GBP, 0 for JPY/KRW, 3 for BHD/JOD/KWD) but currency-converted prices can carry a different scale — ALWAYS use the decimal_places sent with the amount, never a hardcoded 2. Only if the field is genuinely absent on a value-shaped object, fall back to the ISO digits for the currency.', examples=[2])


class JinkoCommitFlightRefundConfig(_Input):
    'Refund or void a booked flight (every ticket on the item) against a quote the customer accepted'
    operation: Literal['commit_flight_refund'] = Field('commit_flight_refund', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    booked_item_id: str | None = Field(None , description='The booked item, from get_booking items[].booked_item_id. Preserved across exchanges. Omit only when the booking has exactly one item of the requested domain; otherwise a 409 returns items to choose from.', pattern='^itm_[a-z2-7]+$', examples=['itm_aaaaaaaaaaaaafhuxsdxpbzrbfz5hm3a'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    intent: JinkoIntentInput | None = Field(None)
    quote_id: str = Field(... , description='The `quote_id` from a preceding POST /v1/flight_refund_preview. Binds this commit to the figures that quote reported.', examples=['svq_01J7ZR3M8FKX2P9C'])
    acknowledged: JinkoCommitFlightRefundConfigAcknowledged | None = Field(None , description="The refund the customer was shown — copy the preview's `refund.amount_money` across. Copying the whole `refund` object, as older integrations do, is still accepted. REQUIRED whenever the preview carried a `refund`, which is every quote that names a figure. It may be omitted in exactly one case: a MANUAL_REQUIRED quote that carries no `refund` at all because the penalty is unknown (`penalty.fee_known: false`), submitted with `manual_ok: true` — there is no figure to acknowledge, and inventing one would have the customer agree to a number nobody computed. Omitting it anywhere else is refused by the platform, not here. When present, all three of `value` (minor units), `currency` and `decimal_places` are required: the platform compares this against the refund as it stands, and a figure whose scale is unstated cannot be compared. `amount` is not accepted in its place. Any other key, such as `display` or `basis`, is ignored. A mismatch against a still-live quote’s refund is answered 409 `quote_drift`. `retry_quote_id` is that same quote’s handle and `current.refund` its figure. Show it to the customer, then commit again with that handle and figure. Nothing is sent to the airline.")
    manual_ok: bool | None = Field(None , description='Send `true` to submit a quote whose `support_level` is MANUAL_REQUIRED. The operation is then raised for a Jinko agent and answers `state: attention_required` with `reason: manual_required` — NOTHING is sent to the airline by this call, and the agent settles or fails it. Without the flag such a commit is refused 409 `manual_required`, so a customer is never put in an agent queue unasked. On an AUTO or AUTO_VOID quote the flag changes nothing. This is also the one submission that may carry no `acknowledged` figure — when the quote itself named none, because the penalty is unknown.', examples=[False])


class JinkoStatusFlightRefundConfig(_Input):
    'Check how a flight refund or void ended'
    operation: Literal['status_flight_refund'] = Field('status_flight_refund', json_schema_extra={"ui:hidden": True})
    booking_ref: str = Field(... , description='Jinko booking reference. Call get_booking first, then select its booked_item_id for servicing.', min_length=1, examples=['JNK-A0AUR2'])
    booked_item_id: str | None = Field(None , description='The booked item, from get_booking items[].booked_item_id. Preserved across exchanges. Omit only when the booking has exactly one item of the requested domain; otherwise a 409 returns items to choose from.', pattern='^itm_[a-z2-7]+$', examples=['itm_aaaaaaaaaaaaafhuxsdxpbzrbfz5hm3a'])
    last_name: str | None = Field(None , description='Required for guest lookup. A credential that owns the booking may omit it; ownership is checked by the platform.', min_length=1, examples=['Doe'])
    intent: JinkoIntentInput | None = Field(None)
    service_operation: str = Field(... , description='The "svc_…" handle from a commit, or from POST /v1/refund_commit.', examples=['svc_01J7ZR5Q2KME8V4T'])


class JinkoListDestinationsConfig(_Input):
    'Rank the top destinations by travel demand'
    operation: Literal['list_destinations'] = Field('list_destinations', json_schema_extra={"ui:hidden": True})
    origin: str = Field('global' , description='Origin selector `<Level>:<Code>` (e.g. `Country:US`), or `global` for all origins. Required for the destination endpoints.', examples=['Country:US'])
    departure_date_from: str | None = Field(None , description='Start of the departure window (YYYY-MM-DD). Supply together with departure_date_to; omit both for no departure-date filter (all departure dates).', pattern='^\\d{4}-\\d{2}-\\d{2}$', examples=['2026-07-01'])
    departure_date_to: str | None = Field(None , description='End of the departure window (YYYY-MM-DD). Supply together with departure_date_from; omit both for no departure-date filter (all departure dates).', pattern='^\\d{4}-\\d{2}-\\d{2}$', examples=['2026-07-31'])
    traveler_type: Literal['Solo', 'Couple', 'Group', 'Family'] | None = Field(None , examples=['Couple'])
    trip_type: Literal['oneway', 'roundtrip'] | None = Field(None , examples=['roundtrip'])
    trip_duration_min: int | None = Field(None , description='Minimum trip length in nights (return_date − dep_date). Round-trips only.', ge=0, examples=[5])
    trip_duration_max: int | None = Field(None , description='Maximum trip length in nights (must be >= trip_duration_min).', ge=0, examples=[9])
    search_window_min: int | None = Field(None , description='Minimum advance-purchase window in days (dep_date − search_date): keep demand from searches made at least this many days before departure.', ge=0, examples=[7])
    search_window_max: int | None = Field(None , description='Maximum advance-purchase window in days (must be >= search_window_min).', ge=0, examples=[30])
    snapshot_window_days: int | None = Field(None , description='Number of most-recent days of search activity aggregated into the demand level (min 2, default 7, max 90 — a 1-day window is the current day, whose data is incomplete; data is kept for 90 days).', ge=2, le=90, examples=[30])
    limit: int | None = Field(20 , description='Maximum number of result rows. Default 20, max 200.', ge=1, le=200, examples=[20])
    level: Literal['country', 'city'] | None = Field(None , description='Ranked output granularity: country (default) or city. Applies to destination/market (not audience).', examples=['city'])
    destination_country: str | None = Field(None , description='Destination country selector `Country:<code>` (e.g. `Country:FR`). Optional and allowed ONLY together with level=city: it scopes the ranked destinations to a single country so that country’s cities are ranked. Must be a country — a City selector is rejected.', examples=['Country:FR'])


JinkoConfig = Annotated[Union[
    JinkoSearchFlightsAiConfig,
    JinkoGetFlightSearchTaskConfig,
    JinkoCancelFlightSearchTaskConfig,
    JinkoSearchHotelsAiConfig,
    JinkoGetHotelSearchTaskConfig,
    JinkoCancelHotelSearchTaskConfig,
    JinkoSearchCarsConfig,
    JinkoManageTripConfig,
    JinkoGetTripConfig,
    JinkoListTripAncillariesConfig,
    JinkoCheckoutTripConfig,
    JinkoGetHotelDetailsConfig,
    JinkoGetHotelReviewsConfig,
    JinkoGetBookingConfig,
    JinkoPreviewHotelCancelConfig,
    JinkoCommitHotelCancelConfig,
    JinkoStatusHotelCancelConfig,
    JinkoPreviewFlightRefundConfig,
    JinkoCommitFlightRefundConfig,
    JinkoStatusFlightRefundConfig,
    JinkoListDestinationsConfig
], Field(discriminator="operation")]

ROUTES = {'search_flights_ai': ('POST', '/v1/flight_ai_search'), 'get_flight_search_task': ('GET', '/v1/flight_ai_search/tasks/{task_id}'), 'cancel_flight_search_task': ('POST', '/v1/flight_ai_search/tasks/{task_id}:cancel'), 'search_hotels_ai': ('POST', '/v1/hotel_ai_search'), 'get_hotel_search_task': ('GET', '/v1/hotel_ai_search/tasks/{task_id}'), 'cancel_hotel_search_task': ('POST', '/v1/hotel_ai_search/tasks/{task_id}:cancel'), 'search_cars': ('POST', '/v1/car_search'), 'manage_trip': ('POST', '/v1/trip'), 'get_trip': ('GET', '/v1/trip/{trip_id}'), 'list_trip_ancillaries': ('GET', '/v1/trip/{trip_id}/ancillaries'), 'checkout_trip': ('POST', '/v1/checkout'), 'get_hotel_details': ('GET', '/v1/hotel_details/{hotel_id}'), 'get_hotel_reviews': ('GET', '/v1/hotel_reviews/{hotel_id}'), 'get_booking': ('POST', '/v1/get_booking'), 'preview_hotel_cancel': ('POST', '/v1/hotel_cancel_preview'), 'commit_hotel_cancel': ('POST', '/v1/hotel_cancel_commit'), 'status_hotel_cancel': ('POST', '/v1/hotel_cancel_status'), 'preview_flight_refund': ('POST', '/v1/flight_refund_preview'), 'commit_flight_refund': ('POST', '/v1/flight_refund_commit'), 'status_flight_refund': ('POST', '/v1/flight_refund_status'), 'list_destinations': ('GET', '/v1/destination')}
