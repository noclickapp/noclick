"""CallerAPI phone intelligence, voice screening and DID monitoring.

Contract: https://docs.callerapi.com/raiz5jee8eiph0eeFooV/api/v1/projects/755496/published-projects/export-data?branchId=1014148
API keys are sent only to the fixed official API origin. Each operation makes
one documented request; list results retain the provider's continuation cursor.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.callerapi.com"


class CallerapiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="CallerAPI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://callerapi.com/",
            "x-credential-instructions": "Paste your CallerAPI API key. NoClick sends it in the X-Auth header and reads your account email and balance to verify the connection.",
        })
    credential_type: Literal["callerapi_api_key"] = Field("callerapi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Lookup(_Operation):
    phone: str = Field(..., pattern=r"^[1-9][0-9]{6,14}$", description="International phone number, digits only, without a leading plus.")


class _MonitoredPhone(_Operation):
    phone: str = Field(..., pattern=r"^\+[1-9][0-9]{6,14}$", description="Monitored phone number in E.164 format, including +.")


class _ListScope(_Operation):
    list_id: int | None = Field(None, description="Monitoring list ID; omit for the account default.")


class GetAccount(_Operation):
    """Balance and email."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class LookupPhone(_Lookup):
    """Spam score + HLR."""
    operation: Literal["lookup_phone"] = Field("lookup_phone", json_schema_extra={"ui:hidden": True})
    hlr: StrictBool | None = Field(None, description="Request the optional HLR lookup; provider charges apply.")


class GetPortedDate(_Lookup):
    """Ported date."""
    operation: Literal["get_ported_date"] = Field("get_ported_date", json_schema_extra={"ui:hidden": True})


class GetPortingHistory(_Lookup):
    """Porting history."""
    operation: Literal["get_porting_history"] = Field("get_porting_history", json_schema_extra={"ui:hidden": True})


class GetOnlinePresence(_Lookup):
    """Online presence."""
    operation: Literal["get_online_presence"] = Field("get_online_presence", json_schema_extra={"ui:hidden": True})


class ScanTranscript(_Operation):
    """Score a transcript or a recording."""
    operation: Literal["scan_transcript"] = Field("scan_transcript", json_schema_extra={"ui:hidden": True})
    transcript: str = Field(..., min_length=1, description="Call transcript to score. Provider charges apply.")
    caller_number: str | None = Field(None, pattern=r"^\+[1-9][0-9]{6,14}$", description="Caller E.164 number; required when reporting.")
    called_number: str | None = Field(None, pattern=r"^\+[1-9][0-9]{6,14}$")
    report: StrictBool = Field(False, description="File complaints when the score is at least 0.8.")

    @model_validator(mode="after")
    def report_caller(self):
        if self.report and not self.caller_number:
            raise ValueError("Reporting requires the caller number")
        return self


class ListVoiceSessions(_Operation):
    """List your recent sessions."""
    operation: Literal["list_voice_sessions"] = Field("list_voice_sessions", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=200, description="Maximum recent sessions to return; this endpoint has no cursor.")


class GetVoiceSession(_Operation):
    """Get one session with verdict and intel."""
    operation: Literal["get_voice_session"] = Field("get_voice_session", json_schema_extra={"ui:hidden": True})
    session_id: UUID = Field(..., description="Session ID from a scan or event.")


class SubmitNumbers(_ListScope):
    """Submit numbers."""
    operation: Literal["submit_numbers"] = Field("submit_numbers", json_schema_extra={"ui:hidden": True})
    numbers: list[str] = Field(..., min_length=1, max_length=100000, description="E.164 numbers, or national numbers with default_country. Each scheduled check uses credits.")
    default_country: str | None = Field(None, pattern=r"^[A-Z]{2}$", description="ISO 3166 two-letter country code for national numbers.")

    @field_validator("numbers")
    @classmethod
    def valid_numbers(cls, value):
        if any(not n.strip() or len(n) > 64 for n in value):
            raise ValueError("Supply nonempty phone numbers of at most 64 characters")
        return value


class ListNumbers(_ListScope):
    """List number status."""
    operation: Literal["list_numbers"] = Field("list_numbers", json_schema_extra={"ui:hidden": True})
    status: Literal["pending", "clean", "flagged", "unknown"] | None = None
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, description="next_cursor from the previous page; retain the same status and list_id.")


class GetNumber(_MonitoredPhone):
    """Read one number."""
    operation: Literal["get_number"] = Field("get_number", json_schema_extra={"ui:hidden": True})


class RemoveNumber(_MonitoredPhone):
    """Remove a number."""
    operation: Literal["remove_number"] = Field("remove_number", json_schema_extra={"ui:hidden": True})


class GetSchedule(_ListScope):
    """Read the check schedule."""
    operation: Literal["get_schedule"] = Field("get_schedule", json_schema_extra={"ui:hidden": True})


class SetSchedule(_ListScope):
    """Set the check schedule."""
    operation: Literal["set_schedule"] = Field("set_schedule", json_schema_extra={"ui:hidden": True})
    enabled: StrictBool | None = None
    mode: Literal["interval", "times"] | None = None
    interval_minutes: Literal[15, 30, 60, 120, 180, 240, 360, 480, 720, 1440] | None = None
    times: list[str] | None = Field(None, min_length=1, max_length=24)
    weekdays: list[int] | None = None
    start: str | None = None
    end: str | None = None
    timezone: str | None = Field(None, description="IANA timezone, such as UTC or America/New_York.")

    @field_validator("times")
    @classmethod
    def check_times(cls, value):
        if value is not None and (len(set(value)) != len(value) or any(not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", v) for v in value)):
            raise ValueError("Use distinct times in HH:MM format")
        return value

    @field_validator("weekdays")
    @classmethod
    def check_weekdays(cls, value):
        if value is not None and (not value or any(v < 1 or v > 7 for v in value) or len(set(value)) != len(value)):
            raise ValueError("Weekdays must be distinct integers from 1 to 7")
        return value

    @field_validator("start", "end")
    @classmethod
    def check_window(cls, value, info):
        if value is not None and not (info.field_name == "end" and value == "24:00") and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            raise ValueError("Use HH:MM; end also accepts 24:00")
        return value

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Use an IANA timezone") from None
        return value

    @model_validator(mode="after")
    def check_schedule(self):
        if not any(getattr(self, k) is not None for k in ("enabled", "mode", "interval_minutes", "times", "weekdays", "start", "end", "timezone")):
            raise ValueError("Supply at least one schedule change")
        if (self.mode == "times" and self.interval_minutes is not None) or (self.mode == "interval" and self.times is not None):
            raise ValueError("Use schedule fields matching the selected mode")
        return self


class SaveWebhook(_Operation):
    """Save the webhook URL."""
    operation: Literal["save_webhook"] = Field("save_webhook", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, max_length=2048, description="Public HTTPS receiver URL on port 443 or 8443. The response contains the signing secret once.")

    @field_validator("url")
    @classmethod
    def webhook_url(cls, value):
        try:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443, 8443):
                raise ValueError()
        except ValueError:
            raise ValueError("Use a public HTTPS URL on port 443 or 8443") from None
        return value


class GetWebhook(_Operation):
    """Read the webhook."""
    operation: Literal["get_webhook"] = Field("get_webhook", json_schema_extra={"ui:hidden": True})


class DeleteWebhook(_Operation):
    """Delete the webhook."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})


class TestWebhook(_Operation):
    """Send a test event."""
    operation: Literal["test_webhook"] = Field("test_webhook", json_schema_extra={"ui:hidden": True})


class RotateWebhookSecret(_Operation):
    """Rotate the webhook secret."""
    operation: Literal["rotate_webhook_secret"] = Field("rotate_webhook_secret", json_schema_extra={"ui:hidden": True})


CallerapiConfig = Annotated[Union[GetAccount, LookupPhone, GetPortedDate, GetPortingHistory, GetOnlinePresence, ScanTranscript, ListVoiceSessions, GetVoiceSession, SubmitNumbers, ListNumbers, GetNumber, RemoveNumber, GetSchedule, SetSchedule, SaveWebhook, GetWebhook, DeleteWebhook, TestWebhook, RotateWebhookSecret], Field(discriminator="operation")]


class CallerapiFullConfig(NodeConfig[CallerapiConfig, CallerapiAPIKeyCredential]):
    pass


ROUTES = {'get_account': ('GET', '/api/me'), 'lookup_phone': ('GET', '/api/lookup/{phone}'), 'get_ported_date': ('GET', '/api/ported/{phone}'), 'get_porting_history': ('GET', '/api/porting-history/{phone}'), 'get_online_presence': ('GET', '/api/online-presence/{phone}'), 'scan_transcript': ('POST', '/api/voice/scan'), 'list_voice_sessions': ('GET', '/api/voice/sessions'), 'get_voice_session': ('GET', '/api/voice/sessions/{id}'), 'submit_numbers': ('POST', '/api/did-monitoring/v1/numbers'), 'list_numbers': ('GET', '/api/did-monitoring/v1/numbers'), 'get_number': ('GET', '/api/did-monitoring/v1/numbers/{phone}'), 'remove_number': ('DELETE', '/api/did-monitoring/v1/numbers/{phone}'), 'get_schedule': ('GET', '/api/did-monitoring/v1/schedule'), 'set_schedule': ('PUT', '/api/did-monitoring/v1/schedule'), 'save_webhook': ('PUT', '/api/did-monitoring/v1/webhook'), 'get_webhook': ('GET', '/api/did-monitoring/v1/webhook'), 'delete_webhook': ('DELETE', '/api/did-monitoring/v1/webhook'), 'test_webhook': ('POST', '/api/did-monitoring/v1/webhook/test'), 'rotate_webhook_secret': ('POST', '/api/did-monitoring/v1/webhook/rotate-secret')}


class CallerapiNode(WorkflowNode):
    integration_type = "automation-callerapi"
    connection_evidence = ConnectionEvidence(noun="CallerAPI account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return CallerapiFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a CallerAPI API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        values.pop("operation")
        for field, placeholder in (("phone", "phone"), ("session_id", "id")):
            if "{" + placeholder + "}" in path:
                path = path.replace("{" + placeholder + "}", quote(str(values.pop(field)), safe=""))
        params, body = {}, None
        if method == "GET":
            params = values
        elif method in ("POST", "PUT"):
            body = values
            if config.operation == "set_schedule" and "list_id" in body:
                params["list_id"] = body.pop("list_id")
            if config.operation == "scan_transcript":
                for source, target in (("caller_number", "from"), ("called_number", "to")):
                    if source in body:
                        body[target] = body.pop(source)
        # A fixed origin, disabled redirects and the shared guarded transport keep
        # the key from following an untrusted response location.
        async with guarded_async_client(timeout=60.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-Auth": credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "CallerAPI returned a non-JSON response"}
        if not response.is_success or not isinstance(payload, dict) or payload.get("status") in ("error", "failed") or payload.get("error"):
            message = (payload.get("error") or payload.get("message")) if isinstance(payload, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": str(message or "CallerAPI did not accept the request").replace(credential.api_key, "[redacted]")}
        if config.operation == "get_account" and not isinstance(payload.get("email"), str):
            return {"status": "error", "error": "CallerAPI account response is missing the email"}
        return {**payload, "status": "success", "http_status": response.status_code}
