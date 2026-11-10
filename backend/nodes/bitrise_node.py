"""Bitrise reads protected app, branch and build metadata through six native operations.
Closed projections exclude repositories, owners, commits, secrets and control capabilities.
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

API_ROOT = "https://api.bitrise.io/v0.1"
HIDDEN = {"ui:hidden": True}
WITNESS_PAGES = 5
ROUTES = {"apps": "/apps", "app": "/apps/{app}", "branches": "/apps/{app}/branches",
    "builds": "/apps/{app}/builds", "build": "/apps/{app}/builds/{build}"}
BITRISE_SCOPES = ScopeRegistry("bitrise", {route: ScopeRequirement((), credential_types=("bitrise_api_token",),
    note="Existing personal or workspace API token; current provider permissions apply. No OAuth scopes are invented.") for route in ROUTES})


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Use an existing bounded Bitrise app or build slug, not a URL.")
    return value


def _text(value, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]|://|www\.", value, re.I):
        raise ValueError("Use bounded text without control characters or URLs.")
    return value.strip()


class BitriseAPITokenCredential(BaseModel):
    credential_type: Literal["bitrise_api_token"] = Field("bitrise_api_token", json_schema_extra=HIDDEN)
    access_token: str = Field(..., min_length=1, max_length=8192, title="Existing Bitrise Personal or Workspace API Token",
        description="Sent directly as the Authorization header. Do not include Bearer or use an add-on token. No token issuance, exchange or assumed lifetime.",
        json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.bitrise.io/en/bitrise-ci/api/authenticating-with-the-bitrise-api",
        "x-credential-instructions": "Use an existing personal access token or Workspace API token. Protected app catalog access proves reachability, not an actor ID or workspace membership. No OAuth flow or add-on key is implemented."})

    @field_validator("access_token", mode="before")
    @classmethod
    def issued_token(cls, value):
        if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f]|://", value):
            raise ValueError("Supply the existing raw API token without whitespace, a prefix or URL.")
        return value


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "bitrise_api_token":
        raise ValueError("Use the current Bitrise personal or workspace API token credential.")
    try:
        shaped = BitriseAPITokenCredential.model_validate({k: data[k] for k in BitriseAPITokenCredential.model_fields if k in data})
    except Exception:
        raise ValueError("The Bitrise API token is incomplete or invalid.") from None
    return {**data, **shaped.model_dump(mode="json")}


def _picker(field):
    result = {"x-dynamic-options": {"field": field}}
    if field == "build_slug":
        result["x-dynamic-options"]["depends_on"] = "app_slug"
    return result


class BitriseReadConfig(BaseModel):
    include_names: bool = Field(False, strict=True, description="Opt in to app titles and branch names. Owner, repository, commit and capability fields are always excluded.")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BitrisePageConfig(BitriseReadConfig):
    limit: int = Field(50, strict=True, ge=1, le=50, description="Documented per-page limit, capped at 50.")
    page_token: Optional[str] = Field(None, min_length=1, max_length=16384,
        description="NoClick continuation wrapping the provider's same-endpoint paging.next anchor; bound to current token, operation and app.")


class BitriseCheckConfig(BitriseReadConfig):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra=HIDDEN)


class BitriseAppsConfig(BitrisePageConfig):
    operation: Literal["list_apps"] = Field("list_apps", json_schema_extra=HIDDEN)


class BitriseAppConfig(BitriseReadConfig):
    app_slug: str = Field(..., min_length=1, max_length=128, json_schema_extra=_picker("app_slug"),
        description="Must be witnessed in the current protected accessible-app catalog; does not imply ownership.")
    _app_value = field_validator("app_slug", mode="before")(_slug)


class BitriseGetAppConfig(BitriseAppConfig):
    operation: Literal["get_app"] = Field("get_app", json_schema_extra=HIDDEN)


class BitriseBranchesConfig(BitriseAppConfig):
    operation: Literal["list_branches"] = Field("list_branches", json_schema_extra=HIDDEN)
    max_names: int = Field(100, strict=True, ge=1, le=500,
        description="Local output bound only; this route has no documented paging. Names require Include Names and only branches with existing builds are listed.")


class BitriseBuildsConfig(BitrisePageConfig, BitriseAppConfig):
    operation: Literal["list_builds"] = Field("list_builds", json_schema_extra=HIDDEN)


class BitriseGetBuildConfig(BitriseAppConfig):
    operation: Literal["get_build"] = Field("get_build", json_schema_extra=HIDDEN)
    build_slug: str = Field(..., min_length=1, max_length=128, json_schema_extra=_picker("build_slug"),
        description="Witnessed in the selected app's current build catalog before the app-bound detail read.")
    _build_value = field_validator("build_slug", mode="before")(_slug)


BitriseConfig = Annotated[Union[BitriseCheckConfig, BitriseAppsConfig, BitriseGetAppConfig,
    BitriseBranchesConfig, BitriseBuildsConfig, BitriseGetBuildConfig], Field(discriminator="operation")]


class BitriseNodeConfig(NodeConfig[BitriseConfig, BitriseAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


async def _request(data, kind, *, app=None, build=None, limit=None, anchor=None):
    data = _credential(data)
    if kind not in ROUTES:
        raise ValueError("Unsupported Bitrise metadata route.")
    BITRISE_SCOPES.enforce_credential_type(kind, data["credential_type"])
    path = ROUTES[kind]
    for key, value in (("app", app), ("build", build)):
        if "{"+key+"}" in path:
            path = path.replace("{"+key+"}", _slug(value))
        elif value is not None:
            raise ValueError("This Bitrise metadata route does not accept that resource.")
    params = {}
    if kind in {"apps", "builds"}:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Use Bitrise's documented limit from 1 to 50.")
        params["limit"] = limit
        if anchor is not None:
            params["next"] = _slug(anchor)
    elif limit is not None or anchor is not None:
        raise ValueError("Only Bitrise app and build catalogs have documented paging.")
    headers = {"Authorization": data["access_token"], "Accept": "application/json",
        "User-Agent": "NoClick-Bitrise/1.0 (+https://noclick.com)"}
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25) as client:
            response = await client.get(API_ROOT+path, headers=headers, params=params)
    except Exception:
        raise RuntimeError("Bitrise could not be reached; access remains unverified.") from None
    if response.status_code != 200:
        messages = {400: "Bitrise refused the metadata parameters.", 401: "Bitrise did not confirm API token access.",
            403: "Bitrise did not confirm access to this resource.", 404: "The selected Bitrise resource is unavailable.",
            429: "Bitrise throttled the metadata request; try again later.", 500: "Bitrise metadata is unavailable."}
        raise RuntimeError(messages.get(response.status_code, "Bitrise did not return usable metadata."))
    if len(response.content) > 2000000:
        raise RuntimeError("Bitrise metadata exceeded the client response bound.")
    try:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" and not mime.endswith("+json"):
            raise ValueError()
        body = response.json()
        if not isinstance(body, dict) or "data" not in body or any(k in body for k in ("error", "errors")) or body.get("success") is False:
            raise ValueError()
        return body
    except Exception:
        raise RuntimeError("Bitrise returned an unsupported metadata envelope.") from None


def _row(raw, kind, names=False, slug=None):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        row = {"slug": _slug(raw.get("slug"))}
        if slug is not None and row["slug"] != slug:
            raise ValueError()
        if "status" in raw:
            value = raw["status"]
            if type(value) is not int or not -(2**31) <= value < 2**31:
                raise ValueError()
            row["status"] = value
        if kind == "app":
            if raw.get("project_type") is not None:
                row["project_type"] = _text(raw["project_type"], 128)
            if names and raw.get("title") is not None:
                row["title"] = _text(raw["title"])
        else:
            if raw.get("build_number") is not None:
                value = raw["build_number"]
                if type(value) is not int or not 0 <= value <= 2**63-1:
                    raise ValueError()
                row["build_number"] = str(value)
            for key in ("triggered_at", "started_on_worker_at", "environment_prepare_finished_at", "finished_at"):
                if key in raw:
                    value = raw[key]
                    if value is not None:
                        if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
                            raise ValueError()
                        datetime.fromisoformat(value.replace("Z", "+00:00"))
                    row[key] = value
            if names and raw.get("branch") is not None:
                row["branch"] = _text(raw["branch"])
        return row
    except Exception:
        raise RuntimeError("Bitrise returned metadata outside the selected resource contract.") from None


async def _catalog(data, kind, *, app=None, limit=50, anchor=None, names=False):
    body = await _request(data, kind, app=app, limit=limit, anchor=anchor)
    raw = body["data"]
    if not isinstance(raw, list) or len(raw) > limit:
        raise RuntimeError("Bitrise returned an unsupported or excessive catalog page.")
    rows = [_row(item, "app" if kind == "apps" else "build", names) for item in raw]
    if len({row["slug"] for row in rows}) != len(rows):
        raise RuntimeError("Bitrise returned duplicate resource slugs in one page.")
    try:
        paging = body.get("paging", {})
        if not isinstance(paging, dict):
            raise ValueError()
        next_anchor = paging.get("next")
        if next_anchor == "":
            next_anchor = None
        if next_anchor is not None:
            next_anchor = _slug(next_anchor)
            if next_anchor == anchor:
                raise ValueError()
        total, page_limit = paging.get("total_item_count"), paging.get("page_item_limit")
        if total is not None and (type(total) is not int or not len(rows) <= total <= 2**63-1):
            raise ValueError()
        if page_limit is not None and (type(page_limit) is not int or not 1 <= page_limit <= 50 or len(rows) > page_limit):
            raise ValueError()
        return rows, next_anchor, total, page_limit
    except Exception:
        raise RuntimeError("Bitrise returned unsupported same-endpoint paging metadata.") from None


async def _witness(data, kind, slug, *, app=None):
    anchor, seen = None, set()
    for _ in range(WITNESS_PAGES):
        rows, following, _, _ = await _catalog(data, kind, app=app, anchor=anchor)
        if any(row["slug"] == slug for row in rows):
            return
        if following is None:
            break
        if following in seen:
            raise RuntimeError("Bitrise returned a repeated catalog anchor.")
        seen.add(following)
        anchor = following
    raise ValueError("The selected Bitrise resource was not witnessed in the bounded current parent catalog; access remains unverified.")


def _token(data, scope, anchor):
    payload = json.dumps({"scope": scope, "anchor": anchor}, sort_keys=True, separators=(",", ":")).encode()
    key = hashlib.sha256(data["access_token"].encode()).digest()
    return base64.urlsafe_b64encode(hmac.new(key, payload, hashlib.sha256).digest()+payload).decode().rstrip("=")


def _anchor(data, token, scope):
    if token is None:
        return None
    try:
        if not isinstance(token, str) or len(token) > 16384 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        raw = base64.b64decode(token+"="*(-len(token)%4), altchars=b"-_", validate=True)
        mac, payload = raw[:32], raw[32:]
        key = hashlib.sha256(data["access_token"].encode()).digest()
        value = json.loads(payload)
        if not hmac.compare_digest(mac, hmac.new(key, payload, hashlib.sha256).digest()) or set(value) != {"scope", "anchor"} or value["scope"] != scope:
            raise ValueError()
        return _slug(value["anchor"])
    except Exception:
        raise ValueError("The Bitrise continuation belongs to another current token, operation, app, page size or search.") from None


async def _page(data, kind, scope, *, app=None, limit=50, token=None, names=False, search=None):
    rows, following, total, page_limit = await _catalog(data, kind, app=app, limit=limit,
        anchor=_anchor(data, token, scope), names=names)
    selected = [row for row in rows if search.casefold() in row["slug"].casefold()] if search else rows
    return {"items": selected, "returned": len(selected), "provider_returned": len(rows),
        "total_item_count": str(total) if total is not None else None, "page_item_limit": page_limit,
        "has_more": following is not None, "next_page_token": _token(data, scope, following) if following else None,
        "completion": "Provider paging.next anchor"}


class BitriseNode(WorkflowNode):
    integration_type = "automation-bitrise"
    credential_provider_labels = {"bitrise": "Bitrise Account"}
    auto_select_credential = False
    scope_registry = BITRISE_SCOPES
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="accessible app slugs", label_keys=("slug",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BitriseNodeConfig

    @classmethod
    async def validate_credential_access(cls, credential_data):
        await _catalog(_credential(credential_data), "apps")
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        if field_name not in {"app_slug", "build_slug"} or context is not None and not isinstance(context, dict):
            raise ValueError("Use a supported Bitrise app or build selector.")
        search = _text(search, 256) if search is not None else None
        app = _slug((context or {}).get("app_slug")) if field_name == "build_slug" else None
        scope = {"selector": field_name, "app_slug": app, "search": search, "limit": 50}
        _anchor(data, page_token, scope)
        if app is not None:
            await _witness(data, "apps", app)
        page = await _page(data, "builds" if app else "apps", scope, app=app, token=page_token, search=search)
        return {"options": [{"value": row["slug"], "label": row["slug"]} for row in page["items"]], "next_page_token": page["next_page_token"]}

    async def execute(self, inputs):
        if not isinstance(self.config, BitriseNodeConfig) or not self.config.credentials:
            raise ValueError("Bitrise configuration and an existing API token are required.")
        raw = (self.node_data or {}).get("credentials")
        data = _credential(raw if isinstance(raw, dict) else self.config.credentials.model_dump(mode="json"))
        c, op = self.config.config, self.config.config.operation
        scope = c.model_dump(mode="json", exclude={"page_token"})
        if isinstance(c, BitrisePageConfig):
            _anchor(data, c.page_token, scope)
        common = {"proof": "Protected accessible-app catalog and current app/build URL ancestry; actor identity, workspace membership and ownership are not inferred."}
        if op == "check_connection":
            return {**common, **await _page(data, "apps", scope), "protected_catalog": True}
        if op == "list_apps":
            return {**common, **await _page(data, "apps", scope, limit=c.limit, token=c.page_token, names=c.include_names)}
        await _witness(data, "apps", c.app_slug)
        common["selected_app_slug"] = c.app_slug
        if op == "get_app":
            body = await _request(data, "app", app=c.app_slug)
            return {**common, "app": _row(body["data"], "app", c.include_names, c.app_slug)}
        if op == "list_branches":
            body = await _request(data, "branches", app=c.app_slug)
            branches = body["data"]
            if not isinstance(branches, list) or len(branches) > 5000 or any(not isinstance(x, str) for x in branches):
                raise RuntimeError("Bitrise returned an unsupported or excessive branch catalog.")
            try:
                names = [_text(name) for name in branches[:c.max_names]] if c.include_names else []
            except Exception:
                raise RuntimeError("Bitrise returned unsupported branch names.") from None
            return {**common, "branch_count": len(branches), "branches": names, "names_included": c.include_names,
                "local_truncated": c.include_names and len(branches) > c.max_names,
                "scope": "Only branches with existing builds; no documented branch pagination."}
        if op == "list_builds":
            return {**common, **await _page(data, "builds", scope, app=c.app_slug, limit=c.limit, token=c.page_token, names=c.include_names)}
        if op == "get_build":
            await _witness(data, "builds", c.build_slug, app=c.app_slug)
            body = await _request(data, "build", app=c.app_slug, build=c.build_slug)
            return {**common, "build": _row(body["data"], "build", c.include_names, c.build_slug),
                "ancestry": "Build slug witnessed in the selected app's current build URL catalog; no returned app parent or owner field is invented."}
        raise ValueError("Unsupported Bitrise metadata operation.")
