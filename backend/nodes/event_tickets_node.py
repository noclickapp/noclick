"""Event Tickets v1 ticket, attendee and cart actions.

Contract: https://docs.theeventscalendar.com/tec-tickets-v1-doc.json
Auth: https://dev.theeventscalendar.com/knowledgebase/rest-api-authentication/
Application passwords: https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/
Cart updates replace quantities in a new request session; they do not purchase tickets.
"""
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class EventTicketsApplicationPasswordCredential(BaseModel):
    model_config = ConfigDict(title="Event Tickets Application Password", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/",
            "x-credential-instructions": "In your WordPress admin, open Users → Profile → Application Passwords and create a password. Enter the site URL, your username and that application password. Your user needs permission to read attendees. Requires WordPress 5.6 or later and Event Tickets. Cart actions use a new session and do not place an order.",
        })
    credential_type: Literal["event_tickets_application_password"] = Field("event_tickets_application_password", json_schema_extra={"ui:hidden": True})
    site_url: str = Field(..., title="WordPress site URL", description="HTTPS site root, including a WordPress installation subdirectory if needed.")
    username: str = Field(..., min_length=1, max_length=250, title="WordPress username")
    application_password: str = Field(..., min_length=1, max_length=4096, title="Application password", json_schema_extra={"ui:widget": "password"})

    @field_validator("site_url")
    @classmethod
    def site(cls, value):
        value = value.strip().rstrip("/")
        try:
            p = urlsplit(value)
            if p.scheme != "https" or not p.hostname or "." not in p.hostname or p.username or p.password or p.query or p.fragment or p.port not in (None, 443):
                raise ValueError()
            if any(c.isspace() or ord(c) < 32 for c in value) or any(s in (".", "..") for s in p.path.split("/")) or "%" in p.path or "\\" in value:
                raise ValueError()
        except ValueError:
            raise ValueError("Enter an HTTPS WordPress site root without credentials, query or fragment") from None
        return value

    @field_validator("username")
    @classmethod
    def user(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter the WordPress username without a colon or controls")
        return value

    @field_validator("application_password")
    @classmethod
    def password(cls, value):
        value = clean_secret(value, field_name="Application password")
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Paste an application password without controls")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page to retrieve. Each action returns one page; use next_page for continuation.")
    per_page: int = Field(20, ge=1, le=100)


class ListTickets(_Page):
    operation: Literal["list_tickets"] = "list_tickets"
    provider: str | None = Field(None, description="Comma-separated ticket providers, such as rsvp or woo.")
    after: str | None = Field(None, description="Tickets created on or after this UTC date or timestamp.")
    before: str | None = Field(None, description="Tickets created on or before this UTC date or timestamp.")
    status: str | None = None


class SearchTickets(_Page):
    operation: Literal["search_tickets"] = "search_tickets"
    search: str = Field(..., min_length=1, max_length=1000, description="Search ticket titles and descriptions.")


class ListAvailableTickets(_Page):
    operation: Literal["list_available_tickets"] = "list_available_tickets"
    is_available: Literal[True] = Field(True, description="Only currently available tickets.")


class ListEventTickets(_Page):
    operation: Literal["list_event_tickets"] = "list_event_tickets"
    include_post: int = Field(..., gt=0, title="Event post ID")


class GetTicket(_Input):
    operation: Literal["get_ticket"] = "get_ticket"
    id: int = Field(..., gt=0, title="Ticket ID")


class ListAttendees(_Page):
    operation: Literal["list_attendees"] = "list_attendees"
    provider: str | None = None
    after: str | None = Field(None, description="Attendees created on or after this UTC date or timestamp.")
    before: str | None = Field(None, description="Attendees created on or before this UTC date or timestamp.")
    order_status: str | None = None


class FindAttendees(_Page):
    operation: Literal["find_attendees"] = "find_attendees"
    email: str = Field(..., min_length=1, max_length=320, description="Find attendees with an email like this value.")


class ListEventAttendees(_Page):
    operation: Literal["list_event_attendees"] = "list_event_attendees"
    post_id: int = Field(..., gt=0, title="Event post ID")


class ListTicketAttendees(_Page):
    operation: Literal["list_ticket_attendees"] = "list_ticket_attendees"
    ticket_id: int = Field(..., gt=0)


class ListCheckedInAttendees(_Page):
    operation: Literal["list_checked_in_attendees"] = "list_checked_in_attendees"
    checkedin: bool = Field(True, description="Yes for checked-in attendees; No for attendees awaiting check-in.")
    post_id: int | None = Field(None, gt=0, title="Event post ID")


class GetAttendee(_Input):
    operation: Literal["get_attendee"] = "get_attendee"
    id: int = Field(..., gt=0, title="Attendee ID")


class GetCart(_Input):
    operation: Literal["get_cart"] = "get_cart"
    provider: str | None = None
    post_id: int | None = Field(None, gt=0)


class CartTicket(_Input):
    ticket_id: int = Field(..., gt=0)
    quantity: int = Field(..., ge=0, le=10000)


class UpdateCart(_Input):
    operation: Literal["update_cart"] = "update_cart"
    provider: str = Field(..., min_length=1, max_length=100, description="Commerce provider, for example woo. Must be enabled on the site.")
    tickets: list[CartTicket] = Field(..., min_length=1, max_length=100, description="Replace cart ticket quantities in a new session. This does not place an order or modify a shopper's existing browser cart.")
    post_id: int | None = Field(None, gt=0)


EventTicketsConfig = Annotated[Union[ListTickets, SearchTickets, ListAvailableTickets, ListEventTickets,
    GetTicket, ListAttendees, FindAttendees, ListEventAttendees, ListTicketAttendees,
    ListCheckedInAttendees, GetAttendee, GetCart, UpdateCart], Field(discriminator="operation")]


class EventTicketsFullConfig(NodeConfig[EventTicketsConfig, EventTicketsApplicationPasswordCredential]):
    pass


# Every action maps to one published HTTP operation. Filtered lists expose common
# automation tasks without inventing create/update/check-in endpoints absent in v1.
ROUTES = {
    "list_tickets": ("GET", "/tickets"), "search_tickets": ("GET", "/tickets"),
    "list_available_tickets": ("GET", "/tickets"), "list_event_tickets": ("GET", "/tickets"),
    "get_ticket": ("GET", "/tickets/{id}"), "list_attendees": ("GET", "/attendees"),
    "find_attendees": ("GET", "/attendees"), "list_event_attendees": ("GET", "/attendees"),
    "list_ticket_attendees": ("GET", "/attendees"), "list_checked_in_attendees": ("GET", "/attendees"),
    "get_attendee": ("GET", "/attendees/{id}"), "get_cart": ("GET", "/cart"),
    "update_cart": ("POST", "/cart"),
}


class EventTicketsNode(WorkflowNode):
    integration_type = "automation-event-tickets"
    connection_evidence = ConnectionEvidence(operation="list_attendees", noun="attendees")

    @classmethod
    def get_config_model(cls):
        return EventTicketsFullConfig

    @staticmethod
    def _config_view(data):
        # Saved credential attachments are editor metadata, not API arguments.
        if not isinstance(data.get("config"), dict):
            return data
        return {**data, "config": {k: v for k, v in data["config"].items() if k != "credentialIds"}}

    @classmethod
    def parse_config(cls, config_data):
        return super().parse_config(cls._config_view(config_data))

    @classmethod
    def validate_config(cls, config_data):
        return super().validate_config(cls._config_view(config_data))

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect an Event Tickets application password")
        config = self.config.config
        method, route = ROUTES[config.operation]
        fields = config.model_dump(exclude={"operation"}, exclude_none=True)
        if "{id}" in route:
            route = route.replace("{id}", str(fields.pop("id")))
        params = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in fields.items()} if method == "GET" else None
        form = None
        if method == "POST":
            form = {"provider": config.provider}
            if config.post_id is not None:
                form["post_id"] = str(config.post_id)
            for index, ticket in enumerate(config.tickets):
                # The provider documents a list of ticket_id/quantity records.
                form[f"tickets[{index}][ticket_id]"] = str(ticket.ticket_id)
                form[f"tickets[{index}][quantity]"] = str(ticket.quantity)
        url = credential.site_url + "/wp-json/tribe/tickets/v1" + route
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, params=params, data=form,
                auth=httpx.BasicAuth(credential.username, credential.application_password),
                headers={"Accept": "application/json"})
        if response.status_code != 200:
            # Preserve provider rejection wording without reflecting secrets.
            try:
                message = response.json().get("message", "Event Tickets request failed")
            except (ValueError, AttributeError):
                message = "Event Tickets request failed"
            message = str(message)[:2000].replace(credential.application_password, "[redacted]")
            raise ValueError(f"Event Tickets HTTP {response.status_code}: {message}")
        if "json" not in response.headers.get("Content-Type", "").lower() or len(response.content) > 10_000_000:
            raise ValueError("Event Tickets did not return bounded JSON")
        body = response.json()
        if not isinstance(body, dict) or "code" in body or "error" in body:
            raise ValueError("Event Tickets returned an unexpected response")
        if route in ("/tickets", "/attendees"):
            resource = route[1:]
            if not isinstance(body.get(resource), list):
                raise ValueError("Event Tickets list response is missing its records")
            pages = body.get("total_pages")
            if type(pages) is not int or pages < 0:
                raise ValueError("Event Tickets list response is missing total_pages")
            return {**body, "next_page": config.page + 1 if config.page < pages else None}
        return body
