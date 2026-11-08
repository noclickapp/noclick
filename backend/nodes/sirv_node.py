"""Native Sirv supplied-token file/folder metadata reads; no media or mutations."""
import base64
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Discriminator, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "sirv_access_token"
NODE_TYPE = "automation-sirv"
API_ORIGIN = "https://api.sirv.com"
API_ROOT = API_ORIGIN + "/v2"
MAX_BYTES = 2 * 1024 * 1024
MAX_WITNESS_PAGES = 5
_PRIVATE = ContextVar("sirv_private_transport", default=False)
ROUTES = {"readdir", "stat", "meta", "meta/approval", "options"}


def path(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 1024 or not value.startswith("/")
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in ("\\", "%", "?", "#")) or "//" in value or "://" in value
            or (value != "/" and (value.endswith("/") or any(p in ("", ".", "..") for p in value[1:].split("/"))))):
        raise ValueError("Use a canonical absolute Sirv path without URL syntax or traversal")
    return value


def child_path(folder, name):
    if not isinstance(name, str) or not name or "/" in name:
        raise _Unverified("Sirv directory entry name is unverified")
    try:
        return path(("" if folder == "/" else folder) + "/" + name)
    except ValueError:
        raise _Unverified("Sirv directory entry path is unverified") from None


def within(root, selected):
    path(root); path(selected)
    if selected != root and not selected.startswith(("" if root == "/" else root) + "/"):
        raise _Refused("Sirv selected path is outside the saved root folder")
    return selected


def deadline(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Supply the actual timezone-aware token expiry deadline")
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc).isoformat()
    except ValueError:
        raise ValueError("Supply the actual timezone-aware token expiry deadline") from None


def token(value):
    try:
        value = clean_secret(value, field_name="Sirv Access Token")
        if len(value) > 8192 or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value):
            raise ValueError()
        return value
    except Exception:
        raise ValueError("Supply an existing Sirv bearer token without the Bearer prefix") from None


class SirvAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Sirv Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://sirv.com/help/articles/sirv-rest-api/",
        "x-credential-instructions": "Supply an existing Bearer token, its actual issuer-reported scope list including files:read, actual expiry deadline, and a selected absolute root-folder path. This node neither creates nor refreshes tokens. Sent only in the Authorization header to fixed public HTTPS api.sirv.com/v2. Folder reads establish reachability, not principal/tenant ownership or token-claim verification.",
        "x-required-token-scopes": ["files:read"],
    })
    credential_type: Literal["sirv_access_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Existing Access Token", min_length=1, max_length=8192,
        json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    root_folder: str = Field(..., title="Selected Root Folder", description="Absolute account path, such as /catalog. A local read boundary, not account identity.",
        json_schema_extra={"ui:sensitive": True})
    expires_at: str = Field(..., title="Actual Token Expiry", description="Timezone-aware ISO deadline from the genuine token issuance time and expiresIn. Never inferred from a decoded JWT.")
    scope: list[str] = Field(..., title="Actual Token Scope List", min_length=1, max_length=32,
        description="Copy the issuer-reported scope array, including files:read. No scope is requested or granted by this node.")
    _token = field_validator("access_token", mode="before")(token)
    _root = field_validator("root_folder", mode="before")(path)
    _expiry = field_validator("expires_at", mode="before")(deadline)

    @model_validator(mode="before")
    @classmethod
    def _manual_family(cls, value):
        if isinstance(value, dict) and "credential_type" not in value:
            return {**value, "credential_type": FAMILY}
        return value

    @field_validator("scope", mode="before")
    @classmethod
    def _scope(cls, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                raise ValueError("Copy the actual token scope as a JSON array") from None
        if (not isinstance(value, list) or not 1 <= len(value) <= 32
                or any(not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?::[a-z][a-z0-9]*){0,3}", v) for v in value)
                or len(set(value)) != len(value) or "files:read" not in value):
            raise ValueError("Supply the actual scope array including files:read")
        return sorted(value)


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
            raise ValueError()
        if any(data.get(k) not in (None, "", []) for k in
               ("refresh_token", "client_id", "client_secret", "api_key", "token", "base_url", "host", "region", "username", "password", "scopes")):
            raise ValueError()
        shaped = SirvAccessTokenCredential.model_validate(data).model_dump()
        expiry = datetime.fromisoformat(shaped["expires_at"])
        if expiry <= datetime.now(timezone.utc):
            raise ValueError()
        return shaped
    except Exception:
        raise ValueError("Connect the native Sirv unexpired token, actual files:read scope and root folder") from None


async def current_credential(data):
    # Staging resolves saved credentials before calling the node. Supplied
    # Sirv tokens do not refresh; validate their scope and expiry on each read.
    return credential(data)


def runtime(data):
    return credential(data)


def resource(field, parents=()):
    return {"x-resource-type": "sirv_" + field, "x-dynamic-options": {
        "field_name": field, "allow_custom": True, "searchable": True,
        "depends_on": list(parents), "required_context_scopes": {p: [] for p in parents},
        "context_fields": list(parents) + ["include_paths"], "placeholder": "Select current " + field.replace("_", " ")}}


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
    root_folder: str = Field(..., title="Saved Root Folder", json_schema_extra=resource("root_folder"))
    folder_path: str = Field(..., title="Selected Folder", description="Current folder at or beneath the saved root. Ancestry checks scan at most five pages per ancestor and eight descendant levels.",
        json_schema_extra=resource("folder_path", ("root_folder",)))
    include_paths: bool = Field(False, strict=True, title="Include File Names and Paths",
        description="Opt in to bounded file/folder names and absolute paths. Metadata text, tags, product values, comments, media and private URLs are never returned.")
    @field_validator("root_folder", "folder_path", "file_path", mode="before", check_fields=False)
    @classmethod
    def _path(cls, value):
        return path(value)


class _File(_Config):
    file_path: str = Field(..., title="Selected File", description="A current direct child of the selected folder.",
        json_schema_extra=resource("file_path", ("root_folder", "folder_path")))


class ListFolder(_Config):
    operation: Literal["list_folder"] = Field("list_folder", title="List Folder Metadata")
    page_token: Optional[str] = Field(None, title="Next Page Token", max_length=8192,
        description="Locally sealed continuation from this same current grant and folder; not a provider URL.")
    limit: int = Field(100, strict=True, ge=1, le=100, title="Local Output Limit",
        description="The API returns at most100 entries. Local truncation never skips entries with a continuation token.")


class GetFileInfo(_File):
    operation: Literal["get_file_info"] = Field("get_file_info", title="Get File Stat Metadata")


class GetFileMetadata(_File):
    operation: Literal["get_file_metadata"] = Field("get_file_metadata", title="Get File Metadata Summary")


class GetFileApproval(_File):
    operation: Literal["get_file_approval"] = Field("get_file_approval", title="Get File Approval Status")


class GetFolderOptions(_Config):
    operation: Literal["get_folder_options"] = Field("get_folder_options", title="Get Folder Option Flags")
    with_inherited: bool = Field(False, strict=True, title="Include Inherited Folder Options")


SirvOperation = Annotated[Union[ListFolder, GetFileInfo, GetFileMetadata, GetFileApproval, GetFolderOptions], Discriminator("operation")]
OPS = ("list_folder", "get_file_info", "get_file_metadata", "get_file_approval", "get_folder_options")


class SirvNodeConfig(NodeConfig[SirvOperation, SirvAccessTokenCredential]):
    pass


class _Refused(ValueError):
    pass


class _Unverified(RuntimeError):
    pass


class _Privacy(logging.Filter):
    def filter(self, record):
        return not _PRIVATE.get()


def _json(payload):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    return json.loads(payload, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def continuation(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value) or "://" in value:
        raise _Unverified("Sirv opaque continuation is unverified")
    return value


async def request(data, route, selected, *, cursor=None, with_inherited=False):
    data = runtime(data)
    if route not in ROUTES:
        raise ValueError("Use a documented native Sirv metadata route")
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _Privacy) for f in logger.filters):
            logger.addFilter(_Privacy())
    mark = _PRIVATE.set(True)
    try:
        current = await current_credential(data)
        selected = within(current["root_folder"], selected)
        params = {"dirname" if route == "readdir" else "filename": selected}
        if cursor is not None:
            if route != "readdir":
                raise ValueError()
            params["continuation"] = continuation(cursor)
        if route == "options":
            if type(with_inherited) is not bool:
                raise ValueError()
            params["withInherited"] = "true" if with_inherited else "false"
        url = API_ROOT + "/files/" + route
        async with guarded_async_client(timeout=25.0, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url, params=params, headers={
                    "Accept": "application/json", "Authorization": "Bearer " + current["access_token"]}) as response:
                await current_credential(data)
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise _Unverified("Sirv metadata response exceeds the local bound")
                await current_credential(data)
                if response.status_code in {400, 401, 403, 404, 405, 406, 409, 422}:
                    raise _Refused("Sirv refused current access or the selected metadata read")
                if response.status_code != 200:
                    raise _Unverified("Sirv did not confirm a completed metadata response")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise _Unverified("Sirv JSON metadata is unverified")
                try:
                    raw = _json(bytes(payload))
                except (ValueError, TypeError):
                    raise _Unverified("Sirv JSON metadata is unverified") from None
                if not isinstance(raw, dict) or any(k in raw for k in ("statusCode", "error", "message", "errors")):
                    raise _Unverified("Sirv documented metadata envelope is unverified")
                return raw
    except (_Refused, _Unverified):
        raise
    except ValueError:
        raise ValueError("Sirv credential or request policy refused the read") from None
    except Exception:
        raise _Unverified("Sirv metadata read could not complete") from None
    finally:
        _PRIVATE.reset(mark)


def timestamp(value):
    try:
        return deadline(value)
    except ValueError:
        raise _Unverified("Sirv metadata timestamp is unverified") from None


def stat(raw):
    if not isinstance(raw, dict) or type(raw.get("isDirectory")) is not bool or "mtime" not in raw:
        raise _Unverified("Sirv typed file/folder stat is unverified")
    out = {"is_directory": raw["isDirectory"], "modified_at": timestamp(raw["mtime"])}
    if "ctime" in raw:
        out["created_at"] = timestamp(raw["ctime"])
    if "size" in raw:
        if type(raw["size"]) is not int or not 0 <= raw["size"] <= 9223372036854775807:
            raise _Unverified("Sirv byte count is unverified")
        out["size_bytes"] = raw["size"]
    if "contentType" in raw:
        if not isinstance(raw["contentType"], str) or not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]{1,100}/[A-Za-z0-9!#$&^_.+-]{1,100}", raw["contentType"]):
            raise _Unverified("Sirv media type is unverified")
        out["content_type"] = raw["contentType"]
    return out


def directory_page(raw, folder):
    if not isinstance(raw.get("contents"), list) or len(raw["contents"]) > 100:
        raise _Unverified("Sirv bounded directory envelope is unverified")
    entries = []
    for row in raw["contents"]:
        if not isinstance(row, dict):
            raise _Unverified("Sirv directory metadata entry is unverified")
        entries.append((child_path(folder, row.get("filename")), stat(row)))
    if len({p for p, _ in entries}) != len(entries):
        raise _Unverified("Sirv directory contains duplicate child paths")
    cursor = continuation(raw["continuation"]) if "continuation" in raw else None
    return entries, cursor


async def find_child(data, folder, selected, *, directory):
    path(selected)
    if selected.rsplit("/", 1)[0] != ("" if folder == "/" else folder):
        raise _Refused("Sirv selected resource is not a direct child of its current folder")
    cursor, seen = None, set()
    for _ in range(MAX_WITNESS_PAGES):
        entries, following = directory_page(await request(data, "readdir", folder, cursor=cursor), folder)
        match = next((row for p, row in entries if p == selected), None)
        if match is not None:
            if match["is_directory"] is not directory:
                raise _Refused("Sirv selected resource type differs from its folder catalog")
            return match
        if following is None:
            raise _Refused("Sirv selected resource is absent from its current folder catalog")
        if following in seen:
            raise _Unverified("Sirv continuation repeated during the bounded ancestry read")
        seen.add(following); cursor = following
    raise _Unverified("Sirv selected resource ancestry exceeds the local five-page bound")


async def folder_witness(data, folder):
    root = (await current_credential(data))["root_folder"]
    within(root, folder)
    # The documented folder API supplies typed entries and pagination; stat is
    # documented for files. Prove folder reads using their own response shape.
    root_page = directory_page(await request(data, "readdir", root), root)
    remainder = folder[len(root):].strip("/") if root != "/" else folder[1:]
    pieces = remainder.split("/") if remainder else []
    if len(pieces) > 8:
        raise _Refused("Sirv selected folder exceeds the local eight-level ancestry bound")
    current, chain = root, []
    for piece in pieces:
        selected = child_path(current, piece)
        witness = await find_child(data, current, selected, directory=True)
        chain.append((selected, witness))
        current = selected
    selected_page = root_page if folder == root else directory_page(await request(data, "readdir", folder), folder)
    return root_page, chain, selected_page


def _page_binding(data, folder):
    shaped = credential(data)
    return hashlib.sha256(json.dumps({"credential": shaped, "folder": path(folder)},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _page_cipher(data):
    key = hashlib.sha256(("sirv-directory-page:" + credential(data)["access_token"]).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal_page(data, folder, cursor):
    if cursor is None:
        return None
    body = {"binding": _page_binding(data, folder), "continuation": continuation(cursor)}
    return _page_cipher(data).encrypt(json.dumps(body, separators=(",", ":")).encode()).decode()


def unseal_page(data, folder, value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 8192:
            raise ValueError()
        body = _json(_page_cipher(data).decrypt(value.encode("ascii"), ttl=300))
        if not isinstance(body, dict) or body.get("binding") != _page_binding(data, folder):
            raise ValueError()
        return continuation(body["continuation"])
    except Exception:
        raise ValueError("Reload Sirv pagination for the same current credential and folder") from None


def approval(raw):
    if not isinstance(raw, dict):
        raise _Unverified("Sirv approval metadata is unverified")
    out = {"approved": None}
    if "approved" in raw:
        if type(raw["approved"]) is not bool:
            raise _Unverified("Sirv approval flag is unverified")
        out["approved"] = raw["approved"]
    if "datetime" in raw:
        out["recorded_at"] = timestamp(raw["datetime"])
    return out


def meta_summary(raw):
    out = {}
    for key in ("title", "description"):
        if key in raw and not isinstance(raw[key], str):
            raise _Unverified("Sirv metadata presence is unverified")
        out[key + "_present"] = bool(raw.get(key))
    if "tags" in raw and (not isinstance(raw["tags"], list) or len(raw["tags"]) > 1000 or any(not isinstance(v, str) for v in raw["tags"])):
        raise _Unverified("Sirv metadata tag count is unverified")
    out["tag_count"] = len(raw["tags"]) if "tags" in raw else None
    if "product" in raw:
        if not isinstance(raw["product"], dict):
            raise _Unverified("Sirv product metadata shape is unverified")
        out["product_fields_present"] = [k for k in ("id", "name", "brand", "category1", "category2") if isinstance(raw["product"].get(k), str) and raw["product"][k]]
    if "approval" in raw:
        out["approval"] = approval(raw["approval"])
    return out


async def records(data, args):
    cfg = TypeAdapter(SirvOperation).validate_python(args).model_dump()
    data = runtime(data)
    current = await current_credential(data)
    if cfg["root_folder"] != current["root_folder"]:
        raise _Refused("Sirv selected root differs from the current saved credential")
    folder, op = cfg["folder_path"], cfg["operation"]
    cursor = unseal_page(data, folder, cfg["page_token"]) if op == "list_folder" else None
    before_folder = await folder_witness(data, folder)
    selected = cfg.get("file_path")
    before_child, before_file = None, None
    if selected is not None:
        within(current["root_folder"], selected)
        before_child = await find_child(data, folder, selected, directory=False)
        before_file = stat(await request(data, "stat", selected))
        if before_file["is_directory"] is not False:
            raise _Refused("Sirv selected file is no longer a file")
    if op == "list_folder":
        entries, following = directory_page(await request(data, "readdir", folder, cursor=cursor), folder)
        projected = []
        for p, row in entries:
            projected.append({**row, **({"path": p, "name": p.rsplit("/", 1)[-1]} if cfg["include_paths"] else {})})
        truncated = len(projected) > cfg["limit"]
        # A provider continuation starts AFTER this response: local truncation
        # must never offer it as a way to recover skipped response entries.
        out = {"records": projected[:cfg["limit"]], "returned": min(len(projected), cfg["limit"]),
            "provider_returned": len(entries), "local_truncated": truncated,
            "has_more": True if truncated else following is not None,
            "next_page_token": None if truncated else seal_page(data, folder, following),
            "completion_known": not truncated and following is None,
            "total_count": None, "continuation_scope": "selected folder and current saved grant"}
        again, again_cursor = directory_page(await request(data, "readdir", folder, cursor=cursor), folder)
        if entries != again or following != again_cursor:
            raise _Refused("Sirv selected folder catalog changed during this page read")
    elif op == "get_file_info":
        out = {"record": before_file}
    elif op == "get_file_metadata":
        out = {"record": meta_summary(await request(data, "meta", selected))}
    elif op == "get_file_approval":
        out = {"record": approval(await request(data, "meta/approval", selected))}
    else:
        raw = await request(data, "options", folder, with_inherited=cfg["with_inherited"])
        flags = {}
        for k in ("scanSpins", "nameSpinsAfterFolder", "allowListing", "locked"):
            if k in raw:
                if type(raw[k]) is not bool:
                    raise _Unverified("Sirv folder option flag is unverified")
                flags[k] = raw[k]
        out = {"record": flags, "with_inherited": cfg["with_inherited"]}
    after_folder = await folder_witness(data, folder)
    if before_folder != after_folder:
        raise _Refused("Sirv selected folder ancestry or metadata changed during the read")
    if selected is not None:
        after_child = await find_child(data, folder, selected, directory=False)
        after_file = stat(await request(data, "stat", selected))
        if before_child != after_child or before_file != after_file:
            raise _Refused("Sirv selected file catalog or stat changed during the read")
    await current_credential(data)
    return {"read_completed": True, "reachability_verified": True, "identity_verified": False,
        "paths_included": cfg["include_paths"], **({"root_folder": current["root_folder"], "folder_path": folder,
        **({"file_path": selected} if selected is not None else {})} if cfg["include_paths"] else {}), **out}


class SirvNode(WorkflowNode):
    integration_type = "automation-sirv"
    scope_registry = ScopeRegistry(provider="sirv", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=("files:read",), credential_types=(FAMILY,)) for op in OPS})
    connection_evidence = ConnectionEvidence(field="root_folder",
        noun="Sirv selected-folder metadata", proves="reachability")
    edit_examples = ["List one current folder metadata page without file paths", "Read a selected file size and timestamps", "Read approval status and metadata counts without descriptions or media"]

    @classmethod
    def get_config_model(cls):
        return SirvNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            credential(config_data["credentials"])
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try:
                credential(config_data["credentials"])
            except ValueError:
                return {"valid": False, "errors": ["Connect the native Sirv unexpired token, scope and root folder"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"root_folder", "folder_path", "file_path"}:
            return {"options": [], "has_more": False, "next_page_token": None}
        search = normalize_search(search)
        if search and (len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise ValueError("Use a bounded Sirv picker search")
        context = context or {}
        data = runtime(credential_data)
        root = (await current_credential(data))["root_folder"]
        names = context.get("include_paths", False)
        if type(names) is not bool:
            raise ValueError("Use a boolean Sirv path opt-in")
        if field_name == "root_folder":
            if page_token is not None:
                raise ValueError("Reload the configured root-folder witness")
            await folder_witness(data, root)
            await current_credential(data)
            return {"options": [{"value": root, "label": root if names else "Selected root folder",
                "metadata": {"proves": "reachability"}}], "has_more": False, "next_page_token": None}
        if path(context.get("root_folder")) != root:
            raise _Refused("Sirv picker selected root differs")
        folder = root if field_name == "folder_path" else within(root, path(context.get("folder_path")))
        cursor = unseal_page(data, folder, page_token)
        before = await folder_witness(data, folder)
        entries, following = directory_page(await request(data, "readdir", folder, cursor=cursor), folder)
        wanted_directory = field_name == "folder_path"
        options = []
        if wanted_directory and page_token is None:
            options.append({"value": root, "label": root if names else "Selected root folder", "metadata": {"root_folder": root}})
        for p, row in entries:
            if row["is_directory"] is wanted_directory:
                options.append({"value": p, "label": p.rsplit("/", 1)[-1] if names else ("Folder " if wanted_directory else "File ") + str(len(options) + 1),
                    "metadata": {"root_folder": root, **({"folder_path": folder} if not wanted_directory else {})}})
        again, again_cursor = directory_page(await request(data, "readdir", folder, cursor=cursor), folder)
        after = await folder_witness(data, folder)
        if entries != again or following != again_cursor or before != after:
            raise _Refused("Sirv picker current folder catalog or ancestry changed")
        await current_credential(data)
        return {"options": filter_options_by_search(options, search), "has_more": following is not None,
            "next_page_token": seal_page(data, folder, following), "total_count": None,
            "provider_returned": len(entries), "locally_filtered": True, "completion_known": following is None,
            "paths_are_selection_anchors": True}

    async def execute(self, inputs):
        if not isinstance(self.config, SirvNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect the native Sirv supplied access token")
        raw = (self.node_data or {}).get("credentials")
        data = runtime(raw if raw is not None else self.config.credentials.model_dump())
        return await records(data, self.config.config.model_dump())
