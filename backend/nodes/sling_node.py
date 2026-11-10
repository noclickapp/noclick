"""Native Sling workforce metadata and bounded calendar reads.

The supplied user-bound token is a raw Authorization header. Public Swagger2
omits several response schemas; strict projections reject unknown envelopes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

TYPES = ("sling_user_token",)
ROOT = "https://api.getsling.com/v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_ID = 9223372036854775807
MAX_CATALOG = 1000
OPERATIONS = ("get_organization", "list_groups", "get_group", "list_users", "get_user", "list_group_users", "list_calendar_events")


def id_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > MAX_ID:
        raise ValueError("Use a positive decimal Sling ID, without a URL or path")
    return value


def provider_id(value):
    if type(value) is not int or not 1 <= value <= MAX_ID:
        raise ValueError("Sling returned an invalid integer ID")
    return str(value)


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Use an ISO 8601 timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError()
    except ValueError:
        raise ValueError("Use a valid ISO 8601 timestamp with a timezone") from None
    return value


RecordID = Annotated[str, BeforeValidator(id_value)]
Timestamp = Annotated[str, BeforeValidator(timestamp)]


class SlingUserTokenCredential(BaseModel):
    credential_type: Literal["sling_user_token"] = Field(TYPES[0], json_schema_extra={"ui:hidden": True})
    token: str = Field(..., min_length=1, max_length=6000, repr=False, title="Sling User Token", json_schema_extra={"ui:widget": "password"})
    organization_id: RecordID = Field(..., title="Sling Organization ID", description="The organization whose protected details you can read. This supplied ID is a resource parent, not proof of the token's current organization or principal identity.")
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://github.com/getsling/getsling-api-docs#authentication",
        "x-credential-instructions": "Supply an existing user-bound Sling token and organization ID. The header is Authorization: token, without Bearer. Access follows the issuing user's permissions. Console-session tokens stop working on logout. No login, session mutation, token minting or refresh is performed.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        return {"credential_type": TYPES[0], **value} if isinstance(value, dict) else value

    @field_validator("token", mode="before")
    @classmethod
    def token_value(cls, value):
        if not isinstance(value, str):
            raise ValueError("Supply the issued opaque Sling token")
        value = clean_secret(value)
        if not value or not value.isascii() or re.search(r"[\x00-\x20\x7f]", value) or value.lower() == "bearer" or value.lower().startswith("authorization:"):
            raise ValueError("Supply only the token without a header prefix or whitespace")
        return value


def credential_value(raw, *, manual=False):
    if isinstance(raw, SlingUserTokenCredential):
        raw = raw.model_dump()
    if manual and isinstance(raw, dict) and raw.get("credential_type") is None:
        raw = {**raw, "credential_type": TYPES[0]}
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPES[0]:
        raise ValueError("Connect a typed Sling user token")
    try:
        return SlingUserTokenCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply valid Sling token and organization fields") from None


def picker(field, depends=None):
    dynamic = {"field_name": field, "searchable": True, "allow_custom": True, "custom_placeholder": "Paste a decimal Sling ID"}
    if depends:
        dynamic["depends_on"] = depends
    return {"x-resource-type": "sling_" + field, "x-dynamic-options": dynamic}


def operation_field(value, name, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": name, "x-category": category})


def operation_meta(name, category):
    return ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-display-name": name, "x-category": category, "x-is-trigger": False, "x-operation-effect": "Read protected workforce metadata using the supplied user's permissions; no schedule or employee changes."})


class GetOrganization(BaseModel):
    operation: Literal["get_organization"] = operation_field("get_organization", "Get organization metadata", "Organization")
    model_config = operation_meta("Get organization metadata", "Organization")


class ListGroups(BaseModel):
    operation: Literal["list_groups"] = operation_field("list_groups", "List groups, locations and positions", "Workforce")
    group_type: Literal["location", "position"] | None = Field(None, title="Group Type", description="Optional documented /groups type filter. Leave unset for all current-token organization groups.")
    model_config = operation_meta("List groups, locations and positions", "Workforce")


class GroupParent(BaseModel):
    group_id: RecordID = Field(..., title="Group ID", json_schema_extra=picker("group_id"))


class GetGroup(GroupParent):
    operation: Literal["get_group"] = operation_field("get_group", "Get group metadata", "Workforce")
    model_config = operation_meta("Get group metadata", "Workforce")


class ListUsers(BaseModel):
    operation: Literal["list_users"] = operation_field("list_users", "List user metadata", "Workforce")
    model_config = operation_meta("List user metadata", "Workforce")


class GetUser(BaseModel):
    operation: Literal["get_user"] = operation_field("get_user", "Get user metadata", "Workforce")
    user_id: RecordID = Field(..., title="User ID", json_schema_extra=picker("user_id"))
    model_config = operation_meta("Get user metadata", "Workforce")


class ListGroupUsers(GroupParent):
    operation: Literal["list_group_users"] = operation_field("list_group_users", "List group member metadata", "Workforce")
    model_config = operation_meta("List group member metadata", "Workforce")


class ListCalendarEvents(BaseModel):
    operation: Literal["list_calendar_events"] = operation_field("list_calendar_events", "List calendar event metadata", "Calendar")
    user_id: RecordID = Field(..., title="Calendar User ID", description="A user in the token's current organization; selected organization is taken from the saved credential.", json_schema_extra=picker("user_id"))
    start: Timestamp = Field(..., title="Start Time")
    end: Timestamp = Field(..., title="End Time", description="Increasing ISO 8601 interval, at most eight weeks.")
    page_size: int = Field(50, strict=True, ge=1, le=100, title="Page Size", description="NoClick bounds one page to 100; the public specification does not define a provider maximum.")
    page_token: str | None = Field(None, max_length=128, title="Next Page Token", description="Use the returned continuation with unchanged credential, parent and interval. A full page only indicates a possible continuation.")
    model_config = operation_meta("List calendar event metadata", "Calendar")

    @model_validator(mode="after")
    def interval(self):
        start = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.end.replace("Z", "+00:00"))
        if not timedelta(0) < end - start <= timedelta(weeks=8):
            raise ValueError("Use an increasing calendar interval of at most eight weeks")
        return self


Operations = Annotated[Union[GetOrganization, ListGroups, GetGroup, ListUsers, GetUser, ListGroupUsers, ListCalendarEvents], Discriminator("operation")]


class SlingNodeConfig(NodeConfig):
    config: Operations = Field(default_factory=GetOrganization)
    credentials: Union[SlingUserTokenCredential, None] = None


SLING_SCOPES = ScopeRegistry("sling", {name: ScopeRequirement(credential_types=TYPES, note="The supplied token has the issuing user's actual Sling permissions; no grant or entitlement is inferred") for name in OPERATIONS})


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
        raise ValueError("Sling returned malformed or nonfinite JSON") from None


class SlingAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"Sling HTTP {status}: read not confirmed; no automatic retry" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


async def fetch(credential, operation, path, *, params=None):
    credential = credential_value(credential)
    SLING_SCOPES.enforce_credential_type(operation, credential.credential_type)
    paths = {"/organisations/" + credential.organization_id, "/groups", "/users"}
    child = re.fullmatch(r"/(?:groups/[1-9][0-9]{0,18}(?:/users)?|users/[1-9][0-9]{0,18})", path)
    calendar = re.fullmatch(r"/calendar/" + credential.organization_id + r"/users/[1-9][0-9]{0,18}", path)
    if path not in paths and not child and not calendar or allow_private_hosts():
        raise ValueError("Use native public Sling routes without arbitrary requests or private overrides")
    allowed = {"dates", "pageSize", "page", "skipUnscheduled", "showPlanningEvents"} if calendar else {"type"} if path == "/groups" else set()
    if params and set(params) - allowed:
        raise ValueError("Use only native Sling read filters")
    serialized = json.dumps(params, ensure_ascii=False, allow_nan=False)
    if credential.token in serialized:
        raise ValueError("Do not place token bytes in read filters")
    try:
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", ROOT + path, headers={"Authorization": credential.token, "Accept": "application/json", "User-Agent": "NoClick Sling native integration"}, params=params) as response:
                if response.status_code != 200:
                    retry = response.headers.get("retry-after", "")
                    raise SlingAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Sling response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Sling returned a non-JSON success response")
                raw = finite_json(bytes(content))
                if not isinstance(raw, (dict, list)) or isinstance(raw, dict) and ("error" in raw or "errors" in raw or raw.get("success") is False):
                    raise ValueError("Sling returned a failure or unsupported metadata envelope")
                return raw
    except SSRFError:
        raise ValueError("Sling destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Sling read could not be completed; no automatic retry") from None


def safe_text(value, credential):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 500 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Sling returned invalid metadata text")
    value = unicodedata.normalize("NFC", value)
    for secret in (credential.token, quote(credential.token, safe="")):
        value = value.replace(secret, "[redacted]")
    return re.sub(r"(?i)(?:api[_-]?key|authorization|password|access_token|token)\s*[=:]\s*[^\s&]+", "[redacted]", value)


def entity(raw, credential, kind, expected_id=None):
    if not isinstance(raw, dict):
        raise ValueError("Sling returned unsupported entity metadata")
    identity = provider_id(raw.get("id"))
    if expected_id is not None and identity != expected_id:
        raise ValueError("Sling returned a different resource")
    data = {"id": identity}
    fields = ("name", "type", "timezone", "color") if kind == "group" else ("name", "lastname", "timezone") if kind == "user" else ("dtstart", "dtend")
    for field in fields:
        if field in raw:
            data[field] = safe_text(raw[field], credential)
    if kind == "user":
        for field in ("active", "deleted", "hiddenOnSchedule"):
            if field in raw:
                if type(raw[field]) is not bool:
                    raise ValueError("Sling returned invalid user state")
                data[field] = raw[field]
    if kind == "event":
        for field in ("dtstart", "dtend"):
            if data.get(field) is not None:
                timestamp(data[field])
        if data.get("dtstart") and data.get("dtend") and datetime.fromisoformat(data["dtend"].replace("Z", "+00:00")) < datetime.fromisoformat(data["dtstart"].replace("Z", "+00:00")):
            raise ValueError("Sling returned an inverted event interval")
    return data


def catalog(raw, credential, kind, *, limit=MAX_CATALOG):
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError("Sling returned an unsupported or oversized list; no partial result accepted")
    data = [entity(row, credential, kind) for row in raw]
    if len({row["id"] for row in data}) != len(data):
        raise ValueError("Sling returned duplicate resource IDs")
    return data


async def organization(credential, operation):
    raw = await fetch(credential, operation, "/organisations/" + credential.organization_id)
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
        raise ValueError("Sling omitted protected organization metadata")
    # The Swagger2 Org definition does not document a response ID. The requested
    # parent is explicit; it is never substituted for a verified provider identity.
    if "id" in raw and provider_id(raw["id"]) != credential.organization_id:
        raise ValueError("Sling returned a different organization")
    return {"requested_organization_id": credential.organization_id, **{field: safe_text(raw[field], credential) for field in ("name", "businessCategory", "customIndustry") if field in raw}}


async def current_catalog(credential, operation, kind, params=None):
    return catalog(await fetch(credential, operation, "/groups" if kind == "group" else "/users", params=params), credential, kind)


async def member(credential, operation, kind, identity):
    rows = await current_catalog(credential, operation, kind)
    if not any(row["id"] == identity for row in rows):
        raise ValueError("Selected resource is absent from the token's current organization catalog")


def page_binding(credential, config):
    return hashlib.sha256(json.dumps([credential.model_dump(), config.model_dump(exclude={"page_token"})], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:32] + ":"


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    operation = config.operation
    org = await organization(credential, operation)
    if isinstance(config, GetOrganization):
        return {"data": org, "principal_identity_verified": False}
    if isinstance(config, ListGroups):
        rows = await current_catalog(credential, operation, "group", {"type": config.group_type} if config.group_type else None)
        if config.group_type and any(row.get("type") != config.group_type for row in rows):
            raise ValueError("Sling returned a group outside the requested type")
        return {"data": {"items": rows, "scope": "token_current_organization", "next_page_token": None}}
    if isinstance(config, ListUsers):
        return {"data": {"items": await current_catalog(credential, operation, "user"), "scope": "token_current_organization", "next_page_token": None}}
    if isinstance(config, (GetGroup, ListGroupUsers)):
        await member(credential, operation, "group", config.group_id)
        raw = await fetch(credential, operation, "/groups/" + config.group_id)
        group = entity(raw, credential, "group", config.group_id)
        if isinstance(config, GetGroup):
            return {"data": group}
        rows = catalog(await fetch(credential, operation, "/groups/" + config.group_id + "/users"), credential, "user")
        current = await current_catalog(credential, operation, "user")
        if not {row["id"] for row in rows} <= {row["id"] for row in current}:
            raise ValueError("Sling group members are outside the current organization catalog")
        return {"data": {"group_id": config.group_id, "items": rows, "next_page_token": None}}
    await member(credential, operation, "user", config.user_id)
    if isinstance(config, GetUser):
        return {"data": entity(await fetch(credential, operation, "/users/" + config.user_id), credential, "user", config.user_id)}
    if isinstance(config, ListCalendarEvents):
        prefix, page = page_binding(credential, config), 0
        if config.page_token is not None:
            suffix = config.page_token[len(prefix):] if config.page_token.startswith(prefix) else ""
            if not re.fullmatch(r"[1-9][0-9]{0,5}", suffix):
                raise ValueError("Continuation changed credential, parent, interval or page size")
            page = int(suffix)
        params = {"dates": config.start + "/" + config.end, "pageSize": config.page_size, "page": page, "skipUnscheduled": "true", "showPlanningEvents": "false"}
        rows = catalog(await fetch(credential, operation, "/calendar/" + credential.organization_id + "/users/" + config.user_id, params=params), credential, "event", limit=config.page_size)
        # The specification defines an offset as pageSize * page, but no total
        # or next-link response fields. A full page is only a possible next page.
        possible = len(rows) == config.page_size
        if possible and page == 999999:
            raise ValueError("Sling calendar paging reached the native bound")
        return {"data": {"organization_id": credential.organization_id, "user_id": config.user_id, "items": rows, "page": page, "page_size": config.page_size, "has_more": None if possible else False, "next_page_token": prefix + str(page + 1) if possible else None}}
    raise ValueError("Use a native Sling metadata read")


class SlingNode(WorkflowNode):
    integration_type = "automation-sling"
    credential_provider_labels = {"sling": "Sling Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    scope_registry = SLING_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_organization", noun="Sling organization metadata", proves="reachability", label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return SlingNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use native Sling configuration")
        credential_value(raw.get("credentials"))
        for key in ("group_id", "user_id"):
            if key in raw["config"]:
                id_value(raw["config"][key])
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "token", "organization_id", "credentials", "password", "session", "capabilities", "includeTimesheets", "user-fields", "field_scopes", "field_dependencies"}
        if (controls - {"credentials"}).intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed read fields without request, credential or organization overrides")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native Sling fields and a typed credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_id:
            if not user_id:
                raise ValueError("Stored Sling credential requires an authorized caller")
            from utils.database_pool import get_native_pool
            from wss.handlers.workflow_handler import get_user_org_context
            from repositories.credentials import CredentialsRepo
            from utils.credentials import resolve_credential_with_owner_fallback
            pool = pool if pool is not None else get_native_pool()
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
            repo = CredentialsRepo(pool)
            row = await repo.fetch_with_access(credential_id, user_id, organization_id)
            if row is None or row.credential_type not in TYPES:
                raise ValueError("Current Sling authority is unavailable or has a different family")
            credential_data = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id)
            if not credential_data or credential_data.get("credential_type") != row.credential_type:
                raise ValueError("Sling credential unavailable, revoked or access denied")
            if await repo.fetch_with_access(credential_id, user_id, organization_id) != row:
                raise ValueError("Sling authority changed during resolution; reconnect and retry deliberately")
        return credential_value(credential_data, manual=not credential_id).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential_value(credential_data)
        except ValueError:
            return {"valid": False, "error": "Connect a typed Sling user token"}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"group_id", "user_id"}:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        if page_token is not None:
            raise ValueError("Sling group and user catalogs have no documented pagination")
        if context is not None and not isinstance(context, dict):
            raise ValueError("Use native Sling picker context")
        context = context or {}
        if any(key.startswith("_") and key != "_user_id" or key in {"token", "organization_id", "credentials", "credential_type", "field_scopes", "field_dependencies", "url", "headers"} for key in context):
            raise ValueError("Use the saved Sling token and resource scope")
        if search is not None and (not isinstance(search, str) or len(search) > 200 or re.search(r"[\x00-\x1f\x7f]", search)):
            raise ValueError("Use bounded picker search text")
        await organization(credential, "list_groups" if field_name == "group_id" else "list_users")
        kind = "group" if field_name == "group_id" else "user"
        rows = await current_catalog(credential, "list_groups" if kind == "group" else "list_users", kind)
        options = [{"value": row["id"], "label": row.get("name") or ("Group " if kind == "group" else "User ") + row["id"], "metadata": {"id": row["id"], "scope": "token_current_organization"}} for row in rows]
        return {"options": filter_options_by_search(options, normalize_search(search)), "next_page_token": None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, SlingNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Sling credential")
        self._require_raw(self.node_data or self.config.model_dump())
        credential = await self.freshen_credential(self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"))
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
