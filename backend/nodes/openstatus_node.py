"""OpenStatus native Connect RPC metadata reads.
Only closed read-semantic methods are exposed; provider configuration and content
never leave the local projection. Supplied API keys are neither minted nor refreshed.
"""
import base64
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Discriminator, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.openstatus_authority import AuthorityCredentialsTableStore, CURRENT_ORGANIZATION
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin
from nodes.openstatus_transport import guarded_async_client

FAMILY = "openstatus_api_key"
NODE_TYPE = "automation-openstatus"
API_ORIGIN = "https://api.openstatus.dev"
MAX_BYTES = 2 * 1024 * 1024
MAX_WITNESS_PAGES = 5
_ORG_OMITTED = object()
_PRIVATE = ContextVar("openstatus_private_transport", default=False)
SERVICES = {
    "ListMonitors": "monitor.v1.MonitorService", "GetMonitor": "monitor.v1.MonitorService",
    "GetMonitorStatus": "monitor.v1.MonitorService", "GetMonitorSummary": "monitor.v1.MonitorService",
    "ListStatusPages": "status_page.v1.StatusPageService", "GetStatusPage": "status_page.v1.StatusPageService",
    "GetStatusPageOverview": "status_page.v1.StatusPageService",
    "GetOverallStatus": "status_page.v1.StatusPageService", "GetPageComponent": "status_page.v1.StatusPageService",
    "ListStatusReports": "status_report.v1.StatusReportService", "GetStatusReport": "status_report.v1.StatusReportService",
    "ListMaintenances": "maintenance.v1.MaintenanceService", "GetMaintenance": "maintenance.v1.MaintenanceService",
}
MONITOR_TYPES = ("http", "tcp", "dns", "icmp", "grpc", "heartbeat")
MONITOR_STATUSES = {"MONITOR_STATUS_" + v for v in ("UNSPECIFIED", "ACTIVE", "DEGRADED", "ERROR")}
OVERALL_STATUSES = {"OVERALL_STATUS_" + v for v in ("UNSPECIFIED", "OPERATIONAL", "DEGRADED", "PARTIAL_OUTAGE", "MAJOR_OUTAGE", "MAINTENANCE", "UNKNOWN")}
REPORT_STATUSES = {"STATUS_REPORT_STATUS_" + v for v in ("UNSPECIFIED", "INVESTIGATING", "IDENTIFIED", "MONITORING", "RESOLVED")}
COMPONENT_TYPES = {"PAGE_COMPONENT_TYPE_" + v for v in ("UNSPECIFIED", "MONITOR", "STATIC")}
CONNECT_CODES = {"canceled", "unknown", "invalid_argument", "deadline_exceeded", "not_found", "already_exists",
    "permission_denied", "resource_exhausted", "failed_precondition", "aborted", "out_of_range",
    "unimplemented", "internal", "unavailable", "data_loss", "unauthenticated"}
REFUSAL_CODES = {"invalid_argument", "not_found", "permission_denied", "unauthenticated", "failed_precondition", "out_of_range"}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Select a bounded OpenStatus resource ID without URL syntax")
    return value


def key(value):
    try:
        value = clean_secret(value, field_name="OpenStatus API Key")
        if len(value) > 4096 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError()
        return value
    except Exception:
        raise ValueError("Supply an existing OpenStatus API key without a header prefix") from None


class OpenStatusApiKeyCredential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.openstatus.dev/docs/sdk/nodejs/authentication",
        "x-credential-instructions": "Supply an existing account-authorized API key. Prefer a read-only ['read'] key from Settings → General → API Keys. Sent only as x-openstatus-key to fixed public HTTPS api.openstatus.dev/rpc. This node does not create, introspect, refresh or revoke keys. Protected reads establish reachability, not actor/workspace identity, key scope verification or ownership.",
    })
    credential_type: Literal["openstatus_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    _key = field_validator("api_key", mode="before")(key)

    @model_validator(mode="before")
    @classmethod
    def _native_family(cls, value):
        # Manual connect serializes only explicitly set fields. Materialize
        # this model's default so its evidence probe receives a typed credential.
        if isinstance(value, dict) and "credential_type" not in value:
            return {**value, "credential_type": FAMILY}
        return value


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
            raise ValueError()
        if any(data.get(k) not in (None, "", []) for k in
               ("access_token", "refresh_token", "client_id", "client_secret", "token", "base_url", "host", "username", "password", "scope", "scopes")):
            raise ValueError()
        return OpenStatusApiKeyCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Connect the native OpenStatus supplied API key") from None


class _Credential(dict):
    pass


class _BoundCredential(_Credential):
    def __init__(self, data, store, snapshot):
        super().__init__(data)
        self["_openstatus_saved_authority_required"] = True
        self.store, self.snapshot = store, snapshot


class _Store(AuthorityCredentialsTableStore):
    def _repo(self):
        from repositories.openstatus_authority import OpenStatusAuthorityRepo
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        return OpenStatusAuthorityRepo(self.pool)


async def _load_current(store):
    try:
        raw = await store.load()
        stamp = raw.get("updated_at")
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None or store.current is None:
            raise ValueError()
        return credential(raw), (store.current, stamp)
    except ValueError:
        raise ValueError("OpenStatus saved credential or current access changed; reload") from None
    except Exception:
        raise RuntimeError("OpenStatus current credential authority could not be verified") from None


async def current_credential(data):
    shaped = credential(data)
    if not isinstance(data, _BoundCredential):
        if "_openstatus_saved_authority_required" in data:
            raise ValueError("OpenStatus saved authority was lost; reload")
        return shaped
    now, snapshot = await _load_current(data.store)
    if data.get("_openstatus_saved_authority_required") is not True or now != shaped or snapshot != data.snapshot:
        raise ValueError("OpenStatus current key or authority changed; reload")
    return now


def runtime(data):
    credential(data)
    if "_openstatus_saved_authority_required" in data and not isinstance(data, _BoundCredential):
        raise ValueError("OpenStatus saved authority was lost; reload")
    return data if isinstance(data, _Credential) else _Credential(data)


def resource(field, parents=()):
    return {"x-resource-type": "openstatus_" + field, "x-dynamic-options": {
        "field_name": field, "allow_custom": True, "searchable": True,
        "depends_on": list(parents), "required_context_scopes": {p: [] for p in parents},
        "context_fields": list(parents) + ["include_names"], "placeholder": "Select current " + field.replace("_", " ")}}


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
    include_names: bool = Field(False, strict=True, title="Include Resource Names",
        description="Opt in to bounded monitor/component names and page/report/maintenance titles. Request settings, URLs, descriptions, content, identities and capabilities are never returned.")

    @field_validator("monitor_id", "page_id", "component_id", "report_id", "maintenance_id", mode="before", check_fields=False)
    @classmethod
    def _id(cls, value):
        return identifier(value)


class _Paged(_Config):
    limit: int = Field(50, strict=True, ge=1, le=100, title="Page Size")
    page_token: Optional[str] = Field(None, max_length=8192, title="Next Page Token",
        description="A local sealed offset for the same current credential, resource and parent. The API uses limit/offset, not a provider cursor.")


class _Monitor(_Config):
    monitor_id: str = Field(..., title="Monitor", json_schema_extra=resource("monitor_id"))


class _Page(_Config):
    page_id: str = Field(..., title="Status Page", json_schema_extra=resource("page_id"))


class ListMonitors(_Paged):
    operation: Literal["list_monitors"] = Field("list_monitors", title="List Monitor Metadata")


class GetMonitor(_Monitor):
    operation: Literal["get_monitor"] = Field("get_monitor", title="Get Monitor Metadata")


class GetMonitorStatus(_Monitor):
    operation: Literal["get_monitor_status"] = Field("get_monitor_status", title="Get Monitor Status Counts")


class GetMonitorSummary(_Monitor):
    operation: Literal["get_monitor_summary"] = Field("get_monitor_summary", title="Get Monitor Metric Counts")
    time_range: Literal["TIME_RANGE_1D", "TIME_RANGE_7D", "TIME_RANGE_14D"] = Field("TIME_RANGE_1D", title="Metric Time Range")


class ListStatusPages(_Paged):
    operation: Literal["list_status_pages"] = Field("list_status_pages", title="List Status Page Metadata")


class GetStatusPage(_Page):
    operation: Literal["get_status_page"] = Field("get_status_page", title="Get Status Page Metadata")


class GetPageComponents(_Page):
    operation: Literal["get_page_components"] = Field("get_page_components", title="List Selected Page Components")
    limit: int = Field(100, strict=True, ge=1, le=100, title="Local Output Limit")


class GetPageOverallStatus(_Page):
    operation: Literal["get_page_overall_status"] = Field("get_page_overall_status", title="Get Selected Page Overall Status")


class GetPageComponent(_Page):
    operation: Literal["get_page_component"] = Field("get_page_component", title="Get Selected Page Component")
    component_id: str = Field(..., title="Component", json_schema_extra=resource("component_id", ("page_id",)))


class ListStatusReports(_Paged):
    operation: Literal["list_status_reports"] = Field("list_status_reports", title="List Workspace Status Report Metadata")


class GetStatusReport(_Config):
    operation: Literal["get_status_report"] = Field("get_status_report", title="Get Workspace Status Report Metadata")
    report_id: str = Field(..., title="Status Report", json_schema_extra=resource("report_id"))


class ListMaintenances(_Paged):
    operation: Literal["list_maintenances"] = Field("list_maintenances", title="List Selected Page Maintenance Metadata")
    page_id: str = Field(..., title="Status Page", json_schema_extra=resource("page_id"))


class GetMaintenance(_Page):
    operation: Literal["get_maintenance"] = Field("get_maintenance", title="Get Selected Page Maintenance Metadata")
    maintenance_id: str = Field(..., title="Maintenance", json_schema_extra=resource("maintenance_id", ("page_id",)))


OpenStatusOperation = Annotated[Union[ListMonitors, GetMonitor, GetMonitorStatus, GetMonitorSummary,
    ListStatusPages, GetStatusPage, GetPageComponents, GetPageOverallStatus, GetPageComponent,
    ListStatusReports, GetStatusReport, ListMaintenances, GetMaintenance], Discriminator("operation")]
OPS = ("list_monitors", "get_monitor", "get_monitor_status", "get_monitor_summary", "list_status_pages",
    "get_status_page", "get_page_components", "get_page_overall_status", "get_page_component",
    "list_status_reports", "get_status_report", "list_maintenances", "get_maintenance")


class OpenStatusNodeConfig(NodeConfig[OpenStatusOperation, OpenStatusApiKeyCredential]):
    pass


class _Refused(ValueError):
    pass


class _Unverified(RuntimeError):
    pass


class _Privacy(logging.Filter):
    def filter(self, record):
        return not _PRIVATE.get()


def _json(payload):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError()
            out[k] = v
        return out
    return json.loads(payload, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


async def request(data, method, body):
    data = runtime(data)
    allowed = ({"limit", "offset", "pageId"} if method == "ListMaintenances" else
        {"limit", "offset"} if method.startswith("List") else
        {"id", "timeRange"} if method == "GetMonitorSummary" else {"id"})
    if method not in SERVICES or not isinstance(body, dict) or set(body) - allowed:
        raise ValueError("Use a closed native OpenStatus metadata RPC")
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _Privacy) for f in logger.filters):
            logger.addFilter(_Privacy())
    mark = _PRIVATE.set(True)
    try:
        current = await current_credential(data)
        url = API_ORIGIN + "/rpc/openstatus." + SERVICES[method] + "/" + method
        assert_exact_url_origin(url, API_ORIGIN)
        async with guarded_async_client(timeout=25.0, follow_redirects=False, trust_env=False, require_public=True) as client:
            async with client.stream("POST", url, json=body, headers={"Content-Type": "application/json",
                    "Accept": "application/json", "Connect-Protocol-Version": "1", "x-openstatus-key": current["api_key"]}) as response:
                await current_credential(data)
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise _Unverified("OpenStatus metadata response exceeds the local bound")
                await current_credential(data)
                status = response.status_code
                if status == 429 or status >= 500 or 300 <= status < 400:
                    raise _Unverified("OpenStatus metadata RPC was rate limited or inconclusive")
                try:
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError()
                    raw = _json(bytes(payload))
                    if not isinstance(raw, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    if status in {401, 403, 404}:
                        raise _Refused("OpenStatus refused the current metadata read") from None
                    raise _Unverified("OpenStatus JSON response is unverified") from None
                if "code" in raw or "message" in raw or "details" in raw:
                    code = raw.get("code")
                    if code in REFUSAL_CODES:
                        raise _Refused("OpenStatus refused the current metadata read")
                    raise _Unverified("OpenStatus Connect RPC did not complete")
                if status in {400, 401, 403, 404, 409, 412, 416, 422}:
                    raise _Refused("OpenStatus refused the current metadata read")
                if status != 200:
                    raise _Unverified("OpenStatus did not confirm a completed metadata read")
                return raw
    except (_Refused, _Unverified):
        raise
    except ValueError:
        raise ValueError("OpenStatus current authority or public-origin policy refused the read") from None
    except Exception:
        raise _Unverified("OpenStatus metadata read could not complete") from None
    finally:
        _PRIVATE.reset(mark)


def output_id(value):
    try:
        return identifier(value)
    except ValueError:
        raise _Unverified("OpenStatus returned resource identity is unverified") from None


def count(value, *, wide=False):
    if wide and isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= (9223372036854775807 if wide else 2147483647):
        raise _Unverified("OpenStatus metadata count is unverified")
    return str(value) if wide else value


def timestamp(value):
    try:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError()
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc).isoformat()
    except ValueError:
        raise _Unverified("OpenStatus metadata timestamp is unverified") from None


def enum(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise _Unverified("OpenStatus metadata enum is unverified")
    return value


def array(raw, field, maximum=1000):
    value = raw.get(field, [])
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(v, dict) for v in value):
        raise _Unverified("OpenStatus bounded metadata collection is unverified")
    return value


def project(row, kind, names=False):
    if not isinstance(row, dict):
        raise _Unverified("OpenStatus resource metadata is unverified")
    out = {"id": output_id(row.get("id"))}
    for name in ("createdAt", "updatedAt"):
        if row.get(name) not in (None, ""):
            out[name] = timestamp(row[name])
    if kind == "monitor":
        if "status" in row:
            out["status"] = enum(row["status"], MONITOR_STATUSES)
        if row.get("active") is not None:
            if type(row["active"]) is not bool:
                raise _Unverified("OpenStatus monitor active flag is unverified")
            out["active"] = row["active"]
    if kind == "page" and "published" in row:
        if type(row["published"]) is not bool:
            raise _Unverified("OpenStatus page publication flag is unverified")
        out["published"] = row["published"]
    if kind in {"component", "maintenance"}:
        out["page_id"] = output_id(row.get("pageId"))
    if kind == "component" and "type" in row:
        out["type"] = enum(row["type"], COMPONENT_TYPES)
    if kind == "report" and "status" in row:
        out["status"] = enum(row["status"], REPORT_STATUSES)
    if kind in {"maintenance", "report"}:
        affected = row.get("pageComponentIds", [])
        if not isinstance(affected, list) or len(affected) > 1000:
            raise _Unverified("OpenStatus affected component count is unverified")
        ids = [output_id(v) for v in affected]
        if len(set(ids)) != len(ids):
            raise _Unverified("OpenStatus affected component identities repeat")
        out["affected_component_count"] = len(ids)
    if kind == "maintenance":
        for name in ("from", "to"):
            if row.get(name) not in (None, ""):
                out[name] = timestamp(row[name])
    if names:
        field = "name" if kind in {"monitor", "component"} else "title"
        if field in row:
            value = row[field]
            if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise _Unverified("OpenStatus bounded display name is unverified")
            out["name"] = value
    return out


LISTS = {"monitor": ("ListMonitors", None), "page": ("ListStatusPages", "statusPages"),
    "report": ("ListStatusReports", "statusReports"), "maintenance": ("ListMaintenances", "maintenances")}


async def list_page(data, kind, limit=100, offset=0, parent=None, names=False):
    method, field = LISTS[kind]
    body = {"limit": limit, "offset": offset}
    if kind == "maintenance":
        body["pageId"] = identifier(parent)
    raw = await request(data, method, body)
    rows = []
    if kind == "monitor":
        for mode in MONITOR_TYPES:
            rows.extend({**project(v, kind, names), "type": mode} for v in array(raw, mode + "Monitors", 100))
    else:
        rows = [project(v, kind, names) for v in array(raw, field, 100)]
    total = count(raw.get("totalSize", 0))
    if len(rows) > limit or len({v["id"] for v in rows}) != len(rows) or offset + len(rows) > total and rows:
        raise _Unverified("OpenStatus paging count or identities are inconsistent")
    if kind == "maintenance" and any(v["page_id"] != parent for v in rows):
        raise _Refused("OpenStatus maintenance belongs to a different selected page")
    more = offset + len(rows) < total
    if more and not rows:
        raise _Unverified("OpenStatus pagination made no progress")
    return rows, total, offset + len(rows) if more else None


async def find(data, kind, selected, parent=None):
    selected = identifier(selected)
    offset = 0
    for _ in range(MAX_WITNESS_PAGES):
        rows, _, next_offset = await list_page(data, kind, offset=offset, parent=parent)
        found = next((v for v in rows if v["id"] == selected), None)
        if found is not None:
            return found
        if next_offset is None:
            raise _Refused("OpenStatus selected resource is absent from the current protected catalog")
        offset = next_offset
    raise _Unverified("OpenStatus selected resource exceeds the five-page ancestry bound")


async def page_witness(data, selected):
    before = await find(data, "page", selected)
    raw = await request(data, "GetStatusPage", {"id": identifier(selected)})
    value = project(raw.get("statusPage"), "page")
    if value["id"] != selected:
        raise _Refused("OpenStatus returned status page differs from the selected catalog")
    return before, value


async def components(data, parent, names=False):
    raw = await request(data, "GetStatusPageOverview", {"id": identifier(parent)})
    page = project(raw.get("statusPage"), "page")
    if page["id"] != parent:
        raise _Refused("OpenStatus overview differs from the selected page")
    items = [project(v, "component", names) for v in array(raw, "components")]
    if len({v["id"] for v in items}) != len(items) or any(v["page_id"] != parent for v in items):
        raise _Refused("OpenStatus component catalog is not bound to the selected page")
    return items


def _binding(data, kind, parent, limit):
    shape = credential(data)
    snapshot = repr(data.snapshot) if isinstance(data, _BoundCredential) else None
    return hashlib.sha256(json.dumps({"credential": shape, "snapshot": snapshot, "kind": kind, "parent": parent, "limit": limit},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cipher(data):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("openstatus-offset:" + credential(data)["api_key"]).encode()).digest()))


def seal_page(data, kind, parent, limit, offset):
    if offset is None:
        return None
    return _cipher(data).encrypt(json.dumps({"binding": _binding(data, kind, parent, limit), "offset": offset}).encode()).decode()


def unseal_page(data, kind, parent, limit, value):
    if value is None:
        return 0
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 8192:
            raise ValueError()
        raw = _json(_cipher(data).decrypt(value.encode("ascii"), ttl=300))
        if raw.get("binding") != _binding(data, kind, parent, limit):
            raise ValueError()
        offset = raw["offset"]
        if type(offset) is not int or not 1 <= offset <= 2147483647:
            raise ValueError()
        return offset
    except Exception:
        raise ValueError("Reload OpenStatus pagination for the same current key, resource and parent") from None


async def records(data, args):
    cfg = TypeAdapter(OpenStatusOperation).validate_python(args).model_dump()
    data = runtime(data)
    await current_credential(data)
    op, names, parent = cfg["operation"], cfg["include_names"], cfg.get("page_id")
    list_kind = {"list_monitors": "monitor", "list_status_pages": "page", "list_status_reports": "report", "list_maintenances": "maintenance"}.get(op)
    offset = unseal_page(data, list_kind, parent, cfg["limit"], cfg["page_token"]) if list_kind else 0
    before_parent = await page_witness(data, parent) if parent else None
    before_selected = None
    if cfg.get("monitor_id"):
        before_selected = await find(data, "monitor", cfg["monitor_id"])
    if cfg.get("report_id"):
        before_selected = await find(data, "report", cfg["report_id"])
    if cfg.get("maintenance_id"):
        before_selected = await find(data, "maintenance", cfg["maintenance_id"], parent)
    if cfg.get("component_id"):
        before_selected = await components(data, parent)
        if not any(v["id"] == cfg["component_id"] for v in before_selected):
            raise _Refused("OpenStatus selected component is absent from its selected page")
    if list_kind:
        items, total, following = await list_page(data, list_kind, cfg["limit"], offset, parent, names)
        again = await list_page(data, list_kind, cfg["limit"], offset, parent, names)
        if (items, total, following) != again:
            raise _Refused("OpenStatus metadata catalog changed during the read")
        result = {"data": items, "total_count": total, "provider_returned": len(items), "has_more": following is not None,
            "next_page_token": seal_page(data, list_kind, parent, cfg["limit"], following), "completion_known": following is None,
            "paging": "limit_offset", "snapshot_consistency_verified": False}
    elif op == "get_monitor":
        raw = await request(data, "GetMonitor", {"id": cfg["monitor_id"]})
        monitor = raw.get("monitor")
        if not isinstance(monitor, dict) or len(monitor) != 1 or next(iter(monitor)) not in MONITOR_TYPES:
            raise _Unverified("OpenStatus monitor oneof envelope is unverified")
        mode = next(iter(monitor))
        item = {**project(monitor[mode], "monitor", names), "type": mode}
        if item["id"] != cfg["monitor_id"]:
            raise _Refused("OpenStatus returned monitor differs")
        result = {"data": item}
    elif op in {"get_monitor_status", "get_monitor_summary"}:
        body = {"id": cfg["monitor_id"]}
        if op == "get_monitor_summary":
            body["timeRange"] = cfg["time_range"]
        raw = await request(data, "GetMonitorStatus" if op == "get_monitor_status" else "GetMonitorSummary", body)
        if output_id(raw.get("id")) != cfg["monitor_id"]:
            raise _Refused("OpenStatus returned monitor differs")
        item = {"id": cfg["monitor_id"]}
        if op == "get_monitor_status":
            states = [enum(v.get("status", "MONITOR_STATUS_UNSPECIFIED"), MONITOR_STATUSES) for v in array(raw, "regions", 1000)]
            item["region_count"] = len(states)
            item["status_counts"] = {v: states.count(v) for v in sorted(set(states))}
        else:
            for field in ("totalSuccessful", "totalDegraded", "totalFailed", "p50", "p75", "p90", "p95", "p99"):
                item[field] = count(raw.get(field, "0"), wide=True)
            if raw.get("lastPingAt"):
                item["lastPingAt"] = timestamp(raw["lastPingAt"])
            item["timeRange"] = enum(raw.get("timeRange", "TIME_RANGE_UNSPECIFIED"),
                {"TIME_RANGE_UNSPECIFIED", "TIME_RANGE_1D", "TIME_RANGE_7D", "TIME_RANGE_14D"})
            if item["timeRange"] != cfg["time_range"]:
                raise _Unverified("OpenStatus returned metric interval differs")
        result = {"data": item}
    elif op == "get_status_page":
        raw = await request(data, "GetStatusPage", {"id": parent})
        item = project(raw.get("statusPage"), "page", names)
        if item["id"] != parent:
            raise _Refused("OpenStatus returned page differs")
        result = {"data": item}
    elif op in {"get_page_components", "get_page_component"}:
        items = await components(data, parent, names)
        if op == "get_page_component":
            if not any(v["id"] == cfg["component_id"] for v in items):
                raise _Refused("OpenStatus selected component disappeared")
            raw = await request(data, "GetPageComponent", {"id": cfg["component_id"]})
            item = project(raw.get("component"), "component", names)
            if item["id"] != cfg["component_id"] or item["page_id"] != parent:
                raise _Refused("OpenStatus returned component has a different parent")
            result = {"data": item}
        else:
            again = await components(data, parent, names)
            if items != again:
                raise _Refused("OpenStatus selected component catalog changed")
            result = {"data": items[:cfg["limit"]], "total_count": len(items), "locally_truncated": len(items) > cfg["limit"],
                "completion_known": len(items) <= cfg["limit"], "has_more": len(items) > cfg["limit"], "next_page_token": None,
                "provider_catalog_bound": 1000, "provider_pagination_supported": False}
    elif op == "get_page_overall_status":
        raw = await request(data, "GetOverallStatus", {"id": parent})
        item = {"page_id": parent, "overall_status": enum(raw.get("overallStatus", "OVERALL_STATUS_UNSPECIFIED"), OVERALL_STATUSES)}
        known = {v["id"] for v in await components(data, parent)}
        statuses = []
        for row in array(raw, "componentStatuses"):
            cid = output_id(row.get("componentId"))
            if cid not in known:
                raise _Refused("OpenStatus overall status references a foreign component")
            statuses.append({"id": cid, "status": enum(row.get("status", "OVERALL_STATUS_UNSPECIFIED"), OVERALL_STATUSES)})
        if len({v["id"] for v in statuses}) != len(statuses):
            raise _Unverified("OpenStatus component status identities repeat")
        item["components"] = statuses
        result = {"data": item}
    else:
        kind, field, method, selected = ("report", "statusReport", "GetStatusReport", cfg["report_id"]) if op == "get_status_report" else (
            "maintenance", "maintenance", "GetMaintenance", cfg["maintenance_id"])
        raw = await request(data, method, {"id": selected})
        item = project(raw.get(field), kind, names)
        if item["id"] != selected or kind == "maintenance" and item["page_id"] != parent:
            raise _Refused("OpenStatus returned resource has a different selected scope")
        result = {"data": item}
    if cfg.get("monitor_id") and before_selected != await find(data, "monitor", cfg["monitor_id"]):
        raise _Refused("OpenStatus current monitor catalog changed")
    if cfg.get("report_id") and before_selected != await find(data, "report", cfg["report_id"]):
        raise _Refused("OpenStatus current report catalog changed")
    if cfg.get("maintenance_id") and before_selected != await find(data, "maintenance", cfg["maintenance_id"], parent):
        raise _Refused("OpenStatus current maintenance catalog changed")
    if cfg.get("component_id") and before_selected != await components(data, parent):
        raise _Refused("OpenStatus current component catalog changed")
    if parent and before_parent != await page_witness(data, parent):
        raise _Refused("OpenStatus selected page ancestry changed")
    await current_credential(data)
    return {**result, "read_completed": True, "reachability_verified": True, "identity_verified": False,
        "workspace_ownership_verified": False, "scope": "selected_page" if parent else "protected_workspace_catalog"}


class OpenStatusNode(WorkflowNode):
    integration_type = "automation-openstatus"
    credential_provider_labels = {"openstatus": "Openstatus Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_status_pages", noun="status pages", proves="reachability")
    scope_registry = ScopeRegistry(provider="openstatus", requirements={
        op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})

    @classmethod
    def get_config_model(cls):
        return OpenStatusNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            credential(config_data["credentials"])
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try:
                credential(config_data["credentials"])
            except ValueError:
                return {"valid": False, "errors": ["Connect the native OpenStatus API key"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id)

    @classmethod
    async def _freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None,
            workflow_id=None, organization_id=_ORG_OMITTED, require_owner=False):
        initial = credential(credential_data)
        if not credential_id:
            if "_openstatus_saved_authority_required" in credential_data:
                raise ValueError("OpenStatus saved authority was lost; reload")
            return _Credential(initial)
        if not user_id:
            raise ValueError("OpenStatus requires the current authorized principal")
        def validate(raw):
            now = credential(raw)
            if now != initial:
                raise ValueError("OpenStatus current supplied key changed")
            return now
        store = _Store(pool, user_id, credential_id, credential_type=FAMILY, validate=validate,
            organization_id=CURRENT_ORGANIZATION if organization_id is _ORG_OMITTED else organization_id,
            workflow_id=workflow_id, require_owner=require_owner)
        now, snapshot = await _load_current(store)
        return _BoundCredential(now, store, snapshot)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            data = credential(credential_data)
        except ValueError:
            return {"valid": False, "error": "OpenStatus credential shape is invalid"}
        try:
            result = await records(data, {"operation": "list_status_pages"})
        except _Refused:
            return {"valid": False, "error": "OpenStatus current metadata access refused"}
        except Exception:
            return {"valid": None, "error": "OpenStatus metadata access could not be judged"}
        if result.get("read_completed") is not True or result.get("reachability_verified") is not True:
            return {"valid": None, "error": "OpenStatus protected metadata read is unverified"}
        return {"valid": True, "proves": "reachability", "identity_verified": False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        mapping = {"monitor_id": ("monitor", "list_monitors"), "page_id": ("page", "list_status_pages"),
            "report_id": ("report", "list_status_reports"), "maintenance_id": ("maintenance", "list_maintenances")}
        if field_name not in mapping and field_name != "component_id":
            return {"options": [], "has_more": False, "next_page_token": None}
        context = context or {}
        names = context.get("include_names", False)
        if type(names) is not bool:
            raise ValueError("Use a boolean OpenStatus name opt-in")
        search = normalize_search(search)
        if search and (len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise ValueError("Use a bounded OpenStatus picker search")
        data = runtime(credential_data)
        parent = identifier(context.get("page_id")) if field_name in {"component_id", "maintenance_id"} else None
        if field_name == "component_id":
            if page_token is not None:
                raise ValueError("OpenStatus component RPC has no documented pagination")
            result = await records(data, {"operation": "get_page_components", "page_id": parent, "include_names": names})
        else:
            _, op = mapping[field_name]
            args = {"operation": op, "include_names": names, "page_token": page_token}
            if parent:
                args["page_id"] = parent
            result = await records(data, args)
        options = [{"value": v["id"], "label": v.get("name", "Resource " + str(i + 1)),
            "metadata": {"proves": "reachability", **({"page_id": parent} if parent else {})}} for i, v in enumerate(result["data"])]
        return {"options": filter_options_by_search(options, search), "has_more": result.get("has_more", False),
            "next_page_token": result.get("next_page_token"), "total_count": result.get("total_count"),
            "completion_known": result.get("completion_known", True), "locally_filtered": True}

    async def execute(self, inputs):
        if not isinstance(self.config, OpenStatusNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect the native OpenStatus supplied API key")
        raw = (self.node_data or {}).get("credentials")
        data = await self._freshen_credential(raw if raw is not None else self.config.credentials.model_dump(),
            pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"), workflow_id=self.workflow_id, organization_id=self.organization_id)
        return await records(data, self.config.config.model_dump())
