"""Native HetrixTools v3 protected metadata reads.
Closed GET routes and projections preserve actual scope/resource witnesses without identity claims.
"""
from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_serializer, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.encryption import get_encryption
from utils.ssrf import guarded_async_client

TYPE = "hetrixtools_api_key"
API = "https://api.hetrixtools.com/v3"
AUTH_KEY = "_hetrixtools_authority"
CURRENT_ORGANIZATION = object()
MAX_BODY = 4 * 1024 * 1024
UNAVAILABLE = "HetrixTools credential is unavailable or its current authority changed"
UNVERIFIED = "HetrixTools response could not be verified"
ID = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9]{32}$", min_length=32, max_length=32)]
Text = Annotated[StrictStr, Field(max_length=65536)]
Count = Annotated[StrictInt, Field(ge=0, le=9007199254740991)]
Page = Annotated[StrictInt, Field(ge=1, le=10000)]
PageSize = Annotated[StrictInt, Field(ge=1, le=200)]
Percentage = Annotated[StrictFloat, Field(ge=0, le=100, allow_inf_nan=False)]


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Enter the issued API key without a URL, whitespace or authentication prefix")
    return value


class HetrixToolsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.hetrixtools.com/api-key-scope/",
        "x-credential-instructions": "Supply an existing v3 API key. Bearer headers go only to api.hetrixtools.com/v3. Connection reads GET /account/api/scope: actual permitted calls/assets, not principal or tenant identity. This node does not use legacy key-in-path APIs or issue keys. Monitor child reads additionally require GET Uptime Monitors for an independent parent witness. The provider enforces endpoint and asset permissions; scope names are not guessed.",
    })
    credential_type: Literal["hetrixtools_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("HetrixTools requires its original v3 API-key credential")
    try:
        return HetrixToolsAPIKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("HetrixTools credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("HetrixTools credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Monitoring Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to monitor/status-page names. Targets, URLs, notes, contact lists, IPs and configuration are always omitted.")


class Paging(Config):
    page: Page = Field(1, title="Page", description="One provider page per run. Local maximum 10,000; no automatic scans or retries.")
    per_page: PageSize = Field(20, title="Results per Page", description="Documented maximum 200 for monitors, downtimes and maintenance; status pages use maximum 100.")


class MonitorScope(Config):
    monitor_id: ID = Field(..., title="Uptime Monitor ID", description="Exact existing 32-character monitor ID. Child reads first verify this monitor through the protected ID filter.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class GetAPIScope(Config):
    operation: Literal["get_api_scope"] = op("get_api_scope", "Get API Read-Permission Witness", "Read the actual key scope and permitted asset IDs. This endpoint proves protected reachability, not account or human identity.")


class ListMonitors(Paging):
    operation: Literal["list_uptime_monitors"] = op("list_uptime_monitors", "List Uptime Monitor Metadata", "Read one bounded monitor page, retaining only IDs, type, status and times.")
    uptime_status: Optional[Literal["up", "down"]] = Field(None, title="Uptime Status")
    monitor_status: Optional[Literal["active", "paused", "disabled", "maint", "maint_dnd"]] = Field(None, title="Monitor Status")
    monitor_type: Optional[Literal["website", "ping", "service", "smtp", "heartbeat"]] = Field(None, title="Monitor Type")


class GetMonitor(MonitorScope):
    operation: Literal["get_uptime_monitor"] = op("get_uptime_monitor", "Get Uptime Monitor Metadata", "Use documented GET /uptime-monitors?id=... and verify the exact returned monitor; no invented detail route.")


class GetReport(MonitorScope):
    operation: Literal["get_uptime_report"] = op("get_uptime_report", "Get Uptime Report", "Read daily/summary/historical uptime percentages and downtime counts after protected monitor verification. Network timing/hourly diagnostics are omitted.")
    days: Annotated[StrictInt, Field(ge=1, le=30)] = Field(7, title="Recent Days")
    month: Optional[Annotated[StrictStr, Field(pattern=r"^(19|20)\d{2}-(0[1-9]|1[0-2])$", min_length=7, max_length=7)]] = Field(None, title="Month", description="Optional YYYY-MM; provider ignores days when supplied. Report timezone is fixed UTC.")


class ListDowntimes(Paging, MonitorScope):
    operation: Literal["list_downtimes"] = op("list_downtimes", "List Monitor Downtimes", "Read a single monitor's downtime IDs, start/end timestamps and maintenance flags. Date bounds are inclusive in the published examples.")
    start_after: Optional[Count] = Field(None, title="Started At or After", description="Optional nonnegative Unix timestamp.")
    start_before: Optional[Count] = Field(None, title="Started At or Before", description="Optional nonnegative Unix timestamp.")

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.start_after is not None and self.start_before is not None and self.start_after > self.start_before:
            raise ValueError("Start-after must not exceed start-before")
        return self


class ListStatusPages(Paging):
    operation: Literal["list_status_pages"] = op("list_status_pages", "List Status-Page Metadata", "Read IDs, page type and monitor count. URLs, announcements, Twitter users and access settings are omitted.")
    per_page: Annotated[StrictInt, Field(ge=1, le=100)] = Field(20, title="Results per Page", description="Documented status-page maximum 100; local page maximum 10,000.")


class ListMaintenance(Paging, MonitorScope):
    operation: Literal["list_scheduled_maintenance"] = op("list_scheduled_maintenance", "List Monitor Scheduled Maintenance", "Read one page filtered by the exact protected monitor, checking every returned parent ID. No maintenance state or notification changes.")


OPERATIONS = (GetAPIScope, ListMonitors, GetMonitor, GetReport, ListDowntimes, ListStatusPages, ListMaintenance)
HetrixToolsConfig = Annotated[Union[GetAPIScope, ListMonitors, GetMonitor, GetReport, ListDowntimes, ListStatusPages, ListMaintenance], Field(discriminator="operation")]


class HetrixToolsNodeConfig(NodeConfig[HetrixToolsConfig, HetrixToolsAPIKeyCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-hetrixtools"] = "automation-hetrixtools"


@dataclass(frozen=True)
class HetrixToolsCredentialAuthority:
    credential_type: str
    owner_id: str
    token_version: int
    updated_at: datetime
    approval_revision: int
    revoked_at: Optional[datetime]
    credential: Any = field(repr=False)


async def fetch_credential_authority(pool, credential_id):
    """Snapshot an already resolved key; authorization stays in the shared resolver."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT credential_type, owner_id, token_version, updated_at, "
            "approval_revision, revoked_at, credential FROM credentials WHERE id=$1",
            credential_id,
        )
    return HetrixToolsCredentialAuthority(
        credential_type=row["credential_type"], owner_id=str(row["owner_id"]),
        token_version=row["token_version"], updated_at=row["updated_at"],
        approval_revision=row["approval_revision"], revoked_at=row["revoked_at"],
        credential=row["credential"],
    ) if row else None


@dataclass(eq=False)
class Authority:
    credential: HetrixToolsAPIKeyCredential = field(repr=False)
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
        # Let staging's resolver own runner/owner/lender authorization. The raw
        # row is a local snapshot only; it never grants access or selects a key.
        result = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if not result:
            raise ValueError(UNAVAILABLE)
        row = await fetch_credential_authority(self.pool, self.credential_id)
        if row is None or row.credential_type != TYPE or row.revoked_at is not None or type(row.token_version) is not int or row.token_version < 1:
            raise ValueError(UNAVAILABLE)
        shaped = credential(get_encryption().decrypt_credential(row.credential))
        if shaped != credential(result):
            raise ValueError(UNAVAILABLE)
        return shaped, row

    async def require_current(self):
        if self.credential_id:
            if self.resolve_organization and await self.current_organization() != self.organization_id:
                raise ValueError(UNAVAILABLE)
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor:
                raise ValueError(UNAVAILABLE)


_PRIVATE = ContextVar("hetrixtools_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "HetrixTools transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        meaning = {401: "authentication rejected", 403: "permission denied"}.get(status, "provider outcome unverified")
        super().__init__(f"HetrixTools returned HTTP {status}: {meaning}")


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
    """Closed fixed-host GET routes; token remains in the Bearer header."""
    allowed = {"account/api/scope", "uptime-monitors", "status-pages", "schedule-maintenance"}
    if route not in allowed and not re.fullmatch(r"uptime-monitors/[A-Za-z0-9]{32}/(?:report|downtimes)", route):
        raise ValueError("Unsupported HetrixTools route")
    params = params or {}
    keys = {"account/api/scope": set(), "uptime-monitors": {"page", "per_page", "id", "type", "uptime_status", "monitor_status"}, "status-pages": {"page", "per_page"}, "schedule-maintenance": {"page", "per_page", "monitor_id"}}
    valid = keys.get(route, {"days", "month", "timezone", "hourly_stats"} if route.endswith("/report") else {"page", "per_page", "start_before", "start_after"})
    if not isinstance(params, dict) or set(params) - valid:
        raise ValueError("Unsupported HetrixTools query")
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", API + "/" + route, params=params, headers={"Accept": "application/json", "Authorization": "Bearer " + auth.credential.api_key}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("HetrixTools response exceeds the local 4 MiB bound; no partial output")
                    await auth.require_current()
                    if response.status_code != 200:
                        raise ApiError(response.status_code)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        result = json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
                    if not isinstance(result, dict) or "error" in result or "error_message" in result or "status" in result:
                        raise OutcomeUnverified(UNVERIFIED)
                    return result
    except httpx.RequestError:
        await auth.require_current()
        raise OutcomeUnverified("HetrixTools transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


class Response(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Monitor(Response):
    id: ID
    type: Optional[Literal["website", "ping", "service", "smtp", "heartbeat"]] = None
    uptime_status: Optional[Literal["up", "down"]] = None
    monitor_status: Optional[Literal["active", "paused", "disabled", "maint", "maint_dnd"]] = None
    created_at: Optional[Count] = None
    last_check: Optional[Count] = None
    last_status_change: Optional[Count] = None
    name: Optional[Text] = None


class Downtime(Response):
    id: ID
    start: Count
    end: Count
    maintenance: StrictBool


class StatusPage(Response):
    id: ID
    type: Literal["blacklist", "uptime"]
    monitors: Annotated[list[ID], Field(max_length=10000)]
    name: Optional[Text] = None


def schedule_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", value):
        raise ValueError("Invalid maintenance time")
    datetime.strptime(value, "%Y-%m-%d %H:%M")
    return value


class ScheduledMaintenance(Response):
    id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", min_length=1, max_length=128)]
    monitor_id: ID
    start: Annotated[StrictStr, BeforeValidator(schedule_time)]
    end: Annotated[StrictStr, BeforeValidator(schedule_time)]
    timezone: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    with_notifications: StrictBool
    recurring: StrictBool
    recurring_time: Count
    recurring_time_type: Literal["", "hour", "day", "week", "month", "year"]


class Pagination(Response):
    current: Page
    last: Count
    previous: Optional[Page]
    next: Optional[Page]


class Meta(Response):
    total: Count
    total_filtered: Count
    returned: Count
    pagination: Pagination


class ScopeAssets(Response):
    type: Literal["uptime_monitors", "blacklist_monitors", "contact_lists", "status_pages"]
    ids: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=512)]], Field(max_length=10000)]


class APIScope(Response):
    access: Literal["full", "restricted"]
    api_calls: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=256)]], Field(max_length=1000)]
    assets: Optional[ScopeAssets]

    @model_validator(mode="after")
    def complete_scope(self):
        if self.access == "full" and self.api_calls:
            raise ValueError("Full scope must have no restricted call list")
        if self.assets is not None and len(set(self.assets.ids)) != len(self.assets.ids):
            raise ValueError("Duplicate scope asset IDs")
        return self


class Uptime(Response):
    percentage: Percentage
    percentage_incl_maint: Percentage
    downtimes: Optional[Count] = None
    downtimes_incl_maint: Optional[Count] = None


def projected(model, raw, include_names=False):
    if not isinstance(raw, dict):
        raise OutcomeUnverified(UNVERIFIED)
    selected = {key: raw[key] for key in model.model_fields if key in raw and (key != "name" or include_names)}
    try:
        result = model.model_validate(selected).model_dump(exclude_unset=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None
    if model is APIScope and result["assets"] is not None:
        assets = result["assets"]
        if assets["type"] not in {"uptime_monitors", "status_pages"}:
            result["assets"] = {"type": assets["type"], "asset_count": len(assets["ids"])}
        elif any(not re.fullmatch(r"[A-Za-z0-9]{32}", identifier) for identifier in assets["ids"]):
            raise OutcomeUnverified(UNVERIFIED)
    if model is StatusPage:
        result["monitor_count"] = len(result.pop("monitors"))
    return result


def collection(model, raw, envelope, cfg):
    if not isinstance(raw, dict) or not isinstance(raw.get(envelope), list) or len(raw[envelope]) > cfg.per_page:
        raise OutcomeUnverified(UNVERIFIED)
    items = [projected(model, item, cfg.include_names) for item in raw[envelope]]
    if len({item["id"] for item in items}) != len(items):
        raise OutcomeUnverified("HetrixTools returned duplicate resource IDs")
    meta = projected(Meta, raw.get("meta"))
    paging = meta["pagination"]
    if meta["returned"] != len(items) or meta["total_filtered"] > meta["total"] or meta["returned"] > meta["total_filtered"] or paging["current"] != cfg.page:
        raise OutcomeUnverified("HetrixTools pagination or counts did not match the requested page")
    if paging["previous"] is not None and paging["previous"] != cfg.page - 1:
        raise OutcomeUnverified("HetrixTools previous page is inconsistent")
    if paging["next"] is not None and (paging["next"] != cfg.page + 1 or paging["next"] > paging["last"]):
        raise OutcomeUnverified("HetrixTools next page is inconsistent")
    return {"items": items, "meta": meta, "snapshot_consistent": False}


async def monitor(auth, identifier, include_names=False):
    raw = await request(auth, "uptime-monitors", {"id": identifier, "page": 1, "per_page": 1})
    cfg = ListMonitors(page=1, per_page=1, include_names=include_names)
    result = collection(Monitor, raw, "monitors", cfg)
    if len(result["items"]) != 1 or result["items"][0]["id"] != identifier or result["meta"]["pagination"]["next"] is not None:
        raise OutcomeUnverified("Requested HetrixTools monitor is absent or differs from its protected witness")
    return result["items"][0]


def uptime(raw, counts):
    result = projected(Uptime, raw)
    if counts and ("downtimes" not in result or "downtimes_incl_maint" not in result):
        raise OutcomeUnverified(UNVERIFIED)
    return result


def report(raw):
    if not isinstance(raw.get("data"), dict) or not isinstance(raw.get("summary"), dict) or not isinstance(raw.get("history"), dict):
        raise OutcomeUnverified(UNVERIFIED)
    if len(raw["data"]) > 31 or len(raw["history"]) > 1200:
        raise OutcomeUnverified("HetrixTools report exceeds its local daily/history bound")
    daily, history = {}, {}
    for date, item in raw["data"].items():
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raise ValueError()
            datetime.strptime(date, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise OutcomeUnverified(UNVERIFIED) from None
        if not isinstance(item, dict):
            raise OutcomeUnverified(UNVERIFIED)
        daily[date] = {"uptime": uptime(item.get("uptime"), True)}
    for month, item in raw["history"].items():
        if not re.fullmatch(r"(19|20)\d{2}-(0[1-9]|1[0-2])", month) or not isinstance(item, dict):
            raise OutcomeUnverified(UNVERIFIED)
        history[month] = {"uptime": uptime(item.get("uptime"), False)}
    # Response-time/location/hourly diagnostics and arbitrary extra fields are
    # discarded before validation or ordinary output.
    return {"data": daily, "summary": {"uptime": uptime(raw["summary"].get("uptime"), True)}, "history": history, "requested_timezone": "+00:00"}


async def operate(auth, cfg):
    if isinstance(cfg, GetAPIScope):
        return projected(APIScope, await request(auth, "account/api/scope"))
    if isinstance(cfg, ListMonitors):
        params = {"page": cfg.page, "per_page": cfg.per_page}
        for attr, key in (("monitor_type", "type"), ("uptime_status", "uptime_status"), ("monitor_status", "monitor_status")):
            value = getattr(cfg, attr)
            if value is not None:
                params[key] = value
        return collection(Monitor, await request(auth, "uptime-monitors", params), "monitors", cfg)
    if isinstance(cfg, ListStatusPages):
        return collection(StatusPage, await request(auth, "status-pages", {"page": cfg.page, "per_page": cfg.per_page}), "status_pages", cfg)
    parent = await monitor(auth, cfg.monitor_id, cfg.include_names)
    if isinstance(cfg, GetMonitor):
        return parent
    if isinstance(cfg, GetReport):
        params = {"timezone": "+00:00", "hourly_stats": "false"}
        if cfg.month is not None:
            params["month"] = cfg.month
        else:
            params["days"] = cfg.days
        return {"monitor": parent, "report": report(await request(auth, f"uptime-monitors/{cfg.monitor_id}/report", params)), "snapshot_consistent": False}
    params = {"page": cfg.page, "per_page": cfg.per_page}
    if isinstance(cfg, ListDowntimes):
        for name in ("start_after", "start_before"):
            value = getattr(cfg, name)
            if value is not None:
                params[name] = value
        result = collection(Downtime, await request(auth, f"uptime-monitors/{cfg.monitor_id}/downtimes", params), "downtimes", cfg)
    elif isinstance(cfg, ListMaintenance):
        params["monitor_id"] = cfg.monitor_id
        result = collection(ScheduledMaintenance, await request(auth, "schedule-maintenance", params), "scheduled_maintenances", cfg)
        if any(item["monitor_id"] != cfg.monitor_id for item in result["items"]):
            raise OutcomeUnverified("HetrixTools scheduled-maintenance monitor ancestry differs")
    else:
        raise ValueError("Unsupported HetrixTools operation")
    return {"monitor": parent, **result}


class HetrixToolsNode(WorkflowNode):
    integration_type = "automation-hetrixtools"
    credential_provider_labels = {"hetrixtools": "Hetrixtools Account"}
    connection_evidence = ConnectionEvidence(operation="get_api_scope", noun="HetrixTools API scope", label_keys=(), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return HetrixToolsNodeConfig

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
                result = await validation_context.run_operation("get_api_scope", {})
                await validation_context.revalidate()
                return (True, None) if result.get("status") == "success" else (None, UNVERIFIED)
            auth = await Authority.create(raw)
            await operate(auth, GetAPIScope())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.status_code in (401, 403) else (None, str(error))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, HetrixToolsNodeConfig) or self.config.credentials is None:
            raise ValueError("HetrixTools v3 API Key is required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        result = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if field_name != "monitor_id":
            raise ValueError("Unsupported HetrixTools picker")
        if not isinstance(auth, Authority) or not auth.credential_id or not auth.user_id or context.get("_user_id") != auth.user_id:
            raise ValueError("HetrixTools pickers require a current saved credential authorized for this actor")
        if search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("HetrixTools picker search is invalid")
        if page_token is None:
            page = 1
        elif isinstance(page_token, str) and re.fullmatch(r"[1-9]\d{0,3}|10000", page_token):
            page = int(page_token)
        else:
            raise ValueError("Invalid HetrixTools picker page")
        await auth.require_current()
        result = await operate(auth, ListMonitors(page=page, per_page=200))
        options = [{"value": item["id"], "label": item["id"]} for item in result["items"]]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        await auth.require_current()
        next_page = result["meta"]["pagination"]["next"]
        return {"options": options, "next_page_token": str(next_page) if next_page is not None else None}
