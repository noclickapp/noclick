"""OwnerRez v2 for a person's own account, using HTTP Basic personal tokens.

Contract: https://api.ownerrez.com/openapi/v2.json
Auth: https://api.ownerrez.com/help/guides/api-auth.md
"""
from __future__ import annotations
from datetime import date
from typing import Annotated, Literal, Union
import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.ownerrez.com"
Id = Annotated[int, Field(gt=0, le=2147483647)]
Count = Annotated[int, Field(ge=0, le=2147483647)]
EntityType = Literal["booking", "inquiry", "property", "quote", "guest", "blocked_off_time", "owner"]


class OwnerRezPersonalTokenCredential(BaseModel):
    model_config = ConfigDict(title="OwnerRez Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.ownerrez.com/settings/api",
            "x-credential-instructions": "For your own OwnerRez account, create a Personal Access Token in Settings > Advanced Tools > Developer/API Settings and grant access to yourself. Enter your account email and pt_ token. OwnerRez limits personal tokens to two accounts per IP within 24 hours; partner deployments need OAuth. Messages require OAuth and are unavailable with this connection."})
    credential_type: Literal["ownerrez_personal_token"] = Field("ownerrez_personal_token", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Account email", min_length=3, max_length=320, description="Your OwnerRez sign-in email, used as the HTTP Basic username.")
    personal_access_token: str = Field(..., title="Personal access token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("email")
    @classmethod
    def account_email(cls, value):
        value = value.strip()
        if value.count("@") != 1 or any(c.isspace() or ord(c) < 32 or c == ":" for c in value):
            raise ValueError("Enter your OwnerRez account email")
        return value

    @field_validator("personal_access_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not 3 < len(value) <= 4096 or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the personal access token beginning pt_, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, max_length=8192, description="Copy the cursor query value from next_page_url, keeping the same filters. Each run fetches one page.")


class OwnerRezGetCurrentUser(_Input):
    """Read the authenticated account identity."""
    operation: Literal["get_current_user"] = "get_current_user"


class OwnerRezListBookings(_Page):
    """List bookings created or changed since a UTC timestamp."""
    operation: Literal["list_bookings"] = "list_bookings"
    since_utc: AwareDatetime = Field(..., description="Required UTC timestamp, e.g. 2026-03-01T00:00:00Z.")
    status: Literal["active", "canceled", "pending"] | None = None
    include_guest: bool = False
    include_tags: bool = False


class OwnerRezGetBooking(_Input):
    """Fetch one booking."""
    operation: Literal["get_booking"] = "get_booking"
    booking_id: Id


class _Stay(_Input):
    property_id: Id
    guest_id: Id
    arrival: date
    departure: date
    adults: int = Field(1, ge=1, le=2147483647)
    children: Count = 0
    infants: Count = 0
    pets: Count = 0
    notes: str | None = Field(None, max_length=100000)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.departure <= self.arrival:
            raise ValueError("Departure must be after arrival")
        return self


class OwnerRezCreateBooking(_Stay):
    """Create a guest booking, optionally calculating default charges."""
    operation: Literal["create_booking"] = "create_booking"
    generate_charges: bool = Field(False, description="Calculate property default charges and validate property rules.")


class OwnerRezUpdateBooking(_Input):
    """Update supplied booking notes, title and guest counts."""
    operation: Literal["update_booking"] = "update_booking"
    booking_id: Id
    notes: str | None = Field(None, max_length=100000)
    title: str | None = Field(None, max_length=1000)
    adults: Count | None = None
    children: Count | None = None
    infants: Count | None = None
    pets: Count | None = None

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(getattr(self, f) is not None for f in ("notes", "title", "adults", "children", "infants", "pets")):
            raise ValueError("Supply at least one booking field to update")
        return self


class OwnerRezListGuests(_Page):
    """Search guests by name, email or other search text."""
    operation: Literal["list_guests"] = "list_guests"
    q: str = Field(..., min_length=1, max_length=1000)
    include_tags: bool = False


class OwnerRezGetGuest(_Input):
    """Fetch one guest."""
    operation: Literal["get_guest"] = "get_guest"
    guest_id: Id


class OwnerRezCreateGuest(_Input):
    """Create a guest with optional name, notes and default email."""
    operation: Literal["create_guest"] = "create_guest"
    first_name: str | None = Field(None, max_length=1000)
    last_name: str | None = Field(None, max_length=1000)
    email_address: str | None = Field(None, max_length=320)
    notes: str | None = Field(None, max_length=100000)


class OwnerRezUpdateGuest(_Input):
    """Update guest names and notes, preserving contact collections."""
    operation: Literal["update_guest"] = "update_guest"
    guest_id: Id
    first_name: str | None = Field(None, max_length=1000)
    last_name: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=100000)

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(getattr(self, f) is not None for f in ("first_name", "last_name", "notes")):
            raise ValueError("Supply at least one guest field to update")
        return self


class OwnerRezListProperties(_Page):
    """List the account's properties, one page at a time."""
    operation: Literal["list_properties"] = "list_properties"
    active: bool = True


class OwnerRezGetProperty(_Input):
    """Fetch one property."""
    operation: Literal["get_property"] = "get_property"
    property_id: Id


class OwnerRezGetCalendar(_Input):
    """Read nightly availability, rates and rules for one property."""
    operation: Literal["get_calendar"] = "get_calendar"
    property_id: Id
    from_date: date = Field(..., title="From date", description="Inclusive property-local date.")
    to_date: date = Field(..., title="To date", description="Inclusive property-local date; at most 366 days.")

    @model_validator(mode="after")
    def bounded_range(self):
        if not 0 <= (self.to_date - self.from_date).days <= 365:
            raise ValueError("Select an ordered range of at most 366 calendar days")
        return self


class OwnerRezListQuotes(_Page):
    """List quotes with optional changed-since filtering."""
    operation: Literal["list_quotes"] = "list_quotes"
    since_utc: AwareDatetime | None = None
    include_guest: bool = False
    include_tags: bool = False


class OwnerRezGetQuote(_Input):
    """Fetch one quote."""
    operation: Literal["get_quote"] = "get_quote"
    quote_id: Id


class OwnerRezCreateQuote(_Stay):
    """Create a quote with explicit email, hold and charge choices."""
    operation: Literal["create_quote"] = "create_quote"
    generate_charges: bool = Field(True, description="Generate default quote charges.")
    generate_email: bool = Field(False, description="Send system email messages after creation.")
    hold_dates: bool = Field(False, description="Create a hold block for the quoted dates.")


class OwnerRezUpdateQuote(_Input):
    """Update quote notes, optionally resetting existing charges."""
    operation: Literal["update_quote"] = "update_quote"
    quote_id: Id
    notes: str = Field(..., max_length=100000)
    generate_charges: bool = Field(False, description="Regenerate and reset quote charges when true.")


class OwnerRezListTagDefinitions(_Page):
    """List the account's tag definitions."""
    operation: Literal["list_tag_definitions"] = "list_tag_definitions"
    active: bool = True


class OwnerRezListTags(_Page):
    """List tags applied to one selected entity."""
    operation: Literal["list_tags"] = "list_tags"
    entity_id: Id
    entity_type: EntityType


class OwnerRezAddTag(_Input):
    """Apply a named tag, creating its definition if needed."""
    operation: Literal["add_tag"] = "add_tag"
    entity_id: Id
    entity_type: EntityType
    name: str = Field(..., min_length=1, max_length=1000)


class OwnerRezRemoveTag(_Input):
    """Remove a tag assignment by ID, preserving its definition."""
    operation: Literal["remove_tag"] = "remove_tag"
    tag_id: Id


# OwnerRez's own MCP server: agents get its tools through a person's OwnerRez sign-in.
OwnerrezMcpCredential = mcp_credential("ownerrez", "https://api.ownerrez.com/mcp", app="OwnerRez")
OwnerRezCredential = Union[OwnerRezPersonalTokenCredential, OwnerrezMcpCredential]


OwnerRezConfig = Annotated[Union[
    OwnerRezGetCurrentUser, OwnerRezListBookings, OwnerRezGetBooking, OwnerRezCreateBooking,
    OwnerRezUpdateBooking, OwnerRezListGuests, OwnerRezGetGuest, OwnerRezCreateGuest,
    OwnerRezUpdateGuest, OwnerRezListProperties, OwnerRezGetProperty, OwnerRezGetCalendar,
    OwnerRezListQuotes, OwnerRezGetQuote, OwnerRezCreateQuote, OwnerRezUpdateQuote,
    OwnerRezListTagDefinitions, OwnerRezListTags, OwnerRezAddTag, OwnerRezRemoveTag,
], Field(discriminator="operation")]


class OwnerRezFullConfig(NodeConfig[OwnerRezConfig, OwnerRezCredential]):
    pass


ROUTES = {
    "get_current_user": ("GET", "/v2/users/me"),
    "list_bookings": ("GET", "/v2/bookings"),
    "get_booking": ("GET", "/v2/bookings/{booking_id}"),
    "create_booking": ("POST", "/v2/bookings"),
    "update_booking": ("PATCH", "/v2/bookings/{booking_id}"),
    "list_guests": ("GET", "/v2/guests"),
    "get_guest": ("GET", "/v2/guests/{guest_id}"),
    "create_guest": ("POST", "/v2/guests"),
    "update_guest": ("PATCH", "/v2/guests/{guest_id}"),
    "list_properties": ("GET", "/v2/properties"),
    "get_property": ("GET", "/v2/properties/{property_id}"),
    "get_calendar": ("GET", "/v2/calendar/{property_id}"),
    "list_quotes": ("GET", "/v2/quotes"),
    "get_quote": ("GET", "/v2/quotes/{quote_id}"),
    "create_quote": ("POST", "/v2/quotes"),
    "update_quote": ("PATCH", "/v2/quotes/{quote_id}"),
    "list_tag_definitions": ("GET", "/v2/tagdefinitions"),
    "list_tags": ("GET", "/v2/tags"),
    "add_tag": ("POST", "/v2/tags"),
    "remove_tag": ("DELETE", "/v2/tags/{tag_id}"),
}


class OwnerRezNode(WorkflowNode):
    integration_type = "automation-ownerrez"
    credential_provider_labels = {"ownerrez": "OwnerRez Account"}
    connection_evidence = ConnectionEvidence(noun="OwnerRez account", identity_operation="get_current_user", identity_keys=("email_address", "company_name", "id"))

    @classmethod
    def get_config_model(cls):
        return OwnerRezFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an OwnerRez personal access token")
        config, credential = self.config.config, self.config.credentials
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("booking_id", "guest_id", "property_id", "quote_id", "tag_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", str(values.pop(field)))
        if config.operation == "get_calendar":
            values["from"] = values.pop("from_date")
            values["to"] = values.pop("to_date")
        if config.operation == "create_guest" and "email_address" in values:
            values["email_addresses"] = [{"address": values.pop("email_address"), "is_default": True}]
        if config.operation == "create_booking":
            values["type"] = "booking"
        if method == "GET":
            values = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                auth=httpx.BasicAuth(credential.email, credential.personal_access_token),
                headers={"Accept": "application/json", "User-Agent": "NoClick/1.0 (OwnerRez personal integration)"},
                **({"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}))
        if not 200 <= response.status_code < 300:
            message = "OwnerRez rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    messages = error.get("messages")
                    if isinstance(messages, list) and messages and all(isinstance(item, str) for item in messages):
                        message = "\n".join(messages)
                    else:
                        message = str(error.get("message") or error.get("error_description") or message)
            except ValueError:
                pass
            message = message.replace(credential.personal_access_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message[:2000]}
        if method == "DELETE":
            return {"status": "success", "deleted": True, "tag_id": config.tag_id}
        if len(response.content) > 10_000_000:
            raise ValueError("OwnerRez response exceeds the JSON size limit")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected an OwnerRez JSON object")
        if "messages" in body and ("code" in body or "status_code" in body):
            raise ValueError("OwnerRez returned an error envelope with a success HTTP status")
        if config.operation.startswith("list_"):
            if not isinstance(body.get("items"), list):
                raise ValueError("OwnerRez page is missing its items array")
            return {"status": "success", "data": body, "items": body["items"],
                "next_page_url": body.get("next_page_url"), "has_more": bool(body.get("next_page_url"))}
        if config.operation == "get_current_user" and not (body.get("email_address") or body.get("id")):
            raise ValueError("OwnerRez did not return an account identity")
        return {"status": "success", "data": body}
