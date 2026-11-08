"""DNS Made Easy metadata, signed using existing environment-bound credentials.

Only the three documented managed-DNS GET routes are declared. DNS values,
delegation, monitoring, credentials and configuration never enter node output.
"""
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Annotated, Any, Dict, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

HOSTS = {"production": "https://api.dnsmadeeasy.com/V2.0", "sandbox": "https://api.sandbox.dnsmadeeasy.com/V2.0"}
MAX_BYTES, MAX_ROWS, MAX_PAGE, MAX_INTEGER = 2 * 1024 * 1024, 100, 1000, 2**53 - 1
RecordType = Literal["A", "AAAA", "CNAME", "HTTPRED", "MX", "NS", "PTR", "SRV", "TXT"]
RECORD_TYPES = set(RecordType.__args__)


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INTEGER: raise ValueError("Expected a bounded exact metadata integer")
    return value


def _id(value):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,15}", value): value = int(value)
    return _integer(value, 1)


def _page(value):
    if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]{0,3})", value): value = int(value)
    if type(value) is not int or not 0 <= value <= MAX_PAGE: raise ValueError("Use an explicit bounded zero-based page")
    return value


def _text(value, limit=255, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use bounded text without control characters")
    if re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("URLs are outside metadata output")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected the documented JSON object")
    return value


class DNSMadeEasyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="DNS Made Easy API Key and Secret", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://api-docs.dnsmadeeasy.com/", "x-credential-instructions": "Supply existing issued API key and secret, explicit production or sandbox environment, and independently known accessible managed domain ID. Sandbox requires its own separately issued keys; no fallback or cross-environment retry. Business/Corporate API entitlement and permissions remain unverified. Protected catalog access is reachability, not actor/account ownership. No key issue, login, exchange or rotation."})
    credential_type: Literal["dnsmadeeasy_api_key"] = Field("dnsmadeeasy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, title="Existing API Key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., repr=False, title="Existing API Secret", json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field(..., title="Issued-Key Environment", description="Explicit fixed host selection. Production and sandbox need separate credentials; no automatic fallback.")
    domain_id: int = Field(..., title="Independently Known Managed Domain ID", description="One positive exact integer ID already accessible in the default protected catalog.")
    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply the raw issued key/secret without prefixes or whitespace")
        return clean_secret(value, field_name="DNS Made Easy credential")
    @field_validator("domain_id", mode="before")
    @classmethod
    def domain(cls, value): return _id(value)


def _credential(raw):
    if isinstance(raw, DNSMadeEasyAPIKeyCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "dnsmadeeasy_api_key": raise ValueError("Select the actual DNS Made Easy API key and secret family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) - {"credential_type", "api_key", "api_secret", "environment", "domain_id"} or raw.get("environment") not in HOSTS: raise ValueError("Unsupported key/environment binding; no arbitrary host, Bearer or refresh grant")
    try: return DNSMadeEasyAPIKeyCredential.model_validate(raw)
    except Exception: raise ValueError("DNS Made Easy key/secret/environment/domain binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, load):
        super().__init__(data)
        self.load = load
        self.anchor = _stored(data)

    async def reload(self):
        try:
            if _stored(await self.load()) != self.anchor:
                raise ValueError()
        except Exception:
            raise ValueError("DNS Made Easy current saved key/secret/environment/domain or access changed") from None

    def __repr__(self): return "<DNS Made Easy current credential>"


def _signed_headers(key, now=None):
    # Fresh UTC HTTP date for every request; exact ASCII date bytes, lowercase hex.
    date = format_datetime(now if now is not None else datetime.now(timezone.utc), usegmt=True)
    signature = hmac.new(key.api_secret.encode("utf-8"), date.encode("ascii"), hashlib.sha1).hexdigest()
    return {"x-dnsme-apiKey": key.api_key, "x-dnsme-requestDate": date, "x-dnsme-hmac": signature, "Accept": "application/json", "Content-Type": "application/json"}


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "DNS Made Easy Metadata", "x-is-trigger": False})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Domain and Record Names", description="Opt in to names. All record values/RDATA, URLs and configuration remain omitted.")


class _Domain(_Config):
    domain_id: int = Field(..., title="Current Credential-bound Domain", json_schema_extra={"x-resource-type": "domain_id", "x-dynamic-options": {"field_name": "domain_id", "allow_custom": True}})
    @field_validator("domain_id", mode="before")
    @classmethod
    def validate_domain(cls, value): return _id(value)


class DNSMadeEasyDomainsConfig(_Config):
    operation: Literal["list_domains"] = _op("list_domains", "Read Protected Managed Domain Catalog")
class DNSMadeEasyDomainConfig(_Domain):
    operation: Literal["get_domain"] = _op("get_domain", "Get Managed Domain Metadata")
class DNSMadeEasyRecordsConfig(_Domain):
    operation: Literal["list_records"] = _op("list_records", "Read Domain DNS Record Metadata")
    rows: int = Field(20, ge=1, le=MAX_ROWS, strict=True, title="Rows", description="Explicit local bound 1–100; not a documented vendor maximum.")
    page: int = Field(0, ge=0, le=MAX_PAGE, strict=True, title="Page", description="Published examples start at page0. Explicit local bound; no auto-pagination or completion inference.")
    record_type: RecordType | None = Field(None, title="Record Type Filter", description="Only documented types; sent as the published type query parameter.")


DNSMadeEasyOperation = Annotated[Union[DNSMadeEasyDomainsConfig, DNSMadeEasyDomainConfig, DNSMadeEasyRecordsConfig], Field(discriminator="operation")]
class DNSMadeEasyNodeConfig(NodeConfig[DNSMadeEasyOperation, DNSMadeEasyAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _domain(raw, names=False):
    row = _object(raw); out = {"resource_type": "managed_domain", "id": _integer(row.get("id"), 1)}
    if names and "name" in row: out["name"] = _text(row["name"])
    # Timestamp units are not established; created/updated are not converted/copied.
    return out


def _record(raw, names=False):
    row = _object(raw); kind = row.get("type")
    if not isinstance(kind, str) or kind not in RECORD_TYPES: raise ValueError("Unsupported published DNS record type")
    out = {"resource_type": "dns_record", "id": _integer(row.get("id"), 1), "type": kind}
    if "ttl" in row: out["ttl"] = _integer(row["ttl"])
    if names and "name" in row: out["name"] = _text(row["name"], empty=True)
    return out


def _wrapper(raw, bound, requested_page=None):
    row = _object(raw); data = row.get("data")
    if not isinstance(data, list) or len(data) > bound: raise ValueError("Expected the bounded published data array")
    page = _integer(row.get("page")); total_pages = _integer(row.get("totalPages")); total_records = _integer(row.get("totalRecords"))
    if requested_page is not None and page != requested_page: raise ValueError("Returned page differs from selected records page")
    return data, {"provider_page": page, "provider_total_pages": total_pages, "provider_total_records": total_records, "provider_count_scope": "unspecified", "returned_count": len(data), "has_more": None, "next_page": None, "pagination_complete": None}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, action): self.raw, self.key, self.action, self.attempted, self.status = raw, _credential(raw), action, False, None
    def error(self, message): return {"status": "error", "action": self.action, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, kind, *, rows=20, page=0, record_type=None):
        params = {}
        if kind == "domains": path = "/dns/managed/"  # Exact published collection example.
        elif kind == "domain": path = f"/dns/managed/{self.key.domain_id}"
        elif kind == "records":
            path = f"/dns/managed/{self.key.domain_id}/records"
            if type(rows) is not int or not 1 <= rows <= MAX_ROWS: raise ValueError("Unsupported explicit row bound")
            params.update(rows=str(rows), page=str(_page(page)))
            if record_type is not None:
                if record_type not in RECORD_TYPES: raise ValueError("Closed published type filter required")
                params["type"] = record_type
        else: raise ValueError("Closed native metadata route required")
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                # Signing values remain private; never include them in output/error.
                async with client.stream("GET", HOSTS[key.environment] + path, params=params, headers=_signed_headers(key)) as response:
                    self.status = response.status_code; content_type = response.headers.get("content-type", ""); body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("DNS Made Easy response exceeds local bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200: raise _ProviderError(self.error("DNS Made Easy protected read could not be verified. HTTP403 can mean invalid credentials or request date; access verdict unknown. Private provider text omitted; no retry or environment fallback"))
            if "application/json" not in content_type.lower(): raise ValueError("Expected the published JSON response")
            return json.loads(body)
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("DNS Made Easy transport outcome unknown; no retry or environment fallback")) from None
    async def parents(self):
        rows, _ = _wrapper(await self.request("domains"), MAX_ROWS)
        domains = [_domain(row)["id"] for row in rows]
        if len(set(domains)) != len(domains) or self.key.domain_id not in domains: raise ValueError("Known domain not established in bounded default catalog; no absence/ownership claim")
        domain = _domain(await self.request("domain"))
        if domain["id"] != self.key.domain_id: raise ValueError("Selected managed domain detail differs")


class DNSMadeEasyNode(WorkflowNode):
    integration_type = "automation-dnsmadeeasy"
    connection_evidence = ConnectionEvidence(operation="list_domains", noun="DNS Made Easy protected domain catalog", proves="reachability")
    edit_examples = ["Read metadata for my known DNS Made Easy domain without DNS values", "Read record IDs, types and TTLs without failover or configuration", "Read one explicit records page, not a complete DNS export"]
    @classmethod
    def get_config_model(cls): return DNSMadeEasyNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._resolve_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )
    @classmethod
    async def _resolve_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        initial = _stored(credential_data)
        if not credential_id:
            return credential_data

        async def load():
            from nodes.core.run_op import resolve_operation_credential

            return await resolve_operation_credential(
                credential_id, user_id, pool, organization_id, workflow_id,
            )

        try:
            current = await load()
            if _stored(current) != initial:
                raise ValueError()
            return _CurrentCredential(current, load)
        except Exception:
            raise ValueError("DNS Made Easy saved API key unavailable under current access") from None
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            if hasattr(config, "domain_id") and config.domain_id != session.key.domain_id: raise ValueError("Selected domain differs from current credential binding")
            await session.parents()
            if config.operation == "list_domains":
                raw_rows, counts = _wrapper(await session.request("domains"), MAX_ROWS)
                data = [_domain(row, config.include_names) for row in raw_rows]
            elif config.operation == "get_domain":
                data = _domain(await session.request("domain"), config.include_names); counts = {}
                if data["id"] != session.key.domain_id: raise ValueError("Returned managed domain differs")
            elif config.operation == "list_records":
                raw_rows, counts = _wrapper(await session.request("records", rows=config.rows, page=config.page, record_type=config.record_type), config.rows, config.page)
                data = [_record(row, config.include_names) for row in raw_rows]
                if config.record_type is not None and any(row["type"] != config.record_type for row in data): raise ValueError("Records cross selected type filter")
                counts.update(requested_rows=config.rows, requested_page=config.page)
            else: raise ValueError("Closed native operation required")
            if isinstance(data, list) and len({row["id"] for row in data}) != len(data): raise ValueError("Duplicate metadata IDs")
            status = session.status
            await session.parents()
            out = {"data": data, **counts}
            rendered = json.dumps(out, ensure_ascii=False, allow_nan=False)
            if session.key.api_key in rendered or session.key.api_secret in rendered: raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "account_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current credentials/environment/domain ancestry or bounded published metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        key = _credential(credential_data); context = context or {}
        if field_name != "domain_id" or page_token is not None: raise ValueError("Only the default protected domain catalog picker is documented; no catalog paging")
        names = context.get("include_names", False)
        if type(names) is not bool: raise ValueError("Explicit names opt-in required")
        if search is not None: _text(search, 100)
        if context.get("domain_id") is not None and _id(context["domain_id"]) != key.domain_id: raise ValueError("Picker differs from current credential domain")
        result = await cls._dispatch(credential_data, DNSMadeEasyDomainsConfig(include_names=names))
        if result.get("status") != "success": raise ValueError(result["error"])
        selected = [row for row in result["data"] if row["id"] == key.domain_id]
        options = [{"value": str(row["id"]), "label": row.get("name") or str(row["id"]), "metadata": {"resource_type": "managed_domain", "credential_bound": True}} for row in selected]
        return {"options": [row for row in options if not search or search.casefold() in row["label"].casefold()], "has_more": None, "next_page_token": None, "pagination_complete": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        credential = await self._resolve_current_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
