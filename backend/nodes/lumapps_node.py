"""LumApps typed intranet metadata and explicit unpublished content drafts.

Requests use an issued bearer token on its documented production cell origin.
Projections exclude private profiles, widget definitions and document URLs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

KIND = "lumapps_access_token"
API_PATH = "/_ah/api/lumsites/v1/"
MAX_RESPONSE = 2 * 1024 * 1024
MAX_ITEMS = 100
_private_request = ContextVar("lumapps_private_request", default=False)


class _PrivateLogFilter(logging.Filter):
    def filter(self, record):
        return not _private_request.get()


for _logger in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool",
        "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_logger).addFilter(_PrivateLogFilter())


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("LumApps requires a bounded resource ID.")
    return value


def bounded_text(value, limit=500, *, empty=False):
    if not isinstance(value, str) or (not value and not empty) or len(value) > limit or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("LumApps returned invalid text metadata.")
    return value


def localized_text(value):
    if isinstance(value, str):
        return bounded_text(value, 500, empty=True)
    # Older published SDK examples use language maps; the current discovery
    # describes a string. Accept either documented read shape, never templates.
    if isinstance(value, dict) and 1 <= len(value) <= 30:
        return {bounded_text(key, 20): bounded_text(item, 500, empty=True) for key, item in value.items()}
    raise ValueError("LumApps returned invalid localized metadata.")


def api_origin(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("LumApps requires a documented production cell API origin.")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or not re.fullmatch(r"[a-z]{2}-cell-[0-9]{3}\.api\.lumapps\.com", parsed.hostname or "")):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("LumApps requires https://XX-cell-YYY.api.lumapps.com without any other URL component.") from None
    return "https://" + parsed.hostname


class LumAppsAccessTokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", title="LumApps Supplied Access Token", json_schema_extra={
        "x-credential-url": "https://developer.lumapps.com/documentation.html",
        "x-credential-instructions": "Supply an already issued LumApps bearer token, its actual expiry, organization ID and production cell API origin. The node does not create tokens, impersonate users or run browser OAuth.",
    })
    credential_type: Literal["lumapps_access_token"] = Field(KIND, json_schema_extra={"ui:hidden": True})
    access_token: StrictStr = Field(..., title="Issued Access Token", min_length=1, max_length=8192,
        json_schema_extra={"ui:widget": "password"})
    api_origin: StrictStr = Field(..., title="Platform Cell API Origin", description="Use your actual platform cell, for example https://go-cell-001.api.lumapps.com.")
    customer_id: StrictStr = Field(..., title="Organization ID", description="Actual LumApps customer/organization ID. Token owner and instances are checked against it.")
    expires_at: StrictStr = Field(..., title="Actual Token Expiry", description="ISO 8601 timestamp with timezone. Renew externally; no inferred token lifetime.")

    @field_validator("api_origin")
    @classmethod
    def origin(cls, value):
        return api_origin(value)

    @field_validator("customer_id")
    @classmethod
    def customer(cls, value):
        return identifier(value)

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        if not value.isascii() or re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Supply a valid ASCII bearer header token.")
        return value

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        try:
            if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Supply the actual token expiry with timezone.") from None
        return value


def credential(data):
    if isinstance(data, LumAppsAccessTokenCredential):
        data = data.model_dump()
    if not isinstance(data, dict) or data.get("credential_type") != KIND:
        raise ValueError("LumApps requires its own issued access-token credential.")
    try:
        return LumAppsAccessTokenCredential.model_validate(data)
    except Exception:
        raise ValueError("Invalid LumApps issued-token shape.") from None


def raw_tag(data):
    if isinstance(data, dict) and isinstance(data.get("credentials"), dict):
        if data["credentials"].get("credential_type") != KIND:
            raise ConfigValidationError("Credential type is not supported by LumApps.")


def operation(name, label, *, creates=False):
    extra = {"const": name, "ui:hidden": True, "x-display-name": label}
    if creates:
        extra.update({"x-creates-resource": True, "x-resource-type": "lumapps_content", "x-resource-id-path": "data.id"})
    return Field(name, title=label, json_schema_extra=extra)


def resource_field(name, *, depends=None, resource_type=None):
    dynamic = {"field_name": name, "searchable": True, "allow_custom": True}
    if depends:
        dynamic["depends_on"] = depends
    return Field(..., title=name.replace("_", " ").title(),
        json_schema_extra={"x-resource-type": resource_type or "lumapps_" + name.removesuffix("_id"),
                           "x-dynamic-options": dynamic})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("instance_id", "content_id", "community_id", "user_id", "metadata_id", "resource_id", check_fields=False)
    @classmethod
    def ids(cls, value):
        return identifier(value)

    @field_validator("title", "query", check_fields=False)
    @classmethod
    def text(cls, value):
        return bounded_text(value, 255, empty=True) if value is not None else None


class PageInput(Input):
    page_size: StrictInt = Field(30, ge=1, le=100, description="Client bound of 100 metadata items per page.")
    page_token: Optional[StrictStr] = Field(None, max_length=24000, description="Opaque node cursor bound to the token, platform, organization and all filters.")


class InstanceInput(Input):
    instance_id: StrictStr = resource_field("instance_id")
    lang: Literal["cn", "en", "es", "fr", "it", "nl", "pl", "pt", "tr", "cs", "sv", "de", "ru", "ja", "pt_br"] = "en"


class LumAppsCurrentUser(Input):
    operation: Literal["get_current_user"] = operation("get_current_user", "Get Token Owner Metadata")


class LumAppsListUsers(PageInput):
    operation: Literal["list_users"] = operation("list_users", "List User Metadata")
    query: Optional[StrictStr] = Field(None, max_length=255)
    status: Optional[Literal["enabled", "disabled"]] = None


class LumAppsGetUser(Input):
    operation: Literal["get_user"] = operation("get_user", "Get User Metadata")
    user_id: StrictStr = resource_field("user_id")


class LumAppsListInstances(PageInput):
    operation: Literal["list_instances"] = operation("list_instances", "List Accessible Instances")
    query: Optional[StrictStr] = Field(None, max_length=255)


class LumAppsGetInstance(InstanceInput):
    operation: Literal["get_instance"] = operation("get_instance", "Get Instance Metadata")


class ContentInput(InstanceInput):
    content_id: StrictStr = resource_field("content_id", depends=["instance_id"])
    content_type: Literal["page", "news"] = "page"


class LumAppsListContent(PageInput, InstanceInput):
    operation: Literal["list_content"] = operation("list_content", "List Content Metadata")
    query: Optional[StrictStr] = Field(None, max_length=255)
    status: Optional[Literal["DRAFT", "REFUSED", "TO_VALIDATE", "LIVE", "ARCHIVE"]] = None
    content_type: Literal["page", "news"] = "page"


class LumAppsGetContent(ContentInput):
    operation: Literal["get_content"] = operation("get_content", "Get Content Metadata")


class LumAppsCreateDraft(InstanceInput):
    operation: Literal["create_content_draft"] = operation("create_content_draft", "Create Unpublished Content Draft", creates=True)
    title: StrictStr = Field(..., min_length=1, max_length=255)
    source_content_id: StrictStr = resource_field("source_content_id", depends=["instance_id"], resource_type="lumapps_content")

    @field_validator("source_content_id")
    @classmethod
    def source(cls, value):
        return identifier(value)


class LumAppsUpdateDraft(ContentInput):
    operation: Literal["update_content_draft"] = operation("update_content_draft", "Rename Unpublished Content Draft")
    title: StrictStr = Field(..., min_length=1, max_length=255)


class LumAppsDeleteDraft(ContentInput):
    operation: Literal["delete_content_draft"] = operation("delete_content_draft", "Delete Unpublished Content Draft")
    confirm_draft_delete: Literal[True] = Field(..., description="Explicitly acknowledge deletion of this draft.")

    @field_validator("confirm_draft_delete", mode="before")
    @classmethod
    def confirm(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Confirm draft deletion with true.")
        return value


class LumAppsListCommunities(PageInput, InstanceInput):
    operation: Literal["list_communities"] = operation("list_communities", "List Community Metadata")
    query: Optional[StrictStr] = Field(None, max_length=255)
    status: Optional[Literal["DRAFT", "REFUSED", "TO_VALIDATE", "LIVE", "ARCHIVE"]] = None


class LumAppsGetCommunity(InstanceInput):
    operation: Literal["get_community"] = operation("get_community", "Get Community Metadata")
    community_id: StrictStr = resource_field("community_id", depends=["instance_id"])


class LumAppsListDocuments(PageInput, InstanceInput):
    operation: Literal["list_documents"] = operation("list_documents", "List Local Document Metadata")
    folder_id: Optional[StrictStr] = Field(None, max_length=256, description="Optional local folder ID inside the selected instance.")
    query: Optional[StrictStr] = Field(None, max_length=255)
    search_in_folder: StrictBool = True

    @field_validator("folder_id")
    @classmethod
    def folder(cls, value):
        return identifier(value) if value is not None else None


class LumAppsGetDocument(InstanceInput):
    operation: Literal["get_document"] = operation("get_document", "Get Local Document Metadata")
    resource_id: StrictStr = resource_field("resource_id", depends=["instance_id"])


class LumAppsListMetadata(PageInput, InstanceInput):
    operation: Literal["list_metadata"] = operation("list_metadata", "List Instance Metadata")
    query: Optional[StrictStr] = Field(None, max_length=255)


class LumAppsGetMetadata(InstanceInput):
    operation: Literal["get_metadata"] = operation("get_metadata", "Get Instance Metadata Item")
    metadata_id: StrictStr = resource_field("metadata_id", depends=["instance_id"])


LumAppsOperations = Annotated[Union[
    LumAppsCurrentUser, LumAppsListUsers, LumAppsGetUser, LumAppsListInstances, LumAppsGetInstance,
    LumAppsListContent, LumAppsGetContent, LumAppsCreateDraft, LumAppsUpdateDraft, LumAppsDeleteDraft,
    LumAppsListCommunities, LumAppsGetCommunity, LumAppsListDocuments, LumAppsGetDocument,
    LumAppsListMetadata, LumAppsGetMetadata,
], Field(discriminator="operation")]


class LumAppsConfiguration(NodeConfig[LumAppsOperations, LumAppsAccessTokenCredential]):
    pass


def binding(creds):
    return (creds.credential_type, creds.access_token, creds.api_origin, creds.customer_id, creds.expires_at)


def cursor_cipher(creds):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("lumapps-cursor:" + creds.access_token).encode()).digest()))


def cursor_context(config, creds):
    return {"origin": creds.api_origin, "customer": creds.customer_id, "config": config.model_dump(exclude={"page_token"})}


def encode_cursor(cursor, history, config, creds):
    return cursor_cipher(creds).encrypt(json.dumps({"context": cursor_context(config, creds),
        "cursor": cursor, "history": history}, sort_keys=True).encode()).decode()


def decode_cursor(token, config, creds):
    if token is None:
        return None, []
    try:
        value = json.loads(cursor_cipher(creds).decrypt(token.encode()))
        if value["context"] != cursor_context(config, creds):
            raise ValueError()
        cursor = bounded_text(value["cursor"], 4096)
        history = value["history"]
        if not isinstance(history, list) or len(history) > 30 or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in history):
            raise ValueError()
        return cursor, history
    except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("LumApps page token does not match the current credential and filters.") from None


def record(value, kind, *, customer=None, instance=None, requested=None):
    if not isinstance(value, dict):
        raise ValueError("LumApps returned malformed metadata.")
    uid = identifier(value.get("uid") or value.get("id"))
    if value.get("uid") and value.get("id") and value["uid"] != value["id"]:
        raise ValueError("LumApps returned conflicting resource IDs.")
    if requested is not None and uid != requested:
        raise ValueError("LumApps returned a different resource ID.")
    if customer is not None:
        if value.get("customer") != customer:
            raise ValueError("LumApps resource belongs to a different or unverified organization.")
    if instance is not None and value.get("instance") != instance:
        raise ValueError("LumApps resource belongs to a different or unverified instance.")
    result = {"id": uid}
    keys = {
        "user": ("fullName", "firstName", "lastName", "status", "customer"),
        "instance": ("name", "status", "customer", "createdAt", "updatedAt"),
        "content": ("title", "status", "instance", "type", "createdAt", "updatedAt"),
        "community": ("title", "status", "instance", "type", "createdAt", "updatedAt"),
        "document": ("name", "status", "instance", "customer", "createdAt", "updatedAt"),
        "metadata": ("name", "instance", "customer", "familyKey", "createdAt", "updatedAt"),
    }[kind]
    for key in keys:
        if value.get(key) is not None:
            result[key] = localized_text(value[key]) if key in {"title", "name"} else bounded_text(value[key], 500, empty=True)
    if kind in {"content", "community"} and not result.get("status"):
        raise ValueError("LumApps returned no content status.")
    if kind == "document":
        for key in ("isFolder", "isShared", "trashed"):
            if key in value:
                if type(value[key]) is not bool:
                    raise ValueError("LumApps returned invalid document flags.")
                result[key] = value[key]
        if "content" in value:
            if not isinstance(value["content"], list) or len(value["content"]) > 30:
                raise ValueError("LumApps returned invalid document metadata.")
            files = []
            for item in value["content"]:
                if not isinstance(item, dict):
                    raise ValueError("LumApps returned invalid file metadata.")
                safe = {}
                if item.get("mimeType") is not None:
                    safe["mimeType"] = bounded_text(item["mimeType"], 200)
                if "size" in item:
                    size = item["size"]
                    if type(size) is not int or size < 0:
                        raise ValueError("LumApps returned invalid file size.")
                    safe["size"] = size
                files.append(safe)
            result["files"] = files
    if kind == "user":
        result["name"] = result.get("fullName") or " ".join(filter(None, (result.get("firstName"), result.get("lastName")))) or uid
    elif kind in {"content", "community"}:
        title = result.get("title")
        result["name"] = (next(iter(title.values()), uid) if isinstance(title, dict) else title) or uid
    elif isinstance(result.get("name"), dict):
        result["name"] = next(iter(result["name"].values()), uid)
    # No emails, profile/security/settings fields, templates, document URLs or blob values.
    return result


class LumAppsNode(WorkflowNode):
    integration_type = "automation-lumapps"
    agent_tool_provider = True
    connection_evidence = ConnectionEvidence(identity_operation="get_current_user", noun="token owner", proves="account")

    @classmethod
    def get_config_model(cls):
        return LumAppsConfiguration

    @classmethod
    def parse_config(cls, config_data):
        raw_tag(config_data)
        try:
            return LumAppsConfiguration.model_validate(runtime_config_view(config_data, LumAppsConfiguration))
        except Exception:
            raise ConfigValidationError("Invalid LumApps configuration or issued-token shape.") from None

    @classmethod
    def validate_config(cls, config_data):
        try:
            raw_tag(config_data)
        except ConfigValidationError:
            return {"valid": False, "errors": ["Invalid LumApps credential type."], "satisfied_set": None}
        data = runtime_config_view(config_data, LumAppsConfiguration)
        try:
            LumAppsConfiguration.model_validate(data)
        except ValidationError as exc:
            config = data.get("config", {})
            config = config if isinstance(config, dict) else {}
            for error in exc.errors():
                loc = error.get("loc", ())
                # Discriminated unions insert the operation tag in the error
                # path. Save-time references resolve later; execute still uses
                # the full strict parse after that resolution.
                field = None
                if len(loc) > 1 and loc[0] == "config":
                    field = loc[2] if len(loc) > 2 and loc[1] == config.get("operation") else loc[1]
                value = config.get(field)
                if isinstance(value, str) and "{{" in value:
                    continue
                return {"valid": False, "errors": ["Invalid LumApps configuration or credential shape."], "satisfied_set": None}
        return {"valid": True, "errors": [], "satisfied_set": "default"}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging's credential loaders supply the decrypted saved grant.
        # Issued tokens are renewed externally, so only validate their expiry.
        creds = credential(credential_data)
        if datetime.fromisoformat(creds.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ValueError("LumApps issued token expired; supply a current token and actual expiry.")
        return creds.model_dump()

    async def _current(self):
        raw_tag(self.node_data)
        if not isinstance(self.config, LumAppsConfiguration) or self.config.credentials is None:
            raise ValueError("LumApps issued credentials are required.")
        creds = credential(await self.freshen_credential(self.config.credentials))
        self.config.credentials = creds
        return creds

    async def _request(self, method, endpoint, *, query=None, body=None, expected=None):
        creds = await self._current()
        if expected is not None and binding(creds) != expected:
            raise ValueError("LumApps current credential changed between dependent requests.")
        marker = _private_request.set(True)
        try:
            async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
                async with client.stream(method, creds.api_origin + API_PATH + endpoint, params=query, json=body,
                        headers={"Authorization": "Bearer " + creds.access_token, "Accept": "application/json",
                                 "x-lumapps-analytics": "off"}) as response:
                    if response.status_code not in ({200, 204} if method == "DELETE" else {200}):
                        safe = httpx.Request(method, "https://lumapps.invalid/api/")
                        raise httpx.HTTPStatusError(
                            f"LumApps HTTP {response.status_code}; saved credential validity is unverified.",
                            request=safe, response=httpx.Response(response.status_code, request=safe))
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE:
                            raise ValueError("LumApps metadata exceeds the 2 MiB client bound.")
                    if method == "DELETE":
                        if bytes(content).strip() not in {b"", b"{}", b"null"}:
                            raise ValueError("LumApps returned an unexpected deletion response.")
                        return None, creds, response.status_code
                    try:
                        value = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except Exception:
                        raise ValueError("LumApps returned malformed JSON.") from None
                    if (not isinstance(value, dict) or "error" in value
                            or ("errors" in value and (not isinstance(value["errors"], list) or value["errors"]))):
                        raise ValueError("LumApps returned a malformed or failed response; saved credential validity is unverified.")
                    if value.get("unavailable") is True:
                        raise ValueError("LumApps document provider is unavailable for this token.")
                    return value, creds, response.status_code
        except httpx.HTTPStatusError:
            raise
        except (httpx.RequestError, SSRFError):
            raise ValueError("LumApps request failed; saved credential validity is unverified.") from None
        finally:
            _private_request.reset(marker)

    async def _identity(self):
        value, creds, _ = await self._request("GET", "user/get")
        safe = record(value, "user", customer=creds.customer_id)
        return safe, binding(creds)

    async def _instance(self, instance_id, expected):
        value, creds, _ = await self._request("GET", "instance/get", query={"uid": instance_id}, expected=expected)
        return record(value, "instance", customer=creds.customer_id, requested=instance_id)

    async def _page(self, config, endpoint, kind, params, expected, *, method="GET"):
        creds = await self._current()
        if binding(creds) != expected:
            raise ValueError("LumApps current credential changed before pagination.")
        cursor, history = decode_cursor(config.page_token, config, creds)
        params["maxResults"] = config.page_size
        if cursor is not None:
            params["cursor"] = cursor
        value, current, _ = await self._request(method, endpoint,
            query=params if method == "GET" else None, body=params if method == "POST" else None, expected=expected)
        items = value.get("items", [])
        # Discovery fields are optional; the publisher SDK treats absent `more`
        # as a final page, including an empty object when items are omitted.
        more = value.get("more", False)
        if not isinstance(items, list) or len(items) > config.page_size or any(not isinstance(item, dict) for item in items) or type(more) is not bool:
            raise ValueError("LumApps returned malformed pagination.")
        nxt = value.get("cursor")
        token = None
        if more:
            nxt = bounded_text(nxt, 4096)
            digest = hashlib.sha256(nxt.encode()).hexdigest()
            if not items or nxt == cursor or digest in history or len(history) >= 30:
                raise ValueError("LumApps returned empty, repeated or excessive pagination.")
            token = encode_cursor(nxt, history + [digest], config, current)
        instance_id = getattr(config, "instance_id", None)
        return {"items": [record(item, kind, customer=current.customer_id if kind in {"user", "instance"} else None,
            instance=instance_id) for item in items], "has_more": more, "next_page_token": token}

    async def execute(self, inputs):
        owner, expected = await self._identity()
        config = self.config.config
        op = config.operation
        if op == "get_current_user":
            return {"status": "success", "data": owner}
        if isinstance(config, LumAppsListUsers):
            data = await self._page(config, "user/list", "user",
                {k: v for k, v in {"query": config.query, "status": config.status, "action": "USER_READ"}.items() if v is not None}, expected)
        elif isinstance(config, LumAppsGetUser):
            value, creds, _ = await self._request("GET", "user/get", query={"uid": config.user_id}, expected=expected)
            data = record(value, "user", customer=creds.customer_id, requested=config.user_id)
        elif isinstance(config, LumAppsListInstances):
            data = await self._page(config, "instance/list", "instance",
                {k: v for k, v in {"name": config.query, "considerUserIdentity": "true"}.items() if v is not None}, expected)
        else:
            parent = await self._instance(config.instance_id, expected)
            if isinstance(config, LumAppsGetInstance):
                data = parent
            elif isinstance(config, (LumAppsListContent, LumAppsListCommunities)):
                kind = "content" if isinstance(config, LumAppsListContent) else "community"
                params = {"instanceId": [config.instance_id], "customerId": self.config.credentials.customer_id, "lang": [config.lang]}
                params["action"] = ("PAGE_READ" if config.content_type == "page" else "NEWS_READ") if kind == "content" else "COMMUNITY_READ"
                if kind == "content":
                    params["type"] = [config.content_type]
                if config.query is not None:
                    params["query"] = config.query
                if config.status is not None:
                    params["status"] = [config.status]
                data = await self._page(config, kind + "/list", kind, params, expected, method="POST")
            elif isinstance(config, (LumAppsGetContent, LumAppsGetCommunity, LumAppsUpdateDraft, LumAppsDeleteDraft)):
                community = isinstance(config, LumAppsGetCommunity)
                kind = "community" if community else "content"
                uid = config.community_id if community else config.content_id
                query = {"uid": uid, "instance": config.instance_id, "lang": config.lang}
                if not community:
                    edit = isinstance(config, LumAppsUpdateDraft)
                    query["action"] = ("PAGE_" if config.content_type == "page" else "NEWS_") + ("EDIT" if edit else "READ")
                value, creds, _ = await self._request("GET", kind + "/get",
                    query=query, expected=expected)
                data = record(value, kind, instance=config.instance_id, requested=uid)
                if isinstance(config, (LumAppsUpdateDraft, LumAppsDeleteDraft)):
                    if value.get("status") != "DRAFT" or value.get("type") != config.content_type:
                        raise ValueError("LumApps draft operation requires current DRAFT status.")
                    if isinstance(config, LumAppsUpdateDraft):
                        if type(value.get("version")) is not int or value["version"] < 0:
                            raise ValueError("LumApps draft update requires the current provider version lock.")
                        # Publisher SDK documents get/modify/save; retain the current draft.
                        payload = dict(value)
                        payload["title"] = ({**value["title"], config.lang: config.title}
                            if isinstance(value.get("title"), dict) else {config.lang: config.title})
                        payload["status"] = "DRAFT"
                        saved, _, _ = await self._request("POST", "content/save",
                            query={"sendNotifications": "false"}, body=payload, expected=expected)
                        data = record(saved, "content", instance=config.instance_id, requested=uid)
                        if data["status"] != "DRAFT":
                            raise ValueError("LumApps save did not return DRAFT; read back before further action.")
                    else:
                        _, _, code = await self._request("DELETE", "content/delete", query={"uid": uid}, expected=expected)
                        data = {"id": uid, "instance": config.instance_id, "operation": op, "http_status": code, "acknowledged": True}
            elif isinstance(config, LumAppsCreateDraft):
                source, _, _ = await self._request("GET", "content/get",
                    query={"uid": config.source_content_id, "instance": config.instance_id, "lang": config.lang, "action": "PAGE_READ"},
                    expected=expected)
                record(source, "content", instance=config.instance_id, requested=config.source_content_id)
                if source.get("type") != "page" or not isinstance(source.get("template"), dict):
                    raise ValueError("LumApps draft creation requires a page with a documented template.")
                payload = {key: source[key] for key in ("template", "customContentType", "feedKeys") if key in source}
                payload.update({"title": {config.lang: config.title}, "instance": config.instance_id, "customer": self.config.credentials.customer_id,
                    "type": "page", "status": "DRAFT"})
                saved, _, _ = await self._request("POST", "content/save",
                    query={"sendNotifications": "false"}, body=payload, expected=expected)
                data = record(saved, "content", instance=config.instance_id)
                if data["status"] != "DRAFT":
                    raise ValueError("LumApps save did not return DRAFT; read back before further action.")
                data.update({"requested_status": "DRAFT", "notifications_requested": False})
            elif isinstance(config, LumAppsListDocuments):
                path = "provider=local/site=" + config.instance_id
                if config.folder_id is not None:
                    path += "/resource=" + config.folder_id
                params = {"docPath": path, "asApplication": False, "searchInFolder": config.search_in_folder, "lang": config.lang}
                if config.query is not None:
                    params["searchText"] = config.query
                data = await self._page(config, "document/list", "document", params, expected, method="POST")
            elif isinstance(config, LumAppsGetDocument):
                path = "provider=local/site=" + config.instance_id + "/resource=" + config.resource_id
                value, _, _ = await self._request("POST", "document/get", body={"docPath": path}, expected=expected)
                data = record(value, "document", instance=config.instance_id, requested=config.resource_id)
            elif isinstance(config, LumAppsListMetadata):
                params = {"instance": config.instance_id}
                if config.query is not None:
                    params["name"] = config.query
                data = await self._page(config, "metadata/list", "metadata", params, expected)
            elif isinstance(config, LumAppsGetMetadata):
                value, _, _ = await self._request("GET", "metadata/get", query={"uid": config.metadata_id}, expected=expected)
                data = record(value, "metadata", instance=config.instance_id, requested=config.metadata_id)
            else:
                raise ValueError("Unsupported LumApps operation.")
        return {"status": "success", "data": data}

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        if validation_context is None:
            return {"valid": None, "message": "LumApps access is unverified; retry with authenticated validation context."}
        try:
            result = await validation_context.run_operation("get_current_user", {})
            if result.get("executed") is False or result.get("_halt_downstream") is True:
                return {"valid": None, "message": "LumApps access is unverified; retry validation."}
            if result.get("status") == "success" and isinstance(result.get("data"), dict) and result["data"].get("id"):
                return {"valid": True, "message": "LumApps returned the token owner in the configured organization. Other resource permissions remain provider-enforced."}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return {"valid": False, "message": f"LumApps rejected token-owner access (HTTP {exc.response.status_code})."}
        except Exception:
            pass
        return {"valid": None, "message": "LumApps access is unverified; retry validation."}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search_query=None, page_token=None, **kwargs):
        context = context or {}
        operations = {"instance_id": "list_instances", "user_id": "list_users", "content_id": "list_content",
                      "source_content_id": "list_content",
                      "community_id": "list_communities", "resource_id": "list_documents", "metadata_id": "list_metadata"}
        if field_name not in operations:
            return {"options": [], "has_more": False}
        config = {"operation": operations[field_name], "page_size": 100, "page_token": page_token}
        if field_name not in {"instance_id", "user_id"}:
            if not context.get("instance_id"):
                raise ValueError("Select the LumApps instance before loading dependent resources.")
            config["instance_id"] = identifier(context["instance_id"])
        if field_name == "content_id" and context.get("content_type") in {"page", "news"}:
            config["content_type"] = context["content_type"]
        search = search_query if search_query is not None else kwargs.get("search")
        if search is not None:
            config["query"] = bounded_text(search, 255, empty=True)
        creds = credential(credential_data)
        node_data = {"credentials": creds.model_dump()}
        node = cls("lumapps-picker", "automation-lumapps", node_data,
            cls.parse_config({"credentials": creds.model_dump(), "config": config}))
        data = (await node.execute({}))["data"]
        return {"options": [{"value": item["id"], "label": item.get("name") or item["id"],
            "metadata": {"instance_id": config["instance_id"]} if "instance_id" in config else {}} for item in data["items"]],
            "has_more": data["has_more"], "next_page_token": data["next_page_token"]}
