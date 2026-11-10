"""ilert exposes protected actor, team, service, incident and status-page metadata.
Closed read projections omit responders, private settings, secrets and capability URLs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

API_ROOT = "https://api.ilert.com/api"
HIDDEN = {"ui:hidden": True}
MAX_OFFSET = 1000000
WITNESS_PAGES = 5
ROUTES = {"actor": "/users/current", "teams": "/teams", "team": "/teams/{id}",
    "services": "/services", "service": "/services/{id}", "incidents": "/incidents",
    "incident": "/incidents/{id}", "statuspages": "/status-pages"}
PAGE_CAPS = {"teams": 100, "services": 100, "incidents": 100, "statuspages": 50}
SERVICE_STATES = {"OPERATIONAL", "UNDER_MAINTENANCE", "DEGRADED", "PARTIAL_OUTAGE", "MAJOR_OUTAGE"}
INCIDENT_STATES = {"DECLARED", "INVESTIGATING", "IDENTIFIED", "MONITORING", "RESOLVED"}
ILERT_SCOPES = ScopeRegistry("ilert", {route: ScopeRequirement((), credential_types=("ilert_api_key",),
    note="Existing user REST API key; current VIEW permissions apply. No OAuth scopes are invented.") for route in ROUTES})


def _id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 2**63-1:
        raise ValueError("Use an existing positive ilert numeric ID.")
    return value


def _text(value, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]|://|www\.", value, re.I):
        raise ValueError("Use bounded text without control characters or URLs.")
    return value.strip()


class IlertAPIKeyCredential(BaseModel):
    credential_type: Literal["ilert_api_key"] = Field("ilert_api_key", json_schema_extra=HIDDEN)
    access_token: str = Field(..., min_length=1, max_length=8192, title="Existing ilert User REST API Key",
        description="Supply the existing user REST key alone, not an Events integrationKey. Sent only in the Bearer header.",
        json_schema_extra={"ui:widget": "password"})
    actor_id: str = Field(..., min_length=1, max_length=19, title="Expected Current User ID",
        description="Existing private numeric ID from GET /users/current. Each operation verifies the actual actor; this is not a tenant ID.")
    team_context: Optional[int] = Field(None, strict=True, ge=-1, le=2**63-1, title="Optional Team Context",
        description="Omit for all VIEW-permitted resources independent of UI selection. Header 0 means ALL teams, -1 MY teams, a positive ID selects a team. Catalog access does not establish membership.")
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.ilert.com/developer-docs/rest-api/api-reference/introduction/authentication",
        "x-credential-instructions": "Use an existing user REST API key and its actual current-user ID. No key creation or OAuth flow. REST Bearer authentication differs from Events integrationKey and Basic login context."})
    _actor_value = field_validator("actor_id", mode="before")(_id)

    @field_validator("access_token", mode="before")
    @classmethod
    def issued_key(cls, value):
        if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f]|://", value):
            raise ValueError("Supply the existing REST key without whitespace, a prefix or URL.")
        return value


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "ilert_api_key":
        raise ValueError("Use the current actor-bound ilert user REST API key.")
    try:
        shaped = IlertAPIKeyCredential.model_validate({k: data[k] for k in IlertAPIKeyCredential.model_fields if k in data})
    except Exception:
        raise ValueError("The ilert credential binding is incomplete or invalid.") from None
    return {**data, **shaped.model_dump(mode="json")}


def _picker(field):
    result = {"x-dynamic-options": {"field": field}}
    if field == "service_id":
        result["x-dynamic-options"]["depends_on"] = "team_id"
    elif field == "incident_id":
        result["x-dynamic-options"]["depends_on"] = "service_id"
    return result


class IlertReadConfig(BaseModel):
    include_names: bool = Field(False, strict=True, description="Opt in to resource names and incident titles. IDs/status/time are returned by default.")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class IlertPageConfig(IlertReadConfig):
    limit: int = Field(50, strict=True, ge=1, le=100, description="Documented max-results; no includes are requested.")
    offset: int = Field(0, strict=True, ge=0, le=MAX_OFFSET, description="Documented zero-based start-index. Keep zero when using a continuation.")
    page_token: Optional[str] = Field(None, min_length=1, max_length=16384,
        description="NoClick continuation bound to the current REST key, actor, team context, parent and page size. Not a provider cursor.")


class IlertCheckConfig(IlertReadConfig):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra=HIDDEN)


class IlertTeamsConfig(IlertPageConfig):
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra=HIDDEN)


class IlertTeamConfig(IlertReadConfig):
    team_id: str = Field(..., min_length=1, max_length=19, json_schema_extra=_picker("team_id"))
    _team_value = field_validator("team_id", mode="before")(_id)


class IlertGetTeamConfig(IlertTeamConfig):
    operation: Literal["get_team"] = Field("get_team", json_schema_extra=HIDDEN)


class IlertServicesConfig(IlertPageConfig, IlertTeamConfig):
    operation: Literal["list_services"] = Field("list_services", json_schema_extra=HIDDEN)


class IlertServiceConfig(IlertTeamConfig):
    service_id: str = Field(..., min_length=1, max_length=19, json_schema_extra=_picker("service_id"),
        description="Current service whose documented team references include the selected team.")
    _service_value = field_validator("service_id", mode="before")(_id)


class IlertGetServiceConfig(IlertServiceConfig):
    operation: Literal["get_service"] = Field("get_service", json_schema_extra=HIDDEN)


class IlertIncidentsConfig(IlertPageConfig, IlertServiceConfig):
    operation: Literal["list_incidents"] = Field("list_incidents", json_schema_extra=HIDDEN)


class IlertGetIncidentConfig(IlertServiceConfig):
    operation: Literal["get_incident"] = Field("get_incident", json_schema_extra=HIDDEN)
    incident_id: str = Field(..., min_length=1, max_length=19, json_schema_extra=_picker("incident_id"),
        description="Witnessed in the current service-filtered incident catalog; detail must include the selected affected service.")
    _incident_value = field_validator("incident_id", mode="before")(_id)


class IlertStatusPagesConfig(IlertPageConfig):
    operation: Literal["list_status_pages"] = Field("list_status_pages", json_schema_extra=HIDDEN)
    limit: int = Field(25, strict=True, ge=1, le=50, description="Status-page max-results is capped at 50.")


IlertConfig = Annotated[Union[IlertCheckConfig, IlertTeamsConfig, IlertGetTeamConfig,
    IlertServicesConfig, IlertGetServiceConfig, IlertIncidentsConfig, IlertGetIncidentConfig,
    IlertStatusPagesConfig], Field(discriminator="operation")]


class IlertNodeConfig(NodeConfig[IlertConfig, IlertAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


async def _request(data, kind, *, identifier=None, service=None, limit=None, offset=None):
    data = _credential(data)
    if kind not in ROUTES:
        raise ValueError("Unsupported ilert metadata route.")
    ILERT_SCOPES.enforce_credential_type(kind, data["credential_type"])
    path = ROUTES[kind]
    if "{id}" in path:
        path = path.replace("{id}", _id(identifier))
    elif identifier is not None:
        raise ValueError("This ilert route does not accept an entity ID.")
    params = {}
    if kind in PAGE_CAPS:
        if type(limit) is not int or not 1 <= limit <= PAGE_CAPS[kind] or type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
            raise ValueError("Use bounded documented ilert pagination.")
        params.update({"max-results": limit, "start-index": offset})
    elif limit is not None or offset is not None:
        raise ValueError("Only catalogs support pagination.")
    if service is not None:
        if kind != "incidents":
            raise ValueError("Only the incident catalog supports the documented services filter.")
        params["services"] = _id(service)
    headers = {"Authorization": "Bearer "+data["access_token"], "Accept": "application/json",
        "User-Agent": "NoClick-ilert/1.0 (+https://noclick.com)"}
    if data["team_context"] is not None:
        headers["team-context"] = str(data["team_context"])
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25) as client:
            response = await client.get(API_ROOT+path, headers=headers, params=params)
    except Exception:
        raise RuntimeError("ilert could not be reached; access remains unverified.") from None
    if response.status_code != 200:
        messages = {400: "ilert refused the metadata parameters.", 401: "ilert did not confirm REST key access.",
            403: "ilert did not confirm access to this resource.", 404: "The selected ilert resource is unavailable.",
            429: "ilert throttled the request; try again later.", 500: "ilert metadata is unavailable."}
        raise RuntimeError(messages.get(response.status_code, "ilert did not return usable metadata."))
    if len(response.content) > 2000000:
        raise RuntimeError("ilert metadata exceeded the response bound.")
    try:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" and not mime.endswith("+json"):
            raise ValueError()
        body = response.json()
        if not isinstance(body, (dict, list)) or isinstance(body, dict) and any(k in body for k in ("error", "errors", "message", "code")):
            raise ValueError()
        return body
    except Exception:
        raise RuntimeError("ilert returned an unsupported metadata response.") from None


def _refs(raw):
    if not isinstance(raw, list) or len(raw) > 1000:
        raise ValueError()
    values = []
    for row in raw:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError()
        values.append(_id(row["id"]))
    if len(set(values)) != len(values):
        raise ValueError()
    return values


def _row(raw, kind, names=False, identifier=None):
    try:
        if not isinstance(raw, dict) or type(raw.get("id")) is not int:
            raise ValueError()
        out = {"id": _id(raw["id"])}
        if identifier is not None and out["id"] != identifier:
            raise ValueError()
        for key in ({"actor": ("createdAt", "updatedAt"), "team": ("createdAt", "updatedAt"),
            "incident": ("declaredAt", "resolvedAt")}.get(kind, ())):
            if key in raw:
                value = raw[key]
                if value is not None:
                    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
                        raise ValueError()
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                out[key] = value
        if kind in {"service", "incident", "statuspage"} and raw.get("status") is not None:
            states = INCIDENT_STATES if kind == "incident" else SERVICE_STATES
            if raw["status"] not in states:
                raise ValueError()
            out["status"] = raw["status"]
        if kind == "service":
            out["team_ids"] = _refs(raw.get("teams"))
        if kind == "incident":
            if raw.get("severity") is not None:
                if type(raw["severity"]) is not int or not 1 <= raw["severity"] <= 5:
                    raise ValueError()
                out["severity"] = raw["severity"]
            if "affectedServices" in raw:
                affected = raw["affectedServices"]
                if not isinstance(affected, list) or len(affected) > 1000:
                    raise ValueError()
                out["affected_services"] = []
                for entry in affected:
                    if not isinstance(entry, dict):
                        raise ValueError()
                    service = entry.get("service")
                    if not isinstance(service, dict) or type(service.get("id")) is not int:
                        raise ValueError()
                    item = {"id": _id(service["id"])}
                    for key, source in (("impact", entry), ("status", service)):
                        if source.get(key) is not None:
                            if source[key] not in SERVICE_STATES:
                                raise ValueError()
                            item[key] = source[key]
                    out["affected_services"].append(item)
                if len({x["id"] for x in out["affected_services"]}) != len(out["affected_services"]):
                    raise ValueError()
        label = "title" if kind == "incident" else "name"
        if names and kind != "actor" and label in raw:
            out[label] = _text(raw[label])
        return out
    except Exception:
        raise RuntimeError("ilert returned metadata outside the expected resource or actor contract.") from None


async def _actor(data):
    return _row(await _request(data, "actor"), "actor", identifier=data["actor_id"])


async def _catalog(data, kind, *, team=None, service=None, limit=50, offset=0, names=False):
    body = await _request(data, kind, service=service, limit=limit, offset=offset)
    if not isinstance(body, list) or len(body) > limit:
        raise RuntimeError("ilert returned an unsupported or excessive catalog page.")
    singular = {"teams": "team", "services": "service", "incidents": "incident", "statuspages": "statuspage"}[kind]
    rows = [_row(raw, singular, names) for raw in body]
    if len({row["id"] for row in rows}) != len(rows):
        raise RuntimeError("ilert returned duplicate IDs in a catalog page.")
    if kind == "services" and team is not None:
        rows = [row for row in rows if team in row["team_ids"]]
    return rows, len(body)


async def _witness(data, kind, identifier, *, team=None, service=None):
    offset, limit = 0, PAGE_CAPS[kind]
    for _ in range(WITNESS_PAGES):
        rows, count = await _catalog(data, kind, team=team, service=service, limit=limit, offset=offset)
        if any(row["id"] == identifier for row in rows):
            return
        if count < limit or offset+count > MAX_OFFSET:
            break
        offset += count
    raise ValueError("The selected ilert resource was not witnessed in the bounded current catalog; access remains unverified.")


def _key(data):
    return hashlib.sha256(json.dumps([data["access_token"], data["actor_id"], data["team_context"]], separators=(",", ":")).encode()).digest()


def _token(data, scope, offset):
    payload = json.dumps({"scope": scope, "offset": offset}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(hmac.new(_key(data), payload, hashlib.sha256).digest()+payload).decode().rstrip("=")


def _offset(data, token, scope, initial=0):
    if token is None:
        return initial
    try:
        if initial != 0 or not isinstance(token, str) or len(token) > 16384 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        raw = base64.b64decode(token+"="*(-len(token)%4), altchars=b"-_", validate=True)
        mac, payload = raw[:32], raw[32:]
        value = json.loads(payload)
        if not hmac.compare_digest(mac, hmac.new(_key(data), payload, hashlib.sha256).digest()) or set(value) != {"scope", "offset"} or value["scope"] != scope or type(value["offset"]) is not int or not 0 <= value["offset"] <= MAX_OFFSET:
            raise ValueError()
        return value["offset"]
    except Exception:
        raise ValueError("The ilert continuation belongs to another current key, actor, team context, parent or query; keep offset zero.") from None


async def _page(data, kind, scope, *, team=None, service=None, limit=50, offset=0, token=None, names=False, search=None):
    start = _offset(data, token, scope, offset)
    rows, count = await _catalog(data, kind, team=team, service=service, limit=limit, offset=start, names=names)
    next_offset = start+count
    selected = [row for row in rows if search.casefold() in row["id"].casefold()] if search else rows
    return {"items": selected, "returned": len(selected), "provider_returned": count, "offset": start, "limit": limit,
        "total": None, "has_more": None, "completion": "unknown",
        "next_page_token": _token(data, scope, next_offset) if count == limit and next_offset <= MAX_OFFSET else None,
        "continuation_limit_reached": count == limit and next_offset > MAX_OFFSET}


class IlertNode(WorkflowNode):
    integration_type = "automation-ilert"
    credential_provider_labels = {"ilert": "Ilert Account"}
    auto_select_credential = False
    scope_registry = ILERT_SCOPES
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="current user IDs", label_keys=("id",), proves="account")

    @classmethod
    def get_config_model(cls):
        return IlertNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging resolves stored credentials before invoking this non-rotating key hook.
        return _credential(credential_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            await _actor(_credential(credential_data))
        except (ValueError, RuntimeError):
            return {"valid": None}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        if field_name not in {"team_id", "service_id", "incident_id"} or context is not None and not isinstance(context, dict):
            raise ValueError("Use a supported ilert resource selector.")
        context = context or {}
        search = _text(search, 256) if search is not None else None
        team = _id(context.get("team_id")) if field_name != "team_id" else None
        service = _id(context.get("service_id")) if field_name == "incident_id" else None
        kind = {"team_id": "teams", "service_id": "services", "incident_id": "incidents"}[field_name]
        scope = {"selector": field_name, "team_id": team, "service_id": service, "search": search, "limit": 50}
        _offset(data, page_token, scope)
        await _actor(data)
        if team is not None:
            await _witness(data, "teams", team)
        if service is not None:
            await _witness(data, "services", service, team=team)
        page = await _page(data, kind, scope, team=team, service=service, token=page_token, search=search)
        return {"options": [{"value": row["id"], "label": row["id"]} for row in page["items"]], "next_page_token": page["next_page_token"]}

    async def execute(self, inputs):
        if not isinstance(self.config, IlertNodeConfig) or not self.config.credentials:
            raise ValueError("ilert configuration and an existing actor-bound REST key are required.")
        raw = (self.node_data or {}).get("credentials")
        if not (self.node_data or {}).get("credential_id") and isinstance(raw, dict):
            _credential(raw)
        data = _credential(raw if isinstance(raw, dict) else self.config.credentials.model_dump(mode="json"))
        c, op = self.config.config, self.config.config.operation
        scope = c.model_dump(mode="json", exclude={"page_token", "offset"})
        if isinstance(c, IlertPageConfig):
            _offset(data, c.page_token, scope, c.offset)
        actor = await _actor(data)
        common = {"current_user_id": actor["id"], "proof": "Protected actor ID and current VIEW-permitted resource ancestry; team membership, tenant identity and incident ownership are not inferred."}
        if op == "check_connection":
            return {**common, "items": [actor], "protected_actor": True}
        if op in {"list_teams", "list_status_pages"}:
            kind = "teams" if op == "list_teams" else "statuspages"
            return {**common, **await _page(data, kind, scope, limit=c.limit, offset=c.offset, token=c.page_token, names=c.include_names)}
        await _witness(data, "teams", c.team_id)
        common["selected_team_id"] = c.team_id
        if op == "get_team":
            return {**common, "team": _row(await _request(data, "team", identifier=c.team_id), "team", c.include_names, c.team_id)}
        if op == "list_services":
            return {**common, **await _page(data, "services", scope, team=c.team_id, limit=c.limit, offset=c.offset, token=c.page_token, names=c.include_names)}
        await _witness(data, "services", c.service_id, team=c.team_id)
        common["selected_service_id"] = c.service_id
        if op == "get_service":
            row = _row(await _request(data, "service", identifier=c.service_id), "service", c.include_names, c.service_id)
            if c.team_id not in row["team_ids"]:
                raise RuntimeError("The current ilert service no longer references the selected team.")
            return {**common, "service": row}
        if op == "list_incidents":
            return {**common, **await _page(data, "incidents", scope, service=c.service_id, limit=c.limit, offset=c.offset, token=c.page_token, names=c.include_names)}
        if op == "get_incident":
            await _witness(data, "incidents", c.incident_id, service=c.service_id)
            row = _row(await _request(data, "incident", identifier=c.incident_id), "incident", c.include_names, c.incident_id)
            if not any(item["id"] == c.service_id for item in row.get("affected_services", [])):
                raise RuntimeError("The current ilert incident does not include the selected affected service.")
            return {**common, "incident": row}
        raise ValueError("Unsupported ilert metadata operation.")
