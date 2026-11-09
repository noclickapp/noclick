"""Appointedd JSON API v2. Contract: https://json-api.appointedd.com/openapi/json.

A manually supplied bearer token supports the provider's documented long-lived
access-token option. Polls watch a configurable updated-since window, including
all pages, and deduplicate each resource's documented created/updated revision.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://json-api.appointedd.com"
Id = Annotated[str, Field(pattern=r"^[a-f\d]{24}$")]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class AppointeddTokenCredential(BaseModel):
    model_config = ConfigDict(title="Appointedd Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.appointedd.com/v2.0/reference/introduction-1",
            "x-credential-instructions": "Create an OAuth client in Appointedd's API integration settings, then use Create OAuth Token to generate a bearer access token. Paste only the token here. Appointedd supports long-lived tokens; choose an expiry appropriate for your account and replace the token before it expires. NoClick does not refresh this manually supplied token.",
        })
    credential_type: Literal["appointedd_access_token"] = Field("appointedd_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the bearer token, without a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Page(Input):
    page_size: int = Field(100, ge=1, le=1000, description="Number of records on this page; use next_page_after for the following page.")
    page_after: Id | None = None


class AccountPage(Page):
    account_id: Id | None = Field(None, description="Restrict to one Appointedd account, or leave empty for all accounts this token can access.")


class ChangesPage(AccountPage):
    updated_since: datetime | None = Field(None, description="Only records updated since this ISO 8601 date and time, including a timezone.")
    @field_validator("updated_since")
    @classmethod
    def aware(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Include the timezone in updated_since")
        return value


class CustomerAttributes(Input):
    firstname: Text | None = None
    lastname: Text | None = None
    email: str | None = None
    tags: list[Text] | None = None
    marketingOptIn: StrictBool | None = Field(None, title="Marketing opt in", description="Set only with the customer's consent.")
    customFields: dict[str, str] | None = Field(None, title="Custom fields")
    @model_validator(mode="after")
    def no_null_fields(self):
        if any(getattr(self, k) is None for k in self.model_fields_set - {"email"}):
            raise ValueError("Only email may be explicitly cleared with null")
        return self


class NewCustomerAttributes(CustomerAttributes):
    firstname: Text
    lastname: Text


class ListAccounts(Page):
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True, "x-display-name": "List Accounts"})


class GetAccount(Input):
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Account"})
    account_id: Id


class ListBookings(ChangesPage):
    operation: Literal["list_bookings"] = Field("list_bookings", json_schema_extra={"ui:hidden": True, "x-display-name": "List Bookings"})


class GetBooking(Input):
    operation: Literal["get_booking"] = Field("get_booking", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Booking"})
    booking_id: Id


class ListCustomers(ChangesPage):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True, "x-display-name": "List Customers"})


class GetCustomer(Input):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Customer"})
    customer_id: Id


class ListEvents(ChangesPage):
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True, "x-display-name": "List Events"})


class GetEvent(Input):
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Event"})
    event_id: Id


class ListServices(AccountPage):
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"ui:hidden": True, "x-display-name": "List Services"})


class GetService(Input):
    operation: Literal["get_service"] = Field("get_service", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Service"})
    service_id: Id


class ListResources(AccountPage):
    operation: Literal["list_resources"] = Field("list_resources", json_schema_extra={"ui:hidden": True, "x-display-name": "List Resources"})


class GetResource(Input):
    operation: Literal["get_resource"] = Field("get_resource", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Resource"})
    resource_id: Id


class CreateCustomer(Input):
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Customer"})
    account_id: Id
    attributes: NewCustomerAttributes


class UpdateCustomer(Input):
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Customer"})
    customer_id: Id
    attributes: CustomerAttributes


class DeleteCustomer(Input):
    """Permanently delete a customer by ID."""
    operation: Literal["delete_customer"] = Field("delete_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Customer"})
    customer_id: Id


class CancelBooking(Input):
    """Cancel a participant booking; Appointedd may send cancellation communications."""
    operation: Literal["cancel_booking"] = Field("cancel_booking", json_schema_extra={"ui:hidden": True, "x-display-name": "Cancel Booking"})
    booking_id: Id


class CancelEvent(Input):
    """Cancel the event for all participants; Appointedd may send cancellation communications."""
    operation: Literal["cancel_event"] = Field("cancel_event", json_schema_extra={"ui:hidden": True, "x-display-name": "Cancel Event"})
    event_id: Id


class Range(Input):
    start: datetime
    end: datetime
    @model_validator(mode="after")
    def ordered(self):
        if self.start.utcoffset() is None or self.end.utcoffset() is None or self.start > self.end:
            raise ValueError("Use a nondecreasing range with timezones")
        return self


class AvailabilityAccount(Input):
    accountId: Id = Field(..., title="Account ID")
    serviceId: Id = Field(..., title="Service ID")
    resourceIds: list[Id] | None = Field(None, title="Resource IDs")


class SearchAvailability(Input):
    operation: Literal["search_availability"] = Field("search_availability", json_schema_extra={"ui:hidden": True, "x-display-name": "Search Availability"})
    ranges: list[Range] = Field(..., min_length=1)
    accounts: list[AvailabilityAccount] = Field(..., min_length=1, max_length=25)
    duration: int | None = Field(None, ge=1)
    spaces: int = Field(1, ge=1)
    timezone: str = "Europe/London"


class CreateReservation(Input):
    operation: Literal["create_reservation"] = Field("create_reservation", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Reservation"})
    account_id: Id
    service_id: Id
    start: datetime
    resource_id: Id | None = None
    required_spaces: int = Field(1, ge=1)
    timezone: str = "UTC"
    @field_validator("start")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None: raise ValueError("Include a timezone")
        return value


class ExistingParticipant(Input):
    type: Literal["ExistingCustomer"] = "ExistingCustomer"
    id: Id = Field(..., title="Customer ID")
    notes: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    spaces: int = Field(1, ge=1, le=500)


class CreateEvent(Input):
    """Finalize a reservation as an event with existing customers. Booking communications follow Appointedd account settings."""
    operation: Literal["create_event"] = Field("create_event", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Event"})
    account_id: Id
    reservation_id: Id
    participants: list[ExistingParticipant] = Field(..., min_length=1, max_length=100)
    label: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    timezone: str = "UTC"
    send_payment_request: StrictBool = Field(False, description="Explicitly enable to send payment requests to participants.")


class PollChanges(PollTriggerConfigBase):
    account_id: Id | None = None
    updated_since: datetime | None = Field(None, description="Optional fixed lower bound for this watch; include a timezone. The full matching collection is checked each poll.")
    @field_validator("updated_since")
    @classmethod
    def aware(cls, value):
        if value is not None and value.utcoffset() is None: raise ValueError("Include a timezone")
        return value


class OnBookingChanged(PollChanges):
    operation: Literal["on_booking_changed"] = Field("on_booking_changed", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Booking"})


class OnCustomerChanged(PollChanges):
    operation: Literal["on_customer_changed"] = Field("on_customer_changed", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Customer"})


AppointeddConfig = Annotated[Union[ListAccounts, GetAccount, ListBookings, GetBooking, ListCustomers, GetCustomer, ListEvents, GetEvent, ListServices, GetService, ListResources, GetResource, CreateCustomer, UpdateCustomer, DeleteCustomer, CancelBooking, CancelEvent, SearchAvailability, CreateReservation, CreateEvent, OnBookingChanged, OnCustomerChanged], Field(discriminator="operation")]


class AppointeddNodeConfig(NodeConfig[AppointeddConfig, AppointeddTokenCredential]):
    model_config = ConfigDict(title="Appointedd Node Configuration")


class AppointeddNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-appointedd"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="Appointedd accounts")

    @classmethod
    def get_config_model(cls):
        return AppointeddNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_booking_changed", "on_customer_changed"}:
            return bool(output.get("changed_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "changed_items" not in output:
            return super().resolve_agent_event(output)
        items = output["changed_items"]
        if not items: return None
        lines = []
        for row in items[:10]:
            attrs = row["attributes"]
            if row["type"] == "Customer":
                description = " ".join(str(attrs.get(k) or "") for k in ("firstname", "lastname")).strip()
                detail = attrs.get("email") or ""
            else:
                description = f"{attrs.get('state', '')} booking at {attrs.get('start', '')}"
                detail = attrs.get("notes") or ""
            lines.append(f"- {row['type']} {row['id']}: {description}; {detail}; relationships: {row.get('relationships', {})}")
        return {"text": f"Appointedd: {len(items)} new or updated record(s):\n" + "\n".join(lines), "conversation_key": None}

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None: raise ValueError("Connect an Appointedd access token")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.is_error:
            try:
                detail = response.json().get("message", "Request rejected")
            except (ValueError, AttributeError):
                detail = "Request rejected"
            # The provider's rejection is evidence; ensure a reflected secret is redacted.
            raise ValueError(f"Appointedd API {response.status_code}: {str(detail).replace(credential.access_token, '[redacted]')}")
        if response.status_code == 204: return {"acknowledged": True}
        payload = response.json()
        if not isinstance(payload, dict) or "errors" in payload:
            raise ValueError("Unexpected Appointedd JSON response")
        return payload

    @staticmethod
    def _params(op, *, size=None, after=None, kind=None):
        params = {"page[first]": size or getattr(op, "page_size", 100)}
        cursor = after or getattr(op, "page_after", None)
        if cursor: params["page[after]"] = cursor
        if getattr(op, "account_id", None): params["filter[accountIds]"] = [op.account_id]
        if getattr(op, "updated_since", None):
            key = "filter[updatedSince]" if kind == "customers" else "filter[updated][after]"
            params[key] = op.updated_since.isoformat()
        return params

    @staticmethod
    def _rows(payload, kind):
        rows = payload.get("data")
        if not isinstance(rows, list): raise ValueError("Appointedd list response has no data array")
        expected = {"bookings": "Booking", "customers": "Customer", "events": "Event", "accounts": "Account", "services": "Service", "resources": "Resource"}[kind]
        for row in rows:
            if not isinstance(row, dict) or row.get("type") != expected or not isinstance(row.get("id"), str) or not isinstance(row.get("attributes"), dict):
                raise ValueError("Invalid Appointedd resource")
        return rows

    async def _poll(self, op, kind):
        rows, seen, cursor = [], set(), None
        for _ in range(10):
            payload = await self._request("GET", "/v2/" + kind, params=self._params(op, size=1000, after=cursor, kind=kind))
            page = self._rows(payload, kind)
            for row in page:
                if row["id"] in seen: raise ValueError("Appointedd repeated a record across poll pages")
                seen.add(row["id"])
                rows.append(row)
            # The documented total counts all matching documents. A next link
            # alone is insufficient to prove there are additional records.
            total = payload["meta"]["total"]
            if not isinstance(total, (int, float)) or isinstance(total, bool) or total < 0:
                raise ValueError("Appointedd returned an invalid matching total")
            if len(rows) >= total: break
            # Forward cursor pagination is by resource ID. Never follow a remote URL.
            if not page or not payload["links"]["next"]:
                raise ValueError("Appointedd returned an incomplete matching collection")
            cursor = page[-1]["id"]
        else:
            raise ValueError("More than 10,000 records match this watch; narrow account or updated_since")
        def revision(row):
            attrs = row["attributes"]
            return row["id"] + ":" + str(attrs.get("updated") or attrs["created"])
        fresh = await self._filter_unseen(rows, revision)
        return {"changed_items": fresh, "changed_count": len(fresh)}

    async def execute(self, inputs):
        op = self.config.config
        action = op.operation
        if action in {"on_booking_changed", "on_customer_changed"}:
            return await self._poll(op, "bookings" if action == "on_booking_changed" else "customers")
        if action.startswith("list_"):
            kind = action[5:]
            payload = await self._request("GET", "/v2/" + kind, params=self._params(op, kind=kind))
            rows = self._rows(payload, kind)
            result = {**payload, "next_page_after": rows[-1]["id"] if rows and payload.get("links", {}).get("next") else None}
            if kind == "accounts":
                result["items"] = [{"id": row["id"], "name": row["attributes"].get("name") or row["attributes"]["slug"]} for row in rows]
            return result
        if action.startswith("get_"):
            kind = action[4:]
            return await self._request("GET", f"/v2/{kind}s/{getattr(op, kind + '_id')}")
        if action in {"cancel_booking", "cancel_event"}:
            kind = action[7:]
            return await self._request("POST", f"/v2/{kind}s/{getattr(op, kind + '_id')}/cancel")
        if action == "delete_customer":
            return await self._request("DELETE", f"/v2/customers/{op.customer_id}")
        if action in {"create_customer", "update_customer"}:
            attrs = op.attributes.model_dump(mode="json", exclude_unset=True)
            if not attrs: raise ValueError("Provide at least one customer field")
            body = {"attributes": attrs}
            if action == "create_customer":
                body["relationships"] = {"account": {"data": {"type": "Account", "id": op.account_id}}}
            return await self._request("POST" if action == "create_customer" else "PATCH",
                "/v2/customers" + ("/" + op.customer_id if action == "update_customer" else ""), body=body)
        if action == "search_availability":
            return await self._request("POST", "/v2/availability/intervals/search", body=op.model_dump(mode="json", exclude_none=True, exclude={"operation"}))
        if action == "create_reservation":
            attrs = {"accountId": op.account_id, "serviceId": op.service_id, "start": op.start.isoformat(),
                "requiredSpaces": op.required_spaces, "timezone": op.timezone}
            if op.resource_id: attrs["resourceId"] = op.resource_id
            return await self._request("POST", "/v2/reservations", body={"type": "Reservation", "attributes": attrs})
        if action == "create_event":
            attrs = {"accountId": op.account_id, "reservationId": op.reservation_id,
                "participants": [v.model_dump(exclude_none=True) for v in op.participants],
                "sendPaymentRequest": op.send_payment_request, "timezone": op.timezone}
            if op.label is not None: attrs["label"] = op.label
            return await self._request("POST", "/v2/events", body={"type": "Event", "attributes": attrs})
        raise ValueError("Unsupported Appointedd operation")
