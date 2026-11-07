"""Grocy location and quantity-unit metadata using an existing header API key.
Independent current catalogs witness access, never actor or server ownership.
"""
import ipaddress
import json
import re
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from dataclasses import dataclass
from uuid import UUID

from repositories.credentials import credential_access_predicate
from repositories.organization import OrgRepo


class GrocyAuthorityRepo:
    """Read the saved credential anchor under the shared access predicate."""
    def __init__(self, pool):
        self.pool = pool

    async def organization(self, caller_id):
        async with self.pool.acquire() as conn:
            return await OrgRepo(self.pool).get_primary_org_id(conn, caller_id)

    async def load(self, credential_id, principal_id, organization_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(f"""
                SELECT c.credential, c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at
                FROM credentials c
                WHERE c.id = $1::uuid AND {credential_access_predicate()}
            """, credential_id, principal_id, organization_id)


CURRENT_ORGANIZATION = object()


@dataclass(frozen=True)
class GrocyCredentialAnchor:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: str | None
    current_organization: bool
    workflow_id: str | None
    owner_id: str
    credential_type: str
    token_version: int


class GrocyCredentialStore:
    def __init__(self, pool, user_id, credential_id, *, validate,
                 organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.validate = validate
        self.current = None

    async def load(self):
        from utils.credentials import (
            resolve_credential_with_owner_fallback, get_workflow_owner_id,
            is_credential_authorized_for_workflow, credential_lender,
        )
        from utils.encryption import get_encryption
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        self.current = None
        repo = GrocyAuthorityRepo(self.pool)
        current_org = self.organization_id is CURRENT_ORGANIZATION
        org = await repo.organization(self.user_id) if current_org else self.organization_id
        principal = self.user_id
        row = await repo.load(self.credential_id, principal, org)
        if row is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if owner and owner != self.user_id and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id):
                principal = owner
                row = await repo.load(self.credential_id, principal, org)
        if row is None and self.workflow_id:
            lender = await credential_lender(self.pool, self.workflow_id, self.credential_id)
            if lender and lender != self.user_id:
                principal = lender
                row = await repo.load(self.credential_id, principal, org)
        if (row is None or row['revoked_at'] is not None
                or row['credential_type'] != 'grocy_api_key'
                or type(row['token_version']) is not int or row['token_version'] < 1):
            raise ValueError('Grocy saved credential unavailable under current authority')
        resolved = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool, org_id=org, workflow_id=self.workflow_id,
        )
        if resolved is None:
            raise ValueError('Grocy saved credential unavailable under current authority')
        data = get_encryption().decrypt_credential(row['credential'])
        data['credential_type'] = row['credential_type']
        data = self.validate(data)
        if data != self.validate(resolved):
            raise ValueError('Grocy saved credential changed during resolution')
        self.current = GrocyCredentialAnchor(
            self.credential_id, self.user_id, str(principal), org, current_org,
            self.workflow_id, str(row['owner_id']), row['credential_type'], row['token_version'],
        )
        return {**data, 'token_version': row['token_version']}

from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin

MAX_BYTES, MAX_ROWS, MAX_ID = 2 * 1024 * 1024, 10000, 9007199254740991


def _text(value, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _integer(value):
    if type(value) is not int or not 1 <= value <= MAX_ID: raise ValueError("Expected a strict positive integer within the local UI-safe ID bound")
    return value


def _selected_id(value):
    if type(value) is int: return str(_integer(value))
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value): raise ValueError("Use the exact canonical decimal ID from the current picker")
    _integer(int(value))
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected documented Grocy JSON object")
    return value


def _origin(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use a bounded public HTTPS origin")
    try:
        origin = normalize_https_origin(value, field_name="Grocy instance"); host = urlsplit(origin).hostname
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError("IP literals are unsupported")
        if not host or "." not in host or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
        return origin
    except (ValueError, SSRFError): raise ValueError("Use one public HTTPS Grocy origin without userinfo, path, query or fragment") from None


class GrocyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Grocy API Key", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://grocy.info/", "x-credential-instructions": "Supply an existing API key and one public HTTPS instance origin. GROCY-API-KEY header only, fixed /api. Protected location catalog access shows reachability, not identity, key kind, role or ownership. No login, token issue/refresh, Basic/Bearer/OAuth or host fallback. Installed source/spec parity and permissions remain unverified."})
    credential_type: Literal["grocy_api_key"] = Field("grocy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, title="Existing API Key", json_schema_extra={"ui:widget": "password"})
    instance_url: str = Field(..., title="Public HTTPS Grocy Instance Origin")
    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply a raw API key without prefix or whitespace")
        return clean_secret(value, field_name="Grocy API key")
    @field_validator("instance_url", mode="before")
    @classmethod
    def instance(cls, value): return _origin(value)


def _credential(raw):
    if isinstance(raw, GrocyAPIKeyCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "grocy_api_key": raise ValueError("Select the authoritative Grocy API-key family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) != {"credential_type", "api_key", "instance_url"}: raise ValueError("Explicit API-key/public-instance grant required; no other auth family")
    try: return GrocyAPIKeyCredential.model_validate(raw)
    except Exception: raise ValueError("Grocy supplied API-key/public-instance binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store): super().__init__(data); self.store, self.anchor = store, self.identity(store.current)
    @staticmethod
    def identity(row): return tuple(getattr(row, name) for name in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))
    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("Grocy current saved key/instance or authority changed") from None
    def __repr__(self): return "<Grocy current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Grocy Metadata", "x-is-trigger": False})


class _Metadata(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Private Resource Names", description="Names are opt-in. Userfields, plural forms, product/stock data and every other field stay excluded.")
    limit: int = Field(100, strict=True, ge=1, le=100, title="Local Catalog Limit", description="Catalogs send only documented limit. Default100 and maximum100 are local bounds; vendor default/maximum and completion are unknown. Details send no query parameters.")


class GrocyLocationsConfig(_Metadata):
    operation: Literal["list_locations"] = _op("list_locations", "Read Accessible Location Metadata")


class GrocyLocationConfig(_Metadata):
    operation: Literal["get_location"] = _op("get_location", "Get Current Location Metadata")
    location_id: str = Field(..., title="Current Location ID", description="Canonical positive decimal ID from this independent current catalog; local UI-safe bound, not a vendor limit.", json_schema_extra={"x-resource-type": "location_id", "x-dynamic-options": {"field_name": "location_id", "allow_custom": True}})
    @field_validator("location_id", mode="before")
    @classmethod
    def selected_location(cls, value): return _selected_id(value)


class GrocyQuantityUnitsConfig(_Metadata):
    operation: Literal["list_quantity_units"] = _op("list_quantity_units", "Read Accessible Quantity Unit Metadata")


class GrocyQuantityUnitConfig(_Metadata):
    operation: Literal["get_quantity_unit"] = _op("get_quantity_unit", "Get Current Quantity Unit Metadata")
    quantity_unit_id: str = Field(..., title="Current Quantity Unit ID", description="Canonical positive decimal ID from this independent current catalog; no inferred relation to a location.", json_schema_extra={"x-resource-type": "quantity_unit_id", "x-dynamic-options": {"field_name": "quantity_unit_id", "allow_custom": True}})
    @field_validator("quantity_unit_id", mode="before")
    @classmethod
    def selected_quantity_unit(cls, value): return _selected_id(value)


GrocyOperation = Annotated[Union[GrocyLocationsConfig, GrocyLocationConfig, GrocyQuantityUnitsConfig, GrocyQuantityUnitConfig], Field(discriminator="operation")]
class GrocyNodeConfig(NodeConfig[GrocyOperation, GrocyAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _projected(raw, names=False):
    row = _object(raw); identifier = _integer(row.get("id")); out = {"id": identifier}
    if "row_created_timestamp" in row:
        value = row["row_created_timestamp"]
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Expected a bounded raw timestamp STRING")
        out["row_created_timestamp"] = value
    if names and "name" in row: out["name"] = _text(row["name"], 1024)
    return out, identifier


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, kind, identifier=None):
        if kind not in {"locations", "quantity_units"}: raise ValueError("Closed Grocy metadata route required")
        path, params = "/api/objects/" + kind, {"limit": str(self.config.limit)}
        if identifier is not None: path += "/" + str(_integer(identifier)); params = {}
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            async with guarded_async_client( timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", key.instance_url + path, params=params, headers={"GROCY-API-KEY": key.api_key, "Accept": "application/json"}) as response:
                    self.status = response.status_code; headers = response.headers; body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("Grocy response exceeds local byte bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200:
                reason = {401: "Authentication was not verified; cause is ambiguous", 403: "Permission is unverified", 404: "Resource is missing-or-invisible", 429: "Rate limit prevents verification"}.get(self.status, "Protected metadata access could not be verified")
                raise _ProviderError(self.error(reason + "; private provider bodies omitted; no retry or fallback"))
            if "application/json" not in headers.get("content-type", "").lower(): raise ValueError("Expected Grocy JSON representation")
            return json.loads(body)
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("Grocy transport outcome unknown; no retry or fallback")) from None
    async def catalog(self, kind):
        rows = await self.request(kind); cap = self.config.limit
        if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise ValueError("Expected locally bounded documented bare catalog ARRAY")
        parsed = [_projected(row, self.config.include_names) for row in rows[:cap]]; identifiers = [i for _, i in parsed]
        if len(set(identifiers)) != len(identifiers): raise ValueError("Ambiguous current independent catalog IDs")
        return {"data": [r for r, _ in parsed], "returned_count": len(rows), "exposed_count": len(parsed), "local_truncated": len(rows) > cap, "has_more": None, "pagination_complete": None, "next_page_token": None, "count_scope": "current_api_key_visible_bounded_response", "global_coverage_proven": False}, identifiers


class GrocyNode(WorkflowNode):
    integration_type = "automation-grocy"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_locations", noun="Grocy protected location catalog", proves="reachability")
    edit_examples = ["Read current location IDs and raw creation timestamps without stock or private names", "Read independent quantity-unit metadata without plural forms, conversions or userfields"]
    @classmethod
    def get_config_model(cls): return GrocyNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        config = config_data.get("config", {})
        if isinstance(config, dict):
            for field in ("location_id", "quantity_unit_id"):
                if field in config:
                    try: _selected_id(config[field])
                    except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_for_execution(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def _freshen_for_execution(cls, credential_data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        _credential(credential_data)
        if not credential_id: return credential_data
        organization = organization_id
        if organization is None and not workflow_id: organization = CURRENT_ORGANIZATION
        store = GrocyCredentialStore(pool, user_id, credential_id, validate=_stored, organization_id=organization, workflow_id=workflow_id)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("Grocy saved API key unavailable under current authority") from None
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Grocy literal API-key/public-instance family unsupported"}
        if validation_context is None: return {"valid": True, "provider_verified": False}
        await validation_context.revalidate(); result = await validation_context.run_operation("list_locations"); await validation_context.revalidate()
        if result.get("status") == "success" and result.get("protected_reachability_verified") is True: return {"valid": True, "provider_verified": True}
        return {"valid": None, "error": result.get("error", "Protected location catalog access could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            kind = "locations" if config.operation in {"list_locations", "get_location"} else "quantity_units" if config.operation in {"list_quantity_units", "get_quantity_unit"} else None
            if kind is None: raise ValueError("Closed native operation required")
            out, identifiers = await session.catalog(kind)
            if config.operation in {"get_location", "get_quantity_unit"}:
                selected = int(config.location_id if kind == "locations" else config.quantity_unit_id)
                if selected not in identifiers: raise ValueError("Selection not on current bounded independent catalog; no global absence claim")
                row, identifier = _projected(await session.request(kind, selected), config.include_names)
                if identifier != selected: raise ValueError("Detail ID differs from current route/catalog witness")
                out = {"data": row}
                if selected not in (await session.catalog(kind))[1]: raise ValueError("Selection left current independent catalog")
            elif set((await session.catalog(kind))[1]) != set(identifiers): raise ValueError("Current independent catalog IDs changed")
            if session.key.api_key in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "instance_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current saved credential/independent catalog or typed metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data); context = context or {}
        if field_name not in {"location_id", "quantity_unit_id"}: raise ValueError("Select a native independent location or quantity-unit ID field")
        if page_token is not None: raise ValueError("Input page/URL continuation is not declared; bounded initial catalog only")
        if search is not None: _text(search, 100)
        config_type = GrocyLocationsConfig if field_name == "location_id" else GrocyQuantityUnitsConfig
        result = await cls._dispatch(credential_data, config_type(limit=context.get("limit", 100), include_names=context.get("include_names", False)))
        if result.get("status") != "success": raise ValueError(result["error"])
        kind = "Location" if field_name == "location_id" else "Quantity unit"
        options = [{"value": str(row["id"]), "label": row.get("name", kind + " " + str(row["id"])), "metadata": {"id": row["id"], "catalog_kind": kind.lower(), "protected_catalog": True, "ownership_proven": False}} for row in result["data"]]
        return {"options": [r for r in options if not search or search.casefold() in r["label"].casefold()], "has_more": None, "next_page_token": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials
        initial = _credential(raw)
        credential = raw if isinstance(raw, _CurrentCredential) else initial
        if self.node_data.get("credential_id"):
            credential = await self._freshen_for_execution(raw, pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id)
        return await self._dispatch(credential, self.config.config)
