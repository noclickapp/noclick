"""Perfect Venue v1 venue, contact, event and team-member automation.

Contract: https://docs.perfectvenue.com/ (v1.5.0).
Each operation makes one documented API call; writes are never retried.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.perfect_venue import PERFECT_VENUE_SCOPES
from nodes.oauth.perfect_venue_oauth import refresh_access_token
from nodes.core.oauth_refresh import freshen_oauth_credential, ensure_fresh_oauth_token
from utils.ssrf import guarded_async_client

BASE = "https://api.perfectvenue.com/api/v1"
VERSION = "2026-11-01"


def _identifier(value):
    if not isinstance(value, str):
        raise ValueError("Enter a Perfect Venue ID, without a URL or path")
    value = value.strip()
    if not value or len(value) > 256 or any(c in value for c in "/?#\\") or any(ord(c) < 32 for c in value) or value in {".", ".."}:
        raise ValueError("Enter a Perfect Venue ID, without a URL or path")
    return value.strip()


def _timestamp(value):
    if value is None:
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Include a timezone in the ISO 8601 timestamp")
    return value


Identifier = Annotated[str, BeforeValidator(_identifier)]
Timestamp = Annotated[str, BeforeValidator(_timestamp)]


class PerfectVenueOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Perfect Venue OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "perfect-venue",
        "x-oauth-scopes": sorted(PERFECT_VENUE_SCOPES.declared_scopes()),
        "x-credential-url": "https://docs.perfectvenue.com/#section/Authentication",
        "x-credential-instructions": "Connect your Perfect Venue account. Perfect Venue must first provision the OAuth application for the NoClick instance; partner developers request setup from eng@perfectvenue.com.",
    })
    credential_type: Literal["perfect_venue_oauth"] = Field("perfect_venue_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None
    scope: str | None = None
    token_type: str = "Bearer"
    name: str | None = None


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListVenues(Input):
    """List venues accessible to the authorizing user."""
    operation: Literal["list_venues"] = "list_venues"


class GetVenue(Input):
    """Read venue settings, spaces and custom fields."""
    operation: Literal["get_venue"] = "get_venue"
    venue_id: Identifier


class ListUsers(Input):
    """List team members in the authorizing user's organization."""
    operation: Literal["list_users"] = "list_users"


class GetUser(Input):
    """Read a team member by ID."""
    operation: Literal["get_user"] = "get_user"
    user_id: Identifier


class ListContacts(Input):
    """Sync one page of contacts; follow meta.next_cursor until null."""
    operation: Literal["list_contacts"] = "list_contacts"
    updated_after: Timestamp | None = None
    created_after: Timestamp | None = None
    limit: int = Field(100, ge=1, le=100)
    cursor: str | None = None


class GetContact(Input):
    """Read one contact."""
    operation: Literal["get_contact"] = "get_contact"
    contact_id: Identifier


class ContactFields(Input):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None


class CreateContact(ContactFields):
    """Create a contact for a venue; the provider does not deduplicate contacts."""
    operation: Literal["create_contact"] = "create_contact"
    venue_id: Identifier


class UpdateContact(ContactFields):
    """Update a contact's name, email or phone."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: Identifier


class ListEvents(Input):
    """Read one event page; use meta.total_pages to continue with page + 1."""
    operation: Literal["list_events"] = "list_events"
    venue_id: Identifier
    status: list[Literal["lead", "qualified", "proposal_sent", "confirmed", "balance_due", "completed", "lost"]] | None = None
    event_type: list[str] | None = None
    source: list[str] | None = None
    spaces: list[str] | None = None
    contact_id: Identifier | None = None
    order: Literal["created_at", "updated_at", "start_time", "name"] = "created_at"
    sort_direction: Literal["asc", "desc"] = "desc"
    date_from: Timestamp | None = None
    date_to: Timestamp | None = None
    date_field: Literal["created_at", "updated_at", "start_time"] = "created_at"
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=100)

    @model_validator(mode="after")
    def paired_dates(self):
        if bool(self.date_from) != bool(self.date_to):
            raise ValueError("Provide both date_from and date_to")
        return self


class GetEvent(Input):
    """Read one event."""
    operation: Literal["get_event"] = "get_event"
    event_id: Identifier


class EventFields(Input):
    contact_id: Identifier | None = None
    name: str | None = None
    start_time: Timestamp | None = None
    end_time: Timestamp | None = None
    group_size: int | None = None
    source: str | None = None
    campaign: str | None = None
    amount: int | None = Field(None, description="Estimated event value in integer cents.")
    event_type: str | None = Field(None, description="An event type configured for this venue.")
    spaces: list[str] | None = Field(None, description="Space slugs from the venue settings.")
    custom: dict[str, str] | None = None


class CreateEvent(EventFields):
    """Create an event using an existing contact or inline contact details."""
    operation: Literal["create_event"] = "create_event"
    venue_id: Identifier
    name: str = Field(..., min_length=1)
    contact: ContactFields | None = Field(None, description="Create or reuse a contact by email; omit when contact_id is set.")
    message_text: str | None = None

    @model_validator(mode="after")
    def contact_choice(self):
        if bool(self.contact_id) == (self.contact is not None):
            raise ValueError("Provide exactly one of contact_id or inline contact")
        return self


class UpdateEvent(EventFields):
    """Update event details and timing."""
    operation: Literal["update_event"] = "update_event"
    event_id: Identifier


Operations = Annotated[Union[ListVenues, GetVenue, ListUsers, GetUser, ListContacts,
    GetContact, CreateContact, UpdateContact, ListEvents, GetEvent, CreateEvent,
    UpdateEvent], Field(discriminator="operation")]


class PerfectVenueNodeConfig(NodeConfig[Operations, PerfectVenueOAuthCredential]):
    pass


ROUTES = {
    "list_venues": ("GET", "/venues"), "get_venue": ("GET", "/venues/{venue_id}"),
    "list_users": ("GET", "/users"), "get_user": ("GET", "/users/{user_id}"),
    "list_contacts": ("GET", "/contacts"), "get_contact": ("GET", "/contacts/{contact_id}"),
    "create_contact": ("POST", "/contacts"), "update_contact": ("PUT", "/contacts/{contact_id}"),
    "list_events": ("GET", "/events"), "get_event": ("GET", "/events/{event_id}"),
    "create_event": ("POST", "/events"), "update_event": ("PATCH", "/events/{event_id}"),
}


class PerfectVenueNode(WorkflowNode):
    integration_type = "automation-perfect-venue"
    scope_registry = PERFECT_VENUE_SCOPES
    credential_provider_labels = {"perfect-venue": "Perfect Venue"}
    connection_evidence = ConnectionEvidence(noun="venues", operation="list_venues")

    @classmethod
    def get_config_model(cls):
        return PerfectVenueNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="perfect-venue")

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Perfect Venue account")
        credential = self.config.credentials.model_dump()
        token = await ensure_fresh_oauth_token(credential=credential,
            credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            refresh=refresh_access_token, provider="perfect-venue", caller_path="execute")
        self.config.credentials = PerfectVenueOAuthCredential.model_validate(credential)
        config = self.config.config
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        method, path = ROUTES[config.operation]
        for key in ("venue_id", "contact_id", "event_id", "user_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        body, params = None, None
        if method == "GET":
            params = values
        elif config.operation.endswith("contact"):
            body = {"contact": values}
        else:
            contact = values.pop("contact", None)
            message = values.pop("message_text", None)
            body = {"event": values}
            if contact is not None:
                body["contact"] = contact
            if message is not None:
                body["message"] = {"text": message}
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "PV-Version": VERSION})
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Perfect Venue returned HTTP {response.status_code} without a JSON response") from None
        if not response.is_success:
            detail = payload.get("detail") or payload.get("title") or "Request rejected"
            for secret in (token, credential.get("refresh_token")):
                if secret:
                    detail = str(detail).replace(secret, "[redacted]")
            raise ValueError(f"Perfect Venue HTTP {response.status_code}: {detail}")
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError("Perfect Venue response is missing data")
        return payload
