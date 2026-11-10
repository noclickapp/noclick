"""Native Dropcontact asynchronous B2B enrichment and documented credit probe."""
from __future__ import annotations
import base64
import json
import logging
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-dropcontact"
FAMILIES = ("dropcontact_access_token",)
BASE = "https://api.dropcontact.com/v1/enrich/all"
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
MAX_CONTACTS = 250
MAX_CONTACT_BYTES = 15000
NOT_READY = "Request not ready yet, try again in 30 seconds"
CONTACT_FIELDS = ("email", "first_name", "last_name", "full_name", "phone", "company", "website", "num_siren", "linkedin", "siret", "country", "job", "company_linkedin")
COMPANY_FIELDS = ("company", "website", "company_linkedin", "num_siren", "siret")
WRITE_OPS = ("enrich_contact", "enrich_batch")


def _token(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("Supply the existing opaque Dropcontact API access token within the local text bound")
    return value


def _request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Supply the exact existing request ID using the local path-safe ASCII subset")
    return value


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,3}", value): value = int(value)
    if type(value) is not int: raise ValueError("Supply a whole numeric count")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError("Supply nonempty contact text; omit unused fields")
    return value


class DropcontactAccessTokenCredential(BaseModel):
    credential_type: Literal["dropcontact_access_token"] = Field("dropcontact_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Existing API Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-credential-url": "https://www.dropcontact.com/help/how-to-use-the-api-key",
        "x-credential-instructions": "Supply an existing issued Dropcontact API token. Exact X-Access-Token header on fixed https://api.dropcontact.com/v1/enrich/all; no Bearer, query token, SDK/MCP/OAuth, key issuance or environment fallback. Protected POST with exactly data:[{}] is the documented no-credit-consumption probe. It proves key reachability and reported credits, not account/principal identity, enrichment permissions, account age or a free plan. Enrichment can consume existing credits; no live enrichment or paid plan is authorized by source preparation. Current stricter company-context/unknown-field rules govern closed payloads.",
    })
    _native_token = field_validator("access_token")(_token)


def _op(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


class DropcontactOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ContactFields(BaseModel):
    email: Optional[str] = Field(None, max_length=4096)
    first_name: Optional[str] = Field(None, max_length=4096)
    last_name: Optional[str] = Field(None, max_length=4096)
    full_name: Optional[str] = Field(None, max_length=4096)
    phone: Optional[str] = Field(None, max_length=4096)
    company: Optional[str] = Field(None, max_length=4096)
    website: Optional[str] = Field(None, max_length=4096)
    num_siren: Optional[str] = Field(None, max_length=4096)
    linkedin: Optional[str] = Field(None, max_length=4096)
    siret: Optional[str] = Field(None, max_length=4096)
    country: Optional[str] = Field(None, max_length=4096)
    job: Optional[str] = Field(None, max_length=4096)
    company_linkedin: Optional[str] = Field(None, max_length=4096)
    model_config = ConfigDict(extra="forbid")
    @field_validator(*CONTACT_FIELDS)
    @classmethod
    def strings(cls, value): return _text(value) if value is not None else None
    @model_validator(mode="after")
    def context_and_identity(self):
        if not any(getattr(self, field) for field in COMPANY_FIELDS):
            raise ValueError("Current B2B enrichment requires company context: company, website, company_linkedin, num_siren or siret")
        if not (self.email or self.linkedin or self.full_name or self.first_name and self.last_name):
            raise ValueError("Supply email, LinkedIn URL, full name or first plus last name with company context; organization-only legal-representative enrichment is outside this native subset")
        return self


class _Contact(_ContactFields):
    custom_fields: Optional[Dict[str, str]] = None


class DropcontactEnrichmentOptions(DropcontactOperation):
    siren: bool = Field(False, description="Request documented French company information; availability is provider-dependent.")
    language: Literal["en", "fr"] = Field("en", description="English sends language=en; French omits language and uses the documented provider default.")
    confirm_existing_credits: bool = Field(False, description="Confirm processing owned B2B contacts with existing credits. Verification/enrichment may consume credits; no purchase, immediate refund or silent webhook-effect guarantee.")


class DropcontactCheckConfig(DropcontactOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Key with Free Credit Probe", "Connection")


class DropcontactCreditsConfig(DropcontactOperation):
    operation: Literal["get_credits"] = _op("get_credits", "Get Remaining Credits", "Connection")


class DropcontactEnrichContactConfig(DropcontactEnrichmentOptions, _ContactFields):
    operation: Literal["enrich_contact"] = _op("enrich_contact", "Submit Owned B2B Contact", "Enrichment")
    custom_fields_json: Optional[str] = Field(None, max_length=MAX_BYTES, title="Custom Fields (JSON)", description="Optional dictionary of strings preserved by the API; no nested values, callbacks or arbitrary request fields.", json_schema_extra={"ui:widget": "textarea"})
    @model_validator(mode="after")
    def bounded_contact(self):
        _single_contact(self)
        return self


class DropcontactEnrichBatchConfig(DropcontactEnrichmentOptions):
    operation: Literal["enrich_batch"] = _op("enrich_batch", "Submit Owned B2B Batch", "Enrichment")
    contacts_json: str = Field(..., max_length=MAX_BYTES, title="Contacts (JSON Array)", description="1–250 closed supported contact objects, each exact compact on-wire UTF8 JSON below 15000 bytes. Every contact requires company context and a supported contact identity combination.", json_schema_extra={"ui:widget": "textarea"})
    @field_validator("contacts_json")
    @classmethod
    def contacts(cls, value):
        _contacts_json(value)
        return value


class DropcontactRequestScope(DropcontactOperation):
    request_id: str = Field(..., title="Existing Request ID", description="Exact returned or supplied request ID. Lookup checks that one protected route; the API has no documented history list. No original-submission ancestry is inferred.", json_schema_extra={"x-dynamic-options": {"field_name": "request_id", "searchable": True, "allow_custom": True, "placeholder": "Paste the full existing request ID", "custom_placeholder": "Exact existing request ID"}, "x-resource-type": "dropcontact_request", "x-resource-id-path": "request_id"})
    expected_contact_count: Optional[int] = Field(None, ge=1, le=250, description="Optional caller-known batch size. Reports missing response rows without inventing IDs, original order or submission ancestry.")
    _existing_id = field_validator("request_id")(_request_id)
    @field_validator("expected_contact_count", mode="before")
    @classmethod
    def count(cls, value): return _whole(value) if value is not None else None


class DropcontactGetStatusConfig(DropcontactRequestScope):
    operation: Literal["get_status"] = _op("get_status", "Read Existing Enrichment Status Once", "Results")


class DropcontactGetResultsConfig(DropcontactRequestScope):
    operation: Literal["get_results"] = _op("get_results", "Read Existing Enrichment Results Once", "Results")
    include_contact_data: bool = Field(False, description="Opt in to private supported contact/company result fields; no unknown output fields or raw diagnostics.")
    include_custom_fields: bool = Field(False, description="Opt in to returned string custom fields, which can contain private data; omitted by default.")


DropcontactConfig = Annotated[Union[DropcontactCheckConfig, DropcontactCreditsConfig, DropcontactEnrichContactConfig, DropcontactEnrichBatchConfig, DropcontactGetStatusConfig, DropcontactGetResultsConfig], Field(discriminator="operation")]


class DropcontactNodeConfig(NodeConfig[DropcontactConfig, DropcontactAccessTokenCredential]):
    pass


class DropcontactAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES:
        raise ValueError("Dropcontact credential family is unsupported")
    try:
        shaped = DropcontactAccessTokenCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except Exception:
        raise ValueError("Dropcontact native credential is invalid") from None
    return {**data, **shaped}


def _binding(data):
    return (data["credential_type"], data["access_token"])


def _bound_matches(bound, current):
    return _binding(bound) == _binding(current)


def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("Dropcontact configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("Dropcontact saved credential family is missing or unsupported")


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


async def _current_data(data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
    if not credential_id:
        return _shape(data)
    from utils.credentials import resolve_credential_with_owner_fallback
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    result = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id,
    )
    if not isinstance(result, dict) or result.get("credential_type") not in FAMILIES:
        raise ValueError("Dropcontact current credential is unavailable or access denied")
    return {**_shape(result), "_dropcontact_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_dropcontact_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("Dropcontact picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id})
    return result


def _authority(context):
    return {"pool": context.get("_approval_pool"), "user_id": context.get("_user_id"), "credential_id": context.get("_credential_id"), "organization_id": context.get("_organization_id"), "workflow_id": context.get("_workflow_id")}


def _bounded(value, depth=0):
    if type(value) is int and value.bit_length() > 256:
        raise ValueError("Unverified JSON integer bound")
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("dropcontact_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "Dropcontact private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


def _protect_transport_logs():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict) if name.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)

def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _parse_json(text):
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
            raise ValueError()
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _bounded(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Dropcontact JSON input must be finite, unambiguous and within local byte/depth bounds") from None


def _custom_fields(value):
    if not isinstance(value, dict) or len(value) > 50 or any(not isinstance(k, str) or not 1 <= len(k) <= 128 or '\x00' in k or not isinstance(v, str) or len(v) > 4096 or '\x00' in v for k, v in value.items()):
        raise ValueError("Dropcontact custom_fields must be a bounded dictionary of strings")
    return value


def _contact(raw):
    if not isinstance(raw, dict) or any(v is None for v in raw.values()):
        raise ValueError("Dropcontact contact entries require supported string fields; omit unused fields rather than null")
    try:
        item = _Contact.model_validate(raw).model_dump(exclude_none=True)
    except ValueError:
        raise ValueError("Dropcontact contact contains an unsupported field, value or B2B identity/company combination") from None
    if "custom_fields" in raw:
        item["custom_fields"] = _custom_fields(raw["custom_fields"])
    if len(_json(item)) >= MAX_CONTACT_BYTES:
        raise ValueError("Every Dropcontact contact must serialize to fewer than 15000 UTF8 bytes on the wire")
    return item


def _single_contact(cfg):
    item = {field: getattr(cfg, field) for field in CONTACT_FIELDS if getattr(cfg, field) is not None}
    if cfg.custom_fields_json is not None and cfg.custom_fields_json.strip():
        item["custom_fields"] = _custom_fields(_parse_json(cfg.custom_fields_json))
    return _contact(item)


def _contacts_json(text):
    value = _parse_json(text)
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CONTACTS:
        raise ValueError("Supply 1–250 Dropcontact contacts as a JSON array")
    return [_contact(item) for item in value]


async def _stable(data, context):
    try:
        current = await _current_data(data, **_authority(context))
    except ValueError:
        raise DropcontactAPIError("Dropcontact current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data):
        raise DropcontactAPIError("Dropcontact current credential changed; result is not accepted", authority_rejected=True)
    return current


async def _request(data, context, method, *, request_id=None, contacts=None, probe=False, siren=False, language="en"):
    if method == "GET":
        url = BASE + "/" + _request_id(request_id)
        if contacts is not None or probe: raise ValueError("Unsupported Dropcontact result request")
        content = None
    elif method == "POST" and request_id is None:
        if probe:
            if contacts is not None: raise ValueError("Credit probe cannot contain enrichment data")
            payload = {"data": [{}]}
        else:
            if not isinstance(contacts, list) or not 1 <= len(contacts) <= MAX_CONTACTS or type(siren) is not bool or language not in ("en", "fr"):
                raise ValueError("Unsupported Dropcontact enrichment request")
            payload = {"data": [_contact(item) for item in contacts], "siren": siren}
            if language == "en": payload["language"] = "en"
        content = _json(payload)
        if len(content) > MAX_BYTES: raise ValueError("Dropcontact batch exceeds the local request byte bound")
        url = BASE
    else:
        raise ValueError("Unsupported native Dropcontact method")
    current = await _stable(data, context)
    headers = {"X-Access-Token": current["access_token"], "Accept": "application/json"}
    if content is not None: headers["Content-Type"] = "application/json"
    uncertainty = "; processing and credit effects may have begun; inspect the original request independently without replay" if method == "POST" and not probe else ""
    _protect_transport_logs()
    private_token = _PRIVATE_REQUEST.set(True)
    try:
        async with guarded_async_client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, content=content, headers=headers) as response:
                status = response.status_code
                if status == 401: raise DropcontactAPIError("Dropcontact rejected the API access token (HTTP401)" + uncertainty, authority_rejected=True)
                if status == 403: raise DropcontactAPIError("Dropcontact refused the operation because the API token quota was exceeded (HTTP403)" + uncertainty, authority_rejected=True)
                if not 200 <= status < 300:
                    raise DropcontactAPIError("Dropcontact returned HTTP" + str(status) + "; operation result is unverified" + uncertainty)
                chunks = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_BYTES: raise DropcontactAPIError("Dropcontact response exceeds its local byte bound" + uncertainty)
                ctype = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if ctype != "application/json": raise DropcontactAPIError("Dropcontact response is not documented JSON" + uncertainty)
                try:
                    raw = json.loads(chunks, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(raw)
                    raw = _redact(raw, current["access_token"])
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise DropcontactAPIError("Dropcontact response JSON is unverified" + uncertainty) from None
        # A long response cannot turn stale owner/ACL/token/grant authority into
        # accepted results. Revalidate again before any native output/proof.
        await _stable(data, context)
        return raw
    except DropcontactAPIError:
        raise
    except Exception:
        raise DropcontactAPIError("Dropcontact transport did not establish an operation result" + uncertainty) from None
    finally:
        _PRIVATE_REQUEST.reset(private_token)


def _diagnostics(value, *, warning=False):
    if not isinstance(value, dict): raise DropcontactAPIError("Dropcontact row diagnostics shape is unverified")
    output = {}
    for key in (("empty_field", "only_organization_data") if warning else ("unexpected_field", "only_contact_data")):
        if key not in value: continue
        item = value[key]
        if key.endswith("_data"):
            if type(item) is not bool: raise DropcontactAPIError("Dropcontact row diagnostic flag is unverified")
            output[key] = item
        else:
            if not isinstance(item, list) or len(item) > MAX_ROWS or any(not isinstance(v, str) or len(v) > 512 for v in item):
                raise DropcontactAPIError("Dropcontact row diagnostic field list is unverified")
            recognized = [v for v in item if v in (*CONTACT_FIELDS, "custom_fields")]
            output[key] = {"count": len(item), "supported_fields": recognized, "unknown_field_count": len(item) - len(recognized)}
    if set(value) - set(output): output["unknown_diagnostics_omitted"] = True
    return output


_OUTPUT_TEXT = (*CONTACT_FIELDS, "civility", "mobile_phone", "siren", "siret_address", "vat", "nb_employees", "naf5_code", "naf5_des", "industry", "siret_zip", "siret_city", "employee_count", "company_turnover", "company_results", "job_level", "job_function")


def _row(raw, position, *, expected_count=None, contact_data=False, custom_fields=False):
    if not isinstance(raw, dict): raise DropcontactAPIError("Dropcontact result row is unverified")
    result = {"response_position": position, "contact_fields_omitted": not contact_data, "custom_fields_omitted": not custom_fields}
    if "index" in raw:
        if type(raw["index"]) is not int or not 0 <= raw["index"] < MAX_CONTACTS or expected_count is not None and raw["index"] >= expected_count:
            raise DropcontactAPIError("Dropcontact returned row index is outside the supplied batch-size scope")
        result["provider_index"] = raw["index"]
    for field in ("errors", "warnings"):
        if field in raw: result[field] = _diagnostics(raw[field], warning=field == "warnings")
    if "custom_fields" in raw:
        try: values = _custom_fields(raw["custom_fields"])
        except ValueError: raise DropcontactAPIError("Dropcontact returned custom field types are unverified") from None
        result["custom_fields_count"] = len(values)
        if custom_fields: result["custom_fields"] = values
    if contact_data:
        for field in _OUTPUT_TEXT:
            if field not in raw: continue
            value = raw[field]
            if field == "email" and isinstance(value, list):
                if len(value) > 50: raise DropcontactAPIError("Dropcontact email result count is unverified")
                rows = []
                for email in value:
                    if not isinstance(email, dict) or not isinstance(email.get("email"), str) or len(email["email"]) > 4096 or not isinstance(email.get("qualification"), str) or len(email["qualification"]) > 256:
                        raise DropcontactAPIError("Dropcontact email/qualification result is unverified")
                    rows.append({"email": email["email"], "qualification": email["qualification"]})
                result[field] = rows
            elif isinstance(value, str) and len(value) <= 4096:
                result[field] = value
            else:
                raise DropcontactAPIError("Dropcontact returned supported contact field type is unverified")
    return result


def _result(raw, *, submitting=False, request_id=None, expected_count=None, contact_data=False, custom_fields=False, probe=False):
    if not isinstance(raw, dict) or type(raw.get("error")) is not bool or type(raw.get("success")) is not bool or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
        raise DropcontactAPIError("Dropcontact documented error/success envelope is unverified")
    error, success = raw["error"], raw["success"]
    if error and success: raise DropcontactAPIError("Dropcontact returned inconsistent error/success flags")
    state = "failed" if error else "accepted" if submitting and success else "completed" if success else "processing"
    if not error and not success and (submitting or raw.get("reason") != NOT_READY):
        raise DropcontactAPIError("Dropcontact asynchronous processing state is unverified")
    output = {"state": state, "error": error, "success": success, "account_identity_verified": False, "submission_ancestry_verified": False, "automatic_polling": False, "raw_diagnostics_omitted": True}
    if "credits_left" in raw:
        value = raw["credits_left"]
        if type(value) is not int or not 0 <= value <= 9007199254740991: raise DropcontactAPIError("Dropcontact reported remaining credits are unverified")
        output["credits_left"] = value
    if "request_id" in raw:
        try: returned_id = _request_id(raw["request_id"])
        except ValueError: raise DropcontactAPIError("Dropcontact returned request ID is unverified") from None
        if request_id is not None and request_id != returned_id: raise DropcontactAPIError("Dropcontact returned another request ID")
        output["request_id"] = returned_id
        output["returned_request_id_verified"] = True
    elif submitting and success:
        raise DropcontactAPIError("Dropcontact accepted receipt lacks a documented request ID")
    else:
        output["returned_request_id_verified"] = False
    if request_id is not None:
        output["requested_request_id"] = request_id
        output["request_scope_source"] = "protected_exact_request_route"
    if probe:
        if error or not success or "credits_left" not in output or "request_id" not in output:
            raise DropcontactAPIError("Dropcontact protected no-credit-consumption probe was not verified")
        output.update({"protected_read_completed": True, "probe_contract": "exact_data_one_empty_object", "credit_consumption_contract": "documented_none_for_probe_only", "enrichment_permissions_verified": False, "results": [{"credits_left": output["credits_left"]}]})
    if "data" in raw:
        if not isinstance(raw["data"], list) or len(raw["data"]) > MAX_CONTACTS or expected_count is not None and len(raw["data"]) > expected_count:
            raise DropcontactAPIError("Dropcontact data row count or shape is unverified")
        rows = [_row(row, position, expected_count=expected_count, contact_data=contact_data, custom_fields=custom_fields) for position, row in enumerate(raw["data"])]
        indices = [row["provider_index"] for row in rows if "provider_index" in row]
        if len(set(indices)) != len(indices): raise DropcontactAPIError("Dropcontact returned duplicate provider row indices")
        output.update({"data": rows, "response_row_count": len(rows), "original_input_order_verified": False})
        if expected_count is not None:
            output["expected_contact_count"] = expected_count
            output["missing_response_row_count"] = expected_count - len(rows)
            output["expected_count_source"] = "current_submission_input" if submitting else "caller_supplied_expectation"
        output["complete_record_coverage_verified"] = False
    elif not submitting and success:
        raise DropcontactAPIError("Dropcontact completed response lacks the documented data array")
    else:
        output["data"] = None
    return output


class DropcontactNode(WorkflowNode):
    integration_type = "automation-dropcontact"
    credential_provider_labels = {"dropcontact": "Dropcontact Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="Dropcontact credit probe", proves="reachability", label_keys=("credits_left",))
    edit_examples = ["Read remaining credits without enrichment", "Submit an explicitly confirmed owned B2B batch", "Read one existing enrichment request without polling"]

    @classmethod
    def get_config_model(cls): return DropcontactNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data)
        shaped = dict(config_data)
        if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
        try: DropcontactNodeConfig.model_validate(runtime_config_view(shaped, DropcontactNodeConfig))
        except ValueError: raise ValueError("Dropcontact native configuration, closed enrichment input or credential scope is invalid") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data)
            shaped = dict(config_data)
            if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
            DropcontactNodeConfig.model_validate(runtime_config_view(shaped, DropcontactNodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["Dropcontact native configuration, contact payload or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await _current_data(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def validate_credential_access(cls, data):
        try:
            proof = await cls._operation(DropcontactCheckConfig(), _shape(data), {})
            if proof.get("protected_read_completed") is not True or proof.get("probe_contract") != "exact_data_one_empty_object" or proof.get("error") is not False or proof.get("success") is not True or type(proof.get("credits_left")) is not int or proof["credits_left"] < 0:
                return {"valid": None, "error": "Dropcontact protected credit probe was not verified"}
        except DropcontactAPIError as exc:
            return {"valid": False if exc.authority_rejected else None, "error": str(exc)}
        except ValueError:
            return {"valid": False, "error": "Dropcontact native credential is invalid"}
        return {"valid": True, "proves": "reachability", "account_identity_verified": False, "enrichment_permissions_verified": False}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, DropcontactNodeConfig) or self.config.credentials is None:
            raise ValueError("Dropcontact requires an explicit existing native access token")
        cfg = self.config.config
        if cfg.operation in WRITE_OPS and not cfg.confirm_existing_credits:
            raise ValueError("Confirm processing owned B2B contacts with existing credits before any provider request")
        node_data = self.node_data or {}
        raw = node_data.get("credentials")
        data = _shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context = {"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current = await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current):
            raise DropcontactAPIError("Dropcontact saved-row binding changed before transport", authority_rejected=True)
        result = await self._operation(cfg, current, context)
        await _stable(current, context)
        return {"status": "error" if result["error"] else "success", "operation": cfg.operation, "data": result, **({"error": "Dropcontact reported a failed processing outcome; raw diagnostics omitted"} if result["error"] else {})}

    @staticmethod
    async def _operation(cfg, data, context):
        op = cfg.operation
        if op in ("test_connection", "get_credits"):
            return _result(await _request(data, context, "POST", probe=True), submitting=True, probe=True)
        if op in WRITE_OPS:
            if not cfg.confirm_existing_credits: raise ValueError("Confirm owned B2B processing with existing credits before any provider request")
            contacts = [_single_contact(cfg)] if op == "enrich_contact" else _contacts_json(cfg.contacts_json)
            raw = await _request(data, context, "POST", contacts=contacts, siren=cfg.siren, language=cfg.language)
            try: result = _result(raw, submitting=True, expected_count=len(contacts))
            except DropcontactAPIError:
                raise DropcontactAPIError("Dropcontact submission receipt is unverified; processing and credit effects may have begun; inspect independently without replay") from None
            result["submitted_contact_count"] = len(contacts)
            result["notification_absence_verified"] = False
            return result
        if op in ("get_status", "get_results"):
            raw = await _request(data, context, "GET", request_id=cfg.request_id)
            result = _result(raw, request_id=cfg.request_id, expected_count=cfg.expected_contact_count, contact_data=getattr(cfg, "include_contact_data", False), custom_fields=getattr(cfg, "include_custom_fields", False))
            if op == "get_status":
                result.pop("data", None)
                result["private_rows_omitted"] = True
            return result
        raise ValueError("Unsupported native Dropcontact operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name != "request_id": return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {})
        if page_token: raise ValueError("Dropcontact exact request lookup has no documented history pagination")
        data = await _current_data(credential_data, **_authority(context))
        if search is None or search == "": return {"options": [], "next_page_token": None}
        identifier = _request_id(search)
        result = await cls._operation(DropcontactGetStatusConfig(request_id=identifier), data, context)
        await _stable(data, context)
        if result["error"]: raise DropcontactAPIError("Dropcontact exact request lookup returned a failed outcome; no resource option accepted")
        return {"options": [{"value": identifier, "label": identifier}], "next_page_token": None}
