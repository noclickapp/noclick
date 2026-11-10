"""Closed Porkbun v3.56 GET metadata; no DNS values or account/control APIs.

Protected catalog and independent domain/record reads bind child ancestry.
A SUCCESS response proves resource reachability, never account ownership.
"""
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.credentials import credential_access_predicate
from utils.credentials import (resolve_credential_with_owner_fallback, get_workflow_owner_id,
                               is_credential_authorized_for_workflow, credential_lender)
from utils.encryption import get_encryption
from utils.ssrf import SSRFError, guarded_async_client

TYPE = "porkbun_api_key"
AUTH_KEY = "_porkbun_authority"
API = "https://api.porkbun.com/api/json/v3"
CURRENT_ORGANIZATION = object()
UNAVAILABLE = "Porkbun saved credential is unavailable or has changed"
UNVERIFIED = "Porkbun metadata access or response could not be verified"
MAX_BODY = 4 * 1024 * 1024
MAX_ARRAY = 10000


def domain_name(value):
    if not isinstance(value, str) or not 3 <= len(value) <= 253 or value != value.lower() or "." not in value:
        raise ValueError("Supply an exact lowercase ASCII or punycode catalog domain, without a URL or trailing dot")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split(".")):
        raise ValueError("Supply an exact lowercase ASCII or punycode catalog domain")
    return value


def record_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", value):
        raise ValueError("Supply the exact numeric string record ID returned by this domain's DNS catalog")
    return value


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Supply only an already-issued API key or secret key value")
    return value


Domain = Annotated[StrictStr, BeforeValidator(domain_name), Field(min_length=3, max_length=253)]
RecordID = Annotated[StrictStr, BeforeValidator(record_id), Field(min_length=1, max_length=40)]
Limit = Annotated[StrictInt, Field(ge=1, le=100)]
Offset = Annotated[StrictInt, Field(ge=0, le=9007199254740991)]


class PorkbunCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": TYPE,
        "x-credential-help-url": "https://kb.porkbun.com/article/307-getting-started-porkbun-api",
        "x-credential-instructions": "Supply the existing API key and secret API key. Both are sent only in HTTPS headers to api.porkbun.com. Protected catalog reachability is not human identity or account ownership. No key issuance, body/query credentials, OAuth, alternate host or automatic refresh. Keys and domain API access must already be enabled by their owner.",
    })
    credential_type: Literal["porkbun_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    secret_api_key: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="Secret API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Porkbun requires its original supplied API key pair")
    try:
        return PorkbunCredential.model_validate(raw)
    except Exception:
        raise ValueError("Porkbun credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("Porkbun credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Domain Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Domain and Record Names", description="Opt in to domain names and DNS record owner names. DNS values, notes, IPs and private account/settings fields are always omitted.")


class Bounded(Config):
    max_results: Limit = Field(20, title="Maximum Results", description="Strict integer 1–100 local output cap. This is not a provider page size or account total.")


class ListDomains(Bounded):
    operation: Literal["list_domains"] = op("list_domains", "List Domain Metadata", "Read one protected domain catalog page. Its count describes this page, not the account. Completion remains unknown.")
    start: Offset = Field(0, title="Domain Start Offset", description="Documented zero-based start. Porkbun can return up to 1000 domains; only the local maximum is emitted. No next cursor or global completeness is inferred.")


class DomainConfig(Config):
    domain: Domain = Field(..., title="Catalog Domain", description="Exact lowercase ASCII/punycode domain from the current catalog. Internally use the documented exact-domain catalog filter and independent detail read before child reads.", json_schema_extra={"x-dynamic-options": {"allow_custom": True, "custom_placeholder": "Paste an exact catalog domain"}})


class GetDomain(DomainConfig):
    operation: Literal["get_domain"] = op("get_domain", "Get Domain Metadata", "Read the current catalog-bound domain's status, TLD and documented date strings. No privacy, security, renewal or delegation settings.")


class ListDNSRecords(DomainConfig, Bounded):
    operation: Literal["list_dns_records"] = op("list_dns_records", "List DNS Record Metadata", "Read editable records for the protected domain; SOA and Porkbun default NS are excluded by this API. No DNS pagination is invented. RDATA is never emitted.")


class GetDNSRecord(DomainConfig):
    operation: Literal["get_dns_record"] = op("get_dns_record", "Get DNS Record Metadata", "Bind a record to the current domain's record catalog and verify the independently returned records array contains exactly that record. No record values or changes.")
    record_id: RecordID = Field(..., title="Catalog DNS Record ID", description="Numeric string ID from this domain's current DNS record catalog, not an integer or URL.", json_schema_extra={"x-dynamic-options": {"depends_on": "domain", "allow_custom": True, "custom_placeholder": "Paste an exact domain record ID"}})


OPERATIONS = (ListDomains, GetDomain, ListDNSRecords, GetDNSRecord)
PorkbunConfig = Annotated[Union[ListDomains, GetDomain, ListDNSRecords, GetDNSRecord], Field(discriminator="operation")]


class PorkbunNodeConfig(NodeConfig[PorkbunConfig, PorkbunCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-porkbun"] = "automation-porkbun"


@dataclass(frozen=True)
class CredentialValidationRow:
    credential_type: str
    owner_id: str
    token_version: int
    updated_at: Any
    approval_revision: int
    revoked_at: Any
    credential: Any = field(repr=False)


async def fetch_validation_authority(pool, identifier, principal, organization_id):
    """Read Porkbun's current authority using staging's canonical access rule."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            SELECT c.credential_type, c.owner_id, c.token_version, c.updated_at,
                   c.approval_revision, c.revoked_at, c.credential
            FROM credentials c
            WHERE c.id = $1 AND {credential_access_predicate()}
        """, identifier, principal, organization_id)
    if row is None:
        return None
    return CredentialValidationRow(
        row['credential_type'], str(row['owner_id']), row['token_version'],
        row['updated_at'], row['approval_revision'], row['revoked_at'], row['credential'],
    )


@dataclass(eq=False)
class Authority:
    credential: PorkbunCredential = field(repr=False)
    pool: Any = field(default=None, repr=False)
    user_id: Any = None
    credential_id: Any = None
    organization_id: Any = None
    workflow_id: Any = None
    anchor: Any = field(default=None, repr=False)
    resolve_organization: bool = False

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        shaped = credential(raw)
        if credential_id and not user_id:
            raise ValueError(UNAVAILABLE)
        current = cls(shaped, pool, user_id, credential_id, organization_id, workflow_id, resolve_organization=organization_id is CURRENT_ORGANIZATION)
        if credential_id:
            if pool is None:
                from utils.database_pool import get_native_pool
                current.pool = get_native_pool()
            if current.resolve_organization:
                current.organization_id = await current.current_organization()
            current.credential, current.anchor = await current.load()
            if current.credential != shaped:
                raise ValueError(UNAVAILABLE)
        return current

    async def current_organization(self):
        from wss.handlers.workflow_handler import get_user_org_context
        async with self.pool.acquire() as conn:
            return await get_user_org_context(conn, self.user_id)

    async def load(self):
        # Staging's resolver owns the workflow authorization decision. Re-read
        # the matching accessible row to bind Porkbun to its current revisions.
        resolved = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if not resolved:
            raise ValueError(UNAVAILABLE)
        principal = self.user_id
        row = await fetch_validation_authority(self.pool, self.credential_id, principal, self.organization_id)
        if row is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if owner and owner != self.user_id and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id):
                principal = owner
                row = await fetch_validation_authority(self.pool, self.credential_id, principal, self.organization_id)
        if row is None and self.workflow_id:
            lender = await credential_lender(self.pool, self.workflow_id, self.credential_id)
            if lender and lender != self.user_id:
                principal = lender
                row = await fetch_validation_authority(self.pool, self.credential_id, principal, self.organization_id)
        if row is None or row.credential_type != TYPE or row.revoked_at is not None or type(row.token_version) is not int or row.token_version < 1:
            raise ValueError(UNAVAILABLE)
        shaped = credential(get_encryption().decrypt_credential(row.credential))
        if shaped != credential(resolved):
            raise ValueError(UNAVAILABLE)
        return shaped, (principal, row)

    async def require_current(self):
        if self.credential_id:
            if self.resolve_organization and await self.current_organization() != self.organization_id:
                raise ValueError(UNAVAILABLE)
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor:
                raise ValueError(UNAVAILABLE)




_PRIVATE = ContextVar("porkbun_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Porkbun transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()
AUTH_CODES = {"API_KEY_REQUIRED", "INVALID_API_KEYS_001", "INVALID_TOKEN", "INVALID_USER"}
PERMISSION_CODES = {"IP_NOT_ALLOWED", "DOMAIN_NOT_ALLOWED", "API_ACCESS_DISABLED"}
RESOURCE_CODES = {"DOMAIN_NOT_FOUND", "DOMAIN_NOT_REGISTERED", "INVALID_DOMAIN"}


class ApiError(ValueError):
    def __init__(self, status, code=None):
        self.status_code = status
        self.category = "authentication" if code in AUTH_CODES or status == 401 else "permission" if code in PERMISSION_CODES or status == 403 else "resource" if code in RESOURCE_CODES or status == 404 else "other"
        meaning = {"authentication": "authentication failed", "permission": "metadata access is forbidden", "resource": "resource is missing, invalid or inaccessible", "other": "request outcome is not successful"}[self.category]
        if status == 429:
            meaning = "rate limit reached; no automatic retry"
        safe_code = code if code in AUTH_CODES | PERMISSION_CODES | RESOURCE_CODES else None
        super().__init__(f"Porkbun returned HTTP {status}: {meaning}" + (f" ({safe_code})" if safe_code else ""))


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def validate_route(route, params):
    if not isinstance(params, dict):
        raise ValueError("Unsupported Porkbun query")
    if route == "/domain/listAll":
        if set(params) - {"start", "includeLabels", "domain"} or params.get("includeLabels") != "no" or type(params.get("start")) is not int or not 0 <= params["start"] <= 9007199254740991:
            raise ValueError("Unsupported Porkbun catalog query")
        if "domain" in params:
            domain_name(params["domain"])
            if params["start"] != 0:
                raise ValueError("Exact-domain catalog qualification starts at zero")
        return
    match = re.fullmatch(r"/(domain/get|dns/retrieve)/([^/]+)(?:/([^/]+))?", route)
    if not match:
        raise ValueError("Unsupported Porkbun metadata route")
    domain_name(match[2])
    if match[1] == "domain/get":
        if match[3] is not None or params != {"includeLabels": "no"}:
            raise ValueError("Unsupported Porkbun domain query")
    elif params:
        raise ValueError("Porkbun DNS metadata has no supported pagination query")
    elif match[3] is not None:
        record_id(match[3])


async def request(auth, route, params=None):
    params = {} if params is None else params
    validate_route(route, params)
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                req = client.build_request("GET", API + route, params=params, headers={"X-API-Key": auth.credential.api_key, "X-Secret-API-Key": auth.credential.secret_api_key, "Accept": "application/json"})
                await auth.require_current()
                response = await client.send(req, stream=True)
                try:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            raise OutcomeUnverified("Porkbun response exceeds the local 4 MiB bound; no partial output")
                    await auth.require_current()
                    raw = None
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json":
                        try:
                            raw = json.loads(body, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                        except (ValueError, UnicodeError, RecursionError):
                            if response.status_code == 200:
                                raise OutcomeUnverified(UNVERIFIED) from None
                    if response.status_code != 200 or isinstance(raw, dict) and raw.get("status") == "ERROR":
                        code = raw.get("code") if isinstance(raw, dict) else None
                        raise ApiError(response.status_code, code if isinstance(code, str) else None)
                    if response.headers.get("X-Porkbun-Mock", "").lower() == "true" or not isinstance(raw, dict) or raw.get("status") != "SUCCESS":
                        raise OutcomeUnverified(UNVERIFIED)
                    if "sandbox" in raw and type(raw["sandbox"]) is not bool:
                        raise OutcomeUnverified(UNVERIFIED)
                    return raw
                finally:
                    await response.aclose()
    except (httpx.RequestError, SSRFError):
        await auth.require_current()
        raise OutcomeUnverified("Porkbun transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


def array(raw, maximum=MAX_ARRAY):
    if not isinstance(raw, list) or len(raw) > maximum:
        raise OutcomeUnverified("Porkbun metadata array is invalid or exceeds the local bound")
    return raw


def text(value, maximum=512):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError()
    return value


def domain(raw, names=False):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        witness = domain_name(raw["domain"])
        output = {}
        for key in ("status", "tld", "createDate", "expireDate"):
            if key in raw:
                output[key] = text(raw[key], 253 if key == "tld" else 64)
        if names:
            output["domain"] = witness
        return witness, output
    except Exception:
        raise OutcomeUnverified("Porkbun domain metadata or ancestry could not be verified") from None


def record(raw, parent, names=False):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        rid = record_id(raw["id"])
        owner = text(raw["name"], 254)
        canonical = owner[:-1] if owner.endswith(".") else owner
        if not re.fullmatch(r"[A-Za-z0-9_*.-]+", canonical) or any(not part for part in canonical.split(".")) or not (canonical.lower() == parent or canonical.lower().endswith("." + parent)):
            raise ValueError()
        rtype = text(raw["type"], 32)
        if not re.fullmatch(r"[A-Z][A-Z0-9-]*", rtype):
            raise ValueError()
        ttl = text(raw["ttl"], 20)
        if not ttl.isascii() or not ttl.isdecimal():
            raise ValueError()
        output = {"id": rid, "type": rtype, "ttl": ttl}
        if "prio" in raw:
            priority = raw["prio"]
            if priority is not None and (not isinstance(priority, str) or not re.fullmatch(r"[0-9]{1,20}", priority)):
                raise ValueError()
            output["prio"] = priority
        if names:
            output["name"] = owner
        return {"id": rid, "name": owner, "type": rtype, "ttl": ttl, **({"prio": raw["prio"]} if "prio" in raw else {})}, output
    except Exception:
        raise OutcomeUnverified("Porkbun record ID, type or domain ancestry could not be verified") from None


def bounded(items, maximum, *, start=None, provider_page_count=None):
    result = {"items": items[:maximum], "returned_count": min(len(items), maximum), "observed_page_count": len(items), "local_limit": maximum, "truncated": len(items) > maximum, "completion": "unknown", "snapshot_consistent": False}
    if start is not None:
        result["start"] = start
    if provider_page_count is not None:
        result["provider_page_count"] = provider_page_count
    return result


def environment_marker(raw, result):
    # The primary introduction documents this response marker; infer no key tier.
    if "sandbox" in raw:
        result["sandbox"] = raw["sandbox"]
    return result


async def domain_catalog(auth, *, names=False, start=0, selected=None):
    params = {"start": start, "includeLabels": "no"}
    if selected is not None:
        params["domain"] = domain_name(selected)
    raw = await request(auth, "/domain/listAll", params)
    rows = [domain(row, names) for row in array(raw.get("domains"), 1000)]
    if len({w for w, _ in rows}) != len(rows) or selected is not None and any(w != selected for w, _ in rows):
        raise OutcomeUnverified("Porkbun current domain catalog witness is invalid")
    count = raw.get("count")
    if "count" in raw and (type(count) is not int or count != len(rows)):
        raise OutcomeUnverified("Porkbun count must equal domains returned in this page, not an account total")
    return raw, rows


async def selected_domain(auth, selected, names=False):
    _, rows = await domain_catalog(auth, names=names, selected=selected)
    if len(rows) != 1 or rows[0][0] != selected:
        raise OutcomeUnverified("Porkbun domain is absent from its current protected exact-match catalog")
    raw = await request(auth, "/domain/get/" + quote(selected, safe=""), {"includeLabels": "no"})
    witness, projected = domain(raw.get("domain"), names)
    if witness != selected:
        raise OutcomeUnverified("Porkbun returned a different domain envelope")
    return raw, projected


async def record_catalog(auth, selected, names=False):
    raw = await request(auth, "/dns/retrieve/" + quote(selected, safe=""))
    rows = [record(row, selected, names) for row in array(raw.get("records"))]
    if len({w["id"] for w, _ in rows}) != len(rows):
        raise OutcomeUnverified("Porkbun DNS catalog has duplicate record IDs")
    return raw, rows


async def operate(auth, cfg):
    if isinstance(cfg, ListDomains):
        raw, rows = await domain_catalog(auth, names=cfg.include_names, start=cfg.start)
        return environment_marker(raw, bounded([p for _, p in rows], cfg.max_results, start=cfg.start, provider_page_count=raw.get("count")))
    parent_raw, parent = await selected_domain(auth, cfg.domain, cfg.include_names)
    if isinstance(cfg, GetDomain):
        return environment_marker(parent_raw, {"domain_metadata": parent})
    if isinstance(cfg, (ListDNSRecords, GetDNSRecord)):
        raw, rows = await record_catalog(auth, cfg.domain, cfg.include_names)
        if isinstance(cfg, ListDNSRecords):
            return environment_marker(raw, {"domain_metadata": parent, "records": bounded([p for _, p in rows], cfg.max_results)})
        selected = next((w for w, _ in rows if w["id"] == cfg.record_id), None)
        if selected is None:
            raise OutcomeUnverified("Porkbun record ID is absent from the current domain record catalog")
        raw = await request(auth, "/dns/retrieve/" + quote(cfg.domain, safe="") + "/" + quote(cfg.record_id, safe=""))
        returned = [record(row, cfg.domain, cfg.include_names) for row in array(raw.get("records"))]
        if len(returned) != 1 or returned[0][0] != selected:
            raise OutcomeUnverified("Porkbun record detail does not match the selected current domain record")
        return environment_marker(raw, {"domain_metadata": parent, "record": returned[0][1]})
    raise ValueError("Unsupported Porkbun metadata operation")


class PorkbunNode(WorkflowNode):
    integration_type = "automation-porkbun"
    credential_provider_labels = {"porkbun": "Porkbun Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_domains", noun="protected domain catalog reachability", label_keys=(), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return PorkbunNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw_guard(config_data)
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        auth = await Authority.create(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        return {**auth.credential.model_dump(), AUTH_KEY: auth}

    @classmethod
    async def validate_credential_access(cls, raw, *, validation_context=None):
        try:
            if validation_context is not None:
                await validation_context.revalidate()
                result = await validation_context.run_operation("list_domains", {})
                return (True, None) if result.get("status") == "success" else (None, UNVERIFIED)
            auth = await Authority.create(raw)
            await operate(auth, ListDomains())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.category in {"authentication", "permission"} else (None, str(error))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, PorkbunNodeConfig) or self.config.credentials is None:
            raise ValueError("Porkbun supplied API key and secret API key are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        result = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if not isinstance(auth, Authority) or not auth.credential_id or not auth.user_id or context.get("_user_id") != auth.user_id:
            raise ValueError("Porkbun picker requires a current saved credential authorized for this actor")
        if field_name not in {"domain", "record_id"} or page_token is not None:
            raise ValueError("Porkbun supports only bounded current catalog pickers, without invented next cursors")
        names = context.get("include_names", False)
        if type(names) is not bool or search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("Porkbun picker opt-in or search is invalid")
        await auth.require_current()
        if field_name == "domain":
            _, rows = await domain_catalog(auth, names=names)
            if len(rows) > 100:
                raise OutcomeUnverified("Porkbun catalog exceeds the 100-option picker bound; paste an exact domain for protected qualification")
            options = [{"value": w, "label": w if names else "Domain " + str(i + 1)} for i, (w, _) in enumerate(rows)]
        else:
            selected = domain_name(context.get("domain"))
            await selected_domain(auth, selected, names)
            _, rows = await record_catalog(auth, selected, names)
            if len(rows) > 100:
                raise OutcomeUnverified("Porkbun record catalog exceeds the 100-option picker bound; paste an exact record ID")
            options = [{"value": w["id"], "label": ((w["name"] + " · ") if names else "") + w["type"] + " record " + w["id"]} for w, _ in rows]
        if search:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        await auth.require_current()
        return {"options": options, "next_page_token": None}
