"""DNSimple account-scoped domain and zone metadata reads.
Only supplied account tokens and closed routes are supported; catalog access is not identity.
"""
import json
import re
from datetime import date, datetime
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

MAX_BYTES, MAX_ROWS, MAX_PAGE = 2 * 1024 * 1024, 10000, 10000
HOSTS = {"production": "https://api.dnsimple.com/v2", "sandbox": "https://api.sandbox.dnsimple.com/v2"}


def _text(value, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _integer(value, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 2**53 - 1: raise ValueError("Expected exact bounded metadata integer")
    return value


def _selected_id(value):
    # Native selects use string values; numeric IDs remain exact, never names.
    if type(value) is int: return str(_integer(value, True))
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value) or _integer(int(value), True) != int(value): raise ValueError("Use a current positive numeric domain ID")
    return value


def _name(value):
    value = _text(value)
    if value in {".", ".."} or any(c.isspace() or c in "/\\%?#" for c in value): raise ValueError("Use a single exact current domain or zone name")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected documented DNSimple JSON object")
    return value


def _date(value, nullable=False, day=False):
    if value is None and nullable: return None
    value = _text(value, 64)
    try:
        if day: date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None: raise ValueError()
    except ValueError: raise ValueError("Expected raw ISO8601 resource date") from None
    return value


class DNSimpleAccountTokenCredential(BaseModel):
    model_config = ConfigDict(title="DNSimple Account Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developer.dnsimple.com/getting-started/", "x-credential-instructions": "Supply an existing ACCOUNT access token, exact account ID and explicit production or sandbox. Bearer header only; sandbox requires separately issued keys. No token issue/refresh, Basic/user-token/OTP/OAuth flow or host fallback. Token kind is a supplied declaration, not provider identity proof. Protected catalog access proves reachability only; scoped permissions and plan eligibility are unknown."})
    credential_type: Literal["dnsimple_account_token"] = Field("dnsimple_account_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing Account Access Token", json_schema_extra={"ui:widget": "password"})
    account_id: int = Field(..., strict=True, ge=1, le=2**53-1, title="Bound DNSimple Account ID")
    environment: Literal["production", "sandbox"] = Field("production", title="Explicit API Environment")
    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply raw account token without prefix or whitespace")
        return clean_secret(value, field_name="DNSimple account token")


def _credential(raw):
    if isinstance(raw, DNSimpleAccountTokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "dnsimple_account_token": raise ValueError("Select the authoritative DNSimple account-token family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) != {"credential_type", "access_token", "account_id", "environment"}: raise ValueError("Explicit account-token/account/environment grant required; no other auth family")
    try: return DNSimpleAccountTokenCredential.model_validate(raw)
    except Exception: raise ValueError("DNSimple supplied account-token binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, load):
        super().__init__(data)
        self.load = load
        self.anchor = _stored(data)

    async def reload(self):
        try:
            if _stored(await self.load()) != self.anchor:
                raise ValueError()
        except Exception:
            raise ValueError("DNSimple current saved token/account/environment or access changed") from None

    def __repr__(self): return "<DNSimple current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "DNSimple Metadata", "x-is-trigger": False})


class _Catalog(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Domain and Zone Names", description="Names and Unicode names are private route labels. Default outputs contain scalar metadata only; zone-name pickers require opt-in.")
    page: int = Field(1, strict=True, ge=1, le=MAX_PAGE, title="Current Catalog Page", description="Documented page1 start. Local maximum10000; one selected page, no blind pagination or global absence claim.")
    per_page: int = Field(30, strict=True, ge=1, le=100, title="Page Size", description="Documented default30/max100. Pagination totals describe the current token-filtered collection only.")


class DNSimpleDomainsConfig(_Catalog):
    operation: Literal["list_domains"] = _op("list_domains", "Read Accessible Domain Catalog")


class DNSimpleDomainConfig(_Catalog):
    operation: Literal["get_domain"] = _op("get_domain", "Get Current Domain Metadata")
    domain_id: str = Field(..., title="Current Domain ID", json_schema_extra={"x-resource-type": "domain_id", "x-dynamic-options": {"field_name": "domain_id", "depends_on": ["page", "per_page", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("domain_id", mode="before")
    @classmethod
    def selected_domain(cls, value): return _selected_id(value)


class DNSimpleZonesConfig(_Catalog):
    operation: Literal["list_zones"] = _op("list_zones", "Read Accessible Zone Catalog")


class DNSimpleZoneConfig(_Catalog):
    operation: Literal["get_zone"] = _op("get_zone", "Get Current Zone Metadata")
    zone_name: str = Field(..., title="Current Zone Name", json_schema_extra={"x-resource-type": "zone_name", "x-dynamic-options": {"field_name": "zone_name", "depends_on": ["page", "per_page", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("zone_name", mode="before")
    @classmethod
    def selected_zone(cls, value): return _name(value)


DNSimpleOperation = Annotated[Union[DNSimpleDomainsConfig, DNSimpleDomainConfig, DNSimpleZonesConfig, DNSimpleZoneConfig], Field(discriminator="operation")]
class DNSimpleNodeConfig(NodeConfig[DNSimpleOperation, DNSimpleAccountTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _projected(raw, account, kind, names=False, singleton=False):
    row = _object(raw)
    anchor = (_integer(row.get("account_id"), True), _integer(row.get("id"), True), _name(row.get("name")))
    if anchor[0] != account: raise ValueError("Returned resource account crosses the bound account")
    out = {"id": anchor[1], "account_id": anchor[0], "created_at": _date(row.get("created_at")), "updated_at": _date(row.get("updated_at"))}
    if kind == "domains":
        if row.get("state") not in {"hosted", "registered", "expired"}: raise ValueError("Expected documented domain state")
        if "expires_at" not in row: raise ValueError("Explicit nullable domain expiry required")
        out.update(state=row["state"], expires_at=_date(row.get("expires_at"), nullable=True))
        if "expires_on" in row: out["expires_on"] = _date(row["expires_on"], nullable=True, day=True)
        if names: out["unicode_name"] = _text(row.get("unicode_name"))
    elif kind == "zones":
        if "last_transferred_at" not in row: raise ValueError("Explicit nullable zone transfer date required")
        for field in ("active", "reverse", "secondary"):
            if type(row.get(field)) is not bool: raise ValueError("Expected documented zone flag")
            out[field] = row[field]
        out["last_transferred_at"] = _date(row.get("last_transferred_at"), nullable=True)
        if singleton and "records_count" in row: out["records_count"] = _integer(row["records_count"])
    else: raise ValueError("Closed metadata projection required")
    if names: out["name"] = anchor[2]
    return out, anchor


def _paging(raw, count, exposed, config):
    meta = _object(raw)
    out = {field: _integer(meta.get(field), field in {"current_page", "per_page"}) for field in ("current_page", "per_page", "total_entries", "total_pages")}
    if out["current_page"] != config.page or out["per_page"] > 100 or out["total_entries"] < count: raise ValueError("Unsupported current token-filtered pagination witness")
    truncated = count > config.per_page
    more = out["current_page"] < out["total_pages"]
    return {"pagination": out, "returned_count": count, "exposed_count": exposed, "local_truncated": truncated, "has_more": None if truncated else more, "pagination_complete": None if truncated else not more, "next_page_token": None if truncated or not more or config.page >= MAX_PAGE else str(config.page + 1), "count_scope": "current_token_filtered_collection", "global_account_coverage_proven": False}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, kind, singleton=False):
        if kind not in {"domains", "zones"}: raise ValueError("Closed DNSimple metadata route required")
        path = "/" + str(self.key.account_id) + "/" + kind
        params = {"page": str(self.config.page), "per_page": str(self.config.per_page)}
        if singleton:
            path += "/" + (_selected_id(self.config.domain_id) if kind == "domains" else quote(_name(self.config.zone_name), safe=""))
            params = {}
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", HOSTS[key.environment] + path, params=params, headers={"Authorization": "Bearer " + key.access_token, "Accept": "application/json"}) as response:
                    self.status = response.status_code; headers = response.headers; body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("DNSimple response exceeds local byte bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200:
                reason = {401: "Account token authentication failed", 402: "Account standing prevents this read", 403: "Resource permission is unverified", 404: "Resource is missing-or-invisible", 412: "Plan feature access is unverified", 429: "Rate or failed-auth block prevents verification"}.get(self.status, "Protected metadata access could not be verified")
                raise _ProviderError(self.error(reason + "; private provider bodies omitted; no retry or environment fallback"))
            if "application/json" not in headers.get("content-type", "").lower(): raise ValueError("Expected DNSimple JSON representation")
            return _object(json.loads(body))
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("DNSimple transport outcome unknown; no retry or environment fallback")) from None
    async def catalog(self, kind):
        raw = await self.request(kind); rows = raw.get("data")
        if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise ValueError("Expected bounded documented data array")
        parsed = [_projected(row, self.key.account_id, kind, self.config.include_names) for row in rows[:self.config.per_page]]
        anchors = [anchor for _, anchor in parsed]
        if len({a[1] for a in anchors}) != len(anchors) or len({a[2] for a in anchors}) != len(anchors): raise ValueError("Ambiguous current catalog IDs/names")
        data = [row for row, _ in parsed]
        return {"data": data, **_paging(raw.get("pagination"), len(rows), len(data), self.config)}, anchors


class DNSimpleNode(WorkflowNode):
    integration_type = "automation-dnsimple"
    credential_provider_labels = {"dnsimple": "DNSimple"}
    auto_select_credential = False
    connection_evidence = ConnectionEvidence(operation="list_domains", noun="DNSimple protected account domain catalog", proves="reachability")
    edit_examples = ["Read accessible domain states and raw expiry dates without exposing domain names", "Read current zone flags and singleton record counts without any DNS record data"]
    @classmethod
    def get_config_model(cls): return DNSimpleNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._resolve_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )
    @classmethod
    async def _resolve_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        initial = _stored(credential_data)
        if not credential_id:
            return credential_data

        async def load():
            from nodes.core.run_op import resolve_operation_credential

            return await resolve_operation_credential(
                credential_id, user_id, pool, organization_id, workflow_id,
            )

        try:
            current = await load()
            if _stored(current) != initial:
                raise ValueError()
            return _CurrentCredential(current, load)
        except Exception:
            raise ValueError("DNSimple saved account token unavailable under current access") from None
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            kind = "domains" if config.operation in {"list_domains", "get_domain"} else "zones" if config.operation in {"list_zones", "get_zone"} else None
            if kind is None: raise ValueError("Closed native operation required")
            out, anchors = await session.catalog(kind); status = session.status
            if config.operation.startswith("get_"):
                selected = next((a for a in anchors if str(a[1]) == config.domain_id), None) if kind == "domains" else next((a for a in anchors if a[2] == config.zone_name), None)
                if selected is None: raise ValueError("Selection not established on bounded current catalog page; no global absence claim")
                raw = await session.request(kind, True)
                data, anchor = _projected(raw.get("data"), session.key.account_id, kind, config.include_names, True); status = session.status
                if anchor != selected: raise ValueError("Detail differs from exact current account/id/name catalog witness")
                out = {"data": data}
                if selected not in (await session.catalog(kind))[1]: raise ValueError("Selection left current catalog page")
            elif set((await session.catalog(kind))[1]) != set(anchors): raise ValueError("Current catalog page witnesses changed")
            session.status = status
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "account_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current saved credentials/account catalog ancestry or typed metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data); context = context or {}
        if field_name not in {"domain_id", "zone_name"}: raise ValueError("Select a native domain ID or zone field")
        if search is not None: _text(search, 100)
        if field_name == "zone_name" and context.get("include_names") is not True: return {"options": [], "has_more": None, "next_page_token": None, "message": "Enable Include Domain and Zone Names to reveal zone route labels, or enter a known name"}
        page = context.get("page", 1)
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", page_token) or int(page_token) > MAX_PAGE: raise ValueError("Use only a bounded numeric catalog continuation")
            page = int(page_token)
        config_type = DNSimpleDomainsConfig if field_name == "domain_id" else DNSimpleZonesConfig
        config = config_type(page=page, per_page=context.get("per_page", 30), include_names=context.get("include_names", False))
        result = await cls._dispatch(credential_data, config)
        if result.get("status") != "success": raise ValueError(result["error"])
        options = [{"value": str(row["id"]) if field_name == "domain_id" else row["name"], "label": row.get("name", "Domain " + str(row["id"])), "metadata": {"id": row["id"], "account_id": row["account_id"], "protected_catalog": True, "ownership_proven": False}} for row in result["data"]]
        return {"options": [r for r in options if not search or search.casefold() in r["label"].casefold()], "has_more": result["has_more"], "next_page_token": result["next_page_token"]}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials
        initial = _credential(raw)
        credential = await self._resolve_current_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
