"""STACKIT DNS metadata only; fixed service, supplied token, no record values/control."""
import json
import re
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.stackitdns_authority import STACKITDNSCredentialsStore, CURRENT_ORGANIZATION
from utils.ssrf import SSRFError, guarded_async_client

HOST, MAX_BYTES, MAX_ROWS = "https://dns.api.stackit.cloud", 2 * 1024 * 1024, 100
STATES = {"CREATING", "CREATE_SUCCEEDED", "CREATE_FAILED", "DELETING", "DELETE_SUCCEEDED", "DELETE_FAILED", "UPDATING", "UPDATE_SUCCEEDED", "UPDATE_FAILED"}
RRTYPES = {"A", "AAAA", "SOA", "CNAME", "NS", "MX", "TXT", "SRV", "PTR", "ALIAS", "DNAME", "CAA", "DNSKEY", "DS", "LOC", "NAPTR", "SSHFP", "TLSA", "URI", "CERT", "SVCB", "TYPE", "CSYNC", "HINFO", "HTTPS"}
TIMES = ("creationStarted", "creationFinished", "updateStarted", "updateFinished")


def _text(value, limit=255, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _id(value):
    value = _text(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", value) or value in {".", ".."}: raise ValueError("Use one safe path ID; UUID format is not required")
    return value


def _integer(value, low=0, high=2**31 - 1):
    if type(value) is not int or not low <= value <= high: raise ValueError("Expected documented bounded metadata integer")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected published JSON object")
    return value


def _array(value, bound=MAX_ROWS):
    if not isinstance(value, list) or len(value) > bound: raise ValueError("Expected documented bounded array")
    return value


class STACKITDNSAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="STACKIT DNS Access Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.stackit.cloud/platform/access-and-identity/service-accounts/access-a-service-with-a-service-account/", "x-credential-instructions": "Supply an existing short- or long-lived service-account access token and protected project ID. Fixed STACKIT DNS host/Bearer header only, not Domain Portal. No token issue/exchange/refresh/JWT/RSA, SDK/CLI or service enabling. Resource access is not actor/project ownership. Permissions/entitlement remain unverified."})
    credential_type: Literal["stackitdns_access_token"] = Field("stackitdns_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing STACKIT Access Token", json_schema_extra={"ui:widget": "password"})
    project_id: str = Field(..., title="Protected Supplied Project ID")
    @field_validator("access_token", mode="before")
    @classmethod
    def secret(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply raw token without Bearer prefix or whitespace")
        return clean_secret(value, field_name="STACKIT access token")
    @field_validator("project_id", mode="before")
    @classmethod
    def project(cls, value): return _id(value)


def _credential(raw):
    if isinstance(raw, STACKITDNSAccessTokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "stackitdns_access_token": raise ValueError("Select the actual STACKIT DNS access token family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) - {"credential_type", "access_token", "project_id"}: raise ValueError("Unsupported raw token/project binding; no host/refresh grant")
    try: return STACKITDNSAccessTokenCredential.model_validate(raw)
    except Exception: raise ValueError("STACKIT DNS token/project binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store): super().__init__(data); self.store, self.anchor = store, self.identity(store.current)
    @staticmethod
    def identity(row): return tuple(getattr(row, name) for name in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))
    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("STACKIT current token/project or saved authority changed") from None
    def __repr__(self): return "<STACKIT DNS current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "STACKIT DNS Metadata", "x-is-trigger": False})
def _page(default=1, title="Page"): return Field(default, strict=True, ge=1, le=2**31 - 1, title=title)


class _Binding(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    project_id: str | None = Field(None, title="Protected Project Context", description="Uses the credential's supplied project when omitted. An explicit selection must agree.", json_schema_extra={"x-resource-type": "project_id", "x-dynamic-options": {"field_name": "project_id", "allow_custom": True, "auto_select_sole_option": False}})
    include_names: bool = Field(False, strict=True, title="Include User and DNS Names", description="Opt in to zone name/dnsName and RRset name. IDs/type/status/time/count metadata remain the default.")
    page_size: int = Field(20, strict=True, ge=1, le=MAX_ROWS, title="Page Size", description="Documented pageSize vendor maximum10000; local bound100.")
    @field_validator("project_id", mode="before")
    @classmethod
    def validate_project(cls, value): return None if value is None else _id(value)


class STACKITDNSZonesConfig(_Binding):
    operation: Literal["list_zones"] = _op("list_zones", "Read Protected Zone Metadata")
    page: int = _page()


class _Zone(_Binding):
    zone_id: str = Field(..., title="Zone ID", json_schema_extra={"x-resource-type": "zone_id", "x-dynamic-options": {"field_name": "zone_id", "depends_on": ["project_id", "zone_catalog_page", "page_size", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    zone_catalog_page: int = _page(title="Zone Catalog Page for Ancestry")
    @field_validator("zone_id", mode="before")
    @classmethod
    def validate_zone(cls, value): return _id(value)


class STACKITDNSZoneConfig(_Zone):
    operation: Literal["get_zone"] = _op("get_zone", "Get Zone Metadata")
class STACKITDNSRRSetsConfig(_Zone):
    operation: Literal["list_rrsets"] = _op("list_rrsets", "Read Zone RRset Metadata")
    page: int = _page(title="RRset Page")
class STACKITDNSRRSetConfig(STACKITDNSRRSetsConfig):
    operation: Literal["get_rrset"] = _op("get_rrset", "Get RRset Metadata")
    rrset_id: str = Field(..., title="RRset ID", json_schema_extra={"x-resource-type": "rrset_id", "x-dynamic-options": {"field_name": "rrset_id", "depends_on": ["project_id", "zone_id", "zone_catalog_page", "page", "page_size", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("rrset_id", mode="before")
    @classmethod
    def validate_rrset(cls, value): return _id(value)


STACKITDNSOperation = Annotated[Union[STACKITDNSZonesConfig, STACKITDNSZoneConfig, STACKITDNSRRSetsConfig, STACKITDNSRRSetConfig], Field(discriminator="operation")]
class STACKITDNSNodeConfig(NodeConfig[STACKITDNSOperation, STACKITDNSAccessTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _projected(raw, rrset=False, names=False):
    row = _object(raw); out = {"resource_type": "rrset" if rrset else "zone", "id": _id(row.get("id"))}
    if row.get("type") not in (RRTYPES if rrset else {"primary", "secondary"}) or row.get("state") not in STATES: raise ValueError("Unsupported published type/state")
    out.update(type=row["type"], state=row["state"])
    field = "ttl" if rrset else "defaultTTL"; out[field] = _integer(row.get(field), 60, 99999999)
    for field in TIMES: out[field] = _text(row.get(field), 128, empty=True)
    for field in (("active",) if rrset else ("active", "isReverseZone")):
        if field in row:
            if type(row[field]) is not bool: raise ValueError("Expected published metadata boolean")
            out[field] = row[field]
    if not rrset:
        out["serialNumber"] = _integer(row.get("serialNumber"))
        if row.get("visibility") != "public": raise ValueError("Unsupported published zone visibility")
        out["visibility"] = row["visibility"]
        if "recordCount" in row: out["recordCount"] = _integer(row["recordCount"])
    if names:
        out["name"] = _text(row.get("name"), 253 if rrset else 63)
        if not rrset: out["dnsName"] = _text(row.get("dnsName"), 253)
    return out


def _catalog(raw, key, page, size, rrset=False, names=False):
    wrapper = _object(raw); rows = _array(wrapper.get(key), size)
    data = [_projected(row, rrset, names) for row in rows]
    if len({row["id"] for row in data}) != len(data): raise ValueError("Duplicate IDs on protected page")
    counts = {field: _integer(wrapper.get(field)) for field in ("itemsPerPage", "totalItems", "totalPages")}
    if counts["itemsPerPage"] > size or counts["totalItems"] < len(data) or (counts["totalPages"] == 0 and data): raise ValueError("Inconsistent or excessive bounded pagination metadata")
    more = page < counts["totalPages"]
    return {"data": data, "returned_count": len(data), **counts, "requested_page": page, "has_more": more, "next_page_token": str(page + 1) if more else None, "pagination_complete": not more, "count_scope": "provider_reported_selected_project_or_zone"}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    def project(self):
        if self.config.project_id is not None and self.config.project_id != self.key.project_id: raise ValueError("Selected project differs from protected supplied project")
        return self.key.project_id
    async def request(self, kind, page=None):
        path = "/v1/projects/" + quote(self.project(), safe="") + "/zones"; params = {}
        if kind in {"zone", "rrsets", "rrset"}: path += "/" + quote(_id(self.config.zone_id), safe="")
        if kind in {"rrsets", "rrset"}: path += "/rrsets"
        if kind == "rrset": path += "/" + quote(_id(self.config.rrset_id), safe="")
        if kind in {"zones", "rrsets"}: params = {"page": str(_integer(page, 1)), "pageSize": str(self.config.page_size)}
        if kind not in {"zones", "zone", "rrsets", "rrset"}: raise ValueError("Closed native metadata route required")
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", HOST + path, params=params, headers={"Authorization": "Bearer " + key.access_token, "Accept": "application/json"}) as response:
                    self.status = response.status_code; content_type = response.headers.get("content-type", ""); body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("STACKIT response exceeds local bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200: raise _ProviderError(self.error("STACKIT protected metadata read could not be verified. HTTP404 is missing-or-invisible; permissions/service eligibility remain unknown. Private provider bodies omitted; no retry"))
            if "application/json" not in content_type.lower(): raise ValueError("Expected documented JSON representation")
            return json.loads(body)
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("STACKIT transport outcome unknown; no retry")) from None
    async def zones(self, page): return _catalog(await self.request("zones", page), "zones", page, self.config.page_size, names=self.config.include_names)
    async def zone(self):
        catalog = await self.zones(self.config.zone_catalog_page)
        if self.config.zone_id not in {row["id"] for row in catalog["data"]}: raise ValueError("Zone not established on protected current page; no global absence claim")
        data = _projected(_object(await self.request("zone")).get("zone"), names=self.config.include_names)
        if data["id"] != self.config.zone_id: raise ValueError("Returned zone differs from protected current catalog ID")
        return data
    async def rrsets(self): return _catalog(await self.request("rrsets", self.config.page), "rrSets", self.config.page, self.config.page_size, rrset=True, names=self.config.include_names)


class STACKITDNSNode(WorkflowNode):
    integration_type = "automation-stackitdns"
    credential_provider_labels = {"stackitdns": "STACKIT DNS"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_zones", noun="STACKIT DNS protected supplied-project zone catalog", proves="reachability")
    edit_examples = ["Read zone status and RRset TTL metadata in my supplied STACKIT project without DNS names or RDATA", "Read a known zone and RRset's IDs and timestamps without changing DNS"]
    @classmethod
    def get_config_model(cls): return STACKITDNSNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_saved_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def _freshen_saved_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        _credential(credential_data)
        if not credential_id: return credential_data
        organization = organization_id
        if organization is None and not workflow_id: organization = CURRENT_ORGANIZATION
        store = STACKITDNSCredentialsStore(pool, user_id, credential_id, credential_type="stackitdns_access_token", validate=_stored, organization_id=organization, workflow_id=workflow_id)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("STACKIT DNS saved credential unavailable under current authority") from None
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "STACKIT literal access-token/project family unsupported"}
        if validation_context is None: return {"valid": None, "error": "Save and check protected STACKIT DNS project access"}
        await validation_context.revalidate(); result = await validation_context.run_operation("list_zones"); await validation_context.revalidate()
        if result.get("status") == "success" and result.get("protected_reachability_verified") is True: return {"valid": True, "provider_verified": True}
        return {"valid": False if result.get("http_status") == 401 else None, "error": result.get("error", "Protected zone access could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            session.project()
            if config.operation == "list_zones": out = await session.zones(config.page)
            elif config.operation in {"get_zone", "list_rrsets", "get_rrset"}:
                parent = await session.zone()
                if config.operation == "get_zone": out = {"data": parent}
                else:
                    catalog = await session.rrsets()
                    if config.operation == "list_rrsets": out = catalog
                    else:
                        if config.rrset_id not in {row["id"] for row in catalog["data"]}: raise ValueError("RRset not established on current zone page; no global absence claim")
                        data = _projected(_object(await session.request("rrset")).get("rrset"), rrset=True, names=config.include_names)
                        if data["id"] != config.rrset_id: raise ValueError("Returned RRset differs from protected current ID")
                        current = await session.rrsets()
                        if config.rrset_id not in {row["id"] for row in current["data"]}: raise ValueError("RRset left protected current parent page")
                        out = {"data": data}
                status = session.status; await session.zone(); session.status = status
            else: raise ValueError("Closed native operation required")
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "project_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current credentials/catalog ancestry or bounded published metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        key = _credential(credential_data); context = context or {}
        if field_name not in {"project_id", "zone_id", "rrset_id"}: raise ValueError("Select native project/zone/RRset field")
        project = context.get("project_id")
        if project is not None and _id(project) != key.project_id: raise ValueError("Picker crosses protected supplied project")
        page = context.get("zone_catalog_page", context.get("page", 1)) if field_name != "rrset_id" else context.get("page", 1)
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", page_token): raise ValueError("Use bounded documented numeric page continuation")
            page = _integer(int(page_token), 1)
        if search is not None: _text(search, 100)
        args = {"project_id": project, "include_names": context.get("include_names", False), "page_size": context.get("page_size", 20), "page": page}
        if field_name == "rrset_id":
            if not context.get("zone_id"): raise ValueError("Select protected current zone first")
            config = STACKITDNSRRSetsConfig(**args, zone_id=context["zone_id"], zone_catalog_page=context.get("zone_catalog_page", 1))
        else: config = STACKITDNSZonesConfig(**args)
        result = await cls._dispatch(credential_data, config)
        if result.get("status") != "success": raise ValueError(result["error"])
        rows = [{"id": key.project_id}] if field_name == "project_id" else result["data"]
        options = [{"value": row["id"], "label": row.get("dnsName", row.get("name", row["id"])), "metadata": {"resource_type": field_name.removesuffix("_id"), "protected_catalog": True, **({"binding_source": "supplied_project"} if field_name == "project_id" else {})}} for row in rows]
        return {"options": [row for row in options if not search or search.casefold() in row["label"].casefold() or search.casefold() in row["value"].casefold()], "has_more": False if field_name == "project_id" else result["has_more"], "next_page_token": None if field_name == "project_id" else result["next_page_token"]}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        credential = await self._freshen_saved_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
