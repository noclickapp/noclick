"""Native BuiltWith domain technology lookup for the documented v26 API.
The credential is never tested by spending lookup credits at connect time.
Execution uses staging’s validated credential config and fixed-host transport.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import re
from typing import Annotated, ClassVar, Literal
from uuid import UUID

import httpx
from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt,
    StrictStr, TypeAdapter, field_validator, model_serializer, model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence


FAMILY = "builtwith_api_key"
ENDPOINT = "https://api.builtwith.com/v26/api.json"
MAX_BYTES = 16 * 1024 * 1024
DateValue = StrictInt | StrictStr | None
SourceValue = StrictBool | Literal["True", "False", "true", "false", "Misleading", "misleading"] | None
Text = Annotated[StrictStr, Field(max_length=16384)]
_in_request = ContextVar("builtwith_request_logging", default=False)


class _PrivateRequestFilter(logging.Filter):
    def filter(self, record):
        return not _in_request.get()


_filter = _PrivateRequestFilter()
for _logger_name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
    logging.getLogger(_logger_name).addFilter(_filter)


@contextmanager
def private_request_logging():
    token = _in_request.set(True)
    try:
        yield
    finally:
        _in_request.reset(token)


def domain_name(value):
    if not isinstance(value, str) or value != value.strip() or len(value) > 253:
        raise ValueError("Supply bare root domains, without URLs, paths or whitespace.")
    domain = value.lower()
    labels = domain.split(".")
    if (len(labels) < 2 or not re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]{2,59}", labels[-1])
            or labels[-1] in {"localhost", "local", "internal", "test", "invalid", "example", "onion"}
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", item) for item in labels)):
        raise ValueError("Supply a public bare root domain; URLs, IPs and local names are unsupported.")
    # A suffix registry is not guessed or fetched; the caller supplies the root.
    return domain


class _Projection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("FirstIndexed", "LastIndexed", "FirstDetected", "LastDetected", check_fields=False)
    @classmethod
    def check_detection_date(cls, value):
        if value is None or type(value) is int and 0 <= value <= 2**63 - 1:
            return value
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                return value
            except ValueError:
                pass
        raise ValueError("Invalid detection date.")


class Technology(_Projection):
    Name: Text = Field(min_length=1)
    Id: StrictInt | None = Field(None, ge=0)
    Parent: Text | None = None
    Description: Text | None = None
    Link: Text | None = None
    confidence: StrictFloat | StrictInt | None = Field(None, ge=0, le=1)
    IsPremium: Text | None = None
    Tag: Text | None = None
    Categories: list[Text] | None = Field(None, max_length=256)
    FirstDetected: DateValue = None
    LastDetected: DateValue = None


class TechnologyPath(_Projection):
    Domain: Text | None = None
    SubDomain: Text | None = None
    Url: Text | None = None
    FirstIndexed: DateValue = None
    LastIndexed: DateValue = None
    Technologies: list[Technology] = Field(max_length=5000)


class TechnologyResult(_Projection):
    Paths: list[TechnologyPath] = Field(max_length=2048)
    IsDB: SourceValue = None


class DomainResult(_Projection):
    Lookup: StrictStr
    Result: TechnologyResult
    IsDB: SourceValue = None
    FirstIndexed: DateValue = None
    LastIndexed: DateValue = None


def _source(value):
    if value is True or value in ("True", "true"):
        return "database"
    if value is False or value in ("False", "false"):
        return "website"
    if value in ("Misleading", "misleading"):
        return "misleading"
    return None


_REASONS = {
    -1: "Unsupported response type.", -2: "API key rejected.", -3: "Lookup credits exhausted.",
    -4: "Technology not found.", -5: "Plan upgrade required.", -6: "Provider could not save technology usage.",
    -7: "Provider permits one lookup for this endpoint.", -8: "Root domain is invalid or unsupported.",
    -99: "Provider internal error.",
}


def _safe_tree(value, secret):
    if isinstance(value, str):
        return re.sub(re.escape(secret), "[redacted]", value, flags=re.IGNORECASE)
    if isinstance(value, list):
        return [_safe_tree(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _safe_tree(item, secret) for key, item in value.items()}
    return value


def project_response(payload, domains, secret):
    """Preserve domain-specific failures and missing records instead of success padding."""
    try:
        if not isinstance(payload, dict):
            raise ValueError
        if "error" in payload:
            if payload.get("error") == "Rate limit exceeded":
                seconds = payload.get("retryAfterSeconds")
                hint = f" Retry after {seconds} seconds." if type(seconds) is int and 0 < seconds <= 86400 else ""
                raise _ProviderError("BuiltWith rate limit exceeded." + hint)
            raise _ProviderError("BuiltWith returned an error envelope.")
        errors = payload.get("Errors", [])
        if not isinstance(errors, list) or len(errors) > 64:
            raise ValueError
        failures = {}
        for error in errors:
            if not isinstance(error, dict) or type(error.get("Code")) is not int or abs(error["Code"]) > 2**31 - 1:
                raise ValueError
            code = error["Code"]
            if code == -2:
                raise _ProviderError("BuiltWith authentication failed: the API key was rejected.")
            lookup = error.get("Lookup")
            reason = _REASONS.get(code, "Provider returned an unrecognized error code.")
            if lookup is None:
                raise _ProviderError("BuiltWith lookup failed: " + reason)
            lookup = domain_name(lookup)
            if lookup not in domains or lookup in failures:
                raise ValueError
            failures[lookup] = {"code": code, "message": reason}
        raw_results = payload.get("Results")
        if not isinstance(raw_results, list) or len(raw_results) > len(domains):
            raise ValueError
        found, tech_count = {}, 0
        for raw in raw_results:
            if not isinstance(raw, dict):
                raise ValueError
            lookup = domain_name(raw.get("Lookup"))
            if lookup not in domains or lookup in found:
                raise ValueError
            if lookup in failures:
                found[lookup] = None
                continue
            row = DomainResult.model_validate(raw)
            for path in row.Result.Paths:
                if path.Domain not in (None, "") and domain_name(path.Domain) != lookup:
                    raise ValueError
                tech_count += len(path.Technologies)
                if tech_count > 100000:
                    raise ValueError
            inner = row.Result.IsDB
            outer = row.IsDB
            if inner is not None and outer is not None and _source(inner) != _source(outer):
                raise ValueError
            origin = inner if inner is not None else outer
            projected = row.model_dump(exclude_unset=True)
            # Never return metadata, attributes, contacts, sales/spend or extra provider fields.
            found[lookup] = {
                "lookup": lookup, "status": "ok", "lookup_source": _source(origin),
                "data": _safe_tree(projected, secret),
            }
        output = []
        for lookup in domains:
            if lookup in failures:
                output.append({"lookup": lookup, "status": "error", "error": failures[lookup]})
            elif found.get(lookup) is not None:
                output.append(found[lookup])
            else:
                output.append({"lookup": lookup, "status": "missing",
                    "message": "The response did not supply this requested lookup; no success is inferred."})
        successful = sum(row["status"] == "ok" for row in output)
        return {
            "status": "success" if successful == len(domains) else "partial" if successful else "error",
            "operation": "lookup_domain_technologies", "lookups": output,
            "requested_count": len(domains), "successful_count": successful,
            "error_count": sum(row["status"] == "error" for row in output),
            "missing_count": sum(row["status"] == "missing" for row in output),
            "protected_reachability_verified": True if successful else None,
            "principal_identity_verified": False, "account_identity_verified": False,
            "lookup_may_use_credits_and_visit_website": True,
        }
    except _ProviderError:
        raise
    except Exception:
        raise ValueError("BuiltWith returned an invalid or oversized domain technology response.") from None


class _ProviderError(ValueError):
    pass


def _retry_hint(value):
    try:
        seconds = int(value) if value.isdigit() else int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        return f" Retry after {seconds} seconds." if 0 < seconds <= 86400 else ""
    except (ValueError, TypeError, AttributeError, OverflowError):
        return ""


async def lookup_domains(config, credential):
    if any(credential["api_key"].lower() in value.lower() for value in config.domains):
        raise ValueError("A credential cannot be included in a BuiltWith lookup domain.")
    params = {"LOOKUP": ",".join(config.domains), "NOPII": "yes", "NOMETA": "yes", "NOATTR": "yes"}
    if config.live_only:
        params["LIVEONLY"] = "yes"
    if config.details == "no_description_links":
        params["HIDEDL"] = "yes"
    elif config.details == "names_only":
        params["HIDETEXT"] = "yes"
    for prefix, name in (("first_detected", "FDRANGE"), ("last_detected", "LDRANGE")):
        start, end = getattr(config, prefix + "_start"), getattr(config, prefix + "_end")
        if start is not None:
            params[name] = start + "|" + end
    try:
        with private_request_logging():
            async with httpx.AsyncClient(timeout=45.0, trust_env=False, follow_redirects=False) as client:
                async with client.stream("GET", ENDPOINT, params=params, headers={
                    "Authorization": "API " + credential["api_key"], "Accept": "application/json"}) as response:
                    if response.status_code in (401, 403):
                        raise ValueError("BuiltWith authentication failed (HTTP 401/403).")
                    if response.status_code == 429:
                        raise ValueError("BuiltWith rate limit exceeded (HTTP 429)." + _retry_hint(response.headers.get("Retry-After", "")))
                    if response.status_code != 200:
                        raise ValueError(f"BuiltWith lookup failed (HTTP {response.status_code}).")
                    media = response.headers.get("content-type", "").split(";")[0].lower().strip()
                    if media != "application/json" and not media.endswith("+json"):
                        raise ValueError("BuiltWith returned an unexpected response media type.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise ValueError("BuiltWith domain response exceeds the native 16 MiB limit.")
                    try:
                        payload = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError):
                        raise ValueError("BuiltWith returned malformed JSON.") from None
        result = project_response(payload, config.domains, credential["api_key"])
        return result
    except httpx.HTTPError:
        raise ValueError("BuiltWith lookup transport failed; no automatic retry was made.") from None


class BuiltWithApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="BuiltWith API Key", extra="ignore", json_schema_extra={
        "x-credential-url": "https://api.builtwith.com/domain-api",
        "x-credential-instructions": "Use an existing BuiltWith API key. Connecting saves it unverified without a credit-consuming lookup. An explicit domain lookup uses credits and may visit the website.",
    })
    credential_type: Literal["builtwith_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: StrictStr = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def check_api_key(cls, value):
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value) or UUID(value).int == 0:
            raise ValueError("Supply an existing BuiltWith GUID API key.")
        return value

    @model_serializer(mode="wrap")
    def emit_credential_type(self, handler):
        result = handler(self)
        result["credential_type"] = FAMILY
        return result


def validate_credential(data):
    if not isinstance(data, dict) or data.get("credential_type") not in (None, FAMILY):
        raise ValueError("A BuiltWith API key credential is required.")
    try:
        return BuiltWithApiKeyCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("The BuiltWith API key credential is invalid.") from None


class LookupDomainTechnologies(BaseModel):
    model_config = ConfigDict(extra="ignore")
    operation: Literal["lookup_domain_technologies"] = Field(
        "lookup_domain_technologies", json_schema_extra={"const": "lookup_domain_technologies", "ui:hidden": True})
    domains: list[StrictStr] = Field(..., min_length=1, max_length=16, title="Root Domains",
        description="1–16 public root domains, such as example.com. Supply the root yourself; subdomains are not converted. Each lookup consumes credits and may visit the website.")
    live_only: StrictBool = Field(False, title="Live Technologies Only",
        description="Uses BuiltWith LIVEONLY. Without it, historical detections can also be returned.")
    details: Literal["full", "no_description_links", "names_only"] = Field("full", title="Technology Details",
        description="Full details; omit descriptions and links with HIDEDL; or omit description, link, tag and categories with HIDETEXT.")
    first_detected_start: StrictStr | None = Field(None, title="First Detected From", description="YYYY-MM-DD; supply both range dates.")
    first_detected_end: StrictStr | None = Field(None, title="First Detected Through", description="YYYY-MM-DD.")
    last_detected_start: StrictStr | None = Field(None, title="Last Detected From", description="YYYY-MM-DD; supply both range dates.")
    last_detected_end: StrictStr | None = Field(None, title="Last Detected Through", description="YYYY-MM-DD.")

    @field_validator("domains")
    @classmethod
    def check_domains(cls, values):
        result = [domain_name(value) for value in values]
        if len(set(result)) != len(result):
            raise ValueError("Supply each root domain once.")
        return result

    @field_validator("first_detected_start", "first_detected_end", "last_detected_start", "last_detected_end")
    @classmethod
    def check_date_value(cls, value):
        if value is not None:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                raise ValueError("Use a real YYYY-MM-DD date.") from None
        return value

    @model_validator(mode="after")
    def check_date_ranges(self):
        for prefix in ("first_detected", "last_detected"):
            start, end = getattr(self, prefix + "_start"), getattr(self, prefix + "_end")
            if (start is None) != (end is None) or (start is not None and start > end):
                raise ValueError("Supply both dates of each range in chronological order.")
        return self


class BuiltWithFullConfig(NodeConfig[LookupDomainTechnologies, BuiltWithApiKeyCredential]):
    pass


class BuiltWithNode(WorkflowNode):
    integration_type = "automation-builtwith"
    agent_tool_provider = True
    # The named config field is handled locally, without a dynamic picker or
    # provider probe. A lookup is an explicit credit-consuming user action.
    connection_evidence: ClassVar[ConnectionEvidence] = ConnectionEvidence(
        noun="domain technology lookups", field="domains", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BuiltWithFullConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials") is not None:
            validate_credential(config_data["credentials"])
        try:
            return TypeAdapter(BuiltWithFullConfig).validate_python(runtime_config_view(config_data, BuiltWithFullConfig))
        except Exception:
            raise ValueError("BuiltWith configuration is invalid. Supply 1–16 root domains and valid paired date ranges.") from None

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, **kwargs):
        if field_name != "domains":
            raise ValueError("BuiltWith has no dynamic field options.")
        validate_credential(credential_data)
        raise ValueError("BuiltWith connection is unverified: no automatic lookup is made because domain lookups consume credits. Run an explicit domain lookup to check protected reachability.")

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        validate_credential(credential_data)
        return {"valid": None, "error": "Unverified: BuiltWith has no automatic credit-free domain credential probe."}

    async def execute(self, inputs):
        if not isinstance(self.config, BuiltWithFullConfig):
            raise ValueError("A valid BuiltWith configuration is required.")
        if self.config.credentials is None:
            raise ValueError("Connect a BuiltWith API key in the credentials tab.")
        credential = validate_credential(self.config.credentials.model_dump())
        return await lookup_domains(self.config.config, credential)
