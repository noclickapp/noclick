"""Exchange Online mail, calendars and contacts through delegated Microsoft Graph v1.0.

Fixed /me routes never accept an arbitrary URL. Each action makes one provider
request; accepted mail actions report acceptance, not delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit, parse_qsl

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft_exchange import EXCHANGE_SCOPES

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


class ExchangeOAuthCredential(BaseModel):
    """Uses the existing Microsoft mail sign-in and its stored credential type."""
    credential_type: Literal["microsoft_outlook_oauth"] = Field("microsoft_outlook_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field("", title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field("", title="Token Expiry", description="ISO 8601 expiry returned by Microsoft.")
    email: str = Field("", title="Microsoft Account", description="Email address returned by Microsoft sign-in.")
    model_config = ConfigDict(title="Microsoft Exchange OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "microsoft",
        "x-oauth-scopes": EXCHANGE_SCOPES.declared_scopes(),
        "x-credential-url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "x-credential-instructions": "Sign in with the Microsoft account that owns your Exchange Online mailbox. Mail, calendar and contact permissions are requested. Exchange Server on-premises is not supported by these Microsoft Graph endpoints.",
    })


@dataclass(frozen=True)
class Operation:
    title: str
    category: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: str = ""


OPERATIONS = {
    "list_messages": Operation("List Messages", "Mail", "GET", "/me/messages", ("top", "skip", "filter")),
    "get_message": Operation("Get Message", "Mail", "GET", "/me/messages/{message_id}", ("message_id",)),
    "send_email": Operation("Send Email", "Mail", "POST", "/me/sendMail", ("subject", "body_text", "to_email"), "send"),
    "create_draft": Operation("Create Draft", "Mail", "POST", "/me/messages", ("subject", "body_text", "to_email"), "message"),
    "update_message": Operation("Mark Message Read or Unread", "Mail", "PATCH", "/me/messages/{message_id}", ("message_id", "is_read"), "read"),
    "delete_message": Operation("Delete Message", "Mail", "DELETE", "/me/messages/{message_id}", ("message_id",)),
    "move_message": Operation("Move Message", "Mail", "POST", "/me/messages/{message_id}/move", ("message_id", "destination_id"), "move"),
    "reply_message": Operation("Reply to Message", "Mail", "POST", "/me/messages/{message_id}/reply", ("message_id", "comment"), "reply"),
    "forward_message": Operation("Forward Message", "Mail", "POST", "/me/messages/{message_id}/forward", ("message_id", "comment", "to_email"), "forward"),
    "send_draft": Operation("Send Draft", "Mail", "POST", "/me/messages/{message_id}/send", ("message_id",)),
    "list_mail_folders": Operation("List Mail Folders", "Folder", "GET", "/me/mailFolders", ("top", "skip")),
    "get_mail_folder": Operation("Get Mail Folder", "Folder", "GET", "/me/mailFolders/{folder_id}", ("folder_id",)),
    "create_mail_folder": Operation("Create Mail Folder", "Folder", "POST", "/me/mailFolders", ("display_name",), "name"),
    "list_calendars": Operation("List Calendars", "Calendar", "GET", "/me/calendars", ("top", "skip")),
    "list_events": Operation("List Events", "Event", "GET", "/me/events", ("top", "skip", "filter")),
    "get_event": Operation("Get Event", "Event", "GET", "/me/events/{event_id}", ("event_id",)),
    "create_event": Operation("Create Event", "Event", "POST", "/me/events", ("subject", "body_text", "start_datetime", "end_datetime", "time_zone"), "event"),
    "update_event": Operation("Update Event Subject", "Event", "PATCH", "/me/events/{event_id}", ("event_id", "subject"), "subject"),
    "delete_event": Operation("Delete Event", "Event", "DELETE", "/me/events/{event_id}", ("event_id",)),
    "list_contacts": Operation("List Contacts", "Contact", "GET", "/me/contacts", ("top", "skip", "filter")),
    "get_contact": Operation("Get Contact", "Contact", "GET", "/me/contacts/{contact_id}", ("contact_id",)),
    "create_contact": Operation("Create Contact", "Contact", "POST", "/me/contacts", ("given_name", "surname", "email_address"), "contact"),
    "update_contact": Operation("Update Contact Name", "Contact", "PATCH", "/me/contacts/{contact_id}", ("contact_id", "display_name"), "name"),
    "delete_contact": Operation("Delete Contact", "Contact", "DELETE", "/me/contacts/{contact_id}", ("contact_id",)),
    "list_contact_folders": Operation("List Contact Folders", "Contact", "GET", "/me/contactFolders", ("top", "skip")),
}


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_value(cls, value, info):
        key = info.field_name
        if isinstance(value, str):
            if key.endswith("_id") and (not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#%") or any(ord(c) < 33 for c in value)):
                raise ValueError("Use a single Microsoft Graph resource ID")
            if key in {"to_email", "email_address"} and (value.count("@") != 1 or any(c.isspace() for c in value) or any(c in value for c in "<>,;")):
                raise ValueError("Use one email address")
            if key in {"start_datetime", "end_datetime"}:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def time_order(self):
        if hasattr(self, "start_datetime"):
            start = datetime.fromisoformat(self.start_datetime.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.end_datetime.replace("Z", "+00:00"))
            if start.tzinfo != end.tzinfo or end <= start:
                raise ValueError("End must follow start using matching timezone formats")
        return self


def _model(name, spec):
    fields = {"operation": (Literal[name], Field(name, title=spec.title, json_schema_extra={"const": name, "ui:hidden": True, "x-category": spec.category, "x-display-name": spec.title, "x-is-trigger": False}))}
    for key in spec.fields:
        title = key.replace("_", " ").title()
        if key == "top": fields[key] = (int, Field(25, ge=1, le=100, title="Page Size"))
        elif key == "skip": fields[key] = (int, Field(0, ge=0, le=1000000, title="Offset", description="Number of items to skip. Follow the returned next_link for the provider's exact continuation."))
        elif key == "filter": fields[key] = (str | None, Field(None, max_length=2048, title="OData Filter", description="Optional documented OData $filter expression."))
        elif key == "time_zone": fields[key] = (str, Field("UTC", max_length=100, title="Time Zone", description="Microsoft Graph supported time zone, for example UTC or Pacific Standard Time."))
        elif key in {"to_email", "email_address"}: fields[key] = (str, Field(..., min_length=1, max_length=320, title=title, json_schema_extra={"format": "email"}))
        elif key == "is_read": fields[key] = (bool, Field(..., title="Is Read"))
        else: fields[key] = (str, Field(..., min_length=1, max_length=100000 if key in {"body_text", "comment"} else 1024, title=title))
    return create_model("Exchange" + "".join(x.title() for x in name.split("_")) + "Config", __base__=_Input, **fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
ExchangeOperationConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class ExchangeNodeConfig(NodeConfig[ExchangeOperationConfig, ExchangeOAuthCredential]):
    pass


class MicrosoftExchangeNode(WorkflowNode):
    integration_type = "automation-microsoft-exchange"
    scope_registry = EXCHANGE_SCOPES
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    connection_evidence = ConnectionEvidence(operation="list_messages", noun="messages", label_keys=("subject", "id"))
    edit_examples = ["Read my Exchange mailbox messages", "Send an email from Exchange Online", "Create a calendar event", "Add a mailbox contact"]

    @classmethod
    def get_config_model(cls):
        return ExchangeNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        if not isinstance(self.config, ExchangeNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Microsoft account with an Exchange Online mailbox")
        credential = self.config.credentials
        updated = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id, credential=updated, refresh=refresh_access_token, provider="microsoft", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in updated: setattr(credential, key, updated[key])
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"})
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {"$" + k: values[k] for k in ("top", "skip", "filter") if values.get(k) is not None}
        body = None
        def recipient(address): return {"emailAddress": {"address": address}}
        if spec.body in {"send", "message"}:
            message = {"subject": config.subject, "body": {"contentType": "text", "content": config.body_text}, "toRecipients": [recipient(config.to_email)]}
            body = {"message": message} if spec.body == "send" else message
        elif spec.body == "read": body = {"isRead": config.is_read}
        elif spec.body == "move": body = {"destinationId": config.destination_id}
        elif spec.body == "reply": body = {"comment": config.comment}
        elif spec.body == "forward": body = {"comment": config.comment, "toRecipients": [recipient(config.to_email)]}
        elif spec.body == "name": body = {"displayName": config.display_name}
        elif spec.body == "subject": body = {"subject": config.subject}
        elif spec.body == "event":
            body = {"subject": config.subject, "body": {"contentType": "text", "content": config.body_text}, "start": {"dateTime": config.start_datetime, "timeZone": config.time_zone}, "end": {"dateTime": config.end_datetime, "timeZone": config.time_zone}}
        elif spec.body == "contact":
            body = {"givenName": config.given_name, "surname": config.surname, "emailAddresses": [{"address": config.email_address}]}
        kwargs = {"headers": {"Authorization": f"Bearer {token}", "Accept": "application/json"}, "params": params}
        if body is not None: kwargs["json"] = body
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(spec.method, GRAPH_ROOT + path, **kwargs)
        if not 200 <= response.status_code < 300:
            try: error = response.json().get("error", {})
            except ValueError: error = {}
            message = error.get("message", response.reason_phrase) if isinstance(error, dict) else response.reason_phrase
            for secret in (token, credential.refresh_token):
                if secret: message = message.replace(secret, "[redacted]")
            raise ValueError(f"Microsoft Graph error ({response.status_code}): {message}")
        result = {"operation": config.operation, "http_status": response.status_code, "status": "accepted" if response.status_code == 202 else "success"}
        if response.content:
            data = response.json()
            if not isinstance(data, dict) or "error" in data: raise ValueError("Microsoft Graph returned an invalid response")
            if config.operation.startswith("list_"):
                if not isinstance(data.get("value"), list): raise ValueError("Microsoft Graph list response lacks value")
                result.update(items=data["value"], count=len(data["value"]))
                following = data.get("@odata.nextLink")
                if following:
                    parsed = urlsplit(following)
                    if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or parsed.path != "/v1.0" + path or parsed.fragment:
                        raise ValueError("Microsoft Graph returned an unexpected continuation URL")
                    result["next_link"] = following
                    # This node accepts offset paging. The URL remains data, never a request target.
                    skips = [v for k, v in parse_qsl(parsed.query) if k == "$skip"]
                    if len(skips) == 1 and skips[0].isdigit(): result["next_skip"] = int(skips[0])
                result["has_more"] = bool(following)
            else: result["data"] = data
        elif config.operation.startswith("list_"):
            raise ValueError("Microsoft Graph returned no list response")
        if config.operation in {"send_email", "reply_message", "forward_message", "send_draft"}:
            result["delivery_verified"] = False
        return result
