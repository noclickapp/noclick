"""Mastodon: four closed own-actor metadata GETs with supplied user tokens.

Public account/status reads are always surrounded by protected user-token
verification. No federation URL, response Link or private content is followed.
"""
import ipaddress
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin

TYPE = "mastodon_user_token"
UNAVAILABLE = "Mastodon saved credential is unavailable or has changed"
UNVERIFIED = "Mastodon own-actor metadata or access could not be verified"
MAX_BODY = 4 * 1024 * 1024


def normalize_instance_origin(value):
    if not isinstance(value, str) or value != value.strip() or len(value) > 2048:
        raise ValueError("Supply the token's exact public HTTPS instance origin")
    try:
        origin = normalize_https_origin(value, field_name="Mastodon instance origin")
        parts = urlsplit(origin)
        host = parts.hostname
        if not host or parts.port == 0 or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split(".")):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
        return origin
    except Exception:
        raise ValueError("Mastodon requires a public HTTPS origin with an optional intentional port; paths, userinfo, local/private hosts and trust overrides are unsupported") from None


def opaque_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.~-]+", value):
        raise ValueError("Supply the exact URL-safe opaque string ID from this instance, not a number, URL or encoded path")
    return value


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Supply only an already-issued user access token")
    return value


ResourceID = Annotated[StrictStr, BeforeValidator(opaque_id), Field(min_length=1, max_length=512)]
Limit = Annotated[StrictInt, Field(ge=1, le=40)]


class MastodonCredential(BaseModel):
    model_config = ConfigDict(title="Mastodon User Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-help-url": "https://docs.joinmastodon.org/methods/accounts/#verify_credentials",
        "x-credential-instructions": "Supply an existing USER OAuth access token and its public HTTPS instance origin. verify_credentials needs read:accounts, or profile on Mastodon 4.3+. Private own statuses need read:statuses. These are documented requirements, not a claim about your granted scopes or server version. No app token, token issuance/exchange/refresh, anonymous fallback or default instance.",
    })
    credential_type: Literal["mastodon_user_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    instance_origin: Annotated[StrictStr, BeforeValidator(normalize_instance_origin)] = Field(..., title="Instance Origin", description="Exact public HTTPS origin where this user token was issued, e.g. https://social.example.com. No /api path, profile URL, query, userinfo or federation destination.")
    access_token: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="Existing User Access Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Mastodon requires its original supplied user-token credential")
    try:
        return MastodonCredential.model_validate(raw)
    except Exception:
        raise ValueError("Mastodon credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("Mastodon credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Own Account Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Own Account Names", description="Opt in to username, acct and display_name on your account detail only. Profile/source, URLs, content, attachments, roles and all nested private fields are always omitted.")


class VerifyCredentials(Config):
    operation: Literal["verify_credentials"] = op("verify_credentials", "Verify User Token", "Read the protected token verification endpoint and return only its opaque current actor ID. Public account/status success alone cannot prove authentication.")


class AccountConfig(Config):
    account_id: ResourceID = Field(..., title="Current Actor Account ID", description="Must equal the current protected verify_credentials ID. Third-party accounts are not supported; IDs are opaque strings, not necessarily numbers.", json_schema_extra={"x-dynamic-options": {"allow_custom": True, "custom_placeholder": "Paste your verified actor ID"}})


class GetAccount(AccountConfig):
    operation: Literal["get_account"] = op("get_account", "Get Own Account Metadata", "Independently read your verified account's scalar IDs, counts and raw dates. Reverify the user token before returning output.")


class StatusPage(AccountConfig):
    limit: Limit = Field(20, title="Status Page Limit", description="Strict integer 1–40, documented default 20. One page only; no total or completeness is inferred from page length.")
    max_id: ResourceID | None = Field(None, title="Maximum Status Cursor", description="Optional opaque ID: request statuses older than this ID. No numeric comparison or Link parsing.")
    since_id: ResourceID | None = Field(None, title="Since Status Cursor", description="Optional opaque ID: request statuses newer than this ID.")
    min_id: ResourceID | None = Field(None, title="Minimum Status Cursor", description="Optional opaque ID: request statuses immediately newer than this ID. Combining min_id and max_id requires Mastodon 3.3+; instance compatibility is unverified.")


class ListStatuses(StatusPage):
    operation: Literal["list_statuses"] = op("list_statuses", "List Own Status Metadata", "Read one current actor page with exclude_reblogs and exclude_replies fixed true. The latter excludes replies to other accounts; self replies may remain. Content and nested data are never returned.")


class GetStatus(StatusPage):
    operation: Literal["get_status"] = op("get_status", "Get Own Catalog Status Metadata", "Require the exact status ID in your current configured catalog page, then independently read its metadata and reverify the actor. Use documented cursors to select older pages.")
    status_id: ResourceID = Field(..., title="Own Catalog Status ID", description="Opaque string ID from your current selected status page. Third-party IDs and IDs outside that page are refused before status detail.", json_schema_extra={"x-dynamic-options": {"depends_on": "account_id", "allow_custom": True, "custom_placeholder": "Paste an ID from your selected status page"}})


OPERATIONS = (VerifyCredentials, GetAccount, ListStatuses, GetStatus)
MastodonConfig = Annotated[Union[VerifyCredentials, GetAccount, ListStatuses, GetStatus], Field(discriminator="operation")]


class MastodonNodeConfig(NodeConfig[MastodonConfig, MastodonCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-mastodon"] = "automation-mastodon"


@dataclass(eq=False)
class Authority:
    """Use staging's credential resolver; supplied tokens never refresh."""
    credential: MastodonCredential = field(repr=False)
    pool: Any = field(default=None, repr=False)
    user_id: Any = None
    credential_id: Any = None
    organization_id: Any = None
    workflow_id: Any = None

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        current = cls(credential(raw), pool, user_id, credential_id, organization_id, workflow_id)
        if credential_id:
            if not user_id:
                raise ValueError(UNAVAILABLE)
            if pool is None:
                from utils.database_pool import get_native_pool
                current.pool = get_native_pool()
            await current.require_current()
        return current

    async def require_current(self):
        if self.credential_id:
            latest = await resolve_credential_with_owner_fallback(
                self.credential_id, self.user_id, self.pool,
                org_id=self.organization_id, workflow_id=self.workflow_id,
            )
            if not latest or credential(latest) != self.credential:
                raise ValueError(UNAVAILABLE)


_PRIVATE = ContextVar("mastodon_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Mastodon transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        self.category = "authentication" if status == 401 else "permission" if status == 403 else "resource" if status in {404, 410} else "other"
        meaning = {"authentication": "user authentication failed", "permission": "access is forbidden; scope, disabled-account or approval cause is unverified", "resource": "resource is missing or invisible", "other": "metadata request was unsuccessful"}[self.category]
        if status == 429:
            meaning = "rate limit reached; no automatic retry"
        super().__init__(f"Mastodon returned HTTP {status}: {meaning}")


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def validate_route(route, params):
    if not isinstance(params, dict):
        raise ValueError("Unsupported Mastodon query")
    if route == "/accounts/verify_credentials":
        if params:
            raise ValueError("Token verification has no supported query")
        return
    match = re.fullmatch(r"/(accounts|statuses)/([A-Za-z0-9_.~-]+)(/statuses)?", route)
    if not match:
        raise ValueError("Unsupported Mastodon metadata route")
    opaque_id(match[2])
    if match[3]:
        if match[1] != "accounts" or set(params) - {"limit", "max_id", "since_id", "min_id", "exclude_reblogs", "exclude_replies"} or type(params.get("limit")) is not int or not 1 <= params["limit"] <= 40 or params.get("exclude_reblogs") != "true" or params.get("exclude_replies") != "true":
            raise ValueError("Unsupported Mastodon own-status page query")
        for key in ("max_id", "since_id", "min_id"):
            if key in params:
                opaque_id(params[key])
    elif params:
        raise ValueError("Mastodon metadata detail has no supported query")


async def request(auth, route, params=None):
    params = {} if params is None else params
    validate_route(route, params)
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                req = client.build_request("GET", auth.credential.instance_origin + "/api/v1" + route, params=params, headers={"Authorization": "Bearer " + auth.credential.access_token, "Accept": "application/json"})
                await auth.require_current()
                response = await client.send(req, stream=True)
                try:
                    if response.status_code != 200:
                        await auth.require_current()
                        raise ApiError(response.status_code)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            raise OutcomeUnverified("Mastodon response exceeds the local 4 MiB bound; no partial output")
                    await auth.require_current()
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        raw = json.loads(body, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
                    return raw, "link" in response.headers
                finally:
                    await response.aclose()
    except (httpx.RequestError, SSRFError):
        await auth.require_current()
        raise OutcomeUnverified("Mastodon transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


def text(value, *, nullable=False, empty=False, maximum=128):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError()
    return value


def count(value):
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        raise ValueError()
    return value


def account(raw, names=False):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        result = {"id": opaque_id(raw["id"]), "created_at": text(raw["created_at"])}
        for key in ("statuses_count", "followers_count", "following_count"):
            result[key] = count(raw[key])
        if "last_status_at" in raw:
            result["last_status_at"] = text(raw["last_status_at"], nullable=True)
        if names:
            for key in ("username", "acct", "display_name"):
                result[key] = text(raw[key], empty=True, maximum=512)
        return result
    except Exception:
        raise OutcomeUnverified("Mastodon account metadata shape is unverified") from None


def status(raw, actor):
    try:
        if not isinstance(raw, dict) or raw["reblog"] is not None or not isinstance(raw["account"], dict) or opaque_id(raw["account"]["id"]) != actor:
            raise ValueError()
        if raw.get("in_reply_to_account_id") is not None and opaque_id(raw["in_reply_to_account_id"]) != actor:
            raise ValueError()
        if raw["visibility"] not in {"public", "unlisted", "private", "direct"}:
            raise ValueError()
        result = {"id": opaque_id(raw["id"]), "created_at": text(raw["created_at"]), "visibility": raw["visibility"]}
        for key in ("replies_count", "reblogs_count", "favourites_count"):
            result[key] = count(raw[key])
        for key in ("edited_at", "language"):
            if key in raw:
                result[key] = text(raw[key], nullable=True, maximum=128)
        return result
    except Exception:
        raise OutcomeUnverified("Mastodon status shape, authored actor or excluded boost could not be verified") from None


async def verify_actor(auth, expected=None):
    raw, _ = await request(auth, "/accounts/verify_credentials")
    try:
        actor = opaque_id(raw["id"]) if isinstance(raw, dict) else None
        if actor is None or expected is not None and actor != expected:
            raise ValueError()
    except Exception:
        raise OutcomeUnverified("Mastodon current protected actor ID could not be verified") from None
    return actor


def page_params(cfg):
    result = {"limit": cfg.limit, "exclude_reblogs": "true", "exclude_replies": "true"}
    for key in ("max_id", "since_id", "min_id"):
        if getattr(cfg, key) is not None:
            result[key] = getattr(cfg, key)
    return result


async def status_catalog(auth, actor, cfg):
    raw, has_link = await request(auth, "/accounts/" + quote(actor, safe="") + "/statuses", page_params(cfg))
    if not isinstance(raw, list) or len(raw) > cfg.limit:
        raise OutcomeUnverified("Mastodon status catalog must be a bare array within the requested page bound")
    projected = [status(row, actor) for row in raw]
    if len({row["id"] for row in projected}) != len(projected):
        raise OutcomeUnverified("Mastodon own-status catalog contains duplicate IDs")
    return projected, has_link


async def operate(auth, cfg):
    actor = await verify_actor(auth)
    if isinstance(cfg, VerifyCredentials):
        return {"id": actor}
    if cfg.account_id != actor:
        raise ValueError("Mastodon account_id must equal the current protected actor ID")
    if isinstance(cfg, GetAccount):
        raw, _ = await request(auth, "/accounts/" + quote(actor, safe=""))
        projected = account(raw, cfg.include_names)
        if projected["id"] != actor:
            raise OutcomeUnverified("Mastodon account detail does not match the verified actor")
        result = {"account": projected}
    elif isinstance(cfg, (ListStatuses, GetStatus)):
        rows, has_link = await status_catalog(auth, actor, cfg)
        if isinstance(cfg, ListStatuses):
            result = {"actor_id": actor, "items": rows, "returned_count": len(rows), "requested_limit": cfg.limit, "link_header_present": has_link, "completion": "unknown", "snapshot_consistent": False}
        else:
            if not any(row["id"] == cfg.status_id for row in rows):
                raise OutcomeUnverified("Mastodon selected status is absent from the current actor's configured page")
            raw, _ = await request(auth, "/statuses/" + quote(cfg.status_id, safe=""))
            projected = status(raw, actor)
            if projected["id"] != cfg.status_id:
                raise OutcomeUnverified("Mastodon status detail ID differs from the current selected catalog ID")
            result = {"actor_id": actor, "status": projected, "snapshot_consistent": False}
    else:
        raise ValueError("Unsupported Mastodon metadata operation")
    await verify_actor(auth, actor)
    return result


class MastodonNode(WorkflowNode):
    integration_type = "automation-mastodon"
    connection_evidence = ConnectionEvidence(noun="verified user account", identity_operation="verify_credentials", identity_keys=("id",), label_keys=(), proves="account")

    @classmethod
    def get_config_model(cls):
        return MastodonNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw_guard(config_data)
        return super().validate_config(config_data)

    @classmethod
    async def validate_credential_access(cls, raw):
        try:
            auth = await Authority.create(raw)
            await operate(auth, VerifyCredentials())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.category in {"authentication", "permission"} else (None, str(error))
        except Exception:
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, MastodonNodeConfig) or self.config.credentials is None:
            raise ValueError("Mastodon public instance origin and supplied user access token are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        result = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        auth = await Authority.create(credential_data)
        if field_name not in {"account_id", "status_id"} or page_token is not None:
            raise ValueError("Mastodon pickers use explicit status page fields, never returned Link URLs or invented cursors")
        names = context.get("include_names", False)
        if type(names) is not bool or search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("Mastodon picker search or name opt-in is invalid")
        cfg = ListStatuses(account_id=context.get("account_id"), include_names=names, **{key: context[key] for key in ("limit", "max_id", "since_id", "min_id") if key in context}) if field_name == "status_id" else None
        actor = await verify_actor(auth)
        if field_name == "account_id":
            options = [{"value": actor, "label": "Verified account " + actor}]
        else:
            if cfg.account_id != actor:
                raise ValueError("Mastodon status picker parent must equal the current protected actor")
            rows, _ = await status_catalog(auth, actor, cfg)
            options = [{"value": row["id"], "label": "Status " + row["id"] + " · " + row["created_at"]} for row in rows]
        if search:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        await verify_actor(auth, actor)
        await auth.require_current()
        return {"options": options, "next_page_token": None}
