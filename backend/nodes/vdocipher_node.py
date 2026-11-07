"""Closed VdoCipher v3 video actions; supplied Apisecret and current saved authority.

Upload policies and OTPs are sensitive action outputs, never logged here. Creating
an upload policy creates an empty asset; no file transfer or URL import is performed.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.credentials import credential_access_predicate
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE = "https://dev.vdocipher.com/api"
TYPE = "vdocipher_api_secret"
MAX_BYTES = 2 * 1024 * 1024
OPERATIONS = {"list_videos", "get_video", "update_video_metadata", "delete_video", "list_tags", "append_video_tags", "set_video_tags", "create_upload_policy", "create_replacement_upload_policy", "create_playback_authorization"}
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=256)]
Snapshot = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Use one VdoCipher asset or folder ID, without URL syntax")
    return value


def validate_raw_identifiers(config_data):
    # The shared runtime view coerces scalar string fields before Pydantic.
    # Asset IDs must already be strings, so check their original types first.
    config = config_data.get("config") if isinstance(config_data, dict) else None
    if isinstance(config, dict):
        for key in ("video_id", "folder_id"):
            if config.get(key) is not None and not isinstance(config[key], str):
                identifier(config[key])


def safe_text(value):
    if value is None:
        return value
    if not isinstance(value, str) or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value):
        raise ValueError("Use plain VdoCipher metadata text")
    return value


class VdoCipherAPISecretCredential(BaseModel):
    model_config = ConfigDict(title="VdoCipher API Secret", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://www.vdocipher.com/docs/server/authorization/"})
    credential_type: Literal["vdocipher_api_secret"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_secret: str = Field(..., min_length=1, max_length=4096, repr=False, title="API Secret", description="Supplied account API secret. Sent only as Authorization: Apisecret to the fixed v3 server; no OAuth, session mint or automatic rotation.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_secret")
    @classmethod
    def header_value(cls, value):
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Supply one VdoCipher API secret")
        return value

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed VdoCipher API secret")
    try:
        return VdoCipherAPISecretCredential.model_validate({k: v for k, v in data.items() if k not in {"_vdocipher_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("VdoCipher credential is invalid; reconnect it") from None


def authority(value):
    return TYPE, BASE, value.api_secret


async def fetch_snapshot(pool, credential_id, user_id, organization_id=None, *, workflow_id=None):
    # Keep this provider's optional current-grant checks local. Staging's
    # canonical predicate governs owner, user-share and organization access.
    workflow_guard = "" if workflow_id is None else """
      AND EXISTS (SELECT 1 FROM workflows w
          JOIN workflow_authorized_credentials a ON a.workflow_id = w.id
          WHERE w.id = $4 AND w.owner_id = $2 AND a.credential_id = c.id)
    """
    args = [credential_id, user_id, organization_id]
    if workflow_id is not None:
        args.append(workflow_id)
    async with pool.acquire() as conn:
        return await conn.fetchrow(f"""
          SELECT c.credential, c.credential_type, c.owner_id, c.token_version, c.revoked_at
          FROM credentials c WHERE c.id = $1
          AND {credential_access_predicate()} {workflow_guard}
        """, *args)


async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored VdoCipher credentials require a caller")
    from utils.database_pool import get_native_pool
    from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
    from utils.encryption import get_encryption
    pool = pool or get_native_pool()
    row = await fetch_snapshot(pool, credential_id, user_id, organization_id)
    if row is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if owner and str(owner) != str(user_id) and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            row = await fetch_snapshot(pool, credential_id, owner, organization_id, workflow_id=workflow_id)
    if row is None or row["revoked_at"] is not None or row["credential_type"] != TYPE or not row["owner_id"] or type(row["token_version"]) is not int or row["token_version"] < 0:
        raise ValueError("VdoCipher credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("VdoCipher credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("VdoCipher saved credential type does not match its row")
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
            raise ValueError("VdoCipher cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and self.anchor != binding:
            raise ValueError("VdoCipher saved credential changed during this call; inspect before retrying")
        self.anchor = binding
        return value


def op(value, title, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def resource():
    return {"x-resource-type": "vdocipher_video", "x-dynamic-options": {"field_name": "video_id", "searchable": True, "allow_custom": True}}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    _ids = field_validator("video_id", "folder_id", mode="before", check_fields=False)(lambda value: None if value is None else identifier(value))
    _texts = field_validator("title", "description", "search", mode="before", check_fields=False)(safe_text)


class ListVideos(Input):
    operation: Literal["list_videos"] = op("list_videos", "List Videos", "Videos")
    page: StrictInt = Field(1, ge=1, le=100000, title="Page")
    limit: StrictInt = Field(20, ge=1, le=40, title="Page Size", description="The current listing guide documents a maximum of 40; returns one page, newest first.")
    search: str | None = Field(None, max_length=256, title="ID or Title Search")
    tags: list[Text] = Field(default_factory=list, max_length=50, title="Required Tags", description="Case-sensitive AND filter. Commas inside tags are rejected.")
    folder_id: Identifier | None = Field(None, title="Folder ID", description="Optional exact folder from your dashboard; root denotes the top level. This filter does not prove account identity.")

    @field_validator("tags")
    @classmethod
    def tag_filter(cls, value):
        return validate_tags(value)


class Video(Input):
    video_id: Identifier = Field(..., title="Video", json_schema_extra=resource())


class GetVideo(Video):
    operation: Literal["get_video"] = op("get_video", "Get Video Metadata", "Videos")


class UpdateVideo(Video):
    operation: Literal["update_video_metadata"] = op("update_video_metadata", "Update Video Metadata", "Videos")
    title: Text = Field(..., title="New Title")
    description: str | None = Field(None, max_length=8192, title="New Description", description="Omit to preserve it. Use Clear Description for an explicit empty value.")
    clear_description: bool = Field(False, title="Clear Description")
    expected_snapshot: Snapshot = Field(..., title="Expected Metadata Snapshot", description="From Get Video. A local preflight condition, not an atomic provider write fence.")

    @model_validator(mode="after")
    def no_conflict(self):
        if self.clear_description and self.description is not None:
            raise ValueError("Choose a description or Clear Description")
        return self


class DeleteVideo(Video):
    operation: Literal["delete_video"] = op("delete_video", "Delete Video and Files", "Videos")
    expected_snapshot: Snapshot = Field(..., title="Expected Metadata Snapshot")
    expected_title: Text = Field(..., title="Expected Title", description="Confirm the exact owned disposable asset. Deletion may leave cached playback briefly available; it is not immediate erasure.")


class ListTags(Input):
    operation: Literal["list_tags"] = op("list_tags", "List Tags", "Tags")
    page: StrictInt = Field(1, ge=1, le=100000, title="Page", description="The tag endpoint always returns up to 10 tags; a full page needs a further read.")
    search: str | None = Field(None, max_length=256, title="Tag Search")


class TagInput(Video):
    tags: list[Text] = Field(..., max_length=50, title="Tags")
    _tags = field_validator("tags")(lambda value: validate_tags(value))


class AppendTags(TagInput):
    operation: Literal["append_video_tags"] = op("append_video_tags", "Append Video Tags", "Tags")
    tags: list[Text] = Field(..., min_length=1, max_length=50, title="Tags to Append")


class SetTags(TagInput):
    operation: Literal["set_video_tags"] = op("set_video_tags", "Replace Video Tags", "Tags")
    expected_snapshot: Snapshot = Field(..., title="Expected Metadata Snapshot", description="Replace all current tags. An empty array clears them. Local preflight only.")


class CreateUpload(Input):
    operation: Literal["create_upload_policy"] = op("create_upload_policy", "Create Video Upload Policy", "Upload Metadata")
    title: Text = Field(..., title="New Video Title", description="This call immediately creates an empty pre-upload asset. It does not upload media or complete encoding.")
    folder_id: Identifier | None = Field(None, title="Folder ID", description="Optional exact dashboard folder ID. Omit for the documented top-level root default. The node performs no file transfer or remote URL import.")


class ReplaceUpload(Video):
    operation: Literal["create_replacement_upload_policy"] = op("create_replacement_upload_policy", "Create Replacement Upload Policy", "Upload Metadata")
    expected_snapshot: Snapshot = Field(..., title="Expected Metadata Snapshot")


class Playback(Video):
    operation: Literal["create_playback_authorization"] = op("create_playback_authorization", "Create Playback Authorization", "Playback")
    ttl: StrictInt = Field(300, ge=300, le=21600, title="OTP Validity Seconds", description="Local range: 5 minutes to 6 hours. This is validity before playback starts, not the playback duration. Advanced watermark/IP/offline controls are excluded.")


Config = Annotated[Union[ListVideos, GetVideo, UpdateVideo, DeleteVideo, ListTags, AppendTags, SetTags, CreateUpload, ReplaceUpload, Playback], Field(discriminator="operation")]


class VdoCipherNodeConfig(NodeConfig[Config, VdoCipherAPISecretCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def validate_tags(value):
    if not isinstance(value, list) or len(value) > 50 or any(not isinstance(v, str) or not 1 <= len(v) <= 256 or "," in v or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in value) or len(set(value)) != len(value):
        raise ValueError("Use up to 50 distinct plain tags without commas")
    return value


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response field")
        result[key] = value
    return result


def reject_number(_value):
    raise ValueError("Nonfinite response number")


async def request(value, method, path, *, params=None, body=None, reader=None, missing=False, empty=False):
    single = re.fullmatch(r"/videos/[A-Za-z0-9_-]{1,128}", path)
    allowed = method == "GET" and (path in {"/videos", "/videos/tags/"} or single)
    allowed = allowed or method in {"POST", "PUT"} and single or method in {"PUT", "DELETE"} and path == "/videos"
    allowed = allowed or method in {"POST", "PUT"} and path == "/videos/tags/" or method == "POST" and re.fullmatch(r"/videos/[A-Za-z0-9_-]{1,128}/otp", path)
    if not allowed:
        raise ValueError("Unsupported VdoCipher route")
    if reader:
        value = await reader.read()
    headers = {"Authorization": "Apisecret " + value.api_secret, "Accept": "application/json", "Cache-Control": "no-store"}
    if body is not None:
        if len(json.dumps(body, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError("VdoCipher request exceeded the local size limit")
        headers["Content-Type"] = "application/json"
    try:
        async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, BASE + path, params=params, json=body, headers=headers) as response:
                status = response.status_code
                if status != 200 and not (missing and method == "GET" and single and status == 404):
                    hint = "API secret" if status == 401 else "account API access and asset visibility" if status == 403 else "rate limits; retry manually later" if status == 429 else "asset contract or service availability"
                    raise ValueError(f"VdoCipher request failed (HTTP {status}); check {hint}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("VdoCipher response exceeded the 2 MiB local limit")
                if status == 200 and data and not empty and response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("VdoCipher returned an unexpected response format")
    except httpx.HTTPError:
        raise ValueError("VdoCipher connection failed; inspect before retrying") from None
    if reader:
        await reader.read()
    if status == 404:
        return None
    # Tag writes have a documented 200 response with no specified body schema.
    if empty:
        return None
    try:
        return json.loads(data, object_pairs_hook=unique_json, parse_constant=reject_number)
    except (ValueError, UnicodeError):
        raise ValueError("Malformed VdoCipher JSON response; inspect before retrying") from None


def video_record(payload, expected=None):
    if not isinstance(payload, dict):
        raise ValueError("Unexpected VdoCipher video envelope")
    result = {"id": identifier(payload.get("id"))}
    if expected is not None and result["id"] != expected:
        raise ValueError("VdoCipher returned a different video")
    for key, maximum in (("title", 256), ("description", 8192), ("status", 128)):
        value = payload.get(key)
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError("Malformed VdoCipher video metadata")
        result[key] = value
    for key in ("length", "upload_time"):
        value = payload.get(key)
        if type(value) is not int or value < 0:
            raise ValueError("Malformed VdoCipher video numeric metadata")
        result[key] = value
    if "tags" in payload:
        result["tags"] = validate_tags(payload["tags"])
    # Never project poster/download/stream URLs, encoding internals or unknown fields.
    return result


def video_page(payload, page, limit):
    # Current narrative is authoritative: rows/count. Swagger's older data field
    # conflicts and is deliberately not guessed into a successful inventory.
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list) or type(payload.get("count")) is not int or payload["count"] < 0 or len(payload["rows"]) > limit:
        raise ValueError("Unexpected VdoCipher rows/count page")
    rows = [video_record(item) for item in payload["rows"]]
    total, offset = payload["count"], (page - 1) * limit
    if len({row["id"] for row in rows}) != len(rows) or len(rows) > max(total - offset, 0) or len(rows) != min(limit, max(total - offset, 0)):
        raise ValueError("VdoCipher page count or IDs are inconsistent")
    more = offset + len(rows) < total
    return {"items": rows, "count": len(rows), "total_count": total, "page": page, "limit": limit, "has_more": more, "next_page": page + 1 if more else None}


def snapshot(item):
    return hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def continuation(value, scope, page):
    raw = json.dumps({"scope": snapshot(scope), "page": page}, sort_keys=True, separators=(",", ":"))
    return raw + "." + hmac.new(value.api_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()


def read_continuation(token, value, scope):
    if token is None:
        return 1
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise ValueError()
        raw, _signature = token.rsplit(".", 1)
        saved = json.loads(raw)
        if saved["scope"] != snapshot(scope) or type(saved["page"]) is not int or not 2 <= saved["page"] <= 100000 or not hmac.compare_digest(token, continuation(value, scope, saved["page"])):
            raise ValueError()
        return saved["page"]
    except (ValueError, KeyError, TypeError):
        raise ValueError("VdoCipher continuation does not match this grant and search") from None


def success(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str) or not 1 <= len(payload["message"]) <= 1024:
        raise ValueError("Unexpected VdoCipher acknowledgement; inspect before retrying")
    # Free text provider acknowledgements can echo private values; do not return it.


def upload_policy(payload, expected=None):
    if not isinstance(payload, dict):
        raise ValueError("Unexpected VdoCipher upload policy")
    # Prefer current nested clientPayload/singular credential. Explicit Swagger
    # replacement policy is flat and spells credentials plural; both are pinned.
    nested = "clientPayload" in payload
    policy = payload["clientPayload"] if nested else payload
    if not isinstance(policy, dict):
        raise ValueError("Malformed VdoCipher upload policy")
    credential_key = "x-amz-credential" if nested else "x-amz-credentials"
    keys = ("policy", "key", "x-amz-signature", "x-amz-algorithm", "x-amz-date", credential_key, "uploadLink")
    result = {}
    for key in keys:
        item = policy.get(key)
        if not isinstance(item, str) or not 1 <= len(item) <= 32768 or any(ord(c) < 32 or ord(c) == 127 for c in item):
            raise ValueError("Malformed VdoCipher signed upload field")
        result[key] = item
    try:
        url = urlsplit(result["uploadLink"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in {None, 443} or url.fragment or not url.hostname.endswith(".amazonaws.com"):
            raise ValueError()
    except ValueError:
        raise ValueError("VdoCipher upload policy returned an unexpected destination") from None
    identifier_value = identifier(payload.get("videoId")) if expected is None else expected
    if expected is not None and payload.get("videoId") is not None and identifier(payload["videoId"]) != expected:
        raise ValueError("VdoCipher replacement policy belongs to another video")
    return {"video_id": identifier_value, "client_payload": result, "sensitive_output": True, "upload_performed": False, "encoding_complete": False, "policy_created": True}


async def bind_current(credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
    value = guard(credential_data)
    if credential_id:
        reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
        value = await reader.read()
        return {**value.model_dump(), "_vdocipher_reader": reader}
    return value.model_dump()


class VdoCipherNode(WorkflowNode):
    integration_type = "automation-vdocipher"
    scope_registry = ScopeRegistry(
        provider="vdocipher", enforcement=Enforcement.STRICT,
        requirements={operation: ScopeRequirement(
            scopes=(), credential_types=(TYPE,),
            note="Supplied API secret; provider account permissions govern access. No OAuth scopes.",
        ) for operation in OPERATIONS},
    )
    connection_evidence = ConnectionEvidence(operation="list_videos", noun="visible videos", proves="reachability", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return VdoCipherNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        validate_raw_identifiers(config_data)
        if isinstance(config_data, dict) and config_data.get("credentials"):
            config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            validate_raw_identifiers(config_data)
        except ValueError as error:
            return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        if isinstance(config_data, dict) and config_data.get("credentials"):
            try:
                config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
            except ValueError as error:
                return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        organization_id = None
        if credential_id:
            if not user_id:
                raise ValueError("Stored VdoCipher credentials require a caller")
            if pool is None:
                from utils.database_pool import get_native_pool
                pool = get_native_pool()
            from wss.handlers.workflow_handler import get_user_org_context
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
        return await bind_current(credential_data, pool=pool, user_id=user_id,
                                  credential_id=credential_id, organization_id=organization_id)

    @staticmethod
    async def _get(value, video_id, reader, missing=False):
        payload = await request(value, "GET", "/videos/" + video_id, reader=reader, missing=missing)
        return None if payload is None else video_record(payload, video_id)

    @staticmethod
    async def _list(value, page, limit, reader, search=None, tags=None, folder=None):
        params = {"page": page, "limit": limit}
        if search:
            params["q"] = search
        if tags:
            params["tags"] = ",".join(tags)
        if folder:
            params["folderId"] = folder
        return video_page(await request(value, "GET", "/videos", params=params, reader=reader), page, limit)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "video_id":
            return {"options": [], "next_page_token": None}
        value = guard(credential_data)
        reader = credential_data.get("_vdocipher_reader")
        search = search or ""
        safe_text(search)
        if len(search) > 256:
            raise ValueError("Use up to 256 characters of video search text")
        scope = {"field": field_name, "search": search, "limit": 40}
        page = read_continuation(page_token, value, scope)
        result = await cls._list(value, page, 40, reader, search)
        return {"options": [{"value": item["id"], "label": item["title"] + " · " + item["id"]} for item in result["items"]], "next_page_token": continuation(value, scope, result["next_page"]) if result["has_more"] else None}

    async def execute(self, input_data):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await bind_current(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_vdocipher_reader")
        operation = cfg.operation
        if operation == "list_videos":
            return await self._list(value, cfg.page, cfg.limit, reader, cfg.search, cfg.tags, cfg.folder_id)
        if operation == "list_tags":
            params = {"page": cfg.page}
            if cfg.search:
                params["q"] = cfg.search
            payload = await request(value, "GET", "/videos/tags/", params=params, reader=reader)
            if not isinstance(payload, list) or len(payload) > 10:
                raise ValueError("Unexpected VdoCipher tag page")
            items = []
            for item in payload:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not 1 <= len(item["name"]) <= 256 or type(item.get("count")) is not int or item["count"] < 0:
                    raise ValueError("Malformed VdoCipher tag metadata")
                items.append({"name": item["name"], "count": item["count"]})
            if len({item["name"] for item in items}) != len(items):
                raise ValueError("VdoCipher repeated a tag")
            return {"items": items, "count": len(items), "page": cfg.page, "has_more": None if len(items) == 10 else False, "next_page": cfg.page + 1 if len(items) == 10 else None, "continuation_requires_read": len(items) == 10}
        if operation == "create_upload_policy":
            params = {"title": cfg.title}
            if cfg.folder_id is not None:
                params["folderId"] = cfg.folder_id
            payload = await request(value, "PUT", "/videos", params=params, reader=reader)
            result = upload_policy(payload)
            return {**result, "asset_created": True, "initial_status": "pre-upload", "status_is_expected_not_observed": True}
        original = await self._get(value, cfg.video_id, reader)
        if operation == "get_video":
            return {**original, "snapshot": snapshot(original)}
        if hasattr(cfg, "expected_snapshot") and snapshot(original) != cfg.expected_snapshot:
            raise ValueError("Video metadata changed; read it again before writing")
        if operation == "create_replacement_upload_policy":
            return upload_policy(await request(value, "PUT", "/videos/" + cfg.video_id, reader=reader), cfg.video_id)
        if operation == "create_playback_authorization":
            if original["status"].lower() != "ready":
                raise ValueError("Playback authorization requires a ready video")
            payload = await request(value, "POST", "/videos/" + cfg.video_id + "/otp", body={"ttl": cfg.ttl}, reader=reader)
            if not isinstance(payload, dict) or any(not isinstance(payload.get(key), str) or not 1 <= len(payload[key]) <= 32768 or any(ord(c) < 32 or ord(c) == 127 for c in payload[key]) for key in ("otp", "playbackInfo")):
                raise ValueError("Malformed VdoCipher playback authorization")
            return {"video_id": cfg.video_id, "otp": payload["otp"], "playbackInfo": payload["playbackInfo"], "ttl": cfg.ttl, "sensitive_output": True, "playback_started": False}
        if operation == "delete_video":
            if original["title"] != cfg.expected_title:
                raise ValueError("Video title does not match the disposable asset")
            success(await request(value, "DELETE", "/videos", params={"videos": cfg.video_id}, reader=reader))
            remaining = await self._get(value, cfg.video_id, reader, missing=True)
            return {"video_id": cfg.video_id, "deletion_accepted": True, "absence_observed": remaining is None, "absence_status": 404 if remaining is None else None, "cached_playback_may_continue": True}
        if operation == "update_video_metadata":
            body = {"title": cfg.title}
            if cfg.clear_description:
                body["description"] = ""
            elif cfg.description is not None:
                body["description"] = cfg.description
            success(await request(value, "POST", "/videos/" + cfg.video_id, body=body, reader=reader))
            result = await self._get(value, cfg.video_id, reader)
            if any(result[key] != item for key, item in body.items()):
                raise ValueError("Video update accepted but readback differs; inspect before retrying")
            return {**result, "snapshot": snapshot(result), "updated": True}
        if operation in {"append_video_tags", "set_video_tags"}:
            if "tags" not in original:
                raise ValueError("Video readback omitted tags; tag writes require their current value")
            await request(value, "POST" if operation == "append_video_tags" else "PUT", "/videos/tags/", body={"videos": [cfg.video_id], "tags": cfg.tags}, reader=reader, empty=True)
            result = await self._get(value, cfg.video_id, reader)
            expected = set(original["tags"]) | set(cfg.tags) if operation == "append_video_tags" else set(cfg.tags)
            if "tags" not in result or set(result["tags"]) != expected:
                raise ValueError("Tag update accepted but readback differs; inspect before retrying")
            return {**result, "snapshot": snapshot(result), "updated": True}
        raise ValueError("Unsupported VdoCipher operation")
