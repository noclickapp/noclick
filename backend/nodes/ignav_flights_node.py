"""Ignav's published flight-search and booking-link API, version 1.0.0.

Ten actions cover seven endpoints, including documented manual booking and
round-trip calendar modes. Booking links do not purchase or reserve flights.
Contract: https://ignav.com/api/openapi.json
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://ignav.com"
CREDENTIAL_TYPE = "ignav_flights_api_key"


class IgnavFlightsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Ignav Flights API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://ignav.com/dashboard",
            "x-credential-instructions": "Paste your API key from the Ignav dashboard after verifying your email. NoClick sends it in X-Api-Key. Connecting searches the public airport catalogue to verify key acceptance, not account identity. Fare and booking-link requests can consume Ignav request credits.",
        })
    credential_type: Literal["ignav_flights_api_key"] = Field("ignav_flights_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste an Ignav API key")
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def coherent_trip(self):
        # Additional documented constraints: https://ignav.com/docs/search and
        # https://ignav.com/docs/cheapest-dates. No current-date restriction is
        # imposed locally, so saved workflows keep working across time zones.
        if hasattr(self, "adults"):
            adults = self.adults if self.adults is not None else 1
            children = getattr(self, "children", 0) or 0
            seated = adults + children + (getattr(self, "infants_in_seat", 0) or 0)
            lap = getattr(self, "infants_on_lap", 0) or 0
            if seated + lap > 9 or lap > adults:
                raise ValueError("Use at most nine passengers, with at most one lap infant per adult")
            if any((getattr(self, name, 0) or 0) > seated for name in ("carry_on_bags", "checked_bags")):
                raise ValueError("Bag counts cannot exceed travelers with a seat")
        start, end = getattr(self, "departure_date", None), getattr(self, "return_date", None)
        if start and end and end < start:
            raise ValueError("Return date cannot precede departure")
        if getattr(self, "return_time_range", None) and hasattr(self, "stay_days") and self.stay_days is None:
            raise ValueError("Return time filters require stay days")
        if set(getattr(self, "airlines_include", None) or []) & set(getattr(self, "airlines_exclude", None) or []):
            raise ValueError("An airline cannot be both included and excluded")
        legs = getattr(self, "legs", None)
        if legs and any(b.departure_date < a.departure_date for a, b in zip(legs, legs[1:])):
            raise ValueError("Flight legs must be chronological")
        if hasattr(self, "start") and (self.end - self.start).days not in range(31):
            raise ValueError("Departure window must span one to 31 days")
        if getattr(self, "return_date", None) and hasattr(self, "outbound_carrier_code"):
            if not self.inbound_carrier_code or not self.inbound_flight_number:
                raise ValueError("Return flights require inbound carrier and flight number")
        return self


class TimeRangeInput(_Input):
    earliest_hour: int | None = Field(None, ge=0, le=23, strict=True)
    latest_hour: int | None = Field(None, ge=0, le=23, strict=True)
    arrival_earliest_hour: int | None = Field(None, ge=0, le=23, strict=True)
    arrival_latest_hour: int | None = Field(None, ge=0, le=23, strict=True)


class DepartureDateRange(_Input):
    start: date = Field(...)
    end: date = Field(...)


class SearchLegInput(_Input):
    origin: str = Field(...)
    destination: str = Field(...)
    departure_date: date = Field(...)
    max_stops: int | None = Field(None, ge=0, le=2, strict=True)
    departure_time_range: TimeRangeInput | None = Field(None)


class OneWayRequest(_Input):
    origin: str = Field(...)
    destination: str = Field(...)
    departure_date: date = Field(...)
    adults: int = Field(1, ge=1, strict=True)
    children: int = Field(0, ge=0, strict=True)
    infants_in_seat: int = Field(0, ge=0, strict=True)
    infants_on_lap: int = Field(0, ge=0, strict=True)
    cabin_class: Literal['economy', 'premium_economy', 'business', 'first'] = Field('economy')
    max_stops: int | None = Field(None, ge=0, le=2, strict=True)
    checked_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total checked bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference.')
    carry_on_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total carry-on bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference. Prices include estimated bag fees where available.')
    max_price: int | None = Field(None, ge=0, strict=True)
    departure_time_range: TimeRangeInput | None = Field(None)
    airlines_include: list[str] | None = Field(None)
    airlines_exclude: list[str] | None = Field(None)
    allow_mixed_carriers: bool = Field(True, strict=True, description='Allow multiple reported marketing carriers within a direction. This does not describe ticketing or connection protection.')
    market: str = Field('US')


class RoundTripRequest(_Input):
    origin: str = Field(...)
    destination: str = Field(...)
    departure_date: date = Field(...)
    adults: int = Field(1, ge=1, strict=True)
    children: int = Field(0, ge=0, strict=True)
    infants_in_seat: int = Field(0, ge=0, strict=True)
    infants_on_lap: int = Field(0, ge=0, strict=True)
    cabin_class: Literal['economy', 'premium_economy', 'business', 'first'] = Field('economy')
    max_stops: int | None = Field(None, ge=0, le=2, strict=True)
    checked_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total checked bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference.')
    carry_on_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total carry-on bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference. Prices include estimated bag fees where available.')
    max_price: int | None = Field(None, ge=0, strict=True)
    departure_time_range: TimeRangeInput | None = Field(None)
    airlines_include: list[str] | None = Field(None)
    airlines_exclude: list[str] | None = Field(None)
    allow_mixed_carriers: bool = Field(True, strict=True, description='Allow multiple reported marketing carriers within a direction. This does not describe ticketing or connection protection.')
    market: str = Field('US')
    return_date: date = Field(...)
    return_time_range: TimeRangeInput | None = Field(None)


class FareSearchRequest(_Input):
    legs: list[SearchLegInput] = Field(..., min_length=1, max_length=2)
    adults: int = Field(1, ge=1, strict=True)
    children: int = Field(0, ge=0, strict=True)
    infants_in_seat: int = Field(0, ge=0, strict=True)
    infants_on_lap: int = Field(0, ge=0, strict=True)
    cabin_class: Literal['economy', 'premium_economy', 'business', 'first'] = Field('economy')
    checked_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total checked bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference.')
    carry_on_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total carry-on bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference. Prices include estimated bag fees where available.')
    max_price: int | None = Field(None, ge=0, strict=True)
    airlines_include: list[str] | None = Field(None)
    airlines_exclude: list[str] | None = Field(None)
    allow_mixed_carriers: bool = Field(True, strict=True, description='Allow multiple reported marketing carriers within a leg. This does not describe ticketing or connection protection.')
    market: str = Field('US')


class CheapestDatesRequest(_Input):
    origin: str = Field(...)
    destination: str = Field(...)
    departure_date_range: DepartureDateRange = Field(...)
    stay_days: int | None = Field(None, ge=0, le=365, strict=True)
    adults: int = Field(1, ge=1, strict=True)
    children: int = Field(0, ge=0, strict=True)
    infants_in_seat: int = Field(0, ge=0, strict=True)
    infants_on_lap: int = Field(0, ge=0, strict=True)
    cabin_class: Literal['economy', 'premium_economy', 'business', 'first'] = Field('economy')
    max_stops: int | None = Field(None, ge=0, le=2, strict=True)
    carry_on_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total carry-on bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference. Calendar returns date-level prices.')
    checked_bags: int | None = Field(None, ge=0, le=9, strict=True, description='Requested total checked bags for the party, up to one per traveler with a seat. Zero, null or omitted means no preference.')
    max_price: int | None = Field(None, ge=0, strict=True)
    departure_time_range: TimeRangeInput | None = Field(None)
    return_time_range: TimeRangeInput | None = Field(None)
    market: str = Field('US')


class ManualBookingRequest(_Input):
    origin: str = Field(...)
    destination: str = Field(...)
    departure_date: date = Field(...)
    outbound_carrier_code: str = Field(...)
    outbound_flight_number: str = Field(...)
    return_date: date | None = Field(None)
    inbound_carrier_code: str | None = Field(None)
    inbound_flight_number: str | None = Field(None)
    adults: int | None = Field(None, ge=1, strict=True)
    children: int | None = Field(None, ge=0, strict=True)
    infants_in_seat: int | None = Field(None, ge=0, strict=True)
    infants_on_lap: int | None = Field(None, ge=0, strict=True)
    market: str | None = Field(None)


class GetHealth(_Input):
    operation: Literal['get_health'] = Field('get_health', title='Get API Health', json_schema_extra={"ui:hidden": True})

class SearchAirports(_Input):
    operation: Literal['search_airports'] = Field('search_airports', title='Search Airports', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=2, description="Airport code, city, country or name")
    limit: int = Field(10, ge=1, le=20, strict=True)

class CheckConnection(_Input):
    operation: Literal['check_connection'] = Field('check_connection', title='Check API Key', json_schema_extra={"ui:hidden": True})

class SearchFares(FareSearchRequest):
    operation: Literal['search_fares'] = Field('search_fares', title='Search Ordered Flight Legs', json_schema_extra={"ui:hidden": True})

class SearchOneWay(OneWayRequest):
    operation: Literal['search_one_way'] = Field('search_one_way', title='Search One-Way Fares', json_schema_extra={"ui:hidden": True})

class SearchRoundTrip(RoundTripRequest):
    operation: Literal['search_round_trip'] = Field('search_round_trip', title='Search Round-Trip Fares', json_schema_extra={"ui:hidden": True})

class GetBookingLinks(_Input):
    operation: Literal['get_booking_links'] = Field('get_booking_links', title='Get Booking Links by Itinerary ID', json_schema_extra={"ui:hidden": True})
    ignav_id: str = Field(..., min_length=1, description="Opaque ID from a fare search made with the same Ignav account")

class GetManualBookingLinks(ManualBookingRequest):
    operation: Literal['get_manual_booking_links'] = Field('get_manual_booking_links', title='Get Booking Links by Flight Details', json_schema_extra={"ui:hidden": True})

class SearchCheapestDates(CheapestDatesRequest):
    operation: Literal['search_cheapest_dates'] = Field('search_cheapest_dates', title='Search Cheapest Dates', json_schema_extra={"ui:hidden": True})

class SearchRoundTripDates(CheapestDatesRequest):
    operation: Literal['search_round_trip_dates'] = Field('search_round_trip_dates', title='Search Round-Trip Calendar', json_schema_extra={"ui:hidden": True})
    stay_days: int = Field(..., ge=0, le=365, strict=True)

Operation = Annotated[Union[GetHealth, SearchAirports, CheckConnection, SearchFares, SearchOneWay, SearchRoundTrip, GetBookingLinks, GetManualBookingLinks, SearchCheapestDates, SearchRoundTripDates], Field(discriminator="operation")]


class IgnavFlightsConfig(NodeConfig[Operation, IgnavFlightsAPIKeyCredential]):
    pass


ROUTES = {'get_health': ('GET', '/api/health'), 'search_airports': ('GET', '/api/airports'), 'check_connection': ('GET', '/api/airports'), 'search_fares': ('POST', '/api/fares/search'), 'search_one_way': ('POST', '/api/fares/one-way'), 'search_round_trip': ('POST', '/api/fares/round-trip'), 'get_booking_links': ('POST', '/api/fares/booking-links'), 'get_manual_booking_links': ('POST', '/api/fares/booking-links'), 'search_cheapest_dates': ('POST', '/api/fares/cheapest-dates'), 'search_round_trip_dates': ('POST', '/api/fares/cheapest-dates')}


class IgnavFlightsNode(WorkflowNode):
    integration_type = "automation-ignav-flights"
    connection_evidence = ConnectionEvidence(
        noun="Ignav airport catalogue", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return IgnavFlightsConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Ignav Flights API key")
        method, path = ROUTES[config.operation]
        payload = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if config.operation == "check_connection":
            payload = {"q": "san fran", "limit": 5}
        headers = {"Accept": "application/json"}
        if path != "/api/health":
            headers["X-Api-Key"] = credential.api_key
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers,
                **({"params": payload} if method == "GET" else {"json": payload}))
        if response.status_code != 200:
            # Preserve the provider's rejection for connection evidence, but
            # never echo a credential even if an upstream error includes it.
            message = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Ignav HTTP {response.status_code}: {message}")
        body = response.json()
        expected = list if path == "/api/airports" else dict
        if not isinstance(body, expected) or isinstance(body, dict) and ("error" in body or "errors" in body):
            raise ValueError("Ignav returned an unexpected response")
        return {"data": body}
