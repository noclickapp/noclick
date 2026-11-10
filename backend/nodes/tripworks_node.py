"""TripWorks REST API 1.1.6. Contract: https://api-docs.tripworks.com/openapi.json.

Webhooks are configured in TripWorks UI; new-customer and new-trip polls use
cursor pagination and persist their baseline through the shared poll family.
"""
from typing import Annotated, Literal, Union, Any
import re
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.tripworks import TRIPWORKS_SCOPES
from utils.ssrf import guarded_async_client

class TripWorksCredential(BaseModel):
    model_config = ConfigDict(title="TripWorks API Key", json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-instructions": "In TripWorks, open Setup → REST API → Keys and create a key with the read/write scopes for the resources you automate. Enter your account subdomain and paste the key shown once.",
        "x-credential-url": "https://api-docs.tripworks.com/"})
    credential_type: Literal["tripworks_api_key"] = Field("tripworks_api_key", json_schema_extra={"ui:hidden": True})
    account: str = Field(..., title="Account subdomain", description="The account part of https://your-account.tripworks.com")
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("account")
    @classmethod
    def valid_account(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter only your TripWorks account subdomain")
        return value

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the REST API key without whitespace")
        return value

class _Input(BaseModel):
    pass

class _List(_Input):
    cursor: str | None = Field(None, description="Opaque next_cursor from the preceding page")
    per_page: int = Field(25, ge=1, le=25)

class _Identified(_Input):
    id: UUID = Field(..., title="Resource ID", description="Public UUID returned by TripWorks")

class _CustomerFields(_Input):
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=35)
    is_opt_in: bool | None = None
    timezone: str | None = Field(None, max_length=45)

class TripWorksListCustomersConfig(_List):
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, description="Exact customer email address")

class TripWorksGetCustomersConfig(_Identified):
    operation: Literal["get_customers"] = Field("get_customers", title="Get Customers", json_schema_extra={"ui:hidden": True})

class TripWorksListTripsConfig(_List):
    operation: Literal["list_trips"] = Field("list_trips", title="List Trips", json_schema_extra={"ui:hidden": True})

class TripWorksGetTripsConfig(_Identified):
    operation: Literal["get_trips"] = Field("get_trips", title="Get Trips", json_schema_extra={"ui:hidden": True})

class TripWorksListBookingsConfig(_List):
    operation: Literal["list_bookings"] = Field("list_bookings", title="List Bookings", json_schema_extra={"ui:hidden": True})

class TripWorksGetBookingsConfig(_Identified):
    operation: Literal["get_bookings"] = Field("get_bookings", title="Get Bookings", json_schema_extra={"ui:hidden": True})

class TripWorksListExperiencesConfig(_List):
    operation: Literal["list_experiences"] = Field("list_experiences", title="List Experiences", json_schema_extra={"ui:hidden": True})

class TripWorksGetExperiencesConfig(_Identified):
    operation: Literal["get_experiences"] = Field("get_experiences", title="Get Experiences", json_schema_extra={"ui:hidden": True})

class TripWorksListLocationsConfig(_List):
    operation: Literal["list_locations"] = Field("list_locations", title="List Locations", json_schema_extra={"ui:hidden": True})

class TripWorksGetLocationsConfig(_Identified):
    operation: Literal["get_locations"] = Field("get_locations", title="Get Locations", json_schema_extra={"ui:hidden": True})

class TripWorksListGiftCardsConfig(_List):
    operation: Literal["list_gift_cards"] = Field("list_gift_cards", title="List Gift Cards", json_schema_extra={"ui:hidden": True})

class TripWorksGetGiftCardsConfig(_Identified):
    operation: Literal["get_gift_cards"] = Field("get_gift_cards", title="Get Gift Cards", json_schema_extra={"ui:hidden": True})

class TripWorksCreateCustomerConfig(_CustomerFields):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer", json_schema_extra={"ui:hidden": True})

class TripWorksUpdateCustomerConfig(_CustomerFields, _Identified):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Customer", json_schema_extra={"ui:hidden": True})

class TripWorksCreateBookingConfig(_Input):
    operation: Literal["create_booking"] = Field("create_booking", title="Create Booking", json_schema_extra={"ui:hidden": True})
    trip_order_id: UUID
    experience_customer_type_id: UUID
    qty: int = Field(1, ge=1, le=100)
    customer_id: UUID | None = None
    dry_run: bool = False
    decisions: dict[str, Any] = Field(default_factory=dict, description="Answers to TripWorks decision_required questions; left empty to ask before saving")

class TripWorksListBookingStatusesConfig(_Input):
    operation: Literal["list_booking_statuses"] = Field("list_booking_statuses", title="List Booking Statuses", json_schema_extra={"ui:hidden": True})

class TripWorksSetBookingStatusConfig(_Identified):
    operation: Literal["set_booking_status"] = Field("set_booking_status", title="Set Booking Status", json_schema_extra={"ui:hidden": True})
    booking_status_id: UUID
    decisions: dict[str, Any] = Field(default_factory=dict, description="Answers to decision_required; empty asks before check-in saves")

class TripWorksListTripNotesConfig(_List):
    operation: Literal["list_trip_notes"] = Field("list_trip_notes", title="List Trip Notes", json_schema_extra={"ui:hidden": True})

class TripWorksCreateTripNoteConfig(_Input):
    operation: Literal["create_trip_note"] = Field("create_trip_note", title="Create Trip Note", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1)
    trip_id: UUID

class TripWorksUpdateTripNoteConfig(_Identified):
    operation: Literal["update_trip_note"] = Field("update_trip_note", title="Update Trip Note", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1)

class TripWorksOnNewCustomersConfig(PollTriggerConfigBase):
    operation: Literal["on_new_customers"] = Field("on_new_customers", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "New Customers", "x-category": "Triggers"})
    created_since: str | None = Field(None, description="Optional UTC creation date lower bound (ISO 8601)")

class TripWorksOnNewTripsConfig(PollTriggerConfigBase):
    operation: Literal["on_new_trips"] = Field("on_new_trips", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "New Trips", "x-category": "Triggers"})
    created_since: str | None = Field(None, description="Optional UTC creation date lower bound (ISO 8601)")

TripWorksConfig = Annotated[Union[TripWorksListCustomersConfig, TripWorksGetCustomersConfig, TripWorksListTripsConfig, TripWorksGetTripsConfig, TripWorksListBookingsConfig, TripWorksGetBookingsConfig, TripWorksListExperiencesConfig, TripWorksGetExperiencesConfig, TripWorksListLocationsConfig, TripWorksGetLocationsConfig, TripWorksListGiftCardsConfig, TripWorksGetGiftCardsConfig, TripWorksCreateCustomerConfig, TripWorksUpdateCustomerConfig, TripWorksCreateBookingConfig, TripWorksListBookingStatusesConfig, TripWorksSetBookingStatusConfig, TripWorksListTripNotesConfig, TripWorksCreateTripNoteConfig, TripWorksUpdateTripNoteConfig, TripWorksOnNewCustomersConfig, TripWorksOnNewTripsConfig], Field(discriminator="operation")]

class TripWorksFullConfig(NodeConfig[TripWorksConfig, TripWorksCredential]):
    pass

OPERATIONS = {'list_customers': ('GET', '/rest/customers'), 'get_customers': ('GET', '/rest/customers/{id}'), 'list_trips': ('GET', '/rest/trips'), 'get_trips': ('GET', '/rest/trips/{id}'), 'list_bookings': ('GET', '/rest/bookings'), 'get_bookings': ('GET', '/rest/bookings/{id}'), 'list_experiences': ('GET', '/rest/experiences'), 'get_experiences': ('GET', '/rest/experiences/{id}'), 'list_locations': ('GET', '/rest/locations'), 'get_locations': ('GET', '/rest/locations/{id}'), 'list_gift_cards': ('GET', '/rest/gift-cards'), 'get_gift_cards': ('GET', '/rest/gift-cards/{id}'), 'create_customer': ('POST', '/rest/customers'), 'update_customer': ('PATCH', '/rest/customers/{id}'), 'create_booking': ('POST', '/rest/bookings'), 'list_booking_statuses': ('GET', '/rest/bookings/statuses'), 'set_booking_status': ('POST', '/rest/bookings/{id}/status'), 'list_trip_notes': ('GET', '/rest/trip-notes'), 'create_trip_note': ('POST', '/rest/trip-notes'), 'update_trip_note': ('PATCH', '/rest/trip-notes/{id}')}

class TripWorksNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-tripworks"
    scope_registry = TRIPWORKS_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_customers", noun="TripWorks customers")

    @classmethod
    def get_config_model(cls):
        return TripWorksFullConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_item_count")) if config.get("operation", "").startswith("on_new_") else True

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your TripWorks account")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, f"https://{credential.account}.tripworks.com" + path,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ValueError("TripWorks did not confirm the request")
        return data

    async def _poll(self, resource, config):
        items, cursor, seen_cursors = [], None, set()
        for _ in range(200):
            params = {"per_page": 25}
            if config.created_since:
                params["created_at[gte]"] = config.created_since
            if resource == "customers":
                params["sort"] = "-created_at"
            if cursor:
                params["cursor"] = cursor
            data = await self._request("GET", "/rest/" + resource, params=params)
            rows = data.get(resource)
            meta = data.get("meta")
            if not isinstance(rows, list) or not isinstance(meta, dict):
                raise ValueError("TripWorks list response is incomplete")
            if any(not isinstance(row, dict) or not row.get("id") for row in rows):
                raise ValueError("TripWorks record lacks its public ID")
            items.extend(rows)
            if meta.get("has_more") is False:
                break
            cursor = meta.get("next_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise ValueError("TripWorks pagination did not progress")
            seen_cursors.add(cursor)
        else:
            raise ValueError("More than 5,000 records; set a later creation date for this poll")
        fresh = await self._filter_unseen(items, lambda item: str(item["id"]))
        return {"status": "success", "items": fresh, "new_item_count": len(fresh)}

    async def execute(self, inputs):
        config = self.config.config
        self.scope_registry.require(config.operation)
        if config.operation.startswith("on_new_"):
            return await self._poll(config.operation.removeprefix("on_new_"), config)
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", values.pop("id"))
        if method == "GET":
            if config.operation == "list_customers" and "email" in values:
                values["email[eq]"] = values.pop("email")
            data = await self._request(method, path, params=values)
        else:
            data = await self._request(method, path, body=values)
        return {"status": "success", **data}
