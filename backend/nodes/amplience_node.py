"""Amplience Content Management metadata on fixed declared GET routes.

Supplied PAT/access tokens only. Parent membership is read from closed catalogs;
HAL capability links and user content never enter native output or request routing.
"""
import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE, MAX_BYTES = "https://api.amplience.net/v2/content", 2 * 1024 * 1024


def _text(value, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use bounded Amplience text without control characters")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value): raise ValueError("Use an exact Amplience ID as one safe path segment")
    return value


def _uuid(value):
    if not isinstance(value, str): raise ValueError("Use the exact content item UUID")
    try: canonical = str(UUID(value))
    except (ValueError, TypeError): raise ValueError("Use the exact content item UUID") from None
    if value != canonical: raise ValueError("Use the canonical lowercase content item UUID")
    return value


def _expiry(value):
    if not isinstance(value, str): raise ValueError("Supply the independently known access-token expiry")
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: raise ValueError("Use an actual timezone-aware ISO8601 expiry") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError("Access-token expiry requires a timezone")
    if parsed <= datetime.now(timezone.utc): raise ValueError("Supplied Amplience access token is expired; no token exchange/refresh is implemented")
    return value


def _timestamp(value):
    value = _text(value, 100)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value): raise ValueError("Unsupported published item date-time")
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: raise ValueError("Unsupported published item date-time") from None
    return value


class _Credential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    token: str = Field(..., repr=False, title="Already Issued Token", json_schema_extra={"ui:widget": "password"})
    reference_hub_id: str = Field(..., title="Independently Known Hub ID", description="A protected resource binding, not proof of token principal or organization ownership.")
    @field_validator("token", mode="before")
    @classmethod
    def issued(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply the raw token without a Bearer prefix")
        return clean_secret(value, field_name="Amplience token")
    @field_validator("reference_hub_id", mode="before")
    @classmethod
    def hub(cls, value): return _id(value)


class AmpliencePATCredential(_Credential):
    model_config = ConfigDict(title="Amplience PAT", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://amplience.com/developers/docs/apis/content-management-reference/", "x-credential-instructions": "Supply an existing personal access token and known hub ID. Current docs admit user/organization PATs that do not expire but can be deleted. Bearer header only at api.amplience.net/v2/content. No PAT creation, exchange, refresh or principal/organization discovery. Entitlement and functional/ACL permissions need independent qualification."})
    credential_type: Literal["amplience_pat"] = Field("amplience_pat", json_schema_extra={"ui:hidden": True})


class AmplienceAccessTokenCredential(_Credential):
    model_config = ConfigDict(title="Amplience Access Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://amplience.com/developers/docs/apis/content-management-reference/", "x-credential-instructions": "Supply an already issued client-credentials access token, its independently known timezone-aware expiry and hub ID. Documented issued tokens last 300 seconds. This node never exchanges a client key/secret or refreshes a token; replace an expired saved token through the credential UI. Bearer header only, not a client secret/PAT substitution."})
    credential_type: Literal["amplience_access_token"] = Field("amplience_access_token", json_schema_extra={"ui:hidden": True})
    expires_at: str = Field(..., repr=False, title="Actual Issued Token Expiry (ISO8601)")
    @field_validator("expires_at", mode="before")
    @classmethod
    def expiry(cls, value): return _expiry(value)


AmplienceCredential = Union[AmpliencePATCredential, AmplienceAccessTokenCredential]
_CREDENTIAL = TypeAdapter(Annotated[AmplienceCredential, Field(discriminator="credential_type")])


def _credential(raw):
    if isinstance(raw, (AmpliencePATCredential, AmplienceAccessTokenCredential)): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") not in {"amplience_pat", "amplience_access_token"}: raise ValueError("Select the actual Amplience PAT or supplied access-token family")
    raw = dict(raw)
    # The existing saved-row adapter appends these private row bookkeeping keys.
    # They never establish authority; that comes from store.current after admission.
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved token version")
    raw.pop("token_version", None)
    raw.pop("updated_at", None)
    fields = {"credential_type", "token", "reference_hub_id"} | ({"expires_at"} if raw["credential_type"] == "amplience_access_token" else set())
    if set(raw) - fields: raise ValueError("Unsupported Amplience grant fields; no exchange/refresh/default grant")
    try: return _CREDENTIAL.validate_python(raw)
    except Exception: raise ValueError("Amplience token, current expiry or hub binding is unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


def _op(value, title, category): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})
def _pick(name, parent=None, **kwargs): return Field(..., **kwargs, json_schema_extra={"x-resource-type": name, "x-dynamic-options": {"field_name": name, "allow_custom": True, **({"depends_on": parent} if parent else {})}})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Resource Names", description="Opt in to hub/repository labels, folder names and item labels. Content type settings/labels remain omitted.")


class _Page(_Config):
    page: int = Field(0, strict=True, ge=0, le=10000, title="Zero-based Page")
    size: int = Field(20, strict=True, ge=1, le=100, title="Page Size", description="Published HAL page size maximum 100; one explicit operation page only.")


class _Hub(_Config):
    hub_id: str = _pick("hub_id", title="Credential-bound Hub")
    @field_validator("hub_id", mode="before")
    @classmethod
    def hub(cls, value): return _id(value)


class _Repository(_Hub):
    repository_id: str = _pick("repository_id", "hub_id", title="Repository in Selected Hub")
    @field_validator("repository_id", mode="before")
    @classmethod
    def repository(cls, value): return _id(value)


class AmplienceCheckConnectionConfig(_Config):
    operation: Literal["check_connection"] = _op("check_connection", "Verify Protected Hub Catalog Reachability", "Connection")


class AmplienceListHubsConfig(_Page):
    operation: Literal["list_hubs"] = _op("list_hubs", "Read Accessible Hub Metadata Page", "Hubs")


class AmplienceGetHubConfig(_Hub):
    operation: Literal["get_hub"] = _op("get_hub", "Get Bound Hub Metadata", "Hubs")


class AmplienceListRepositoriesConfig(_Hub, _Page):
    operation: Literal["list_repositories"] = _op("list_repositories", "Read Hub Repository Metadata Page", "Repositories")


class AmplienceGetRepositoryConfig(_Repository):
    operation: Literal["get_repository"] = _op("get_repository", "Get Selected Repository Metadata", "Repositories")


class AmplienceListContentTypesConfig(_Hub, _Page):
    operation: Literal["list_content_types"] = _op("list_content_types", "Read Hub Content Type Metadata Page", "Content Types")
    status: Literal["ACTIVE", "ARCHIVED", "ACTIVE,ARCHIVED"] = Field("ACTIVE,ARCHIVED", title="Documented Content Type Status")


class AmplienceGetContentTypeConfig(_Hub):
    operation: Literal["get_content_type"] = _op("get_content_type", "Get Selected Content Type Metadata", "Content Types")
    content_type_id: str = _pick("content_type_id", "hub_id", title="Content Type in Selected Hub")
    @field_validator("content_type_id", mode="before")
    @classmethod
    def type_id(cls, value): return _id(value)


class AmplienceListContentItemsConfig(_Repository, _Page):
    operation: Literal["list_content_items"] = _op("list_content_items", "Read Repository Item Metadata Page", "Content Items")
    status: Literal["ACTIVE", "ARCHIVED", "DELETED"] = Field("ACTIVE", title="Item Status")


class AmplienceGetContentItemConfig(_Repository):
    operation: Literal["get_content_item"] = _op("get_content_item", "Get Selected Item Metadata", "Content Items")
    content_item_id: str = _pick("content_item_id", "repository_id", title="Content Item in Selected Repository")
    @field_validator("content_item_id", mode="before")
    @classmethod
    def item_id(cls, value): return _uuid(value)


class AmplienceListFoldersConfig(_Repository, _Page):
    operation: Literal["list_folders"] = _op("list_folders", "Read Repository Top-level Folder Metadata Page", "Folders")


class AmplienceGetFolderConfig(_Repository):
    operation: Literal["get_folder"] = _op("get_folder", "Get Selected Top-level Folder Metadata", "Folders")
    folder_id: str = _pick("folder_id", "repository_id", title="Top-level Folder in Selected Repository")
    @field_validator("folder_id", mode="before")
    @classmethod
    def folder_id_value(cls, value): return _id(value)


class AmplienceListSubfoldersConfig(AmplienceGetFolderConfig):
    operation: Literal["list_subfolders"] = _op("list_subfolders", "Read Selected Folder's Initial Child Metadata Page", "Folders")


AmplienceOperation = Annotated[Union[AmplienceCheckConnectionConfig, AmplienceListHubsConfig, AmplienceGetHubConfig, AmplienceListRepositoriesConfig, AmplienceGetRepositoryConfig, AmplienceListContentTypesConfig, AmplienceGetContentTypeConfig, AmplienceListContentItemsConfig, AmplienceGetContentItemConfig, AmplienceListFoldersConfig, AmplienceGetFolderConfig, AmplienceListSubfoldersConfig], Field(discriminator="operation")]


class AmplienceNodeConfig(NodeConfig[AmplienceOperation, AmplienceCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _object(raw):
    if not isinstance(raw, dict): raise ValueError("Unsupported Amplience HAL object")
    return raw


def _project(raw, resource, include_names=False, expected_id=None, repository_id=None):
    row = _object(raw)
    item_id = _uuid(row.get("id")) if resource == "content-items" else _id(row.get("id"))
    if expected_id is not None and expected_id != item_id: raise ValueError("Amplience returned another selected resource")
    out = {"id": item_id, "resource_type": resource}
    if resource in {"content-repositories", "content-types", "content-items"}:
        statuses = {"content-repositories": {"ACTIVE", "DELETED"}, "content-types": {"ACTIVE", "ARCHIVED"}, "content-items": {"ACTIVE", "ARCHIVED", "DELETED"}}[resource]
        if "status" in row:
            if row["status"] not in statuses: raise ValueError("Unsupported Amplience status")
            out["status"] = row["status"]
    if resource == "content-repositories" and "type" in row:
        if row["type"] != "CONTENT": raise ValueError("Unsupported repository type")
        out["type"] = row["type"]
    if resource == "content-items":
        if _id(row.get("contentRepositoryId")) != repository_id: raise ValueError("Content item belongs to another repository")
        out["contentRepositoryId"] = repository_id
        for name in ("version", "lastPublishedVersion", "lastUnpublishedVersion"):
            if name in row:
                if type(row[name]) is not int or row[name] < 0: raise ValueError("Unsupported item version")
                out[name] = row[name]
        for name in ("createdDate", "lastModifiedDate", "lastPublishedDate", "lastUnpublishedDate"):
            if row.get(name) is not None: out[name] = _timestamp(row[name])
        if "publishingStatus" in row:
            if row["publishingStatus"] not in {"NONE", "EARLY", "LATEST", "UNPUBLISHED"}: raise ValueError("Unsupported item publishing status")
            out["publishingStatus"] = row["publishingStatus"]
        if row.get("folderId") is not None: out["folderId"] = _id(row["folderId"])
    if include_names and resource != "content-types":
        for name in {"hubs": ("name", "label"), "content-repositories": ("name", "label"), "content-items": ("label",), "folders": ("name",)}[resource]:
            if name in row: out[name] = _text(row[name])
    return out


def _page(raw, resource, *, page=None, size=None, include_names=False, repository_id=None):
    payload = _object(raw)
    rows = _object(payload.get("_embedded")).get(resource)
    paging = _object(payload.get("page"))
    if not isinstance(rows, list) or len(rows) > 100: raise ValueError("Unsupported Amplience embedded collection")
    values = {}
    for name, minimum in (("number", 0), ("size", 1), ("totalElements", 1), ("totalPages", 1)):
        value = paging.get(name)
        if type(value) is not int or value < minimum: raise ValueError("Unsupported published HAL page fields/minima")
        values[name] = value
    if values["size"] > 100 or values["number"] >= values["totalPages"] or len(rows) > values["size"] or values["totalElements"] < len(rows): raise ValueError("Inconsistent HAL page")
    if page is not None and values["number"] != page: raise ValueError("HAL returned another page")
    # The response schema defines the current page size, not an echo of the
    # requested size. Providers may cap it; never accept an enlarged page.
    if size is not None and values["size"] > size: raise ValueError("HAL returned a larger page size")
    data = [_project(row, resource, include_names, repository_id=repository_id) for row in rows]
    if len({row["id"] for row in data}) != len(data): raise ValueError("Duplicate Amplience IDs")
    more = values["number"] + 1 < values["totalPages"]
    return {"data": data, "page": values, "has_more": more, "next_page": values["number"] + 1 if more else None, "snapshot_stable": False}


def _error(action, message, session):
    return {"status": "error", "action": action, "error": message, "executed": session.attempted, "mutation_attempted": False, **({"http_status": session.status, "status_code": session.status} if session.status is not None else {}), "_halt_downstream": True}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, action):
        self.raw, self.key, self.action = raw, _credential(raw), action
        self.attempted, self.status = False, None
    async def request(self, path, params=None):
        segment = r"[A-Za-z0-9_-]{1,128}"
        allowed = path == "/hubs" or re.fullmatch(r"/hubs/" + segment + r"(?:/(content-repositories|content-types))?", path) or re.fullmatch(r"/content-repositories/" + segment + r"(?:/(content-items|folders))?", path) or re.fullmatch(r"/(content-types|folders)/" + segment + r"(?:/folders)?", path) or re.fullmatch(r"/content-items/[0-9a-f-]{36}", path)
        if not allowed or (path.startswith("/content-types/") and path.endswith("/folders")): raise ValueError("Unsupported Amplience route")
        try:
            key = _credential(self.raw)
            self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", BASE + path, params=params, headers={"Authorization": "Bearer " + key.token, "Accept": "application/hal+json"}) as response:
                    self.status = response.status_code
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES: raise ValueError("Amplience response exceeds native bound")
                        data.extend(chunk)
            _credential(self.raw)  # Recheck short-lived expiry after the response too.
            if self.status != 200: raise _ProviderError(_error(self.action, "Amplience refused the GET; verify current expiry, ACL/functional permissions or entitlement. No retry occurred", self))
            raw = _object(json.loads(data))
            if raw.get("errors"): raise _ProviderError(_error(self.action, "Amplience returned an error envelope; raw errors and invalidValue are omitted", self))
            return raw
        except (httpx.HTTPError, SSRFError): raise _ProviderError(_error(self.action, "Amplience transport outcome is unknown; no retry occurred", self)) from None
    async def member(self, path, resource, selected, extra=None):
        # Closed declared catalog pages, never HAL URLs. At most ten metadata pages.
        page = 0
        while page < 10:
            result = _page(await self.request(path, {"page": page, "size": 100, **(extra or {})}), resource, page=page, size=100)
            matching = [row for row in result["data"] if row["id"] == selected]
            if len(matching) == 1: return matching[0]
            if not result["has_more"]: break
            page += 1
        raise ValueError("Current resource membership was not established within ten closed catalog pages")
    async def hub(self):
        await self.member("/hubs", "hubs", self.key.reference_hub_id)
        return _project(await self.request("/hubs/" + self.key.reference_hub_id), "hubs", expected_id=self.key.reference_hub_id)
    async def repository(self, hub_id, repository_id):
        if hub_id != self.key.reference_hub_id: raise ValueError("Selected hub differs from current credential binding")
        await self.member("/hubs/" + hub_id + "/content-repositories", "content-repositories", repository_id)
        return _project(await self.request("/content-repositories/" + repository_id), "content-repositories", expected_id=repository_id)
    async def folder(self, repository_id, folder_id):
        await self.member("/content-repositories/" + repository_id + "/folders", "folders", folder_id)
        return _project(await self.request("/folders/" + folder_id), "folders", expected_id=folder_id)


# These are the ACL/functional permission labels in the pinned Content Management
# specification, not scopes requested through an OAuth connection flow. Tokens
# are independently issued and supplied; this node never acquires extra grants.
_HUB_READ = ("ACL: Hub - READ",)
_REPOSITORY_READ = "FN: CONTENT:FUNCTIONAL:REPOSITORY:READ"
_AMPLIENCE_PERMISSIONS = {
    "check_connection": _HUB_READ,
    "list_hubs": _HUB_READ,
    "get_hub": _HUB_READ,
    "list_repositories": (*_HUB_READ, _REPOSITORY_READ),
    "get_repository": (*_HUB_READ, _REPOSITORY_READ),
    "list_content_types": (*_HUB_READ, "FN: CONTENT:FUNCTIONAL:CONTENT_TYPE:READ"),
    "get_content_type": (*_HUB_READ, "FN: CONTENT:FUNCTIONAL:CONTENT_TYPE:READ"),
    "list_content_items": (*_HUB_READ, _REPOSITORY_READ, "FN: CONTENT:FUNCTIONAL:CONTENT_ITEM:READ"),
    "get_content_item": (*_HUB_READ, _REPOSITORY_READ, "FN: CONTENT:FUNCTIONAL:CONTENT_ITEM:READ"),
    "list_folders": (*_HUB_READ, _REPOSITORY_READ, "FN: CONTENT:FUNCTIONAL:FOLDER:READ"),
    "get_folder": (*_HUB_READ, _REPOSITORY_READ, "FN: CONTENT:FUNCTIONAL:FOLDER:READ"),
    "list_subfolders": (*_HUB_READ, _REPOSITORY_READ, "FN: CONTENT:FUNCTIONAL:FOLDER:READ"),
}


class AmplienceNode(WorkflowNode):
    integration_type = "automation-amplience"
    credential_provider_labels = {"amplience": "Amplience"}
    scope_registry = ScopeRegistry("amplience", {
        operation: ScopeRequirement(scopes=permissions, tier="supplied",
                                    credential_types=("amplience_pat", "amplience_access_token"))
        for operation, permissions in _AMPLIENCE_PERMISSIONS.items()
    })
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Amplience protected hub catalog", proves="reachability")
    edit_examples = ["Read content metadata IDs/status without bodies or names", "Read repository items in my selected Amplience hub", "Opt in to names for selected folder metadata"]
    @classmethod
    def get_config_model(cls): return AmplienceNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging loaders resolve saved-row access; supplied tokens are never refreshed.
        return _stored(credential_data)
    @classmethod
    async def validate_credential_access(cls, credential_data):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Amplience token family, expiry or bound hub unsupported"}
        return {"valid": None, "error": "Run Check connection to verify Amplience protected catalog reachability."}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            action, key = config.operation, session.key
            if hasattr(config, "hub_id") and config.hub_id != key.reference_hub_id: raise ValueError("Choose the current credential-bound hub")
            await session.hub()
            if hasattr(config, "repository_id"): await session.repository(config.hub_id, config.repository_id)
            if action == "check_connection": out = {"data": {"hub_id": key.reference_hub_id}, "protected_reachability_verified": True, "principal_identity_proven": False, "organization_ownership_proven": False}
            elif action == "get_hub": out = {"data": _project(await session.request("/hubs/" + config.hub_id), "hubs", config.include_names, config.hub_id)}
            elif action == "get_repository": out = {"data": _project(await session.request("/content-repositories/" + config.repository_id), "content-repositories", config.include_names, config.repository_id)}
            elif action == "get_content_type":
                await session.member("/hubs/" + config.hub_id + "/content-types", "content-types", config.content_type_id, {"status": "ACTIVE,ARCHIVED"})
                out = {"data": _project(await session.request("/content-types/" + config.content_type_id), "content-types", False, config.content_type_id)}
            elif action == "get_content_item": out = {"data": _project(await session.request("/content-items/" + config.content_item_id), "content-items", config.include_names, config.content_item_id, config.repository_id)}
            elif action in {"get_folder", "list_subfolders"}:
                await session.folder(config.repository_id, config.folder_id)
                if action == "get_folder": out = {"data": _project(await session.request("/folders/" + config.folder_id), "folders", config.include_names, config.folder_id)}
                else:
                    out = _page(await session.request("/folders/" + config.folder_id + "/folders"), "folders", include_names=config.include_names)
                    out["continuation_supported"] = False  # OAS declares no page/size query on this route.
            else:
                resource, path = {"list_hubs": ("hubs", "/hubs"), "list_repositories": ("content-repositories", "/hubs/" + getattr(config, "hub_id", key.reference_hub_id) + "/content-repositories"), "list_content_types": ("content-types", "/hubs/" + getattr(config, "hub_id", key.reference_hub_id) + "/content-types"), "list_content_items": ("content-items", "/content-repositories/" + getattr(config, "repository_id", "") + "/content-items"), "list_folders": ("folders", "/content-repositories/" + getattr(config, "repository_id", "") + "/folders")}[action]
                params = {"page": config.page, "size": config.size}
                if hasattr(config, "status"): params["status"] = config.status
                # The OAS enum says 'projection', while its example/prose says basic.
                # Do not invent parity; bodies are always projected away locally.
                out = _page(await session.request(path, params), resource, page=config.page, size=config.size, include_names=config.include_names, repository_id=getattr(config, "repository_id", None))
                out["continuation_supported"] = True
            status = session.status
            # Discard metadata if current closed catalog ancestry changed in flight.
            await session.hub()
            if hasattr(config, "repository_id"): await session.repository(config.hub_id, config.repository_id)
            if action == "get_content_type": await session.member("/hubs/" + config.hub_id + "/content-types", "content-types", config.content_type_id, {"status": "ACTIVE,ARCHIVED"})
            if action == "get_content_item": _project(await session.request("/content-items/" + config.content_item_id), "content-items", False, config.content_item_id, config.repository_id)
            if action in {"get_folder", "list_subfolders"}: await session.folder(config.repository_id, config.folder_id)
            if key.token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Amplience output contains credential material")
            return {"status": "success", "action": action, "executed": True, "http_status": status, "mutation_attempted": False, "reference_hub_id": key.reference_hub_id, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError): return _error(config.operation, "Amplience current catalog ancestry or published bounded response could not be established; no raw fallback or retry", session)
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        key, context = _credential(credential_data), context or {}
        if search is not None: _text(search, 100)
        if page_token is None: page = 0
        elif isinstance(page_token, str) and re.fullmatch(r"0|[1-9][0-9]{0,3}", page_token): page = int(page_token)
        else: raise ValueError("Use an exact bounded zero-based page token")
        names = context.get("include_names", False)
        if type(names) is not bool: raise ValueError("Explicit boolean names opt-in required")
        if field_name == "hub_id":
            if page != 0: raise ValueError("Bound hub selector has no pagination")
            result = await cls._dispatch(credential_data, AmplienceGetHubConfig(hub_id=key.reference_hub_id, include_names=names))
            rows = [result["data"]] if result.get("status") == "success" else []
        else:
            hub_id = _id(context.get("hub_id"))
            if hub_id != key.reference_hub_id: raise ValueError("Choose the current bound hub before discovery")
            if field_name == "repository_id": config = AmplienceListRepositoriesConfig(hub_id=hub_id, page=page, include_names=names)
            elif field_name == "content_type_id": config = AmplienceListContentTypesConfig(hub_id=hub_id, page=page, include_names=names)
            elif field_name in {"content_item_id", "folder_id"}:
                repository_id = _id(context.get("repository_id"))
                model = AmplienceListContentItemsConfig if field_name == "content_item_id" else AmplienceListFoldersConfig
                config = model(hub_id=hub_id, repository_id=repository_id, page=page, include_names=names)
            else: raise ValueError("Unsupported Amplience selector")
            result = await cls._dispatch(credential_data, config)
            rows = result.get("data", [])
        if result.get("status") != "success": raise ValueError(result["error"])
        options = [{"value": row["id"], "label": row.get("label", row.get("name", row["id"])), "metadata": {"hub_id": key.reference_hub_id, **({"repository_id": context["repository_id"]} if field_name in {"content_item_id", "folder_id"} else {})}} for row in rows if not search or search.casefold() in row.get("label", row.get("name", row["id"])).casefold()]
        next_page = result.get("next_page")
        return {"options": options, "has_more": result.get("has_more", False), "next_page_token": str(next_page) if next_page is not None else None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        return await self._dispatch(initial, self.config.config)
