"""Homebase's documented individual reads; unresolved collection contracts stay held."""
import base64
from contextvars import ContextVar
import json
import logging
import re
from typing import Annotated, Literal, Union
from urllib.parse import parse_qsl, quote, urlsplit
from uuid import UUID

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import normalize_search
from utils.credentials import (resolve_credential_with_owner_fallback, get_workflow_owner_id,
    is_credential_authorized_for_workflow, credential_lender)
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL
from utils.database_pool import get_native_pool
from utils.encryption import get_encryption
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN = "https://api.joinhomebase.com"
FAMILY = "homebase_api_key"
PRIVATE_REQUEST = ContextVar("homebase_private_http_request", default=False)


def _text(value, limit=255):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Homebase metadata text is invalid")
    return value


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("Enter an actual Homebase location UUID")
    return str(UUID(value))


def _id(value):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,9}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("Enter a positive Homebase integer ID")
    return value


LocationID = Annotated[str, BeforeValidator(_uuid), Field(json_schema_extra={"format": "uuid"})]
UserID = Annotated[int, BeforeValidator(_id)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or "credential_type" in raw and raw["credential_type"] != FAMILY:
        raise ValueError("Connect a native Homebase API key credential")
    return raw


class HomebaseApiKeyCredential(BaseModel):
    credential_type: Literal["homebase_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=8192, title="Existing Homebase API Key", json_schema_extra={"ui:widget": "password"})
    expected_company_name: str = Field(..., min_length=1, max_length=255, title="Expected Company Name", description="Match the current /company response; a name is not a unique company identity.")
    expected_company_owner_id: UserID = Field(..., title="Expected Company Owner ID", description="The company owner's documented user ID, not a claim about the API key's principal.")
    allowed_location_uuids: list[LocationID] = Field(..., min_length=1, max_length=20, title="Allowed Location UUIDs", description="Only these explicit locations may be read or selected; each is checked through its documented protected resource.")
    model_config = ConfigDict(title="Homebase API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.joinhomebase.com/reference/authentication-1"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid Homebase API key")
        return value

    @field_validator("expected_company_name")
    @classmethod
    def name(cls, value):
        return _text(value)

    @field_validator("allowed_location_uuids")
    @classmethod
    def locations(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Homebase allowed locations must be unique")
        return values


def _credential(raw):
    raw = _family(raw)
    try:
        return HomebaseApiKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("Homebase credential is invalid; reconnect") from None


def _op(value, title):
    return Field(value, title=title, json_schema_extra={"x-operation-group": "Protected Metadata Reads"})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCompany(Settings):
    operation: Literal["get_company"] = _op("get_company", "Read Current Company Metadata")


class ListConfiguredLocations(Settings):
    operation: Literal["list_configured_locations"] = _op("list_configured_locations", "Read Configured Location Metadata")


class Location(Settings):
    location_uuid: LocationID = Field(..., title="Allowed Location", json_schema_extra={"x-resource-type": "homebase_location", "x-dynamic-options": {"field_name": "location_uuid", "searchable": True, "allow_custom": True}})


class GetLocation(Location):
    operation: Literal["get_location"] = _op("get_location", "Get Selected Location Metadata")


class GetEmployee(Location):
    operation: Literal["get_employee"] = _op("get_employee", "Get Employee Metadata in Selected Location")
    employee_id: UserID = Field(..., title="Employee ID", description="Actual known ID under this location; the undocumented employee-list envelope is not guessed.", json_schema_extra={"x-resource-type": "homebase_employee"})


Operations = Annotated[Union[GetCompany, ListConfiguredLocations, GetLocation, GetEmployee], Field(discriminator="operation")]


class HomebaseNodeConfig(NodeConfig[Operations, HomebaseApiKeyCredential]):
    pass


class HomebaseCredentialSnapshot(dict):
    anchor: tuple
    authority = None


async def load_homebase_credential(credential_id, user_id, pool=None, org_id=None, workflow_id=None):
    pool = pool or get_native_pool()
    if org_id is None:
        async with pool.acquire() as conn:
            context = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
        org_id = str(context["organization_id"]) if context else None

    async def read(principal):
        async with pool.acquire() as conn:
            return await conn.fetchrow(f"""
                SELECT c.credential, c.credential_type, c.revoked_at, c.owner_id,
                       c.token_version, c.updated_at, c.metadata,
                       c.approval_operations, c.approval_revision
                FROM credentials c
                WHERE c.id = $1 AND {credential_access_predicate()}
            """, credential_id, principal, org_id)

    row = await read(user_id)
    if row is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if owner and owner != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            row = await read(owner)
    if row is None and workflow_id:
        lender = await credential_lender(pool, workflow_id, credential_id)
        if lender and lender != str(user_id):
            row = await read(lender)
    # A foreign or revoked row cannot reach the native decrypt/parse boundary.
    if not row or row["revoked_at"] is not None:
        return None
    if row["credential_type"] not in {"homebase_api_key"}:
        raise ValueError("Homebase credential family does not match the current row")
    try:
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", str(row["owner_id"])) or type(row["token_version"]) is not int or row["token_version"] < 0 or row["updated_at"] is None or type(row["approval_revision"]) is not int or row["approval_revision"] < 0 or not isinstance(row["approval_operations"], (list, tuple)) or any(not isinstance(v, str) for v in row["approval_operations"]):
            raise ValueError
        data = get_encryption().decrypt_credential(row["credential"])
        if not isinstance(data, dict):
            raise ValueError
        if "credential_type" in data and data["credential_type"] != row["credential_type"]:
            raise ValueError
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError
        data = HomebaseCredentialSnapshot(data)
        data["credential_type"] = row["credential_type"]
        data.anchor = (str(row["owner_id"]), row["token_version"],
                       str(row["updated_at"]), json.dumps(metadata, sort_keys=True),
                       row["approval_revision"], tuple(sorted(row["approval_operations"])))
        # The shared resolver remains authoritative for workflow owner/lender
        # admission; this local snapshot adds only a current-row binding check.
        resolved = await resolve_credential_with_owner_fallback(
            credential_id, user_id, pool, org_id=org_id, workflow_id=workflow_id)
        if resolved is None or _credential(resolved).model_dump() != _credential(data).model_dump():
            raise ValueError()
        return data
    except Exception:
        raise ValueError("Homebase current credential is invalid") from None


class _Authority:
    def __init__(self, credential, *, credential_id=None, user_id=None, pool=None, organization_id=None, workflow_id=None):
        self.credential = _credential(credential)
        self.credential_id, self.user_id, self.pool = credential_id, user_id, pool
        self.organization_id, self.workflow_id, self.anchor = organization_id, workflow_id, None

    async def check(self):
        _credential(self.credential)
        if not self.credential_id:
            return
        if not self.user_id:
            raise ValueError("Homebase saved credential requires an authorized actor")
        row = await load_homebase_credential(self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not row:
            raise ValueError("Homebase current credential is unavailable or revoked")
        if _credential(row).model_dump() != self.credential.model_dump():
            raise ValueError("Homebase credential binding changed; reconnect")
        if self.anchor is not None and self.anchor != row.anchor:
            raise ValueError("Homebase current authority changed; retry after review")
        self.anchor = row.anchor


class _RequestFilter(logging.Filter):
    def filter(self, record):
        if PRIVATE_REQUEST.get():
            record.msg, record.args = "Homebase HTTP transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _public(value, credential):
    key = credential.api_key
    canaries = {key, quote(key, safe=""), base64.b64encode(key.encode()).decode(), base64.urlsafe_b64encode(key.encode()).decode(), key.encode().hex()}
    text = json.dumps(value, ensure_ascii=False)
    if any(secret in text for secret in canaries) or re.search(r"https?://|data:|[?&](?:token|key|signature)=", text, re.I):
        raise ValueError("Homebase returned protected capability or credential data")
    return value


def _next_page(link, expected_path, params, current_page):
    """Constrain RFC5988 next to a page number; never return/request its URL.

    Collection dispatch stays held pending an actual collection response contract.
    Individual read routes use this boundary to refuse unexpected continuation.
    """
    if not link:
        return None
    if not isinstance(link, str) or len(link) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in link) or type(current_page) is not int or not 1 <= current_page <= 100:
        raise ValueError("Homebase pagination header is malformed")
    next_urls = []
    parts = re.split(r",\s*(?=<)", link)
    if len(parts) > 10:
        raise ValueError("Homebase pagination header exceeds its bound")
    for part in parts:
        match = re.fullmatch(r"\s*<([^<>]+)>\s*((?:;[^<>]*)?)", part)
        if not match:
            raise ValueError("Homebase pagination link is malformed")
        rels = re.findall(r';\s*rel\s*=\s*(?:"([^"]*)"|([^;\s]+))', match[2], re.I)
        if len(rels) != 1:
            raise ValueError("Homebase pagination relation is ambiguous")
        if "next" in (rels[0][0] or rels[0][1]).split():
            next_urls.append(match[1])
    if not next_urls:
        return None
    if len(next_urls) != 1:
        raise ValueError("Homebase pagination has multiple next links")
    try:
        parsed = urlsplit(next_urls[0])
    except ValueError:
        raise ValueError("Homebase pagination URL is malformed") from None
    if parsed.scheme != "https" or parsed.netloc != "api.joinhomebase.com" or parsed.username or parsed.password or parsed.fragment or parsed.path != expected_path or "\\" in next_urls[0]:
        raise ValueError("Homebase pagination is outside the current native route")
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ValueError("Homebase pagination query is malformed") from None
    query = dict(pairs)
    if len(query) != len(pairs) or set(query) != set(params) | {"page"} or any(query.get(k) != str(v) for k, v in params.items()) or not re.fullmatch(r"[1-9][0-9]{0,2}", query.get("page", "")):
        raise ValueError("Homebase pagination changed the typed request context")
    page = int(query["page"])
    if not current_page < page <= 100:
        raise ValueError("Homebase pagination repeated or exceeded its bound")
    return page


class HomebaseRequestError(ValueError):
    def __init__(self, message, *, status=None, outcome="unverified"):
        super().__init__(message)
        self.status, self.outcome = status, outcome


class _Client:
    def __init__(self, authority):
        self.authority, self.credential, self.verified = authority, authority.credential, False

    def allowed(self, value):
        value = _uuid(value)
        if value not in self.credential.allowed_location_uuids:
            raise ValueError("Homebase location is outside the credential's explicit scope")
        return value

    async def request(self, path):
        if path != "/company":
            match = re.fullmatch(r"/locations/([0-9a-f-]{36})(?:/employees/([1-9][0-9]{0,9}))?", path)
            if not match or not self.verified:
                raise ValueError("Unsupported Homebase native read route")
            self.allowed(match[1])
            if match[2]:
                _id(match[2])
        url = ORIGIN + path
        assert_exact_url_origin(url, ORIGIN)
        await self.authority.check()
        headers = {"Authorization": "Bearer " + self.credential.api_key, "Accept": "application/vnd.homebase-v1+json"}
        _install_privacy()
        private = PRIVATE_REQUEST.set(True)
        try:
            with OutboundTraceProvider().get_tracer(__name__).start_as_current_span("GET", kind=SpanKind.CLIENT,
                attributes={"http.request.method": "GET", "url.full": ORIGIN + "/[native-resource]", "url.scheme": "https", "server.address": "api.joinhomebase.com", "server.port": 443}, record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream("GET", url, headers=headers) as response:
                                status = response.status_code
                                span.set_attribute("http.response.status_code", status)
                                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                                link = response.headers.get("link")
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > 1_000_000:
                                        raise HomebaseRequestError("Homebase response exceeds its native bound")
                                    content.extend(chunk)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    if isinstance(error, httpx.HTTPError):
                        raise HomebaseRequestError("Homebase request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        if status != 200:
            outcome = "unauthenticated" if status == 401 else "forbidden" if status == 403 else "rate_limited" if status == 429 else "unverified"
            raise HomebaseRequestError(f"Homebase returned HTTP {status}; resource access is unverified", status=status, outcome=outcome)
        if _next_page(link, path, {}, 1) is not None:
            raise HomebaseRequestError("Homebase individual resource unexpectedly advertised pagination")
        try:
            if media not in {"application/json", "application/vnd.homebase-v1+json"}:
                raise ValueError
            row = json.loads(content)
            if not isinstance(row, dict) or row.get("error") or row.get("errors"):
                raise ValueError
            return row
        except Exception:
            raise HomebaseRequestError("Homebase did not return a documented individual resource", status=200) from None

    async def company(self):
        row = await self.request("/company")
        owner = row.get("owner")
        if not isinstance(owner, dict):
            raise ValueError("Homebase current company owner witness is missing")
        name, owner_id = _text(row.get("name")), _id(owner.get("id"))
        if name != self.credential.expected_company_name or owner_id != self.credential.expected_company_owner_id:
            raise ValueError("Homebase current company differs from the configured witness")
        result = {"name": name, "owner_id": owner_id}
        result = _public(result, self.credential)
        self.verified = True
        return result

    async def location(self, location_uuid):
        location_uuid = self.allowed(location_uuid)
        row = await self.request("/locations/" + location_uuid)
        if _uuid(row.get("uuid")) != location_uuid:
            raise ValueError("Homebase location UUID differs from the selected parent")
        result = {"uuid": location_uuid, "name": _text(row.get("name"))}
        for field in ("time_zone", "city", "state", "country_code"):
            if row.get(field) is not None:
                result[field] = _text(row[field])
        return _public(result, self.credential)

    async def employee(self, location_uuid, employee_id):
        location_uuid, employee_id = self.allowed(location_uuid), _id(employee_id)
        await self.location(location_uuid)
        row = await self.request(f"/locations/{location_uuid}/employees/{employee_id}")
        job = row.get("job")
        if _id(row.get("id")) != employee_id or not isinstance(job, dict) or _uuid(job.get("location_uuid")) != location_uuid:
            raise ValueError("Homebase employee differs from the selected ID or location")
        result = {"id": employee_id, "location_uuid": location_uuid}
        for field in ("first_name", "last_name"):
            if row.get(field) is not None:
                result[field] = _text(row[field])
        return _public(result, self.credential)


class HomebaseNode(WorkflowNode):
    integration_type = "automation-homebase"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(noun="Homebase company", operation="get_company", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return HomebaseNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, HomebaseNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ConfigValidationError("Homebase configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["Homebase credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials, credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            pool=self.node_data.get("_approval_pool"), organization_id=self.organization_id, workflow_id=self.workflow_id)

    async def run(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        self._native_authority = self._authority()
        await self._native_authority.check()
        return await super().run(inputs)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        raw = _family(credential_data)
        if credential_id:
            # The shared dropdown loader attaches row metadata. The native loader
            # below rechecks the current row and supplies its own authority anchor.
            raw = {key: value for key, value in raw.items() if key not in {"token_version", "updated_at"}}
        authority = _Authority(_credential(raw), credential_id=credential_id, user_id=user_id, pool=pool)
        await authority.check()
        result = HomebaseCredentialSnapshot(authority.credential.model_dump())
        result.authority = authority
        return result

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run the protected Homebase company witness; static validation proves no principal, ownership, role or API entitlement"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(getattr(self, "_native_authority", None) or self._authority())
        cfg = self.config.config
        if isinstance(cfg, Location):
            client.allowed(cfg.location_uuid)
        company = await client.company()
        if cfg.operation == "get_company":
            return {"data": company, "reachable": True, "identity_verified": False, "ownership_verified": False, "company_identity_verified": False, "http_status": 200}
        if cfg.operation == "list_configured_locations":
            rows = [await client.location(value) for value in client.credential.allowed_location_uuids]
            return {"data": rows, "total": len(rows), "configured_scope_only": True, "next_page_token": None, "http_status": 200}
        if cfg.operation == "get_location":
            result = await client.location(cfg.location_uuid)
        elif cfg.operation == "get_employee":
            result = await client.employee(cfg.location_uuid, cfg.employee_id)
        else:
            raise ValueError("Unsupported Homebase native operation")
        return {"data": result, "http_status": 200, "identity_verified": False, "ownership_verified": False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data)
        if field_name != "location_uuid" or page_token is not None:
            raise ValueError("Homebase supports only the bounded configured-location selector")
        authority = getattr(credential_data, "authority", None)
        if authority is None:
            raise ValueError("Load Homebase selectors through the admitted current credential loader")
        client = _Client(authority)
        await client.company()
        rows = [await client.location(value) for value in client.credential.allowed_location_uuids]
        query = normalize_search(search)
        options = [{"value": row["uuid"], "label": row["name"]} for row in rows if not query or query.casefold() in row["name"].casefold() or query.casefold() in row["uuid"].casefold()]
        return {"options": options, "next_page_token": None}
