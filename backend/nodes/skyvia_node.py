"""Closed Skyvia management metadata reads, scoped to supplied workspace IDs.

Accessible workspace resources are evidence of reachability and visibility, not
an authenticated human principal, account ownership, or permission introspection.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.skyvia_credentials import fetch_snapshot, fetch_primary_org
from utils.ssrf import guarded_async_client

ROOT = "https://api.skyvia.com/v1"
TYPE = "skyvia_api_token"
MAX_BYTES = 2 * 1024 * 1024
INT32_MAX = 2147483647
MAX_WORKSPACES = 1000
PICKER_TAKE = 50
PICKER_MAX_SKIP = 450
KINDS = {"connection_id": "connections", "integration_id": "integrations", "backup_id": "backups", "automation_id": "automations"}
OPERATIONS = {"list_workspaces", "get_workspace", "list_connections", "get_connection", "list_integrations", "get_integration", "list_backups", "get_backup", "list_automations", "get_automation"}


def identifier(value):
    # Socket/editor option values are strings. Admit exact decimal IDs only.
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= INT32_MAX:
        raise ValueError("Supply a nonnegative int32 Skyvia resource ID")
    return value


ID = Annotated[StrictInt, BeforeValidator(identifier), Field(ge=0, le=INT32_MAX)]


def metadata_text(value, *, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Skyvia returned malformed metadata text")
    return value


class SkyviaAPITokenCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.skyvia.com/account-management/api-settings.html"})
    credential_type: Literal["skyvia_api_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="API Token", description="Supplied Skyvia API token, sent as the raw Authorization header to api.skyvia.com. Do not add Bearer. No token exchange or automatic renewal.", json_schema_extra={"ui:widget": "password"})
    workspace_ids: list[ID] = Field(..., min_length=1, max_length=50, title="Allowed Workspace IDs", description="Explicit workspace IDs this node may read. Protected available-workspace membership is checked on every call; visibility does not establish ownership or roles.")

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("api_token", mode="before")
    @classmethod
    def opaque_token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the raw opaque Skyvia token without whitespace or an authorization prefix")
        return value

    @field_validator("workspace_ids")
    @classmethod
    def unique_workspaces(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Supply unique allowed Skyvia workspace IDs")
        return value


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Skyvia API token credential")
    try:
        return SkyviaAPITokenCredential.model_validate({k: v for k, v in data.items() if k not in {"_skyvia_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Skyvia credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, tuple(value.workspace_ids), value.api_token


async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Skyvia credentials require a caller")
    from utils.database_pool import get_native_pool
    from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
    from utils.encryption import get_encryption
    pool = pool or get_native_pool()
    if organization_id is None:
        organization_id = await fetch_primary_org(pool, user_id)
    row = await fetch_snapshot(pool, credential_id, user_id, organization_id)
    if row is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if owner and str(owner) != str(user_id) and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            row = await fetch_snapshot(pool, credential_id, owner, organization_id, workflow_id=workflow_id)
    if row is None or row["revoked_at"] is not None or row["credential_type"] != TYPE or not row["owner_id"] or type(row["token_version"]) is not int or row["token_version"] < 0:
        raise ValueError("Skyvia credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Skyvia credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Skyvia saved credential type does not match its row")
    return guard(data), str(row["owner_id"]), row["token_version"]


@dataclass(repr=False)
class Reader:
    credential_id: Any
    user_id: Any
    organization_id: Any = None
    workflow_id: Any = None
    pool: Any = None
    anchor: Any = field(default=None, repr=False)
    expected: Any = field(default=None, repr=False)

    async def read(self):
        value, owner, version = await current(self.credential_id, self.user_id, self.organization_id, self.workflow_id, pool=self.pool)
        if self.expected is not None and authority(value) != self.expected:
            raise ValueError("Skyvia cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Skyvia saved credential changed during this call; inspect before retrying")
        self.anchor = binding
        return value


def op(value, title, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def resource(name):
    return {"x-resource-type": "skyvia_" + name.removesuffix("_id"), "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, **({"depends_on": ["workspace_id"]} if name != "workspace_id" else {})}}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to workspace/resource names. IDs and documented type flags are returned by default; names may contain business or personal data.")


class Workspace(Input):
    workspace_id: ID = Field(..., title="Workspace", json_schema_extra=resource("workspace_id"))


class Page(Workspace):
    take: Annotated[StrictInt, Field(ge=1, le=100)] = Field(20, title="Page Size", description="Documented take parameter; locally limited to1..100. Provider maximum is not inferred.")
    skip: Annotated[StrictInt, Field(ge=0, le=10000)] = Field(0, title="Skip", description="Documented number of resources to skip; locally limited to10000. Pagination is not a stable snapshot.")


class ListWorkspaces(Input):
    operation: Literal["list_workspaces"] = op("list_workspaces", "List Allowed Accessible Workspaces", "Workspaces")


class GetWorkspace(Workspace):
    operation: Literal["get_workspace"] = op("get_workspace", "Get Workspace Metadata", "Workspaces")


class ListConnections(Page):
    operation: Literal["list_connections"] = op("list_connections", "List Connection Metadata", "Connections")


class GetConnection(Workspace):
    operation: Literal["get_connection"] = op("get_connection", "Get Connection Metadata", "Connections")
    connection_id: ID = Field(..., title="Connection", json_schema_extra=resource("connection_id"))


class ListIntegrations(Page):
    operation: Literal["list_integrations"] = op("list_integrations", "List Integration Metadata", "Integrations")


class GetIntegration(Workspace):
    operation: Literal["get_integration"] = op("get_integration", "Get Integration Metadata", "Integrations")
    integration_id: ID = Field(..., title="Integration", json_schema_extra=resource("integration_id"))


class ListBackups(Page):
    operation: Literal["list_backups"] = op("list_backups", "List Backup Metadata", "Backups")


class GetBackup(Workspace):
    operation: Literal["get_backup"] = op("get_backup", "Get Backup Metadata", "Backups")
    backup_id: ID = Field(..., title="Backup", json_schema_extra=resource("backup_id"))


class ListAutomations(Page):
    operation: Literal["list_automations"] = op("list_automations", "List Automation Metadata", "Automations")


class GetAutomation(Workspace):
    operation: Literal["get_automation"] = op("get_automation", "Get Automation Metadata", "Automations")
    automation_id: ID = Field(..., title="Automation", json_schema_extra=resource("automation_id"))


Config = Annotated[Union[ListWorkspaces, GetWorkspace, ListConnections, GetConnection, ListIntegrations, GetIntegration, ListBackups, GetBackup, ListAutomations, GetAutomation], Field(discriminator="operation")]


class SkyviaNodeConfig(NodeConfig[Config, SkyviaAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self):
        return "<private Skyvia authorization header>"

    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Skyvia metadata field")
        result[key] = value
    return result


def invalid_number(_value):
    raise ValueError("Nonfinite Skyvia metadata number")


async def request(value, path, *, params=None, reader=None):
    query = params or {}
    if path == "/workspaces":
        allowed = set()
    else:
        match = re.fullmatch(r"/workspaces/(0|[1-9][0-9]{0,9})(?:/(connections|integrations|backups|automations)(?:/(0|[1-9][0-9]{0,9}))?)?", path)
        if match is None or identifier(match[1]) not in value.workspace_ids:
            raise ValueError("Skyvia route is outside the saved workspace scope")
        if match[3] is not None:
            identifier(match[3])
        allowed = {"take", "skip"} if match[2] is not None and match[3] is None else set()
    if set(query) != allowed:
        raise ValueError("Unsupported Skyvia metadata query")
    if query and (type(query["take"]) is not int or not 1 <= query["take"] <= 100 or type(query["skip"]) is not int or not 0 <= query["skip"] <= 10000):
        raise ValueError("Supply bounded documented Skyvia take/skip pagination")
    if reader:
        value = await reader.read()
    try:
        try:
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", ROOT + path, params=query, headers=PrivateHeaders({"Authorization": value.api_token, "Accept": "application/json", "Cache-Control": "no-store"})) as response:
                    if response.status_code != 200:
                        raise ValueError("Skyvia metadata read refused or service unavailable")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Skyvia returned an unsupported metadata format")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ValueError("Skyvia metadata exceeds the local2MiB bound")
            return json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
        except Exception:
            raise ValueError("Skyvia metadata read could not be established; inspect token, permissions, entitlement or service availability") from None
    finally:
        if reader:
            await reader.read()


def rows(items, *, maximum):
    if not isinstance(items, list) or len(items) > maximum or any(not isinstance(v, dict) for v in items):
        raise ValueError("Malformed or oversized Skyvia metadata array")
    # Response IDs must really be JSON integers, rather than coerced editor strings.
    ids = [v.get("id") for v in items]
    if any(type(v) is not int or identifier(v) != v for v in ids) or len(set(ids)) != len(ids):
        raise ValueError("Skyvia returned malformed or repeated resource identifiers")
    return items


def page(payload, take):
    if not isinstance(payload, dict) or type(payload.get("hasMore")) is not bool:
        raise ValueError("Skyvia list requires the documented data/hasMore envelope")
    items = rows(payload.get("data"), maximum=take)
    if payload["hasMore"] and not items:
        raise ValueError("Skyvia reported more resources without a progressing page")
    return items, payload["hasMore"]


def projection(row, kind, *, include_names=False):
    if not isinstance(row, dict) or type(row.get("id")) is not int:
        raise ValueError("Malformed Skyvia metadata record")
    result = {"id": identifier(row["id"])}
    text_fields = {"connections": ("connector", "type"), "integrations": ("type",), "automations": ("triggerType",)}.get(kind, ())
    bool_fields = {"workspaces": ("isPersonal",), "integrations": ("scheduled",), "backups": ("scheduled",)}.get(kind, ())
    for key in text_fields:
        if key in row:
            result[key] = metadata_text(row[key], limit=128)
    for key in bool_fields:
        if key in row:
            if type(row[key]) is not bool:
                raise ValueError("Malformed Skyvia metadata flag")
            result[key] = row[key]
    if include_names and "name" in row:
        result["name"] = metadata_text(row["name"])
    return result


def reader_from(data):
    reader = data.get("_skyvia_reader")
    if reader is not None and not isinstance(reader, Reader):
        raise ValueError("Invalid Skyvia stored-credential reader")
    return reader


class SkyviaNode(WorkflowNode):
    integration_type = "automation-skyvia"
    credential_provider_labels = {"skyvia": "Skyvia Account"}
    auto_select_credential = False
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="allowed accessible workspace IDs", proves="account", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return SkyviaNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            try:
                config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
            except ValueError as error:
                return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return cls._bind_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @staticmethod
    def _bind_credential(credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if credential_id:
            reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
            return {**value.model_dump(), "_skyvia_reader": reader}
        return value.model_dump()

    @staticmethod
    async def _catalog(value, reader):
        items = rows(await request(value, "/workspaces", reader=reader), maximum=MAX_WORKSPACES)
        ids = {row["id"] for row in items}
        if not set(value.workspace_ids) <= ids:
            raise ValueError("Saved workspace scope is absent from Skyvia's current available-workspace catalog")
        return [row for row in items if row["id"] in value.workspace_ids]

    @staticmethod
    async def _workspace(value, workspace_id, reader):
        workspace_id = identifier(workspace_id)
        if workspace_id not in value.workspace_ids:
            raise ValueError("Workspace is outside the credential's saved scope")
        row = await request(value, f"/workspaces/{workspace_id}", reader=reader)
        item = projection(row, "workspaces")
        if item["id"] != workspace_id:
            raise ValueError("Skyvia returned a different scoped workspace")
        return row

    @staticmethod
    async def _member(value, workspace_id, kind, resource_id, reader):
        resource_id = identifier(resource_id)
        seen = set()
        skip = 0
        for _page in range(10):
            items, more = page(await request(value, f"/workspaces/{workspace_id}/{kind}", params={"take": 100, "skip": skip}, reader=reader), 100)
            ids = {row["id"] for row in items}
            if seen & ids:
                raise ValueError("Skyvia resource membership changed or repeated while paging")
            seen |= ids
            if resource_id in ids:
                return
            if not more:
                raise ValueError("Resource is absent from the selected workspace's current resource catalog")
            skip += len(items)
        raise ValueError("Skyvia resource membership exceeds ten bounded pages; choose a directly visible resource after inspection")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"workspace_id", *KINDS}:
            return {"options": [], "next_page_token": None}
        value = guard(credential_data); reader = reader_from(credential_data)
        context = context or {}; search = search or ""
        if not isinstance(context, dict) or not isinstance(search, str) or len(search) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in search):
            raise ValueError("Supply bounded Skyvia picker context/search")
        if reader and reader.workflow_id is None:
            reader.workflow_id = context.get("_workflow_id")
        workspace_id = identifier(context.get("workspace_id")) if field_name != "workspace_id" else None
        binding = {"field": field_name, "workspace": workspace_id, "search": search, "take": PICKER_TAKE}
        key = json.dumps(authority(value), separators=(",", ":")).encode()
        skip, seen, pages = 0, [], 0
        if page_token is not None:
            try:
                if field_name == "workspace_id" or not isinstance(page_token, str) or len(page_token) > 16384:
                    raise ValueError()
                encoded, signature = page_token.rsplit(".", 1); saved = json.loads(encoded)
                if not isinstance(saved, dict) or set(saved) != {"binding", "skip", "seen", "pages"} or saved["binding"] != binding or type(saved["skip"]) is not int or not 0 < saved["skip"] <= PICKER_MAX_SKIP or type(saved["pages"]) is not int or not 1 <= saved["pages"] < 10 or not isinstance(saved["seen"], list) or len(saved["seen"]) != saved["skip"] or any(type(v) is not int or identifier(v) != v for v in saved["seen"]) or len(set(saved["seen"])) != len(saved["seen"]) or not hmac.compare_digest(signature, hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()):
                    raise ValueError()
                skip, seen, pages = saved["skip"], saved["seen"], saved["pages"]
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ValueError("Skyvia continuation no longer matches its credential, workspace, field or search") from None
        try:
            catalog = await cls._catalog(value, reader)
            if field_name == "workspace_id":
                items, more = catalog, False
            else:
                await cls._workspace(value, workspace_id, reader)
                items, more = page(await request(value, f"/workspaces/{workspace_id}/{KINDS[field_name]}", params={"take": PICKER_TAKE, "skip": skip}, reader=reader), PICKER_TAKE)
            ids = [row["id"] for row in items]
            if set(seen) & set(ids):
                raise ValueError("Skyvia picker resource inventory changed or repeated while paging")
            next_token = None
            if more:
                next_skip = skip + len(ids)
                if next_skip > PICKER_MAX_SKIP or pages + 1 >= 10:
                    raise ValueError("Skyvia picker exceeds ten bounded pages; use an exact scoped ID after inspection")
                encoded = json.dumps({"binding": binding, "skip": next_skip, "seen": seen + ids, "pages": pages + 1}, sort_keys=True, separators=(",", ":"))
                next_token = encoded + "." + hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
            selected = [row for row in items if search.casefold() in str(row["id"]).casefold()]
            return {"options": [{"value": str(row["id"]), "label": str(row["id"])} for row in selected], "next_page_token": next_token}
        finally:
            if reader:
                await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = self._bind_credential(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), reader_from(data)
        try:
            catalog = await self._catalog(value, reader)
            if cfg.operation == "list_workspaces":
                items = [projection(row, "workspaces", include_names=cfg.include_names) for row in catalog]
                return {"items": items, "count": len(items), "total": None, "complete": None, "has_more": None, "pagination": "not_documented", "evidence": "protected_accessible_workspace_resources", "principal_identity_verified": False, "account_ownership_verified": False, "provider_permissions_verified": False}
            workspace = await self._workspace(value, cfg.workspace_id, reader)
            if cfg.operation == "get_workspace":
                return projection(workspace, "workspaces", include_names=cfg.include_names)
            kind = next((kind for field, kind in KINDS.items() if cfg.operation in {"list_" + kind, "get_" + field.removesuffix("_id")}), None)
            if kind is None:
                raise ValueError("Unsupported Skyvia metadata operation")
            path = f"/workspaces/{cfg.workspace_id}/{kind}"
            if cfg.operation.startswith("list_"):
                raw_items, more = page(await request(value, path, params={"take": cfg.take, "skip": cfg.skip}, reader=reader), cfg.take)
                items = [projection(row, kind, include_names=cfg.include_names) for row in raw_items]
                next_skip = cfg.skip + len(items)
                return {"items": items, "count": len(items), "workspace_id": cfg.workspace_id, "take": cfg.take, "skip": cfg.skip, "has_more": more, "next_skip": next_skip if more and next_skip <= 10000 else None, "local_limit_reached": bool(more and next_skip > 10000), "total": None, "complete": None}
            field_name = next(field for field, plural in KINDS.items() if plural == kind)
            resource_id = getattr(cfg, field_name)
            await self._member(value, cfg.workspace_id, kind, resource_id, reader)
            item = projection(await request(value, path + f"/{resource_id}", reader=reader), kind, include_names=cfg.include_names)
            if item["id"] != resource_id:
                raise ValueError("Skyvia returned a different scoped resource")
            return {**item, "workspace_id": cfg.workspace_id}
        finally:
            if reader:
                await reader.read()
