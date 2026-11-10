"""Pulsetic OAS 3.0.3/v1.0.0: eleven protected metadata GETs.

Raw Authorization key, bare-array list contracts and explicit monitor ancestry.
No account identity, request content, capability data or monitoring controls.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import math
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, WrapValidator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.pulsetic.com/api/public"
FAMILY = "pulsetic_api_key"
OPERATIONS = ("list_monitors", "get_monitor", "list_snapshots", "list_checks", "list_events", "get_stats", "get_downtime", "list_heartbeats", "get_heartbeat", "list_status_pages", "get_status_page")
_private_transport = contextvars.ContextVar("pulsetic_private_transport", default=False)


class PulseticError(ValueError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _reference(value):
    return isinstance(value, str) and "{{" in value and "}}" in value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value.strip()) or int(value.strip()) > 2**63 - 1:
        raise ValueError("Enter a positive int64 Pulsetic resource ID as text, not a URL.")
    return value.strip()


def _pending(value, handler):
    return value if _reference(value) else handler(value)


ResourceID = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$", max_length=19), WrapValidator(_pending)]
Page = Annotated[int, Field(ge=1, le=1000000), WrapValidator(_pending)]
PageSize = Annotated[int, Field(ge=1, le=100), WrapValidator(_pending)]
LocalLimit = Annotated[int, Field(ge=1, le=1000), WrapValidator(_pending)]
ProviderTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"), WrapValidator(_pending)]
Seconds = Annotated[int, Field(ge=1, le=7776000), WrapValidator(_pending)]
EventFilter = Annotated[Literal["Online", "Offline"], WrapValidator(_pending)]


class PulseticAPIKeyCredential(BaseModel):
    credential_type: Literal["pulsetic_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., description="Existing Pulsetic API key, sent as the raw Authorization header without Bearer. A read-only issued key supports GET; actual grants and entitlement are not inferred.", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Pulsetic API Key", extra="ignore", json_schema_extra={
        "x-credential-type": "pulsetic_api_key", "x-credential-url": "https://app.pulsetic.com/api",
        "x-credential-instructions": "Supply an existing API key, preferably one issued read-only. NoClick does not issue keys or assume their grants. Confirm your account's API entitlement separately; public documentation places API access on Team and above.",
    })

    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a text Pulsetic API key.")
        value = clean_secret(value, field_name="API key")
        if not value or len(value) > 8192 or _reference(value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter a valid raw API key without whitespace, Bearer prefix or references.")
        return value


class _Common(BaseModel):
    include_names: bool = Field(False, description="Include monitor/heartbeat names or status-page titles. Names can disclose business resources.")
    model_config = ConfigDict(extra="ignore")

    @field_validator("monitor_id", "heartbeat_id", "status_page_id", mode="before", check_fields=False)
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) and not _reference(value) else value


class ListMonitorsConfig(_Common):
    """Read one documented monitor page as a bare array; omit private targets and settings."""
    operation: Literal["list_monitors"] = "list_monitors"
    page: Page = Field(1, description="One provider page; the native page-number cap is 1,000,000, not a documented provider maximum.")
    per_page: PageSize = Field(20, description="Requested provider rows, with a local cap of 100. No loop, totals or completion are invented.")


class GetMonitorConfig(_Common):
    operation: Literal["get_monitor"] = "get_monitor"
    monitor_id: ResourceID = Field(..., description="Exact monitor ID. Enter an explicit ID or resolved workflow reference.", json_schema_extra={"x-resource-type": "pulsetic_monitor_id"})


class _Window(GetMonitorConfig):
    start_dt: ProviderTime = Field(..., description="OAS date-time string with an explicit offset, or the documented YYYY-MM-DD HH:MM:SS example form whose timezone is unspecified. Sent unchanged.")
    end_dt: ProviderTime = Field(..., description="Same provider time convention, after start and at most 31 days later (native bound).")


class ListSnapshotsConfig(_Window):
    """Read one numbered snapshot page and aggregate counts, with exact monitor ancestry."""
    operation: Literal["list_snapshots"] = "list_snapshots"
    page: Page = 1
    per_page: PageSize = Field(100, description="One documented snapshot page; local requested cap is 100.")


class ListChecksConfig(_Window):
    """Read bounded check codes/flags/timestamps, excluding request/response content and locations."""
    operation: Literal["list_checks"] = "list_checks"
    limit: LocalLimit = Field(100, description="Local result cap only. This route documents no paging query parameters.")


class ListEventsConfig(_Window):
    operation: Literal["list_events"] = "list_events"
    monitor_event_type: Optional[EventFilter] = Field(None, description="Optional documented request filter. Returned event type strings are preserved without inventing a mapping to this filter.")
    limit: LocalLimit = Field(100, description="Local result cap only; no request paging is documented.")


class GetStatsConfig(GetMonitorConfig):
    """Read exact 1day/7days/30days/90days aggregate objects, excluding target data."""
    operation: Literal["get_stats"] = "get_stats"


class GetDowntimeConfig(GetMonitorConfig):
    """Read the documented numeric downtime-in-seconds response, not an object wrapper."""
    operation: Literal["get_downtime"] = "get_downtime"
    seconds: Seconds = Field(3600, description="Documented seconds filter. Native maximum is 90 days; no provider maximum is inferred.")


class _LocalList(_Common):
    limit: LocalLimit = Field(100, description="Local result cap. This catalog documents no request paging parameters; completeness remains unknown.")


class ListHeartbeatsConfig(_LocalList):
    operation: Literal["list_heartbeats"] = "list_heartbeats"


class GetHeartbeatConfig(_Common):
    operation: Literal["get_heartbeat"] = "get_heartbeat"
    heartbeat_id: ResourceID = Field(..., description="Exact heartbeat ID, not an ingestion or capability URL.", json_schema_extra={"x-resource-type": "pulsetic_heartbeat_id"})


class ListStatusPagesConfig(_LocalList):
    operation: Literal["list_status_pages"] = "list_status_pages"


class GetStatusPageConfig(_Common):
    operation: Literal["get_status_page"] = "get_status_page"
    status_page_id: ResourceID = Field(..., description="Exact status-page ID. Secrets, domains, subscription/settings fields are omitted.", json_schema_extra={"x-resource-type": "pulsetic_status_page_id"})


PulseticOperation = Annotated[Union[ListMonitorsConfig, GetMonitorConfig, ListSnapshotsConfig, ListChecksConfig, ListEventsConfig, GetStatsConfig, GetDowntimeConfig, ListHeartbeatsConfig, GetHeartbeatConfig, ListStatusPagesConfig, GetStatusPageConfig], Field(discriminator="operation")]


class PulseticNodeConfig(NodeConfig[PulseticOperation, PulseticAPIKeyCredential]):
    pass


def _raw_guard(data):
    if not isinstance(data, dict):
        raise ValueError("Pulsetic configuration must be an object.")
    ids = data.get("credentialIds") or {}
    if not isinstance(ids, dict) or any(k not in (FAMILY, "credential_type") for k in ids) or ids.get("credential_type") not in (None, FAMILY) or data.get("credential_type") not in (None, FAMILY):
        raise ValueError("Select the native Pulsetic API-key credential family.")
    chosen, mapped = data.get("credential_id"), ids.get(FAMILY)
    for value in (chosen, mapped):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Select a saved Pulsetic credential UUID.")
            try:
                UUID(value)
            except (ValueError, TypeError):
                raise ValueError("Select a saved Pulsetic credential UUID.") from None
    if chosen and mapped and chosen != mapped:
        raise ValueError("Pulsetic credential selections disagree.")
    creds = data.get("credentials")
    if creds is not None:
        if not isinstance(creds, dict) or creds.get("credential_type") not in (None, FAMILY):
            raise ValueError("Foreign credential data cannot authenticate Pulsetic.")
        if (chosen or mapped or creds.get("token_version") is not None or creds.get("updated_at") is not None) and creds.get("credential_type") != FAMILY:
            raise ValueError("Stored Pulsetic credentials require their native family tag.")
        try:
            PulseticAPIKeyCredential.model_validate(creds)
        except Exception:
            raise ValueError("Check the Pulsetic API-key field.") from None
    inner = data.get("config") or {}
    if not isinstance(inner, dict):
        raise ValueError("Pulsetic operation configuration must be an object.")
    operation = inner.get("operation")
    field = "monitor_id" if operation in ("get_monitor", "list_snapshots", "list_checks", "list_events", "get_stats", "get_downtime") else "heartbeat_id" if operation == "get_heartbeat" else "status_page_id" if operation == "get_status_page" else None
    if field and inner.get(field) not in (None, "") and not _reference(inner[field]):
        _id(inner[field])
    paging = ("page", "per_page") if operation in ("list_monitors", "list_snapshots") else ("limit",) if operation in ("list_checks", "list_events", "list_heartbeats", "list_status_pages") else ("seconds",) if operation == "get_downtime" else ()
    for key in paging:
        value = inner.get(key)
        if value not in (None, "") and not _reference(value) and type(value) is not int:
            raise ValueError("Pulsetic page, local-limit and seconds values must be integers.")
    if "include_names" in inner and inner["include_names"] not in (None, "") and type(inner["include_names"]) is not bool:
        raise ValueError("Include names must be a checkbox value.")


class _TransportFilter(logging.Filter):
    def filter(self, record):
        return not _private_transport.get()


@contextmanager
def _quiet_transport():
    token = _private_transport.set(True)
    filters = []
    try:
        for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logger = logging.getLogger(name)
            f = _TransportFilter()
            logger.addFilter(f)
            filters.append((logger, f))
        yield
    finally:
        for logger, f in filters:
            logger.removeFilter(f)
        _private_transport.reset(token)


class PulseticNode(WorkflowNode):
    integration_type = "automation-pulsetic"
    credential_provider_labels = {"pulsetic": "Pulsetic Account"}
    connection_evidence = ConnectionEvidence(operation="list_monitors", noun="monitors", label_keys=("id",), proves="reachability")
    scope_registry = ScopeRegistry("pulsetic", {op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPERATIONS})

    @classmethod
    def get_config_model(cls):
        return PulseticNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _raw_guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    def _selected_id(self):
        _raw_guard(self.node_data)
        return self.node_data.get("credential_id") or (self.node_data.get("credentialIds") or {}).get(FAMILY)

    def _snapshot(self):
        return hashlib.sha256(json.dumps({"actor": self.user_id, "org": self.organization_id, "workflow": self.workflow_id,
            "raw": {k: self.node_data.get(k) for k in ("credentials", "credential_id", "credentialIds", "config")},
            "typed": self.config.model_dump(mode="json")}, sort_keys=True, default=str).encode()).hexdigest()

    def _unchanged(self):
        if self._snapshot() != self._frame:
            raise PulseticError("Pulsetic actor, credential or resource selection changed. Retry with the current selection.")

    async def run(self, inputs):
        cid = self._selected_id()
        self.node_data = dict(self.node_data)
        if cid:
            self.node_data["credential_id"] = cid
        self._frame = self._snapshot()
        return await super().run(inputs)

    async def _fresh(self):
        self._unchanged()
        attached = self.config.credentials
        if attached is None:
            raise PulseticError("Select a Pulsetic API key.")
        cid = self._selected_id()
        if not cid:
            credential = attached
            raw = self.node_data.get("credentials")
            if isinstance(raw, dict) and PulseticAPIKeyCredential.model_validate(raw) != attached:
                raise PulseticError("Pulsetic unsaved credential shaping changed; parse the current selection.")
            binding = (None, credential.api_key)
        else:
            from repositories.organization import OrgRepo
            from repositories.pulsetic_authority import current_pulsetic_row
            from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
            from utils.database_pool import get_native_pool
            from utils.encryption import get_encryption

            if not self.user_id:
                raise PulseticError("Pulsetic saved credentials need the current authenticated actor.")
            pool = get_native_pool()
            async with pool.acquire() as conn:
                org_id = await OrgRepo(pool).get_primary_org_id(conn, self.user_id)
                self._unchanged()
                row = await current_pulsetic_row(conn, cid, self.user_id, org_id)
            self._unchanged()
            if not row and self.workflow_id:
                owner = await get_workflow_owner_id(pool, self.workflow_id)
                self._unchanged()
                authorized = owner and owner != self.user_id and await is_credential_authorized_for_workflow(pool, self.workflow_id, cid)
                self._unchanged()
                if authorized:
                    async with pool.acquire() as conn:
                        row = await current_pulsetic_row(conn, cid, owner, org_id)
                    self._unchanged()
            if not row or str(row.get("id")) != cid or row.get("credential_type") != FAMILY or row.get("revoked_at") is not None:
                raise PulseticError("Current Pulsetic credential is missing, inaccessible, revoked or of another family.")
            raw = get_encryption().decrypt_credential(row["credential"])
            if not isinstance(raw, dict) or raw.get("credential_type") not in (None, FAMILY):
                raise PulseticError("Current Pulsetic row contains foreign credential data.")
            try:
                credential = PulseticAPIKeyCredential.model_validate(dict(raw, credential_type=FAMILY))
            except Exception:
                raise PulseticError("Current Pulsetic credential has invalid API-key fields.") from None
            binding = (cid, str(row["owner_id"]), str(row.get("organization_id")), org_id,
                row.get("token_version"), str(row.get("updated_at")), credential.api_key)
        if self._binding is None:
            self._binding = binding
        elif self._binding != binding:
            raise PulseticError("Pulsetic credential access or version changed during this read.")
        self._unchanged()
        return credential

    async def _request(self, route, params=None):
        if route == "/monitors":
            allowed = {"page", "per_page"}
        elif re.fullmatch(r"/monitors/[1-9][0-9]{0,18}/snapshots", route):
            allowed = {"start_dt", "end_dt", "page", "per_page"}
        elif re.fullmatch(r"/monitors/[1-9][0-9]{0,18}/(?:checks|events)", route):
            allowed = {"start_dt", "end_dt"} | ({"monitor_event_type"} if route.endswith("/events") else set())
        elif re.fullmatch(r"/monitors/[1-9][0-9]{0,18}/downtime", route):
            allowed = {"seconds"}
        elif route in ("/heartbeats", "/status-page") or re.fullmatch(r"/(?:monitors|heartbeats|status-page)/[1-9][0-9]{0,18}", route) or re.fullmatch(r"/monitors/[1-9][0-9]{0,18}/stats", route):
            allowed = set()
        else:
            raise PulseticError("Unsupported Pulsetic metadata route.")
        params = dict(params or {})
        if not set(params) <= allowed:
            raise PulseticError("Unsupported Pulsetic request parameters.")
        for key, maximum in (("page", 1000000), ("per_page", 100), ("seconds", 7776000)):
            if key in params and (type(params[key]) is not int or not 1 <= params[key] <= maximum):
                raise PulseticError("Pulsetic numeric request parameter exceeded its native bound.")
        if "start_dt" in allowed:
            if not {"start_dt", "end_dt"} <= set(params):
                raise PulseticError("Pulsetic history requires an explicit documented time interval.")
            self._window(params["start_dt"], params["end_dt"])
        if params.get("monitor_event_type") not in (None, "Online", "Offline"):
            raise PulseticError("Unsupported Pulsetic event filter.")
        credential = await self._fresh()
        path = "/api/public" + route

        async def before_send(request):
            current = await self._fresh()
            if request.url.scheme != "https" or request.url.host != "api.pulsetic.com" or request.url.port not in (None, 443) or request.url.path != path or sorted(request.url.params.multi_items()) != sorted((k, str(v)) for k, v in params.items()):
                raise PulseticError("Pulsetic request origin, resource parent or parameters changed.")
            request.headers["Authorization"] = current.api_key

        try:
            with _quiet_transport():
                async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [before_send]}) as client:
                    async with client.stream("GET", BASE_URL + route, params=params, headers={"Accept": "application/json", "Authorization": credential.api_key}) as response:
                        status = response.status_code
                        if status != 200:
                            raise PulseticError({400: "Pulsetic rejected the metadata parameters.", 401: "Pulsetic rejected the API key.", 403: "Pulsetic permission or resource access is missing.", 404: "Pulsetic resource was not found.", 422: "Pulsetic rejected the metadata filters.", 429: "Pulsetic rate limit reached; retry later."}.get(status, "Pulsetic did not return a completed metadata read."), status)
                        if "json" not in response.headers.get("content-type", "").lower():
                            raise PulseticError("Pulsetic returned unsupported response media.")
                        body = bytearray()
                        async for part in response.aiter_bytes():
                            body.extend(part)
                            if len(body) > 4 * 1024 * 1024:
                                raise PulseticError("Pulsetic response exceeded the metadata size bound.")
                        try:
                            data = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                        except (ValueError, RecursionError):
                            raise PulseticError("Pulsetic returned invalid JSON metadata.") from None
            await self._fresh()
            pending, visited = [data], 0
            while pending:
                value = pending.pop(); visited += 1
                if visited > 100000:
                    raise PulseticError("Pulsetic JSON exceeded the metadata complexity bound.")
                if isinstance(value, str) and credential.api_key in value:
                    raise PulseticError("Pulsetic reflected credential material; response withheld.")
                if isinstance(value, dict):
                    pending.extend(value.keys()); pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            if not isinstance(data, (dict, list)) and type(data) not in (int, float):
                raise PulseticError("Pulsetic returned an unsupported metadata envelope.")
            return data
        except httpx.HTTPError:
            raise PulseticError("Pulsetic metadata transport failed; no response is confirmed.") from None

    @staticmethod
    def _integer(value, *, positive=False):
        if type(value) is not int or not (1 if positive else 0) <= value <= 2**63 - 1:
            raise PulseticError("Pulsetic returned an invalid integer ID or count.")
        return value

    @staticmethod
    def _number(value):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10**12:
            raise PulseticError("Pulsetic returned invalid aggregate duration metadata.")
        return value

    @staticmethod
    def _text(data, key, result, *, timestamp=False, state=False):
        value = data.get(key)
        if value is None:
            return
        if not isinstance(value, str) or len(value) > (64 if timestamp or state else 500) or any(ord(c) < 32 for c in value) or "://" in value:
            raise PulseticError("Pulsetic returned invalid text metadata.")
        if state and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
            raise PulseticError("Pulsetic returned an unsupported state token.")
        if timestamp:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
                raise PulseticError("Pulsetic returned invalid timestamp metadata.")
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise PulseticError("Pulsetic returned invalid timestamp metadata.") from None
        result[key] = value

    @staticmethod
    def _decimal_text(value, maximum):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,12})?", value) or not 0 <= float(value) <= maximum:
            raise PulseticError("Pulsetic returned an invalid aggregate decimal string.")
        return value

    @staticmethod
    def _window(start, end):
        try:
            if any(not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value) for value in (start, end)):
                raise ValueError("Invalid time form")
            a, b = (datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (start, end))
        except (ValueError, TypeError):
            raise PulseticError("Enter valid provider date-time strings or the documented YYYY-MM-DD HH:MM:SS form.") from None
        if (a.tzinfo is None) != (b.tzinfo is None):
            raise PulseticError("Pulsetic history cannot mix timezone-unspecified and explicit-offset timestamps.")
        if b <= a or (b - a).total_seconds() > 31 * 86400:
            raise PulseticError("Pulsetic history interval is reversed or exceeds the native 31-day bound.")

    def _resource(self, data, kind):
        if not isinstance(data, dict):
            raise PulseticError("Pulsetic returned an unsupported resource envelope.")
        result = {"id": self._integer(data.get("id"), positive=True)}
        for key in ("created_at", "updated_at"):
            if kind != "status_page":
                self._text(data, key, result, timestamp=True)
        if kind == "monitor":
            for key in ("status", "ssl_certificate_state"):
                self._text(data, key, result, state=True)
            for key in ("uptime", "snapshots_average_uptime"):
                if data.get(key) is not None:
                    result[key] = self._decimal_text(data[key], 1)
            for key in ("checked_at", "status_changed_at"):
                self._text(data, key, result, timestamp=True)
        if self.config.config.include_names:
            self._text(data, "title" if kind == "status_page" else "name", result)
        return result

    def _array(self, data, *, bound=10000, identified=False):
        if not isinstance(data, list) or len(data) > bound or any(not isinstance(row, dict) for row in data):
            raise PulseticError("Pulsetic returned an unsupported bare-array metadata collection or exceeded the native bound.")
        if identified:
            ids = [self._integer(row.get("id"), positive=True) for row in data]
            if len(set(ids)) != len(ids):
                raise PulseticError("Pulsetic returned duplicate resource IDs.")
        return data

    async def _monitor(self, monitor_id):
        data = await self._request("/monitors/" + _id(monitor_id))
        projected = self._resource(data, "monitor")
        if projected["id"] != int(monitor_id):
            raise PulseticError("Pulsetic returned another monitor parent.")
        return projected

    def _history(self, row, operation, monitor_id):
        if self._integer(row.get("monitor_id"), positive=True) != int(monitor_id):
            raise PulseticError("Pulsetic history crosses the selected monitor parent.")
        result = {"monitor_id": int(monitor_id)}
        for key in (("hour",) if operation == "list_snapshots" else ("created_at", "updated_at") if operation == "list_events" else ("created_at",)):
            self._text(row, key, result, timestamp=True)
        if operation == "list_snapshots":
            for key in ("total_checks", "failed_checks"):
                if row.get(key) is not None:
                    result[key] = self._integer(row[key])
            if "total_checks" in result and result.get("failed_checks", 0) > result["total_checks"]:
                raise PulseticError("Pulsetic snapshot counts are inconsistent.")
            if row.get("uptime") is not None:
                result["uptime"] = self._decimal_text(row["uptime"], 1)
        elif operation == "list_checks":
            if row.get("response_code") is not None:
                code = self._integer(row["response_code"])
                if code > 599:
                    raise PulseticError("Pulsetic returned an invalid check response code.")
                result["response_code"] = code
            for key in ("is_successful", "is_failed"):
                if row.get(key) is not None:
                    value = self._integer(row[key])
                    if value not in (0, 1):
                        raise PulseticError("Pulsetic returned an unsupported check flag.")
                    result[key] = value
        else:
            self._text(row, "type", result, state=True)
        return result

    def _stats(self, data):
        if not isinstance(data, dict) or not any(key in data for key in ("1day", "7days", "30days", "90days")):
            raise PulseticError("Pulsetic returned an unsupported statistics envelope.")
        result = {}
        for key in ("1day", "7days", "30days", "90days"):
            if key not in data:
                continue
            row = data[key]
            if not isinstance(row, dict):
                raise PulseticError("Pulsetic returned an unsupported aggregate window.")
            item = {}
            if row.get("averageResponseTime") is not None:
                item["averageResponseTime"] = self._integer(row["averageResponseTime"])
            if row.get("uptime") is not None:
                item["uptime"] = self._decimal_text(row["uptime"], 100)
            if row.get("downtime") is not None:
                value = row["downtime"]
                if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2,5}:[0-5][0-9]:[0-5][0-9]", value):
                    raise PulseticError("Pulsetic returned invalid aggregate downtime text.")
                item["downtime"] = value
            result[key] = item
        return result

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        _raw_guard(self.node_data)
        self._frame = getattr(self, "_frame", self._snapshot())
        self._binding = None
        config = self.config.config
        if any(_reference(value) for value in config.model_dump().values()):
            raise PulseticError("Resolve Pulsetic resource and filter references before execution.")
        await self._fresh()
        operation = config.operation
        if operation in ("list_snapshots", "list_checks", "list_events"):
            self._window(config.start_dt, config.end_dt)
        if operation in ("list_monitors", "list_heartbeats", "list_status_pages"):
            kind, route, key = {"list_monitors": ("monitor", "/monitors", "monitors"), "list_heartbeats": ("heartbeat", "/heartbeats", "heartbeats"), "list_status_pages": ("status_page", "/status-page", "status_pages")}[operation]
            numbered = operation == "list_monitors"
            data = await self._request(route, {"page": config.page, "per_page": config.per_page} if numbered else None)
            rows = self._array(data, bound=config.per_page if numbered else 10000, identified=True)
            selected = rows if numbered else rows[:config.limit]
            result = {key: [self._resource(row, kind) for row in selected], "returned_count": len(selected), "locally_truncated": len(selected) < len(rows), "completion": "unknown"}
            if numbered:
                result.update(requested_page=config.page, requested_per_page=config.per_page)
        elif operation in ("get_heartbeat", "get_status_page"):
            kind, route, resource_id = ("heartbeat", "/heartbeats/", config.heartbeat_id) if operation == "get_heartbeat" else ("status_page", "/status-page/", config.status_page_id)
            data = await self._request(route + _id(resource_id))
            projected = self._resource(data, kind)
            if projected["id"] != int(resource_id):
                raise PulseticError("Pulsetic returned another selected resource.")
            result = {kind: projected}
        else:
            monitor = await self._monitor(config.monitor_id)
            if operation == "get_monitor":
                result = {"monitor": monitor}
            elif operation in ("get_stats", "get_downtime"):
                data = await self._request("/monitors/" + config.monitor_id + ("/stats" if operation == "get_stats" else "/downtime"), {"seconds": config.seconds} if operation == "get_downtime" else None)
                result = {"monitor_id": int(config.monitor_id), "stats": self._stats(data)} if operation == "get_stats" else {"monitor_id": int(config.monitor_id), "downtime_seconds": self._number(data), "requested_seconds": config.seconds}
            else:
                params = {"start_dt": config.start_dt, "end_dt": config.end_dt}
                numbered = operation == "list_snapshots"
                if numbered:
                    params.update(page=config.page, per_page=config.per_page)
                if operation == "list_events" and config.monitor_event_type is not None:
                    params["monitor_event_type"] = config.monitor_event_type
                key = {"list_snapshots": "snapshots", "list_checks": "checks", "list_events": "events"}[operation]
                data = await self._request("/monitors/" + config.monitor_id + "/" + key, params)
                rows = self._array(data, bound=config.per_page if numbered else 10000)
                # Validate ancestry for all returned rows, including locally omitted rows.
                for row in rows:
                    if self._integer(row.get("monitor_id"), positive=True) != int(config.monitor_id):
                        raise PulseticError("Pulsetic history crosses the selected monitor parent.")
                selected = rows if numbered else rows[:config.limit]
                result = {key: [self._history(row, operation, config.monitor_id) for row in selected], "monitor_id": int(config.monitor_id), "returned_count": len(selected), "locally_truncated": len(selected) < len(rows), "completion": "unknown", "timestamp_timezone": "unspecified unless an offset is present"}
                if numbered:
                    result.update(requested_page=config.page, requested_per_page=config.per_page)
            if operation != "get_monitor":
                await self._monitor(config.monitor_id)
        await self._fresh()
        self._unchanged()
        return {"success": True, "data": result}
