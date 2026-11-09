"""TeamUp v2 business automation using a manually supplied M2M token.

Contract: https://goteamup.com/api/v2/schema/?format=json
Authentication: https://docs.goteamup.com/api-reference/authentication
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://goteamup.com/api/v2"


class TeamUpM2MTokenCredential(BaseModel):
    model_config = ConfigDict(title="TeamUp M2M Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.goteamup.com/en/articles/14819895-creating-a-machine-to-machine-m2m-token",
            "x-credential-instructions": "In TeamUp Business Dashboard, open Settings → Integrations → API Integration → Options → View and Update Applications. Create an M2M token with the permissions your operations need and paste it here. Read-only tokens support reads only. Replace expired or revoked tokens here. This connection acts in provider mode; it does not sign in as a customer.",
        })
    credential_type: Literal["teamup_m2m_token"] = Field("teamup_m2m_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="M2M token", min_length=1, max_length=4096, repr=False,
        description="Paste the M2M token only, without an Authorization prefix or your application client secret.",
        json_schema_extra={"ui:widget": "password"})
    provider_id: int | None = Field(None, title="Provider ID", gt=0,
        description="Business ID from your TeamUp customer site URL. Set this when the token can access multiple providers.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="M2M token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste a token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, strict=True, description="Page to read. Use next_page from the previous result; each run fetches one page.")
    page_size: int = Field(50, ge=1, le=100, strict=True)


class _Customer(_Input):
    customer: int = Field(..., gt=0, strict=True, title="Customer ID")


class _Event(_Input):
    event_id: int = Field(..., gt=0, strict=True, title="Event ID")


class _EventCustomer(_Event, _Customer):
    pass


class TeamUpListProvidersConfig(_Page):
    """Read one page of providers."""
    operation: Literal["list_providers"] = Field("list_providers", json_schema_extra={"ui:hidden": True})


class TeamUpGetProviderConfig(_Input):
    """Read one provider."""
    operation: Literal["get_provider"] = Field("get_provider", json_schema_extra={"ui:hidden": True})
    provider_id: int = Field(..., gt=0, strict=True, title="Provider ID")


class TeamUpListCustomersConfig(_Page):
    """Read one page of customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=500, description="Search customers by name or email.")


class TeamUpGetCustomerConfig(_Input):
    """Read one customer."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., gt=0, strict=True, title="Customer ID")


class TeamUpListEventsConfig(_Page):
    """Read one page of events."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    starts_at_gte: datetime | None = None
    starts_at_lte: datetime | None = None


class TeamUpGetEventConfig(_Input):
    """Read one event."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., gt=0, strict=True, title="Event ID")


class TeamUpListAttendancesConfig(_Page):
    """Read one page of attendances."""
    operation: Literal["list_attendances"] = Field("list_attendances", json_schema_extra={"ui:hidden": True})
    customer: int | None = Field(None, gt=0, strict=True, title="Customer ID")


class TeamUpGetAttendanceConfig(_Input):
    """Read one attendance."""
    operation: Literal["get_attendance"] = Field("get_attendance", json_schema_extra={"ui:hidden": True})
    attendance_id: int = Field(..., gt=0, strict=True, title="Attendance ID")


class TeamUpListMembershipsConfig(_Page):
    """Read one page of memberships."""
    operation: Literal["list_memberships"] = Field("list_memberships", json_schema_extra={"ui:hidden": True})
    name_contains: str | None = Field(None, max_length=500)


class TeamUpGetMembershipConfig(_Input):
    """Read one membership."""
    operation: Literal["get_membership"] = Field("get_membership", json_schema_extra={"ui:hidden": True})
    membership_id: int = Field(..., gt=0, strict=True, title="Membership ID")


class TeamUpListCustomerMembershipsConfig(_Page):
    """Read one page of customer memberships."""
    operation: Literal["list_customer_memberships"] = Field("list_customer_memberships", json_schema_extra={"ui:hidden": True})
    customer: int | None = Field(None, gt=0, strict=True, title="Customer ID")


class TeamUpGetCustomerMembershipConfig(_Input):
    """Read one customer membership."""
    operation: Literal["get_customer_membership"] = Field("get_customer_membership", json_schema_extra={"ui:hidden": True})
    customer_membership_id: int = Field(..., gt=0, strict=True, title="Customer Membership ID")


class TeamUpListVenuesConfig(_Page):
    """Read one page of venues."""
    operation: Literal["list_venues"] = Field("list_venues", json_schema_extra={"ui:hidden": True})


class TeamUpGetVenueConfig(_Input):
    """Read one venue."""
    operation: Literal["get_venue"] = Field("get_venue", json_schema_extra={"ui:hidden": True})
    venue_id: int = Field(..., gt=0, strict=True, title="Venue ID")


class TeamUpCreateCustomerConfig(_Input):
    """Create a customer; an invitation is sent only when explicitly enabled."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=150)
    last_name: str = Field(..., min_length=1, max_length=150)
    email: str | None = Field(None, min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    send_invitation_email: bool = Field(False, strict=True, description="When enabled, TeamUp emails the customer an invitation.")


class TeamUpRegisterCustomerConfig(_EventCustomer):
    """Register a customer for a class, consuming membership usage unless comped."""
    operation: Literal["register_customer"] = Field("register_customer", json_schema_extra={"ui:hidden": True})
    customer_membership: int | None = Field(None, gt=0, strict=True)
    comped: bool = Field(False, strict=True, description="Register without charging a membership use.")


class TeamUpUnregisterCustomerConfig(_EventCustomer):
    """Remove a registration; late cancellation can incur provider-configured penalties."""
    operation: Literal["unregister_customer"] = Field("unregister_customer", json_schema_extra={"ui:hidden": True})
    is_late_cancel: bool | None = None


class TeamUpConfirmAttendanceConfig(_EventCustomer):
    """Mark a customer as attended."""
    operation: Literal["confirm_attendance"] = Field("confirm_attendance", json_schema_extra={"ui:hidden": True})


class TeamUpMarkNoShowConfig(_EventCustomer):
    """Mark a registered customer as a no-show; provider-configured penalties may apply."""
    operation: Literal["mark_no_show"] = Field("mark_no_show", json_schema_extra={"ui:hidden": True})


class TeamUpCreateCustomerMembershipConfig(_Customer):
    """Assign a membership to a customer; TeamUp applies its configured billing rules."""
    operation: Literal["create_customer_membership"] = Field("create_customer_membership", json_schema_extra={"ui:hidden": True})
    membership: int = Field(..., gt=0, strict=True, title="Membership ID")
    start_date: date | None = None
    payment_plan: int | None = Field(None, gt=0, strict=True)


class TeamUpCancelCustomerMembershipConfig(_Input):
    """Cancel a customer membership; provider cancellation and billing rules apply."""
    operation: Literal["cancel_customer_membership"] = Field("cancel_customer_membership", json_schema_extra={"ui:hidden": True})
    customer_membership_id: int = Field(..., gt=0, strict=True)
    forced_expiration_date: date | None = Field(None, description="Optional final expiration date. Omit to use TeamUp cancellation rules.")


TeamUpOperation = Annotated[Union[
    TeamUpListProvidersConfig,
    TeamUpGetProviderConfig,
    TeamUpListCustomersConfig,
    TeamUpGetCustomerConfig,
    TeamUpListEventsConfig,
    TeamUpGetEventConfig,
    TeamUpListAttendancesConfig,
    TeamUpGetAttendanceConfig,
    TeamUpListMembershipsConfig,
    TeamUpGetMembershipConfig,
    TeamUpListCustomerMembershipsConfig,
    TeamUpGetCustomerMembershipConfig,
    TeamUpListVenuesConfig,
    TeamUpGetVenueConfig,
    TeamUpCreateCustomerConfig,
    TeamUpRegisterCustomerConfig,
    TeamUpUnregisterCustomerConfig,
    TeamUpConfirmAttendanceConfig,
    TeamUpMarkNoShowConfig,
    TeamUpCreateCustomerMembershipConfig,
    TeamUpCancelCustomerMembershipConfig
], Field(discriminator="operation")]


class TeamUpFullConfig(NodeConfig[TeamUpOperation, TeamUpM2MTokenCredential]):
    pass


ROUTES = {'list_providers': ('GET', '/providers', None, []),
 'get_provider': ('GET', '/providers/{provider_id}', None, []),
 'list_customers': ('GET', '/customers', None, []),
 'get_customer': ('GET', '/customers/{customer_id}', None, []),
 'list_events': ('GET', '/events', None, []),
 'get_event': ('GET', '/events/{event_id}', None, []),
 'list_attendances': ('GET', '/attendances', None, []),
 'get_attendance': ('GET', '/attendances/{attendance_id}', None, []),
 'list_memberships': ('GET', '/memberships', None, []),
 'get_membership': ('GET', '/memberships/{membership_id}', None, []),
 'list_customer_memberships': ('GET', '/customer_memberships', None, []),
 'get_customer_membership': ('GET', '/customer_memberships/{customer_membership_id}', None, []),
 'list_venues': ('GET', '/venues', None, []),
 'get_venue': ('GET', '/venues/{venue_id}', None, []),
 'create_customer': ('POST',
                     '/customers',
                     201,
                     ['first_name', 'last_name', 'email', 'send_invitation_email']),
 'register_customer': ('POST',
                       '/events/{event_id}/register',
                       200,
                       ['customer', 'customer_membership', 'comped']),
 'unregister_customer': ('POST', '/events/{event_id}/unregister', 200, ['customer', 'is_late_cancel']),
 'confirm_attendance': ('POST', '/events/{event_id}/confirm_attendance', 200, ['customer']),
 'mark_no_show': ('POST', '/events/{event_id}/mark_no_show', 200, ['customer']),
 'create_customer_membership': ('POST',
                                '/customer_memberships',
                                201,
                                ['customer', 'membership', 'start_date', 'payment_plan']),
 'cancel_customer_membership': ('POST',
                                '/customer_memberships/{customer_membership_id}/cancel',
                                200,
                                ['forced_expiration_date'])}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key.replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class TeamUpNode(WorkflowNode):
    integration_type = "automation-teamup"
    connection_evidence = ConnectionEvidence(operation="list_customers", noun="TeamUp customers")

    @classmethod
    def get_config_model(cls):
        return TeamUpFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a TeamUp M2M token")
        credential = self.config.credentials
        config = self.config.config
        method, template, expected_status, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = template.format(**values)
        headers = {"Authorization": "Bearer " + credential.api_token,
            "Accept": "application/json", "TeamUp-Request-Mode": "provider"}
        if credential.provider_id is not None:
            headers["TeamUp-Provider-ID"] = str(credential.provider_id)
        params = {}
        if config.operation.startswith("list_"):
            params = {k: v for k, v in values.items() if k != "operation"}
        body = {key: values[key] for key in body_fields if key in values}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers,
                    params=params, **({"json": body} if method != "GET" else {}))
        except httpx.RequestError:
            raise ValueError("TeamUp request failed; a write may have completed. Check TeamUp before retrying.") from None
        if response.status_code != (expected_status or 200):
            try:
                detail = _redact(response.json(), credential.api_token)
            except ValueError:
                detail = "TeamUp returned an unexpected response"
            output = {"status": "error", "http_status": response.status_code, "error": detail}
        else:
            payload = response.json()
            if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                raise ValueError("TeamUp returned an invalid response")
            if config.operation.startswith("list_"):
                if not isinstance(payload.get("results"), list) or type(payload.get("count")) is not int:
                    raise ValueError("TeamUp returned an invalid page")
                output = {"status": "success", "items": payload["results"], "count": payload["count"],
                    "next_page": config.page + 1 if payload.get("next") else None}
            else:
                output = {"status": "success", "item": payload}
            output = _redact(output, credential.api_token)
        await self.emit(output)
        return output
