"""Koyeb organization-bound inventory, status and empty-app metadata operations.

Only fixed native v1 routes are exposed. Projections omit service definitions,
environment values, logs, billing, domain configuration and provider errors.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

ROOT = "https://app.koyeb.com"
HIDDEN = {"ui:hidden": True}
MAX_OFFSET = 1000000


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Use an actual Koyeb UUID identifier.") from None


def _text(value, maximum=256):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Use bounded nonempty text without control characters.")
    return value


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise ValueError("Use a 1–63 character lowercase app slug with letters, digits or internal hyphens.")
    return value


class KoyebAPIKeyCredential(BaseModel):
    credential_type: Literal["koyeb_api_key"] = Field("koyeb_api_key", json_schema_extra=HIDDEN)
    api_key: str = Field(..., min_length=1, max_length=4096, title="Koyeb API Token",
        description="Existing token sent only in the Bearer header. Its current organization must match the UUID below.", json_schema_extra={"ui:widget": "password"})
    organization_id: UUID = Field(..., title="Koyeb Organization ID", description="Explicit organization UUID. The read-only current-organization check must match it.")
    model_config = ConfigDict(title="Koyeb API Token", extra="ignore", json_schema_extra={"x-credential-url": "https://www.koyeb.com/docs/reference/api"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key_value(cls, value):
        value = clean_secret(value)
        if re.search(r"[^\x21-\x7e]", value) or value.lower().startswith(("bearer", "token ")):
            raise ValueError("Paste the API token without whitespace or an authentication prefix.")
        return value


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "koyeb_api_key":
        raise ValueError("Use a current organization-bound Koyeb API-token connection.")
    try:
        shaped = KoyebAPIKeyCredential.model_validate({key: data[key] for key in KoyebAPIKeyCredential.model_fields if key in data}).model_dump(mode="json")
    except Exception:
        raise ValueError("The Koyeb token or organization binding is invalid.") from None
    return {**data, **shaped}


def _picker(field, *parents):
    dynamic = {"field_name": field, "searchable": True, "allow_custom": True}
    if parents:
        dynamic["depends_on"] = parents[-1]
    return {"x-dynamic-options": dynamic, "x-resource-type": "koyeb_" + field.removesuffix("_id")}


class KoyebOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KoyebCheckConnectionConfig(KoyebOperation):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"x-display-name": "Check Organization Access", "x-category": "Connection"})


class KoyebGetOrganizationConfig(KoyebOperation):
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"x-display-name": "Get Bound Organization", "x-category": "Organization"})


class KoyebPage(KoyebOperation):
    limit: int = Field(50, ge=1, le=100, title="Page Size")
    offset: int = Field(0, ge=0, le=MAX_OFFSET, description="Initial offset. Continuation uses the node's returned page token.")
    page_token: Optional[str] = Field(None, max_length=2048, title="Next Page Token", description="Bound to this organization, resource parents, search and page size; never a URL.")
    search: Optional[str] = Field(None, max_length=256, description="Local substring filter on this page's name/ID/status. A zero-match page can still have a continuation.")
    _search_value = field_validator("search")(lambda value: _text(value) if value else None)


class KoyebListAppsConfig(KoyebPage):
    operation: Literal["list_apps"] = Field("list_apps", json_schema_extra={"x-display-name": "List Apps", "x-category": "Apps"})


class KoyebAppTarget(KoyebOperation):
    app_id: UUID = Field(..., title="App", json_schema_extra=_picker("app_id"))


class KoyebGetAppConfig(KoyebAppTarget):
    operation: Literal["get_app"] = Field("get_app", json_schema_extra={"x-display-name": "Get App Metadata", "x-category": "Apps"})


class KoyebCreateEmptyAppConfig(KoyebOperation):
    operation: Literal["create_empty_app"] = Field("create_empty_app", json_schema_extra={"x-display-name": "Create Empty App", "x-category": "Apps"})
    name: str = Field(..., min_length=1, max_length=63, title="New App Name", description="Node accepts a lowercase slug. Creates the app container and Koyeb's managed subdomain; no service, build or instance is provisioned by this operation.")
    _name_value = field_validator("name")(_name)


class KoyebEmptyAppTarget(KoyebAppTarget):
    expected_name: str = Field(..., min_length=1, max_length=256, title="Expected Current Name", description="Must match the readback. Empty-service and no-custom-domain preflight is observational, not an atomic concurrency guarantee.")
    _expected_value = field_validator("expected_name")(_text)


class KoyebRenameEmptyAppConfig(KoyebEmptyAppTarget):
    operation: Literal["rename_empty_app"] = Field("rename_empty_app", json_schema_extra={"x-display-name": "Rename Empty App", "x-category": "Apps"})
    name: str = Field(..., min_length=1, max_length=63, title="New App Name", description="Updates name only, then reads it back. No domain update is sent.")
    _name_value = field_validator("name")(_name)


class KoyebDeleteEmptyAppConfig(KoyebEmptyAppTarget):
    operation: Literal["delete_empty_app"] = Field("delete_empty_app", json_schema_extra={"x-display-name": "Delete Empty App", "x-category": "Apps"})


class KoyebListServicesConfig(KoyebAppTarget, KoyebPage):
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"x-display-name": "List App Services", "x-category": "Services"})


class KoyebServiceTarget(KoyebAppTarget):
    service_id: UUID = Field(..., title="Service", json_schema_extra=_picker("service_id", "app_id"))


class KoyebGetServiceConfig(KoyebServiceTarget):
    operation: Literal["get_service"] = Field("get_service", json_schema_extra={"x-display-name": "Get Service Status", "x-category": "Services"})


class KoyebListDeploymentsConfig(KoyebServiceTarget, KoyebPage):
    operation: Literal["list_deployments"] = Field("list_deployments", json_schema_extra={"x-display-name": "List Service Deployments", "x-category": "Deployments"})


class KoyebGetDeploymentConfig(KoyebServiceTarget):
    operation: Literal["get_deployment"] = Field("get_deployment", json_schema_extra={"x-display-name": "Get Deployment Status", "x-category": "Deployments"})
    deployment_id: UUID = Field(..., title="Deployment", json_schema_extra=_picker("deployment_id", "app_id", "service_id"))


class KoyebListInstancesConfig(KoyebServiceTarget, KoyebPage):
    operation: Literal["list_instances"] = Field("list_instances", json_schema_extra={"x-display-name": "List Service Instances", "x-category": "Instances"})


class KoyebGetInstanceConfig(KoyebServiceTarget):
    operation: Literal["get_instance"] = Field("get_instance", json_schema_extra={"x-display-name": "Get Instance Status", "x-category": "Instances"})
    instance_id: UUID = Field(..., title="Instance", json_schema_extra=_picker("instance_id", "app_id", "service_id"))


KoyebConfig = Annotated[Union[KoyebCheckConnectionConfig, KoyebGetOrganizationConfig, KoyebListAppsConfig,
    KoyebGetAppConfig, KoyebCreateEmptyAppConfig, KoyebRenameEmptyAppConfig, KoyebDeleteEmptyAppConfig,
    KoyebListServicesConfig, KoyebGetServiceConfig, KoyebListDeploymentsConfig, KoyebGetDeploymentConfig,
    KoyebListInstancesConfig, KoyebGetInstanceConfig], Field(discriminator="operation")]


class KoyebNodeConfig(NodeConfig[KoyebConfig, KoyebAPIKeyCredential]):
    pass


async def _request(data, method, path, *, params=None, body=None, missing=False):
    data = _credential(data)
    item = re.fullmatch(r"/v1/(apps|services|deployments|instances)/[0-9a-f-]{36}", path)
    if not (method == "GET" and (path == "/v1/account/organization" or path in {"/v1/apps", "/v1/services", "/v1/deployments", "/v1/instances"} or item)
            or method == "POST" and path == "/v1/apps"
            or method in {"PATCH", "DELETE"} and item and item[1] == "apps"):
        raise ValueError("Unsupported native Koyeb route.")
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25.0) as client:
            response = await client.request(method, ROOT + path, params=params, json=body,
                headers={"Authorization": "Bearer " + data["api_key"], "Accept": "application/json"})
    except Exception:
        raise RuntimeError("Koyeb request could not complete; access or write completion remains unverified. No retry occurred.") from None
    if missing and method == "GET" and item and item[1] == "apps" and response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError({401: "Koyeb access remains unverified; check the current token and organization.",
            403: "Koyeb access remains unverified; check current organization permissions.",
            404: "Koyeb resource is not currently available.", 429: "Koyeb rate limit reached; no retry occurred."}.get(response.status_code,
                "Koyeb did not return the documented HTTP 200 response; completion remains unverified."))
    try:
        if not response.content or len(response.content) > 2000000:
            raise ValueError()
        result = response.json()
        if not isinstance(result, dict) or any(key in result for key in ("error", "errors", "detail", "code")):
            raise ValueError()
    except Exception:
        raise RuntimeError("Koyeb returned malformed or excessive content; private response details were omitted.") from None
    return result


def _project(raw, kind, data, parents=None, expected=None):
    try:
        if not isinstance(raw, dict) or _uuid(raw["id"]) != (expected or _uuid(raw["id"])):
            raise ValueError()
        if kind == "organization":
            if _uuid(raw["id"]) != data["organization_id"]:
                raise ValueError()
        elif _uuid(raw["organization_id"]) != data["organization_id"]:
            raise ValueError()
        for key, value in (parents or {}).items():
            if _uuid(raw[key]) != value:
                raise ValueError()
        out = {"id": _uuid(raw["id"])}
        identifiers = {"organization": (), "app": ("organization_id",),
            "service": ("organization_id", "app_id", "project_id", "active_deployment_id", "latest_deployment_id"),
            "deployment": ("organization_id", "app_id", "service_id", "project_id", "parent_id", "child_id"),
            "instance": ("organization_id", "app_id", "service_id")}[kind]
        for key in identifiers:
            if raw.get(key):
                out[key] = _uuid(raw[key])
        text_keys = {"organization": ("name", "status"), "app": ("name", "status", "version"),
            "service": ("name", "status", "type", "version"), "deployment": ("status", "version"),
            "instance": ("status", "type", "region")}[kind]
        for key in text_keys:
            if raw.get(key) is not None:
                out[key] = _text(raw[key], 256)
        if "version" in out and (not out["version"].isascii() or not out["version"].isdigit() or len(out["version"]) > 20 or int(out["version"]) > 18446744073709551615):
            raise ValueError()
        if kind in {"organization", "app", "service"}:
            out["name"] = _text(raw["name"])
        for key in (() if kind == "organization" else ("created_at", "updated_at", "allocated_at", "started_at", "succeeded_at", "paused_at", "resumed_at", "terminated_at")):
            if key in raw:
                value = raw[key]
                if value is not None and (not isinstance(value, str) or len(value) > 64 or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None):
                    raise ValueError()
                out[key] = value
        if kind == "instance" and "replica_index" in raw:
            if type(raw["replica_index"]) is not int or raw["replica_index"] < 0:
                raise ValueError()
            out["replica_index"] = raw["replica_index"]
        return out
    except Exception:
        raise RuntimeError("Koyeb metadata is malformed or outside the selected organization/resource parents; private details were omitted.") from None


async def _organization(data):
    payload = await _request(data, "GET", "/v1/account/organization")
    return _project(payload.get("organization"), "organization", data, expected=data["organization_id"])


async def _get(data, kind, identifier, parents=None):
    payload = await _request(data, "GET", "/v1/" + kind + "s/" + identifier)
    raw = payload.get(kind)
    return _project(raw, kind, data, parents, identifier), raw


def _scope(data, kind, parents, limit, search):
    return {"v": 1, "organization_id": data["organization_id"], "kind": kind, "parents": parents, "limit": limit, "search": search}


def _offset(token, scope, initial):
    if token is None:
        return initial
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {*scope, "offset"} or any(type(value[key]) is not type(expected) or value[key] != expected for key, expected in scope.items()):
            raise ValueError()
        offset = value["offset"]
        if type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
            raise ValueError()
        return offset
    except Exception:
        raise ValueError("Use a Koyeb page token from this organization, resource parents, page size and search.") from None


def _cursor(scope, offset):
    return base64.urlsafe_b64encode(json.dumps({**scope, "offset": offset}, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")


async def _parents(data, parents):
    if "app_id" in parents:
        await _get(data, "app", parents["app_id"])
    if "service_id" in parents:
        await _get(data, "service", parents["service_id"], {"app_id": parents["app_id"]})


async def _list(data, kind, parents, *, limit=50, offset=0, token=None, search=None):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
        raise ValueError("Use a bounded Koyeb page size and offset.")
    if search == "":
        search = None
    if search is not None:
        _text(search)
    scope = _scope(data, kind, parents, limit, search)
    offset = _offset(token, scope, offset)
    await _organization(data)
    await _parents(data, parents)
    payload = await _request(data, "GET", "/v1/" + kind + "s", params={**parents, "limit": limit, "offset": offset})
    try:
        rows, total = payload[kind + "s"], payload["count"]
        if not isinstance(rows, list) or len(rows) > limit or type(total) is not int or total < len(rows):
            raise ValueError()
        if type(payload["limit"]) is not int or payload["limit"] != limit or type(payload["offset"]) is not int or payload["offset"] != offset:
            raise ValueError()
        projected = [_project(row, kind, data, parents) for row in rows]
        if len({row["id"] for row in projected}) != len(projected):
            raise ValueError()
        more = offset + len(rows) < total if kind == "instance" else payload["has_next"]
        if type(more) is not bool or more and not rows:
            raise ValueError()
    except Exception:
        raise RuntimeError("Koyeb returned an invalid list page; private details were omitted.") from None
    next_offset = offset + len(rows)
    bounded = more and next_offset > MAX_OFFSET
    items = projected if not search else [row for row in projected if search.casefold() in " ".join(str(row.get(k, "")) for k in ("id", "name", "status")).casefold()]
    return {"items": items, "organization_id": data["organization_id"], **parents, "limit": limit, "offset": offset,
        "total": total, "returned": len(rows), "matched": len(items), "has_more": more,
        "next_page_token": _cursor(scope, next_offset) if more and not bounded else None,
        "offset_bound_reached": bounded, "search_scope": "Current page only; no automatic page drain."}


async def _empty(data, app, raw, expected_name=None):
    if expected_name is not None and app["name"] != expected_name:
        raise ValueError("The current app name differs from the explicit expected name; no write was sent.")
    domains = raw.get("domains", [])
    if not isinstance(domains, list) or any(not isinstance(domain, dict) or domain.get("type") != "AUTOASSIGNED" for domain in domains):
        raise ValueError("Empty-app writes require no attached custom domains; no write was sent.")
    page = await _list(data, "service", {"app_id": app["id"]}, limit=1)
    if page["returned"] != 0 or page["total"] != 0 or page["has_more"]:
        raise ValueError("This app contains services; empty-app metadata writes were refused.")


class KoyebNode(WorkflowNode):
    integration_type = "automation-koyeb"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="organizations", label_keys=("name", "id"), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return KoyebNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        kinds = {"app_id": "app", "service_id": "service", "deployment_id": "deployment", "instance_id": "instance"}
        if field_name not in kinds or context is not None and not isinstance(context, dict):
            raise ValueError("Use a supported Koyeb inventory selector.")
        context = context or {}
        parents = {}
        if field_name != "app_id":
            parents["app_id"] = _uuid(context.get("app_id"))
        if field_name in {"deployment_id", "instance_id"}:
            parents["service_id"] = _uuid(context.get("service_id"))
        page = await _list(data, kinds[field_name], parents, token=page_token, search=search)
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"] + (" · " + row["status"] if row.get("status") else "")} for row in page["items"]],
            "next_page_token": page["next_page_token"]}

    async def execute(self, inputs):
        if not isinstance(self.config, KoyebNodeConfig) or not self.config.credentials:
            raise ValueError("Koyeb configuration and a connection are required.")
        data = _credential(self.config.credentials.model_dump(mode="json"))
        c, op = self.config.config, self.config.config.operation
        parents = {key: str(getattr(c, key)) for key in ("app_id", "service_id") if hasattr(c, key)}
        if op.startswith("list_"):
            kind = {"list_apps": "app", "list_services": "service", "list_deployments": "deployment", "list_instances": "instance"}[op]
            return await _list(data, kind, parents, limit=c.limit, offset=c.offset, token=c.page_token, search=c.search)
        organization = await _organization(data)
        if op in {"check_connection", "get_organization"}:
            return {"organization_id": data["organization_id"], "organization": organization, "items": [organization],
                "proof": "Current token reaches the explicitly bound organization; no individual account identity claim."}
        if op == "create_empty_app":
            payload = await _request(data, "POST", "/v1/apps", body={"name": c.name})
            app = _project(payload.get("app"), "app", data)
            readback, raw = await _get(data, "app", app["id"])
            await _empty(data, readback, raw, c.name)
            return {"app": readback, "readback_verified": True, "empty_at_readback": True, "http_status": 200,
                "effect": "App container and managed Koyeb subdomain created; no service/build/instance creation request."}
        if op in {"get_service", "get_deployment", "get_instance"}:
            kind = op.removeprefix("get_")
            target = str(getattr(c, kind + "_id"))
            resource_parents = {"app_id": parents["app_id"]} if kind == "service" else parents
            await _parents(data, resource_parents)
            resource, _ = await _get(data, kind, target, resource_parents)
            return {kind: resource, "organization_id": data["organization_id"]}
        app, raw = await _get(data, "app", parents["app_id"])
        if op == "get_app":
            return {"app": app, "organization_id": data["organization_id"]}
        await _empty(data, app, raw, c.expected_name)
        if op == "rename_empty_app":
            payload = await _request(data, "PATCH", "/v1/apps/" + app["id"], params={"update_mask": "name"}, body={"name": c.name})
            _project(payload.get("app"), "app", data, expected=app["id"])
            readback, raw = await _get(data, "app", app["id"])
            await _empty(data, readback, raw, c.name)
            return {"app": readback, "readback_verified": True, "empty_at_readback": True, "http_status": 200}
        acknowledgement = await _request(data, "DELETE", "/v1/apps/" + app["id"])
        if acknowledgement != {}:
            raise RuntimeError("Koyeb deletion acknowledgement is malformed; deletion remains unverified.")
        readback = await _request(data, "GET", "/v1/apps/" + app["id"], missing=True)
        if readback is not None:
            _project(readback.get("app"), "app", data, expected=app["id"])
        return {"app_id": app["id"], "organization_id": data["organization_id"], "http_status": 200,
            "deletion_acknowledged": True, "confirmed_absent": readback is None, "pending": readback is not None,
            "preflight": "No services/custom domains observed before deletion; concurrent changes are not atomically excluded."}
