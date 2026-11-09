"""Zadarma calling, messaging and PBX operations using user API keys.

Each operation makes one documented request. Statistics and templates expose
explicit pagination; writes are never retried automatically.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.zadarma.com"
DOCS = "https://zadarma.com/en/support/api/"


class ZadarmaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zadarma API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://my.zadarma.com/api/",
            "x-credential-instructions": "Paste the key and secret from Zadarma → Settings → API. NoClick signs requests locally and sends them only to api.zadarma.com. Connecting reads your SIP numbers; sending SMS and requesting callbacks may incur charges."})
    credential_type: Literal["zadarma_api_key"] = Field("zadarma_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=512, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=512, title="API secret", json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


Phone = Annotated[str, Field(pattern=r"^\+?[0-9]{7,15}$")]
SIP = Annotated[str, Field(pattern=r"^[0-9]{5}$")]
Extension = Annotated[str, Field(pattern=r"^[0-9]{3}$")]
DateTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")]


class _Period(_Input):
    start: DateTime = Field(..., description="Start in account timezone: YYYY-MM-DD HH:MM:SS.")
    end: DateTime = Field(..., description="End in account timezone: YYYY-MM-DD HH:MM:SS.")
    skip: int = Field(0, ge=0, description="Offset; increase by limit for the next page.")
    limit: int = Field(1000, ge=1, le=1000)

    @model_validator(mode="after")
    def period(self):
        start = datetime.strptime(self.start, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(self.end, "%Y-%m-%d %H:%M:%S")
        if end < start:
            raise ValueError("End must not precede start")
        return self


class GetBalance(_Input):
    """GET /v1/info/balance — get balance."""
    operation: Literal["get_balance"] = Field("get_balance", json_schema_extra={"ui:hidden": True})


class GetCallPrice(_Input):
    """GET /v1/info/price — get call price."""
    operation: Literal["get_call_price"] = Field("get_call_price", json_schema_extra={"ui:hidden": True})
    number: Phone
    caller_id: Phone | None = None


class GetTimezone(_Input):
    """GET /v1/info/timezone — get timezone."""
    operation: Literal["get_timezone"] = Field("get_timezone", json_schema_extra={"ui:hidden": True})


class GetTariff(_Input):
    """GET /v1/tariff — get tariff."""
    operation: Literal["get_tariff"] = Field("get_tariff", json_schema_extra={"ui:hidden": True})


class RequestCallback(_Input):
    """GET /v1/request/callback — request callback."""
    operation: Literal["request_callback"] = Field("request_callback", json_schema_extra={"ui:hidden": True})
    from_number: str = Field(..., pattern=r"^(\+?[0-9]{7,15}|[0-9]{3,5})$", description="Your phone, SIP or PBX extension. Starts a billable call.")
    to: str = Field(..., pattern=r"^(\+?[0-9]{7,15}|[0-9]{5})$")
    sip: SIP | Extension | None = None
    predicted: bool | None = None


class ListSIPNumbers(_Input):
    """GET /v1/sip — list sip numbers."""
    operation: Literal["list_sip_numbers"] = Field("list_sip_numbers", json_schema_extra={"ui:hidden": True})


class GetSIPStatus(_Input):
    """GET /v1/sip/{sip}/status — get sip status."""
    operation: Literal["get_sip_status"] = Field("get_sip_status", json_schema_extra={"ui:hidden": True})
    sip: SIP


class SetSIPCallerID(_Input):
    """PUT /v1/sip/callerid — set sip caller id."""
    operation: Literal["set_sip_caller_id"] = Field("set_sip_caller_id", json_schema_extra={"ui:hidden": True})
    id: SIP
    number: Phone = Field(..., description="A confirmed or purchased caller ID.")


class GetSIPForwarding(_Input):
    """GET /v1/sip/redirection — get sip forwarding."""
    operation: Literal["get_sip_forwarding"] = Field("get_sip_forwarding", json_schema_extra={"ui:hidden": True})
    id: SIP | None = None


class SetSIPForwarding(_Input):
    """PUT /v1/sip/redirection — set sip forwarding."""
    operation: Literal["set_sip_forwarding"] = Field("set_sip_forwarding", json_schema_extra={"ui:hidden": True})
    id: SIP
    status: Literal["on", "off"] = Field(..., description="Switch the existing forwarding destination on or off.")


class GetCallStatistics(_Period):
    """GET /v1/statistics — get call statistics."""
    operation: Literal["get_call_statistics"] = Field("get_call_statistics", json_schema_extra={"ui:hidden": True})
    sip: SIP | None = None
    cost_only: bool | None = None
    type: Literal["overall", "toll-free"] | None = None


class GetPBXStatistics(_Period):
    """GET /v1/statistics/pbx — get pbx statistics."""
    operation: Literal["get_pbx_statistics"] = Field("get_pbx_statistics", json_schema_extra={"ui:hidden": True})
    version: Literal[1, 2] = Field(2, description="Version 2 is recommended.")
    call_type: Literal["in", "out"] | None = None


class ListPBXExtensions(_Input):
    """GET /v1/pbx/internal — list pbx extensions."""
    operation: Literal["list_pbx_extensions"] = Field("list_pbx_extensions", json_schema_extra={"ui:hidden": True})


class GetPBXExtensionStatus(_Input):
    """GET /v1/pbx/internal/{pbxsip}/status — get pbx extension status."""
    operation: Literal["get_pbx_extension_status"] = Field("get_pbx_extension_status", json_schema_extra={"ui:hidden": True})
    pbxsip: Extension


class GetPBXExtensionInfo(_Input):
    """GET /v1/pbx/internal/{pbxsip}/info — get pbx extension info."""
    operation: Literal["get_pbx_extension_info"] = Field("get_pbx_extension_info", json_schema_extra={"ui:hidden": True})
    pbxsip: Extension


class GetPBXForwarding(_Input):
    """GET /v1/pbx/redirection — get pbx forwarding."""
    operation: Literal["get_pbx_forwarding"] = Field("get_pbx_forwarding", json_schema_extra={"ui:hidden": True})
    pbx_number: Extension


class SetPBXForwarding(_Input):
    """POST /v1/pbx/redirection — set pbx forwarding."""
    operation: Literal["set_pbx_forwarding"] = Field("set_pbx_forwarding", json_schema_extra={"ui:hidden": True})
    pbx_number: Extension
    status: Literal["on", "off"]
    type: Literal["phone", "menu", "sip", "sip_uri"] | None = None
    destination: str | None = Field(None, min_length=1, max_length=512)
    condition: Literal["always", "noanswer"] | None = None

    @model_validator(mode="after")
    def forwarding(self):
        fields = (self.type, self.destination, self.condition)
        if self.status == "on" and any(value is None for value in fields):
            raise ValueError("Enabling forwarding requires type, destination and condition")
        if self.status == "off" and any(value is not None for value in fields):
            raise ValueError("Disabling forwarding takes only extension and status")
        return self


class ListVirtualNumbers(_Input):
    """GET /v1/direct_numbers — list virtual numbers."""
    operation: Literal["list_virtual_numbers"] = Field("list_virtual_numbers", json_schema_extra={"ui:hidden": True})


class SendSMS(_Input):
    """POST /v1/sms/send — send sms."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    number: Phone = Field(..., description="One recipient in international format. Sending may incur charges.")
    message: str = Field(..., min_length=1, max_length=10000, description="Long messages are split and billed by Zadarma.")
    sender: str | None = Field(None, max_length=100)
    language: str | None = Field(None, pattern=r"^[a-z]{2}$")


class ListSMSTemplates(_Input):
    """GET /v1/sms/templates — list sms templates."""
    operation: Literal["list_sms_templates"] = Field("list_sms_templates", json_schema_extra={"ui:hidden": True})
    skip: int = Field(0, ge=0)
    limit: int = Field(25, ge=1, le=1000)
    language: Literal["en", "es", "de", "pl", "ru", "ua", "fr"] | None = None


Operations = Annotated[Union[
    GetBalance, GetCallPrice, GetTimezone, GetTariff, RequestCallback, ListSIPNumbers, GetSIPStatus, SetSIPCallerID, GetSIPForwarding, SetSIPForwarding, GetCallStatistics, GetPBXStatistics, ListPBXExtensions, GetPBXExtensionStatus, GetPBXExtensionInfo, GetPBXForwarding, SetPBXForwarding, ListVirtualNumbers, SendSMS, ListSMSTemplates], Field(discriminator="operation")]


class ZadarmaFullConfig(NodeConfig[Operations, ZadarmaAPIKeyCredential]):
    pass


ROUTES = {
    'get_balance': ('GET', '/v1/info/balance'),
    'get_call_price': ('GET', '/v1/info/price'),
    'get_timezone': ('GET', '/v1/info/timezone'),
    'get_tariff': ('GET', '/v1/tariff'),
    'request_callback': ('GET', '/v1/request/callback'),
    'list_sip_numbers': ('GET', '/v1/sip'),
    'get_sip_status': ('GET', '/v1/sip/{sip}/status'),
    'set_sip_caller_id': ('PUT', '/v1/sip/callerid'),
    'get_sip_forwarding': ('GET', '/v1/sip/redirection'),
    'set_sip_forwarding': ('PUT', '/v1/sip/redirection'),
    'get_call_statistics': ('GET', '/v1/statistics'),
    'get_pbx_statistics': ('GET', '/v1/statistics/pbx'),
    'list_pbx_extensions': ('GET', '/v1/pbx/internal'),
    'get_pbx_extension_status': ('GET', '/v1/pbx/internal/{pbxsip}/status'),
    'get_pbx_extension_info': ('GET', '/v1/pbx/internal/{pbxsip}/info'),
    'get_pbx_forwarding': ('GET', '/v1/pbx/redirection'),
    'set_pbx_forwarding': ('POST', '/v1/pbx/redirection'),
    'list_virtual_numbers': ('GET', '/v1/direct_numbers'),
    'send_sms': ('POST', '/v1/sms/send'),
    'list_sms_templates': ('GET', '/v1/sms/templates'),
}


def encode_params(params):
    """PHP_QUERY_RFC1738 sorting/encoding, including PHP boolean scalars."""
    return urlencode(sorted((key, "1" if value is True else "0" if value is False else str(value))
                            for key, value in params.items())).replace("~", "%7E")


def authorization(credential, path, query):
    """The provider PHP example base64-encodes the hexadecimal SHA1 HMAC."""
    message = path + query + hashlib.md5(query.encode()).hexdigest()
    digest = hmac.new(credential.api_secret.encode(), message.encode(), hashlib.sha1).hexdigest()
    return credential.api_key + ":" + base64.b64encode(digest.encode("ascii")).decode("ascii")


class ZadarmaNode(WorkflowNode):
    integration_type = "automation-zadarma"
    connection_evidence = ConnectionEvidence(operation="list_sip_numbers", noun="SIP numbers")

    @classmethod
    def get_config_model(cls):
        return ZadarmaFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Zadarma API key and secret")
        config = self.config.config
        method, path = ROUTES[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("sip", "pbxsip"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(params.pop(field), safe=""))
        # Use the exact route in the provider OpenAPI contract when signing.
        if "from_number" in params:
            params["from"] = params.pop("from_number")
        query = encode_params(params)
        headers = {"Authorization": authorization(self.config.credentials, path, query), "Accept": "application/json"}
        url = BASE + path
        kwargs = {}
        if method == "GET":
            url += "?" + query if query else ""
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            kwargs["content"] = query.encode()
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
        # Preserve provider rejection text for the shared connection validator.
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Zadarma returned an invalid JSON response") from None
        if response.status_code >= 400 or isinstance(body, dict) and body.get("status") == "error":
            message = body.get("message") if isinstance(body, dict) else None
            if isinstance(message, str):
                for secret in (self.config.credentials.api_key, self.config.credentials.api_secret):
                    message = message.replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code,
                    "error": message or "Zadarma rejected the request"}
        templates = config.operation == "list_sms_templates" and isinstance(body, dict) and isinstance(body.get("list"), list)
        if not isinstance(body, dict) or (body.get("status") != "success" and not templates):
            raise ValueError("Zadarma did not confirm the operation")
        result = {"status": "success", "operation": config.operation, "data": body}
        if config.operation == "list_sip_numbers":
            result["items"] = [{"id": row["id"], "name": row.get("display_name") or row["id"]}
                               for row in body.get("sips", [])]
        return result
