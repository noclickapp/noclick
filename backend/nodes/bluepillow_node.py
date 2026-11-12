"""Bluepillow B2A API, pinned to the provider's 2026-05-08 OpenAPI contract.

Anonymous bearer keys identify a rate-limit bucket, not an account. Booking
initiation creates a tracked handoff link; it never confirms a reservation.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.b2a.bluepillow.com/v1"
VERSION = "2026-05-08"
CREDENTIAL = "bluepillow_api_key"
LANGUAGES = Literal["en", "it", "fr", "de", "es", "pt", "nl", "ko", "pl", "ja"]
DESTINATION_TYPES = Literal["city", "neighborhood", "airport", "poi", "area"]


class BluepillowAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bluepillow API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://b2a.bluepillow.com/",
            "x-credential-instructions": "Generate an anonymous API key at b2a.bluepillow.com and paste it here. No signup or email is needed. Reuse your existing key. Keys identify a rate-limit bucket, not an account; connecting checks acceptance only.",
        })
    credential_type: Literal["bluepillow_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"}, description="Paste the key only, without Bearer or quotes.")

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetHealth(_Config):
    """Read public service health and per-booking-site status; does not test a key."""
    operation: Literal["get_health"] = "get_health"


class IssueAnonymousKey(_Config):
    """Issue a persistent anonymous key. Reuse existing keys; issuance is IP-capped."""
    operation: Literal["issue_anonymous_key"] = "issue_anonymous_key"
    label: str | None = Field(None, max_length=64)
    agent: str | None = Field(None, max_length=64)


class _Property(_Config):
    property_id: str = Field(..., min_length=1, max_length=256, description="Property ID from search or a decision.")

    @field_validator("property_id")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
            raise ValueError("Use a single Bluepillow property ID")
        return value


class GetPropertyPreview(_Property):
    """Read a public static preview without pricing or availability."""
    operation: Literal["get_property_preview"] = "get_property_preview"
    src: str | None = Field(None, max_length=32, description="Optional provenance tag.")


class GetProperty(_Property):
    """Read property facts and optional review enrichments."""
    operation: Literal["get_property"] = "get_property"
    include: str | None = Field(None, description="Comma-separated reviews_aggregate, reviews_sample, reviews_extended.")
    user_country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    language: str | None = Field(None, pattern=r"^[a-z]{2}$")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")

    @field_validator("include")
    @classmethod
    def includes(cls, value):
        if value is not None and any(x not in {"reviews_aggregate", "reviews_sample", "reviews_extended"} for x in value.split(",")):
            raise ValueError("Choose documented review enrichments separated by commas")
        return value


class ResolveDestination(_Config):
    """Resolve a place name to destination IDs. This authenticated read also checks key acceptance."""
    operation: Literal["resolve_destination"] = "resolve_destination"
    name: str = Field(..., min_length=2, max_length=100)
    country: str | None = None
    type: DESTINATION_TYPES | None = None
    language: LANGUAGES = "en"


class DiscoverDestinations(_Config):
    """Discover destinations within a radius of a coordinate."""
    operation: Literal["discover_destinations"] = "discover_destinations"
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(5.0, gt=0)
    type: DESTINATION_TYPES | None = None
    language: LANGUAGES = "en"


class _Idempotent(_Config):
    idempotency_key: UUID | None = Field(None, description="Optional UUID for replaying the same request. If omitted a UUID is generated for this execution. Keep it unchanged when retrying a booking handoff.")


class _Stay(_Idempotent):
    check_in: date = Field(..., description="Check-in date, YYYY-MM-DD.")
    check_out: date = Field(..., description="Check-out date, YYYY-MM-DD, after check-in.")
    adults: int = Field(2, ge=1, le=16)
    children_ages: list[int] | None = None
    rooms: int = Field(1, ge=1, le=9)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in")
        return self


class SearchStays(_Stay):
    """Search ranked stays for a resolved destination. One page per execution."""
    operation: Literal["search_stays"] = "search_stays"
    destination_id: str = Field(..., min_length=1, description="Destination ID from Resolve destination or Discover destinations.")
    price_max_eur: float | None = None
    min_rating: float | None = Field(None, ge=0, le=5)
    property_types: list[Literal["hotel", "aparthotel", "apartment", "villa", "bnb", "hostel", "resort"]] | None = Field(None, description="Preferences boost these types; other types can still appear.")
    sort: Literal["score_desc", "price_asc", "rating_desc", "conversion_desc"] = "score_desc"
    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, description="Use page.next_cursor from the previous result with the same search.")
    user_country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    language: str | None = Field(None, pattern=r"^[a-z]{2}$")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")


class RecommendStay(_Stay):
    """Choose a recommended stay and alternatives for a resolved destination."""
    operation: Literal["recommend_stay"] = "recommend_stay"
    destination_id: str = Field(..., min_length=1)
    price_max_eur: float | None = None
    price_min_eur: float | None = None
    min_rating: float | None = Field(None, ge=0, le=5)
    property_types: list[Literal["hotel", "apartment", "house", "villa", "bb", "hostel", "farmstay", "holiday-home"]] | None = Field(None, description="Preferences boost these types; other types can still appear.")
    required_amenities: list[str] | None = None
    cancellation: Literal["any", "free", "non_refundable"] = "any"
    preferred_otas: list[str] | None = None
    excluded_otas: list[str] | None = None
    end_user_country: str = Field("US", pattern=r"^[A-Z]{2}$")
    currency: str = Field("USD", pattern=r"^[A-Z]{3}$")
    language: str | None = Field(None, min_length=2)
    user_hash: str | None = None
    agent_profile: str | None = None


class RecommendByHotel(_Property, _Stay):
    """Find the best booking site for a property already chosen by the user."""
    operation: Literal["recommend_by_hotel"] = "recommend_by_hotel"


class ValidateOffer(_Property, _Stay):
    """Re-price a previously seen offer; still_valid=false is a successful validation verdict."""
    operation: Literal["validate_offer"] = "validate_offer"
    total_eur: float = Field(..., ge=0, description="Previously seen total in EUR.")
    ota: str | None = None


class InitiateBooking(_Property, _Stay):
    """Create a tracked booking link for the end user. This does not book or pay."""
    operation: Literal["initiate_booking"] = "initiate_booking"
    ota: str | None = None


Operation = Annotated[Union[GetHealth, IssueAnonymousKey, GetPropertyPreview, GetProperty,
    ResolveDestination, DiscoverDestinations, SearchStays, RecommendStay, RecommendByHotel,
    ValidateOffer, InitiateBooking], Field(discriminator="operation")]


class BluepillowConfig(NodeConfig[Operation, BluepillowAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Every operation has one fixed route from the pinned OpenAPI document.
ROUTES = {
    "get_health": ("GET", "/health"),
    "issue_anonymous_key": ("POST", "/keys"),
    "get_property_preview": ("GET", "/properties/{property_id}/preview"),
    "get_property": ("GET", "/properties/{property_id}"),
    "resolve_destination": ("POST", "/destinations/resolve"),
    "discover_destinations": ("POST", "/destinations/discover-near"),
    "search_stays": ("POST", "/search/stays"),
    "recommend_stay": ("POST", "/decide"),
    "recommend_by_hotel": ("POST", "/recommendations/by-hotel"),
    "validate_offer": ("POST", "/validate"),
    "initiate_booking": ("POST", "/bookings/initiate"),
}
PUBLIC = {"get_health", "issue_anonymous_key", "get_property_preview"}
IDEMPOTENT = {"search_stays", "recommend_stay", "recommend_by_hotel", "validate_offer", "initiate_booking"}
OTAS = {"Booking", "Agoda", "Expedia", "TripCom", "Vrbo", "HotelsDotCom", "HotelPlanner",
    "Priceline", "Hotwire", "Orbitz", "Kayak", "Trivago", "Hostelworld", "MrAndMrsSmith",
    "Nuitee", "Direct", "Eps", "HotelBeds", "NextPax", "TuiVillas", "HomeStay", "BelVilla", "Other"}


class BluepillowNode(WorkflowNode):
    integration_type = "automation-bluepillow"
    connection_evidence = ConnectionEvidence(noun="Bluepillow destination search", operation="resolve_destination", operation_arguments={"name": "Rome"}, proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BluepillowConfig

    @staticmethod
    def _body(op):
        data = op.model_dump(mode="json", exclude_none=True, exclude={"operation", "idempotency_key"})
        if not isinstance(op, _Stay):
            return data
        body = {
            "dates": {"check_in": data["check_in"], "check_out": data["check_out"]},
            "guests": {k: data[k] for k in ("adults", "children_ages", "rooms") if k in data},
        }
        if isinstance(op, (SearchStays, RecommendStay)):
            body["location"] = {"type": "destination_id", "value": op.destination_id}
        else:
            body["property_id"] = op.property_id
        if isinstance(op, SearchStays):
            body.update(filters={k: data[k] for k in ("price_max_eur", "min_rating", "property_types") if k in data},
                sort=op.sort, page={"limit": op.limit, **({"cursor": op.cursor} if op.cursor is not None else {})})
            body.update({k: data[k] for k in ("user_country", "language", "currency") if k in data})
        elif isinstance(op, RecommendStay):
            body["constraints"] = {k: data[k] for k in ("price_max_eur", "price_min_eur", "min_rating", "property_types", "required_amenities", "cancellation", "preferred_otas", "excluded_otas") if k in data}
            body["context"] = {k: data[k] for k in ("end_user_country", "currency", "language", "user_hash", "agent_profile") if k in data}
            if any(x not in OTAS for key in ("preferred_otas", "excluded_otas") for x in (data.get(key) or [])):
                raise ValueError("Choose a booking site supported by Bluepillow")
        elif isinstance(op, ValidateOffer):
            body["offer_to_compare"] = {"total_eur": op.total_eur, **({"ota": op.ota} if op.ota is not None else {})}
        elif isinstance(op, InitiateBooking) and op.ota is not None:
            body["ota"] = op.ota
        return body

    @staticmethod
    def _parse(action, body):
        if not isinstance(body, dict) or "error" in body or "errors" in body:
            raise ValueError("Bluepillow returned an invalid response envelope")
        required = {
            "get_health": {"status": str, "version": str},
            "issue_anonymous_key": {"key": str, "created_at": str, "rate_limit": dict},
            "get_property_preview": {"id": str, "name": str, "property_type": str, "location": dict, "upgrade": dict},
            "get_property": {"id": str, "name": str, "property_type": str, "rating": (int, float), "location": dict, "amenities": list, "ota_coverage": list},
            "resolve_destination": {"candidates": list, "total_matches": int, "disambiguation_recommended": bool},
            "discover_destinations": {"candidates": list, "total_matches": int},
            "search_stays": {"results": list, "page": dict, "metadata": dict},
            "recommend_stay": {"recommended": dict, "metadata": dict},
            "recommend_by_hotel": {"recommended": dict, "metadata": dict},
            "validate_offer": {"still_valid": bool},
            "initiate_booking": {"tracking_id": str, "deep_link": str},
        }[action]
        if any(k not in body or not isinstance(body[k], kind) or (kind in (int, (int, float)) and isinstance(body[k], bool)) for k, kind in required.items()):
            raise ValueError("Bluepillow returned an incomplete response")
        return body

    async def execute(self, inputs):
        op = self.config.config
        action = op.operation
        method, route = ROUTES[action]
        headers = {"Accept": "application/json", "B2A-Version": VERSION}
        secret = self.config.credentials.api_key if self.config.credentials else None
        if action not in PUBLIC:
            if not secret:
                raise ValueError("Connect a Bluepillow API key")
            headers["Authorization"] = "Bearer " + secret
        if "{property_id}" in route:
            route = route.replace("{property_id}", quote(op.property_id, safe=""))
        params = None
        body = None
        if method == "GET":
            params = op.model_dump(mode="json", exclude_none=True, exclude={"operation", "property_id"})
        else:
            body = self._body(op)
        request_key = None
        if action in IDEMPOTENT:
            request_key = str(op.idempotency_key or uuid4())
            headers["Idempotency-Key"] = request_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route, headers=headers, params=params,
                    **({"json": body} if body is not None else {}))
        except (httpx.HTTPError, OSError):
            # Transport errors can carry request headers. Never expose their text.
            raise ValueError("Bluepillow request did not complete; inspect the outcome before retrying") from None
        expected = 201 if action == "issue_anonymous_key" else 200
        if response.status_code != expected:
            message = "Bluepillow returned HTTP " + str(response.status_code)
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000]
            except (ValueError, AttributeError):
                pass
            if secret:
                message = message.replace(secret, "[redacted]")
            output = {"status": "error", "action": action, "http_status": response.status_code, "message": message}
            if request_key:
                output["idempotency_key"] = request_key
            await self.emit(output)
            return output
        if len(response.content) > 5_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a bounded JSON response from Bluepillow")
        try:
            data = self._parse(action, response.json())
        except (ValueError, TypeError):
            raise ValueError("Bluepillow response could not be verified") from None
        output = {"status": "success", "action": action, "data": data}
        if request_key:
            output["idempotency_key"] = request_key
        if action == "initiate_booking":
            output["booking_completed"] = False
        await self.emit(output)
        return output
