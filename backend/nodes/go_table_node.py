"""Go Table v1 restaurant automation, pinned to the provider's OpenAPI contract.

Each operation makes one request. Paginated reads return the provider's meta
and next_page so workflows can continue explicitly without silently truncating.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://gotable.app"


class GoTableAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Go Table API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://gotable.app/api/docs/v1",
            "x-credential-instructions": "Paste your Go Table API token. NoClick sends it as a bearer token to gotable.app and lists your accessible restaurants to check the connection.",
        })
    credential_type: Literal["go_table_api_token"] = Field("go_table_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GoTableListRestaurantsConfig(_Input):
    """Retrieve a list of accessible restaurants."""
    operation: Literal["list_restaurants"] = Field("list_restaurants", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")


class GoTableGetRestaurantConfig(_Input):
    """Find a restaurant by ID."""
    operation: Literal["get_restaurant"] = Field("get_restaurant", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)


class GoTableListAccountsConfig(_Input):
    """Retrieve a paginated list of accounts that have access to the restaurant."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")


class GoTableListReservationsConfig(_Input):
    """Retrieve a paginated list of reservations."""
    operation: Literal["list_reservations"] = Field("list_reservations", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")
    query: str | None = Field(None)


class GoTableGetReservationConfig(_Input):
    """Find a reservation by ID."""
    operation: Literal["get_reservation"] = Field("get_reservation", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    reservation_id: int = Field(..., ge=1)


class GoTableListGuestsConfig(_Input):
    """Retrieve a paginated list of guests."""
    operation: Literal["list_guests"] = Field("list_guests", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")
    query: str | None = Field(None)


class GoTableGetGuestConfig(_Input):
    """Find a guest by ID."""
    operation: Literal["get_guest"] = Field("get_guest", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    guest_id: int = Field(..., ge=1)


class GoTableListOffersConfig(_Input):
    """Retrieve a paginated list of a restaurant's offers."""
    operation: Literal["list_offers"] = Field("list_offers", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")


class GoTableGetOfferConfig(_Input):
    """Retrieve the information about a specific restaurant's offer."""
    operation: Literal["get_offer"] = Field("get_offer", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    offer_id: int = Field(..., ge=1)


class GoTableListTablesConfig(_Input):
    """Retrieve a paginated list of a restaurant's tables."""
    operation: Literal["list_tables"] = Field("list_tables", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")


class GoTableGetTableConfig(_Input):
    """Find a table by ID."""
    operation: Literal["get_table"] = Field("get_table", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    table_id: int = Field(..., ge=1)


class GoTableListCombinationsConfig(_Input):
    """Retrieve a paginated list of a restaurant's table combinations."""
    operation: Literal["list_combinations"] = Field("list_combinations", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")


class GoTableGetCombinationConfig(_Input):
    """Find a table combination by ID."""
    operation: Literal["get_combination"] = Field("get_combination", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    combination_id: int = Field(..., ge=1)


class GoTableListReviewsConfig(_Input):
    """Retrieve a paginated list of a restaurant's reviews."""
    operation: Literal["list_reviews"] = Field("list_reviews", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    page: int = Field(1, ge=1, description="One page per call; use next_page to continue.")
    per_page: int = Field(20, ge=1, le=100, description="One page per call; use next_page to continue.")


class GoTableCreateGuestConfig(_Input):
    """Create a guest."""
    operation: Literal["create_guest"] = Field("create_guest", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, description="Guest's name")
    email: str | None = Field(None, description="Guest's email address")
    telephone: str | None = Field(None, description="Guest's telephone number")
    subscribed: bool | None = Field(None, description='Whether the guest may receive the newsletter')


class GoTableUpdateGuestConfig(_Input):
    """Update a guest."""
    operation: Literal["update_guest"] = Field("update_guest", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    guest_id: int = Field(..., ge=1)
    name: str | None = Field(None, description="Guest's name")
    email: str | None = Field(None, description="Guest's email address")
    telephone: str | None = Field(None, description="Guest's telephone number")
    subscribed: bool | None = Field(None, description='Whether the guest may receive the newsletter')


class GoTableCreateReservationConfig(_Input):
    """Create a new reservation."""
    operation: Literal["create_reservation"] = Field("create_reservation", json_schema_extra={"ui:hidden": True})
    role: Literal["restaurant", "guest"] = Field("restaurant", description="Role used for reservation email and SMS notifications.")
    skip_email: bool = Field(False, description="Set true to suppress the provider notification.")
    skip_sms: bool = Field(False, description="Set true to suppress the provider notification.")
    restaurant_id: int = Field(..., ge=1)
    type: Literal["Reservation", "WalkIn"] | None = Field(None, description='Set to "WalkIn" for walk-in reservations. For walk-ins, date/time defaults to current if not provided.')
    offer_id: int | None = Field(None, ge=1, description='The (optional) ID of the offer we want to book this reservation for.')
    date: Date | None = Field(None, description='Required for reservations without a type or "Reservation" type. Can be omitted for "WalkIn" reservations.')
    time: str | None = Field(None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$", description='Time (HH:MM) of reservation. Required for reservations without a type or "Reservation" type.')
    party_size: int = Field(..., ge=1, description='Number of guests in the party.')
    guest_name: str | None = Field(None, description="Primary guest's name")
    guest_email: str | None = Field(None, description="Primary guest's email address")
    guest_telephone: str | None = Field(None, description="Primary guest's telephone")
    comments: str | None = Field(None, description="Primary guest's comments for the reservation.")
    duration_in_minutes: int | None = Field(None, ge=1, description='The duration of the reservation in minutes')
    table_ids: list[int] | None = Field(None, description='An array of table IDs to assign to this reservation. Ignored when `role=guest`.')
    table_lock: bool | None = Field(None, description='Set to `true` to pin the assigned tables and prevent auto-assignment. Ignored when `role=guest`.')

    @model_validator(mode="after")
    def scheduled_time(self):
        if self.type != "WalkIn" and (self.date is None or self.time is None):
            raise ValueError("Date and time are required for a scheduled reservation")
        return self


class GoTableUpdateReservationConfig(_Input):
    """Update a reservation's details."""
    operation: Literal["update_reservation"] = Field("update_reservation", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    reservation_id: int = Field(..., ge=1)
    date: Date | None = Field(None, description='Required for reservations without a type or "Reservation" type. Can be omitted for "WalkIn" reservations.')
    time: str | None = Field(None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$", description='Time (HH:MM) of reservation. Required for reservations without a type or "Reservation" type.')
    party_size: int | None = Field(None, ge=1, description='Number of guests in the party.')
    guest_name: str | None = Field(None, description="Primary guest's name")
    guest_email: str | None = Field(None, description="Primary guest's email address")
    guest_telephone: str | None = Field(None, description="Primary guest's telephone")
    comments: str | None = Field(None, description="Primary guest's comments for the reservation.")
    duration_in_minutes: int | None = Field(None, ge=1, description='The duration of the reservation in minutes')
    table_ids: list[int] | None = Field(None, description="IDs of tables to assign to this reservation. Any ID that doesn't belong to this restaurant is silently dropped.")
    table_lock: bool | None = Field(None, description='Set to true to pin the assigned tables and prevent auto-reassignment.')


class GoTableCancelReservationConfig(_Input):
    """Cancel a reservation."""
    operation: Literal["cancel_reservation"] = Field("cancel_reservation", json_schema_extra={"ui:hidden": True})
    role: Literal["restaurant", "guest"] = Field("restaurant", description="Role used for reservation email and SMS notifications.")
    skip_email: bool = Field(False, description="Set true to suppress the provider notification.")
    skip_sms: bool = Field(False, description="Set true to suppress the provider notification.")
    restaurant_id: int = Field(..., ge=1)
    reservation_id: int = Field(..., ge=1)


class GoTableListReservationNotesConfig(_Input):
    """Retrieve a list of reservation notes."""
    operation: Literal["list_reservation_notes"] = Field("list_reservation_notes", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    reservation_id: int = Field(..., ge=1)


class GoTableCreateReservationNoteConfig(_Input):
    """Create a new reservation note."""
    operation: Literal["create_reservation_note"] = Field("create_reservation_note", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    reservation_id: int = Field(..., ge=1)
    content: str = Field(..., min_length=1, description='The HTML contents of the note.')
    author_id: int = Field(..., ge=1, description='The unique ID of an account that has access to the restaurant.')


class GoTableGetRestaurantAvailabilityConfig(_Input):
    """Retrieve availability for the given restaurant."""
    operation: Literal["get_restaurant_availability"] = Field("get_restaurant_availability", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    from_date: str | None = Field(None, description="ISO 8601 date or datetime boundary.")
    till: str | None = Field(None, description="ISO 8601 date or datetime boundary.")


class GoTableGetOfferAvailabilityConfig(_Input):
    """Retrieve availability for the given offer."""
    operation: Literal["get_offer_availability"] = Field("get_offer_availability", json_schema_extra={"ui:hidden": True})
    restaurant_id: int = Field(..., ge=1)
    offer_id: int = Field(..., ge=1)
    from_date: str | None = Field(None, description="ISO 8601 date or datetime boundary.")
    till: str | None = Field(None, description="ISO 8601 date or datetime boundary.")


GoTableConfig = Annotated[Union[
    GoTableListRestaurantsConfig,
    GoTableGetRestaurantConfig,
    GoTableListAccountsConfig,
    GoTableListReservationsConfig,
    GoTableGetReservationConfig,
    GoTableListGuestsConfig,
    GoTableGetGuestConfig,
    GoTableListOffersConfig,
    GoTableGetOfferConfig,
    GoTableListTablesConfig,
    GoTableGetTableConfig,
    GoTableListCombinationsConfig,
    GoTableGetCombinationConfig,
    GoTableListReviewsConfig,
    GoTableCreateGuestConfig,
    GoTableUpdateGuestConfig,
    GoTableCreateReservationConfig,
    GoTableUpdateReservationConfig,
    GoTableCancelReservationConfig,
    GoTableListReservationNotesConfig,
    GoTableCreateReservationNoteConfig,
    GoTableGetRestaurantAvailabilityConfig,
    GoTableGetOfferAvailabilityConfig
], Field(discriminator="operation")]


class GoTableFullConfig(NodeConfig[GoTableConfig, GoTableAPITokenCredential]):
    pass


ROUTES = {'list_restaurants': ('GET', '/api/v1/restaurants', {'page': 'page', 'per_page': 'per_page'}, []),
 'get_restaurant': ('GET', '/api/v1/restaurants/{restaurant_id}', {}, []),
 'list_accounts': ('GET',
                   '/api/v1/restaurants/{restaurant_id}/accounts',
                   {'page': 'page', 'per_page': 'per_page'},
                   []),
 'list_reservations': ('GET',
                       '/api/v1/restaurants/{restaurant_id}/reservations',
                       {'page': 'page', 'per_page': 'per_page', 'query': 'query'},
                       []),
 'get_reservation': ('GET', '/api/v1/restaurants/{restaurant_id}/reservations/{reservation_id}', {}, []),
 'list_guests': ('GET',
                 '/api/v1/restaurants/{restaurant_id}/guests',
                 {'page': 'page', 'per_page': 'per_page', 'query': 'query'},
                 []),
 'get_guest': ('GET', '/api/v1/restaurants/{restaurant_id}/guests/{guest_id}', {}, []),
 'list_offers': ('GET',
                 '/api/v1/restaurants/{restaurant_id}/offers',
                 {'page': 'page', 'per_page': 'per_page'},
                 []),
 'get_offer': ('GET', '/api/v1/restaurants/{restaurant_id}/offers/{offer_id}', {}, []),
 'list_tables': ('GET',
                 '/api/v1/restaurants/{restaurant_id}/tables',
                 {'page': 'page', 'per_page': 'per_page'},
                 []),
 'get_table': ('GET', '/api/v1/restaurants/{restaurant_id}/tables/{table_id}', {}, []),
 'list_combinations': ('GET',
                       '/api/v1/restaurants/{restaurant_id}/combinations',
                       {'page': 'page', 'per_page': 'per_page'},
                       []),
 'get_combination': ('GET', '/api/v1/restaurants/{restaurant_id}/combinations/{combination_id}', {}, []),
 'list_reviews': ('GET',
                  '/api/v1/restaurants/{restaurant_id}/reviews',
                  {'page': 'page', 'per_page': 'per_page'},
                  []),
 'create_guest': ('POST',
                  '/api/v1/restaurants/{restaurant_id}/guests',
                  {},
                  ['name', 'email', 'telephone', 'subscribed']),
 'update_guest': ('PATCH',
                  '/api/v1/restaurants/{restaurant_id}/guests/{guest_id}',
                  {},
                  ['name', 'email', 'telephone', 'subscribed']),
 'create_reservation': ('POST',
                        '/api/v1/restaurants/{restaurant_id}/reservations',
                        {'role': 'role', 'skip_email': 'skip_email', 'skip_sms': 'skip_sms'},
                        ['type',
                         'offer_id',
                         'date',
                         'time',
                         'party_size',
                         'guest_name',
                         'guest_email',
                         'guest_telephone',
                         'comments',
                         'duration_in_minutes',
                         'table_ids',
                         'table_lock']),
 'update_reservation': ('PUT',
                        '/api/v1/restaurants/{restaurant_id}/reservations/{reservation_id}',
                        {},
                        ['date',
                         'time',
                         'party_size',
                         'guest_name',
                         'guest_email',
                         'guest_telephone',
                         'comments',
                         'duration_in_minutes',
                         'table_ids',
                         'table_lock']),
 'cancel_reservation': ('POST',
                        '/api/v1/restaurants/{restaurant_id}/reservations/{reservation_id}/cancel',
                        {'role': 'role', 'skip_email': 'skip_email', 'skip_sms': 'skip_sms'},
                        []),
 'list_reservation_notes': ('GET',
                            '/api/v1/restaurants/{restaurant_id}/reservations/{reservation_id}/notes',
                            {},
                            []),
 'create_reservation_note': ('POST',
                             '/api/v1/restaurants/{restaurant_id}/reservations/{reservation_id}/notes',
                             {},
                             ['content', 'author_id']),
 'get_restaurant_availability': ('GET',
                                 '/api/v1/restaurants/{restaurant_id}/availability',
                                 {'from_date': 'from', 'till': 'till'},
                                 []),
 'get_offer_availability': ('GET',
                            '/api/v1/restaurants/{restaurant_id}/offers/{offer_id}/availability',
                            {'from_date': 'from', 'till': 'till'},
                            [])}


class GoTableNode(WorkflowNode):
    integration_type = "automation-go-table"
    connection_evidence = ConnectionEvidence(noun="restaurants", operation="list_restaurants")

    @classmethod
    def get_config_model(cls):
        return GoTableFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Go Table API token")
        config = self.config.config
        values = config.model_dump(mode="json", exclude_none=True)
        method, template, query_fields, body_fields = ROUTES[config.operation]
        path = template.format(**values)
        params = {wire: values[key] for key, wire in query_fields.items() if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body_fields else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the shared connect seam.
            message = response.text.replace(credential.api_token, "[redacted]")[:2000]
            raise ValueError(f"Go Table HTTP {response.status_code}: {message}")
        result = response.json()
        if not isinstance(result, dict) or any(k in result for k in ("error", "errors")):
            raise ValueError("Go Table returned an unexpected response or error envelope")
        result = _redact(result, credential.api_token)
        if config.operation.startswith("list_"):
            key = "notes" if config.operation == "list_reservation_notes" else config.operation[5:]
            if not isinstance(result.get(key), list):
                raise ValueError("Go Table did not return the requested list")
            result["items"] = result[key]
            meta = result.get("meta", {})
            current, total = meta.get("current_page"), meta.get("total_pages")
            result["next_page"] = current + 1 if type(current) is int and type(total) is int and current < total else None
        return result


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value
