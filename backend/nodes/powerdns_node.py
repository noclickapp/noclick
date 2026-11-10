"""PowerDNS Authoritative: closed public HTTPS metadata GETs only.

The published Zone allOf points to an array. The explicit HTML object contract
controls detail parsing; records, comments and capability URLs are never output.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import unquote, urlsplit

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.encryption import get_encryption
from utils import ssrf
from utils.ssrf import SSRFError, normalize_https_origin

TYPE = "powerdns_api_key"
AUTH_KEY = "_powerdns_authority"
CURRENT_ORGANIZATION = object()
MAX_BODY = 4 * 1024 * 1024
MAX_CATALOG = 10000
UNAVAILABLE = "PowerDNS credential is unavailable or its current authority changed"
UNVERIFIED = "PowerDNS metadata response could not be verified"
Count = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
Limit = Annotated[StrictInt, Field(ge=1, le=200)]
Serial = Annotated[StrictInt, Field(ge=0, le=4294967295)]
Text = Annotated[StrictStr, Field(min_length=1, max_length=512)]


def normalize_api_origin(value):
    if not isinstance(value, str) or value != value.strip() or len(value) > 2048:
        raise ValueError("Supply a public HTTPS API origin")
    try:
        origin = normalize_https_origin(value, field_name="PowerDNS API origin")
        parts = urlsplit(origin)
        host = parts.hostname
        if not host or parts.port == 0 or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
        return origin
    except Exception:
        raise ValueError("PowerDNS requires an exact public HTTPS origin with an optional intentional port; paths, userinfo, private/local hosts and overrides are unsupported") from None


def resource_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or not re.fullmatch(r"[A-Za-z0-9_.~%-]+", value) or re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError("Use the exact URL-safe resource ID returned by the catalog")
    decoded = unquote(value)
    if decoded in {".", ".."} or any(c in decoded for c in "/\\?#%") or any(ord(c) < 33 or ord(c) == 127 for c in decoded):
        raise ValueError("The catalog resource ID is not safe for a single URL segment")
    return value


ResourceID = Annotated[StrictStr, BeforeValidator(resource_id), Field(min_length=1, max_length=512)]


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Supply only the issued X-API-Key value")
    return value


class PowerDNSCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-help-url": "https://docs.powerdns.com/authoritative/http-api/index.html",
        "x-credential-instructions": "Supply an existing X-API-Key and a publicly reachable HTTPS API origin. The selected server ID must be present in the protected catalog with daemon_type authoritative. localhost is the documented server resource label, not the API host. This proves resource access, not a user or tenant identity. No key issuance, webserver enabling, trust changes or private network workaround.",
    })
    credential_type: Literal["powerdns_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_origin: Annotated[StrictStr, BeforeValidator(normalize_api_origin)] = Field(..., title="API Origin", description="Exact public HTTPS origin, e.g. https://dns.example.com:8443. No /api/v1 path, credentials, query or fragment. DNS resolution and connection remain strictly public.")
    api_key: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    server_id: Annotated[StrictStr, BeforeValidator(resource_id), Field(max_length=512)] = Field("localhost", title="Server ID", description="Exact protected catalog ID. The documented localhost value is a resource label, never a host or networking exception.")

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("PowerDNS requires its original supplied API-key credential")
    try:
        return PowerDNSCredential.model_validate(raw)
    except Exception:
        raise ValueError("PowerDNS credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("PowerDNS credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "DNS Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include DNS Names and Zone Locators", description="Opt in to displayed zone IDs/names and RRset names. Opaque zone IDs can encode DNS names; they stay internal by default. DNS record data and comments are always omitted.")


class Bounded(Config):
    max_results: Limit = Field(20, title="Maximum Results", description="Local 1–200 output cap for an unpaged array. No provider paging, total or global completion is inferred.")


class ListServers(Bounded):
    operation: Literal["list_servers"] = op("list_servers", "List Authoritative Server Metadata", "Verify the selected authoritative daemon, then project its accessible authoritative server catalog. No configuration URLs or Recursor parity.")


class GetServer(Config):
    operation: Literal["get_server"] = op("get_server", "Get Selected Server Metadata", "Verify the selected catalog witness and independently read its exact server detail.")


class ListZones(Bounded):
    operation: Literal["list_zones"] = op("list_zones", "List Zone Metadata", "Read the selected server's zone catalog with dnssec=false. Zone IDs and names are internal unless explicitly opted in.")


class ZoneConfig(Config):
    zone_id: ResourceID = Field(..., title="Catalog Zone ID", description="Select the exact opaque ID from this server's current catalog. Never derive it from a zone name. An explicit copied catalog ID is verified again before detail reads.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class GetZone(ZoneConfig):
    operation: Literal["get_zone"] = op("get_zone", "Get Zone Metadata", "Verify current server/catalog ancestry, then request rrsets=false and project the published direct zone object.")
    include_record_count: StrictBool = Field(False, title="Request Provider Record Count", description="Explicitly request and validate the provider's record_count. It is a record count, never an invented RRset count.")


class ListRRSets(ZoneConfig, Bounded):
    operation: Literal["list_rrsets"] = op("list_rrsets", "List RRset Metadata", "Request rrsets=true only after current catalog ancestry. Return bounded type/TTL metadata and optional names, never records/RDATA/comments.")
    include_record_count: StrictBool = Field(False, title="Request Provider Record Count", description="Explicitly request record_count, independently of the local RRset output cap.")


OPERATIONS = (ListServers, GetServer, ListZones, GetZone, ListRRSets)
PowerDNSConfig = Annotated[Union[ListServers, GetServer, ListZones, GetZone, ListRRSets], Field(discriminator="operation")]


class PowerDNSNodeConfig(NodeConfig[PowerDNSConfig, PowerDNSCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-powerdns"] = "automation-powerdns"


@dataclass(frozen=True)
class PowerDNSAuthorityRow:
    credential_type: str
    owner_id: str
    token_version: int
    updated_at: Any
    approval_revision: int
    revoked_at: Any
    credential: Any = field(repr=False)


async def load_authority_row(pool, identifier):
    # Access and workflow-owner/lender fallback are resolved by staging's
    # canonical resolver before this snapshot is read. Keep the original blob
    # discriminator and row revisions to discard a racing response.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT credential_type,owner_id,token_version,updated_at,"
            "approval_revision,revoked_at,credential FROM credentials WHERE id=$1",
            identifier,
        )
    return PowerDNSAuthorityRow(**{key: row[key] for key in PowerDNSAuthorityRow.__dataclass_fields__}) if row else None


def guarded_async_client(*, require_public=True, **kwargs):
    # Staging's pinned client supports an install-wide private-network opt-out.
    # PowerDNS deliberately refuses that mode instead of weakening its contract.
    if require_public is not True or ssrf.allow_private_hosts():
        raise SSRFError("PowerDNS requires public-only outbound networking")
    return ssrf.guarded_async_client(**kwargs)


@dataclass(eq=False)
class Authority:
    credential: PowerDNSCredential = field(repr=False)
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
        result = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if not result:
            raise ValueError(UNAVAILABLE)
        row = await load_authority_row(self.pool, self.credential_id)
        if row is None or row.credential_type != TYPE or row.revoked_at is not None or type(row.token_version) is not int or row.token_version < 1:
            raise ValueError(UNAVAILABLE)
        shaped = credential(get_encryption().decrypt_credential(row.credential))
        if credential(result) != shaped:
            raise ValueError(UNAVAILABLE)
        return shaped, row

    async def require_current(self):
        if self.credential_id:
            if self.resolve_organization and await self.current_organization() != self.organization_id:
                raise ValueError(UNAVAILABLE)
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor:
                raise ValueError(UNAVAILABLE)



_PRIVATE = ContextVar("powerdns_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "PowerDNS transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        meaning = "key authentication was rejected" if status == 401 else "metadata access is forbidden" if status == 403 else "resource was not found" if status == 404 else "rate limit reached; no automatic retry" if status == 429 else "request outcome is not successful"
        super().__init__(f"PowerDNS returned HTTP {status}: {meaning}")


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def request(auth, route, params=None):
    if not isinstance(route, str) or not re.fullmatch(r"/servers(?:/[A-Za-z0-9_.~%-]+(?:/zones(?:/[A-Za-z0-9_.~%-]+)?)?)?", route):
        raise ValueError("Unsupported PowerDNS metadata route")
    parts = route.split("/")
    for identifier in parts[2:]:
        if identifier != "zones":
            resource_id(identifier)
    params = params or {}
    zone_catalog = len(parts) == 4 and parts[-1] == "zones"
    zone_detail = len(parts) == 5 and parts[3] == "zones"
    allowed = {"dnssec"} if zone_catalog else {"rrsets", "record_count"} if zone_detail else set()
    if set(params) - allowed or any(value not in {"true", "false"} for value in params.values()):
        raise ValueError("Unsupported PowerDNS metadata query")
    if zone_catalog and params != {"dnssec": "false"}:
        raise ValueError("PowerDNS catalog requires dnssec=false")
    if zone_detail and set(params) != allowed:
        raise ValueError("PowerDNS detail requires explicit metadata query flags")
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(require_public=True, timeout=30, follow_redirects=False, trust_env=False) as client:
                req = client.build_request("GET", auth.credential.api_origin + '/api/v1' + route, params=params, headers={"X-API-Key": auth.credential.api_key, "Accept": "application/json"})
                await auth.require_current()
                response = await client.send(req, stream=True)
                try:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("PowerDNS response exceeds the local 4 MiB bound; no partial output")
                    await auth.require_current()
                    if response.status_code != 200:
                        raise ApiError(response.status_code)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        return json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
                finally:
                    await response.aclose()
    except (httpx.RequestError, SSRFError):
        await auth.require_current()
        raise OutcomeUnverified("PowerDNS transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)



class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Server(Response):
    id: ResourceID
    type: Literal["Server"]
    daemon_type: Literal["authoritative", "recursor"]
    version: Text


class Zone(Response):
    # Provider-authored zone catalog/detail examples omit this optional marker.
    # zone() excludes unset fields, so an absent marker is never synthesized.
    type: Literal["Zone"] = "Zone"
    kind: Literal["Native", "Master", "Slave", "Producer", "Consumer"]
    serial: Serial
    notified_serial: Optional[Serial] = None
    last_check: Optional[Count] = None
    id: Optional[ResourceID] = None
    name: Optional[Text] = None


class RRSet(Response):
    type: Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9-]{0,31}$")]
    ttl: Serial
    name: Optional[Text] = None


def server(raw):
    if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors")):
        raise OutcomeUnverified(UNVERIFIED)
    try:
        return Server.model_validate({key: raw[key] for key in ("id", "type", "daemon_type", "version")}).model_dump()
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None


def zone(raw, names=False):
    if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors")):
        raise OutcomeUnverified(UNVERIFIED)
    try:
        identifier = resource_id(raw["id"])
        selected = {key: raw[key] for key in ("type", "kind", "serial", "notified_serial", "last_check") if key in raw}
        if names:
            selected["id"] = identifier
            if "name" in raw:
                selected["name"] = raw["name"]
        return identifier, Zone.model_validate(selected).model_dump(exclude_unset=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None


def array(raw):
    if not isinstance(raw, list) or len(raw) > MAX_CATALOG:
        raise OutcomeUnverified("PowerDNS unpaged catalog exceeds the local bound or has an invalid array shape")
    return raw


def bounded(items, maximum):
    return {"items": items[:maximum], "returned_count": min(len(items), maximum), "observed_array_count": len(items), "local_limit": maximum, "truncated": len(items) > maximum, "provider_pagination": False, "completion": "unknown", "snapshot_consistent": False}


async def server_catalog(auth):
    catalog = [server(row) for row in array(await request(auth, "/servers"))]
    if len({row["id"] for row in catalog}) != len(catalog):
        raise OutcomeUnverified(UNVERIFIED)
    selected = next((row for row in catalog if row["id"] == auth.credential.server_id), None)
    if selected is None or selected["daemon_type"] != "authoritative":
        raise OutcomeUnverified("Selected PowerDNS authoritative server is absent from the protected catalog")
    return catalog, selected


async def zone_catalog(auth, names=False):
    route = "/servers/" + auth.credential.server_id + "/zones"
    catalog = [zone(row, names) for row in array(await request(auth, route, {"dnssec": "false"}))]
    if len({identifier for identifier, _ in catalog}) != len(catalog):
        raise OutcomeUnverified(UNVERIFIED)
    return catalog


async def operate(auth, cfg):
    catalog, witness = await server_catalog(auth)
    server_id = auth.credential.server_id
    if isinstance(cfg, ListServers):
        return bounded([row for row in catalog if row["daemon_type"] == "authoritative"], cfg.max_results)
    if isinstance(cfg, GetServer):
        detail = server(await request(auth, "/servers/" + server_id))
        if detail["id"] != server_id or detail["daemon_type"] != "authoritative":
            raise OutcomeUnverified(UNVERIFIED)
        return detail
    zones = await zone_catalog(auth, cfg.include_names)
    if isinstance(cfg, ListZones):
        return bounded([row for _, row in zones], cfg.max_results)
    if not isinstance(cfg, (GetZone, ListRRSets)) or cfg.zone_id not in {identifier for identifier, _ in zones}:
        raise OutcomeUnverified("PowerDNS zone locator is absent from the selected server's current catalog")
    raw = await request(auth, "/servers/" + server_id + "/zones/" + cfg.zone_id, {"rrsets": "true" if isinstance(cfg, ListRRSets) else "false", "record_count": "true" if cfg.include_record_count else "false"})
    identifier, result = zone(raw, cfg.include_names)
    if identifier != cfg.zone_id:
        raise OutcomeUnverified("PowerDNS returned a different zone locator")
    if cfg.include_record_count:
        try:
            count = raw["record_count"]
            if type(count) is not int or not 0 <= count <= 9223372036854775807:
                raise ValueError()
            result["record_count"] = count
        except Exception:
            raise OutcomeUnverified("PowerDNS requested record count could not be verified") from None
    if isinstance(cfg, ListRRSets):
        try:
            rows = array(raw["rrsets"])
            parsed, seen = [], set()
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"] or len(row["name"]) > 512:
                    raise ValueError()
                selected = {key: row[key] for key in ("type", "ttl")}
                if cfg.include_names:
                    selected["name"] = row["name"]
                item = RRSet.model_validate(selected).model_dump(exclude_unset=True)
                key = (row["name"], item["type"])
                if key in seen:
                    raise ValueError()
                seen.add(key)
                parsed.append(item)
            result["rrset_metadata"] = bounded(parsed, cfg.max_results)
        except Exception:
            raise OutcomeUnverified("PowerDNS RRset metadata could not be verified") from None
    return result


class PowerDNSNode(WorkflowNode):
    integration_type = "automation-powerdns"
    credential_provider_labels = {"powerdns": "Powerdns Account"}
    connection_evidence = ConnectionEvidence(operation="list_servers", noun="accessible authoritative server metadata", label_keys=("id",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return PowerDNSNodeConfig

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
                result = await validation_context.run_operation("list_servers", {})
                return (True, None) if result.get("status") == "success" else (None, UNVERIFIED)
            auth = await Authority.create(raw)
            await operate(auth, ListServers())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.status_code in (401, 403) else (None, str(error))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, PowerDNSNodeConfig) or self.config.credentials is None:
            raise ValueError("PowerDNS supplied key, public origin and server witness are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        result = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if not isinstance(auth, Authority) or not auth.credential_id or not auth.user_id or context.get("_user_id") != auth.user_id:
            raise ValueError("PowerDNS picker requires a current saved credential authorized for this actor")
        if field_name != "zone_id" or page_token is not None:
            raise ValueError("PowerDNS has only an unpaged current zone-catalog picker")
        names = context.get("include_names", False)
        if type(names) is not bool:
            raise ValueError("PowerDNS picker name opt-in must be boolean")
        if search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("PowerDNS picker search is invalid")
        await auth.require_current()
        await server_catalog(auth)
        rows = array(await request(auth, "/servers/" + auth.credential.server_id + "/zones", {"dnssec": "false"}))
        catalog = [zone(row, names) for row in rows]
        if len({identifier for identifier, _ in catalog}) != len(catalog):
            raise OutcomeUnverified(UNVERIFIED)
        options = [{"value": identifier, "label": item.get("name", identifier) if names else "Zone " + str(index + 1)} for index, (identifier, item) in enumerate(catalog[:200])]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        await auth.require_current()
        return {"options": options, "next_page_token": None}
