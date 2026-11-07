"""Scalr v3 metadata only. Protected account access is not actor ownership."""
import json
import re
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

MAX_BYTES = 2 * 1024 * 1024
# Local bounds, not advertised vendor maxima. The OAS page parameters are strings.
MAX_PAGE, MAX_PAGE_SIZE = 1000, 100
ATTRIBUTES = {
    "accounts": ("created-at",),
    "environments": ("created-at", "updated-at", "status", "locked"),
    "workspaces": ("created-at", "updated-at", "locked", "iac-platform", "terraform-version"),
    "runs": ("created-at", "status", "iac-platform", "has-changes", "is-destroy", "is-dry"),
}
RELATIONSHIPS = {"accounts": (), "environments": ("account",), "workspaces": ("environment",), "runs": ("environment", "workspace")}
RUN_STATES = {"pending", "pre_plan_queued", "pre_plan_running", "pre_plan_finished", "plan_queued", "planning", "planned", "confirmed", "discarded", "planned_and_finished", "planned_and_saved", "post_plan_running", "post_plan_finished", "cost_estimating", "cost_estimated", "policy_checking", "policy_override", "policy_checked", "pre_apply_queued", "pre_apply_running", "pre_apply_finished", "apply_queued", "applying", "applied", "post_apply_running", "post_apply_finished", "errored", "canceled"}


def _text(value, limit=300):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use bounded text without control characters")
    if re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("URLs are outside metadata output")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value): raise ValueError("Use a bounded opaque Scalr resource ID")
    return value


def _host(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.scalr\.io", value):
        raise ValueError("Supply a single canonical tenant.scalr.io hostname, without scheme/path/port")
    if value.split(".")[0] in {"www", "docs", "api"}: raise ValueError("Select the actual tenant hostname")
    return value


def _page(value):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,3}", value): value = int(value)
    if type(value) is not int or not 1 <= value <= MAX_PAGE: raise ValueError("Use a bounded positive page number")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected the documented JSON:API object")
    return value


class ScalrTokenCredential(BaseModel):
    model_config = ConfigDict(title="Scalr Existing Bearer Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.scalr.io/reference/overview-1", "x-credential-instructions": "Supply an existing personal or service-account Bearer token, canonical tenant.scalr.io host, and independently known accessible account ID/catalog page. Protected catalog access proves reachability, never actor/tenant ownership. No token creation/exchange/refresh. Entitlement and permissions remain unknown."})
    credential_type: Literal["scalr_token"] = Field("scalr_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing Personal or Service-account Token", json_schema_extra={"ui:widget": "password"})
    tenant_host: str = Field(..., title="Canonical Tenant Host", description="One tenant.scalr.io label. No custom host, scheme, port or path.")
    account_id: str = Field(..., title="Independently Known Accessible Account ID")
    account_catalog_page: int = Field(1, ge=1, le=MAX_PAGE, title="Known Account Catalog Page", description="Page containing the known account; local bound. No automatic traversal or completion claim.")
    @field_validator("access_token", mode="before")
    @classmethod
    def secret(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply the raw token without a Bearer prefix")
        return clean_secret(value, field_name="Scalr token")
    @field_validator("tenant_host", mode="before")
    @classmethod
    def host(cls, value): return _host(value)
    @field_validator("account_id", mode="before")
    @classmethod
    def account(cls, value): return _id(value)
    @field_validator("account_catalog_page", mode="before")
    @classmethod
    def catalog_page(cls, value): return _page(value)


def _credential(raw):
    if isinstance(raw, ScalrTokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "scalr_token": raise ValueError("Select the actual Scalr issued token family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) - {"credential_type", "access_token", "tenant_host", "account_id", "account_catalog_page"}: raise ValueError("Unsupported token grant; no arbitrary host/expiry/refresh")
    try: return ScalrTokenCredential.model_validate(raw)
    except Exception: raise ValueError("Scalr token/tenant/account binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Scalr Metadata", "x-is-trigger": False})
def _selector(title, field, parents=()): return Field(..., title=title, json_schema_extra={"x-resource-type": field, "x-dynamic-options": {"field_name": field, "depends_on": list(parents), "allow_custom": True}})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Display Names", description="Names may contain private labels. Only account/environment/workspace names are supported; run messages are always omitted.")


class _Paged(_Config):
    page: int = Field(1, ge=1, le=MAX_PAGE, strict=True, title="Page Number", description="Explicit bounded page; no returned link is followed.")
    page_size: int = Field(20, ge=1, le=MAX_PAGE_SIZE, strict=True, title="Page Size", description="Local maximum 100; not a vendor maximum. Total/continuation/completion stay unknown.")


class _Account(_Config):
    account_id: str = _selector("Current Credential-bound Account", "account_id")
    @field_validator("account_id", mode="before")
    @classmethod
    def validate_account(cls, value): return _id(value)


class _Environment(_Account):
    environment_id: str = _selector("Environment in Selected Account", "environment_id", ("account_id",))
    @field_validator("environment_id", mode="before")
    @classmethod
    def validate_environment(cls, value): return _id(value)


class _Workspace(_Environment):
    workspace_id: str = _selector("Workspace in Selected Environment", "workspace_id", ("account_id", "environment_id"))
    @field_validator("workspace_id", mode="before")
    @classmethod
    def validate_workspace(cls, value): return _id(value)


class ScalrAccountsConfig(_Paged):
    operation: Literal["list_accounts"] = _op("list_accounts", "Read Accessible Account Catalog")
class ScalrEnvironmentsConfig(_Account, _Paged):
    operation: Literal["list_environments"] = _op("list_environments", "Read Account Environments")
class ScalrEnvironmentConfig(_Environment):
    operation: Literal["get_environment"] = _op("get_environment", "Get Environment Metadata")
class ScalrWorkspacesConfig(_Environment, _Paged):
    operation: Literal["list_workspaces"] = _op("list_workspaces", "Read Environment Workspaces")
class ScalrWorkspaceConfig(_Workspace):
    operation: Literal["get_workspace"] = _op("get_workspace", "Get Workspace Metadata")
class ScalrRunsConfig(_Workspace, _Paged):
    operation: Literal["list_runs"] = _op("list_runs", "Read Workspace Run Status")
class ScalrRunConfig(_Workspace):
    operation: Literal["get_run"] = _op("get_run", "Get Run Status Metadata")
    run_id: str = _selector("Run in Selected Workspace", "run_id", ("account_id", "environment_id", "workspace_id"))
    @field_validator("run_id", mode="before")
    @classmethod
    def validate_run(cls, value): return _id(value)


ScalrOperation = Annotated[Union[ScalrAccountsConfig, ScalrEnvironmentsConfig, ScalrEnvironmentConfig, ScalrWorkspacesConfig, ScalrWorkspaceConfig, ScalrRunsConfig, ScalrRunConfig], Field(discriminator="operation")]
class ScalrNodeConfig(NodeConfig[ScalrOperation, ScalrTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _relationship(row, field, expected_type):
    data = _object(_object(_object(row.get("relationships")).get(field)).get("data"))
    if data.get("type") != expected_type: raise ValueError("JSON:API parent relationship type differs")
    return _id(data.get("id"))


def _resource(raw, kind, names=False):
    row = _object(raw)
    if row.get("type") != kind: raise ValueError("JSON:API resource type differs")
    out = {"id": _id(row.get("id")), "type": kind}
    attrs = _object(row.get("attributes", {}))
    for field in ATTRIBUTES[kind]:
        if field not in attrs: continue
        value = attrs[field]
        if value is None and field == "updated-at": out[field] = None; continue
        if field in {"locked", "has-changes", "is-destroy", "is-dry"}:
            if type(value) is not bool: raise ValueError("Unsupported metadata boolean")
        else:
            value = _text(value, 100)
            if field.endswith("-at"):
                date = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if date.tzinfo is None: raise ValueError("Expected a documented date-time with offset")
            if field == "iac-platform" and value not in {"terraform", "opentofu"}: raise ValueError("Unsupported IaC platform")
            if field == "status" and kind == "runs" and value not in RUN_STATES: raise ValueError("Unsupported documented run status")
        out[field] = value
    if kind == "environments": out["account_id"] = _relationship(row, "account", "accounts")
    elif kind == "workspaces": out["environment_id"] = _relationship(row, "environment", "environments")
    elif kind == "runs":
        # Official run examples omit environment; workspace still establishes it.
        if "environment" in _object(row.get("relationships")):
            out["environment_id"] = _relationship(row, "environment", "environments")
        out["workspace_id"] = _relationship(row, "workspace", "workspaces")
    if names and kind != "runs": out["name"] = _text(attrs.get("name"), 255)
    return out


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, action): self.raw, self.key, self.action, self.attempted, self.status = raw, _credential(raw), action, False, None
    def error(self, message): return {"status": "error", "action": self.action, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, kind, resource_id=None, *, filters=None, page=1, page_size=20, names=False):
        if kind not in ATTRIBUTES or type(names) is not bool: raise ValueError("Closed native resource route required")
        filters = filters or {}
        allowed = {"accounts": set(), "environments": {"account"}, "workspaces": {"account", "environment"}, "runs": {"account", "environment", "workspace"}}[kind]
        if set(filters) - allowed or (resource_id is not None and filters): raise ValueError("Closed native parent filters required")
        fields = list(ATTRIBUTES[kind]) + list(RELATIONSHIPS[kind])
        if names and kind != "runs": fields.append("name")
        params = {f"fields[{kind}]": ",".join(fields)}
        if resource_id is None:
            if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE: raise ValueError("Unsupported page size")
            params.update({"page[number]": str(_page(page)), "page[size]": str(page_size)})
            params.update({f"filter[{key}]": _id(value) for key, value in filters.items()})
        elif kind == "accounts": raise ValueError("Account detail route is not declared")
        elif kind == "environments": params["track_access"] = "false"
        path = f"https://{self.key.tenant_host}/api/iacp/v3/{kind}" + (f"/{_id(resource_id)}" if resource_id is not None else "")
        try:
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", path, params=params, headers={"Authorization": f"Bearer {key.access_token}", "Accept": "application/vnd.api+json"}) as response:
                    self.status = response.status_code; data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES: raise ValueError("Scalr response exceeds native bound")
                        data.extend(chunk)
            if self.status != 200:
                message = "Scalr HTTP401 documents missing/invalid token" if self.status == 401 else "Scalr HTTP404 is permission-or-resource ambiguous" if self.status == 404 else "Scalr protected read could not be verified; check access/entitlement"
                raise _ProviderError(self.error(message + ". Private provider text omitted; no retry occurred"))
            document = _object(json.loads(data))
            if "errors" in document: raise ValueError("JSON:API errors cannot establish protected metadata")
            payload = document.get("data")
            if resource_id is not None:
                result = _resource(payload, kind, names)
                if result["id"] != resource_id: raise ValueError("Selected ID differs from detail response")
                return result
            if not isinstance(payload, list) or len(payload) > page_size: raise ValueError("Unsupported bounded JSON:API data array")
            result = [_resource(row, kind, names) for row in payload]
            if len({row["id"] for row in result}) != len(result): raise ValueError("Duplicate resource IDs")
            return result
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("Scalr transport outcome is unknown; no retry occurred")) from None
    async def account(self):
        rows = await self.request("accounts", page=self.key.account_catalog_page, page_size=MAX_PAGE_SIZE)
        if self.key.account_id not in {row["id"] for row in rows}: raise ValueError("Known account not established in bounded protected catalog; empty is not identity")
    async def parents(self, config):
        await self.account()
        if hasattr(config, "account_id") and config.account_id != self.key.account_id: raise ValueError("Selected account differs from current credential binding")
        if hasattr(config, "environment_id"):
            env = await self.request("environments", config.environment_id)
            if env["account_id"] != self.key.account_id: raise ValueError("Environment is outside selected account")
        if hasattr(config, "workspace_id"):
            workspace = await self.request("workspaces", config.workspace_id)
            if workspace["environment_id"] != config.environment_id: raise ValueError("Workspace is outside selected environment")


class ScalrNode(WorkflowNode):
    integration_type = "automation-scalr"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="Scalr accessible account catalog", proves="reachability")
    edit_examples = ["Read metadata from my selected Scalr account", "Read workspace and run status without inputs or logs", "Get metadata in one known environment without tracking access"]
    @classmethod
    def get_config_model(cls): return ScalrNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            # Reject a caller's different bound account before any provider request.
            if hasattr(config, "account_id") and config.account_id != session.key.account_id: raise ValueError("Selected account differs")
            await session.parents(config)
            kind = {"list_accounts": "accounts", "list_environments": "environments", "get_environment": "environments", "list_workspaces": "workspaces", "get_workspace": "workspaces", "list_runs": "runs", "get_run": "runs"}[config.operation]
            filters = {"account": session.key.account_id} if kind != "accounts" else {}
            if kind in {"workspaces", "runs"}: filters["environment"] = config.environment_id
            if kind == "runs": filters["workspace"] = config.workspace_id
            if config.operation.startswith("list_"):
                data = await session.request(kind, filters=filters, page=config.page, page_size=config.page_size, names=config.include_names)
                out = {"data": data, "page": config.page, "page_size": config.page_size, "returned_count": len(data), "total_count": None, "has_more": None, "next_page": None, "pagination_complete": None}
            else:
                selected = {"environments": "environment_id", "workspaces": "workspace_id", "runs": "run_id"}[kind]
                data = await session.request(kind, getattr(config, selected), names=config.include_names)
                out = {"data": data}
            for row in data if isinstance(data, list) else [data]:
                if kind == "environments" and row["account_id"] != session.key.account_id: raise ValueError("Environment response crosses account")
                if kind == "runs":
                    if row["workspace_id"] != config.workspace_id: raise ValueError("Run response crosses workspace")
                    row.setdefault("environment_id", config.environment_id)
                if kind in {"workspaces", "runs"} and row["environment_id"] != config.environment_id: raise ValueError("Response crosses environment")
            response_status = session.status
            await session.parents(config)
            if not isinstance(data, list) and kind in {"environments", "workspaces", "runs"}:
                current = await session.request(kind, data["id"])
                if kind == "runs" and current["workspace_id"] == config.workspace_id:
                    current.setdefault("environment_id", config.environment_id)
                for parent in ("account_id", "environment_id", "workspace_id"):
                    if parent in data and current.get(parent) != data[parent]: raise ValueError("Resource ancestry changed before output")
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains secret material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": response_status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "tenant_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current token/catalog/resource ancestry or bounded published response could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        credential = _credential(credential_data); context = context or {}
        names = context.get("include_names", False)
        if type(names) is not bool: raise ValueError("Explicit names opt-in required")
        if search is not None: _text(search, 100)
        page = (credential.account_catalog_page if field_name == "account_id" else 1) if page_token is None else _page(page_token)
        configs = {"account_id": ScalrAccountsConfig, "environment_id": ScalrEnvironmentsConfig, "workspace_id": ScalrWorkspacesConfig, "run_id": ScalrRunsConfig}
        if field_name not in configs: raise ValueError("Unsupported native picker")
        parents = {"account_id": (), "environment_id": ("account_id",), "workspace_id": ("account_id", "environment_id"), "run_id": ("account_id", "environment_id", "workspace_id")}[field_name]
        args = {parent: _id(context.get(parent)) for parent in parents}
        result = await cls._dispatch(credential_data, configs[field_name](**args, page=page, page_size=MAX_PAGE_SIZE, include_names=names))
        if result.get("status") != "success": raise ValueError(result["error"])
        rows = result["data"]
        if field_name == "account_id": rows = [row for row in rows if row["id"] == credential.account_id]
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"], "metadata": {"resource_type": row["type"], **{key: row[key] for key in ("account_id", "environment_id", "workspace_id") if key in row}}} for row in rows if not search or search.casefold() in (row.get("name") or row["id"]).casefold()], "has_more": None, "next_page_token": None, "pagination_complete": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, ScalrNodeConfig) or not self.config.credentials:
            raise ValueError("Scalr token credential is required")
        credential = _credential(self.config.credentials)
        return await self._dispatch(credential, self.config.config)
