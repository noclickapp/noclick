"""Office 365 mail, calendar and contacts through delegated Microsoft Graph v1.0.

Each operation performs one fixed Graph operation on the signed-in user's
mailbox. List results are one page, with Graph's continuation returned intact;
continuations are accepted only for that same collection on graph.microsoft.com.
No application permissions, arbitrary URLs, MIME or attachments are exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.office_365 import OFFICE_365_SCOPES

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


class Office365OAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Microsoft Office 365 OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "microsoft",
            "x-oauth-scopes": OFFICE_365_SCOPES.declared_scopes(),
            "x-credential-url": "https://learn.microsoft.com/en-us/graph/auth-v2-user",
            "x-credential-instructions": "Connect your Microsoft work, school or personal account. Your account needs an Exchange Online mailbox for mail, calendar and contact operations. Your organization may require administrator consent.",
        },
    )
    credential_type: Literal["microsoft_outlook_oauth"] = Field("microsoft_outlook_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token expiry", description="ISO 8601 expiry returned by Microsoft OAuth.")
    email: str | None = Field(None, title="Account email")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        return clean_secret(value, field_name="Token") if value is not None else None


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: str = ""
    status: int = 200
    docs: str = ""


OPERATIONS = {
    "get_profile": Operation("GET", "/me", docs="user-get"),
    "list_messages": Operation("GET", "/me/messages", ("top", "filter", "page_url"), docs="user-list-messages"),
    "get_message": Operation("GET", "/me/messages/{message_id}", ("message_id",), docs="message-get"),
    "send_mail": Operation("POST", "/me/sendMail", ("subject", "body_text", "to_recipients", "save_to_sent_items"), "send", 202, "user-sendmail"),
    "create_draft": Operation("POST", "/me/messages", ("subject", "body_text", "to_recipients"), "message", 201, "user-post-messages"),
    "update_message": Operation("PATCH", "/me/messages/{message_id}", ("message_id", "is_read"), "read", docs="message-update"),
    "delete_message": Operation("DELETE", "/me/messages/{message_id}", ("message_id",), status=204, docs="message-delete"),
    "reply_message": Operation("POST", "/me/messages/{message_id}/reply", ("message_id", "comment"), "reply", 202, "message-reply"),
    "move_message": Operation("POST", "/me/messages/{message_id}/move", ("message_id", "destination_id"), "move", 201, "message-move"),
    "list_mail_folders": Operation("GET", "/me/mailFolders", ("top", "page_url"), docs="user-list-mailfolders"),
    "list_calendars": Operation("GET", "/me/calendars", ("top", "page_url"), docs="user-list-calendars"),
    "list_events": Operation("GET", "/me/events", ("top", "filter", "page_url"), docs="user-list-events"),
    "get_event": Operation("GET", "/me/events/{event_id}", ("event_id",), docs="event-get"),
    "create_event": Operation("POST", "/me/events", ("subject", "body_text", "start", "end", "time_zone"), "event", 201, "user-post-events"),
    "update_event": Operation("PATCH", "/me/events/{event_id}", ("event_id", "subject"), "event_subject", docs="event-update"),
    "delete_event": Operation("DELETE", "/me/events/{event_id}", ("event_id",), status=204, docs="event-delete"),
    "list_contacts": Operation("GET", "/me/contacts", ("top", "filter", "page_url"), docs="user-list-contacts"),
    "get_contact": Operation("GET", "/me/contacts/{contact_id}", ("contact_id",), docs="contact-get"),
    "create_contact": Operation("POST", "/me/contacts", ("given_name", "surname", "email_address"), "contact", 201, "user-post-contacts"),
    "update_contact": Operation("PATCH", "/me/contacts/{contact_id}", ("contact_id", "given_name", "surname"), "contact", docs="contact-update"),
    "delete_contact": Operation("DELETE", "/me/contacts/{contact_id}", ("contact_id",), status=204, docs="contact-delete"),
}

Email = Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
FIELDS = {
    "top": (int, Field(25, ge=1, le=100, title="Page size")),
    "filter": (str | None, Field(None, max_length=4000, title="Filter", description="Graph OData $filter expression, for example isRead eq false.")),
    "page_url": (str | None, Field(None, max_length=16000, title="Next page URL", description="Paste next_page_url from this same list operation; overrides page size and filter.")),
    "message_id": (str, Field(..., min_length=1, max_length=2048, title="Message ID")),
    "event_id": (str, Field(..., min_length=1, max_length=2048, title="Event ID")),
    "contact_id": (str, Field(..., min_length=1, max_length=2048, title="Contact ID")),
    "destination_id": (str, Field(..., min_length=1, max_length=2048, title="Destination folder ID", description="A mail folder ID or well-known name such as archive or deleteditems.")),
    "subject": (str, Field(..., min_length=1, max_length=1000, title="Subject")),
    "body_text": (str, Field(..., max_length=100000, title="Body", description="Plain text content.", json_schema_extra={"ui:widget": "textarea"})),
    "to_recipients": (list[Email], Field(..., min_length=1, max_length=100, title="To email addresses")),
    "save_to_sent_items": (bool, Field(True, title="Save to Sent Items")),
    "is_read": (bool, Field(..., title="Mark as read")),
    "comment": (str, Field(..., min_length=1, max_length=100000, title="Reply text")),
    "start": (str, Field(..., title="Start", description="Local ISO date and time, e.g. 2026-11-10T09:00:00, in the specified time zone.")),
    "end": (str, Field(..., title="End", description="Local ISO date and time in the specified time zone.")),
    "time_zone": (str, Field("UTC", max_length=128, title="Time zone", description="Mailbox-supported zone, e.g. UTC or Pacific Standard Time.")),
    "given_name": (str, Field(..., min_length=1, max_length=256, title="Given name")),
    "surname": (str, Field(..., min_length=1, max_length=256, title="Surname")),
    "email_address": (Email, Field(..., title="Email address")),
}


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def times(self):
        if self.operation == "create_event":
            try:
                start, end = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
                if start.tzinfo or end.tzinfo or end <= start:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError("Use local ISO start/end times, with end after start, and specify the time zone separately") from None
        return self


def _model(name, spec):
    title = name.replace("_", " ").title()
    return create_model(
        "Office365" + title.replace(" ", "") + "Config", __base__=_Config,
        operation=(Literal[name], Field(name, title=title, json_schema_extra={
            "ui:hidden": True, "x-display-name": title, "x-is-trigger": False,
            "x-category": "Contacts" if "contact" in name else "Calendar" if "event" in name or "calendar" in name else "Account" if name == "get_profile" else "Mail",
        })),
        **{key: FIELDS[key] for key in spec.fields},
    )


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
Office365OperationConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class Office365NodeConfig(NodeConfig[Office365OperationConfig, Office365OAuthCredential]):
    pass


def _page_url(value: str, path: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.netloc != "graph.microsoft.com"
            or parts.path != "/v1.0" + path or parts.fragment or not parts.query):
        raise ValueError("Use the Graph next-page URL for this exact collection")
    return value


class Office365Node(WorkflowNode):
    integration_type = "automation-office-365"
    borrowed_credential_types = frozenset({"microsoft_outlook_oauth"})
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = OFFICE_365_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_profile", noun="Microsoft account")

    @classmethod
    def get_config_model(cls):
        return Office365NodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="microsoft",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, Office365NodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Microsoft Office 365 account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token

        credential = self.config.credentials
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=refresh_access_token, provider="microsoft", caller_path="execute",
        )
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in data:
                setattr(credential, key, data[key])
        config = self.config.config
        name = config.operation
        spec = OPERATIONS[name]
        values = config.model_dump(exclude={"operation"})
        path = spec.path
        for key in ("message_id", "event_id", "contact_id"):
            if "{" + key + "}" in path:
                identifier = values[key]
                if identifier in {".", ".."} or any(ord(c) < 32 for c in identifier):
                    raise ValueError("Use a Graph resource ID")
                path = path.replace("{" + key + "}", quote(identifier, safe=""))
        url = GRAPH_ROOT + path
        params = {}
        if "top" in values:
            params["$top"] = values["top"]
            if values.get("filter"):
                params["$filter"] = values["filter"]
            if values.get("page_url"):
                url, params = _page_url(values["page_url"], path), {}

        body = None
        if spec.body in {"send", "message"}:
            body = {"subject": values["subject"], "body": {"contentType": "text", "content": values["body_text"]},
                    "toRecipients": [{"emailAddress": {"address": email}} for email in values["to_recipients"]]}
            if spec.body == "send":
                body = {"message": body, "saveToSentItems": values["save_to_sent_items"]}
        elif spec.body == "read":
            body = {"isRead": values["is_read"]}
        elif spec.body == "reply":
            body = {"comment": values["comment"]}
        elif spec.body == "move":
            body = {"destinationId": values["destination_id"]}
        elif spec.body == "event":
            body = {"subject": values["subject"], "body": {"contentType": "text", "content": values["body_text"]},
                    "start": {"dateTime": values["start"], "timeZone": values["time_zone"]},
                    "end": {"dateTime": values["end"], "timeZone": values["time_zone"]}}
        elif spec.body == "event_subject":
            body = {"subject": values["subject"]}
        elif spec.body == "contact":
            body = {"givenName": values["given_name"], "surname": values["surname"]}
            if "email_address" in values:
                body["emailAddresses"] = [{"address": values["email_address"]}]
        kwargs = {"headers": {"Authorization": f"Bearer {token}", "Accept": "application/json"}}
        # httpx replaces an existing URL query even when params is empty.
        if params:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(spec.method, url, **kwargs)
        # Graph's metadata uses a 2XX response for move and 204 for mail
        # actions, while the method docs show 201 and 202 respectively.
        # Accept both published success forms without claiming delivery.
        success_codes = {spec.status}
        if name in {"send_mail", "reply_message"}:
            success_codes.add(204)
        elif name == "move_message":
            success_codes.add(200)
        if response.status_code not in success_codes:
            try:
                error = response.json().get("error", {})
                message = error.get("message", "Request rejected") if isinstance(error, dict) else "Request rejected"
            except (ValueError, AttributeError):
                message = "Unexpected Graph response"
            for secret in (token, credential.refresh_token):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"Microsoft Graph ({response.status_code}): {message[:1000]}")

        result = {"status": "success", "operation": name, "http_status": response.status_code}
        if spec.status == 202:
            result.update(accepted=True, delivery_verified=False)
        elif spec.status == 204:
            result["deleted"] = True
        else:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Graph returned an invalid resource")
            if name.startswith("list_"):
                if not isinstance(payload.get("value"), list):
                    raise ValueError("Graph returned an invalid collection")
                following = payload.get("@odata.nextLink")
                if following is not None:
                    _page_url(following, path)
                result.update(items=payload["value"], next_page_url=following, has_more=bool(following))
            else:
                # Microsoft documents shortened PATCH representations without
                # IDs. Keep those intact; GET/create responses identify a row.
                if not payload or (spec.method != "PATCH" and (not isinstance(payload.get("id"), str) or not payload["id"])):
                    raise ValueError("Graph returned a resource without an ID")
                result["data"] = payload
                if name == "get_profile":
                    result["account"] = payload.get("mail") or payload.get("userPrincipalName") or payload.get("displayName") or payload["id"]
        return result
