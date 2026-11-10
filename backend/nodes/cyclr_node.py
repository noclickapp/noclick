"""Native Cyclr account, cycle, template, catalog and step metadata reads.

Only supplied console API OAuth tokens are accepted. Account headers come from
the current saved credential; actions, runtime data and capability URLs are excluded.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

TYPES = ("cyclr_oauth_token",)
ROOTS = {"us": "https://api.cyclr.com", "us2": "https://api.us2.cyclr.com", "uk": "https://api.cyclr.uk", "eu": "https://api.eu.cyclr.com"}
MAX_BYTES = 2 * 1024 * 1024
CURRENT_ORGANIZATION = object()
OPERATIONS = ("get_account", "list_accounts", "list_cycles", "get_cycle", "list_cycle_steps", "get_cycle_step", "list_templates", "get_template", "list_connector_catalog")
CYCLR_SCOPES = ScopeRegistry("cyclr", {name: ScopeRequirement(credential_types=TYPES, note="Requires the supplied console OAuth token's actual API permissions; account-level DataOnDemand/MCP/webhook grants are not equivalent") for name in OPERATIONS})
STATUSES = {"Stopped", "Active", "Launching", "Finish", "DeleteScheduled", "DeleteFailed"}
RELEASES = {"Unknown", "Draft", "Live", "Deprecated"}
ACTIONS = {"None", "Action", "Webhook", "Decision", "Delay", "WaitUntil", "WaitAll", "WebhookResponse", "Annotation", "Switch", "McpRequest", "McpResponse"}


def account_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Use the Cyclr Account API ID, without a URL, path or whitespace")
    return value


def uuid_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("Use a canonical Cyclr resource UUID")
    result = str(UUID(value))
    if UUID(result).int == 0:
        raise ValueError("Use a nonzero Cyclr resource UUID")
    return result


AccountID = Annotated[str, BeforeValidator(account_id)]
ResourceID = Annotated[str, BeforeValidator(uuid_value)]


class CyclrOAuthTokenCredential(BaseModel):
    credential_type: Literal["cyclr_oauth_token"] = Field(TYPES[0], json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=6000, repr=False, title="Console OAuth Access Token", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "us2", "uk", "eu"] = Field("us", title="Cyclr Region", description="Use the region of the console that issued this token. Private-instance URLs are not accepted.")
    account_id: AccountID = Field(..., title="Selected Account API ID", description="A partner-accessible AccountResponseModel.Id; this saved value supplies X-Cyclr-Account. It is not a user or principal identity.")
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://community.cyclr.com/user-documentation/api/introduction-to-the-cyclr-api",
        "x-credential-instructions": "Supply an already issued private console-level Cyclr API OAuth Bearer token, its region and selected account API ID. No exchange, client-secret storage, refresh or token minting occurs. Account-level DataOnDemand, MCP and webhook tokens are distinct and not substitutes for console API grants. Actual expiry/permissions remain Cyclr authority.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        return {"credential_type": TYPES[0], **value} if isinstance(value, dict) else value

    @field_validator("access_token", mode="before")
    @classmethod
    def token_value(cls, value):
        if not isinstance(value, str):
            raise ValueError("Supply only the issued opaque OAuth token")
        value = clean_secret(value)
        if not value or not value.isascii() or re.search(r"[\x00-\x20\x7f]", value) or value.lower().startswith("authorization:"):
            raise ValueError("Supply only the token without a header prefix or whitespace")
        return value


def credential_value(raw, *, manual=False):
    if isinstance(raw, CyclrOAuthTokenCredential):
        raw = raw.model_dump()
    if manual and isinstance(raw, dict) and raw.get("credential_type") is None:
        raw = {**raw, "credential_type": TYPES[0]}
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPES[0]:
        raise ValueError("Connect a typed Cyclr console OAuth token")
    try:
        return CyclrOAuthTokenCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply valid Cyclr token, region and selected-account fields") from None


class _CurrentCredential(dict):
    """Server-only authority accompanies picker data without adding JSON fields.

    Normal JSON credentials cannot create this carrier. Serialization keeps only
    public credential fields; execute resolves its own fresh server authority.
    """
    def __init__(self, fields, check):
        super().__init__(fields)
        self._fields = dict(fields)
        self._check = check

    async def check(self):
        if credential_value(self).model_dump() != self._fields:
            raise ValueError("Cyclr credential fields changed after current-row resolution")
        await self._check()


async def check_current(raw):
    if isinstance(raw, _CurrentCredential):
        await raw.check()


def picker(field, depends=None):
    dynamic = {"field_name": field, "searchable": True, "allow_custom": True, "custom_placeholder": "Paste a Cyclr resource UUID"}
    if depends:
        dynamic["depends_on"] = depends
    return {"x-resource-type": "cyclr_" + field, "x-dynamic-options": dynamic}


def operation_field(value, name, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": name, "x-category": category})


def operation_meta(name, category):
    return ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-display-name": name, "x-category": category, "x-is-trigger": False, "x-operation-effect": "Read metadata using the selected account and actual console token permissions; no cycle or connector execution."})


class Names(BaseModel):
    include_names: bool = Field(False, strict=True, title="Include Resource Names", description="Optional account/workflow names may contain customer information. Default output is IDs and closed status metadata.")


class Page(Names):
    page_size: int = Field(10, strict=True, ge=1, le=100, title="Page Size", description="One page; NoClick bound100, not a claimed provider maximum.")
    page_token: str | None = Field(None, max_length=128, title="Next Page Token", description="A full page is only a possible continuation. Keep the token, account, region and fields unchanged.")


class GetAccount(Names):
    operation: Literal["get_account"] = operation_field("get_account", "Get selected account metadata", "Accounts")
    model_config = operation_meta("Get selected account metadata", "Accounts")


class ListAccounts(Page):
    operation: Literal["list_accounts"] = operation_field("list_accounts", "List partner account metadata", "Accounts")
    model_config = operation_meta("List partner account metadata", "Accounts")


class ListCycles(Page):
    operation: Literal["list_cycles"] = operation_field("list_cycles", "List cycle metadata", "Cycles")
    model_config = operation_meta("List cycle metadata", "Cycles")


class CycleParent(Names):
    cycle_id: ResourceID = Field(..., title="Cycle ID", json_schema_extra=picker("cycle_id"))


class GetCycle(CycleParent):
    operation: Literal["get_cycle"] = operation_field("get_cycle", "Get cycle metadata", "Cycles")
    model_config = operation_meta("Get cycle metadata", "Cycles")


class ListCycleSteps(CycleParent):
    operation: Literal["list_cycle_steps"] = operation_field("list_cycle_steps", "List cycle step metadata", "Steps")
    model_config = operation_meta("List cycle step metadata", "Steps")


class GetCycleStep(CycleParent):
    operation: Literal["get_cycle_step"] = operation_field("get_cycle_step", "Get cycle step metadata", "Steps")
    step_id: ResourceID = Field(..., title="Step ID", json_schema_extra=picker("step_id", "cycle_id"))
    model_config = operation_meta("Get cycle step metadata", "Steps")


class ListTemplates(Page):
    operation: Literal["list_templates"] = operation_field("list_templates", "List template metadata", "Templates")
    model_config = operation_meta("List template metadata", "Templates")


class GetTemplate(Names):
    operation: Literal["get_template"] = operation_field("get_template", "Get template metadata", "Templates")
    template_id: ResourceID = Field(..., title="Template ID", json_schema_extra=picker("template_id"))
    model_config = operation_meta("Get template metadata", "Templates")


class ListConnectorCatalog(Page):
    operation: Literal["list_connector_catalog"] = operation_field("list_connector_catalog", "List connector catalog metadata", "Catalog")
    model_config = operation_meta("List connector catalog metadata", "Catalog")


Operations = Annotated[Union[GetAccount, ListAccounts, ListCycles, GetCycle, ListCycleSteps, GetCycleStep, ListTemplates, GetTemplate, ListConnectorCatalog], Discriminator("operation")]


class CyclrNodeConfig(NodeConfig):
    config: Operations = Field(default_factory=GetAccount)
    credentials: Union[CyclrOAuthTokenCredential, None] = None


def finite_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def decimal(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_float=decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Cyclr returned malformed or nonfinite JSON") from None


class CyclrAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"Cyclr HTTP {status}: metadata read unconfirmed; no automatic retry" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


async def fetch(raw_credential, operation, path, *, params=None):
    await check_current(raw_credential)
    credential = credential_value(raw_credential)
    CYCLR_SCOPES.enforce_credential_type(operation, credential.credential_type)
    account_path = "/v1.0/accounts/" + quote(credential.account_id, safe="")
    cycles = re.fullmatch(r"/v1\.0/Cycles/[0-9a-f-]{36}(?:/steps(?:/[0-9a-f-]{36})?)?", path)
    templates = re.fullmatch(r"/v1\.0/Templates/[0-9a-f-]{36}", path)
    if path not in {account_path, "/v1.0/accounts", "/v1.0/Cycles", "/v1.0/Templates", "/v1.0/connectors"} and not cycles and not templates or allow_private_hosts():
        raise ValueError("Use closed native public Cyclr metadata routes")
    paged = path in {"/v1.0/accounts", "/v1.0/Cycles", "/v1.0/Templates", "/v1.0/connectors"}
    allowed = {"page", "pageSize", "sortOrderAsc"} if paged else set()
    if path.startswith("/v1.0/Cycles") and not "/steps" in path:
        allowed |= {"includeIcons", "includePrerequisites", "countAllIncidents"}
        if paged:
            allowed.add("orderBy")
    if path.startswith("/v1.0/Templates"):
        allowed |= {"includeIcons", "includePrerequisites", "includeOptional", "lookupCustomFields"}
        if paged:
            allowed.add("orderBy")
    if path == "/v1.0/connectors":
        allowed |= {"orderBy", "includeCustomConnectors"}
    if params and set(params) - allowed:
        raise ValueError("Use only native Cyclr metadata query fields")
    if credential.access_token in json.dumps(params, ensure_ascii=False, allow_nan=False):
        raise ValueError("Do not put token bytes in metadata filters")
    headers = {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json", "User-Agent": "NoClick Cyclr native integration"}
    if not path.startswith("/v1.0/accounts"):
        headers["X-Cyclr-Account"] = credential.account_id
    try:
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", ROOTS[credential.region] + path, headers=headers, params=params) as response:
                if response.status_code != 200:
                    retry = response.headers.get("retry-after", "")
                    raise CyclrAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Cyclr response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"application/json", "text/json"}:
                    raise ValueError("Cyclr returned a non-JSON success response")
                raw = finite_json(bytes(content))
                if not isinstance(raw, (dict, list)) or isinstance(raw, dict) and ("error" in raw or "errors" in raw or raw.get("success") is False):
                    raise ValueError("Cyclr returned a failure or invalid metadata envelope")
                return raw
    except SSRFError:
        raise ValueError("Cyclr destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Cyclr metadata read could not be completed; no automatic retry") from None
    finally:
        # Current authority takes precedence even when HTTP or JSON parsing fails.
        await check_current(raw_credential)


def safe_text(value, credential):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 500 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Cyclr returned invalid metadata text")
    value = unicodedata.normalize("NFC", value)
    for secret in (credential.access_token, "Bearer " + credential.access_token, quote(credential.access_token, safe="")):
        value = value.replace(secret, "[redacted]")
    return re.sub(r"(?i)(?:api[_-]?key|authorization|password|access_token|client_secret)\s*[=:]\s*[^\s&]+", "[redacted]", value)


def project(raw, credential, kind, *, include_names=False, expected_id=None):
    if not isinstance(raw, dict):
        raise ValueError("Cyclr returned invalid resource metadata")
    if kind == "account":
        identity = account_id(raw.get("Id"))
    elif kind == "connector":
        value = raw.get("Id")
        if type(value) is not int or not 1 <= value <= 2147483647:
            raise ValueError("Cyclr returned an invalid connector ID")
        identity = str(value)
    else:
        identity = uuid_value(raw.get("Id"))
    if expected_id is not None and identity != expected_id:
        raise ValueError("Cyclr returned a resource outside the selected parent")
    data = {"id": identity}
    if include_names and "Name" in raw:
        data["name"] = safe_text(raw["Name"], credential)
    timestamp_fields = {"account": ("CreatedDate",), "cycle": ("CreatedOnUtc", "LastSuccessfulRunDate", "NextRunDate"), "step": ("LastSuccessfulRunDate",)}.get(kind, ())
    for field in timestamp_fields:
        if field in raw:
            value = safe_text(raw[field], credential)
            if value is not None:
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("Cyclr returned an invalid metadata timestamp") from None
            data[field] = value
    if kind == "account" and "Timezone" in raw:
        data["Timezone"] = safe_text(raw["Timezone"], credential)
    enums = {"cycle": ("Status", STATUSES), "template": ("ReleaseStatus", RELEASES), "step": ("ActionType", ACTIONS)}
    if kind in enums:
        field, values = enums[kind]
        if field in raw:
            if not isinstance(raw[field], str) or raw[field] not in values:
                raise ValueError("Cyclr returned an unknown resource status/type")
            data[field] = raw[field]
    if kind == "connector":
        for field in ("Version", "ReleaseVersion"):
            if field in raw:
                data[field] = safe_text(raw[field], credential)
        if "IsSystemConnector" in raw:
            if type(raw["IsSystemConnector"]) is not bool:
                raise ValueError("Cyclr returned invalid catalog metadata")
            data["IsSystemConnector"] = raw["IsSystemConnector"]
    return data


def rows_value(raw, credential, kind, *, limit, include_names=False):
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError("Cyclr returned an invalid or oversized metadata array; no partial result accepted")
    rows = [project(row, credential, kind, include_names=include_names) for row in raw]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Cyclr returned duplicate resource IDs")
    return rows


def page_binding(credential, config):
    return hashlib.sha256(json.dumps([credential.model_dump(), config.model_dump(exclude={"page_token"})], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:32] + ":"


def cycle_params():
    return {"includeIcons": "false", "includePrerequisites": "false", "countAllIncidents": "false"}


def template_params():
    return {"includeIcons": "false", "includePrerequisites": "false", "includeOptional": "false", "lookupCustomFields": "false"}


async def get_bound_account(raw_credential, operation, *, include_names=False):
    credential = credential_value(raw_credential)
    raw = await fetch(raw_credential, operation, "/v1.0/accounts/" + quote(credential.account_id, safe=""))
    return project(raw, credential, "account", include_names=include_names, expected_id=credential.account_id)


async def get_bound_cycle(raw_credential, operation, identity, *, include_names=False):
    credential = credential_value(raw_credential)
    return project(await fetch(raw_credential, operation, "/v1.0/Cycles/" + identity, params=cycle_params()), credential, "cycle", include_names=include_names, expected_id=identity)


async def paged(raw_credential, config):
    credential = credential_value(raw_credential)
    prefix, page = page_binding(credential, config), 1
    if config.page_token is not None:
        suffix = config.page_token[len(prefix):] if config.page_token.startswith(prefix) else ""
        if not re.fullmatch(r"[1-9][0-9]{0,5}", suffix) or int(suffix) < 2:
            raise ValueError("Continuation changed token, selected account, region or fields")
        page = int(suffix)
    path, kind = {"list_accounts": ("/v1.0/accounts", "account"), "list_cycles": ("/v1.0/Cycles", "cycle"), "list_templates": ("/v1.0/Templates", "template"), "list_connector_catalog": ("/v1.0/connectors", "connector")}[config.operation]
    params = {"pageSize": config.page_size, "page": page, "sortOrderAsc": "true"}
    if kind == "cycle":
        params.update(cycle_params(), orderBy="UpdatedOnUtc")
    elif kind == "template":
        params.update(template_params(), orderBy="Name")
    elif kind == "connector":
        params.update(orderBy="Name", includeCustomConnectors="false")
    rows = rows_value(await fetch(raw_credential, config.operation, path, params=params), credential, kind, limit=config.page_size, include_names=config.include_names)
    possible = len(rows) == config.page_size
    if possible and page == 999999:
        raise ValueError("Cyclr metadata paging reached the native bound")
    return {"items": rows, "page": page, "page_size": config.page_size, "has_more": None if possible else False, "next_page_token": prefix + str(page + 1) if possible else None}


async def request_operation(raw_credential, config):
    try:
        await check_current(raw_credential)
        credential = credential_value(raw_credential)
        account = await get_bound_account(raw_credential, config.operation, include_names=config.include_names)
        if isinstance(config, GetAccount):
            return {"data": account, "principal_identity_verified": False}
        if isinstance(config, Page):
            return {"data": {"selected_account_id": credential.account_id, **await paged(raw_credential, config)}}
        if isinstance(config, GetTemplate):
            data = project(await fetch(raw_credential, config.operation, "/v1.0/Templates/" + config.template_id, params=template_params()), credential, "template", include_names=config.include_names, expected_id=config.template_id)
            return {"data": {"selected_account_id": credential.account_id, **data}}
        cycle = await get_bound_cycle(raw_credential, config.operation, config.cycle_id, include_names=config.include_names)
        if isinstance(config, GetCycle):
            return {"data": {"selected_account_id": credential.account_id, **cycle}}
        path = "/v1.0/Cycles/" + config.cycle_id + "/steps"
        steps = rows_value(await fetch(raw_credential, config.operation, path), credential, "step", limit=1000, include_names=config.include_names)
        if isinstance(config, ListCycleSteps):
            return {"data": {"selected_account_id": credential.account_id, "cycle_id": config.cycle_id, "items": steps, "next_page_token": None}}
        if isinstance(config, GetCycleStep):
            if not any(step["id"] == config.step_id for step in steps):
                raise ValueError("Selected step does not belong to the selected account/cycle")
            data = project(await fetch(raw_credential, config.operation, path + "/" + config.step_id), credential, "step", include_names=config.include_names, expected_id=config.step_id)
            return {"data": {"selected_account_id": credential.account_id, "cycle_id": config.cycle_id, **data}}
        raise ValueError("Use a native Cyclr metadata operation")
    finally:
        # Also recheck after projection or parent-binding refusals, not just HTTP.
        await check_current(raw_credential)


class CyclrNode(WorkflowNode):
    integration_type = "automation-cyclr"
    credential_provider_labels = {"cyclr": "Cyclr Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    scope_registry = CYCLR_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_account", noun="Cyclr selected account metadata", proves="reachability", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return CyclrNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use native Cyclr configuration")
        credential_value(raw.get("credentials"))
        for key in ("cycle_id", "step_id", "template_id"):
            if key in raw["config"]:
                uuid_value(raw["config"][key])
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "access_token", "account_id", "region", "credential_type", "credentials", "connectorAuthValue", "settings", "parameters", "webhook", "field_scopes", "field_dependencies"}
        if (controls - {"credentials"}).intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed metadata fields without credential, route or account overrides")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native Cyclr metadata fields and a typed credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._resolve_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )

    @classmethod
    async def _resolve_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=CURRENT_ORGANIZATION):
        if not credential_id:
            return credential_value(credential_data, manual=True).model_dump()
        if not user_id:
            raise ValueError("Stored Cyclr credential requires an authorized caller")
        from utils.database_pool import get_native_pool
        from wss.handlers.workflow_handler import get_user_org_context
        from repositories.credentials import CredentialsRepo
        from utils.credentials import resolve_credential_with_owner_fallback, get_workflow_owner_id, is_credential_authorized_for_workflow
        pool = pool if pool is not None else get_native_pool()
        async with pool.acquire() as conn:
            current_org = await get_user_org_context(conn, user_id)
        if organization_id is CURRENT_ORGANIZATION:
            organization_id = current_org
        elif organization_id != current_org:
            raise ValueError("Cyclr caller organization changed; access must be revalidated")
        authority_user = user_id
        repo = CredentialsRepo(pool)
        row = await repo.fetch_with_access(credential_id, authority_user, organization_id)
        fallback_owner = None
        if row is None and workflow_id:
            owner = await get_workflow_owner_id(pool, workflow_id)
            if owner and owner != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
                authority_user = fallback_owner = owner
                row = await repo.fetch_with_access(credential_id, authority_user, organization_id)
        if row is None or row.credential_type not in TYPES:
            raise ValueError("Current Cyclr authority is unavailable or has a different family")
        current = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
        if not current or current.get("credential_type") != row.credential_type:
            raise ValueError("Cyclr credential unavailable, revoked or access denied")
        fields = credential_value(current).model_dump()
        async def check():
            async with pool.acquire() as conn:
                if await get_user_org_context(conn, user_id) != organization_id:
                    raise ValueError("Cyclr caller organization changed during metadata read")
            if fallback_owner and (await get_workflow_owner_id(pool, workflow_id) != fallback_owner or not await is_credential_authorized_for_workflow(pool, workflow_id, credential_id)):
                raise ValueError("Cyclr workflow owner authorization changed during metadata read")
            if await repo.fetch_with_access(credential_id, authority_user, organization_id) != row:
                raise ValueError("Cyclr authority changed during resolution or metadata read")
            latest = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
            if not latest or credential_value(latest).model_dump() != fields:
                raise ValueError("Cyclr authority changed during resolution or metadata read")
        await check()
        return _CurrentCredential(fields, check)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential_value(credential_data)
        except ValueError:
            return {"valid": False, "error": "Connect a typed Cyclr console OAuth token"}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"cycle_id", "step_id", "template_id"}:
            return {"options": [], "next_page_token": None}
        if context is not None and not isinstance(context, dict):
            raise ValueError("Use native Cyclr picker context")
        context = context or {}
        if any(key.startswith("_") and key not in {"_user_id", "_workflow_id"} or key in {"access_token", "account_id", "region", "credentials", "credential_type", "field_scopes", "field_dependencies", "url", "headers"} for key in context):
            raise ValueError("Use the saved Cyclr region/account/token scope")
        if search is not None and (not isinstance(search, str) or len(search) > 200 or re.search(r"[\x00-\x1f\x7f]", search)):
            raise ValueError("Use bounded picker search text")
        raw = credential_data if isinstance(credential_data, _CurrentCredential) else credential_value(credential_data, manual=True).model_dump()
        if field_name == "step_id":
            if page_token is not None:
                raise ValueError("Cyclr step metadata has no documented pagination")
            config = ListCycleSteps(cycle_id=uuid_value(context.get("cycle_id")))
        else:
            config = (ListCycles if field_name == "cycle_id" else ListTemplates)(page_size=50, page_token=page_token)
        data = (await request_operation(raw, config))["data"]
        options = [{"value": row["id"], "label": ("Step " if field_name == "step_id" else "Cycle " if field_name == "cycle_id" else "Template ") + row["id"], "metadata": {"account_id": credential_value(raw).account_id, **({"cycle_id": config.cycle_id} if field_name == "step_id" else {})}} for row in data["items"]]
        return {"options": filter_options_by_search(options, normalize_search(search)), "next_page_token": data["next_page_token"]}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, CyclrNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Cyclr console credential")
        # Direct callers can supply the validated model without duplicating it
        # in node_data; saved raw configurations still receive the same guards.
        self._require_raw(self.node_data or self.config.model_dump())
        credential = await self._resolve_current_credential(self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"), workflow_id=self.workflow_id, organization_id=self.organization_id)
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
