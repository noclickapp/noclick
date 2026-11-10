"""Websupport DNS metadata uses the current v2 signed Basic-header contract.
The saved service reference binds closed reads without asserting account ownership.
DNS contents, credentials, DynDNS controls and unrelated hosting routes are excluded.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import re
import time
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

ROOT = "https://rest.websupport.sk"
HIDDEN = {"ui:hidden": True}
ROUTES = {"verify": "/v2/check", "zone": "/v2/service/{service}/dns/zone", "records": "/v2/service/{service}/dns/record"}
RecordType = Literal["A", "AAAA", "ANAME", "CAA", "CNAME", "DNSSEC", "MX", "NS", "SRV", "TXT", "CERT", "LOC", "SSHFP", "TLSA", "DS"]
RECORD_TYPES = set(RecordType.__args__)
WEBSUPPORT_SCOPES = ScopeRegistry("websupport", {kind: ScopeRequirement((), credential_types=("websupport_api_key",),
    note="Existing key/secret request signing; no OAuth scopes or actor ownership are inferred.") for kind in ROUTES})

def _service(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,190}", value):
        raise ValueError("Supply a bounded existing opaque service reference, not a URL or path.")
    return value

class WebsupportApiKeyCredential(BaseModel):
    credential_type: Literal["websupport_api_key"] = Field("websupport_api_key", json_schema_extra=HIDDEN)
    api_key: str = Field(..., min_length=1, max_length=8192, title="Existing API Key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=8192, title="Existing Signing Secret", json_schema_extra={"ui:widget": "password"},
        description="Used locally for fresh HMAC-SHA1 signatures. The secret itself is never transmitted.")
    service_id: str = Field(..., min_length=1, max_length=191, title="Existing Service Reference",
        description="Opaque supplied service route reference. No service catalog is invented; this need not equal a domain name.")
    _service_value = field_validator("service_id", mode="before")(_service)
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://rest.websupport.sk/v2/docs/intro",
        "x-credential-instructions": "Supply an existing API key, signing secret and selected service reference. NoClick sends Basic key:fresh-signature, not key:secret, with matching UTC X-Date. Only protected v2 verification/zone/record metadata reads are implemented; no key issue, rotation, exchange or ownership claim."})
    @field_validator("api_key", mode="before")
    @classmethod
    def key_value(cls, value):
        if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f:]|://", value):
            raise ValueError("Supply the raw existing API key without a prefix, URL, colon or whitespace.")
        return value
    @field_validator("api_secret", mode="before")
    @classmethod
    def secret_value(cls, value):
        if not isinstance(value, str) or not value or re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("Supply the existing printable signing secret.")
        return value

def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "websupport_api_key":
        raise ValueError("Use the current Websupport API key credential.")
    try:
        model = WebsupportApiKeyCredential.model_validate({key: data[key] for key in WebsupportApiKeyCredential.model_fields if key in data})
    except Exception:
        raise ValueError("The Websupport key, secret or service reference is invalid.") from None
    return {**data, **model.model_dump(mode="json")}

class WebsupportReadConfig(BaseModel):
    include_names: bool = Field(False, strict=True, description="Opt in to zone/record names. DNS contents and all private hosting fields remain excluded.")
    max_items: int = Field(100, strict=True, ge=1, le=100, description="Local default-page output limit, not a provider pagination parameter.")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
class WebsupportCheckConfig(WebsupportReadConfig):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra=HIDDEN)
class WebsupportZoneConfig(WebsupportReadConfig):
    operation: Literal["get_zone"] = Field("get_zone", json_schema_extra=HIDDEN)
class WebsupportRecordsConfig(WebsupportReadConfig):
    operation: Literal["list_records"] = Field("list_records", json_schema_extra=HIDDEN)
    record_type: RecordType | None = Field(None, json_schema_extra={"x-dynamic-options": {"field": "record_type"}},
        description="Optional local type selection from the current saved service's protected zone/record page; never sent as a query filter.")
WebsupportConfig = Annotated[Union[WebsupportCheckConfig, WebsupportZoneConfig, WebsupportRecordsConfig], Field(discriminator="operation")]
class WebsupportNodeConfig(NodeConfig[WebsupportConfig, WebsupportApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)

def _headers(data, path):
    # The same integer instant supplies both canonical signing text and UTC X-Date.
    stamp = int(time.time())
    signature = hmac.new(data["api_secret"].encode("utf-8"), f"GET {path} {stamp}".encode("utf-8"), hashlib.sha1).hexdigest()
    basic = base64.b64encode((data["api_key"]+":"+signature).encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic "+basic, "X-Date": datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "NoClick-Websupport/1.0 (+https://noclick.com)"}

async def _request(data, kind):
    data = _credential(data)
    if kind not in ROUTES:
        raise ValueError("Unsupported Websupport metadata route.")
    WEBSUPPORT_SCOPES.enforce_credential_type(kind, data["credential_type"])
    path = ROUTES[kind].replace("{service}", quote(data["service_id"], safe=""))
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25) as client:
            response = await client.get(ROOT+path, headers=_headers(data, path))
    except Exception:
        raise RuntimeError("Websupport could not be reached; signed-request access remains unverified.") from None
    if response.status_code != 200:
        messages = {401: "Websupport did not confirm signed-request access.", 403: "Websupport did not confirm service access.",
            404: "The Websupport service resource is missing or inaccessible.", 429: "Websupport throttled the metadata request."}
        raise RuntimeError(messages.get(response.status_code, "Websupport did not return usable metadata."))
    if len(response.content) > 2000000:
        raise RuntimeError("Websupport metadata exceeded the local response bound.")
    try:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        body = response.json()
        if not isinstance(body, dict) or (mime != "application/json" and not mime.endswith("+json")) or any(key in body for key in ("error", "errors", "message", "detail")):
            raise ValueError()
        return body
    except Exception:
        raise RuntimeError("Websupport returned unsupported bounded JSON metadata.") from None

def _text(value, maximum=1024):
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]|://", value):
        raise ValueError()
    return value

def _name(value):
    value = _text(value)
    if re.search(r"[:/\\?#]", value):
        raise ValueError()
    return value

def _zone(raw, names):
    try:
        if any(key in raw for key in ("data", "results", "items", "zone")):
            raise ValueError()
        row = {}
        if "name" in raw:
            name = _name(raw["name"])
            if names:
                row["name"] = name
        if "lastCheck" in raw:
            row["lastCheck"] = _text(raw["lastCheck"], 128)
        if "dnssecSigning" in raw:
            if raw["dnssecSigning"] not in {"active", "inactive", "disabled"}:
                raise ValueError()
            row["dnssecSigning"] = raw["dnssecSigning"]
        return row
    except Exception:
        raise RuntimeError("Websupport zone metadata did not match the current direct-object contract.") from None

def _records(raw, names):
    try:
        counts = {key: raw[key] for key in ("currentPage", "rowsPerPage", "totalPages", "totalRecords")}
        if any(type(value) is not int or not 0 <= value < 2**53 for value in counts.values()):
            raise ValueError()
        data = raw["data"]
        if not isinstance(data, list) or len(data) > 1000:
            raise ValueError()
        rows, identifiers = [], set()
        for item in data:
            if not isinstance(item, dict):
                raise ValueError()
            identifier, kind, ttl = item["id"], item["type"], item["ttl"]
            if identifier is not None and (type(identifier) is not int or not 0 <= identifier < 2**53 or identifier in identifiers):
                raise ValueError()
            if kind not in RECORD_TYPES or type(ttl) is not int or not 0 <= ttl < 2**31:
                raise ValueError()
            name = _name(item["name"])
            if identifier is not None:
                identifiers.add(identifier)
            rows.append({"id": identifier, "type": kind, "ttl": ttl, **({"name": name} if names else {})})
        return rows, counts
    except Exception:
        raise RuntimeError("Websupport record metadata did not match the current page/nullable-ID contract.") from None

class WebsupportVerificationDenied(RuntimeError):
    pass

class WebsupportNode(WorkflowNode):
    integration_type = "automation-websupport"
    credential_provider_labels = {"websupport": "Websupport Account"}
    auto_select_credential = False
    scope_registry = WEBSUPPORT_SCOPES
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="DNS zone metadata", label_keys=("lastCheck", "dnssecSigning"), proves="reachability")
    @classmethod
    def get_config_model(cls):
        return WebsupportNodeConfig
    @classmethod
    async def validate_credential_access(cls, credential_data):
        from nodes.core.run_op import run_node_operation
        result = await run_node_operation(node_type="automation-websupport", operation="check_connection",
            arguments={}, credential_data=_credential(credential_data), user_id="")
        if not isinstance(result, dict) or result.get("verified") is not True or result.get("protected_zone") is not True:
            raise RuntimeError("Websupport signed service access remains unverified.")
        return {"valid": True}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        if field_name != "record_type" or page_token is not None or context is not None and not isinstance(context, dict):
            raise ValueError("Use the current service's record-type selector; no service catalog or page input is available.")
        if search is not None and (not isinstance(search, str) or len(search) > 32 or re.search(r"[\x00-\x1f\x7f]|://", search)):
            raise ValueError("Use a bounded local record-type search.")
        _zone(await _request(data, "zone"), False)
        rows, _ = _records(await _request(data, "records"), False)
        values = list(dict.fromkeys(row["type"] for row in rows))
        return {"options": [{"value": value, "label": value} for value in values if search is None or search.casefold() in value.casefold()],
            "next_page_token": None, "completion": "unknown; current provider default page only"}
    async def execute(self, inputs):
        if not isinstance(self.config, WebsupportNodeConfig) or not self.config.credentials:
            raise ValueError("Websupport configuration and an existing bound key/secret are required.")
        raw = (self.node_data or {}).get("credentials")
        data = _credential(raw if isinstance(raw, dict) else self.config.credentials.model_dump(mode="json"))
        c, op = self.config.config, self.config.config.operation
        proof = "Protected saved-service DNS metadata reachability; no actor, tenant ownership or service/domain identity equivalence is inferred."
        if op == "check_connection":
            verification = await _request(data, "verify")
            if type(verification.get("verified")) is not bool:
                raise RuntimeError("Websupport returned an unsupported verification boolean.")
            if verification["verified"] is False:
                raise WebsupportVerificationDenied("Websupport authentication failed: verification returned false.")
            zone = _zone(await _request(data, "zone"), c.include_names)
            return {"verified": True, "protected_zone": True, "items": [zone], "proof": proof}
        zone = _zone(await _request(data, "zone"), c.include_names)
        if op == "get_zone":
            return {"zone": zone, "proof": proof}
        if op == "list_records":
            rows, counts = _records(await _request(data, "records"), c.include_names)
            matches = [row for row in rows if c.record_type is None or row["type"] == c.record_type]
            return {"items": matches[:c.max_items], "returned": min(len(matches), c.max_items), "provider_returned": len(rows),
                "local_truncated": len(matches) > c.max_items, "provider_page": counts,
                "count_scope": "Provider-reported current page and collection counts; page indexing is unspecified.",
                "completion": "unknown; current provider default page only", "proof": proof}
        raise ValueError("Unsupported Websupport metadata operation.")
