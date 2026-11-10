"""Closed Aprimo DAM content-consumption metadata reads; supplied token only.

Contract: official OAS3.0.1 content-consumption subset, pinned in aprimo-42.
No asset bytes, business field values, links, identities, writes or auth exchange.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Any, Dict, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, WrapValidator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "aprimo_bearer"
OPERATIONS = (
    "get_classification", "list_registered_fields", "get_field_definition",
    "list_registered_field_groups", "get_field_group", "list_records",
    "search_records", "get_record",
)
_TENANT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PRIVATE_REQUEST = ContextVar("aprimo_private_request", default=False)


def _pending(value):
    return isinstance(value, str) and "{{" in value and "}}" in value


def _uuid(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Aprimo IDs must be explicit UUID strings")
    try:
        return UUID(value).hex
    except (ValueError, AttributeError):
        raise ValueError("Aprimo IDs must be explicit UUID strings") from None


def _reference(value, handler):
    return value if _pending(value) else handler(value)


NativeID = Annotated[str, WrapValidator(lambda value, handler: _reference(value, lambda v: _uuid(v)))]
NativeInt = Annotated[int, WrapValidator(lambda value, handler: _reference(value, handler))]
NativeFlag = Annotated[bool, WrapValidator(lambda value, handler: _reference(value, handler))]


def _operation(name, label, category):
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-display-name": label,
        "x-category": category, "x-is-trigger": False,
    })


class AprimoBearerCredential(BaseModel):
    model_config = ConfigDict(title="Aprimo DAM Bearer Token", json_schema_extra={
        "x-credential-url": "https://developers.aprimo.com/docs/rest-api/dam/dam-intro",
        "x-credential-instructions": "Supply an existing Aprimo DAM bearer token, its single tenant label, and one readable classification UUID. No token exchange or refresh is performed. DAM API entitlement and API scope must already be granted. The connection proves selected resource reachability, not account identity.",
    })
    credential_type: Literal["aprimo_bearer"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Bearer Token", json_schema_extra={"ui:widget": "password"})
    tenant: str = Field(..., title="Tenant", description="Single label before .dam.aprimo.com; no URL or path")
    classification_id: str = Field(..., title="Bound Classification ID", description="Readable classification UUID; all record and schema reads stay bound to this classification")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Supply a literal bearer token")
        value = clean_secret(value)
        if not value or len(value) > 8192 or _pending(value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a literal printable bearer token")
        return value

    @field_validator("tenant", mode="before")
    @classmethod
    def tenant_label(cls, value):
        if not isinstance(value, str) or not _TENANT.fullmatch(value):
            raise ValueError("Tenant must be one lowercase DNS label")
        return value

    @field_validator("classification_id", mode="before")
    @classmethod
    def classification(cls, value):
        return _uuid(value)


class _Base(BaseModel):
    classification_id: Optional[NativeID] = Field(None, title="Classification ID", description="Blank uses the credential-bound classification; another classification is refused", json_schema_extra={"x-resource-type": "aprimo_classification_id"})
    include_names: NativeFlag = Field(False, title="Include Names", json_schema_extra={"ui:widget": "checkbox"})


class _LocalList(_Base):
    limit: NativeInt = Field(20, ge=1, le=100, title="Local Result Limit")


class AprimoGetClassification(_Base):
    operation: Literal["get_classification"] = _operation("get_classification", "Get Classification Metadata", "Classification")


class AprimoListRegisteredFields(_LocalList):
    operation: Literal["list_registered_fields"] = _operation("list_registered_fields", "List Registered Field IDs", "Schema")


class AprimoGetFieldDefinition(_Base):
    operation: Literal["get_field_definition"] = _operation("get_field_definition", "Get Registered Field Definition", "Schema")
    field_id: NativeID = Field(..., title="Field Definition ID", description="Must be registered on the bound classification", json_schema_extra={"x-resource-type": "aprimo_field_definition_id"})


class AprimoListRegisteredFieldGroups(_LocalList):
    operation: Literal["list_registered_field_groups"] = _operation("list_registered_field_groups", "List Registered Field Group IDs", "Schema")


class AprimoGetFieldGroup(_Base):
    operation: Literal["get_field_group"] = _operation("get_field_group", "Get Registered Field Group Metadata", "Schema")
    field_group_id: NativeID = Field(..., title="Field Group ID", description="Must be registered on the bound classification", json_schema_extra={"x-resource-type": "aprimo_field_group_id"})


class AprimoListRecords(_Base):
    operation: Literal["list_records"] = _operation("list_records", "List Classified Record Metadata", "Record")
    skip: NativeInt = Field(0, ge=0, le=100000, title="Skip")
    take: NativeInt = Field(20, ge=1, le=100, title="Take", description="One bounded provider request; no link following")


class AprimoSearchRecords(_Base):
    operation: Literal["search_records"] = _operation("search_records", "Search Classified Record Metadata", "Record")
    page: NativeInt = Field(1, ge=1, le=10000, title="Page")
    page_size: NativeInt = Field(20, ge=1, le=100, title="Page Size")
    status: Optional[Literal["Active", "Released", "Archived"]] = Field(None, title="Record Status")
    content_type: Optional[Literal["Asset", "Document", "Image", "Video"]] = Field(None, title="Content Type")
    title_contains: Optional[str] = Field(None, max_length=160, title="Title Contains", description="Literal parameter value; never an expression")

    @field_validator("title_contains")
    @classmethod
    def search_text(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError("Search text must be a single line")
        return value


class AprimoGetRecord(_Base):
    operation: Literal["get_record"] = _operation("get_record", "Get Classified Record Metadata", "Record")
    record_id: NativeID = Field(..., title="Record ID", description="Exact current membership in the bound classification is checked before and after detail", json_schema_extra={"x-resource-type": "aprimo_record_id"})


AprimoOperation = Annotated[Union[
    AprimoGetClassification, AprimoListRegisteredFields, AprimoGetFieldDefinition,
    AprimoListRegisteredFieldGroups, AprimoGetFieldGroup, AprimoListRecords,
    AprimoSearchRecords, AprimoGetRecord,
], Discriminator("operation")]


class AprimoNodeConfig(NodeConfig[AprimoOperation, AprimoBearerCredential]):
    pass


def _selected_id(data):
    target = data.get("config") if isinstance(data.get("config"), dict) else {}
    ids = data.get("credentialIds", target.get("credentialIds", {}))
    if ids:
        if not isinstance(ids, dict) or any(k not in (FAMILY, "credential_type") for k in ids):
            raise ValueError("Select an Aprimo DAM credential")
        if ids.get("credential_type") not in (None, FAMILY):
            raise ValueError("Select an Aprimo DAM credential")
    direct = data.get("credential_id", target.get("credential_id"))
    mapped = ids.get(FAMILY) if isinstance(ids, dict) else None
    if direct is not None and mapped is not None and _uuid(direct) != _uuid(mapped):
        raise ValueError("Aprimo credential selections disagree")
    selected = direct or mapped
    return _uuid(selected) if selected is not None else None


def _raw_guard(data):
    if not isinstance(data, dict):
        raise ValueError("Aprimo configuration must be an object")
    selected = _selected_id(data)
    credential = data.get("credentials")
    if isinstance(credential, BaseModel):
        credential = credential.model_dump()
    if credential is not None:
        if not isinstance(credential, dict) or credential.get("credential_type") not in ((FAMILY,) if selected else (None, FAMILY)):
            raise ValueError("Credential must have its native Aprimo DAM type")
        for name in ("access_token", "tenant", "classification_id"):
            if name in credential and not isinstance(credential[name], str):
                raise ValueError("Aprimo credential fields must be strings")
        try:
            AprimoBearerCredential.model_validate(credential)
        except ValueError:
            raise ValueError("Supply a valid literal Aprimo token, tenant label and classification UUID") from None
    config = data.get("config") if isinstance(data.get("config"), dict) else data
    for name in ("classification_id", "record_id", "field_id", "field_group_id"):
        if config.get(name) is not None and not isinstance(config[name], str):
            raise ValueError("Aprimo IDs must be strings")
    for name in ("limit", "skip", "take", "page", "page_size"):
        if name in config and not _pending(config[name]) and type(config[name]) is not int:
            raise ValueError("Aprimo paging values must be integers")
    if "include_names" in config and not _pending(config["include_names"]) and type(config["include_names"]) is not bool:
        raise ValueError("Include Names must be a boolean")
    return selected


def _short_text(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value) or "://" in value:
        raise ValueError("Aprimo returned invalid metadata text")
    return value


def _project(item, kind, names=False):
    if not isinstance(item, dict):
        raise ValueError("Aprimo returned an invalid metadata object")
    result = {"id": _uuid(item.get("id"))}
    keys = {
        "record": ("status", "contentType", "createdOn", "modifiedOn"),
        "classification": ("createdOn", "modifiedOn"),
        "field": ("dataType", "scope", "scopeCategory", "languageMode", "createdOn", "modifiedOn"),
        "group": ("createdOn", "modifiedOn"),
    }[kind]
    for key in keys:
        if key in item:
            if item[key] is None:
                raise ValueError("Aprimo returned null for non-nullable metadata")
            result[key] = _short_text(item[key])
    if kind == "record" and result.get("status") not in (None, "Active", "Released", "Archived"):
        raise ValueError("Aprimo returned an undocumented record status")
    if kind == "classification":
        if "parentId" not in item:
            raise ValueError("Aprimo classification ancestry is unknown")
        result["parentId"] = _uuid(item["parentId"]) if item["parentId"] is not None else None
        if "isRoot" in item:
            if type(item["isRoot"]) is not bool:
                raise ValueError("Aprimo returned invalid classification ancestry")
            result["isRoot"] = item["isRoot"]
    if names:
        key = "title" if kind == "record" else "name"
        if key in item:
            result[key] = _short_text(item[key])
    return result


def _items(data):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or len(data["items"]) > 1000:
        raise ValueError("Aprimo returned an undocumented collection envelope")
    ids = [_uuid(v.get("id")) if isinstance(v, dict) else None for v in data["items"]]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError("Aprimo returned invalid or duplicate IDs")
    return data["items"]


def _registered(root, key, id_key):
    values = root.get(key)
    if values is None:
        return None
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError("Aprimo returned invalid classification registration metadata")
    ids = [_uuid(v.get(id_key)) if isinstance(v, dict) else None for v in values]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError("Aprimo returned invalid registered IDs")
    return ids


def _refuses_secret(data, secret):
    pending = [data]; count = 0
    while pending:
        value = pending.pop(); count += 1
        if count > 100000:
            raise ValueError("Aprimo JSON exceeds the native metadata complexity bound")
        if isinstance(value, str) and secret in value:
            raise ValueError("Aprimo response reflected a credential; output refused")
        if isinstance(value, dict):
            pending.extend(value.keys()); pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


class _PrivacyFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


@contextmanager
def _private_transport():
    marker = _PRIVATE_REQUEST.set(True)
    filters = []
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        logger = logging.getLogger(name); guard = _PrivacyFilter(); logger.addFilter(guard); filters.append((logger, guard))
    try:
        yield
    finally:
        for logger, guard in filters:
            logger.removeFilter(guard)
        _PRIVATE_REQUEST.reset(marker)


class AprimoNode(WorkflowNode):
    integration_type = "automation-aprimo"
    credential_provider_labels = {"aprimo": "Aprimo Account"}
    connection_evidence = ConnectionEvidence(operation="get_classification", noun="classification", proves="reachability")
    scope_registry = ScopeRegistry("aprimo", {name: ScopeRequirement(("api",), credential_types=(FAMILY,), note="Supplied token must already hold the documented api scope and DAM resource permission; no authorization flow is performed") for name in OPERATIONS})

    @classmethod
    def get_config_model(cls):
        return AprimoNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _raw_guard(config_data)
        except ValueError as error:
            return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    def _context(self):
        payload = {key: self.node_data.get(key) for key in ("credentialIds", "credential_id", "config", "credentials")}
        return (self.user_id, self.organization_id, self.workflow_id,
                hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
                self.config.model_dump_json())

    def _guard_context(self):
        if self._context() != self._start_context:
            raise ValueError("Aprimo actor, credential selection or configuration changed; retry from current state")

    async def run(self, inputs):
        selected = _raw_guard(self.node_data)
        if selected:
            self.node_data = dict(self.node_data)
            self.node_data["credential_id"] = selected
        self._start_context = self._context(); self._binding = None
        return await super().run(inputs)

    async def _credentials(self):
        self._guard_context()
        selected = _selected_id(self.node_data)
        attached = self.config.credentials
        if not selected:
            if attached is None:
                raise ValueError("Attach an Aprimo DAM credential")
            credential = attached
            fingerprint = ("unsaved", credential.model_dump_json())
        else:
            if not self.user_id:
                raise ValueError("Aprimo saved credentials require the current actor")
            from repositories.aprimo_authority import current_aprimo_row
            from repositories.organization import OrgRepo
            from repositories.workflow import WorkflowRepo
            from utils.credentials import is_credential_authorized_for_workflow
            from utils.database_pool import get_native_pool
            from utils.encryption import get_encryption
            pool = get_native_pool()
            async with pool.acquire() as conn:
                org = await OrgRepo(pool).get_primary_org_id(conn, self.user_id); self._guard_context()
                row = await current_aprimo_row(conn, selected, self.user_id, org); self._guard_context()
            if row is None and self.workflow_id:
                owner = await WorkflowRepo(pool).get_owner_id(self.workflow_id); self._guard_context()
                authorized = await is_credential_authorized_for_workflow(pool, self.workflow_id, selected); self._guard_context()
                if owner and owner != self.user_id and authorized:
                    async with pool.acquire() as conn:
                        row = await current_aprimo_row(conn, selected, owner, org); self._guard_context()
            if row is None or str(row["id"]).replace("-", "") != selected or row["credential_type"] != FAMILY or row["revoked_at"] is not None:
                raise ValueError("Aprimo credential is missing, inaccessible, foreign or revoked")
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if not isinstance(metadata, dict) or metadata.get("connection_healthy") is False:
                raise ValueError("Aprimo credential connection is unavailable")
            raw = get_encryption().decrypt_credential(row["credential"])
            if not isinstance(raw, dict) or raw.get("credential_type") not in (None, FAMILY):
                raise ValueError("Current credential has a foreign raw family tag")
            raw = dict(raw); raw["credential_type"] = FAMILY
            try:
                credential = AprimoBearerCredential.model_validate(raw)
            except ValueError:
                raise ValueError("Current Aprimo credential has invalid native fields") from None
            if attached and (credential.tenant, credential.classification_id) != (attached.tenant, attached.classification_id):
                raise ValueError("Aprimo tenant or classification binding changed; reselect the current credential")
            fingerprint = (selected, str(row["owner_id"]), str(row["organization_id"]), str(org), row["token_version"], str(row["updated_at"]), credential.model_dump_json())
        if self._binding is None:
            self._binding = fingerprint
        elif self._binding != fingerprint:
            raise ValueError("Aprimo current credential authority changed during the read")
        self._guard_context()
        return credential

    async def _request(self, method, path, *, params=None, body=None):
        credential = await self._credentials()
        allowed = path in ("/records", "/search/records") or re.fullmatch(r"/(?:record|classification|fielddefinition|fieldgroup)/[0-9a-f]{32}", path)
        if not allowed or method != ("POST" if path == "/search/records" else "GET"):
            raise ValueError("Aprimo route is outside the native metadata contract")
        if method == "POST" and (not isinstance(body, dict) or body.get("logRequest") is not False):
            raise ValueError("Aprimo search logging must remain disabled")
        url = f"https://{credential.tenant}.dam.aprimo.com/api/core{path}"
        async def current_before_send(request):
            await self._credentials()
            if str(request.url).split("?", 1)[0] != url:
                raise ValueError("Aprimo request origin or path changed")
        try:
            with _private_transport():
                async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [current_before_send]}) as client:
                    async with client.stream(method, url, params=params, json=body, headers={
                            "Authorization": "Bearer " + credential.access_token,
                            "API-VERSION": "1", "Accept": "application/json",
                    }) as response:
                        code = response.status_code
                        if code != 200:
                            labels = {401: "token rejected", 403: "resource permission denied", 404: "selected resource unavailable", 429: "rate limit reached", 201: "search acknowledged without a documented result"}
                            raise ValueError(f"Aprimo {labels.get(code, 'metadata request rejected')} (HTTP {code}); no automatic retry")
                        chunks = []; size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 4 * 1024 * 1024:
                                raise ValueError("Aprimo response exceeds the native metadata bound")
                            chunks.append(chunk)
                            self._guard_context()
                        payload = b"".join(chunks)
            await self._credentials()
        except httpx.HTTPError:
            raise ValueError("Aprimo metadata request did not complete; no automatic retry") from None
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("Aprimo returned a non-JSON metadata response") from None
        _refuses_secret(result, credential.access_token)
        return result

    async def _root(self, expected):
        data = await self._request("GET", "/classification/" + expected)
        if _project(data, "classification")["id"] != expected:
            raise ValueError("Aprimo returned another classification")
        return data

    async def _membership(self, root_id, record_id):
        body = {"searchExpression": {"expression": "DirectClassification.Id = @Root AND Id = @Record", "namedParameters": {"Root": root_id, "Record": record_id}}, "logRequest": False}
        data = await self._request("POST", "/search/records", params={"page": 1, "pageSize": 2}, body=body)
        items = _items(data)
        if len(items) != 1 or _uuid(items[0]["id"]) != record_id:
            raise ValueError("Exact current classification membership is unproven; record detail refused")

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not hasattr(self, "_start_context"):
            _raw_guard(self.node_data); self._start_context = self._context(); self._binding = None
        config = self.config.config
        if any(_pending(v) for v in config.model_dump().values()):
            raise ValueError("Resolve Aprimo operation references before execution")
        credential = await self._credentials(); bound = credential.classification_id
        if config.classification_id is not None and config.classification_id != bound:
            raise ValueError("Operation classification differs from the credential-bound resource")
        root = await self._root(bound)
        op = config.operation
        if op == "get_classification":
            result = _project(root, "classification", config.include_names)
        elif op in ("list_registered_fields", "list_registered_field_groups"):
            key, id_key = ("registeredFields", "fieldId") if op == "list_registered_fields" else ("registeredFieldGroups", "fieldGroupId")
            ids = _registered(root, key, id_key)
            result = {"classification_id": bound, "items": [{"id": v} for v in (ids or [])[:config.limit]], "registration_unknown": ids is None, "locally_truncated": ids is not None and len(ids) > config.limit, "completion_unknown": ids is None or len(ids) > config.limit}
        elif op in ("get_field_definition", "get_field_group"):
            is_field = op == "get_field_definition"
            key, id_key = ("registeredFields", "fieldId") if is_field else ("registeredFieldGroups", "fieldGroupId")
            selected = config.field_id if is_field else config.field_group_id
            ids = _registered(root, key, id_key)
            if ids is None or selected not in ids:
                raise ValueError("Selected schema ID is not currently registered on the bound classification")
            data = await self._request("GET", ("/fielddefinition/" if is_field else "/fieldgroup/") + selected)
            result = _project(data, "field" if is_field else "group", config.include_names)
            if result["id"] != selected:
                raise ValueError("Aprimo returned another schema resource")
            final_root = await self._root(bound)
            if selected not in (_registered(final_root, key, id_key) or []):
                raise ValueError("Aprimo schema registration changed during the read")
        elif op == "get_record":
            await self._membership(bound, config.record_id)
            data = await self._request("GET", "/record/" + config.record_id)
            result = _project(data, "record", config.include_names)
            if result["id"] != config.record_id:
                raise ValueError("Aprimo returned another record")
            await self._membership(bound, config.record_id)
        else:
            if op == "list_records":
                data = await self._request("GET", "/records", params={"skip": config.skip, "take": config.take, "filter": f"DirectClassification.Id = '{bound}'"})
                paging = ("offset", "limit"); cap = config.take
            elif op == "search_records":
                clauses = ["DirectClassification.Id = @Root"]; parameters = {"Root": bound}
                for field, value, name, operator in (("Status", config.status, "Status", "="), ("ContentType", config.content_type, "Type", "="), ("Title", config.title_contains, "Title", "CONTAINS")):
                    if value is not None:
                        clauses.append(f"{field} {operator} @{name}"); parameters[name] = value
                body = {"searchExpression": {"expression": " AND ".join(clauses), "namedParameters": parameters}, "logRequest": False}
                data = await self._request("POST", "/search/records", params={"page": config.page, "pageSize": config.page_size}, body=body)
                paging = ("page", "pageSize"); cap = config.page_size
            else:
                raise ValueError("Unsupported Aprimo metadata operation")
            items = _items(data)
            result = {"classification_id": bound, "items": [_project(v, "record", config.include_names) for v in items[:cap]], "returned_count": min(len(items), cap), "locally_truncated": len(items) > cap, "completion_unknown": True}
            if op == "search_records":
                result["total_count_is_approximate"] = True
            else:
                result["total_count_accuracy"] = "unspecified"
            for key in ("totalCount", *paging):
                if key in data:
                    if type(data[key]) is not int or data[key] < 0:
                        raise ValueError("Aprimo returned invalid route-specific pagination")
                    result[key] = data[key]
            await self._root(bound)
        await self._credentials()
        return {"status": "success", "data": result}
