"""Closed SAP LeanIX fact-sheet reads; technical token claims are not identity."""
import asyncio
import base64
from collections import OrderedDict
from contextvars import ContextVar
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import normalize_search
from utils.credentials import resolve_credential_with_owner_fallback
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

TOKEN_PATH = "/services/mtm/v1/oauth2/token"
GRAPHQL_PATH = "/services/pathfinder/v1/graphql"
PRIVATE_REQUEST = ContextVar("leanix_private_http_request", default=False)
TOKEN_CACHE = OrderedDict()
FAMILY = "leanix_api_token"


class _RequestFilter(logging.Filter):
    def filter(self, record):
        if not PRIVATE_REQUEST.get():
            return True
        record.msg, record.args = "SAP LeanIX HTTP transport activity", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _text(value, limit=255):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("SAP LeanIX metadata text is invalid")
    return value


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("Enter an actual SAP LeanIX fact-sheet UUID")
    return str(UUID(value))


def _type_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", value):
        raise ValueError("Select a current SAP LeanIX fact-sheet type")
    return value


Identifier = Annotated[str, BeforeValidator(_uuid)]
TypeKey = Annotated[str, BeforeValidator(_type_key)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or "credential_type" in raw and raw["credential_type"] != FAMILY:
        raise ValueError("Connect a native SAP LeanIX API token credential")
    return raw


class LeanIXApiTokenCredential(BaseModel):
    """SAP LeanIX API Token"""
    credential_type: Literal["leanix_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    workspace_subdomain: str = Field(..., min_length=1, max_length=63, title="Workspace Subdomain", description="Actual single subdomain of your SAP LeanIX workspace; requests use only https://<subdomain>.leanix.net.")
    api_token: str = Field(..., min_length=1, max_length=8192, title="Existing Technical User API Token", description="Exchanged with Basic client ID apitoken; no technical user, token or role is created here.", json_schema_extra={"ui:widget": "password"})
    witness_fact_sheet_id: Identifier = Field(..., title="Known Accessible Fact Sheet ID", description="Protected read witness; this does not prove a personal identity, numeric workspace ID or ownership.", json_schema_extra={"x-resource-type": "leanix_fact_sheet"})
    model_config = ConfigDict(title="SAP LeanIX API Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://help.sap.com/docs/leanix/ea/authentication-to-sap-leanix-services"})

    @field_validator("workspace_subdomain")
    @classmethod
    def subdomain(cls, value):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Supply only the lowercase SAP LeanIX workspace subdomain")
        return value

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid SAP LeanIX technical API token")
        return value


def _credential(raw):
    raw = _family(raw)
    try:
        return LeanIXApiTokenCredential.model_validate(raw)
    except Exception:
        raise ValueError("SAP LeanIX credential is invalid; reconnect") from None


def _op(value, title):
    return Field(value, title=title, json_schema_extra={"x-operation-group": "Fact Sheet Reads"})


def _selector(title, field, resource, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return Field(..., title=title, json_schema_extra={"x-resource-type": "leanix_" + resource, "x-dynamic-options": options})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TestAuthentication(Settings):
    operation: Literal["test_authentication"] = _op("test_authentication", "Read Protected Fact Sheet Witness")


class GetFactSheet(Settings):
    operation: Literal["get_fact_sheet"] = _op("get_fact_sheet", "Get Selected Fact Sheet Metadata")
    fact_sheet_type: TypeKey = _selector("Fact Sheet Type", "fact_sheet_type", "fact_sheet_type")
    fact_sheet_id: Identifier = _selector("Fact Sheet", "fact_sheet_id", "fact_sheet", "fact_sheet_type")


class Page(Settings):
    page_size: int = Field(25, ge=1, le=100, title="Page Size")
    page_token: Optional[str] = Field(None, max_length=18000, title="Continuation", json_schema_extra={"ui:hidden": True})


class ListFactSheets(Page):
    operation: Literal["list_fact_sheets"] = _op("list_fact_sheets", "List Workspace Fact Sheet Metadata")
    fact_sheet_type: Optional[TypeKey] = Field(None, title="Optional Fact Sheet Type", json_schema_extra={"x-resource-type": "leanix_fact_sheet_type", "x-dynamic-options": {"field_name": "fact_sheet_type", "searchable": True, "allow_custom": True}})


class ListFactSheetTypes(Settings):
    operation: Literal["list_fact_sheet_types"] = _op("list_fact_sheet_types", "List Current Fact Sheet Type Facets")


class ListApplicationsByTechnicalFit(Page):
    operation: Literal["list_applications_by_technical_fit"] = _op("list_applications_by_technical_fit", "List Applications by Current Technical Fit")
    technical_fit: str = _selector("Application Technical Fit", "technical_fit", "technical_fit")

    @field_validator("technical_fit")
    @classmethod
    def fit(cls, value):
        return _text(value, 80)


Operations = Annotated[Union[TestAuthentication, GetFactSheet, ListFactSheets, ListFactSheetTypes, ListApplicationsByTechnicalFit], Field(discriminator="operation")]


class LeanIXNodeConfig(NodeConfig[Operations, LeanIXApiTokenCredential]):
    pass


class _Authority:
    def __init__(self, credential, *, credential_id=None, user_id=None, pool=None, organization_id=None, workflow_id=None):
        self.credential = _credential(credential)
        self.credential_id, self.user_id, self.pool = credential_id, user_id, pool
        self.organization_id, self.workflow_id = organization_id, workflow_id

    async def check(self):
        _credential(self.credential)
        if not self.credential_id:
            return
        if not self.user_id:
            raise ValueError("SAP LeanIX saved credential requires an authorized actor")
        row = await resolve_credential_with_owner_fallback(self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not row:
            raise ValueError("SAP LeanIX current credential is unavailable or revoked")
        if _credential(row).model_dump() != self.credential.model_dump():
            raise ValueError("SAP LeanIX credential binding changed; reconnect")

    def key(self):
        return hashlib.sha256(json.dumps([self.credential.model_dump(mode="json"), self.credential_id,
            self.user_id, self.organization_id, self.workflow_id], sort_keys=True, default=str).encode()).hexdigest()


class _TokenEntry:
    def __init__(self):
        self.loop, self.lock = asyncio.get_running_loop(), asyncio.Lock()
        self.access_token, self.expires_at = None, 0


def _cache_entry(authority):
    key = (id(asyncio.get_running_loop()), authority.key())
    if key not in TOKEN_CACHE:
        while len(TOKEN_CACHE) >= 128:
            idle = next((key for key, value in TOKEN_CACHE.items() if not value.lock.locked()), None)
            if idle is None:
                raise ValueError("SAP LeanIX private token cache is busy; retry later")
            del TOKEN_CACHE[idle]
        TOKEN_CACHE[key] = _TokenEntry()
    TOKEN_CACHE.move_to_end(key)
    return TOKEN_CACHE[key]


def _public(value, credential, token=None):
    keys = [credential.api_token] + ([token] if token else [])
    canaries = {secret for key in keys for secret in (key, quote(key, safe=""), base64.b64encode(key.encode()).decode(), base64.urlsafe_b64encode(key.encode()).decode(), key.encode().hex())}
    canaries.add(base64.b64encode(("apitoken:" + credential.api_token).encode()).decode())
    serialized = json.dumps(value, ensure_ascii=False)
    if any(secret in serialized for secret in canaries) or re.search(r"https?://|data:|[?&](?:token|access_token|signature|x-amz-signature)=", serialized, re.I):
        raise ValueError("SAP LeanIX response contained protected credential data")
    return value


class LeanIXRequestError(ValueError):
    def __init__(self, message, *, status=None, outcome="unverified"):
        super().__init__(message)
        self.status, self.outcome = status, outcome


FACT_SHEET = "query NativeFactSheet($id: ID!) { factSheet(id: $id) { id name type } }"
ALL_SHEETS = "query NativeFactSheets($first: Int!, $after: String) { allFactSheets(first: $first, after: $after) { totalCount pageInfo { endCursor hasNextPage } edges { node { id name type } } } }"
FILTERED_SHEETS = "query NativeFilteredFactSheets($first: Int!, $after: String, $filter: FilterInput!) { allFactSheets(first: $first, after: $after, filter: $filter) { totalCount pageInfo { endCursor hasNextPage } edges { node { id name type } } } }"
FIT_SHEETS = "query NativeApplicationFit($first: Int!, $after: String, $filter: FilterInput!) { allFactSheets(first: $first, after: $after, filter: $filter) { totalCount pageInfo { endCursor hasNextPage } edges { node { id name type ... on Application { technicalSuitability } } } } }"
TYPE_FACETS = "query NativeFactSheetTypes { allFactSheets(first: 1) { filterOptions { facets { facetKey results { name key } } } } }"
APPLICATION_FACETS = "query NativeApplicationFacets { allFactSheets(first: 1, factSheetType: Application) { filterOptions { facets { facetKey results { name key } } } } }"
QUERIES = {FACT_SHEET, ALL_SHEETS, FILTERED_SHEETS, FIT_SHEETS, TYPE_FACETS, APPLICATION_FACETS}


def _query_variables(document, variables):
    if not isinstance(variables, dict) or document not in QUERIES:
        raise ValueError("SAP LeanIX accepts only typed native query variables")
    if document == FACT_SHEET:
        if set(variables) != {"id"}:
            raise ValueError("SAP LeanIX fact-sheet query takes only an ID")
        _uuid(variables["id"])
    elif document in {TYPE_FACETS, APPLICATION_FACETS}:
        if variables:
            raise ValueError("SAP LeanIX facet queries do not accept sidecars")
    else:
        filtered = document in {FILTERED_SHEETS, FIT_SHEETS}
        expected = {"first", "after", "filter"} if filtered else {"first", "after"}
        if set(variables) != expected or type(variables["first"]) is not int or not 1 <= variables["first"] <= 100:
            raise ValueError("SAP LeanIX forward paging variables are invalid")
        if variables["after"] is not None:
            _text(variables["after"], 4096)
        if filtered:
            value = variables["filter"]
            facets = value.get("facetFilters") if isinstance(value, dict) and set(value) == {"facetFilters"} else None
            if not isinstance(facets, list) or len(facets) != (2 if document == FIT_SHEETS else 1):
                raise ValueError("SAP LeanIX supports only the native type/fit facets")
            for index, facet in enumerate(facets):
                target = "FactSheetTypes" if index == 0 else "technicalSuitability"
                if not isinstance(facet, dict) or set(facet) != {"facetKey", "operator", "keys"} or facet["facetKey"] != target or facet["operator"] != "OR" or not isinstance(facet["keys"], list) or len(facet["keys"]) != 1:
                    raise ValueError("SAP LeanIX native facet variables are invalid")
                _type_key(facet["keys"][0]) if index == 0 else _text(facet["keys"][0], 80)
            if document == FIT_SHEETS and facets[0]["keys"] != ["Application"]:
                raise ValueError("SAP LeanIX technical fit is limited to Applications")


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.origin = "https://" + self.credential.workspace_subdomain + ".leanix.net"
        self.verified, self.access_token = False, None

    async def _http(self, path, *, body=None, token=None):
        if path == TOKEN_PATH:
            if body is not None or token is not None:
                raise ValueError("SAP LeanIX token exchange uses only the native grant")
            headers = {"Authorization": "Basic " + base64.b64encode(("apitoken:" + self.credential.api_token).encode()).decode(), "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
        elif path == GRAPHQL_PATH:
            if not isinstance(body, dict) or set(body) != {"query", "variables"} or body["query"] not in QUERIES or not isinstance(body["variables"], dict) or not token:
                raise ValueError("SAP LeanIX accepts only fixed native read queries")
            _query_variables(body["query"], body["variables"])
            headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"}
            _public(body, self.credential, token)
        else:
            raise ValueError("Unsupported SAP LeanIX native route")
        url = self.origin + path
        assert_exact_url_origin(url, self.origin)
        await self.authority.check()
        _install_privacy()
        private = PRIVATE_REQUEST.set(True)
        try:
            with OutboundTraceProvider().get_tracer(__name__).start_as_current_span("POST", kind=SpanKind.CLIENT,
                attributes={"http.request.method": "POST", "url.full": "https://workspace.leanix.net/native-resource", "url.scheme": "https", "server.address": "[workspace].leanix.net", "server.port": 443}, record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            payload = {"data": {"grant_type": "client_credentials"}} if path == TOKEN_PATH else {"json": body}
                            async with client.stream("POST", url, headers=headers, **payload) as response:
                                status = response.status_code
                                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                                span.set_attribute("http.response.status_code", status)
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > 2_000_000:
                                        raise LeanIXRequestError("SAP LeanIX response exceeds its bound")
                                    content.extend(chunk)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    if isinstance(error, httpx.HTTPError):
                        raise LeanIXRequestError("SAP LeanIX request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        if status != 200:
            outcome = "unauthenticated" if status == 401 else "forbidden" if status == 403 else "rate_limited" if status == 429 else "unverified"
            raise LeanIXRequestError(f"SAP LeanIX returned HTTP {status}; resource access is unverified", status=status, outcome=outcome)
        try:
            if media != "application/json":
                raise ValueError
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except Exception:
            raise LeanIXRequestError("SAP LeanIX response is not documented JSON", status=status) from None

    async def token(self):
        await self.authority.check()
        entry = _cache_entry(self.authority)
        async with entry.lock:
            await self.authority.check()
            if entry.access_token and entry.expires_at > time.monotonic():
                self.access_token = entry.access_token
                return entry
            entry.access_token, entry.expires_at = None, 0
            started = time.monotonic()
            row = await self._http(TOKEN_PATH)
            access, ttl = row.get("access_token"), row.get("expires_in")
            if not isinstance(access, str) or not 1 <= len(access) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in access) or not isinstance(row.get("token_type"), str) or row["token_type"].lower() != "bearer" or row.get("expired") is not False or type(ttl) is not int or not 30 < ttl <= 3600 or row.get("error") or started + ttl - 30 <= time.monotonic():
                raise LeanIXRequestError("SAP LeanIX token response has no valid bounded expiry")
            await self.authority.check()
            entry.access_token, entry.expires_at = access, started + ttl - 30
            self.access_token = access
            return entry

    async def query(self, document, variables=None):
        entry = await self.token()
        try:
            value = await self._http(GRAPHQL_PATH, body={"query": document, "variables": variables or {}}, token=self.access_token)
        except LeanIXRequestError as error:
            if error.status == 401:
                async with entry.lock:
                    if entry.access_token == self.access_token:
                        entry.access_token, entry.expires_at = None, 0
            raise
        errors = value.get("errors")
        if errors is not None and (not isinstance(errors, list) or errors):
            raise LeanIXRequestError("SAP LeanIX GraphQL reported errors; partial data was withheld", status=200, outcome="graphql_error")
        if not isinstance(value.get("data"), dict):
            raise LeanIXRequestError("SAP LeanIX GraphQL data envelope is invalid", status=200)
        return value["data"]

    def project(self, value, fit=False):
        if not isinstance(value, dict):
            raise ValueError("SAP LeanIX fact sheet was not returned; absence is unverified")
        result = {"id": _uuid(value.get("id")), "name": _text(value.get("name"), 1024), "type": _type_key(value.get("type"))}
        if fit and value.get("technicalSuitability") is not None:
            result["technicalSuitability"] = _text(value["technicalSuitability"], 80)
        return _public(result, self.credential, self.access_token)

    async def witness(self):
        data = await self.query(FACT_SHEET, {"id": self.credential.witness_fact_sheet_id})
        result = self.project(data.get("factSheet"))
        if result["id"] != self.credential.witness_fact_sheet_id:
            raise ValueError("SAP LeanIX protected witness differs")
        self.verified = True
        return {"data": result, "reachable": True, "identity_verified": False, "ownership_verified": False, "workspace_identity_verified": False, "http_status": 200}

    async def facets(self, application=False):
        if not self.verified:
            raise ValueError("Read the protected SAP LeanIX witness first")
        data = await self.query(APPLICATION_FACETS if application else TYPE_FACETS)
        connection = data.get("allFactSheets")
        rows = connection.get("filterOptions", {}).get("facets") if isinstance(connection, dict) and isinstance(connection.get("filterOptions"), dict) else None
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("SAP LeanIX facet envelope exceeds its bound or is malformed")
        target = "technicalSuitability" if application else "FactSheetTypes"
        matches = [row for row in rows if isinstance(row, dict) and row.get("facetKey") == target]
        if len(matches) != 1 or not isinstance(matches[0].get("results"), list) or len(matches[0]["results"]) > 1000:
            raise ValueError("SAP LeanIX current facet is unavailable or malformed")
        result = []
        for row in matches[0]["results"]:
            if not isinstance(row, dict):
                raise ValueError("SAP LeanIX facet option is malformed")
            key = _text(row.get("key"), 80) if application else _type_key(row.get("key"))
            result.append({"key": key, "name": _text(row.get("name"), 255)})
        if len({row["key"] for row in result}) != len(result):
            raise ValueError("SAP LeanIX facet keys repeat")
        return _public(result, self.credential, self.access_token)

    async def type_witness(self, key):
        if key not in {row["key"] for row in await self.facets()}:
            raise ValueError("SAP LeanIX fact-sheet type is not currently available")

    def seal(self, value):
        blob = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()

    def unseal(self, token):
        try:
            encoded, signature = token.split(".")
            blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            if not hmac.compare_digest(signature, hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()):
                raise ValueError
            value = json.loads(blob)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except Exception:
            raise ValueError("SAP LeanIX continuation belongs to another or changed authority") from None

    async def page(self, size, token=None, type_key=None, fit=None):
        if not self.verified:
            raise ValueError("Read the protected SAP LeanIX witness first")
        if fit is not None:
            type_key = "Application"
            if fit not in {row["key"] for row in await self.facets(application=True)}:
                raise ValueError("SAP LeanIX technical fit is not currently available")
        if type_key is not None:
            await self.type_witness(type_key)
        scope = hashlib.sha256(json.dumps([size, type_key, fit]).encode()).hexdigest()
        after, seen = None, []
        if token:
            value = self.unseal(token)
            if set(value) != {"scope", "after", "seen"} or value["scope"] != scope or not isinstance(value["seen"], list) or not 1 <= len(value["seen"]) < 100 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in value["seen"]):
                raise ValueError("SAP LeanIX continuation is invalid or exceeds its page bound")
            after, seen = _text(value["after"], 4096), value["seen"]
        variables = {"first": size, "after": after}
        document = ALL_SHEETS
        if type_key is not None:
            facets = [{"facetKey": "FactSheetTypes", "operator": "OR", "keys": [type_key]}]
            if fit is not None:
                facets.append({"facetKey": "technicalSuitability", "operator": "OR", "keys": [fit]})
            variables["filter"] = {"facetFilters": facets}
            document = FIT_SHEETS if fit is not None else FILTERED_SHEETS
        data = await self.query(document, variables)
        connection = data.get("allFactSheets")
        edges, info = (connection.get("edges"), connection.get("pageInfo")) if isinstance(connection, dict) else (None, None)
        if not isinstance(edges, list) or len(edges) > size or not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool:
            raise ValueError("SAP LeanIX page is malformed or exceeds its bound")
        rows = [self.project(edge.get("node"), fit=fit is not None) for edge in edges if isinstance(edge, dict)]
        if len(rows) != len(edges) or len({row["id"] for row in rows}) != len(rows) or type_key is not None and any(row["type"] != type_key for row in rows) or fit is not None and any(row.get("technicalSuitability") != fit for row in rows):
            raise ValueError("SAP LeanIX page returned repeated or out-of-filter fact sheets")
        more, cursor = info["hasNextPage"], info.get("endCursor")
        if cursor is not None:
            cursor = _text(cursor, 4096)
            _public(cursor, self.credential, self.access_token)
        digest = hashlib.sha256(cursor.encode()).hexdigest() if cursor else None
        if more and (not cursor or cursor == after or digest in seen or len(seen) >= 99):
            raise ValueError("SAP LeanIX forward cursor did not advance or exceeded its page bound")
        total = connection.get("totalCount")
        if total is not None and (type(total) is not int or total < 0):
            raise ValueError("SAP LeanIX live total is malformed")
        return {"data": rows, "total": total, "next_page_token": self.seal({"scope": scope, "after": cursor, "seen": seen + [digest]}) if more else None,
            "snapshot_consistency_verified": False, "idempotence_verified": False, "http_status": 200}


class LeanIXNode(WorkflowNode):
    integration_type = "automation-leanix"
    connection_evidence = ConnectionEvidence(noun="SAP LeanIX fact sheet", operation="test_authentication", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return LeanIXNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, LeanIXNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("SAP LeanIX configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["SAP LeanIX credential or configuration is invalid"], "satisfied_set": None}

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
        # The staging loader has resolved the saved credential already. The
        # technical API token is long-lived; its short-lived bearer is minted
        # privately by _Client.token, never stored as the user's credential.
        return _credential(credential_data).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run protected SAP LeanIX fact-sheet reachability evidence; static validation does not prove identity, workspace ownership, roles or API eligibility"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(getattr(self, "_native_authority", None) or self._authority())
        cfg = self.config.config
        witness = await client.witness()
        if cfg.operation == "test_authentication":
            return witness
        if cfg.operation == "list_fact_sheet_types":
            return {"data": await client.facets(), "http_status": 200, "identity_verified": False}
        if cfg.operation == "get_fact_sheet":
            await client.type_witness(cfg.fact_sheet_type)
            result = client.project((await client.query(FACT_SHEET, {"id": cfg.fact_sheet_id})).get("factSheet"))
            if result["id"] != cfg.fact_sheet_id or result["type"] != cfg.fact_sheet_type:
                raise ValueError("SAP LeanIX fact sheet differs from the selected type or ID")
            return {"data": result, "http_status": 200, "identity_verified": False, "ownership_verified": False}
        if cfg.operation == "list_fact_sheets":
            return await client.page(cfg.page_size, cfg.page_token, cfg.fact_sheet_type)
        if cfg.operation == "list_applications_by_technical_fit":
            return await client.page(cfg.page_size, cfg.page_token, fit=cfg.technical_fit)
        raise ValueError("Unsupported SAP LeanIX native operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data)
        if field_name not in {"fact_sheet_id", "fact_sheet_type", "technical_fit"}:
            raise ValueError("Unsupported SAP LeanIX selector")
        # Staging resolves and admits the saved credential before this loader.
        authority = _Authority(credential_data)
        context = context or {}
        type_key = _type_key(context.get("fact_sheet_type")) if field_name == "fact_sheet_id" else None
        client = _Client(authority)
        await client.witness()
        if field_name == "fact_sheet_id":
            page = await client.page(50, page_token, type_key)
            options = [{"value": row["id"], "label": row["name"]} for row in page["data"]]
            next_token = page["next_page_token"]
        else:
            if page_token is not None:
                raise ValueError("SAP LeanIX facets do not accept a pagination cursor")
            options = [{"value": row["key"], "label": row["name"]} for row in await client.facets(application=field_name == "technical_fit")]
            next_token = None
        query = normalize_search(search)
        if query:
            options = [row for row in options if query.casefold() in row["label"].casefold() or query.casefold() in row["value"].casefold()]
        return {"options": options, "next_page_token": next_token}
