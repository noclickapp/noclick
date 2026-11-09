"""Teltel v2 API: contacts, groups, messaging and account reads.

Contract: https://api.teltel.io/v2/api.user.0d9ae995324f03f254d3da8d963d46b2.json
Each exposed operation performs exactly one documented request; pages are explicit.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.teltel.io/v2"


class TeltelAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Teltel API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.teltel.io/",
            "x-credential-instructions": "Paste your Teltel user API key. NoClick sends it as the apikey query parameter to api.teltel.io over HTTPS. The connection check reads users in your account."
        })
    credential_type: Literal["teltel_api_key"] = Field("teltel_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste an API key without whitespace or a header")
        return value


class _Empty(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Fields(_Empty):
    fields: str | None = Field(None, max_length=2000, description="Comma-separated documented response fields; omit for default fields.")


class _Page(_Fields):
    limit: int = Field(100, ge=1, le=5000, description="Maximum rows in this page. No automatic pagination.")
    offset: int = Field(0, ge=0, le=100, description="Rows to skip; the published contract caps this endpoint at 100.")
    sort: str | None = Field(None, max_length=1000, description="Comma-separated sorting fields; prefix with - for descending.")
    filter: str | None = Field(None, max_length=4000, description="Teltel filter expression, as documented for this resource.")


class _CallList(_Empty):
    limit: int = Field(100, ge=1, le=5000)
    offset: int = Field(0, ge=0, le=200000)
    sort: str | None = Field(None, max_length=1000)
    filter: str | None = Field(None, max_length=4000)
    timezone: str | None = Field(None, max_length=100, description="IANA zone or GMT offset, e.g. Europe/Riga.")
    transcripts: Literal["last", "all"] | None = None


class _Resource(_Empty):
    id: int = Field(..., ge=1, description="Teltel resource ID.")


class _ContactFields(_Empty):
    phone: str | None = Field(None, min_length=1, max_length=100)
    group_id: str | None = Field(None, min_length=1, max_length=100, description="Contact group ID, sent as the documented string.")
    param_1: str | None = Field(None, max_length=4000)
    param_2: str | None = Field(None, max_length=4000)
    param_3: str | None = Field(None, max_length=4000)
    param_4: str | None = Field(None, max_length=4000)
    param_5: str | None = Field(None, max_length=4000)


class _ContactCreate(_ContactFields):
    phone: str = Field(..., min_length=1, max_length=100)
    group_id: str = Field(..., min_length=1, max_length=100)


class _ContactUpdate(_ContactFields, _Resource):
    @model_validator(mode="after")
    def has_change(self):
        if not any(getattr(self, key) is not None for key in _ContactFields.model_fields):
            raise ValueError("Supply at least one contact field to update")
        return self


class _Group(_Empty):
    name: str = Field(..., min_length=1, max_length=1000)


class _GroupUpdate(_Group, _Resource):
    pass


class _SMS(_Empty):
    sender: str = Field(..., min_length=3, max_length=14, description="Verified DID or permitted sender ID; maps to Teltel's from field.")
    to: str = Field(..., min_length=3, max_length=16, pattern=r"^\+?[0-9]+$", description="Destination phone number in international format.")
    message: str = Field(..., min_length=1, max_length=160, description="SMS text; Unicode messages are limited to 70 characters.")
    callback: str | bool | None = Field(None, description="Delivery callback URL, true for account default, or false to disable.")

    @model_validator(mode="after")
    def valid_sms(self):
        if not self.message.isascii() and len(self.message) > 70:
            raise ValueError("Unicode SMS must be at most 70 characters")
        if not self.sender.isdigit() and len(self.sender) > 11:
            raise ValueError("Alphanumeric sender IDs must be at most 11 characters")
        if isinstance(self.callback, str) and not re.fullmatch(r"https?://[^\s]+", self.callback):
            raise ValueError("Use an http or https callback URL")
        return self


class TeltelGetBalanceConfig(_Empty):
    """GET /account/balance."""
    operation: Literal["get_balance"] = Field("get_balance", json_schema_extra={"ui:hidden": True})

class TeltelListUsersConfig(_Empty):
    """GET /users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})

class TeltelListDevicesConfig(_Empty):
    """GET /devices."""
    operation: Literal["list_devices"] = Field("list_devices", json_schema_extra={"ui:hidden": True})

class TeltelListCallsConfig(_CallList):
    """GET /calls."""
    operation: Literal["list_calls"] = Field("list_calls", json_schema_extra={"ui:hidden": True})

class TeltelListContactsConfig(_Page):
    """GET /contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})

class TeltelGetContactConfig(_Resource):
    """GET /contacts/{id}."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})

class TeltelCreateContactConfig(_ContactCreate):
    """POST /contacts."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})

class TeltelUpdateContactConfig(_ContactUpdate):
    """PATCH /contacts/{id}."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})

class TeltelDeleteContactConfig(_Resource):
    """DELETE /contacts/{id}."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})

class TeltelListContactGroupsConfig(_Page):
    """GET /contacts/groups."""
    operation: Literal["list_contact_groups"] = Field("list_contact_groups", json_schema_extra={"ui:hidden": True})

class TeltelGetContactGroupConfig(_Resource):
    """GET /contacts/groups/{id}."""
    operation: Literal["get_contact_group"] = Field("get_contact_group", json_schema_extra={"ui:hidden": True})

class TeltelCreateContactGroupConfig(_Group):
    """POST /contacts/groups."""
    operation: Literal["create_contact_group"] = Field("create_contact_group", json_schema_extra={"ui:hidden": True})

class TeltelUpdateContactGroupConfig(_GroupUpdate):
    """PATCH /contacts/groups/{id}."""
    operation: Literal["update_contact_group"] = Field("update_contact_group", json_schema_extra={"ui:hidden": True})

class TeltelDeleteContactGroupConfig(_Resource):
    """DELETE /contacts/groups/{id}."""
    operation: Literal["delete_contact_group"] = Field("delete_contact_group", json_schema_extra={"ui:hidden": True})

class TeltelSendSmsConfig(_SMS):
    """POST /sms/text."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})

class TeltelListSmsReportsConfig(_Page):
    """GET /sms/reports."""
    operation: Literal["list_sms_reports"] = Field("list_sms_reports", json_schema_extra={"ui:hidden": True})

class TeltelGetSmsReportConfig(_Resource):
    """GET /sms/reports/{id}."""
    operation: Literal["get_sms_report"] = Field("get_sms_report", json_schema_extra={"ui:hidden": True})

class TeltelListInboxMessagesConfig(_Page):
    """GET /sms/inbox/reports."""
    operation: Literal["list_inbox_messages"] = Field("list_inbox_messages", json_schema_extra={"ui:hidden": True})

class TeltelGetInboxMessageConfig(_Resource):
    """GET /sms/inbox/reports/{id}."""
    operation: Literal["get_inbox_message"] = Field("get_inbox_message", json_schema_extra={"ui:hidden": True})

class TeltelListAutodialersConfig(_Fields):
    """GET /autodialers."""
    operation: Literal["list_autodialers"] = Field("list_autodialers", json_schema_extra={"ui:hidden": True})


TeltelOperation = Annotated[Union[TeltelGetBalanceConfig, TeltelListUsersConfig, TeltelListDevicesConfig, TeltelListCallsConfig, TeltelListContactsConfig, TeltelGetContactConfig, TeltelCreateContactConfig, TeltelUpdateContactConfig, TeltelDeleteContactConfig, TeltelListContactGroupsConfig, TeltelGetContactGroupConfig, TeltelCreateContactGroupConfig, TeltelUpdateContactGroupConfig, TeltelDeleteContactGroupConfig, TeltelSendSmsConfig, TeltelListSmsReportsConfig, TeltelGetSmsReportConfig, TeltelListInboxMessagesConfig, TeltelGetInboxMessageConfig, TeltelListAutodialersConfig], Field(discriminator="operation")]


class TeltelNodeConfig(NodeConfig[TeltelOperation, TeltelAPIKeyCredential]):
    pass


ROUTES = {'get_balance': ('GET', '/account/balance'), 'list_users': ('GET', '/users'), 'list_devices': ('GET', '/devices'), 'list_calls': ('GET', '/calls'), 'list_contacts': ('GET', '/contacts'), 'get_contact': ('GET', '/contacts/{id}'), 'create_contact': ('POST', '/contacts'), 'update_contact': ('PATCH', '/contacts/{id}'), 'delete_contact': ('DELETE', '/contacts/{id}'), 'list_contact_groups': ('GET', '/contacts/groups'), 'get_contact_group': ('GET', '/contacts/groups/{id}'), 'create_contact_group': ('POST', '/contacts/groups'), 'update_contact_group': ('PATCH', '/contacts/groups/{id}'), 'delete_contact_group': ('DELETE', '/contacts/groups/{id}'), 'send_sms': ('POST', '/sms/text'), 'list_sms_reports': ('GET', '/sms/reports'), 'get_sms_report': ('GET', '/sms/reports/{id}'), 'list_inbox_messages': ('GET', '/sms/inbox/reports'), 'get_inbox_message': ('GET', '/sms/inbox/reports/{id}'), 'list_autodialers': ('GET', '/autodialers')}


def _redact(value, api_key):
    """The users endpoint includes api_key; never expose provider credentials."""
    if isinstance(value, dict):
        return {k: _redact(v, api_key) for k, v in value.items()
                if not re.search(r"api.?key|token|password|secret|authorization", str(k), re.I)}
    if isinstance(value, list):
        return [_redact(v, api_key) for v in value]
    if isinstance(value, str):
        return value.replace(api_key, "[redacted]")
    return value


class TeltelNode(WorkflowNode):
    integration_type = "automation-teltel"
    connection_evidence = ConnectionEvidence(noun="Teltel users", operation="list_users", label_keys=("display_name", "realname", "name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return TeltelNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Teltel API key")
        config = self.config.config
        api_key = self.config.credentials.api_key
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            route = route.replace("{id}", str(values.pop("id")))
        body = None
        params = {"apikey": api_key}
        if method == "GET":
            params.update(values)
        elif method != "DELETE":
            if config.operation == "send_sms":
                values["from"] = values.pop("sender")
            body = {"data": values}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route, params=params, json=body,
                    headers={"Accept": "application/json"})
            if response.status_code != 200:
                # Never emit a response URL or a transport exception: authentication is in the query.
                message = "Teltel request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        message = error.get("message") or error.get("error") or message
                        if not isinstance(message, str):
                            message = "Teltel request failed"
                except ValueError:
                    pass
                output = {"status": "error", "http_status": response.status_code, "message": message}
            else:
                if len(response.content) > 10_000_000:
                    raise ValueError("Teltel response exceeds the supported size")
                payload = response.json()
                if not isinstance(payload, dict) or not ({"data", "meta"} & payload.keys()) or "error" in payload or "errors" in payload:
                    raise ValueError("Teltel returned an unexpected response")
                output = {"status": "success", **payload}
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Teltel request could not be completed; check its outcome before retrying writes") from None
        except ValueError:
            raise ValueError("Teltel returned an unexpected response") from None
        output = _redact(output, api_key)
        await self.emit(output)
        return output
