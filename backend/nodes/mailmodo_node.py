"""Automate Mailmodo contacts, email campaigns, events and journeys with a pasted API key.

Each operation makes one documented API call; asynchronous acknowledgements are
returned without claiming email delivery or journey completion.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MailmodoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mailmodo API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://manage.mailmodo.com/app/settings/apikey",
            "x-credential-instructions": "In Mailmodo, open Settings → API Keys → Show API Key, then paste the key. NoClick checks access by reading your contact lists."})
    credential_type: Literal["mailmodo_api_key"] = Field("mailmodo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Contact(_Input):
    email: str = Field(..., min_length=3, description="Contact email address.", json_schema_extra={"format": "email"})


class ListContactLists(_Input):
    """Read the account's contact lists and their IDs."""
    operation: Literal["list_contact_lists"] = Field("list_contact_lists", json_schema_extra={"ui:hidden": True})


class GetContact(_Contact):
    """Read a contact's properties and subscription status."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class AddContactToList(_Contact):
    """Add or update a contact and add it to a named list."""
    operation: Literal["add_contact_to_list"] = Field("add_contact_to_list", json_schema_extra={"ui:hidden": True})
    listName: str = Field(..., min_length=1, title="List name")
    data: dict[str, Any] | None = Field(None, description="Contact properties, including custom properties.")
    created_at: str | int | None = None
    last_click: str | int | None = None
    last_open: str | int | None = None
    timezone: str | None = None


class BatchContact(_Contact):
    data: dict[str, Any] | None = None


class BulkAddContacts(_Input):
    """Add a batch of contacts; partial failures remain visible in the response."""
    operation: Literal["bulk_add_contacts"] = Field("bulk_add_contacts", json_schema_extra={"ui:hidden": True})
    listName: str = Field(..., min_length=1, title="List name")
    values: list[BatchContact] = Field(..., min_length=1, description="Contacts with email and optional data properties.")


class UnsubscribeContact(_Contact):
    """Suppress a contact from further email communication."""
    operation: Literal["unsubscribe_contact"] = Field("unsubscribe_contact", json_schema_extra={"ui:hidden": True})


class ResubscribeContact(_Contact):
    """Resubscribe a contact with appropriate consent."""
    operation: Literal["resubscribe_contact"] = Field("resubscribe_contact", json_schema_extra={"ui:hidden": True})


class UpdateSubscription(_Contact):
    """Change subscriptions for specific Mailmodo email types."""
    operation: Literal["update_subscription"] = Field("update_subscription", json_schema_extra={"ui:hidden": True})
    reSubscribeTo: list[str] = Field(default_factory=list, title="Resubscribe to email types")
    unsubscribeFrom: list[str] = Field(default_factory=list, title="Unsubscribe from email types")


class RemoveContactFromList(_Contact):
    """Remove a contact from a named list."""
    operation: Literal["remove_contact_from_list"] = Field("remove_contact_from_list", json_schema_extra={"ui:hidden": True})
    listName: str = Field(..., min_length=1, title="List name")


class ArchiveContact(_Contact):
    """Archive an existing contact."""
    operation: Literal["archive_contact"] = Field("archive_contact", json_schema_extra={"ui:hidden": True})


class _Campaign(_Input):
    campaign_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Campaign ID from Mailmodo's API trigger URL.")


class SendCampaignEmail(_Campaign):
    """Schedule a campaign email for one contact."""
    operation: Literal["send_campaign_email"] = Field("send_campaign_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, json_schema_extra={"format": "email"})
    subject: str | None = None
    replyTo: str | None = None
    fromName: str | None = None
    campaign_data: dict[str, Any] | None = Field(None, description="Transient personalization variables.")
    data: dict[str, Any] | None = Field(None, description="Personalization saved to the contact profile.")
    addToList: str | None = None


class BroadcastCampaign(_Campaign):
    """Schedule a campaign for a list or segment."""
    operation: Literal["broadcast_campaign"] = Field("broadcast_campaign", json_schema_extra={"ui:hidden": True})
    listId: str = Field(..., min_length=1, title="List or segment ID")
    subject: str | None = None
    idempotencyKey: str | None = Field(None, description="Unique value to permit repeating a campaign to the same list within 24 hours; do not generate a new value when retrying.")
    campaign_data: dict[str, Any] | None = None


class _Journey(_Contact):
    journey_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Journey ID from Mailmodo's trigger URL.", json_schema_extra={"format": "uuid"})


class StartJourney(_Journey):
    """Start a journey for a contact."""
    operation: Literal["start_journey"] = Field("start_journey", json_schema_extra={"ui:hidden": True})
    data: dict[str, Any] | None = None
    allowDuplicateEmail: bool = False


class AbortJourney(_Journey):
    """Abort a contact's journey, optionally selecting an instance."""
    operation: Literal["abort_journey"] = Field("abort_journey", json_schema_extra={"ui:hidden": True})
    reason: str | None = Field(None, min_length=1)
    instanceId: str | None = Field(None, json_schema_extra={"format": "uuid"})


class AddEvent(_Contact):
    """Record a custom event for a contact."""
    operation: Literal["add_event"] = Field("add_event", json_schema_extra={"ui:hidden": True})
    event_name: str = Field(..., min_length=1)
    ts: float | None = Field(None, description="UNIX timestamp in seconds; omit for provider current time.")
    event_properties: dict[str, Any] | None = None


class ListTemplates(_Input):
    """Read the account's templates and personalization parameters."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


MailmodoOperation = Annotated[Union[ListContactLists, GetContact, AddContactToList, BulkAddContacts,
    UnsubscribeContact, ResubscribeContact, UpdateSubscription, RemoveContactFromList, ArchiveContact,
    SendCampaignEmail, BroadcastCampaign, StartJourney, AbortJourney, AddEvent, ListTemplates], Field(discriminator="operation")]


class MailmodoFullConfig(NodeConfig[MailmodoOperation, MailmodoAPIKeyCredential]):
    pass


# These routes are fixed to the provider's published API host. IDs never select a host.
ROUTES = {
    "list_contact_lists": ("GET", "/api/v1/getAllContactLists"),
    "get_contact": ("GET", "/api/v1/getContactDetails"),
    "add_contact_to_list": ("POST", "/api/v1/addToList"),
    "bulk_add_contacts": ("POST", "/api/v1/addToList/batch"),
    "unsubscribe_contact": ("POST", "/api/v1/contacts/unsubscribe"),
    "resubscribe_contact": ("POST", "/api/v1/contacts/resubscribe"),
    "update_subscription": ("POST", "/api/v1/contacts/updateSubscription"),
    "remove_contact_from_list": ("POST", "/api/v1/removeFromList"),
    "archive_contact": ("DELETE", "/api/v1/contacts"),
    "send_campaign_email": ("POST", "/api/v1/triggerCampaign/{campaign_id}"),
    "broadcast_campaign": ("POST", "/api/v1/bulktriggerCampaign/{campaign_id}"),
    "start_journey": ("POST", "/hooks/start/{journey_id}"),
    "abort_journey": ("POST", "/hooks/abort/{journey_id}"),
    "add_event": ("POST", "/api/v1/addEvent"),
    "list_templates": ("GET", "/api/v1/getAllTemplates"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class MailmodoNode(WorkflowNode):
    integration_type = "automation-mailmodo"
    connection_evidence = ConnectionEvidence(noun="contact lists", operation="list_contact_lists")

    @classmethod
    def get_config_model(cls):
        return MailmodoFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Mailmodo API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        for field in ("campaign_id", "journey_id"):
            if hasattr(config, field):
                path = path.replace("{" + field + "}", quote(getattr(config, field), safe=""))
        body = config.model_dump(exclude={"operation", "campaign_id", "journey_id"}, exclude_none=True)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.mailmodo.com" + path,
                headers={"mmApiKey": key, "Content-Type": "application/json", "Accept": "application/json"},
                params=body if method == "GET" else None, json=body if method != "GET" else None)
        # Strip a reflected key while preserving the provider's own error text for connect evidence.
        if response.status_code < 200 or response.status_code >= 300:
            try:
                error = response.json()
                message = error.get("message") or error.get("error") if isinstance(error, dict) else None
            except ValueError:
                message = None
            return {"status": "error", "http_status": response.status_code, "status_code": response.status_code,
                "error": str(message or "Mailmodo rejected the request").replace(key, "[redacted]")}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Mailmodo returned a non-JSON response; inspect before retrying writes") from None
        payload = _redact(payload, key)
        if not isinstance(payload, dict):
            raise ValueError("Mailmodo returned an unexpected response")
        if payload.get("success") is False:
            return {"status": "error", "error": str(payload.get("message", "Mailmodo declined the request")).replace(key, "[redacted]"), "data": payload}
        if config.operation in {"list_contact_lists", "list_templates"}:
            field = "listDetails" if config.operation == "list_contact_lists" else "templateDetails"
            rows = payload.get(field)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Mailmodo returned an unexpected list response")
            return {"status": "success", "data": rows}
        return {"status": "partial" if response.status_code == 207 else "success", "http_status": response.status_code, "data": payload}
