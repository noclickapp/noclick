"""Native Sematext Cloud app and alert-rule metadata reads.

Account API keys stay in headers at one explicitly selected official region.
Saved app restrictions and current authority are retained across native seams.
"""
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.sematext_authority import SematextCredentialsRepo
from utils.ssrf import guarded_async_client

FAMILY = "sematext_account_api_key"
NODE_TYPE = "automation-sematext"
ROOTS = {"US": "https://apps.sematext.com", "EU": "https://apps.eu.sematext.com"}
BASE = "/users-web/api/v3"
OPS = ("check_connection", "list_apps", "get_app", "list_app_types", "list_alert_rules")
INT64_MAX = 2**63 - 1


def app_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > INT64_MAX:
        raise ValueError("Enter a positive Sematext app ID without a URL or whitespace")
    return value


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = item
        return result
    def constant(_): raise ValueError("Nonfinite JSON value")
    try: return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError): raise ValueError("Use valid bounded JSON") from None


def approved_apps(value):
    if not isinstance(value, str) or len(value) > 5000: raise ValueError("Enter approved app IDs as a JSON string array")
    raw = strict_json(value)
    if not isinstance(raw, list) or len(raw) > 50: raise ValueError("Approve at most 50 existing app IDs")
    ids = [app_id(item) for item in raw]
    if len(set(ids)) != len(ids): raise ValueError("Approve distinct app IDs")
    return ids


class SematextAccountAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Sematext Account API Key",
        json_schema_extra={"x-credential-instructions": "Enter an existing account API key, its US or EU region, and approved existing app IDs. This is distinct from an app ingestion/read/write token. Protected catalog access does not identify a principal or prove account ownership.", "x-help-url": "https://sematext.com/docs/api/"})
    credential_type: Literal["sematext_account_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Account API Key", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    region: Literal["US", "EU"] = Field("US", title="Account Region", description="Use the region in which the key and apps already exist. No cross-region fallback is performed.")
    approved_app_ids_json: str = Field("[]", title="Approved App IDs", description="JSON string array of existing positive app IDs, at most 50. Example: [\"123\",\"456\"].", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    include_labels: bool = Field(False, strict=True, title="Include App and Rule Names", description="Opt in to names only. Messages, tokens, emails, integration configuration, queries, runbooks and all links are always omitted.")
    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Account API Key")
        if not value or len(value) > 4096 or value.lower().startswith(("apikey ", "bearer ", "token ")) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter the issued account API key without a header prefix or whitespace")
        return value
    @field_validator("approved_app_ids_json")
    @classmethod
    def apps(cls, value):
        approved_apps(value)
        return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect a native Sematext account API key")
    if any(key in data for key in ("app_token", "api_token", "api_secret", "readToken", "readWriteToken", "writeToken", "token", "access_token", "refresh_token", "password", "base_url", "host", "cookie", "client_id")):
        raise ValueError("Use only the native supplied Sematext account API-key form")
    try: return SematextAccountAPIKeyCredential.model_validate(data).model_dump()
    except ValueError: raise ValueError("Complete the native Sematext account key, region and approved-app form") from None


def dynamic():
    return {"x-resource-type": "sematext_app", "x-dynamic-options": {"field_name": "app_id", "searchable": True, "allow_custom": True}}


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class Limited(NativeModel):
    limit: int = Field(50, strict=True, ge=1, le=100, description="Local output bound, not an API page size. No pagination is documented for these routes; global completion remains unknown.")


class ListApps(Limited):
    operation: Literal["list_apps"] = "list_apps"


class AppSelection(NativeModel):
    app_id: str = Field(..., title="App", json_schema_extra=dynamic())
    @field_validator("app_id")
    @classmethod
    def selected(cls, value): return app_id(value)


class GetApp(AppSelection):
    operation: Literal["get_app"] = "get_app"


class ListAppTypes(Limited):
    operation: Literal["list_app_types"] = "list_app_types"


class ListAlertRules(AppSelection):
    operation: Literal["list_alert_rules"] = "list_alert_rules"
    limit: int = Field(50, strict=True, ge=1, le=100, description="Local output bound only. Alert rules are unpaged in the documented contract; global completion remains unknown.")


Operation = Annotated[Union[CheckConnection, ListApps, GetApp, ListAppTypes, ListAlertRules], Field(discriminator="operation")]


class SematextNodeConfig(NodeConfig[Operation, SematextAccountAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class App(Projection):
    id: int = Field(ge=1, le=INT64_MAX)
    appTypeId: Optional[int] = Field(None, ge=0, le=INT64_MAX)
    appType: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, max_length=200)
    displayStatus: Optional[str] = Field(None, max_length=200)
    registrationDate: Optional[int] = Field(None, ge=-(2**63), le=INT64_MAX)
    firstDataSavedDate: Optional[int] = Field(None, ge=-(2**63), le=INT64_MAX)
    lastDataReceivedDate: Optional[int] = Field(None, ge=-(2**63), le=INT64_MAX)
    lastDataSavedDate: Optional[int] = Field(None, ge=-(2**63), le=INT64_MAX)
    name: Optional[str] = Field(None, max_length=500, exclude=True)


class AlertRule(Projection):
    ruleKey: int = Field(ge=1, le=INT64_MAX)
    appId: int = Field(ge=1, le=INT64_MAX)
    enabled: bool
    ruleType: Optional[str] = Field(None, max_length=200)
    priority: Optional[Literal["INFO", "ERROR", "WARN", "CRITICAL"]] = None
    lastTriggered: Optional[int] = Field(None, ge=-(2**63), le=INT64_MAX)
    name: Optional[str] = Field(None, max_length=500, exclude=True)

@dataclass(frozen=True)
class Authority:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]
    organization_derived: bool
    row: object


class BoundCredential(dict):
    def __init__(self, shaped, authority, pool):
        super().__init__(shaped)
        self["_sematext_authority_required"] = True
        self.authority, self.pool = authority, pool


def require_row(row):
    if row is None or row.credential_type != FAMILY or row.revoked_at is not None:
        raise ValueError("Sematext Cloud saved credential is unavailable")
    try: UUID(row.owner_id)
    except (TypeError, ValueError, AttributeError): raise ValueError("Sematext Cloud saved owner is invalid") from None
    if (type(row.token_version) is not int or row.token_version < 1
            or type(row.approval_revision) is not int or row.approval_revision < 0
            or not isinstance(row.updated_at, datetime) or row.updated_at.tzinfo is None):
        raise ValueError("Sematext Cloud saved authority is invalid")


async def bind_current(data, *, pool, user_id, credential_id, organization_id, workflow_id, organization_derived=False, expected=None):
    initial = credential(data)
    selected = {}
    async def load(cid, principal, current_pool, org):
        from utils.encryption import get_encryption
        row = await SematextCredentialsRepo(current_pool).fetch_validation_authority(cid, principal, org)
        if row is None: return None
        require_row(row)
        authority = Authority(str(cid), str(user_id), str(principal), org, workflow_id, organization_derived, row)
        if expected is not None and authority != expected: raise ValueError("Sematext Cloud current authority changed; reload")
        try: raw = get_encryption().decrypt_credential(row.credential)
        except Exception: raise ValueError("Sematext Cloud saved credential could not be decrypted") from None
        now = credential({**raw, "credential_type": row.credential_type}) if isinstance(raw, dict) else None
        if now != initial: raise ValueError("Sematext Cloud saved token, resources or label restriction changed")
        selected["authority"] = authority
        return now
    # Staging exposes its principal policy helpers without a custom row-loader hook.
    from utils.credentials import (get_workflow_owner_id,
        is_credential_authorized_for_workflow, credential_lender)
    now = await load(credential_id, user_id, pool, organization_id)
    if now is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if (owner and owner != user_id and
                await is_credential_authorized_for_workflow(pool, workflow_id, credential_id)):
            now = await load(credential_id, owner, pool, organization_id)
        if now is None:
            lender = await credential_lender(pool, workflow_id, credential_id)
            if lender and lender != user_id:
                now = await load(credential_id, lender, pool, organization_id)
    if now is None or "authority" not in selected: raise ValueError("Sematext Cloud current access denied")
    return BoundCredential(now, selected["authority"], pool)


async def current_credential(data):
    now = credential(data)
    if not isinstance(data, BoundCredential):
        if "_sematext_authority_required" in data: raise ValueError("Sematext Cloud saved authority was lost; reload")
        return now
    old = data.authority
    if old.organization_derived:
        from wss.handlers.workflow_handler import get_user_org_context
        async with data.pool.acquire() as conn: org = await get_user_org_context(conn, old.caller_id)
        if org != old.organization_id: raise ValueError("Sematext Cloud current organization context changed; reload")
    await bind_current(data, pool=data.pool, user_id=old.caller_id, credential_id=old.credential_id,
        organization_id=old.organization_id, workflow_id=old.workflow_id, organization_derived=old.organization_derived, expected=old)
    return now


async def request(data, path, *, params=None):
    now = await current_credential(data)
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", ROOTS[now["region"]] + BASE + path, headers={"Authorization": "apiKey " + now["api_key"],
                "Accept": "application/json", "Content-Type": "application/json"}, params=params) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 403, 404, 422}: raise ValueError(f"Sematext Cloud refused the metadata read (HTTP {status})")
                if status != 200: raise RuntimeError(f"Sematext Cloud metadata read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise RuntimeError("Sematext Cloud returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("Sematext Cloud response exceeds the native metadata limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("Sematext Cloud metadata transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("Sematext Cloud returned invalid JSON") from None


def typed(model, raw):
    try: return model.model_validate(raw)
    except ValueError: raise RuntimeError("Sematext returned unverified metadata") from None


def envelope(raw, key):
    if not isinstance(raw, dict) or type(raw.get("success")) is not bool: raise RuntimeError("Sematext returned an unverified success envelope")
    if raw["success"] is not True: raise ValueError("Sematext refused the metadata read")
    if not isinstance(raw.get("data"), dict) or key not in raw["data"]: raise RuntimeError("Sematext returned an unverified named data envelope")
    return raw["data"][key]


def array(model, raw, key):
    items = envelope(raw, key)
    if not isinstance(items, list) or len(items) > 1000: raise RuntimeError("Sematext returned an unverified or oversized metadata array")
    rows = [typed(model, item) for item in items]
    ids = [row.id if isinstance(row, App) else row.ruleKey for row in rows]
    if len(set(ids)) != len(ids): raise RuntimeError("Sematext repeated a metadata resource ID")
    return rows


def output(row, now):
    result = row.model_dump(exclude_none=True)
    if now["include_labels"] and row.name is not None: result["name"] = row.name
    return result


def selected_app(now, value):
    value = app_id(value)
    if value not in approved_apps(now["approved_app_ids_json"]): raise ValueError("App is outside the saved Sematext approved-ID restriction")
    return value


async def app_witness(data, value):
    now = await current_credential(data)
    selected = selected_app(now, value)
    rows = array(App, await request(data, "/apps"), "apps")
    if int(selected) not in {row.id for row in rows}: raise ValueError("Selected app was not returned by the current protected catalog; ownership and global absence are unverified")
    row = typed(App, envelope(await request(data, "/apps/" + selected), "app"))
    if row.id != int(selected): raise RuntimeError("Sematext detail did not confirm its selected catalog app ID")
    await current_credential(data)
    return row


def list_result(rows, limit, *, received_count, filtered_count=0):
    return {"status": "success", "results": rows[:limit], "received_count": received_count,
            "returned_count": min(len(rows), limit), "filtered_count": filtered_count, "locally_truncated": len(rows) > limit,
            "completion": "unknown", "resource_access_verified": True, "identity_verified": False, "account_ownership_verified": False}


async def list_apps(data, limit):
    now = await current_credential(data)
    allowed = approved_apps(now["approved_app_ids_json"])
    if not allowed: raise ValueError("Approve existing Sematext app IDs before listing apps")
    rows = array(App, await request(data, "/apps"), "apps")
    projected = [output(row, now) for row in rows if str(row.id) in allowed]
    await current_credential(data)
    return list_result(projected, limit, received_count=len(rows), filtered_count=len(rows) - len(projected))


class SematextNode(WorkflowNode):
    integration_type = "automation-sematext"
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", noun="Sematext app catalog access",
        label_keys=(), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="sematext", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,), note="Supplied account API key in Authorization: apiKey header at its explicit US/EU region. App ingestion/read/write tokens are not this family. Current provider acceptance and saved app restrictions remain authoritative; no OAuth scope or account ownership inferred.") for op in OPS})
    edit_examples = ["Read metadata for an approved Sematext app", "List alert-rule status for an approved app", "List supported app types"]
    @classmethod
    def get_config_model(cls): return SematextNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native Sematext Cloud credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    # Execution also supplies trusted workflow context outside the base hook contract.
    @classmethod
    async def _freshen_credential(cls, data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        credential(data)
        if isinstance(data, BoundCredential):
            await current_credential(data)
            return data
        if "_sematext_authority_required" in data: raise ValueError("Sematext Cloud saved authority was lost; reload")
        if not credential_id: return credential(data)
        if not user_id: raise ValueError("Sematext Cloud requires the actual current caller")
        if pool is None:
            from utils.database_pool import get_native_pool
            pool = get_native_pool()
        organization_derived = organization_id is None
        if organization_derived:
            from wss.handlers.workflow_handler import get_user_org_context
            async with pool.acquire() as conn: organization_id = await get_user_org_context(conn, user_id)
        return await bind_current(data, pool=pool, user_id=user_id, credential_id=credential_id,
            organization_id=organization_id, workflow_id=workflow_id, organization_derived=organization_derived)
    @classmethod
    async def validate_credential_access(cls, data, *, validation_context=None):
        try: credential(data)
        except ValueError: return {"valid": False, "error": "Complete the native Sematext Cloud credential form"}
        # Staging's post-connect hook supplies no trusted saved-row context.
        # The registered connection-evidence operation performs the native probe.
        return {"valid": None, "error": "Save and check current Sematext Cloud resource access"}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        await current_credential(credential_data)
        if page_token is not None: raise ValueError("Sematext documents no continuation for these selected routes")
        if field_name != "app_id": return {"options": [], "next_page_token": None, "completion": "unknown"}
        result = await list_apps(credential_data, 100)
        if result["locally_truncated"]: raise ValueError("Sematext app options exceed the native bound; completion is unverified")
        options = [{"value": str(row["id"]), "label": row.get("name") or str(row["id"]),
                    "metadata": {"completion": "unknown", "identity_verified": False}} for row in result["results"]]
        term = (normalize_search(search) or "").casefold()
        if term: options = [row for row in options if term in (row["label"] + " " + row["value"]).casefold()]
        await current_credential(credential_data)
        return {"options": options, "next_page_token": None, "completion": "unknown"}
    async def execute(self, inputs: dict) -> dict:
        # Keep raw bound credentials intact so their current authority is rechecked.
        if "credentials" in self.node_data:
            raw_credential = self.node_data["credentials"]
        else:
            raw_credential = self.config.credentials.model_dump() if self.config.credentials is not None else None
        data = await self._freshen_credential(raw_credential, pool=self.node_data.get("_approval_pool"),
            user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        cfg = self.config.config
        now = await current_credential(data)
        if isinstance(cfg, CheckConnection):
            rows = array(App, await request(data, "/apps"), "apps")
            await current_credential(data)
            return {"status": "success", "witness_verified": True, "received_count": len(rows), "completion": "unknown",
                    "resource_access_verified": True, "identity_verified": False, "account_ownership_verified": False}
        if isinstance(cfg, ListApps): return await list_apps(data, cfg.limit)
        if isinstance(cfg, ListAppTypes):
            types = envelope(await request(data, "/apps/types"), "appTypes")
            if not isinstance(types, list) or len(types) > 1000 or any(not isinstance(t, str) or not t or len(t) > 200 for t in types) or len(set(types)) != len(types):
                raise RuntimeError("Sematext returned unverified app-type strings")
            await current_credential(data)
            return list_result(types, cfg.limit, received_count=len(types))
        row = await app_witness(data, cfg.app_id)
        if isinstance(cfg, GetApp):
            await current_credential(data)
            return {"status": "success", "data": output(row, now), "catalog_link_verified": True,
                    "resource_access_verified": True, "identity_verified": False, "account_ownership_verified": False}
        rules = array(AlertRule, await request(data, "/apps/" + cfg.app_id + "/alerts"), "alertRules")
        if any(rule.appId != row.id for rule in rules): raise RuntimeError("Sematext alert-rule metadata did not confirm its selected app ancestry")
        await current_credential(data)
        return {**list_result([output(rule, now) for rule in rules], cfg.limit, received_count=len(rules)),
                "app_id": cfg.app_id, "parent_link_verified": True}
