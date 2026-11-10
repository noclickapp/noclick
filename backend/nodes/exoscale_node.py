"""Native Exoscale APIv2 metadata reads with exact request signing.
Only documented GET resources are exposed; provider responses are projected before output.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.credentials import credential_access_predicate
from utils import credentials as credential_utils
from utils.encryption import get_encryption
from utils.ssrf import guarded_async_client

TYPE = "exoscale_api_key"
APIS = {"ch-gva-2": "https://api-ch-gva-2.exoscale.com/v2", "de-fra-1": "https://api-de-fra-1.exoscale.com/v2"}
AUTH_KEY = "_exoscale_authority"
CURRENT_ORGANIZATION = object()
MAX_BODY = 4 * 1024 * 1024
UNAVAILABLE = "Exoscale credential is unavailable or its current authority changed"
UNVERIFIED = "Exoscale response could not be verified"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ID = Annotated[StrictStr, Field(pattern="^" + UUID_PATTERN + "$", min_length=36, max_length=36)]
Limit = Annotated[StrictInt, Field(ge=1, le=1000)]
Count = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=255)]
State = Literal["expunging", "starting", "destroying", "running", "stopping", "stopped", "migrating", "error", "destroyed"]


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(c.isspace() or ord(c) < 33 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Enter the issued value without a URL, whitespace or authentication prefix")
    return value


def key(value):
    value = secret(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("API key must be a single opaque header credential")
    return value


class ExoscaleAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-help-url": "https://community.exoscale.com/reference/api/",
        "x-credential-instructions": "Supply an existing API key and secret authorized for the selected zone's metadata GETs. Requests use APIv2 EXO2-HMAC-SHA256 headers, not legacy v1 or Partner API signing. Connection reads protected instance metadata; an empty catalog proves reachability only. The optional expected instance is an existing resource witness, not organization or human identity. This node never issues keys, assumes roles, provisions or controls resources.",
    })
    credential_type: Literal["exoscale_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: Annotated[StrictStr, BeforeValidator(key)] = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="API Secret", repr=False, json_schema_extra={"ui:widget": "password"})
    zone: Literal["ch-gva-2", "de-fra-1"] = Field("ch-gva-2", title="API Zone", description="Only these two exact APIv2 hosts are qualified by this integration. This is zone-local access, not global inventory.")
    expected_instance_id: Optional[ID] = Field(None, title="Expected Instance ID", description="Optional exact existing instance UUID. Every operation checks this protected witness in this zone; it does not establish organization ownership.")

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Exoscale requires its original API key/secret credential")
    try:
        return ExoscaleAPIKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("Exoscale credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("Exoscale credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Cloud Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Resource Names", description="Opt in to instance and anti-affinity group names. IP addresses, labels, private networks, credentials and free-form configuration are always omitted.")


class Catalog(Config):
    max_records: Limit = Field(1000, title="Maximum Catalog Records", description="Local bound on the received unpaged array, not a provider limit or page size. Oversized responses fail without partial results. Completion beyond this response is unknown.")


class ListInstances(Catalog):
    operation: Literal["list_instances"] = op("list_instances", "List Instance Metadata", "Read zone-local instance IDs, states, creation times and instance-type capacity. No query filters or global inventory are assumed.")


class GetInstance(Catalog):
    operation: Literal["get_instance"] = op("get_instance", "Get Instance Metadata", "Verify exact instance UUID against the selected zone's protected catalog, then read its metadata.")
    instance_id: ID = Field(..., title="Instance ID", description="Existing lowercase UUID in the selected API zone.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class ListInstanceTypes(Catalog):
    operation: Literal["list_instance_types"] = op("list_instance_types", "List Instance-Type Capacity", "Read the published instance-type catalog and capacity metadata. This static catalog is not account identity or permission evidence.")


class GetInstanceType(Catalog):
    operation: Literal["get_instance_type"] = op("get_instance_type", "Get Instance-Type Capacity", "Verify exact UUID against the selected endpoint's instance-type catalog, then read capacity metadata.")
    instance_type_id: ID = Field(..., title="Instance Type ID", description="Existing lowercase instance-type UUID.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class ListAntiAffinityGroups(Catalog):
    operation: Literal["list_anti_affinity_groups"] = op("list_anti_affinity_groups", "List Anti-Affinity Metadata", "Read protected group IDs and associated instance IDs with conservative metadata. No descriptions or configuration are returned.")


class GetAntiAffinityGroup(Catalog):
    operation: Literal["get_anti_affinity_group"] = op("get_anti_affinity_group", "Get Anti-Affinity Metadata", "Verify group UUID against the zone-local protected catalog, then read group and associated instance metadata.")
    anti_affinity_group_id: ID = Field(..., title="Anti-Affinity Group ID", description="Existing lowercase group UUID.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


OPERATIONS = (ListInstances, GetInstance, ListInstanceTypes, GetInstanceType, ListAntiAffinityGroups, GetAntiAffinityGroup)
ExoscaleConfig = Annotated[Union[ListInstances, GetInstance, ListInstanceTypes, GetInstanceType, ListAntiAffinityGroups, GetAntiAffinityGroup], Field(discriminator="operation")]


class ExoscaleNodeConfig(NodeConfig[ExoscaleConfig, ExoscaleAPIKeyCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-exoscale"] = "automation-exoscale"

@dataclass(frozen=True)
class ExoscaleCredentialRow:
    """Exoscale's current authority snapshot, using staging's canonical ACL."""
    credential_type: Optional[str]
    owner_id: str
    token_version: int
    updated_at: datetime
    approval_revision: int
    revoked_at: Optional[datetime]
    credential: Any = field(repr=False)


async def fetch_exoscale_authority(pool, identifier, principal, organization_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT c.credential_type,c.owner_id,c.token_version,c.updated_at,"
            f"c.approval_revision,c.revoked_at,c.credential FROM credentials c "
            f"WHERE c.id=$1 AND {credential_access_predicate()}",
            identifier, principal, organization_id,
        )
    return ExoscaleCredentialRow(
        credential_type=row["credential_type"], owner_id=str(row["owner_id"]),
        token_version=row["token_version"], updated_at=row["updated_at"],
        approval_revision=row["approval_revision"], revoked_at=row["revoked_at"],
        credential=row["credential"],
    ) if row else None


@dataclass(eq=False)
class Authority:
    credential: ExoscaleAPIKeyCredential = field(repr=False)
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
        selected = []

        async def loader(identifier, principal, pool, org_id):
            row = await fetch_exoscale_authority(pool, identifier, principal, org_id)
            if row is None:
                return None
            if row.credential_type != TYPE or row.revoked_at is not None or type(row.token_version) is not int or row.token_version < 1:
                raise ValueError(UNAVAILABLE)
            shaped = credential(get_encryption().decrypt_credential(row.credential))
            selected.append((principal, row, shaped))
            return shaped.model_dump()

        # Staging's resolver has no custom-loader hook. Apply its trusted
        # owner/lender checks here so this node can retain the original blob
        # tag and compare the full authority snapshot around each request.
        result = await loader(self.credential_id, self.user_id, self.pool, self.organization_id)
        if not result and self.workflow_id:
            owner = await credential_utils.get_workflow_owner_id(self.pool, self.workflow_id)
            if (owner and owner != self.user_id and
                    await credential_utils.is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id)):
                result = await loader(self.credential_id, owner, self.pool, self.organization_id)
        if not result and self.workflow_id:
            lender = await credential_utils.credential_lender(self.pool, self.workflow_id, self.credential_id)
            if lender and lender != str(self.user_id):
                result = await loader(self.credential_id, lender, self.pool, self.organization_id)
        if not result or not selected:
            raise ValueError(UNAVAILABLE)
        principal, row, shaped = selected[-1]
        return shaped, (principal, row)

    async def require_current(self):
        if self.credential_id:
            if self.resolve_organization and await self.current_organization() != self.organization_id:
                raise ValueError(UNAVAILABLE)
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor:
                raise ValueError(UNAVAILABLE)


_PRIVATE = ContextVar("exoscale_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Exoscale transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"Exoscale returned HTTP {status}; verify the current key, zone and metadata read permissions")


class OutcomeUnverified(RuntimeError):
    pass


def sign_request(request, cred, expiration_ts):
    """Use the official ExoscaleV2Auth's five UTF-8 segments and Base64 digest."""
    if type(expiration_ts) is not int or expiration_ts < 0:
        raise ValueError("Exoscale signing expiry is invalid")
    url = urlsplit(str(request.url))
    params = parse_qs(url.query)
    signed_params = sorted(params)
    if any(len(params[name]) != 1 for name in signed_params):
        raise ValueError("Exoscale metadata signing accepts only single-valued query arguments")
    parts = [
        f"{request.method} {url.path}".encode("utf-8"),
        request.content or b"",
        "".join(params[name][0] for name in signed_params).encode("utf-8"),
        b"",
        str(expiration_ts).encode("utf-8"),
    ]
    signature = base64.standard_b64encode(hmac.new(cred.api_secret.encode("utf-8"), b"\n".join(parts), hashlib.sha256).digest()).decode("ascii")
    query = ",signed-query-args=" + ";".join(signed_params) if signed_params else ""
    request.headers["Authorization"] = f"EXO2-HMAC-SHA256 credential={cred.api_key}{query},expires={expiration_ts},signature={signature}"


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def request(auth, route):
    if not re.fullmatch(r"(?:instance|instance-type|anti-affinity-group)(?:/" + UUID_PATTERN + r")?", route):
        raise ValueError("Unsupported Exoscale metadata route")
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                req = client.build_request("GET", APIS[auth.credential.zone] + "/" + route, headers={"Accept": "application/json"})
                sign_request(req, auth.credential, int(time.time() + 10 * 60))
                response = await client.send(req, stream=True)
                try:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("Exoscale response exceeds the local 4 MiB bound; no partial output is returned")
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
    except httpx.RequestError:
        await auth.require_current()
        raise OutcomeUnverified("Exoscale transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Invalid resource creation time")
    if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("Creation time must have an offset")
    return value


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class InstanceType(Response):
    id: ID
    size: Optional[Literal["large", "huge", "jumbo", "medium", "mega", "small", "extra-large", "titan48c", "titan", "micro", "colossus", "tiny"]] = None
    family: Optional[Literal["gpu3", "gpua30", "gpu3080ti", "gpu2", "gpu", "memory", "gpua5000", "gpub300", "gpurtx6000pro", "storage", "standard", "colossus", "cpu"]] = None
    cpus: Optional[Count] = None
    gpus: Optional[Count] = None
    memory: Optional[Count] = None


class Instance(Response):
    id: ID
    state: Optional[State] = None
    created_at: Optional[Annotated[StrictStr, BeforeValidator(timestamp)]] = Field(None, alias="created-at")
    disk_size: Optional[Annotated[StrictInt, Field(ge=10, le=51200)]] = Field(None, alias="disk-size")
    instance_type: Optional[InstanceType] = Field(None, alias="instance-type")
    name: Optional[Name] = None


class AntiAffinityGroup(Response):
    id: ID
    name: Optional[Name] = None
    instances: Optional[Annotated[list[Instance], Field(max_length=1000)]] = None


RESOURCE = {Instance: "instance", InstanceType: "instance_type", AntiAffinityGroup: "anti_affinity_group"}
CATALOG = {Instance: ("instance", "instances"), InstanceType: ("instance-type", "instance-types"), AntiAffinityGroup: ("anti-affinity-group", "anti-affinity-groups")}


def projected(model, raw, include_names=False):
    if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors", "message")):
        raise OutcomeUnverified(UNVERIFIED)
    selected = {}
    for name, fld in model.model_fields.items():
        source = fld.alias or name
        if source not in raw or name == "name" and not include_names:
            continue
        value = raw[source]
        if name == "instance_type" and value is not None:
            value = projected(InstanceType, value)
            value.pop("resource_type")
        elif name == "instances" and value is not None:
            if not isinstance(value, list) or len(value) > 1000:
                raise OutcomeUnverified(UNVERIFIED)
            value = [projected(Instance, item, include_names) for item in value]
            if len({item["id"] for item in value}) != len(value):
                raise OutcomeUnverified("Exoscale returned duplicate group instance IDs")
            for item in value:
                item.pop("resource_type")
        selected[source] = value
    try:
        result = model.model_validate(selected).model_dump(exclude_unset=True, by_alias=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None
    result["resource_type"] = RESOURCE[model]
    return result


def catalog(model, raw, maximum, include_names=False):
    envelope = CATALOG[model][1]
    if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors", "message")) or envelope not in raw:
        raise OutcomeUnverified(UNVERIFIED)
    records = raw[envelope]
    if not isinstance(records, list) or len(records) > maximum:
        raise OutcomeUnverified("Exoscale catalog is malformed or exceeds its local bound; no partial output or invented continuation")
    result = [projected(model, item, include_names) for item in records]
    if len({item["id"] for item in result}) != len(result):
        raise OutcomeUnverified("Exoscale returned duplicate catalog IDs")
    return result


async def detail(auth, model, identifier, maximum, include_names=False):
    route = CATALOG[model][0]
    members = catalog(model, await request(auth, route), maximum)
    if identifier not in {item["id"] for item in members}:
        raise OutcomeUnverified("Requested Exoscale resource is absent from the selected zone's catalog")
    item = projected(model, await request(auth, f"{route}/{identifier}"), include_names)
    if item["id"] != identifier:
        raise OutcomeUnverified("Exoscale returned a different resource ID")
    return item


async def operate(auth, cfg):
    expected = auth.credential.expected_instance_id
    if expected is not None:
        witness = projected(Instance, await request(auth, f"instance/{expected}"))
        if witness["id"] != expected:
            raise OutcomeUnverified("Expected Exoscale instance witness did not match")
    models = {ListInstances: Instance, ListInstanceTypes: InstanceType, ListAntiAffinityGroups: AntiAffinityGroup}
    for config_type, model in models.items():
        if isinstance(cfg, config_type):
            items = catalog(model, await request(auth, CATALOG[model][0]), cfg.max_records, cfg.include_names)
            return {"items": items, "returned_count": len(items), "provider_paging": "not_documented", "inventory_completion": "unknown", "snapshot_consistent": False}
    if isinstance(cfg, GetInstance):
        return await detail(auth, Instance, cfg.instance_id, cfg.max_records, cfg.include_names)
    if isinstance(cfg, GetInstanceType):
        return await detail(auth, InstanceType, cfg.instance_type_id, cfg.max_records, cfg.include_names)
    if isinstance(cfg, GetAntiAffinityGroup):
        return await detail(auth, AntiAffinityGroup, cfg.anti_affinity_group_id, cfg.max_records, cfg.include_names)
    raise ValueError("Unsupported Exoscale metadata operation")


class ExoscaleNode(WorkflowNode):
    integration_type = "automation-exoscale"
    credential_provider_labels = {"exoscale": "Exoscale Account"}
    connection_evidence = ConnectionEvidence(operation="list_instances", noun="zone-local Exoscale instances", label_keys=("id",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ExoscaleNodeConfig

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
                result = await validation_context.run_operation("list_instances", {})
                return (True, None) if result.get("status") == "success" else (None, UNVERIFIED)
            auth = await Authority.create(raw)
            await operate(auth, ListInstances())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.status_code in (401, 403) else (None, str(error))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, ExoscaleNodeConfig) or self.config.credentials is None:
            raise ValueError("Exoscale API key and secret are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        result = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "zone": auth.credential.zone, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if not isinstance(auth, Authority) or not auth.credential_id or not auth.user_id or context.get("_user_id") != auth.user_id:
            raise ValueError("Exoscale pickers require a current saved credential authorized for this actor")
        if page_token is not None:
            raise ValueError("Exoscale metadata has no documented continuation token")
        if search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("Exoscale picker search is invalid")
        configs = {"instance_id": ListInstances, "instance_type_id": ListInstanceTypes, "anti_affinity_group_id": ListAntiAffinityGroups}
        if field_name not in configs:
            raise ValueError("Unsupported Exoscale picker")
        await auth.require_current()
        result = await operate(auth, configs[field_name]())
        options = [{"value": item["id"], "label": item["id"]} for item in result["items"]]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        await auth.require_current()
        return {"options": options, "next_page_token": None}
