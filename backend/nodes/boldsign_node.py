"""BoldSign protected document/template metadata and owned contact workflows.

Native reads project selected metadata; ordinary contact and tag mutations
exclude sends, signing, reminders, invitations and binary evidence exports.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import math
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlencode
from uuid import UUID
import time
import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.boldsign import BOLDSIGN_SCOPES, OPERATION_ENDPOINTS, require_machine_scopes
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client
from utils.oauth_token_cache import OAuthTokenCache, oauth_authority_digest

NODE_TYPE = "automation-boldsign"
BASE = "https://api.boldsign.com"
FAMILY = "boldsign_api_key"
OAUTH_FAMILY = "boldsign_client_credentials"
FAMILIES = frozenset({FAMILY, OAUTH_FAMILY})
TOKEN_ENDPOINT = "https://account.boldsign.com/connect/token"
_TOKEN_CACHE = OAuthTokenCache()
_MISSING = object()
_REQUEST_CONTEXT = ContextVar("boldsign_request", default=None)
WRITES = frozenset({"create_contact", "update_contact", "delete_contact", "add_document_tags", "delete_document_tags", "add_template_tags", "delete_template_tags"})


class _Privacy(logging.Filter):
    def filter(self, record):
        if _REQUEST_CONTEXT.get() is not None:
            record.msg, record.args = "BoldSign transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_PRIVACY = _Privacy()


def _resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value): raise ValueError("Use the exact BoldSign resource ID, without a URL")
    return value


def _picker(name):
    return {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, "placeholder": "Choose an allowed BoldSign resource", "custom_placeholder": "Paste resource ID"}}


class _BoldSignScope(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    environment: Literal["sandbox", "live"] = Field(..., title="Issued credential environment", description="Choose the actual issued credential environment. This label does not switch or prove the provider environment.")
    expires_at: Optional[datetime] = Field(None, title="Actual credential expiry, if set", description="Use the actual API key or client secret validity date when configured. No lifetime or renewal is assumed.")
    allowed_document_ids: list[str] = Field(default_factory=list, max_length=200, title="Allowed document IDs", description="Enter a JSON list of exact resource IDs, for example [\"existing-id\"]. An empty list permits no selected resources.")
    allowed_template_ids: list[str] = Field(default_factory=list, max_length=200, title="Allowed template IDs", description="Enter a JSON list of exact resource IDs, for example [\"existing-id\"]. An empty list permits no selected resources.")
    allowed_contact_ids: list[str] = Field(default_factory=list, max_length=200, title="Allowed owned contact IDs", description="Enter a JSON list of exact resource IDs, for example [\"existing-id\"]. An empty list permits no selected resources.")
    allowed_contact_group_ids: list[str] = Field(default_factory=list, max_length=200, title="Allowed owned contact group IDs", description="Enter a JSON list of exact resource IDs, for example [\"existing-id\"]. An empty list permits no selected resources.")
    allow_contact_create: bool = Field(False, strict=True, title="Allow contact creation", description="Enter true to opt in or false to decline. Creates an organization contact only. New IDs still require explicit saved scope before later reads or changes.")
    @field_validator("allowed_document_ids", "allowed_template_ids", "allowed_contact_ids", "allowed_contact_group_ids", mode="before")
    @classmethod
    def scope(cls, value):
        # The shared manual credential form submits text; JSON arrays remain
        # explicit and pass the same bounded ID validation as structured input.
        if isinstance(value, str):
            if len(value) > 32_000: raise ValueError("Resource ID list is too large")
            try: value = json.loads(value)
            except ValueError: raise ValueError("Use a JSON list of exact resource IDs") from None
        if not isinstance(value, list): raise ValueError("Use a list of exact resource IDs")
        values = [_resource_id(item) for item in value]
        if len(set(values)) != len(values): raise ValueError("Do not repeat allowed IDs")
        return values
    @field_validator("allow_contact_create", mode="before")
    @classmethod
    def create_opt_in(cls, value):
        if value == "true": return True
        if value == "false": return False
        return value
    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None): raise ValueError("Use the actual timezone-aware expiry")
        return value


def _literal_secret(value):
    if not isinstance(value, str): raise ValueError("Paste literal issued authentication text")
    value = clean_secret(value, field_name="BoldSign authentication")
    if not value or len(value) > 16_384 or "{{" in value or "$(" in value or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Use literal issued authentication text without spaces or references")
    return value


class BoldSignCredential(_BoldSignScope):
    model_config = ConfigDict(title="BoldSign API Key", json_schema_extra={"x-credential-url": "https://developers.boldsign.com/authentication/api-key/", "x-credential-instructions": "Supply an issued US-region API key from the intended Sandbox or Live environment. The key is sent only to api.boldsign.com. Saved ID allowlists narrow this node; provider access and native execution approval remain authoritative."})
    credential_type: Literal["boldsign_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=16_384, title="API key", json_schema_extra={"ui:widget": "password"})
    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value): return _literal_secret(value)
    @model_validator(mode="before")
    @classmethod
    def method(cls, value):
        if isinstance(value, dict) and any(value.get(k) is not None for k in ("client_id", "client_secret", "scopes", "token_endpoint")):
            raise ValueError("Select one BoldSign authentication method")
        return value


class BoldSignClientCredentials(_BoldSignScope):
    model_config = ConfigDict(title="BoldSign OAuth Client", json_schema_extra={"x-credential-url": "https://developers.boldsign.com/authentication/oauth-2-0/", "x-credential-instructions": "Supply an existing US-region machine client ID and secret, actual Sandbox/Live label, and explicit API scopes. Tokens are obtained at account.boldsign.com with client_credentials and sent only to api.boldsign.com. No callback, consent or refresh token. Checking the protected document list proves reachability only; provider permissions and saved ID allowlists remain authoritative."})
    credential_type: Literal["boldsign_client_credentials"] = Field(OAUTH_FAMILY, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., title="Client ID")
    client_secret: str = Field(..., title="Client Secret", json_schema_extra={"ui:widget": "password"})
    scopes: list[Literal["BoldSign.Documents.All", "BoldSign.Templates.Read", "BoldSign.Templates.Write", "BoldSign.Templates.All"]] = Field(..., min_length=1, max_length=4, title="Requested API Scopes", description="Enter explicit scopes separated by single spaces (or supply a structured list). Connection checks require Documents.All; template reads require Templates.Read or All, tag changes also require Write or All. Contact permissions remain provider-enforced; no undocumented scope is invented.")
    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def secret(cls, value): return _literal_secret(value)
    @field_validator("scopes", mode="before")
    @classmethod
    def scope_input(cls, value):
        if isinstance(value, str):
            if len(value) > 256: raise ValueError("Explicit API scope list is too large")
            return value.split(" ")
        return value
    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value):
        if len(set(value)) != len(value): raise ValueError("Choose each API scope once")
        return value
    @model_validator(mode="before")
    @classmethod
    def method(cls, value):
        if isinstance(value, dict) and any(value.get(k) is not None for k in ("api_key", "token_endpoint", "access_token", "refresh_token")):
            raise ValueError("Supply only the issued machine client pair and scopes")
        return value


Credential = Union[BoldSignCredential, BoldSignClientCredentials]
_CREDENTIAL = TypeAdapter(Credential)


def _credential_model(raw): return _CREDENTIAL.validate_python(raw)


def _secrets(credential):
    return (credential.client_id, credential.client_secret) if isinstance(credential, BoldSignClientCredentials) else (credential.api_key,)


def _contains_secret(value, secrets):
    if isinstance(value, str): return any(secret in value for secret in secrets)
    if isinstance(value, dict): return any(_contains_secret(key, secrets) or _contains_secret(item, secrets) for key, item in value.items())
    return any(_contains_secret(item, secrets) for item in value) if isinstance(value, (list, tuple)) else False


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BoldSignCheckConfig(_Input):
    """Read one protected document page as organization reachability, without identity claims."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class _Page(_Input):
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)
    search_key: Optional[str] = Field(None, min_length=1, max_length=200)
    @field_validator("page", "page_size", mode="before")
    @classmethod
    def integers(cls, value):
        if type(value) is not int: raise ValueError("Page and page size must be integers")
        return value


class BoldSignDocumentsConfig(_Page):
    """Read one bounded document page, intersected with saved document scope."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})
    next_cursor: Optional[int] = Field(None, ge=0, le=2**63 - 1, description="Exact last document nextCursor for documented pagination beyond 10,000 records; do not guess it.")
    status_filter: Optional[Literal["WaitingForMe", "WaitingForOthers", "NeedAttention", "Completed", "Declined", "Revoked", "Expired", "Scheduled", "Draft"]] = None
    @field_validator("next_cursor", mode="before")
    @classmethod
    def cursor(cls, value):
        if value is not None and type(value) is not int: raise ValueError("Use the exact integer document cursor")
        return value


class _Document(_Input):
    document_id: str = Field(..., json_schema_extra=_picker("document_id"))
    @field_validator("document_id", mode="before")
    @classmethod
    def identifier(cls, value): return _resource_id(value)


class BoldSignDocumentConfig(_Document):
    """Read document title/status/date/tag metadata, excluding recipients and filled fields."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})


class BoldSignStatusConfig(_Document):
    """Read status and activity metadata without signer identity or signing links."""
    operation: Literal["get_document_status"] = Field("get_document_status", json_schema_extra={"ui:hidden": True})


class BoldSignHistoryConfig(_Document):
    """Read bounded history IDs/actions/timestamps; omit actors, IPs and change contents."""
    operation: Literal["get_document_history"] = Field("get_document_history", json_schema_extra={"ui:hidden": True})


class BoldSignTemplatesConfig(_Page):
    """Read own template metadata only, intersected with saved template IDs."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


class _Template(_Input):
    template_id: str = Field(..., json_schema_extra=_picker("template_id"))
    @field_validator("template_id", mode="before")
    @classmethod
    def identifier(cls, value): return _resource_id(value)


class BoldSignTemplateConfig(_Template):
    """Read selected template title/date/tag metadata without roles, fields or shares."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class BoldSignContactsConfig(_Page):
    """List MyContacts, exposing only saved allowed owned contact IDs."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class _Contact(_Input):
    contact_id: str = Field(..., json_schema_extra=_picker("contact_id"))
    @field_validator("contact_id", mode="before")
    @classmethod
    def identifier(cls, value): return _resource_id(value)


class BoldSignContactConfig(_Contact):
    """Read one saved allowed contact after current MyContacts membership validation."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class _ContactValues(_Input):
    email: str = Field(..., min_length=3, max_length=320)
    name: str = Field(..., min_length=1, max_length=200)
    company_name: Optional[str] = Field(None, max_length=200)
    job_title: Optional[str] = Field(None, max_length=200)
    @field_validator("email")
    @classmethod
    def address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value): raise ValueError("Enter the intended contact email")
        return value


class BoldSignCreateContactConfig(_ContactValues):
    """Create one contact using the documented array body; later readback needs saved scope."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})


class BoldSignUpdateContactConfig(_Contact, _ContactValues):
    """Update an allowed MyContacts entry; a separate GET readback is required."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})


class BoldSignDeleteContactConfig(_Contact):
    """Delete an allowed owned contact; does not revoke or change documents."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class BoldSignGroupsConfig(_Page):
    """Read MyContacts groups with saved allowed IDs, omitting group contact identities."""
    operation: Literal["list_contact_groups"] = Field("list_contact_groups", json_schema_extra={"ui:hidden": True})


class BoldSignGroupConfig(_Input):
    """Read one allowed owned group name/directories; omit creator and contact identities."""
    operation: Literal["get_contact_group"] = Field("get_contact_group", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., json_schema_extra=_picker("group_id"))
    @field_validator("group_id", mode="before")
    @classmethod
    def identifier(cls, value): return _resource_id(value)


class _Tags(_Input):
    tags: list[str] = Field(..., min_length=1, max_length=50, description="Exact tags; each at most 255 characters with no whitespace.")
    @field_validator("tags", mode="before")
    @classmethod
    def values(cls, value):
        if not isinstance(value, list) or any(not isinstance(tag, str) or not 1 <= len(tag) <= 255 or any(c.isspace() for c in tag) for tag in value) or len(set(value)) != len(value): raise ValueError("Use distinct nonempty tags without whitespace")
        return value


class BoldSignAddDocumentTagsConfig(_Document, _Tags):
    """Add document labels only; labels are visible to authorized organization users."""
    operation: Literal["add_document_tags"] = Field("add_document_tags", json_schema_extra={"ui:hidden": True})


class BoldSignDeleteDocumentTagsConfig(_Document, _Tags):
    """Remove exact document labels and independently read them back."""
    operation: Literal["delete_document_tags"] = Field("delete_document_tags", json_schema_extra={"ui:hidden": True})


class BoldSignAddTemplateTagsConfig(_Template, _Tags):
    """Add template labels only, without changing derived-document labels or recipients."""
    operation: Literal["add_template_tags"] = Field("add_template_tags", json_schema_extra={"ui:hidden": True})


class BoldSignDeleteTemplateTagsConfig(_Template, _Tags):
    """Remove exact template labels only; no on-behalf identity or derived-document changes."""
    operation: Literal["delete_template_tags"] = Field("delete_template_tags", json_schema_extra={"ui:hidden": True})


BoldSignConfig = Annotated[Union[BoldSignCheckConfig, BoldSignDocumentsConfig, BoldSignDocumentConfig, BoldSignStatusConfig, BoldSignHistoryConfig,
    BoldSignTemplatesConfig, BoldSignTemplateConfig, BoldSignContactsConfig, BoldSignContactConfig, BoldSignCreateContactConfig,
    BoldSignUpdateContactConfig, BoldSignDeleteContactConfig, BoldSignGroupsConfig, BoldSignGroupConfig,
    BoldSignAddDocumentTagsConfig, BoldSignDeleteDocumentTagsConfig, BoldSignAddTemplateTagsConfig, BoldSignDeleteTemplateTagsConfig], Field(discriminator="operation")]


class BoldSignFullConfig(NodeConfig[BoldSignConfig, Credential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _page_binding(credential, field, search):
    scope = credential.model_dump(mode="json", exclude={"api_key", "client_secret"})
    digest = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"field": field, "search": search or None, "scope_sha256": digest}


def _encode_page(page, credential, field, search):
    payload = json.dumps({"page": page, "expires": int(time.time()) + 900, "binding": _page_binding(credential, field, search)}, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(_secrets(credential)[-1].encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + mac).decode().rstrip("=")


def _decode_page(token, credential, field, search):
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 2_000 or not re.fullmatch(r"[A-Za-z0-9_-]+", token): raise ValueError()
        data = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload, mac = data[:-32], data[-32:]
        if not hmac.compare_digest(mac, hmac.new(_secrets(credential)[-1].encode(), payload, hashlib.sha256).digest()): raise ValueError()
        value = json.loads(payload)
        if not isinstance(value, dict): raise ValueError()
        if value.get("binding") != _page_binding(credential, field, search) or type(value.get("page")) is not int or not 1 <= value["page"] <= 10_000 or type(value.get("expires")) is not int or value["expires"] <= time.time(): raise ValueError()
        return value["page"]
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError("Choice continuation is invalid, expired or belongs to a different credential/scope/search") from None


def _credential_id(data):
    ids = []
    selected = data.get("credential_id")
    if selected is not None and selected != "":
        ids.append(selected)
    for scope in (data, data.get("config", {})):
        mapping = scope.get("credentialIds", {}) if isinstance(scope, dict) else {}
        if not isinstance(mapping, dict):
            raise ValueError("Credential attachment is invalid")
        for family, value in mapping.items():
            if family == "credential_type":
                continue
            if value is not None and value != "":
                if family not in FAMILIES:
                    raise ValueError("Attach only a BoldSign credential")
                ids.append(value)
    if not ids:
        return None
    if any(not isinstance(value, str) or "{{" in value for value in ids) or len(set(ids)) != 1:
        raise ValueError("Choose one saved BoldSign credential")
    try:
        UUID(ids[0])
    except ValueError:
        raise ValueError("Credential attachment is invalid") from None
    return ids[0]


def _guard(data):
    cid = _credential_id(data)
    raw = data.get("credentials")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("BoldSign credential data is invalid")
    tag = raw.get("credential_type", _MISSING)
    if tag is not _MISSING and (not isinstance(tag, str) or tag not in FAMILIES):
        raise ValueError("This credential is not a BoldSign credential")
    if cid and tag is _MISSING:
        raise ValueError("Saved BoldSign credentials require their original family")
    for scope in (data, data.get("config", {})):
        mapping = scope.get("credentialIds", {}) if isinstance(scope, dict) else {}
        if any(family != tag for family, value in mapping.items() if family != "credential_type" and value):
            raise ValueError("Keep the selected BoldSign credential family unchanged")


def _native_config_view(data):
    if not isinstance(data.get("config"), dict):
        return data
    labels = {"credentialIds", "document_id__label", "template_id__label", "contact_id__label", "group_id__label"}
    return {**data, "config": {k: v for k, v in data["config"].items() if k not in labels}}


class _ResponseError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__("BoldSign request was not confirmed")


class BoldSignNode(WorkflowNode):
    integration_type = "automation-boldsign"
    credential_provider_labels = {"boldsign": "BoldSign Account"}
    scope_registry = BOLDSIGN_SCOPES
    connection_evidence = ConnectionEvidence(noun="BoldSign organization API", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BoldSignFullConfig

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(_native_config_view(config_data))

    @classmethod
    def parse_config(cls, config_data):
        _guard(config_data)
        return super().parse_config(_native_config_view(config_data))

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        operations = {"document_id": "list_documents", "template_id": "list_templates", "contact_id": "list_contacts", "group_id": "list_contact_groups"}
        if field_name not in operations: raise ValueError("Unknown BoldSign choice field")
        _guard({"credentials": credential_data})
        config = {"operation": operations[field_name], "page_size": 20}
        if search: config["search_key"] = search
        credential = _credential_model(credential_data)
        if page_token is not None: config["page"] = _decode_page(page_token, credential, field_name, search)
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="boldsign-options", node_type=NODE_TYPE,
            node_data={"credentials": credential_data, "config": config})
        result = await node.execute({})
        if result.get("status") != "success" or result.get("cursor_required") or result.get("pagination_unknown"):
            raise ValueError("BoldSign choices were not completed; check access, approval or paging limits")
        next_page = result.get("next_page")
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"]} for row in result["items"]],
            "next_page_token": _encode_page(next_page, credential, field_name, search) if next_page is not None else None}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="boldsign-check", node_type=NODE_TYPE,
            node_data={"credentials": credential_data, "config": {"operation": "check_connection"}})
        result = await node.execute({})
        return {"valid": result.get("status") == "success", **({"error": result["error"]} if "error" in result else {})}

    async def execute(self, inputs):
        # Staging's operation/workflow loaders resolve saved credentials and
        # WorkflowNode.run owns approval. Non-rotating keys need no refresh;
        # machine tokens are acquired and renewed locally at request time.
        _guard(self.node_data)
        if not isinstance(self.config, BoldSignFullConfig) or self.config.credentials is None:
            raise ValueError("Supply a BoldSign credential")
        for name in {"httpx", "httpcore", *logging.Logger.manager.loggerDict}:
            if name in ("httpx", "httpcore") or name.startswith(("httpx.", "httpcore.")):
                logging.getLogger(name).addFilter(_PRIVACY)
        token = _REQUEST_CONTEXT.set((self, self.config.credentials))
        try:
            return await self._execute(inputs)
        finally:
            _REQUEST_CONTEXT.reset(token)

    async def _authorization(self, credential):
        if not isinstance(credential, BoldSignClientCredentials):
            return {"X-API-KEY": credential.api_key}, _secrets(credential)
        cache_key = oauth_authority_digest(provider="boldsign", credential=credential.model_dump(mode="json"),
            caller=(self.user_id, self.organization_id, self.workflow_id))
        token = _TOKEN_CACHE.get(cache_key, now=time.monotonic())
        if token is None:
            started = time.monotonic()
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream("POST", TOKEN_ENDPOINT, data={"grant_type": "client_credentials", "client_id": credential.client_id,
                    "client_secret": credential.client_secret, "scope": " ".join(credential.scopes)},
                    headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}) as response:
                    status, buffer = response.status_code, bytearray()
                    async for part in response.aiter_bytes():
                        buffer.extend(part)
                        if len(buffer) > 65_536: raise ValueError("BoldSign token response exceeded its bound")
            if status != 200: raise _ResponseError(status)
            try:
                payload = json.loads(buffer)
                token, ttl, scope = payload.get("access_token"), payload.get("expires_in"), payload.get("scope")
                valid = (isinstance(token, str) and len(token) <= 16_384 and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token)
                    and payload.get("token_type", "").lower() == "bearer" and type(ttl) in (int, float)
                    and math.isfinite(ttl) and 0 < ttl <= 86_400 and isinstance(scope, str)
                    and set(scope.split()) == set(credential.scopes) and not any(secret in token for secret in _secrets(credential)))
            except (ValueError, TypeError, AttributeError): valid = False
            if not valid: raise ValueError("BoldSign returned an invalid machine token, scope or expiry")
            _TOKEN_CACHE.put(cache_key, token, expires_in=ttl, now=started)
            if _TOKEN_CACHE.get(cache_key, now=time.monotonic()) is None: raise ValueError("BoldSign machine token expired before use")
        return {"Authorization": "Bearer " + token}, (*_secrets(credential), token)

    async def _request(self, method, path, *, params=None, body=None, statuses=(200,), empty=False, with_status=False):
        ticket = _REQUEST_CONTEXT.get()
        if ticket is None or ticket[0] is not self: raise ValueError("BoldSign request context required")
        _, credential = ticket
        if credential.expires_at is not None and credential.expires_at <= datetime.now(timezone.utc): raise ValueError("Issued credential expired")
        if isinstance(credential, BoldSignClientCredentials):
            require_machine_scopes(credential.scopes, (path,))
        auth, secrets = await self._authorization(credential)
        target = BASE + path
        if params: target += "?" + urlencode(params, doseq=True, quote_via=quote, safe="~")
        if _contains_secret({"path": path, "params": params, "body": body}, secrets):
            raise ValueError("Authentication material cannot be submitted as operation data")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, target, headers={**auth, "Accept": "application/json"}, json=body)
        if response.status_code not in statuses: raise _ResponseError(response.status_code)
        if empty:
            if response.content.strip(): raise ValueError("Expected the documented empty completed response")
            return None
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 2_000_000: raise ValueError("Expected bounded JSON metadata")
        try: result = response.json()
        except ValueError: raise ValueError("Invalid JSON metadata") from None
        if not isinstance(result, dict): raise ValueError("Expected the documented metadata object")
        if isinstance(credential, BoldSignClientCredentials) and _contains_secret(result, secrets):
            raise ValueError("Authentication material was withheld from the response")
        return (response.status_code, result) if with_status else result

    @staticmethod
    def _text(value):
        if value is not None and (not isinstance(value, str) or len(value) > 10_000): raise ValueError("Invalid metadata text")
        return value

    @staticmethod
    def _integer(value):
        if type(value) is not int or not 0 <= value <= 2**63 - 1: raise ValueError("Invalid metadata integer")
        return value

    @classmethod
    def _labels(cls, value):
        if value is None: return None
        if not isinstance(value, list) or len(value) > 50 or any(not isinstance(item, str) or not 1 <= len(item) <= 255 for item in value): raise ValueError("Invalid metadata tags")
        return list(value)

    @classmethod
    def _document(cls, row, *, status_only=False):
        result = {"id": _resource_id(row.get("documentId"))}
        if not isinstance(row.get("status"), str) or not row["status"]: raise ValueError("Document status is missing")
        result["status"] = cls._text(row["status"])
        for key in ("activityAction",):
            if key in row: result[key] = cls._text(row[key])
        for key in ("createdDate", "activityDate", "expiryDate", "scheduledSendTime"):
            if key in row: result[key] = cls._integer(row[key]) if row[key] is not None else None
        if not status_only:
            result["name"] = cls._text(row.get("messageTitle"))
            if "labels" in row: result["labels"] = cls._labels(row["labels"])
            if "isDeleted" in row:
                if type(row["isDeleted"]) is not bool: raise ValueError("Invalid deleted flag")
                result["isDeleted"] = row["isDeleted"]
        return result

    @classmethod
    def _template(cls, row, *, detail=False):
        result = {"id": _resource_id(row.get("templateId" if detail else "documentId")), "name": cls._text(row.get("title" if detail else "templateName"))}
        if "createdDate" in row: result["createdDate"] = cls._integer(row["createdDate"])
        for key in ("labels", "templateLabels"):
            if key in row: result[key] = cls._labels(row[key])
        return result

    @classmethod
    def _contact(cls, row, *, detail=False):
        result = {"id": _resource_id(row.get("contactId" if detail else "id"))}
        for key in ("name", "email", "companyName", "jobTitle"):
            if key in row: result[key] = cls._text(row[key])
        return result

    @classmethod
    def _group(cls, row):
        result = {"id": _resource_id(row.get("groupId")), "name": cls._text(row.get("groupName"))}
        if "directories" in row:
            value = row["directories"]
            if value is not None and (not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) or len(item) > 200 for item in value)): raise ValueError("Invalid group directories")
            result["directories"] = value
        return result

    @classmethod
    def _page(cls, body, config, project, *, documents=False):
        details = body.get("pageDetails")
        if not isinstance(details, dict): raise ValueError("Paging metadata is missing")
        page, size, total = (cls._integer(details.get(key)) for key in ("page", "pageSize", "totalRecordsCount"))
        if page != config.page or size != config.page_size: raise ValueError("Provider returned a different page or page size")
        if "result" not in body: raise ValueError("Result collection is missing")
        raw = body.get("result")
        if raw is None and total == 0: raw = []  # The public schema explicitly permits a null empty collection.
        if not isinstance(raw, list) or len(raw) > size or any(not isinstance(row, dict) for row in raw): raise ValueError("Invalid bounded result collection")
        items = [project(row) for row in raw]
        if len({row["id"] for row in items}) != len(items): raise ValueError("Provider repeated resource IDs")
        expected_pages = math.ceil(total / size)
        if "totalPages" in details and cls._integer(details["totalPages"]) != expected_pages: raise ValueError("Contradictory total pages")
        last_cursor = None
        if documents and raw and "nextCursor" in raw[-1]:
            last_cursor = cls._integer(raw[-1]["nextCursor"])
            if getattr(config, "next_cursor", None) == last_cursor: raise ValueError("Document cursor did not advance")
        if documents and getattr(config, "next_cursor", None) is not None:
            return {"items": items, "page": page, "total_records": total, "has_more": None, "next_page": None, "last_document_cursor": last_cursor, "complete": False, "pagination_unknown": True}
        offset = (page - 1) * size
        if len(raw) != min(size, max(0, total - offset)): raise ValueError("Incomplete or contradictory result page")
        more = offset + len(raw) < total
        if more and not raw: raise ValueError("An empty page cannot continue")
        cursor_required = bool(documents and more and page * size >= 10_000)
        if cursor_required and last_cursor is None: raise ValueError("Document cursor required beyond 10,000 records")
        return {"items": items, "page": page, "total_records": total, "has_more": more,
            "next_page": page + 1 if more and not cursor_required else None, "last_document_cursor": last_cursor,
            "cursor_required": cursor_required, "complete": not more}

    @staticmethod
    def _scope(credential, kind, identifier):
        allowed = getattr(credential, "allowed_" + kind + "_ids")
        if identifier not in allowed: raise ValueError("Resource is outside saved scope")
        return identifier

    async def _owned_member(self, identifier, *, group=False):
        endpoint = "/v1/contactGroups/list" if group else "/v1/contacts/list"
        project = self._group if group else self._contact
        for page in range(1, 21):
            config = BoldSignGroupsConfig(page=page, page_size=100) if group else BoldSignContactsConfig(page=page, page_size=100)
            params = {"page": page, "pageSize": 100, "contactType": "MyContacts"}
            if group: params = {key[0].upper() + key[1:]: value for key, value in params.items()}
            body = await self._request("GET", endpoint, params=params)
            result = self._page(body, config, project)
            if any(item["id"] == identifier for item in result["items"]): return
            if not result["has_more"]: raise ValueError("Resource is not a current MyContacts member")
        raise ValueError("Owned-resource membership exceeded the bounded 2,000-record check")

    async def _selected(self, credential, config):
        if hasattr(config, "document_id"):
            identifier = self._scope(credential, "document", config.document_id)
            body = await self._request("GET", "/v1/document/properties", params={"documentId": identifier})
            item = self._document(body)
        elif hasattr(config, "template_id"):
            identifier = self._scope(credential, "template", config.template_id)
            body = await self._request("GET", "/v1/template/properties", params={"templateId": identifier})
            item = self._template(body, detail=True)
        else:
            group = hasattr(config, "group_id")
            identifier = self._scope(credential, "contact_group" if group else "contact", config.group_id if group else config.contact_id)
            await self._owned_member(identifier, group=group)
            body = await self._request("GET", "/v1/contactGroups/get" if group else "/v1/contacts/get", params={"groupId" if group else "id": identifier})
            item = self._group(body) if group else self._contact(body, detail=True)
        if item["id"] != identifier: raise ValueError("Provider returned a different selected resource")
        return body, item

    @staticmethod
    def _contact_values(config):
        body = {"Email": config.email, "Name": config.name}
        if config.company_name is not None: body["CompanyName"] = config.company_name
        if config.job_title is not None: body["JobTitle"] = config.job_title
        return body

    async def _execute(self, inputs):
        ticket = _REQUEST_CONTEXT.get()
        _, credential = ticket
        config = self.config.config
        output = {"operation": config.operation}
        attempted, resource_id = False, None
        try:
            if _contains_secret(config.model_dump(), _secrets(credential)):
                raise ValueError("Authentication material cannot be submitted as operation data")
            if isinstance(credential, BoldSignClientCredentials):
                require_machine_scopes(credential.scopes, OPERATION_ENDPOINTS[config.operation])
            if config.operation == "check_connection":
                probe = BoldSignDocumentsConfig(page=1, page_size=1)
                body = await self._request("GET", "/v1/document/list", params={"page": 1, "pageSize": 1})
                self._page(body, probe, self._document, documents=True)
                return {**output, "status": "success", "reachable": True, "proves": "reachability"}
            if config.operation.startswith("list_"):
                params = {"page": config.page, "pageSize": config.page_size}
                if config.search_key: params["searchKey"] = config.search_key
                if config.operation == "list_documents":
                    if config.next_cursor is None and (config.page - 1) * config.page_size >= 10_000: raise ValueError("Use the documented document cursor beyond 10,000 records")
                    if config.next_cursor is not None: params["nextCursor"] = config.next_cursor
                    if config.status_filter: params["status"] = config.status_filter
                    path, project, allowed = "/v1/document/list", self._document, credential.allowed_document_ids
                elif config.operation == "list_templates":
                    params["templateType"] = "mytemplates"
                    path, project, allowed = "/v1/template/list", self._template, credential.allowed_template_ids
                elif config.operation == "list_contacts":
                    params["contactType"] = "MyContacts"
                    path, project, allowed = "/v1/contacts/list", self._contact, credential.allowed_contact_ids
                elif config.operation == "list_contact_groups":
                    params["contactType"] = "MyContacts"
                    params = {key[0].upper() + key[1:]: value for key, value in params.items()}
                    path, project, allowed = "/v1/contactGroups/list", self._group, credential.allowed_contact_group_ids
                else: raise ValueError("Unsupported list operation")
                result = self._page(await self._request("GET", path, params=params), config, project, documents=config.operation == "list_documents")
                result["items"] = [row for row in result["items"] if row["id"] in allowed]
                return {**output, "status": "success", **result}
            if config.operation == "create_contact":
                if not credential.allow_contact_create: raise ValueError("Saved credential does not allow contact creation")
                attempted = True
                status, body = await self._request("POST", "/v1/contacts/create", body=[self._contact_values(config)], statuses=(200, 201), with_status=True)
                key = "contacts" if status == 200 else "createdContacts"
                rows = body.get(key)
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict): raise ValueError("Expected one created contact in the status-specific documented envelope")
                resource_id = _resource_id(rows[0].get("id"))
                if rows[0].get("email") != config.email: raise ValueError("Created contact email did not match")
                return {**output, "status": "success", "resource_id": resource_id, "write_attempted": True, "http_status": status, "readback_required": True, "saved_scope_required": True}
            body, item = await self._selected(credential, config)
            resource_id = item["id"]
            if config.operation in {"get_document", "get_template", "get_contact", "get_contact_group"}: return {**output, "status": "success", "item": item}
            if config.operation == "get_document_status": return {**output, "status": "success", "item": self._document(body, status_only=True)}
            if config.operation == "get_document_history":
                if "documentHistory" not in body: raise ValueError("History metadata is unavailable")
                rows = body.get("documentHistory")
                if rows is None: rows = []  # DocumentProperties explicitly defines nullable history.
                if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows): raise ValueError("History exceeded the bounded metadata contract")
                history = [{"id": _resource_id(row.get("id")), "action": self._text(row.get("action")), "timestamp": self._integer(row.get("timestamp"))} for row in rows]
                if len({row["id"] for row in history}) != len(history) or any(not row["action"] for row in history): raise ValueError("Invalid history metadata")
                return {**output, "status": "success", "document_id": resource_id, "items": history, "record_count": len(history)}
            if config.operation == "update_contact":
                attempted = True
                await self._request("PUT", "/v1/contacts/update", params={"id": resource_id}, body=self._contact_values(config), empty=True)
                return {**output, "status": "success", "resource_id": resource_id, "write_attempted": True, "readback_required": True}
            if config.operation == "delete_contact":
                attempted = True
                await self._request("DELETE", "/v1/contacts/delete", params={"id": resource_id}, statuses=(204,), empty=True)
                return {**output, "status": "success", "resource_id": resource_id, "write_attempted": True, "absence_readback_required": True}
            if config.operation not in WRITES: raise ValueError("Unsupported operation")
            template = hasattr(config, "template_id")
            adding = config.operation.startswith("add_")
            label_key = "templateLabels" if template else "labels"
            if label_key not in item or item[label_key] is None: raise ValueError("Current tag metadata is unavailable for readback")
            before = set(item[label_key])
            path = "/v1/" + ("template" if template else "document") + ("/addTags" if adding else "/deleteTags")
            payload = {"TemplateId": resource_id, "TemplateLabels": config.tags} if template else {"DocumentId": resource_id, "Tags": config.tags}
            attempted = True
            await self._request("PATCH" if adding else "DELETE", path, body=payload, empty=True)
            _, readback = await self._selected(credential, config)
            expected = before.union(config.tags) if adding else before.difference(config.tags)
            if readback.get(label_key) is None or set(readback[label_key]) != expected: raise ValueError("Exact selected tag readback did not match")
            return {**output, "status": "success", "item": readback, "write_attempted": True, "readback_verified": True}
        except (ValueError, SSRFError, httpx.HTTPError) as exc:
            result = {**output, "status": "error", "error": "BoldSign did not confirm this operation; check current key, region, permissions, saved scope, ownership, expiry and response contract"}
            if isinstance(exc, _ResponseError):
                result["http_status"] = exc.status
                if exc.status in {404, 410}: result["not_found"] = True
            if attempted:
                result.update(write_attempted=True, outcome_uncertain=True, readback_required=True)
                if resource_id is not None: result["resource_id"] = resource_id
            return result
