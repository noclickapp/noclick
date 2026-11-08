"""Bookingmood v1 bookings, guest records and operational reads.

Each action maps to one published operation; lists expose explicit offset paging.
"""
from datetime import date, datetime, timezone
from uuid import UUID, uuid4
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class BookingmoodCredential(BaseModel):
    model_config = ConfigDict(title="Bookingmood API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.bookingmood.com/v1/openapi.json",
        "x-credential-instructions": "Paste an API key from your Bookingmood organization. Give it read access to organizations for connection verification and access to the resources your workflow uses. The key is sent as a bearer token."})
    credential_type: Literal["bookingmood_api_key"] = "bookingmood_api_key"
    api_key: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "password"})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    limit: int = Field(100, ge=1, le=1000, description="Number of rows on this page.")
    offset: int = Field(0, ge=0, description="Skip this many rows; increase by the number returned to read the next page.")


class ListOrganizations(Page):
    """Read one page of organizations."""
    operation: Literal["list_organizations"] = "list_organizations"


class ListProducts(Page):
    """Read one page of products."""
    operation: Literal["list_products"] = "list_products"


class ListBookings(Page):
    """Read one page of bookings."""
    operation: Literal["list_bookings"] = "list_bookings"


class ListCalendarEvents(Page):
    """Read one page of calendar events."""
    operation: Literal["list_calendar_events"] = "list_calendar_events"


class ListContacts(Page):
    """Read one page of contacts."""
    operation: Literal["list_contacts"] = "list_contacts"


class ListInvoices(Page):
    """Read one page of invoices."""
    operation: Literal["list_invoices"] = "list_invoices"


class ListPayments(Page):
    """Read one page of payments."""
    operation: Literal["list_payments"] = "list_payments"


class ListTasks(Page):
    """Read one page of tasks."""
    operation: Literal["list_tasks"] = "list_tasks"


class ListCalendarEventNotes(Page):
    """Read one page of calendar event notes."""
    operation: Literal["list_calendar_event_notes"] = "list_calendar_event_notes"


class ListServices(Page):
    """Read one page of services."""
    operation: Literal["list_services"] = "list_services"


class ListCapacityGroups(Page):
    """Read one page of capacity groups."""
    operation: Literal["list_capacity_groups"] = "list_capacity_groups"


class ListBookingDetails(Page):
    """Read one page of booking details."""
    operation: Literal["list_booking_details"] = "list_booking_details"


class GetBooking(Input):
    """Read a single booking by exact ID."""
    operation: Literal["get_booking"] = "get_booking"
    id: UUID


class GetProduct(Input):
    """Read a single product by exact ID."""
    operation: Literal["get_product"] = "get_product"
    id: UUID


class GetContact(Input):
    """Read a single contact by exact ID."""
    operation: Literal["get_contact"] = "get_contact"
    id: UUID


class GetTask(Input):
    """Read a single task by exact ID."""
    operation: Literal["get_task"] = "get_task"
    id: UUID


class DeleteBooking(Input):
    """Delete only the row with this exact ID; related data may be removed by the provider."""
    operation: Literal["delete_booking"] = "delete_booking"
    id: UUID


class DeleteCalendarEvent(Input):
    """Delete only the row with this exact ID; related data may be removed by the provider."""
    operation: Literal["delete_calendar_event"] = "delete_calendar_event"
    id: UUID


class DeleteContact(Input):
    """Delete only the row with this exact ID; related data may be removed by the provider."""
    operation: Literal["delete_contact"] = "delete_contact"
    id: UUID


class DeleteTask(Input):
    """Delete only the row with this exact ID; related data may be removed by the provider."""
    operation: Literal["delete_task"] = "delete_task"
    id: UUID


class DeleteCalendarEventNote(Input):
    """Delete only the row with this exact ID; related data may be removed by the provider."""
    operation: Literal["delete_calendar_event_note"] = "delete_calendar_event_note"
    id: UUID


class CreateContact(Input):
    """Create a guest contact in the specified organization."""
    operation: Literal["create_contact"] = "create_contact"
    id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    email: str = ""
    phone: str = ""
    first_name: str = ""
    last_name: str = ""
    street: str = ""
    street2: str = ""
    zip: str = ""
    city: str = ""
    province: str = ""
    state: str = ""
    country: str = ""
    notes: str = ""
    company_name: str = ""
    country_code: str = ""
    e_invoice_scheme: str = ""
    e_invoice_address: str = ""
    meta: dict = Field(default_factory=dict)
    sms_opt_in: bool = True


class CreateTask(Input):
    """Create a housekeeping or other task for a calendar event."""
    operation: Literal["create_task"] = "create_task"
    id: UUID = Field(default_factory=uuid4)
    calendar_event_id: UUID
    label: str = Field(..., min_length=1)
    due_at: datetime
    schedule: Literal["arrival", "departure", "manual"] = "manual"


class CreateCalendarEventNote(Input):
    """Attach a private note to a calendar event."""
    operation: Literal["create_calendar_event_note"] = "create_calendar_event_note"
    id: UUID = Field(default_factory=uuid4)
    calendar_event_id: UUID
    note: str = Field(..., min_length=1)


class Interval(Input):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("End date must be on or after start date")
        return self


class CreateBooking(Input):
    """Book a product for an interval; the response may require the guest to complete payment."""
    operation: Literal["create_booking"] = "create_booking"
    product_id: UUID
    interval: Interval
    occupancy: dict[UUID, Annotated[int, Field(ge=0, le=9007199254740991)]]
    form_values: dict = Field(default_factory=dict)
    coupon_codes: list[str] = Field(default_factory=list)
    currency: Optional[Literal['ARS', 'AUD', 'BRL', 'BYN', 'CAD', 'CHF', 'CLP', 'CNY', 'COP', 'CZK', 'DKK', 'EGP', 'EUR', 'GBP', 'HKD', 'HUF', 'ILS', 'INR', 'JPY', 'KRW', 'KYD', 'MAD', 'MXN', 'MYR', 'NGN', 'NOK', 'NZD', 'PEN', 'PHP', 'PLN', 'RON', 'RUB', 'SEK', 'SGD', 'THB', 'TRY', 'TWD', 'UAH', 'USD', 'XOF', 'VND', 'ZAR']] = None
    failure_url: str = "__BOOKING_PAGE__"
    redirect_url: Optional[str] = None
    show_pending_as: Literal["CONFIRMED", "TENTATIVE", "CANCELLED"] = "TENTATIVE"


BookingmoodOperation = Annotated[Union[ListOrganizations, ListProducts, ListBookings, ListCalendarEvents, ListContacts, ListInvoices, ListPayments, ListTasks, ListCalendarEventNotes, ListServices, ListCapacityGroups, ListBookingDetails, GetBooking, GetProduct, GetContact, GetTask, DeleteBooking, DeleteCalendarEvent, DeleteContact, DeleteTask, DeleteCalendarEventNote, CreateContact, CreateTask, CreateCalendarEventNote, CreateBooking], Field(discriminator="operation")]

class BookingmoodConfig(NodeConfig[BookingmoodOperation, BookingmoodCredential]):
    pass


ROUTES = {'list_organizations': ('GET', '/organizations'), 'list_products': ('GET', '/products'), 'list_bookings': ('GET', '/bookings'), 'list_calendar_events': ('GET', '/calendar_events'), 'list_contacts': ('GET', '/contacts'), 'list_invoices': ('GET', '/invoices'), 'list_payments': ('GET', '/payments'), 'list_tasks': ('GET', '/tasks'), 'list_calendar_event_notes': ('GET', '/calendar_event_notes'), 'list_services': ('GET', '/services'), 'list_capacity_groups': ('GET', '/capacity_groups'), 'list_booking_details': ('GET', '/booking_details'), 'get_booking': ('GET', '/bookings'), 'get_product': ('GET', '/products'), 'get_contact': ('GET', '/contacts'), 'get_task': ('GET', '/tasks'), 'delete_booking': ('DELETE', '/bookings'), 'delete_calendar_event': ('DELETE', '/calendar_events'), 'delete_contact': ('DELETE', '/contacts'), 'delete_task': ('DELETE', '/tasks'), 'delete_calendar_event_note': ('DELETE', '/calendar_event_notes'), 'create_contact': ('POST', '/contacts'), 'create_task': ('POST', '/tasks'), 'create_calendar_event_note': ('POST', '/calendar_event_notes'), 'create_booking': ('POST', '/book')}

class BookingmoodNode(WorkflowNode):
    integration_type = "automation-bookingmood"
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")

    @classmethod
    def get_config_model(cls):
        return BookingmoodConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Bookingmood API key")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude={"operation"})
        params = {}
        if method == "GET":
            if op.operation.startswith("get_"):
                params = {"id": "eq." + values["id"], "limit": "1"}
            else:
                params = {k: str(v) for k, v in values.items()}
        elif method == "DELETE":
            params = {"id": "eq." + values["id"]}
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        # Default minimal writes match the contract's bodyless 201/204 responses.
        kwargs = {"json": values} if method == "POST" else {}
        if method == "POST" and path != "/book":
            headers["Prefer"] = "return=minimal"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.bookingmood.com/v1" + path,
                    headers=headers, params=params, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Bookingmood request did not complete; inspect the provider before retrying a write") from None
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": response.text.replace(credential.api_key, "[redacted]")[:2000]}
        body = response.json() if response.content else None
        if method == "GET":
            if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                raise ValueError("Expected Bookingmood rows")
            if op.operation.startswith("get_"):
                if len(body) > 1 or any(row.get("id") != str(op.id) for row in body):
                    raise ValueError("Bookingmood returned a different resource")
                return {"status": "success", "data": body[0] if body else None}
            return {"status": "success", "data": body, "offset": op.offset,
                "next_offset": op.offset + len(body) if len(body) == op.limit else None}
        if path == "/book":
            if not isinstance(body, dict) or not body.get("booking_id"):
                raise ValueError("Bookingmood did not return a booking confirmation; inspect before retrying")
            return {"status": "success", "data": body}
        return {"status": "success", "http_status": response.status_code,
            "acknowledged": True, "id": str(op.id)}
