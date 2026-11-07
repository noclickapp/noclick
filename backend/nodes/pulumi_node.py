"""Pulumi Cloud stack metadata only; no update/state/config/ESC/control routes."""
import json
import re
from dataclasses import dataclass
from uuid import UUID
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

from repositories.credentials import credential_access_predicate
from repositories.organization import OrgRepo


class PulumiAuthorityRepo:
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
class PulumiCredentialAnchor:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: str | None
    current_organization: bool
    workflow_id: str | None
    owner_id: str
    credential_type: str
    token_version: int


class PulumiCredentialStore:
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
        repo = PulumiAuthorityRepo(self.pool)
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
                or row['credential_type'] != 'pulumi_access_token'
                or type(row['token_version']) is not int or row['token_version'] < 1):
            raise ValueError('Pulumi saved credential unavailable under current authority')
        resolved = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool, org_id=org, workflow_id=self.workflow_id,
        )
        if resolved is None:
            raise ValueError('Pulumi saved credential unavailable under current authority')
        data = get_encryption().decrypt_credential(row['credential'])
        data['credential_type'] = row['credential_type']
        data = self.validate(data)
        if data != self.validate(resolved):
            raise ValueError('Pulumi saved credential changed during resolution')
        self.current = PulumiCredentialAnchor(
            self.credential_id, self.user_id, str(principal), org, current_org,
            self.workflow_id, str(row['owner_id']), row['credential_type'], row['token_version'],
        )
        return {**data, 'token_version': row['token_version']}


HOST, MAX_BYTES, MAX_ROWS = "https://api.pulumi.com", 2 * 1024 * 1024, 100
KINDS = {"update", "preview", "refresh", "rename", "destroy", "import", "resource-import", "Pupdate", "Prefresh", "Pdestroy", "Pimport", "Prename"}


def _text(value, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _name(value):
    value = _text(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", value): raise ValueError("Use one bounded routing name, not a path or URL")
    return value


def _cursor(value): return None if value is None else _text(value, 2048)


def _integer(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1: raise ValueError("Expected an exact nonnegative metadata integer")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected the published JSON object")
    return value


def _array(value, bound=MAX_ROWS):
    if not isinstance(value, list) or len(value) > bound: raise ValueError("Expected the bounded documented array")
    return value


class PulumiAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Pulumi Cloud Access Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://www.pulumi.com/docs/reference/cloud-rest-api/", "x-credential-instructions": "Supply existing personal/organization/team access token, explicit supplied organization routing name and optional protected project restriction. Token access proves no actor/membership/ownership. Lowercase token authorization, Pulumi v8 Accept and JSON Content-Type are fixed. No token issue/exchange/CLI/SDK/selfhost fallback. Permissions and entitlement remain unknown."})
    credential_type: Literal["pulumi_access_token"] = Field("pulumi_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing Pulumi Access Token", json_schema_extra={"ui:widget": "password"})
    organization: str = Field(..., title="Supplied Organization Routing Name")
    project: str | None = Field(None, title="Optional Protected Project Restriction")
    @field_validator("access_token", mode="before")
    @classmethod
    def secret(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply raw token without authorization prefix or whitespace")
        return clean_secret(value, field_name="Pulumi access token")
    @field_validator("organization", mode="before")
    @classmethod
    def org(cls, value): return _name(value)
    @field_validator("project", mode="before")
    @classmethod
    def optional_project(cls, value): return None if value is None else _name(value)


def _credential(raw):
    if isinstance(raw, PulumiAccessTokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "pulumi_access_token": raise ValueError("Select the actual Pulumi Cloud access token family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) - {"credential_type", "access_token", "organization", "project"}: raise ValueError("Unsupported raw token/organization/project binding; no host or refresh grant")
    try: return PulumiAccessTokenCredential.model_validate(raw)
    except Exception: raise ValueError("Pulumi Cloud token/organization/project binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store):
        super().__init__(data); self.store, self.anchor = store, self.identity(store.current)
    @staticmethod
    def identity(row): return tuple(getattr(row, name) for name in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))
    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("Pulumi current token/organization/project or saved authority changed") from None
    def __repr__(self): return "<Pulumi current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Pulumi Cloud Metadata", "x-is-trigger": False})
def _project_field(default): return Field(default, title="Project Routing Name", description="Must match any credential project restriction. Discovery requires names opt-in; manual known names are supported.", json_schema_extra={"x-resource-type": "project_name", "x-dynamic-options": {"field_name": "project_name", "depends_on": ["include_names"], "allow_custom": True, "auto_select_sole_option": False}})


class _Catalog(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    project_name: str | None = _project_field(None)
    include_names: bool = Field(False, strict=True, title="Include Stack and Reference Names", description="Opt in to organization/project/stack names and stack logical ID output and discovery. Numeric metadata remains the default.")
    max_results: int = Field(20, strict=True, ge=1, le=MAX_ROWS, title="Maximum Catalog Results", description="Documented maxResults parameter; local1–100 bound, not a vendor maximum.")
    continuation_token: str | None = Field(None, title="Explicit Catalog Continuation Token", description="Opaque documented input, never a URL. For selected-stack operations this chooses the catalog page used for ancestry.")
    @field_validator("project_name", mode="before")
    @classmethod
    def validate_project(cls, value): return None if value is None else _name(value)
    @field_validator("continuation_token", mode="before")
    @classmethod
    def validate_cursor(cls, value): return _cursor(value)


class _Stack(_Catalog):
    project_name: str = _project_field(...)
    stack_name: str = Field(..., title="Stack Routing Name", json_schema_extra={"x-resource-type": "stack_name", "x-dynamic-options": {"field_name": "stack_name", "depends_on": ["project_name", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("stack_name", mode="before")
    @classmethod
    def validate_stack(cls, value): return _name(value)


class PulumiStacksConfig(_Catalog):
    operation: Literal["list_stacks"] = _op("list_stacks", "Read Protected Stack Catalog Metadata")
class PulumiStackConfig(_Stack):
    operation: Literal["get_stack"] = _op("get_stack", "Get Stack Metadata")
class PulumiResourceCountConfig(_Stack):
    operation: Literal["get_resource_count"] = _op("get_resource_count", "Get Stack Resource Count Metadata")
class PulumiDownstreamReferencesConfig(_Stack):
    operation: Literal["list_downstream_references"] = _op("list_downstream_references", "Read Same-Organization Downstream Reference Metadata")


PulumiOperation = Annotated[Union[PulumiStacksConfig, PulumiStackConfig, PulumiResourceCountConfig, PulumiDownstreamReferencesConfig], Field(discriminator="operation")]
class PulumiNodeConfig(NodeConfig[PulumiOperation, PulumiAccessTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _stack_witness(raw, organization, project=None, stack=None):
    row = _object(raw); org, proj, name = (_name(row.get(field)) for field in ("orgName", "projectName", "stackName"))
    if org != organization or (project is not None and proj != project) or (stack is not None and name != stack): raise ValueError("Stack crosses current protected organization/project/name")
    if row.get("id") != f"{org}/{proj}/{name}": raise ValueError("Returned stack logical ID differs from its routing ancestry")
    return org, proj, name, row["id"]


def _projected_stack(raw, names=False, detail=False):
    row = _object(raw); out = {"resource_type": "stack" if detail else "stack_summary"}
    for field in (("version",) if detail else ("lastUpdate", "resourceCount")):
        if detail or field in row: out[field] = _integer(row.get(field))
    if detail and "currentOperation" in row:
        if row["currentOperation"] is None: out["currentOperation"] = None
        else:
            operation = _object(row["currentOperation"]); kind = operation.get("kind")
            if not isinstance(kind, str) or kind not in KINDS: raise ValueError("Unsupported documented operation kind")
            out["currentOperation"] = {"kind": kind, "started": _integer(operation.get("started"))}
    if names: out.update({field: row[field] for field in ("id", "orgName", "projectName", "stackName")})
    return out


def _pagination(raw):
    if "continuationToken" not in raw: return {"has_more": None, "next_page_token": None, "pagination_complete": None}
    if raw["continuationToken"] is None: return {"has_more": False, "next_page_token": None, "pagination_complete": True}
    return {"has_more": True, "next_page_token": _cursor(raw["continuationToken"]), "pagination_complete": False}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    def project(self):
        selected = self.config.project_name or self.key.project
        if self.key.project is not None and selected != self.key.project: raise ValueError("Selected project differs from credential restriction")
        return selected
    async def request(self, kind):
        project = self.project(); params = {}
        if kind == "catalog":
            path = "/api/user/stacks"; params = {"organization": self.key.organization, "maxResults": str(self.config.max_results)}
            if project is not None: params["project"] = project
            if self.config.continuation_token is not None: params["continuationToken"] = self.config.continuation_token
        elif kind in {"stack", "count", "references"}:
            path = "/api/stacks/" + "/".join(quote(_name(value), safe="") for value in (self.key.organization, project, self.config.stack_name))
            path += {"stack": "", "count": "/resources/count", "references": "/downstreamreferences"}[kind]
        else: raise ValueError("Closed native metadata route required")
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", HOST + path, params=params, headers={"Authorization": "token " + key.access_token, "Accept": "application/vnd.pulumi+8", "Content-Type": "application/json"}) as response:
                    self.status = response.status_code; content_type = response.headers.get("content-type", ""); body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("Pulumi response exceeds local bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200: raise _ProviderError(self.error("Pulumi protected read could not be verified. HTTP404 is missing-or-invisible; permissions/entitlement remain unknown. Private provider text omitted; no retry"))
            if not any(value in content_type.lower() for value in ("application/json", "application/vnd.pulumi+")): raise ValueError("Expected the documented JSON representation")
            return json.loads(body)
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("Pulumi transport outcome unknown; no retry")) from None
    async def catalog(self):
        wrapper = _object(await self.request("catalog")); rows = _array(wrapper.get("stacks"), self.config.max_results)
        witnesses = [_stack_witness(row, self.key.organization, self.project()) for row in rows]
        if len({value[3] for value in witnesses}) != len(witnesses): raise ValueError("Duplicate protected logical stack IDs")
        return rows, _pagination(wrapper)
    async def parent(self):
        rows, _ = await self.catalog()
        if not any(row["projectName"] == self.project() and row["stackName"] == self.config.stack_name for row in rows): raise ValueError("Selected stack not established on current protected page; no global absence claim")
        detail = _object(await self.request("stack")); _stack_witness(detail, self.key.organization, self.project(), self.config.stack_name)
        _integer(detail.get("version"))
        return detail


class PulumiNode(WorkflowNode):
    integration_type = "automation-pulumi"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_stacks", noun="Pulumi Cloud protected supplied-organization stack catalog", proves="reachability")
    edit_examples = ["Read numeric stack metadata in my supplied Pulumi organization without names or config", "Read a known stack resource count and same-organization downstream versions without following references"]
    @classmethod
    def get_config_model(cls): return PulumiNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
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
        store = PulumiCredentialStore(pool, user_id, credential_id, validate=_stored, organization_id=organization, workflow_id=workflow_id)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("Pulumi saved credential unavailable under current authority") from None
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Pulumi literal token/organization/project family unsupported"}
        if validation_context is None: return {"valid": True, "provider_verified": False}
        await validation_context.revalidate(); result = await validation_context.run_operation("list_stacks"); await validation_context.revalidate()
        if result.get("status") == "success" and result.get("protected_reachability_verified") is True: return {"valid": True, "provider_verified": True}
        return {"valid": None, "error": result.get("error", "Scoped stack access could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            session.project()
            if config.operation == "list_stacks":
                rows, pagination = await session.catalog()
                out = {"data": [_projected_stack(row, config.include_names) for row in rows], "returned_count": len(rows), **pagination}
            elif config.operation in {"get_stack", "get_resource_count", "list_downstream_references"}:
                parent = await session.parent()
                if config.operation == "get_stack": out = {"data": _projected_stack(parent, config.include_names, detail=True)}
                elif config.operation == "get_resource_count":
                    row = _object(await session.request("count")); version = _integer(row.get("version"))
                    if version != parent["version"]: raise ValueError("Resource count version differs from current stack detail")
                    out = {"data": {"resource_type": "stack_resource_count", "resourceCount": _integer(row.get("resourceCount")), "version": version}}
                else:
                    rows = _array(_object(await session.request("references")).get("referencedStacks")); data = []
                    for raw in rows:
                        row = _object(raw); org, project, name = (_name(row.get(field)) for field in ("organization", "routingProject", "name")); version = _integer(row.get("version"))
                        if org != session.key.organization: continue
                        item = {"resource_type": "downstream_stack_reference", "version": version}
                        if config.include_names: item.update(organization=org, routingProject=project, name=name)
                        data.append(item)
                    out = {"data": data, "provider_returned_count": len(rows), "same_organization_returned_count": len(data), "provider_count_scope": "bounded_response_unspecified_completion", "local_filter": "same_supplied_organization", "referenced_resource_access_proven": False, "pagination_complete": None}
                status = session.status; current = await session.parent()
                if config.operation == "get_resource_count" and current["version"] != out["data"]["version"]: raise ValueError("Stack version changed around resource count")
                session.status = status
            else: raise ValueError("Closed native operation required")
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "organization_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current credentials/stack ancestry/version or bounded published metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        key = _credential(credential_data); context = context or {}
        if field_name not in {"project_name", "stack_name"} or context.get("include_names") is not True: raise ValueError("Enable explicit names discovery or enter known routing names manually")
        project = context.get("project_name")
        if project is not None: project = _name(project)
        if key.project is not None and project is not None and project != key.project: raise ValueError("Picker crosses credential project restriction")
        if field_name == "stack_name" and project is None: raise ValueError("Select current project before stack discovery")
        if search is not None: _text(search, 100)
        config = PulumiStacksConfig(project_name=project, include_names=True, max_results=context.get("max_results", 20), continuation_token=page_token if page_token is not None else context.get("continuation_token"))
        result = await cls._dispatch(credential_data, config)
        if result.get("status") != "success": raise ValueError(result["error"])
        values = sorted({row["projectName"] if field_name == "project_name" else row["stackName"] for row in result["data"]})
        return {"options": [{"value": value, "label": value, "metadata": {"resource_type": field_name.removesuffix("_name"), "protected_catalog": True}} for value in values if not search or search.casefold() in value.casefold()], "has_more": result["has_more"], "next_page_token": result["next_page_token"], "pagination_complete": result["pagination_complete"]}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        credential = await self._freshen_for_execution(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
