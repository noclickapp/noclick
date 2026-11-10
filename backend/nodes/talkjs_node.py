"""Native TalkJS app-bound REST workflows with per-request admin HS256 JWTs.

Existing server-side secret only. No frontend JWT, login, key/admin/billing API.
Explicit writes can change real users/chat; preparation executes none of them.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import math
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
from uuid import uuid4
import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-talkjs"
FAMILIES = ("talkjs_server_secret",)
API_BASE = "https://api.talkjs.com/v1"
API_VERSION = "2024-01-01"
ID_PATTERN = r"[A-Za-z0-9_-]{1,128}"
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
WRITE_OPS = ("sync_user", "create_conversation", "update_conversation_metadata", "delete_conversation", "send_message", "update_message", "delete_message")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value):
        raise ValueError("Use an exact bounded TalkJS resource ID with letters, digits, underscores or hyphens")
    return value


def _secret_value(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 4096 or not value.startswith(("sk_test", "sk_live")) or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("Supply the existing app server secret beginning sk_test or sk_live")
    return value


class TalkJSServerSecretCredential(BaseModel):
    credential_type: Literal["talkjs_server_secret"] = Field("talkjs_server_secret", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(..., title="Existing App ID", max_length=128, description="Exact existing TalkJS app. This configured identifier alone is not account identity proof.")
    server_secret: str = Field(..., title="Existing Server Secret", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-credential-url": "https://talkjs.com/docs/REST_API/#authentication",
        "x-credential-instructions": "Supply the existing app ID and associated server secret. Native backend uses installed PyJWT to sign a fresh 30-second HS256 admin token per REST request, iss=app ID and tokenType=admin, without sub. Tokens remain in memory and never appear in frontend code or output. Admin credentials have full app data access; native operation allowlisting does not reduce provider rights. No environment fallback, login, key creation/rotation or public catalog identity proof. Direct secret Bearer authentication is legacy and not used.",
    })
    _app = field_validator("app_id")(_id)
    _secret = field_validator("server_secret")(_secret_value)


def _op(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,3}", value):
        value = int(value)
    if type(value) is not int:
        raise ValueError("Use a whole page limit")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 16384 or '\x00' in value:
        raise ValueError("Supply bounded nonempty text")
    return value


def _metadata(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 16384:
        raise ValueError("Supply a small JSON object of string or null metadata values")
    try:
        result = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(result, dict) or not result or len(result) > 20 or any(not isinstance(k, str) or not 1 <= len(k) <= 64 or any(ord(c) < 32 for c in k) or v is not None and (not isinstance(v, str) or len(v) > 2048 or '\x00' in v) for k, v in result.items()):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Use a small flat JSON object with string or null metadata values") from None
    return result


def _dynamic(field, parent=None):
    result = {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True}, "x-resource-type": "talkjs_user" if field == "sender_id" else "talkjs_" + field.removesuffix("_id"), "x-resource-id-path": field}
    if parent:
        result["x-dynamic-options"]["depends_on"] = parent
    return result


class TalkJSOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TalkJSPage(TalkJSOperation):
    limit: int = Field(20, ge=1, le=100, description="One bounded page, maximum 100 users/messages. Conversation pages have a separate cap of 30.")
    starting_after: Optional[str] = Field(None, title="Starting After ID", max_length=128, description="Documented startingAfter cursor. The current scoped resource is checked before use; no arbitrary provider URL.")
    _limit = field_validator("limit", mode="before")(_whole)
    @field_validator("starting_after")
    @classmethod
    def cursor(cls, value):
        return _id(value) if value is not None else None


class TalkJSUserScope(TalkJSOperation):
    user_id: str = Field(..., title="User", json_schema_extra=_dynamic("user_id"))
    _user = field_validator("user_id")(_id)


class TalkJSConversationScope(TalkJSOperation):
    conversation_id: str = Field(..., title="Conversation", json_schema_extra=_dynamic("conversation_id"))
    _conversation = field_validator("conversation_id")(_id)


class TalkJSMessageScope(TalkJSConversationScope):
    message_id: str = Field(..., title="Message", json_schema_extra=_dynamic("message_id", "conversation_id"))
    _message = field_validator("message_id")(_id)


class TalkJSChanges(TalkJSOperation):
    confirm_changes: bool = Field(False, description="Confirm this explicit real app data change. Message sends can notify participants; deletion is irreversible. No live effect is performed during source preparation.")


class TalkJSMetadata(TalkJSOperation):
    metadata_mode: Literal["keep", "merge", "clear"] = Field("keep", description="Keep omits custom metadata. Merge sends only explicit keys; null deletes a key. Clear sends custom:null.")
    custom_metadata_json: Optional[str] = Field(None, title="Custom Metadata (JSON)", max_length=16384, json_schema_extra={"ui:widget": "textarea"}, description="Flat JSON object of string/null values. Blank means omitted; no generic request body.")
    @model_validator(mode="after")
    def metadata_intent(self):
        if self.metadata_mode == "merge":
            _metadata(self.custom_metadata_json)
        elif self.custom_metadata_json is not None and self.custom_metadata_json.strip():
            raise ValueError("Choose merge when supplying custom metadata")
        return self


class TalkJSConversationPage(TalkJSPage):
    limit: int = Field(20, ge=1, le=30, description="Native conversation cap 30 follows the stricter current REST/conversation reference; the user-history page inconsistently says 100.")



class TalkJSCheckConfig(TalkJSOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected App Access", "Connection")



class TalkJSListUsersConfig(TalkJSPage):
    operation: Literal["list_users"] = _op("list_users", "List App User Metadata", "Users")
    include_names: bool = Field(False, description="Explicitly include user names. Email, phone, avatars and push tokens are always omitted.")


class TalkJSGetUserConfig(TalkJSUserScope):
    operation: Literal["get_user"] = _op("get_user", "Get User Metadata", "Users")
    include_names: bool = Field(False)


class TalkJSSyncUserConfig(TalkJSUserScope, TalkJSChanges, TalkJSMetadata):
    operation: Literal["sync_user"] = _op("sync_user", "Create or Update User Metadata", "Users")
    name: str = Field(..., max_length=256)
    locale: Optional[str] = Field(None, max_length=32)
    _name = field_validator("name")(_text)


class TalkJSListConversationsConfig(TalkJSConversationPage):
    operation: Literal["list_conversations"] = _op("list_conversations", "List App Conversations", "Conversations")
    include_subject: bool = Field(False)


class TalkJSUserConversationsConfig(TalkJSUserScope, TalkJSConversationPage):
    operation: Literal["list_user_conversations"] = _op("list_user_conversations", "List User Conversation History", "Conversations")
    include_subject: bool = Field(False)


class TalkJSGetConversationConfig(TalkJSConversationScope):
    operation: Literal["get_conversation"] = _op("get_conversation", "Get Conversation Metadata", "Conversations")
    include_subject: bool = Field(False)


class TalkJSCreateConversationConfig(TalkJSConversationScope, TalkJSChanges, TalkJSMetadata):
    operation: Literal["create_conversation"] = _op("create_conversation", "Create Private Conversation", "Conversations")
    participant_ids: list[str] = Field(..., min_length=1, max_length=10, json_schema_extra={"ui:widget": "list"}, description="Exact existing app user IDs; native checks each before PUT. No messages are sent by this operation. Absence preflight is not an atomic create guarantee; PUT merges if a race creates the ID.")
    subject: Optional[str] = Field(None, max_length=512)
    @field_validator("participant_ids")
    @classmethod
    def participants(cls, value):
        ids = [_id(v) for v in value]
        if len(set(ids)) != len(ids):
            raise ValueError("Supply unique participant IDs")
        return ids


class TalkJSUpdateConversationConfig(TalkJSConversationScope, TalkJSChanges, TalkJSMetadata):
    operation: Literal["update_conversation_metadata"] = _op("update_conversation_metadata", "Update Conversation Metadata", "Conversations")
    subject_mode: Literal["keep", "set", "clear"] = Field("keep")
    subject: Optional[str] = Field(None, max_length=512)
    @model_validator(mode="after")
    def changes(self):
        if self.subject_mode == "set":
            _text(self.subject)
        elif self.subject is not None:
            raise ValueError("Choose set when supplying a subject")
        if self.subject_mode == "keep" and self.metadata_mode == "keep":
            raise ValueError("Choose an explicit metadata change")
        return self


class TalkJSDeleteConversationConfig(TalkJSConversationScope, TalkJSChanges):
    operation: Literal["delete_conversation"] = _op("delete_conversation", "Delete Conversation and All Messages", "Conversations")



class TalkJSParticipationConfig(TalkJSUserScope, TalkJSConversationScope):
    operation: Literal["get_participation"] = _op("get_participation", "Get Scoped Participant Metadata", "Participants")



class TalkJSListMessagesConfig(TalkJSConversationScope, TalkJSPage):
    operation: Literal["list_messages"] = _op("list_messages", "List Conversation Message Metadata", "Messages")
    include_text: bool = Field(False, description="Explicitly include private message text; attachments, content blocks, locations, reactions, read receipts and custom fields are always omitted.")


class TalkJSGetMessageConfig(TalkJSMessageScope):
    operation: Literal["get_message"] = _op("get_message", "Get Scoped Message Metadata", "Messages")
    include_text: bool = Field(False)


class TalkJSSendMessageConfig(TalkJSConversationScope, TalkJSChanges):
    operation: Literal["send_message"] = _op("send_message", "Send Explicit User Message", "Messages")
    sender_id: str = Field(..., title="Existing Sender", json_schema_extra=_dynamic("sender_id", "conversation_id"), description="Must be a current ReadWrite participant in this conversation. This is a real send and may trigger role-based notifications.")
    text: str = Field(..., max_length=16384, json_schema_extra={"ui:widget": "textarea"})
    idempotency_key: str = Field(..., max_length=128, description="Explicit unique key within this conversation. Provider retains it for 24 hours; the native node never automatically retries.")
    _sender = field_validator("sender_id")(_id)
    _text_value = field_validator("text", "idempotency_key")(_text)


class TalkJSUpdateMessageConfig(TalkJSMessageScope, TalkJSChanges, TalkJSMetadata):
    operation: Literal["update_message"] = _op("update_message", "Update Explicit Message", "Messages")
    text: Optional[str] = Field(None, max_length=16384, json_schema_extra={"ui:widget": "textarea"})
    mark_edited: bool = Field(False, description="Documented false default; true sets editedAt and may show an edited indicator.")
    @model_validator(mode="after")
    def message_intent(self):
        if self.text is not None:
            _text(self.text)
        if self.text is None and self.metadata_mode == "keep" and not self.mark_edited:
            raise ValueError("Choose an explicit message change")
        return self


class TalkJSDeleteMessageConfig(TalkJSMessageScope, TalkJSChanges):
    operation: Literal["delete_message"] = _op("delete_message", "Delete Explicit Message", "Messages")


TalkJSConfig = Annotated[Union[TalkJSCheckConfig, TalkJSListUsersConfig, TalkJSGetUserConfig, TalkJSSyncUserConfig, TalkJSListConversationsConfig, TalkJSUserConversationsConfig, TalkJSGetConversationConfig, TalkJSCreateConversationConfig, TalkJSUpdateConversationConfig, TalkJSDeleteConversationConfig, TalkJSParticipationConfig, TalkJSListMessagesConfig, TalkJSGetMessageConfig, TalkJSSendMessageConfig, TalkJSUpdateMessageConfig, TalkJSDeleteMessageConfig], Field(discriminator="operation")]

class TalkJSNodeConfig(NodeConfig[TalkJSConfig, TalkJSServerSecretCredential]):
    pass

class TalkJSAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES:
        raise ValueError("TalkJS credential family is unsupported")
    try:
        shaped = TalkJSServerSecretCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except Exception:
        raise ValueError("TalkJS native app ID or existing server secret is invalid") from None
    return {**data, **shaped}


def _binding(data):
    return (data["credential_type"], data["app_id"], data["server_secret"])

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("TalkJS configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("TalkJS saved credential family is missing or unsupported")


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


async def _current_data(data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
    if not credential_id:
        return _shape(data)
    from utils.credentials import resolve_credential_with_owner_fallback
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    # Staging's resolver checks the current row's revocation, access and type,
    # including workflow-owner/lender grants. Reuse that policy on every request.
    result = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
    if result is None:
        raise ValueError("TalkJS current credential is unavailable or access denied")
    if result.get("credential_type") not in FAMILIES:
        raise ValueError("TalkJS current credential family is unsupported")
    return {**_shape(result), "_talkjs_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_talkjs_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("TalkJS picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id or context.get("_workflow_id")})
    return result


def _authority(context):
    return {"pool": context.get("_approval_pool"), "user_id": context.get("_user_id"), "credential_id": context.get("_credential_id"), "organization_id": context.get("_organization_id"), "workflow_id": context.get("_workflow_id")}


def _bounded(value, depth=0):
    if type(value) is int and value.bit_length() > 256:
        raise ValueError("Unverified JSON integer bound")
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("talkjs_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "TalkJS private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


def _protect_transport_logs():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict) if name.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)


def _route(method, parts):
    if not isinstance(parts, tuple) or not parts:
        raise ValueError("Unsupported native TalkJS route")
    allowed = ()
    if parts[0] == "users":
        if len(parts) == 1:
            allowed = ("GET",)
        elif len(parts) == 2:
            _id(parts[1]); allowed = ("GET", "PUT")
        elif len(parts) == 3 and parts[2] == "conversations":
            _id(parts[1]); allowed = ("GET",)
    elif parts[0] == "conversations":
        if len(parts) == 1:
            allowed = ("GET",)
        elif len(parts) == 2:
            _id(parts[1]); allowed = ("GET", "PUT", "DELETE")
        elif len(parts) == 3 and parts[2] == "messages":
            _id(parts[1]); allowed = ("GET", "POST")
        elif len(parts) == 4 and parts[2] in ("messages", "participants"):
            _id(parts[1]); _id(parts[3])
            allowed = ("GET", "PUT", "DELETE") if parts[2] == "messages" else ("GET",)
    if method not in allowed:
        raise ValueError("Unsupported native TalkJS route or method")
    return "/".join(parts)


async def _request(data, context, method, parts, *, body=None, params=None, allow_missing=False):
    route = _route(method, parts)
    if params is not None and (not isinstance(params, dict) or any(key not in ("limit", "startingAfter", "orderBy", "orderDirection") for key in params)):
        raise ValueError("Unsupported native TalkJS query")
    current = await _current_data(data, **_authority(context))
    if _binding(current) != _binding(data):
        raise ValueError("TalkJS current credential or app changed; rerun with current authority")
    if body is not None:
        _bounded(body)
        if len(json.dumps(body, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("TalkJS native body exceeds the local input bound")
    _protect_transport_logs()
    private = _PRIVATE_REQUEST.set(True)
    try:
        now = int(time.time())
        # Fresh per request; jti uniqueness does not imply provider replay prevention.
        token = jwt.encode({"tokenType": "admin", "iss": current["app_id"], "iat": now, "exp": now + 30, "jti": uuid4().hex}, current["server_secret"], algorithm="HS256")
        if not isinstance(token, str) or not token:
            raise TalkJSAPIError("TalkJS admin token could not be prepared")
        url = API_BASE + "/" + _id(current["app_id"]) + "/" + route
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, params=params, json=body, headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Bearer " + token, "TalkJS-REST-Version": API_VERSION}) as response:
                payload = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(payload) + len(chunk) > MAX_BYTES:
                        raise TalkJSAPIError("TalkJS response exceeds the local byte bound; a write may have applied; no retry")
                    payload.extend(chunk)
                status = response.status_code
                if status in (401, 403):
                    raise TalkJSAPIError(f"TalkJS HTTP {status}: current app authority was rejected", authority_rejected=True)
                if status == 404 and allow_missing and method == "GET":
                    return None
                if status != 200:
                    raise TalkJSAPIError(f"TalkJS HTTP {status}: resource or result is unverified; a write may have applied; no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise TalkJSAPIError("TalkJS documented JSON success is unverified; a write may have applied; no retry")
                try:
                    raw = json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(raw)
                    return _redact(_redact(raw, current["server_secret"]), token)
                except (ValueError, UnicodeError, RecursionError):
                    raise TalkJSAPIError("TalkJS response JSON is unverified; a write may have applied; no retry") from None
        # Success is determined by HTTP status, not invented body status markers.
    except TalkJSAPIError:
        raise
    except (jwt.PyJWTError, httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise TalkJSAPIError("TalkJS request outcome is unverified; a write may have applied; no automatic retry") from None
    finally:
        _PRIVATE_REQUEST.reset(private)


def _returned_id(value):
    try:
        result = _id(value)
        if "[redacted]" in result:
            raise ValueError()
        return result
    except ValueError:
        raise TalkJSAPIError("TalkJS resource identifier is unverified") from None


def _stamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise TalkJSAPIError("TalkJS timestamp is unverified")
    return value


def _optional_text(raw, key, output, *, limit=512):
    if key in raw:
        value = raw[key]
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise TalkJSAPIError("TalkJS metadata field is unverified")
        output[key] = value


def _user(raw, wanted=None, *, names=False):
    if not isinstance(raw, dict):
        raise TalkJSAPIError("TalkJS user response is unverified")
    identifier = _returned_id(raw.get("id"))
    if wanted is not None and identifier != wanted:
        raise TalkJSAPIError("TalkJS returned another user")
    result = {"id": identifier, "createdAt": _stamp(raw.get("createdAt"))}
    for key in ("role", "locale"):
        _optional_text(raw, key, result, limit=128)
    if names:
        _optional_text(raw, "name", result, limit=256)
    return result


def _participation(raw, wanted=None, *, embedded=False):
    if not isinstance(raw, dict) or raw.get("access") not in ("ReadWrite", "Read", "None") or not (type(raw.get("notify")) is bool or raw.get("notify") == "MentionsOnly"):
        raise TalkJSAPIError("TalkJS participant response is unverified")
    identifier = _returned_id(wanted if embedded else raw.get("id"))
    if wanted is not None and not embedded and identifier != wanted:
        raise TalkJSAPIError("TalkJS returned another participant")
    result = {"id": identifier, "access": raw["access"], "notify": raw["notify"]}
    if "joinedAt" in raw or not embedded:
        result["joinedAt"] = _stamp(raw.get("joinedAt"))
    return result


def _conversation(raw, wanted=None, *, subject=False, user=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("participants"), dict) or len(raw["participants"]) > MAX_ROWS:
        raise TalkJSAPIError("TalkJS conversation response is unverified")
    identifier = _returned_id(raw.get("id"))
    if wanted is not None and identifier != wanted:
        raise TalkJSAPIError("TalkJS returned another conversation")
    participants = { _returned_id(uid): _participation(row, uid, embedded=True) for uid, row in raw["participants"].items() }
    if user is not None and user not in participants:
        raise TalkJSAPIError("TalkJS user history returned a conversation without the selected participant")
    result = {"id": identifier, "createdAt": _stamp(raw.get("createdAt")), "participants": participants}
    if subject:
        _optional_text(raw, "subject", result)
    return result


def _message(raw, conversation, wanted=None, *, text=False):
    if not isinstance(raw, dict) or any(key not in raw for key in ("senderId", "editedAt")):
        raise TalkJSAPIError("TalkJS message response is unverified")
    identifier = _returned_id(raw.get("id"))
    if wanted is not None and identifier != wanted or raw.get("conversationId") != conversation:
        raise TalkJSAPIError("TalkJS returned another conversation's message")
    if raw.get("type") not in ("UserMessage", "SystemMessage") or raw.get("origin") not in ("rest", "email", "import", "web"):
        raise TalkJSAPIError("TalkJS message type or origin is unverified")
    sender = _returned_id(raw.get("senderId")) if raw.get("type") == "UserMessage" else None
    if raw.get("type") == "SystemMessage" and raw.get("senderId") is not None:
        raise TalkJSAPIError("TalkJS system message sender is unverified")
    result = {"id": identifier, "conversationId": conversation, "senderId": sender, "type": raw["type"], "origin": raw["origin"], "createdAt": _stamp(raw.get("createdAt")), "editedAt": _stamp(raw["editedAt"]) if raw.get("editedAt") is not None else None}
    if text:
        _optional_text(raw, "text", result, limit=65536)
    return result


def _page(raw, limit, projector, cursor=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or len(raw["data"]) > limit:
        raise TalkJSAPIError("TalkJS documented data page is unverified")
    rows = [projector(row) for row in raw["data"]]
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids) or cursor is not None and cursor in ids:
        raise TalkJSAPIError("TalkJS page repeats a resource ID")
    # No documented hasMore/total. A short nonempty page is not a completion proof.
    return {"results": rows, "next_starting_after": ids[-1] if ids else None, "collection_exhausted": True if not rows else None, "continuation_unknown": bool(rows)}


def _custom(cfg, body):
    if cfg.metadata_mode == "merge":
        body["custom"] = _metadata(cfg.custom_metadata_json)
    elif cfg.metadata_mode == "clear":
        body["custom"] = None
    return body


def _ack(raw, **scope):
    if raw != {}:
        raise TalkJSAPIError("TalkJS write response differs from documented empty JSON; a write may have applied; inspect independently without replay")
    return {**scope, "acknowledged": True, "http_status": 200, "independent_readback_verified": False, "delivery_verified": False, "notification_absence_verified": False}


async def _get_user(data, context, user, *, names=False, missing=False):
    raw = await _request(data, context, "GET", ("users", user), allow_missing=missing)
    return None if raw is None and missing else _user(raw, user, names=names)


async def _get_conversation(data, context, conv, *, subject=False, missing=False):
    raw = await _request(data, context, "GET", ("conversations", conv), allow_missing=missing)
    return None if raw is None and missing else _conversation(raw, conv, subject=subject)


async def _get_message(data, context, conv, message, *, text=False):
    return _message(await _request(data, context, "GET", ("conversations", conv, "messages", message)), conv, message, text=text)


class TalkJSNode(WorkflowNode):
    integration_type = "automation-talkjs"
    credential_provider_labels = {"talkjs": "Talkjs Account"}
    node_type = NODE_TYPE
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="TalkJS user metadata", proves="reachability", label_keys=("id",))
    edit_examples = ["List app conversation identifiers", "Read metadata of a selected conversation", "Create an explicit conversation with existing app users", "Send one explicitly confirmed message with an idempotency key"]

    @classmethod
    def get_config_model(cls):
        return TalkJSNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data)
        shaped = dict(config_data)
        if config_data.get("credentials") is not None:
            shaped["credentials"] = _shape(config_data["credentials"])
        try:
            TalkJSNodeConfig.model_validate(runtime_config_view(shaped, TalkJSNodeConfig))
        except ValueError:
            raise ValueError("TalkJS native configuration or selected credential scope is invalid") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data)
            shaped = dict(config_data)
            if config_data.get("credentials") is not None:
                shaped["credentials"] = _shape(config_data["credentials"])
            TalkJSNodeConfig.model_validate(runtime_config_view(shaped, TalkJSNodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["TalkJS native configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Lookup callers pass workflow scope to load_field_options, after this
        # hook. Bind only the trusted identifiers here; re-resolve with that
        # scope in the loader before any provider request.
        shaped = _shape(credential_data)
        if credential_id:
            shaped["_talkjs_authority"] = _LookupAuthority(pool, user_id, credential_id, None, None)
        return shaped

    @classmethod
    async def validate_credential_access(cls, data):
        # Staging's post-connect hook supplies only a decrypted blob, without
        # the saved row's ID or caller scope. Do not claim current-row proof.
        # The explicit test_connection operation and evidence collector use
        # the normal execution path and can establish protected reachability.
        return {"valid": None, "error": "Run Check Protected App Access to verify TalkJS reachability with current credential access"}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, TalkJSNodeConfig) or self.config.credentials is None:
            raise ValueError("TalkJS requires explicit native app credentials")
        cfg = self.config.config
        if cfg.operation in WRITE_OPS and not cfg.confirm_changes:
            raise ValueError("Confirm the explicit TalkJS app data change before any provider request")
        context = {"_approval_pool": (self.node_data or {}).get("_approval_pool"), "_credential_id": (self.node_data or {}).get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        data = await _current_data(self.config.credentials.model_dump(), **_authority(context))
        result = await self._operation(cfg, data, context)
        return {"status": "success", "operation": cfg.operation, "data": _redact(result, data["server_secret"])}

    @staticmethod
    async def _operation(cfg, data, context):
        op = cfg.operation
        if op in WRITE_OPS and not cfg.confirm_changes:
            raise ValueError("Confirm the explicit TalkJS app data change before any provider request")
        if op in ("test_connection", "list_users"):
            cursor, limit = (None, 1) if op == "test_connection" else (cfg.starting_after, cfg.limit)
            if cursor:
                await _get_user(data, context, cursor)
            params = {"limit": limit, **({"startingAfter": cursor} if cursor else {})}
            result = _page(await _request(data, context, "GET", ("users",), params=params), limit, lambda row: _user(row, names=getattr(cfg, "include_names", False)), cursor)
            if op == "test_connection":
                result.update({"protected_read_completed": True, "account_identity_verified": False, "write_permissions_verified": False})
            return result
        if op == "get_user":
            return await _get_user(data, context, cfg.user_id, names=cfg.include_names)
        if op == "sync_user":
            previous = await _get_user(data, context, cfg.user_id, missing=True)
            body = _custom(cfg, {"name": cfg.name})
            if cfg.locale is not None:
                body["locale"] = cfg.locale
            return _ack(await _request(data, context, "PUT", ("users", cfg.user_id), body=body), user_id=cfg.user_id, previously_present=previous is not None, atomic_creation_verified=False)
        if op in ("list_conversations", "list_user_conversations"):
            user = cfg.user_id if op == "list_user_conversations" else None
            if user:
                await _get_user(data, context, user)
            if cfg.starting_after:
                prior = await _get_conversation(data, context, cfg.starting_after)
                if user and user not in prior["participants"]:
                    raise ValueError("History cursor is not a participant conversation for the selected user")
            parts = ("users", user, "conversations") if user else ("conversations",)
            params = {"limit": cfg.limit, "orderBy": "createdAt", "orderDirection": "DESC", **({"startingAfter": cfg.starting_after} if cfg.starting_after else {})}
            return _page(await _request(data, context, "GET", parts, params=params), cfg.limit, lambda row: _conversation(row, subject=cfg.include_subject, user=user), cfg.starting_after)
        if op == "get_conversation":
            return await _get_conversation(data, context, cfg.conversation_id, subject=cfg.include_subject)
        if op == "create_conversation":
            if await _get_conversation(data, context, cfg.conversation_id, missing=True) is not None:
                raise ValueError("Selected conversation already exists; choose explicit metadata update")
            for user in cfg.participant_ids:
                await _get_user(data, context, user)
            body = _custom(cfg, {"participants": cfg.participant_ids})
            if cfg.subject is not None:
                body["subject"] = cfg.subject
            return _ack(await _request(data, context, "PUT", ("conversations", cfg.conversation_id), body=body), conversation_id=cfg.conversation_id, atomic_creation_verified=False, absence_preflight_completed=True)
        # Every child route is preceded by a current conversation witness.
        conversation = await _get_conversation(data, context, cfg.conversation_id)
        if op == "update_conversation_metadata":
            body = _custom(cfg, {})
            if cfg.subject_mode != "keep":
                body["subject"] = cfg.subject if cfg.subject_mode == "set" else None
            return _ack(await _request(data, context, "PUT", ("conversations", cfg.conversation_id), body=body), conversation_id=cfg.conversation_id)
        if op == "delete_conversation":
            return _ack(await _request(data, context, "DELETE", ("conversations", cfg.conversation_id)), conversation_id=cfg.conversation_id, absence_verified=False, irreversible=True)
        if op == "get_participation":
            await _get_user(data, context, cfg.user_id)
            if cfg.user_id not in conversation["participants"]:
                raise ValueError("Selected user is not a current participant of this conversation")
            return _participation(await _request(data, context, "GET", ("conversations", cfg.conversation_id, "participants", cfg.user_id)), cfg.user_id)
        if op == "list_messages":
            if cfg.starting_after:
                await _get_message(data, context, cfg.conversation_id, cfg.starting_after)
            params = {"limit": cfg.limit, **({"startingAfter": cfg.starting_after} if cfg.starting_after else {})}
            return _page(await _request(data, context, "GET", ("conversations", cfg.conversation_id, "messages"), params=params), cfg.limit, lambda row: _message(row, cfg.conversation_id, text=cfg.include_text), cfg.starting_after)
        if op == "send_message":
            await _get_user(data, context, cfg.sender_id)
            if conversation["participants"].get(cfg.sender_id, {}).get("access") != "ReadWrite":
                raise ValueError("Selected sender must be a current ReadWrite participant")
            raw = await _request(data, context, "POST", ("conversations", cfg.conversation_id, "messages"), body=[{"text": cfg.text, "sender": cfg.sender_id, "type": "UserMessage", "idempotencyKey": cfg.idempotency_key}])
            if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
                raise TalkJSAPIError("TalkJS message send acknowledgement is unverified; do not replay without inspecting the idempotency key")
            return {"conversation_id": cfg.conversation_id, "message_id": _returned_id(raw[0].get("id")), "acknowledged": True, "delivery_verified": False, "notification_delivery_verified": False, "independent_readback_verified": False, "idempotency_window_hours": 24}
        message = await _get_message(data, context, cfg.conversation_id, cfg.message_id, text=op == "get_message" and cfg.include_text)
        if op == "get_message":
            return message
        if op == "update_message":
            body = _custom(cfg, {"markEdited": cfg.mark_edited})
            if cfg.text is not None:
                body["text"] = cfg.text
            return _ack(await _request(data, context, "PUT", ("conversations", cfg.conversation_id, "messages", cfg.message_id), body=body), conversation_id=cfg.conversation_id, message_id=cfg.message_id)
        if op == "delete_message":
            return _ack(await _request(data, context, "DELETE", ("conversations", cfg.conversation_id, "messages", cfg.message_id)), conversation_id=cfg.conversation_id, message_id=cfg.message_id, absence_verified=False, irreversible=True)
        raise ValueError("Unsupported native TalkJS operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("user_id", "conversation_id", "message_id", "sender_id"):
            return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {})
        query = (search or "").strip() if isinstance(search, str) or search is None else None
        if query is None or len(query) > 128 or any(ord(c) < 32 for c in query):
            raise ValueError("Use a bounded TalkJS identifier search")
        parent = _id(context.get("conversation_id")) if field_name in ("message_id", "sender_id") else None
        data = await _current_data(credential_data, **_authority(context))
        binding = hashlib.sha256(json.dumps([field_name, parent, query, _binding(data), context.get("_user_id"), context.get("_credential_id"), context.get("_organization_id"), context.get("_workflow_id")], separators=(",", ":")).encode()).hexdigest()
        page, cursor, seen = 1, None, []
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 8192:
                    raise ValueError()
                saved = json.loads(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
                if not isinstance(saved, dict) or set(saved) != {"binding", "page", "cursor", "seen"} or saved["binding"] != binding or type(saved["page"]) is not int or not 2 <= saved["page"] <= 10 or not isinstance(saved["seen"], list) or len(saved["seen"]) > 180 or len(set(saved["seen"])) != len(saved["seen"]) or any(_id(v) != v for v in saved["seen"]) or not saved["seen"] or saved["cursor"] != saved["seen"][-1]:
                    raise ValueError()
                page, cursor, seen = saved["page"], _id(saved["cursor"]), saved["seen"]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise ValueError("TalkJS continuation belongs to another current actor, app, credential, parent or search") from None
        if field_name == "sender_id":
            if page_token:
                raise ValueError("Participant map has no documented pagination")
            conversation = await _get_conversation(data, context, parent)
            return {"options": [{"value": uid, "label": uid} for uid, row in conversation["participants"].items() if row["access"] == "ReadWrite" and (not query or query.casefold() in uid.casefold())], "next_page_token": None}
        while page <= 10:
            if field_name == "user_id":
                cfg = TalkJSListUsersConfig(starting_after=cursor, limit=20)
            elif field_name == "conversation_id":
                cfg = TalkJSListConversationsConfig(starting_after=cursor, limit=20)
            else:
                cfg = TalkJSListMessagesConfig(conversation_id=parent, starting_after=cursor, limit=20)
            result = await cls._operation(cfg, data, context)
            ids = [row["id"] for row in result["results"]]
            if set(seen).intersection(ids):
                raise TalkJSAPIError("TalkJS picker repeats resource IDs across pages")
            seen += ids
            more = bool(ids)
            if more and (page >= 10 or len(seen) > 180):
                raise TalkJSAPIError("TalkJS picker reached its bounded search before an empty page; supply an exact currently scoped ID")
            cursor, page = result["next_starting_after"], page + 1
            token = base64.urlsafe_b64encode(json.dumps({"binding": binding, "page": page, "cursor": cursor, "seen": seen}, separators=(",", ":")).encode()).decode().rstrip("=") if more else None
            options = [{"value": uid, "label": uid} for uid in ids if not query or query.casefold() in uid.casefold()]
            if options or not more:
                return {"options": options, "next_page_token": token}
        raise TalkJSAPIError("TalkJS picker exhaustion was not established within its local bound")
