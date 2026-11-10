"""Mews Connector API v1: fixed, single-call hotel operations.

Contract: https://api.mews.com/Swagger/connector/swagger.yaml
Authentication: https://docs.mews.com/connector-api/guidelines/authentication
List operations return one bounded page and the provider's cursor. Writes are
never retried automatically; a transport failure can follow an applied write.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.mews.com/api/connector/v1/"
CREDENTIAL_TYPE = "mews_tokens"


class MewsTokenCredential(BaseModel):
    model_config = ConfigDict(title="Mews API Tokens", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.mews.com/connector-api/guidelines/authentication",
        "x-credential-instructions": "Paste your production Connector API client token and the property's access token, supplied by Mews for your enabled integration. Use a single-property access token, not a portfolio token. Demo tokens do not work on the production API. NoClick checks the property's configuration when you connect.",
    })
    credential_type: Literal["mews_tokens"] = Field("mews_tokens", json_schema_extra={"ui:hidden": True})
    client_token: str = Field(..., min_length=1, title="Client token", repr=False, json_schema_extra={"ui:widget": "password"})
    access_token: str = Field(..., min_length=1, title="Property access token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("client_token", "access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Mews token")
        if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() for c in value):
            raise ValueError("Paste the Mews token without whitespace or an authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers_and_times(cls, value, info):
        if value is None:
            return value
        if info.field_name.endswith("_id") or info.field_name == "cursor":
            try:
                return str(UUID(value))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Use a Mews UUID") from None
        if info.field_name.endswith("_utc"):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Use an ISO 8601 UTC timestamp, for example 2026-01-01T14:00:00Z") from None
        return value


class _Page(_Input):
    count: int = Field(100, ge=1, le=1000, description="Maximum records on this page. Pass next_cursor to cursor for the next page.")
    cursor: str | None = Field(None, description="UUID cursor returned by the previous page.")


class _UpdatedPage(_Page):
    updated_start_utc: str | None = None
    updated_end_utc: str | None = None

    @model_validator(mode="after")
    def interval(self):
        if bool(self.updated_start_utc) != bool(self.updated_end_utc):
            raise ValueError("Supply both updated time bounds")
        if self.updated_start_utc and datetime.fromisoformat(self.updated_start_utc.replace("Z", "+00:00")) >= datetime.fromisoformat(self.updated_end_utc.replace("Z", "+00:00")):
            raise ValueError("Updated end must follow start")
        return self


class GetConfiguration(_Input):
    """Read the connected property's configuration."""
    operation: Literal["get_configuration"] = "get_configuration"


class ListCustomers(_UpdatedPage):
    """Read a page of guests, optionally filtered by email or ID."""
    operation: Literal["list_customers"] = "list_customers"
    customer_id: str | None = None
    email: str | None = Field(None, max_length=320)


class SearchCustomers(_Input):
    """Search guests active at the property, such as checked-in companions."""
    operation: Literal["search_customers"] = "search_customers"
    name: str = Field(..., min_length=1, max_length=500)


class _CustomerFields(_Input):
    first_name: str | None = Field(None, max_length=500)
    last_name: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=10000, description="Internal notes; replaces the existing notes on update.")

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        if value is not None and ("@" not in value or any(c.isspace() for c in value)):
            raise ValueError("Use an email address")
        return value


class CreateCustomer(_CustomerFields):
    """Create a guest without overwriting an existing guest."""
    operation: Literal["create_customer"] = "create_customer"
    last_name: str = Field(..., min_length=1, max_length=500)


class UpdateCustomer(_CustomerFields):
    """Update supplied guest fields; omitted fields are left unchanged."""
    operation: Literal["update_customer"] = "update_customer"
    customer_id: str

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, n) is not None for n in ("first_name", "last_name", "email", "phone", "notes")):
            raise ValueError("Supply at least one guest field to update")
        return self


class ListReservations(_UpdatedPage):
    """Read reservations through the current versioned endpoint."""
    operation: Literal["list_reservations"] = "list_reservations"
    reservation_id: str | None = None
    service_id: str | None = None
    customer_id: str | None = None


class CreateReservation(_Input):
    """Create one reservation; rate and overbooking checks remain enabled."""
    operation: Literal["create_reservation"] = "create_reservation"
    service_id: str
    customer_id: str
    requested_category_id: str
    rate_id: str
    age_category_id: str = Field(..., description="Age category returned by List Age Categories for this service.")
    person_count: int = Field(..., ge=1, le=1000)
    start_utc: str
    end_utc: str
    state: Literal["Inquired", "Confirmed"] = "Confirmed"
    send_confirmation_email: bool = Field(False, description="Ask Mews to email the guest a confirmation.")
    notes: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def interval(self):
        if datetime.fromisoformat(self.start_utc.replace("Z", "+00:00")) >= datetime.fromisoformat(self.end_utc.replace("Z", "+00:00")):
            raise ValueError("Reservation end must follow start")
        return self


class _Reservation(_Input):
    reservation_id: str


class ConfirmReservation(_Reservation):
    """Confirm one reservation, optionally emailing the guest."""
    operation: Literal["confirm_reservation"] = "confirm_reservation"
    send_confirmation_email: bool = False


class CancelReservation(_Reservation):
    """Cancel one reservation with explicit fee and email choices."""
    operation: Literal["cancel_reservation"] = "cancel_reservation"
    post_cancellation_fee: bool = Field(False, description="Apply the property's cancellation fee.")
    send_email: bool = Field(False, description="Ask Mews to email the guest about cancellation.")
    notes: str | None = Field(None, max_length=10000)


class StartReservation(_Reservation):
    """Check in one reservation."""
    operation: Literal["start_reservation"] = "start_reservation"


class ProcessReservation(_Reservation):
    """Check out a reservation, requiring a balanced account."""
    operation: Literal["process_reservation"] = "process_reservation"
    close_bills: bool = Field(False, description="Ask Mews to close closable bills during checkout.")


class ListResources(_UpdatedPage):
    """Read rooms and other property resources."""
    operation: Literal["list_resources"] = "list_resources"
    resource_id: str | None = None


class UpdateResource(_Input):
    """Update one room's housekeeping state, name or state reason."""
    operation: Literal["update_resource"] = "update_resource"
    resource_id: str
    name: str | None = Field(None, min_length=1, max_length=500)
    state: Literal["Dirty", "Clean", "Inspected", "OutOfService"] | None = None
    state_reason: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.state is None and self.state_reason is None:
            raise ValueError("Supply a resource change")
        return self


class ListTasks(_Page):
    """Read a page of property tasks."""
    operation: Literal["list_tasks"] = "list_tasks"
    task_id: str | None = None
    department_id: str | None = None


class CreateTask(_Input):
    """Create a property task with a UTC deadline."""
    operation: Literal["create_task"] = "create_task"
    name: str = Field(..., min_length=1, max_length=500)
    deadline_utc: str
    description: str | None = Field(None, max_length=10000)
    department_id: str | None = None
    service_order_id: str | None = None


class CloseTask(_Input):
    """Close one task."""
    operation: Literal["close_task"] = "close_task"
    task_id: str


class ListServices(_UpdatedPage):
    """Read services available at the property."""
    operation: Literal["list_services"] = "list_services"
    service_id: str | None = None


class ListRates(_UpdatedPage):
    """Read rates for one service."""
    operation: Literal["list_rates"] = "list_rates"
    service_id: str


class ListProducts(_UpdatedPage):
    """Read products for one service."""
    operation: Literal["list_products"] = "list_products"
    service_id: str


class ListCompanies(_UpdatedPage):
    """Read company accounts."""
    operation: Literal["list_companies"] = "list_companies"
    company_id: str | None = None


class ListAgeCategories(_Page):
    """Read age categories used for reservation person counts."""
    operation: Literal["list_age_categories"] = "list_age_categories"
    service_id: str


class _UpdatedTrigger(PollTriggerConfigBase):
    """Watch changes from the last 24 hours; existing records are baselined when armed.

    Each poll reads at most 2,000 records. Resume within 24 hours to catch changes
    during an interruption; intermediate versions between polls are not emitted.
    """
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True,
                              json_schema_extra={"x-requires-webhook": True})


class OnUpdatedReservation(_UpdatedTrigger):
    """Watch new and updated reservations, including check-in, check-out and cancellation states.

    Poll the last 24 hours, up to 2,000 records, baselining existing records when armed.
    Only the latest version between polls is delivered.
    """
    operation: Literal["on_updated_reservation"] = Field("on_updated_reservation", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Reservation",
    })
    service_id: UUID | None = Field(None, description="Watch one bookable service, or all bookable services when empty.")


class OnUpdatedCustomer(_UpdatedTrigger):
    """Watch new and updated guest profiles.

    Poll the last 24 hours, up to 2,000 records, baselining existing records when armed.
    Only the latest version between polls is delivered.
    """
    operation: Literal["on_updated_customer"] = Field("on_updated_customer", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Guest",
    })


class OnUpdatedResource(_UpdatedTrigger):
    """Watch new and updated rooms/resources, including housekeeping state changes.

    Poll the last 24 hours, up to 2,000 records, baselining existing records when armed.
    Only the latest version between polls is delivered.
    """
    operation: Literal["on_updated_resource"] = Field("on_updated_resource", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Room / Resource",
    })


POLL_OPERATIONS = {
    "on_updated_reservation": (ListReservations, "Reservations"),
    "on_updated_customer": (ListCustomers, "Customers"),
    "on_updated_resource": (ListResources, "Resources"),
}


MewsOperation = Annotated[Union[GetConfiguration, ListCustomers, SearchCustomers,
    CreateCustomer, UpdateCustomer, ListReservations, CreateReservation,
    ConfirmReservation, CancelReservation, StartReservation, ProcessReservation,
    ListResources, UpdateResource, ListTasks, CreateTask, CloseTask,
    ListServices, ListRates, ListProducts, ListCompanies, ListAgeCategories,
    OnUpdatedReservation, OnUpdatedCustomer, OnUpdatedResource], Field(discriminator="operation")]


class MewsFullConfig(NodeConfig[MewsOperation, MewsTokenCredential]):
    pass


# Each action maps to exactly one published operation; no arbitrary URL/body.
ROUTES = {
    "get_configuration": "configuration/get", "list_customers": "customers/getAll",
    "search_customers": "customers/search", "create_customer": "customers/add",
    "update_customer": "customers/update", "list_reservations": "reservations/getAll/2023-06-06",
    "create_reservation": "reservations/add", "confirm_reservation": "reservations/confirm",
    "cancel_reservation": "reservations/cancel", "start_reservation": "reservations/start",
    "process_reservation": "reservations/process", "list_resources": "resources/getAll",
    "update_resource": "resources/update", "list_tasks": "tasks/getAll",
    "create_task": "tasks/add", "close_task": "tasks/close", "list_services": "services/getAll",
    "list_rates": "rates/getAll", "list_products": "products/getAll",
    "list_companies": "companies/getAll", "list_age_categories": "ageCategories/getAll",
}


def _body(op):
    name = op.operation
    body = {}
    if isinstance(op, _Page):
        body["Limitation"] = {"Count": op.count}
        if op.cursor:
            body["Limitation"]["Cursor"] = op.cursor
    if isinstance(op, _UpdatedPage) and op.updated_start_utc:
        body["UpdatedUtc"] = {"StartUtc": op.updated_start_utc, "EndUtc": op.updated_end_utc}
    if name.startswith("list_"):
        mapping = {"customer_id": "CustomerIds", "service_id": "ServiceIds", "reservation_id": "ReservationIds",
                   "resource_id": "ResourceIds", "task_id": "TaskIds", "department_id": "DepartmentIds", "company_id": "Ids"}
        # Reservations filter accounts under AccountIds rather than CustomerIds.
        if name == "list_reservations":
            mapping = {**mapping, "customer_id": "AccountIds"}
        for field, target in mapping.items():
            if getattr(op, field, None) is not None:
                body[target] = [getattr(op, field)]
        if name == "list_customers":
            body["Extent"] = {"Customers": True}
            if op.email:
                body["Emails"] = [op.email]
        elif name == "list_resources":
            body["Extent"] = {"Resources": True}
        return body
    if name == "search_customers":
        return {"Name": op.name, "Extent": {"Customers": True}}
    if name in {"create_customer", "update_customer"}:
        for field, target in {"first_name": "FirstName", "last_name": "LastName", "email": "Email", "phone": "Phone", "notes": "Notes"}.items():
            if getattr(op, field) is not None:
                body[target] = getattr(op, field)
        if name == "create_customer":
            body["OverwriteExisting"] = False
        else:
            body["CustomerId"] = op.customer_id
    elif name == "create_reservation":
        reservation = {"CustomerId": op.customer_id, "RequestedCategoryId": op.requested_category_id,
            "RateId": op.rate_id, "StartUtc": op.start_utc, "EndUtc": op.end_utc, "State": op.state,
            "PersonCounts": [{"AgeCategoryId": op.age_category_id, "Count": op.person_count}]}
        if op.notes is not None:
            reservation["Notes"] = op.notes
        body = {"ServiceId": op.service_id, "Reservations": [reservation],
                "CheckRateApplicability": True, "CheckOverbooking": True, "SendConfirmationEmail": op.send_confirmation_email}
    elif name in {"confirm_reservation", "cancel_reservation"}:
        body = {"ReservationIds": [op.reservation_id]}
        if name == "confirm_reservation":
            body["SendConfirmationEmail"] = op.send_confirmation_email
        else:
            body.update(PostCancellationFee=op.post_cancellation_fee, SendEmail=op.send_email)
            if op.notes is not None:
                body["Notes"] = op.notes
    elif name in {"start_reservation", "process_reservation"}:
        body = {"ReservationId": op.reservation_id}
        if name == "process_reservation":
            body.update(CloseBills=op.close_bills, AllowOpenBalance=False)
    elif name == "update_resource":
        update = {"ResourceId": op.resource_id}
        for field, target in {"name": "Name", "state": "State", "state_reason": "StateReason"}.items():
            if getattr(op, field) is not None:
                update[target] = {"Value": getattr(op, field)}
        body = {"ResourceUpdates": [update]}
    elif name == "create_task":
        for field, target in {"name": "Name", "deadline_utc": "DeadlineUtc", "description": "Description", "department_id": "DepartmentId", "service_order_id": "ServiceOrderId"}.items():
            if getattr(op, field) is not None:
                body[target] = getattr(op, field)
    elif name == "close_task":
        body = {"TaskIds": [op.task_id]}
    return body


def _redact(value, credential):
    # Keep authentication out of all outputs, including provider error text.
    secrets = (credential.client_token, credential.access_token)
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, dict):
        for key in list(value):
            if key.lower() in {"clienttoken", "accesstoken", "client_token", "access_token"}:
                del value[key]
            else:
                value[key] = _redact(value[key], credential)
    elif isinstance(value, list):
        value[:] = [_redact(item, credential) for item in value]
    return value


class MewsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-mews"
    connection_evidence = ConnectionEvidence(noun="property", identity_operation="get_configuration", identity_keys=("Name",))

    @classmethod
    def get_config_model(cls):
        return MewsFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect Mews API tokens")
        credential = self.config.credentials
        op = self.config.config
        if isinstance(op, _UpdatedTrigger):
            return await self._poll_updates(op, credential)
        data = await self._request(op, credential)
        result = {"data": data}
        if isinstance(op, _Page):
            result["next_cursor"] = data.get("Cursor")
        return result

    async def _poll_updates(self, op, credential):
        model, collection = POLL_OPERATIONS[op.operation]
        end = datetime.now(timezone.utc)
        config = {"count": 100, "updated_start_utc": (end - timedelta(days=1)).isoformat(),
                  "updated_end_utc": end.isoformat()}
        if isinstance(op, OnUpdatedReservation):
            config["service_id"] = str(op.service_id) if op.service_id else None
        items = []
        cursors = set()
        for _ in range(20):
            data = await self._request(model(**config), credential)
            page = data.get(collection)
            if not isinstance(page, list):
                raise ValueError(f"Mews returned an invalid {collection} list")
            for item in page:
                if not isinstance(item, dict) or not item.get("Id") or not item.get("UpdatedUtc"):
                    raise ValueError("Mews returned a record without Id or UpdatedUtc")
            items.extend(page)
            cursor = data.get("Cursor")
            if len(page) < config["count"] or not cursor:
                break
            if cursor in cursors:
                raise ValueError("Mews returned a repeated pagination cursor")
            cursors.add(cursor)
            config["cursor"] = cursor
        else:
            raise ValueError("Mews poll reached 2,000 records; narrow the watched scope or contact support")
        fresh = await self._filter_unseen(items, lambda item: item["Id"] + ":" + item["UpdatedUtc"])
        return {"event": op.operation, "records": fresh, "new_record_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("event") if isinstance(output, dict) else None
        if event not in POLL_OPERATIONS:
            return super().resolve_agent_event(output)
        records = output.get("records") or []
        if not records:
            return None
        lines = []
        for item in records[:10]:
            if event == "on_updated_reservation":
                detail = (f"Reservation {item.get('Number')} ({item.get('State')}); "
                          f"account {item.get('AccountId')}, service {item.get('ServiceId')}, "
                          f"room/resource {item.get('AssignedResourceId')}; "
                          f"stay {item.get('ScheduledStartUtc')} to {item.get('ScheduledEndUtc')}")
            elif event == "on_updated_customer":
                detail = f"Guest {item.get('FirstName') or ''} {item.get('LastName')}; {item.get('Email') or ''}"
            else:
                detail = f"Room/resource {item.get('Name')} ({item.get('State')}); property {item.get('EnterpriseId')}"
            lines.append(f"- {detail}; id {item['Id']}; updated {item['UpdatedUtc']}")
        if len(records) > 10:
            lines.append(f"- {len(records) - 10} more records in the trigger output")
        return {"text": f"Mews: {len(records)} new or updated {POLL_OPERATIONS[event][1].lower()}:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _request(self, op, credential):
        body = {**_body(op), "ClientToken": credential.client_token,
                "AccessToken": credential.access_token, "Client": "NoClick 1.0.0"}
        # No redirects, credentials in the JSON body, fixed production origin.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST", BASE_URL + ROUTES[op.operation],
                headers={"Accept": "application/json"}, json=body)
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("Message") or error.get("message") or message
            except ValueError:
                pass
            raise ValueError(f"Mews HTTP {response.status_code}: {_redact(str(message), credential)}")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Mews returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("Mews returned an unexpected response shape")
        if "Message" in data and data["Message"] and ("RequestId" in data or "Details" in data):
            raise ValueError("Mews: " + _redact(str(data["Message"]), credential))
        data = _redact(data, credential)
        return data
