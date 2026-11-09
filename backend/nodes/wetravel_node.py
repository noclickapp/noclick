"""WeTravel Partner API v3 trips, payment links and itinerary settings.

A pasted Partner API key is exchanged for an access token on each execution.
Routes and payloads follow the published 3.0.0 contracts; create operations publish immediately.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.wetravel.com/v3"
CREDENTIAL = "wetravel_partner_api_key"


class WeTravelPartnerAPIKey(BaseModel):
    model_config = ConfigDict(title="WeTravel Partner API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.wetravel.com/v3/reference/authentication",
            "x-credential-instructions": "Paste the Partner API key generated in your WeTravel account under Partner API Integration. NoClick exchanges this refresh token for a short-lived access token and lists your trips to verify the connection. The key is shown only once when created. API access must be enabled for your account; listing trips does not prove write permissions.",
        })
    credential_type: Literal["wetravel_partner_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=16384, title="Partner API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Partner API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the Partner API key, without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Currency = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
Fees = Literal["none", "credit_card", "service", "all"]


class ListConfig(Input):
    page: int = Field(1, ge=1, description="Page to fetch. Use next_page from the previous result; each run fetches one page.")
    per_page: int = Field(25, ge=1, le=1000)
    query: Optional[str] = Field(None, min_length=3, max_length=1000, description="Search title or external ID.")
    owner_id: Optional[str] = None
    archived: Optional[StrictBool] = None
    deactivated: Optional[StrictBool] = None
    currency: Optional[Currency] = None
    sort_by: Optional[Literal["date_created", "departure_date", "title"]] = None
    sort_order: Optional[Literal["asc", "desc"]] = None


class ListTrips(ListConfig):
    operation: Literal["list_trips"] = Field("list_trips", title="List trips")
    recurring: Optional[StrictBool] = None
    visibility: Optional[Literal["public", "private"]] = None


class ListPaymentLinks(ListConfig):
    operation: Literal["list_payment_links"] = Field("list_payment_links", title="List payment links")


class TripID(Input):
    trip_uuid: ResourceID = Field(..., title="Trip UUID")


class PaymentLinkID(Input):
    payment_link_uuid: ResourceID = Field(..., title="Payment link UUID")


class GetTrip(TripID):
    operation: Literal["get_trip"] = Field("get_trip", title="Get trip")


class DeleteTrip(TripID):
    operation: Literal["delete_trip"] = Field("delete_trip", title="Delete trip", description="Permanently delete the selected trip.")


class GetPaymentLink(PaymentLinkID):
    operation: Literal["get_payment_link"] = Field("get_payment_link", title="Get payment link")


class DeletePaymentLink(PaymentLinkID):
    operation: Literal["delete_payment_link"] = Field("delete_payment_link", title="Delete payment link", description="Delete the selected payment link.")


class Installment(Input):
    amount: int = Field(..., ge=1, le=1000000000, description="Amount in currency minor units (cents).")
    days_before_departure: int = Field(..., ge=-545, le=900)


class PaymentPlan(Input):
    installments: list[Installment] = Field(..., max_length=24)
    allow_auto_payment: Optional[StrictBool] = None
    allow_partial_payment: Optional[StrictBool] = None
    auto_adjust_late_payments: Optional[StrictBool] = None


class Package(Input):
    price: int = Field(..., ge=1, le=1000000000, description="Price in currency minor units (cents).")
    deposit: Optional[int] = Field(None, ge=0, le=1000000000, description="Only persisted when payment_plan is supplied.")
    days_before_departure: Optional[int] = Field(None, ge=-545, le=900)
    payment_plan: Optional[PaymentPlan] = None


class Image(Input):
    url: str = Field(..., max_length=1000, pattern=r"^https?://[^\s]+$", description="Public image URL, such as a Filestack URL.", json_schema_extra={"format": "uri"})


class Destination(Input):
    title: str = Field(..., min_length=1, max_length=1000)
    google_id: Optional[str] = Field(None, max_length=255)
    country: Optional[str] = Field(None, min_length=2, max_length=2)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    latitude: Optional[float] = Field(None, ge=-90, le=90)


class TripOption(Input):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["package", "option", "personal_option"] = Field("package", title="Option type")
    description: Optional[str] = Field(None, max_length=60000)
    price: Optional[int] = Field(None, ge=0, le=1000000000, description="Price in currency minor units (cents).")
    deposit: Optional[int] = Field(None, ge=0, le=1000000000, description="Only persisted when payment_plan is supplied.")
    quantity: Optional[int] = Field(None, ge=0, le=9999)
    participants_per_package: Optional[int] = Field(None, ge=1, le=9999)
    days_before_departure: Optional[int] = Field(None, ge=-545, le=900)
    payment_plan: Optional[PaymentPlan] = None
    images: Optional[list[Image]] = Field(None, max_length=20)


class Dates(Input):
    @model_validator(mode="after")
    def date_order(self):
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end and start > end:
            raise ValueError("End date must be on or after start date")
        return self


class CreateTrip(Dates):
    operation: Literal["create_trip"] = Field("create_trip", title="Create and publish trip", description="Creates and publishes the trip immediately.")
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=60000)
    currency: Currency
    start_date: date
    end_date: date
    min_people: int = Field(1, ge=1, le=9999)
    max_people: int = Field(25, ge=1, le=9999)
    visibility: Literal["public", "private"]
    participant_fees: Fees
    participants_visibility: Optional[Literal["me", "everyone", "participants"]] = None
    images: list[Image] = Field(..., min_length=1)
    destination: Destination
    trip_options: list[TripOption] = Field(..., min_length=1)
    external_id: Optional[str] = Field(None, max_length=255)
    owner_id: Optional[str] = None
    welcome_message: Optional[str] = Field(None, max_length=60000)

    @model_validator(mode="after")
    def packages(self):
        if not any(option.type == "package" for option in self.trip_options):
            raise ValueError("Include at least one trip package")
        if self.min_people > self.max_people:
            raise ValueError("Minimum participants cannot exceed maximum participants")
        return self


class UpdateTrip(TripID, Dates):
    operation: Literal["update_trip"] = Field("update_trip", title="Update trip")
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=60000)
    external_id: Optional[str] = Field(None, max_length=255)
    owner_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    min_people: Optional[int] = Field(None, ge=1, le=9999)
    max_people: Optional[int] = Field(None, ge=1, le=9999)
    visibility: Optional[Literal["public", "private"]] = None
    participants_visibility: Optional[Literal["me", "everyone", "participants"]] = None
    welcome_message: Optional[str] = Field(None, max_length=60000)
    participant_fees: Optional[Fees] = None


class CreatePaymentLink(Dates):
    operation: Literal["create_payment_link"] = Field("create_payment_link", title="Create and publish payment link", description="Creates and publishes the payment link immediately.")
    title: str = Field(..., min_length=1, max_length=255)
    start_date: date
    end_date: date
    currency: Currency
    participant_fees: Fees
    package: Package
    external_id: Optional[str] = Field(None, max_length=255)
    owner_id: Optional[str] = None


class UpdatePaymentLink(PaymentLinkID, Dates):
    operation: Literal["update_payment_link"] = Field("update_payment_link", title="Update payment link")
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    external_id: Optional[str] = Field(None, max_length=255)
    owner_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    currency: Optional[Currency] = None
    participant_fees: Optional[Fees] = None
    package: Optional[Package] = None


class GetTripItinerary(TripID):
    operation: Literal["get_trip_itinerary"] = Field("get_trip_itinerary", title="Get trip itinerary")


class UpdateTripItinerary(TripID):
    operation: Literal["update_trip_itinerary"] = Field("update_trip_itinerary", title="Update trip itinerary settings", description="Update Smart Dates visibility or PDF download settings, preserving section content.")
    hide_dated_sections: Optional[StrictBool] = None
    pdf_download_mode: Optional[Literal["direct", "disabled", "email_required"]] = None


Operations = Annotated[Union[ListTrips, GetTrip, CreateTrip, UpdateTrip, DeleteTrip,
    ListPaymentLinks, GetPaymentLink, CreatePaymentLink, UpdatePaymentLink, DeletePaymentLink,
    GetTripItinerary, UpdateTripItinerary], Field(discriminator="operation")]


class WeTravelConfig(NodeConfig[Operations, WeTravelPartnerAPIKey]):
    pass


# One provider operation per user action. Authentication is an ancillary exchange.
ROUTES = {
    "list_trips": ("GET", "/trips"),
    "get_trip": ("GET", "/trips/{trip_uuid}"),
    "create_trip": ("POST", "/trips"),
    "update_trip": ("PATCH", "/trips/{trip_uuid}"),
    "delete_trip": ("DELETE", "/trips/{trip_uuid}"),
    "list_payment_links": ("GET", "/payment_links"),
    "get_payment_link": ("GET", "/payment_links/{payment_link_uuid}"),
    "create_payment_link": ("POST", "/payment_links"),
    "update_payment_link": ("PATCH", "/payment_links/{payment_link_uuid}"),
    "delete_payment_link": ("DELETE", "/payment_links/{payment_link_uuid}"),
    "get_trip_itinerary": ("GET", "/trips/{trip_uuid}/itinerary"),
    "update_trip_itinerary": ("PATCH", "/trips/{trip_uuid}/itinerary"),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items() if k.lower() not in {"access_token", "refresh_token", "api_key", "authorization"}}
    return value


class ProviderError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


async def _request(client, method, path, token, *, params=None, body=None):
    response = await client.request(method, BASE + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        params=params, **({"json": body} if body is not None else {}))
    if not 200 <= response.status_code < 300:
        try:
            payload = response.json()
            message = payload.get("error") or payload.get("message") or "WeTravel rejected the request"
            if not isinstance(message, str):
                message = "WeTravel rejected the request"
        except (ValueError, AttributeError):
            message = "WeTravel returned a non-JSON error response"
        raise ProviderError(response.status_code, message)
    if response.status_code == 204:
        return None, response.status_code
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("WeTravel returned an unexpected JSON response")
    if payload.get("error"):
        raise ValueError("WeTravel returned an error envelope")
    return payload, response.status_code


class WeTravelNode(WorkflowNode):
    integration_type = "automation-wetravel"
    connection_evidence = ConnectionEvidence(noun="trips", operation="list_trips", label_keys=("title", "uuid"))

    @classmethod
    def get_config_model(cls):
        return WeTravelConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a WeTravel Partner API key")
        op = self.config.config
        method, route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        route = route.format(**values)
        body = {k: v for k, v in values.items() if k not in {"operation", "trip_uuid", "payment_link_uuid"}}
        if method == "PATCH" and not body:
            raise ValueError("Provide at least one field to update")
        secrets = [self.config.credentials.api_key]
        writing = method != "GET"
        dispatched = False
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
                auth, _ = await _request(client, "POST", "/auth/tokens/access", secrets[0])
                access_token = auth.get("access_token") if isinstance(auth, dict) else None
                if not isinstance(access_token, str) or not access_token or not access_token.isascii() or any(c.isspace() for c in access_token):
                    raise ValueError("WeTravel did not return a usable access token")
                secrets.append(access_token)
                dispatched = True
                payload, status = await _request(client, method, route, access_token,
                    params=body if method == "GET" and op.operation.startswith("list_") else None,
                    body=body if method in {"POST", "PATCH"} else None)
            result = {"status": "success", "operation": op.operation, "http_status": status}
            if method == "DELETE":
                if status != 204:
                    raise ValueError("WeTravel did not confirm deletion")
                result.update(deletion_acknowledged=True)
            elif op.operation.startswith("list_"):
                if not isinstance(payload.get("data"), list):
                    raise ValueError("WeTravel did not return a list")
                pagination = payload.get("pagination", {})
                if not isinstance(pagination, dict):
                    raise ValueError("WeTravel returned invalid pagination")
                result.update(data=payload["data"], pagination=pagination)
                result["next_page"] = op.page + 1 if pagination.get("has_next") is True else None
            else:
                result["data"] = payload
            return _redact(result, secrets)
        except ProviderError as exc:
            ambiguous = writing and dispatched and exc.status >= 500
            return {"status": "unknown" if ambiguous else "error", "operation": op.operation,
                "http_status": exc.status, "error": _redact(str(exc), secrets),
                **({"write_outcome": "unverified", "message": "Inspect WeTravel before retrying this write."} if ambiguous else {})}
        except (httpx.HTTPError, ValueError):
            return {"status": "unknown" if writing and dispatched else "error", "operation": op.operation,
                "error": "WeTravel did not return a verifiable response.",
                **({"write_outcome": "unverified", "message": "Inspect WeTravel before retrying this write."} if writing and dispatched else {})}
