"""MightyCall v4 operations from the provider's published Swagger contract.

Authentication is a manually supplied API key and bearer token (24-hour lifetime).
Webhooks are configured only in the provider UI; calls and voicemails use the
scheduled-poll family and the API's documented UTC interval filters instead.
Contract: https://api.mightycall.com/v4/api/swagger/docs/v4
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.mightycall.com/v4/api"
DOCS = "https://api.mightycall.com/v4/api/swagger/docs/v4"


class MightyCallTokenCredential(BaseModel):
    model_config = ConfigDict(title="MightyCall API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://panel.mightycall.com/mightycall/settings/api",
            "x-credential-instructions": "Paste your MightyCall API key and existing authorization token. The API key is in Settings > API. Generate an authorization token with the documented POST /auth/token client_credentials request using your API key and secret key or extension. Tokens last 24 hours: replace the token here when it expires. API access requires an eligible MightyCall plan.",
        })
    credential_type: Literal["mightycall_api_token"] = Field("mightycall_api_token", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    access_token: str = Field(..., title="Authorization token", min_length=1, max_length=16384, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "access_token", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="MightyCall credential")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the key or token, without an Authorization header")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Interval(_Config):
    page_size: int = Field(100, ge=1, le=1000, description="Number of records per page.")
    skip: int = Field(0, ge=0)
    start_utc: datetime | None = Field(None, description="Start of the UTC date/time interval (ISO 8601).")
    end_utc: datetime | None = Field(None, description="End of the UTC date/time interval (ISO 8601).")
    custom_filter: str | None = Field(None, max_length=1000)


class _CallFilter(_Interval):
    call_filter: Literal["Incoming", "Outgoing", "InOutgoing", "Connected", "Missed", "Canceled", "Dropped", "Voicemail", "InternalOnly", "CallbackWidget"] | None = None
    extension: str | None = None


class MightyCallListCallsConfig(_CallFilter):
    operation: Literal["list_calls"] = "list_calls"


class MightyCallGetCallConfig(_Config):
    operation: Literal["get_call"] = "get_call"
    call_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


class MightyCallMakeCallConfig(_Config):
    operation: Literal["make_call"] = "make_call"
    from_number: str = Field(..., title="From number", pattern=r"^\+?(?:[0-9] ?){6,14}[0-9]$")
    to_number: str = Field(..., title="To number or extension", pattern=r"^\+?(?:[0-9] ?){2,15}$")


class MightyCallListVoicemailsConfig(_Interval):
    operation: Literal["list_voicemails"] = "list_voicemails"
    voicemail_filter: Literal["None", "Read", "UnRead", "ReadAndUnRead", "CallerName", "CallerAddress", "CalledName", "CalledAddress", "StartTime", "StartDate", "Duration", "TextFields"] | None = None


class MightyCallGetVoicemailConfig(_Config):
    operation: Literal["get_voicemail"] = "get_voicemail"
    voicemail_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


class MightyCallListContactsConfig(_Config):
    operation: Literal["list_contacts"] = "list_contacts"
    page: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=1000)
    name: str | None = Field(None, description="Search first, last and middle names.")
    phone: str | None = None
    email: str | None = None
    tag: str | None = None
    updated_since: datetime | None = None
    include_auto: bool | None = None


class _ContactId(_Config):
    contact_id: str = Field(..., pattern=r"^[0-9a-fA-F]{24}$")


class MightyCallGetContactConfig(_ContactId):
    operation: Literal["get_contact"] = "get_contact"


class MightyCallChannel(_Config):
    model_config = ConfigDict(extra="forbid")
    labels: list[str] = Field(default_factory=list)
    phone: str | None = None
    email: str | None = None

    @model_validator(mode="after")
    def has_address(self):
        if not self.phone and not self.email:
            raise ValueError("A contact channel needs a phone number or email address")
        return self


class _ContactFields(_Config):
    first_name: str = Field(..., min_length=1, title="First name")
    last_name: str | None = None
    patronymic: str | None = Field(None, title="Middle name")
    comment: str | None = None
    tags: list[str] = Field(default_factory=list)
    channels: list[MightyCallChannel] = Field(default_factory=list)
    check_intersection: bool = Field(False, description="Refuse contacts whose phone numbers overlap an existing contact.")


class MightyCallCreateContactConfig(_ContactFields):
    operation: Literal["create_contact"] = "create_contact"


class MightyCallReplaceContactConfig(_ContactFields, _ContactId):
    """Replace all contact fields and channels. Omitted fields are removed."""
    operation: Literal["replace_contact"] = "replace_contact"
    etag: str | None = Field(None, description="Optional concurrency token from the last contact read.")


class MightyCallDeleteContactConfig(_ContactId):
    operation: Literal["delete_contact"] = "delete_contact"
    etag: str | None = None


class MightyCallAddContactTagsConfig(_ContactId):
    operation: Literal["add_contact_tags"] = "add_contact_tags"
    tags: list[str] = Field(..., min_length=1, description="Tags to add. Existing tags are preserved.")
    etag: str | None = None


class MightyCallListTagsConfig(_Config):
    operation: Literal["list_tags"] = "list_tags"


class MightyCallGetContactLimitsConfig(_Config):
    operation: Literal["get_contact_limits"] = "get_contact_limits"


class MightyCallSendMessageConfig(_Config):
    operation: Literal["send_message"] = "send_message"
    from_number: str = Field(..., title="From number", pattern=r"^(\+1\d{8,15})$")
    to_numbers: list[str] = Field(..., min_length=1, title="Recipient numbers")
    message: str = Field(..., min_length=1, title="Message")


class MightyCallListPhoneNumbersConfig(_Config):
    operation: Literal["list_phone_numbers"] = "list_phone_numbers"


class MightyCallGetPhoneNumberConfig(_Config):
    operation: Literal["get_phone_number"] = "get_phone_number"
    phone_number: str = Field(..., pattern=r"^[0-9]{1,11}$", description="Digits only. The API returns the first number containing these digits.")


class MightyCallGetProfileConfig(_Config):
    operation: Literal["get_profile"] = "get_profile"


class MightyCallGetStatusConfig(_Config):
    operation: Literal["get_status"] = "get_status"


class MightyCallSetStatusConfig(_Config):
    operation: Literal["set_status"] = "set_status"
    status: Literal["available", "dnd"] = Field(..., title="Availability")


class MightyCallGetTeamConfig(_Config):
    operation: Literal["get_team"] = "get_team"


class MightyCallOnNewCallConfig(PollTriggerConfigBase):
    operation: Literal["on_new_call"] = Field("on_new_call", json_schema_extra={"x-is-trigger": True})
    lookback_hours: int = Field(24, ge=1, le=168, description="Poll this rolling UTC window. First poll records a baseline; subsequent polls emit unseen call IDs. Increase for workflow downtime.")
    call_filter: Literal["Incoming", "Outgoing", "InOutgoing", "Connected", "Missed", "Canceled", "Dropped", "Voicemail", "InternalOnly", "CallbackWidget"] | None = None
    extension: str | None = None


class MightyCallOnNewVoicemailConfig(PollTriggerConfigBase):
    operation: Literal["on_new_voicemail"] = Field("on_new_voicemail", json_schema_extra={"x-is-trigger": True})
    lookback_hours: int = Field(24, ge=1, le=168, description="Poll this rolling UTC window. First poll records a baseline; subsequent polls emit unseen voicemail IDs. Increase for workflow downtime.")


MightyCallConfig = Annotated[Union[
    MightyCallListCallsConfig, MightyCallGetCallConfig, MightyCallMakeCallConfig,
    MightyCallListVoicemailsConfig, MightyCallGetVoicemailConfig,
    MightyCallListContactsConfig, MightyCallGetContactConfig, MightyCallCreateContactConfig,
    MightyCallReplaceContactConfig, MightyCallDeleteContactConfig, MightyCallAddContactTagsConfig,
    MightyCallListTagsConfig, MightyCallGetContactLimitsConfig, MightyCallSendMessageConfig,
    MightyCallListPhoneNumbersConfig, MightyCallGetPhoneNumberConfig,
    MightyCallGetProfileConfig, MightyCallGetStatusConfig, MightyCallSetStatusConfig,
    MightyCallGetTeamConfig, MightyCallOnNewCallConfig, MightyCallOnNewVoicemailConfig,
], Field(discriminator="operation")]


class MightyCallFullConfig(NodeConfig[MightyCallConfig, MightyCallTokenCredential]):
    pass


# Each operation targets precisely one published API operation. Poll operations
# reuse the corresponding list endpoint; pagination never changes that endpoint.
ROUTES = {
    "list_calls": ("GET", "/calls"),
    "get_call": ("GET", "/calls/{call_id}"),
    "make_call": ("POST", "/calls/makecall"),
    "list_voicemails": ("GET", "/voicemails"),
    "get_voicemail": ("GET", "/voicemails/{voicemail_id}"),
    "list_contacts": ("GET", "/contacts"),
    "get_contact": ("GET", "/contacts/{contact_id}"),
    "create_contact": ("POST", "/contacts"),
    "replace_contact": ("PUT", "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "add_contact_tags": ("POST", "/contacts/{contact_id}/tags"),
    "list_tags": ("GET", "/contacts/tags"),
    "get_contact_limits": ("GET", "/contacts/limits"),
    "send_message": ("POST", "/messages/send"),
    "list_phone_numbers": ("GET", "/phonenumbers"),
    "get_phone_number": ("GET", "/phonenumbers/{phone_number}"),
    "get_profile": ("GET", "/profile"),
    "get_status": ("GET", "/profile/status"),
    "set_status": ("PUT", "/profile/status/{status}"),
    "get_team": ("GET", "/team"),
    "on_new_call": ("GET", "/calls"),
    "on_new_voicemail": ("GET", "/voicemails"),
}
QUERY_FIELDS = {
    "page_size": "pageSize", "skip": "skip", "start_utc": "startUtc", "end_utc": "endUtc",
    "call_filter": "callFilter", "custom_filter": "customFilter", "extension": "extension",
    "voicemail_filter": "voicemailFilter", "page": "page", "name": "name",
    "phone": "phone", "email": "email", "tag": "tag", "updated_since": "updatedSince",
    "include_auto": "includeAuto", "check_intersection": "checkIntersection", "etag": "etag",
}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.access_token):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        # Preserve response dictionaries so schema-aware readers keep observing
        # the fields the parser and agent-event hooks actually access.
        for key in list(value):
            value[key] = _redact(value[key], credential)
        return value
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    return value


class MightyCallNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-mightycall"
    connection_evidence = ConnectionEvidence(operation="list_phone_numbers", noun="business phone numbers", label_keys=("number", "label", "description"), identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return MightyCallFullConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + credential.access_token,
                         "x-api-key": credential.api_key, "Accept": "application/json"})
        if not response.content:
            if 200 <= response.status_code < 300:
                return {"http_status": response.status_code}
            raise ValueError(f"MightyCall HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"MightyCall returned non-JSON (HTTP {response.status_code})") from None
        data = _redact(data, credential)
        if not 200 <= response.status_code < 300 or isinstance(data, dict) and data.get("isSuccess") is False:
            detail = data.get("message", "Request rejected") if isinstance(data, dict) else "Request rejected"
            raise ValueError(f"MightyCall HTTP {response.status_code}: {detail}")
        if not isinstance(data, (dict, list)):
            raise ValueError("MightyCall returned an unexpected response")
        return data

    @staticmethod
    def _rows(body, kind):
        data = body.get("data") if isinstance(body, dict) else None
        rows = data.get(kind) if isinstance(data, dict) else None
        total = data.get("total") if isinstance(data, dict) else None
        if not isinstance(rows, list) or type(total) is not int or total < 0 or any(not isinstance(row, dict) for row in rows):
            raise ValueError("MightyCall list response is missing records or total")
        return rows, total

    async def _poll(self, credential, config, path):
        kind = "calls" if config.operation == "on_new_call" else "voicemails"
        params = {"pageSize": 100, "skip": 0,
                  "startUtc": (datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)).isoformat(),
                  "endUtc": datetime.now(timezone.utc).isoformat()}
        if kind == "calls":
            for field in ("call_filter", "extension"):
                if getattr(config, field) is not None:
                    params[QUERY_FIELDS[field]] = getattr(config, field)
        items = []
        for _ in range(100):
            body = await self._request(credential, "GET", path, params=params)
            rows, total = self._rows(body, kind)
            if any(not isinstance(row.get("id"), str) or not row["id"] for row in rows):
                raise ValueError("MightyCall poll record has no ID")
            items.extend(rows)
            params["skip"] += len(rows)
            if params["skip"] >= total:
                break
            if not rows:
                raise ValueError("MightyCall pagination stopped before all records were read")
        else:
            raise ValueError("MightyCall poll exceeds 100 pages; reduce the lookback window")
        # Provider examples may repeat a voicemail ID: emit a resource once.
        items = list({row["id"]: row for row in items}.values())
        fresh = await self._filter_unseen(items, lambda row: row["id"])
        return {"status": "success", "operation": config.operation, "items": fresh, "count": len(fresh)}

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a MightyCall API token")
        operation = config.operation
        method, template = ROUTES[operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        if isinstance(config, (MightyCallOnNewCallConfig, MightyCallOnNewVoicemailConfig)):
            return await self._poll(credential, config, path)
        params = {}
        for field, wire in QUERY_FIELDS.items():
            value = getattr(config, field, None)
            # set_status uses a path parameter; status isn't a query field.
            if value is not None:
                params[wire] = value.isoformat() if isinstance(value, datetime) else str(value).lower() if isinstance(value, bool) else value
        body = None
        if operation == "make_call":
            body = {"from": config.from_number, "to": config.to_number}
        elif operation == "send_message":
            body = {"from": config.from_number, "to": config.to_numbers, "message": config.message}
        elif operation in {"create_contact", "replace_contact"}:
            body = {wire: values[field] for field, wire in {
                "first_name": "firstName", "last_name": "lastName", "patronymic": "patronymic",
                "comment": "comment", "tags": "tags", "channels": "channels"}.items() if field in values}
            # comment is a body field on a contact, never a search query.
        elif operation == "add_contact_tags":
            body = config.tags
        result = await self._request(credential, method, path, params=params, body=body)
        return {"status": "success", "operation": operation, "data": result}

    @classmethod
    def resolve_agent_event(cls, output):
        items = output.get("items")
        if not items:
            return None
        voicemail = output.get("operation") == "on_new_voicemail"
        title = "New MightyCall voicemail" if voicemail else "New MightyCall call"
        lines = [title]
        for item in items[:50]:
            if voicemail:
                lines.append(f"From {item.get('from', 'unknown caller')} to {item.get('to', 'unknown number')}; voicemail {item.get('id')}, at {item.get('dateTimeUtc')}, assigned to {item.get('assignedTo')}, status {item.get('voicemailStatus')}, duration {item.get('duration')} seconds. Recording: {(item.get('voicemailRecord') or {}).get('uri', 'not provided')}.")
            else:
                caller = item.get("caller") or {}
                who = caller.get("name") or caller.get("phone") or caller.get("extension") or "unknown caller"
                lines.append(f"{item.get('direction')} call from {who}, business number {item.get('businessNumber')}; call {item.get('id')}, at {item.get('dateTimeUtc')}, status {item.get('callStatus')}. Recipients: {json.dumps(item.get('called', []), ensure_ascii=False)}")
        return {"title": title, "text": "\n".join(lines)[:16000], "conversation_key": "mightycall:" + str(items[0].get("id"))}
