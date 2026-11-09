"""Ten workflow actions covering the six operations in Yelp's published Leads 1.0 contract.

https://docs.developer.yelp.com/docs/leads-api
Requires an approved Yelp reseller partner OAuth client and an eligible
advertising business. Writes are single requests and are never retried here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.yelp_leads_oauth import OAUTH_PROVIDER
from nodes.scopes.yelp_leads import YELP_LEADS_SCOPES
from utils.ssrf import guarded_async_client


def _id(value):
    return OAUTH_PROVIDER.context_fields["business_id"].validate(value)


def _timestamp(value):
    if value is None:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Use an ISO 8601 timestamp including its timezone") from None
    return value


class YelpLeadsOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Yelp Leads OAuth", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "yelp_leads",
            "x-oauth-scopes": YELP_LEADS_SCOPES.declared_scopes(),
            "x-credential-url": "https://docs.developer.yelp.com/docs/oauth-authorization",
            "x-credential-instructions": "Requires a Yelp-approved reseller partner OAuth application and an advertising business. Enter your Yelp business ID before signing in. For manual connection, paste existing OAuth access and refresh tokens, their ISO 8601 expiry, and the business ID. A Places API key does not grant Leads access."})
    credential_type: Literal["yelp_leads_oauth"] = Field("yelp_leads_oauth", json_schema_extra={"ui:hidden": True})
    business_id: str = Field(..., title="Yelp business ID")
    access_token: str = Field(..., title="Access token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token expiry", description="ISO 8601 expiry including timezone.")
    _business = field_validator("business_id", mode="before")(_id)
    _expiry = field_validator("expires_at", mode="before")(_timestamp)

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="OAuth token")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Lead(_Input):
    lead_id: str = Field(..., title="Lead ID")
    _lead = field_validator("lead_id", mode="before")(_id)


class GetLead(_Lead):
    operation: Literal["get_lead"] = Field("get_lead", title="Get Lead", json_schema_extra={"ui:hidden": True})


class GetLeadEvents(_Lead):
    operation: Literal["get_lead_events"] = Field("get_lead_events", title="Get Lead Events", json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, ge=1, le=20)
    older_than_cursor: str | None = Field(None, title="Older than cursor")
    newer_than_cursor: str | None = Field(None, title="Newer than cursor")


class WriteLeadEvent(_Lead):
    operation: Literal["write_lead_event"] = Field("write_lead_event", title="Reply to Lead", json_schema_extra={"ui:hidden": True})
    request_content: str = Field(..., min_length=1, title="Message", json_schema_extra={"ui:widget": "textarea"})
    request_type: Literal["TEXT"] = Field("TEXT", json_schema_extra={"ui:hidden": True})

    @field_validator("request_content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Enter a nonempty message")
        return value


class MarkLeadAsReplied(_Lead):
    operation: Literal["mark_lead_as_replied"] = Field("mark_lead_as_replied", title="Mark Lead as Replied", json_schema_extra={"ui:hidden": True})
    reply_type: Literal["PHONE", "EMAIL"] = Field(..., title="Reply medium")


class MarkLeadEventAsRead(_Lead):
    operation: Literal["mark_lead_event_as_read"] = Field("mark_lead_event_as_read", title="Mark Lead Events as Read", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., title="Event ID", description="Marks this event and all earlier events as read.")
    time_read: str | None = Field(None, title="Read time", description="ISO 8601 with timezone; defaults to Yelp's current time.")
    _event = field_validator("event_id", mode="before")(_id)
    _time = field_validator("time_read", mode="before")(_timestamp)


class ListLeadIds(_Input):
    operation: Literal["list_lead_ids"] = Field("list_lead_ids", title="List Business Lead IDs", json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, ge=1, le=20)
    after_lead_id: str | None = Field(None, title="After lead ID")
    created_after: str | None = Field(None, title="Created at or after")
    created_before: str | None = Field(None, title="Created at or before")
    _after = field_validator("created_after", "created_before", mode="before")(_timestamp)


class GetOlderLeadEvents(GetLeadEvents):
    operation: Literal["get_older_lead_events"] = Field("get_older_lead_events", title="Get Older Lead Events", json_schema_extra={"ui:hidden": True})
    older_than_cursor: str = Field(..., min_length=1, title="Before cursor")
    newer_than_cursor: None = Field(None, json_schema_extra={"ui:hidden": True})


class GetNewerLeadEvents(GetLeadEvents):
    operation: Literal["get_newer_lead_events"] = Field("get_newer_lead_events", title="Get Newer Lead Events", json_schema_extra={"ui:hidden": True})
    newer_than_cursor: str = Field(..., min_length=1, title="After cursor")
    older_than_cursor: None = Field(None, json_schema_extra={"ui:hidden": True})


class MarkLeadRepliedByPhone(MarkLeadAsReplied):
    operation: Literal["mark_lead_replied_by_phone"] = Field("mark_lead_replied_by_phone", title="Mark Lead Replied by Phone", json_schema_extra={"ui:hidden": True})
    reply_type: Literal["PHONE"] = Field("PHONE", json_schema_extra={"ui:hidden": True})


class MarkLeadRepliedByEmail(MarkLeadAsReplied):
    operation: Literal["mark_lead_replied_by_email"] = Field("mark_lead_replied_by_email", title="Mark Lead Replied by Email", json_schema_extra={"ui:hidden": True})
    reply_type: Literal["EMAIL"] = Field("EMAIL", json_schema_extra={"ui:hidden": True})


YelpLeadsConfig = Annotated[Union[GetLead, GetLeadEvents, WriteLeadEvent,
    MarkLeadAsReplied, MarkLeadEventAsRead, ListLeadIds, GetOlderLeadEvents,
    GetNewerLeadEvents, MarkLeadRepliedByPhone, MarkLeadRepliedByEmail], Field(discriminator="operation")]


class YelpLeadsFullConfig(NodeConfig[YelpLeadsConfig, YelpLeadsOAuthCredential]):
    pass


class YelpLeadsNode(WorkflowNode):
    integration_type = "automation-yelp-leads"
    scope_registry = YELP_LEADS_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_lead_ids", noun="Yelp leads", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return YelpLeadsFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="yelp_leads")

    async def execute(self, inputs):
        if not isinstance(self.config, YelpLeadsFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Yelp Leads OAuth account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        credential = self.config.credentials.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential,
            refresh=OAUTH_PROVIDER.bind_refresh(credential),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="yelp_leads", caller_path="execute")
        self.config.credentials = YelpLeadsOAuthCredential.model_validate(credential)
        config = self.config.config
        operation = config.operation
        api_operation = {"get_older_lead_events": "get_lead_events",
            "get_newer_lead_events": "get_lead_events",
            "mark_lead_replied_by_phone": "mark_lead_as_replied",
            "mark_lead_replied_by_email": "mark_lead_as_replied"}.get(operation, operation)
        values = config.model_dump(exclude_none=True, exclude={"operation", "lead_id"})
        body = None
        params = None
        method = "GET"
        if api_operation == "list_lead_ids":
            path = "/businesses/" + quote(credential["business_id"], safe="") + "/lead_ids"
            params = values
        else:
            path = "/leads/" + quote(config.lead_id, safe="")
            if api_operation in {"get_lead_events", "write_lead_event"}:
                path += "/events"
            elif api_operation == "mark_lead_as_replied":
                path += "/mark_as_replied"
            elif api_operation == "mark_lead_event_as_read":
                path += "/events/mark_as_read"
            if api_operation == "get_lead_events":
                params = values
            elif api_operation != "get_lead":
                method, body = "POST", values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.yelp.com/v3" + path,
                params=params, json=body, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if response.status_code != (200 if method == "GET" else 201):
            error = "Yelp Leads request failed"
            try:
                candidate = response.json().get("error", {}).get("description")
                if isinstance(candidate, str):
                    error = candidate
            except (ValueError, AttributeError):
                pass
            for secret in (credential["access_token"], credential["refresh_token"]):
                error = error.replace(secret, "[redacted]")
            return {"status": "error", "status_code": response.status_code, "error": error}
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Yelp returned an unexpected response")
        if api_operation == "list_lead_ids":
            ids = payload.get("lead_ids")
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise ValueError("Yelp returned an invalid lead list")
            return {"status": "success", "data": payload, "items": [{"id": item} for item in ids],
                "has_more": payload.get("has_more"),
                "next_after_lead_id": ids[-1] if payload.get("has_more") and ids else None}
        if api_operation == "get_lead_events" and not isinstance(payload.get("events"), list):
            raise ValueError("Yelp returned an invalid event list")
        return {"status": "success", "data": payload}
