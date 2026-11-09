"""Microsoft Bookings businesses and their appointments, customers, services and staff.

Each operation makes one fixed Graph v1.0 request. Delegated Microsoft OAuth
uses the existing family sign-in; no tenant URLs or arbitrary requests are accepted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.microsoft_bookings import BOOKINGS_SCOPES

GRAPH_ROOT = "https://graph.microsoft.com/v1.0/solutions/bookingBusinesses"


class MicrosoftBookingsOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Microsoft Bookings OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "microsoft",
            "x-oauth-scopes": sorted(BOOKINGS_SCOPES.declared_scopes()),
            "x-credential-url": "https://learn.microsoft.com/graph/bookings-concept-overview",
            "x-credential-instructions": "Connect a Microsoft work or school account with Microsoft Bookings enabled. Bookings.ReadWrite.All requires tenant consent. Personal Microsoft accounts are unsupported. An existing delegated Graph access token can also be supplied; refresh token and expiry are optional for a manually supplied token.",
        })
    credential_type: Literal["microsoft_oauth"] = Field("microsoft_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field("", title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field("", title="Token expiry", description="ISO 8601 expiry, when provided by Microsoft.")
    email: str = Field("", title="Account email")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without spaces or a Bearer prefix")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body_kind: str = ""


OPERATIONS = {
    "list_businesses": Operation("GET", ""),
    "get_business": Operation("GET", "/{business_id}", ("business_id",)),
    "update_business": Operation("PATCH", "/{business_id}", ("business_id", "display_name", "email", "phone", "website_url"), "business"),
}
for _plural, _singular, _kind in (
    ("appointments", "appointment", "appointment"),
    ("customers", "customer", "customer"),
    ("services", "service", "service"),
):
    _root = "/{business_id}/" + _plural
    _ids = ("business_id", _singular + "_id")
    OPERATIONS["list_" + _plural] = Operation("GET", _root, ("business_id",))
    OPERATIONS["get_" + _singular] = Operation("GET", _root + "/{" + _ids[1] + "}", _ids)
    _body_fields = {
        "appointment": ("service_id", "start", "end", "time_zone", "customer_name", "customer_email", "customer_id", "customer_time_zone", "staff_member_ids", "maximum_attendees_count", "service_notes", "opt_out_of_customer_email"),
        "customer": ("display_name", "email_address"),
        "service": ("display_name", "default_duration", "description", "default_price", "default_price_type", "staff_member_ids", "maximum_attendees_count", "is_hidden_from_customers"),
    }[_kind]
    OPERATIONS["create_" + _singular] = Operation("POST", _root, ("business_id",) + _body_fields, _kind)
    OPERATIONS["update_" + _singular] = Operation("PATCH", _root + "/{" + _ids[1] + "}", _ids + _body_fields, _kind)
    OPERATIONS["delete_" + _singular] = Operation("DELETE", _root + "/{" + _ids[1] + "}", _ids)
OPERATIONS.update({
    "list_staff_members": Operation("GET", "/{business_id}/staffMembers", ("business_id",)),
    "get_staff_member": Operation("GET", "/{business_id}/staffMembers/{staff_member_id}", ("business_id", "staff_member_id")),
})

_TEXT = {
    "display_name": "Display name", "email": "Business email", "phone": "Business phone",
    "website_url": "Business website URL", "email_address": "Customer email",
    "service_id": "Service ID", "start": "Start date and time", "end": "End date and time",
    "customer_name": "Customer name", "customer_email": "Customer email", "customer_id": "Existing customer ID",
    "customer_time_zone": "Customer time zone",
    "service_notes": "Service notes", "description": "Service description", "default_duration": "Default duration",
}
_BODY_MAP = {
    "display_name": "displayName", "email": "email", "phone": "phone", "website_url": "webSiteUrl",
    "email_address": "emailAddress", "service_id": "serviceId", "customer_name": "customerName",
    "customer_email": "customerEmailAddress", "service_notes": "serviceNotes",
    "customer_time_zone": "customerTimeZone",
    "opt_out_of_customer_email": "optOutOfCustomerEmail", "description": "description",
    "default_duration": "defaultDuration", "default_price": "defaultPrice", "default_price_type": "defaultPriceType",
    "staff_member_ids": "staffMemberIds", "maximum_attendees_count": "maximumAttendeesCount",
    "is_hidden_from_customers": "isHiddenFromCustomers",
}


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Provide a Microsoft Bookings resource ID")
    if value in {".", ".."} or "://" in value or "\\" in value:
        raise ValueError("Provide a resource ID, not a URL")
    return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def values(self):
        data = self.model_dump(exclude_none=True)
        spec = OPERATIONS[data["operation"]]
        for key in ("business_id", "appointment_id", "customer_id", "service_id", "staff_member_id"):
            if data.get(key) is not None:
                _identifier(data[key])
        for value in data.get("staff_member_ids", []):
            _identifier(value)
        if data.get("default_duration") in {"P", "PT", "P0D", "PT0S", "PT0M", "PT0H"}:
            raise ValueError("Service duration must be positive")
        for key in ("start", "end"):
            if data.get(key):
                try:
                    datetime.fromisoformat(data[key].replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("Use ISO 8601 date and time for start and end") from None
        if data.get("start") and data.get("end"):
            try:
                if datetime.fromisoformat(data["end"].replace("Z", "+00:00")) <= datetime.fromisoformat(data["start"].replace("Z", "+00:00")):
                    raise ValueError("End must be after start")
            except TypeError:
                raise ValueError("Use matching timezone formats for start and end") from None
        if spec.method == "PATCH" and not any(key in data for key in spec.fields
                if "{" + key + "}" not in spec.path and (key in _BODY_MAP or key in {"start", "end", "customer_id"})):
            raise ValueError("Provide at least one field to update")
        return self


def _config(name, spec):
    title = name.replace("_", " ").title()
    fields: dict[str, Any] = {"operation": (Literal[name], Field(name, title=title,
        json_schema_extra={"ui:hidden": True, "x-display-name": title, "x-is-trigger": False}))}
    required = {
        "create_appointment": {"service_id", "start", "end", "customer_name", "customer_email"},
        "create_customer": {"display_name", "email_address"},
        "create_service": {"display_name", "default_duration"},
    }.get(name, set())
    path_keys = set(re.findall(r"\{(\w+)\}", spec.path))
    for key in spec.fields:
        mandatory = key in path_keys or key in required
        if key == "time_zone":
            fields[key] = (str, Field("UTC", max_length=128, title="Time zone", description="Microsoft-supported time zone for start and end."))
        elif key == "staff_member_ids":
            fields[key] = (list[str] | None, Field(None, max_length=100, title="Staff member IDs", json_schema_extra={"ui:widget": "list"}))
        elif key in {"opt_out_of_customer_email", "is_hidden_from_customers"}:
            fields[key] = (bool | None, Field(None, title=key.replace("_", " ").capitalize()))
        elif key == "maximum_attendees_count":
            fields[key] = (int | None, Field(None, ge=1, le=2147483647, title="Maximum attendees"))
        elif key == "default_price":
            fields[key] = (float | None, Field(None, ge=0, allow_inf_nan=False, title="Default price"))
        elif key == "default_price_type":
            fields[key] = (Literal["undefined", "fixedPrice", "startingAt", "hourly", "free", "priceVaries", "callUs", "notSet"] | None, Field(None, title="Price type"))
        else:
            opts = {"min_length": 1, "max_length": 4096, "title": _TEXT.get(key, key.replace("_", " ").title())}
            if key == "default_duration":
                opts["pattern"] = r"^P(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$"
                opts["description"] = "ISO 8601 duration, for example PT1H30M."
            if key in {"start", "end"}:
                opts["description"] = "ISO 8601 date and time, for example 2018-05-01T12:00:00.0000000+00:00."
            fields[key] = (str if mandatory else str | None, Field(... if mandatory else None, **opts))
    return create_model("MicrosoftBookings" + "".join(x.title() for x in name.split("_")) + "Config", __base__=_Input, **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
BookingsConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class MicrosoftBookingsNodeConfig(NodeConfig[BookingsConfig, MicrosoftBookingsOAuthCredential]):
    pass


class MicrosoftBookingsNode(WorkflowNode):
    integration_type = "automation-microsoft-bookings"
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = BOOKINGS_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_businesses", noun="Bookings businesses", label_keys=("displayName", "id"))
    edit_examples = ["List my Bookings businesses", "Create an appointment for a service", "Update a customer email address", "List staff and services"]

    @classmethod
    def get_config_model(cls):
        return MicrosoftBookingsNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Microsoft work or school account")
        credential = self.config.credentials
        token = credential.access_token
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.microsoft_oauth import refresh_access_token
            blob = credential.model_dump()
            token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=blob, refresh=refresh_access_token,
                provider="microsoft", caller_path="execute")
            for key in ("access_token", "refresh_token", "expires_at"):
                setattr(credential, key, blob[key])
        config = self.config.config
        operation = config.operation
        spec = OPERATIONS[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = re.sub(r"\{(\w+)\}", lambda m: quote(_identifier(values[m[1]]), safe=""), spec.path)
        kwargs = {"headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
        if spec.body_kind:
            body = {"@odata.type": "#microsoft.graph.booking" + spec.body_kind.title()}
            body.update({_BODY_MAP[key]: value for key, value in values.items() if key in _BODY_MAP and "{" + key + "}" not in spec.path})
            if spec.body_kind == "appointment":
                # Published Bookings request/resource docs name these start/end.
                # The pinned metadata instead declares startDateTime/endDateTime.
                for key in ("start", "end"):
                    if key in values:
                        body[key] = {"@odata.type": "#microsoft.graph.dateTimeTimeZone", "dateTime": values[key], "timeZone": values["time_zone"]}
                if "customer_id" in values:
                    body["customers"] = [{"@odata.type": "#microsoft.graph.bookingCustomerInformation", "customerId": values["customer_id"],
                        **({"name": values["customer_name"]} if "customer_name" in values else {}),
                        **({"emailAddress": values["customer_email"]} if "customer_email" in values else {})}]
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(spec.method, GRAPH_ROOT + path, **kwargs)
        if not response.is_success:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.reason_phrase
            message = str(message)
            for secret in (token, credential.refresh_token):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"Microsoft Bookings API error ({response.status_code}): {message[:1000]}")
        result = {"status": "success", "operation": operation, "http_status": response.status_code}
        if response.content:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a Microsoft Bookings JSON object")
            if "error" in data:
                raise ValueError("Microsoft Bookings returned an error response")
            if operation.startswith("list_"):
                if not isinstance(data.get("value"), list) or any(not isinstance(row, dict) for row in data["value"]):
                    raise ValueError("Expected a Microsoft Bookings value collection")
                result.update(items=data["value"], count=len(data["value"]))
                if data.get("@odata.nextLink"):
                    result["next_link"] = data["@odata.nextLink"]
            else:
                result["data"] = data
        elif spec.method == "GET":
            raise ValueError("Microsoft Bookings returned no data")
        if spec.method != "GET":
            result["write_acknowledged"] = True
        return result
