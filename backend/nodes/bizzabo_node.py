"""Native Bizzabo public partner API: account/event metadata and bounded contact maintenance."""
import asyncio
from contextvars import ContextVar
import json
import logging
import re
import time
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Discriminator, Field, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin, guarded_async_client

FAMILY = "bizzabo_client_credentials"
NODE_TYPE = "automation-bizzabo"
API_ORIGIN = "https://api.bizzabo.com"
AUTH_ORIGIN = "https://auth.bizzabo.com"
MAX_BYTES = 2 * 1024 * 1024
_PRIVATE = ContextVar("bizzabo_private_transport", default=False)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 9223372036854775807:
        raise ValueError("Use a positive decimal Bizzabo ID within the local signed-64-bit bound")
    return value


def opaque(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > (256 if field == "Client ID" else 4096) or any(ord(c) < 32 for c in value) or "\x7f" in value:
        raise ValueError("Supply your existing Bizzabo client credentials")
    return clean_secret(value, field_name="Bizzabo " + field)


def plain(value, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value) or "\x7f" in value:
        raise ValueError("Supply bounded Bizzabo text without controls")
    return value


def validate_email(value):
    value = plain(value, 254)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Supply a valid contact email")
    return value


class BizzaboClientCredentialsCredential(BaseModel):
    model_config = ConfigDict(title="Bizzabo Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://bizzabo.stoplight.io/docs/bizzabo-partner-apis/ZG9jOjU4NjM4-authentication",
        "x-credential-instructions": "Enter the client ID, client secret and numeric account ID for your Bizzabo public partner API account. These credentials provide access across the account.",
    })
    credential_type: Literal["bizzabo_client_credentials"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=256, title="Client ID", json_schema_extra={"ui:sensitive": True})
    client_secret: str = Field(..., min_length=1, max_length=4096, title="Client Secret", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    account_id: str = Field(..., title="Account ID", description="Numeric ID of the Bizzabo account these credentials belong to.")
    _client = field_validator("client_id", mode="before")(lambda value: opaque(value, "Client ID"))
    _secret = field_validator("client_secret", mode="before")(lambda value: opaque(value, "Client Secret"))
    _account = field_validator("account_id", mode="before")(identifier)


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
            raise ValueError()
        if any(data.get(k) not in (None, "") for k in ("api_key", "access_token", "refresh_token", "auth_token", "base_url", "host", "region", "username", "password")):
            raise ValueError()
        return BizzaboClientCredentialsCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Connect native Bizzabo PUBLIC client credentials with the exact account ID") from None


class _RuntimeCredential(dict):
    def __init__(self, data):
        super().__init__(data)
        self.token, self.expires_at, self.lock = None, 0.0, asyncio.Lock()


class _BoundCredential(_RuntimeCredential):
    def __init__(self, data, loader):
        super().__init__(data)
        self["_bizzabo_saved_authority_required"] = True
        self.loader = loader


async def current_credential(data):
    shaped = credential(data)
    if not isinstance(data, _BoundCredential):
        if "_bizzabo_saved_authority_required" in data:
            raise ValueError("Bizzabo saved authority was lost; reload")
        return shaped
    try:
        now = credential(await data.loader())
        if now != shaped:
            raise ValueError()
    except Exception:
        data.token, data.expires_at = None, 0.0
        raise ValueError("Bizzabo saved credential or current access changed; reload") from None
    return now


async def bound_credential(data, *, pool=None, user_id=None, credential_id=None,
                           organization_id=None, workflow_id=None):
    """Use staging's canonical access resolver; tokens remain runtime-only."""
    shaped = credential(data)
    if not credential_id:
        return runtime(data)
    if not user_id:
        raise ValueError("Bizzabo requires the current authorized principal")
    from utils.credentials import resolve_credential_with_owner_fallback
    from utils.database_pool import get_native_pool
    if pool is None:
        pool = get_native_pool()

    async def load():
        return await resolve_credential_with_owner_fallback(
            credential_id, user_id, pool, org_id=organization_id,
            workflow_id=workflow_id)

    result = _BoundCredential(shaped, load)
    await current_credential(result)
    return result


def runtime(data):
    credential(data)
    if "_bizzabo_saved_authority_required" in data and not isinstance(data, _BoundCredential):
        raise ValueError("Bizzabo saved authority was lost; reload")
    return data if isinstance(data, _RuntimeCredential) else _RuntimeCredential(data)


def resource(name, parents=()):
    return {"x-resource-type": "bizzabo_" + name, "x-dynamic-options": {
        "field_name": name + "_id", "searchable": True, "allow_custom": True,
        **({"depends_on": list(parents)} if parents else {})}}


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
    _ids = field_validator("event_id", "contact_id", "session_id", "speaker_id", "partner_id", "registration_id", "contact_list_id", mode="before", check_fields=False)(lambda value: None if value is None else identifier(value))


class _Page(_Operation):
    page: int = Field(0, ge=0, le=9999, strict=True, title="Page", description="Documented zero-based page.")
    size: int = Field(50, ge=1, le=100, strict=True, title="Page Size", description="Local maximum100; public provider maximum200.")


class GetAccount(_Operation):
    operation: Literal["get_account"] = Field("get_account", title="Get Bound Account Metadata")


class ListEvents(_Page):
    operation: Literal["list_events"] = Field("list_events", title="List Account Events")
    status: Optional[Literal["draft", "published"]] = Field(None, title="Event Status Filter")
    sort: Optional[Literal["startDate,desc"]] = Field(None, title="Sort", description="Exact documented sort example; arbitrary sort/predicate text is unsupported.")


class _Event(_Operation):
    event_id: str = Field(..., title="Event", json_schema_extra=resource("event"))


class GetEvent(_Event):
    operation: Literal["get_event"] = Field("get_event", title="Get Current Event Metadata")


class ListAccountContacts(_Page):
    operation: Literal["list_account_contacts"] = Field("list_account_contacts", title="List Account Contact Metadata")
    contact_id_filter: Optional[str] = Field(None, title="Exact Contact ID Filter")
    _filter = field_validator("contact_id_filter", mode="before")(lambda value: None if value is None else identifier(value))


class ListEventContacts(_Page, _Event):
    operation: Literal["list_event_contacts"] = Field("list_event_contacts", title="List Event Contact Metadata")
    contact_list_id: Optional[str] = Field(None, title="Event Contact List", json_schema_extra=resource("contact_list", ("event_id",)))


class _Contact(_Event):
    contact_id: str = Field(..., title="Event Contact", json_schema_extra=resource("contact", ("event_id",)))


class GetEventContact(_Contact):
    operation: Literal["get_event_contact"] = Field("get_event_contact", title="Get Scoped Event Contact")


class _Owned(_Operation):
    owned_disposable_confirmed: Literal[True] = Field(..., title="Owned Disposable Contact Confirmed", description="Real contact metadata changes, including potential platform automation. Not a quiet or notification-free guarantee.")
    _confirm = field_validator("owned_disposable_confirmed", mode="before")(lambda value: value if type(value) is bool and value else (_ for _ in ()).throw(ValueError("Confirm the owned disposable contact effects")))


class _Names(_Operation):
    first_name: str = Field(..., max_length=200, title="First Name")
    last_name: str = Field(..., max_length=200, title="Last Name")
    _first = field_validator("first_name", mode="before")(plain)
    _last = field_validator("last_name", mode="before")(plain)


class CreateEventContact(_Owned, _Names, _Event):
    operation: Literal["create_event_contact"] = Field("create_event_contact", title="Add Owned Event Contact", description="Adds a real contact to this event, without a registration/order/invitation API. Platform automation effects require qualification.")
    email: str = Field(..., title="Contact Email", json_schema_extra={"ui:sensitive": True})
    _email = field_validator("email", mode="before")(validate_email)


class UpdateEventContactMetadata(_Owned, _Names, _Contact):
    operation: Literal["update_event_contact_metadata"] = Field("update_event_contact_metadata", title="Update Unregistered Contact Names", description="Current contact must explicitly show no tickets; copies its existing email and writes only first/last name. No roles or arbitrary properties.")
    expected_email: str = Field(..., title="Expected Current Contact Email", json_schema_extra={"ui:sensitive": True})
    _email = field_validator("expected_email", mode="before")(validate_email)


class ListEventContactLists(_Page, _Event):
    operation: Literal["list_event_contact_lists"] = Field("list_event_contact_lists", title="List Event Contact Lists")
    list_name: Optional[str] = Field(None, title="Exact List Name", max_length=200, description="Only documented name= filter; URL encoding is performed once.")
    _name = field_validator("list_name", mode="before")(lambda value: None if value is None else plain(value))


class ListEventSessions(_Page, _Event):
    operation: Literal["list_event_sessions"] = Field("list_event_sessions", title="List Event Session Metadata")


class GetEventSession(_Event):
    operation: Literal["get_event_session"] = Field("get_event_session", title="Get Event Session Metadata")
    session_id: str = Field(..., title="Session", json_schema_extra=resource("session", ("event_id",)))


class ListEventSpeakers(_Page, _Event):
    operation: Literal["list_event_speakers"] = Field("list_event_speakers", title="List Event Speaker Metadata")


class GetEventSpeaker(_Event):
    operation: Literal["get_event_speaker"] = Field("get_event_speaker", title="Get Event Speaker Metadata")
    speaker_id: str = Field(..., title="Speaker", json_schema_extra=resource("speaker", ("event_id",)))


class ListEventPartners(_Page, _Event):
    operation: Literal["list_event_partners"] = Field("list_event_partners", title="List Event Partner Metadata")


class GetEventPartner(_Event):
    operation: Literal["get_event_partner"] = Field("get_event_partner", title="Get Event Partner Metadata")
    partner_id: str = Field(..., title="Partner", json_schema_extra=resource("partner", ("event_id",)))


class ListEventRegistrationsV2(_Page, _Event):
    operation: Literal["list_event_registrations_v2"] = Field("list_event_registrations_v2", title="List Event Registration Metadata (v2)", description="Exact operation server override /v2. Missing page metadata leaves continuation unknown.")


class GetEventRegistrationV2(_Event):
    operation: Literal["get_event_registration_v2"] = Field("get_event_registration_v2", title="Get Event Registration Metadata (v2)")
    registration_id: str = Field(..., title="Registration ID", description="Registration resource id, not ticketId (registration type).", json_schema_extra={"x-resource-type": "bizzabo_registration"})


class ListEventRegistrationTypesV2(_Page, _Event):
    operation: Literal["list_event_registration_types_v2"] = Field("list_event_registration_types_v2", title="List Event Registration Type Metadata (v2)")


BizzaboOperation = Annotated[Union[GetAccount, ListEvents, GetEvent, ListAccountContacts, ListEventContacts, GetEventContact, CreateEventContact, UpdateEventContactMetadata, ListEventContactLists, ListEventSessions, GetEventSession, ListEventSpeakers, GetEventSpeaker, ListEventPartners, GetEventPartner, ListEventRegistrationsV2, GetEventRegistrationV2, ListEventRegistrationTypesV2], Discriminator("operation")]
OPS = ("get_account", "list_events", "get_event", "list_account_contacts", "list_event_contacts", "get_event_contact", "create_event_contact", "update_event_contact_metadata", "list_event_contact_lists", "list_event_sessions", "get_event_session", "list_event_speakers", "get_event_speaker", "list_event_partners", "get_event_partner", "list_event_registrations_v2", "get_event_registration_v2", "list_event_registration_types_v2")


class BizzaboNodeConfig(NodeConfig[BizzaboOperation, BizzaboClientCredentialsCredential]):
    pass


class _Privacy(logging.Filter):
    def filter(self, record):
        return not _PRIVATE.get()


class _Refused(ValueError):
    pass


class _Unverified(RuntimeError):
    pass


def _json(payload):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def _route(method, path, params, body):
    eid = r"[1-9][0-9]{0,18}"
    allowed = set()
    if not isinstance(params, dict):
        raise ValueError("Use native Bizzabo parameters")
    if method == "GET":
        if path == "/v1/account" or re.fullmatch("/v1/events/" + eid, path):
            pass
        elif re.fullmatch("/v1/events/" + eid + "/(?:contacts/" + eid + "|agenda/sessions/" + eid + "|speakers/" + eid + "|partners/" + eid + ")", path) or re.fullmatch("/v2/events/" + eid + "/registrations/" + eid, path):
            pass
        elif path == "/v1/events":
            allowed = {"page", "size", "filter", "sort"}
            if "filter" in params and params["filter"] not in {"status=draft", "status=published"} or "sort" in params and params["sort"] != "startDate,desc":
                raise ValueError("Use the documented bounded event filters")
        elif path == "/v1/contacts" or re.fullmatch("/v1/events/" + eid + "/contacts", path):
            allowed = {"page", "size", "contactIds", "listId"}
        elif re.fullmatch("/v1/events/" + eid + "/contacts/lists", path):
            allowed = {"page", "size", "filter"}
            if "filter" in params and (not isinstance(params["filter"], str) or not params["filter"].startswith("name=")):
                raise ValueError("Use the documented exact contact-list name filter")
        elif re.fullmatch("/v1/events/" + eid + "/(?:agenda/sessions|speakers|partners)", path) or re.fullmatch("/v2/events/" + eid + "/(?:registrations|registrationTypes)", path):
            allowed = {"page", "size"}
        else:
            raise ValueError("Unsupported Bizzabo public route")
        if body is not None:
            raise ValueError("Bizzabo metadata reads do not send bodies")
    elif method in {"POST", "PUT"} and re.fullmatch("/v1/events/" + eid + "/contacts" + ("/" + eid if method == "PUT" else ""), path):
        if not isinstance(body, dict) or set(body) != {"properties"} or not isinstance(body["properties"], dict) or set(body["properties"]) != {"email", "firstName", "lastName"}:
            raise ValueError("Use only native contact identity/name fields")
        validate_email(body["properties"]["email"]); plain(body["properties"]["firstName"]); plain(body["properties"]["lastName"])
    else:
        raise ValueError("Unsupported native Bizzabo method or effect")
    if set(params) - allowed:
        raise ValueError("Unsupported native Bizzabo parameters")
    for key in ("page", "size"):
        if key in params and (type(params[key]) is not int or not (0 <= params[key] <= 9999 if key == "page" else 1 <= params[key] <= 100)):
            raise ValueError("Use bounded native Bizzabo page parameters")
    for key in ("contactIds", "listId"):
        if key in params and (type(params[key]) is not int or not 1 <= params[key] <= 9223372036854775807):
            raise ValueError("Use native Bizzabo numeric contact filters")


async def _http(data, method, url, *, headers=None, params=None, body=None):
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, _Privacy) for item in logger.filters):
            logger.addFilter(_Privacy())
    mark = _PRIVATE.set(True)
    try:
        await current_credential(data)
        async with guarded_async_client(timeout=25.0, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                await current_credential(data)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise _Unverified("Bizzabo response exceeds the local bound; write outcome may be unknown")
                await current_credential(data)
                if response.status_code in {400, 401, 403, 404, 405, 409, 422}:
                    raise _Refused("Bizzabo refused current access or the selected public operation")
                if response.status_code != 200:
                    raise _Unverified("Bizzabo did not confirm the documented status; write outcome may be unknown")
                if "json" not in response.headers.get("content-type", "").lower():
                    raise _Unverified("Bizzabo JSON response is unverified")
                try:
                    raw = _json(bytes(content))
                except (ValueError, TypeError):
                    raise _Unverified("Bizzabo JSON response is unverified") from None
                if not isinstance(raw, dict):
                    raise _Unverified("Bizzabo object envelope is unverified")
                if "error" in raw or "errors" in raw:
                    raise _Refused("Bizzabo returned a provider refusal")
                return raw
    except (_Refused, _Unverified):
        raise
    except ValueError:
        raise ValueError("Bizzabo current authority or public-origin policy refused the operation") from None
    except Exception:
        raise _Unverified("Bizzabo operation could not complete; write outcome may be unknown") from None
    finally:
        _PRIVATE.reset(mark)


async def access_token(data):
    current = await current_credential(data)
    async with data.lock:
        await current_credential(data)
        if data.token is not None and time.monotonic() < data.expires_at:
            return data.token
        # No default credential chain, persistent token/secret overlay or refresh token.
        body = {"client_id": current["client_id"], "client_secret": current["client_secret"],
            "account_id": int(current["account_id"]), "audience": "https://api.bizzabo.com/api", "grant_type": "client_credentials"}
        url = AUTH_ORIGIN + "/oauth/token"
        assert_exact_url_origin(url, AUTH_ORIGIN)
        raw = await _http(data, "POST", url, headers={"Accept": "application/json", "Content-Type": "application/json"}, body=body)
        token, ttl = raw.get("access_token"), raw.get("expires_in")
        if raw.get("token_type") != "Bearer" or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{20,8192}", token) or type(ttl) is not int or not 1 <= ttl <= 86400:
            raise RuntimeError("Bizzabo token grant or expiration is unverified")
        await current_credential(data)
        data.token, data.expires_at = token, time.monotonic() + ttl - min(30.0, ttl / 10)
        return token


async def request(data, method, path, *, params=None, body=None):
    params = {} if params is None else params
    _route(method, path, params, body)
    data = runtime(data)
    token = await access_token(data)
    url = API_ORIGIN + path
    assert_exact_url_origin(url, API_ORIGIN)
    await current_credential(data)
    return await _http(data, method, url, headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Bearer " + token}, params=params, body=body)


def rid(value):
    try:
        if type(value) is int:
            value = str(value)
        return identifier(value)
    except ValueError:
        raise RuntimeError("Bizzabo returned an invalid record ID") from None


def safe(value, maximum=500):
    try:
        return plain(value, maximum)
    except ValueError:
        raise RuntimeError("Bizzabo returned invalid text metadata") from None


def project(raw, kind, event=None):
    if not isinstance(raw, dict):
        raise RuntimeError("Bizzabo record envelope is unverified")
    out = {"id": rid(raw.get("id"))}
    if event is not None:
        if (kind in {"contact", "partner", "registration", "registration_type"} or raw.get("eventId") is not None) and rid(raw.get("eventId")) != event:
            raise ValueError("Bizzabo current event ancestry differs")
        out["event_id"] = event
    fields = {
        "account": ("name", "created"),
        "event": ("name", "status", "timezone", "startDate", "endDate", "created", "modified"),
        "contact": ("created", "modified"),
        "session": ("title", "startDate", "endDate"),
        "speaker": ("firstname", "lastname", "title", "company", "created", "modified"),
        "partner": ("name", "type", "created"),
        "contact_list": ("name", "type", "created"),
        "registration": ("formSubmissionStatus", "validity", "registrationDate", "created", "modified", "ticketName"),
        "registration_type": ("name",),
    }[kind]
    for key in fields:
        if raw.get(key) not in (None, ""):
            out[key] = safe(raw[key])
    if kind == "account" and not out.get("name"):
        raise RuntimeError("Bizzabo account identity envelope is incomplete")
    if kind == "event" and any(not out.get(k) for k in ("name", "status", "timezone", "startDate", "endDate", "created", "modified")):
        raise RuntimeError("Bizzabo current event metadata is incomplete")
    if kind == "contact":
        props = raw.get("properties")
        if not isinstance(props, dict):
            raise RuntimeError("Bizzabo contact properties are unverified")
        for key in ("firstName", "lastName"):
            if props.get(key) not in (None, ""):
                out[key] = safe(props[key], 200)
    if kind == "session":
        if not out.get("title"):
            raise RuntimeError("Bizzabo session title is missing")
        for key in ("startMinute", "endMinute"):
            if raw.get(key) is not None:
                if type(raw[key]) not in (int, float) or not 0 <= raw[key] <= 1440:
                    raise RuntimeError("Bizzabo session minute metadata is invalid")
                out[key] = raw[key]
    if kind == "registration":
        for key, allowed in (("formSubmissionStatus", {"unassigned", "assigned", "registered"}), ("validity", {"valid", "invalid"})):
            if not isinstance(raw.get(key), str) or raw[key] not in allowed:
                raise RuntimeError("Bizzabo registration state metadata is unverified")
        for key in ("contactId", "ticketId"):
            if raw.get(key) is not None: out[key] = rid(raw[key])
    # No email, contact/address/billing/financial/roles, arbitrary properties,
    # links, magic/manage links, images, recordings, attachments or external URLs.
    return out


async def account(data):
    raw = await request(data, "GET", "/v1/account")
    out = project(raw, "account")
    if out["id"] != (await current_credential(data))["account_id"]:
        raise ValueError("Bizzabo protected account identity differs from the configured account")
    return out


async def event(data, eid):
    raw = await request(data, "GET", "/v1/events/" + eid)
    out = project(raw, "event")
    if out["id"] != eid:
        raise ValueError("Bizzabo current event witness differs")
    return out


async def contact(data, eid, cid):
    raw = await request(data, "GET", f"/v1/events/{eid}/contacts/{cid}")
    out = project(raw, "contact", eid)
    if out["id"] != cid:
        raise ValueError("Bizzabo current contact witness differs")
    return raw, out


def collection(raw, cfg, *, optional_page=False):
    rows = raw.get("content")
    if not isinstance(rows, list) or len(rows) > cfg["size"] or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Bizzabo bounded content envelope is unverified")
    p = raw.get("page")
    if p is None and optional_page:
        return rows, {"pagination": None, "has_more": None, "next_page_token": None}
    if not isinstance(p, dict) or any(type(p.get(k)) is not int or p[k] < 0 for k in ("size", "totalElements", "totalPages", "number")) or p["size"] != cfg["size"] or p["number"] != cfg["page"] or p["totalPages"] > 10000:
        raise RuntimeError("Bizzabo page binding is unverified or exceeds the local bound")
    more = p["number"] + 1 < p["totalPages"]
    return rows, {"pagination": {k: p[k] for k in ("size", "totalElements", "totalPages", "number")}, "has_more": more, "next_page_token": str(p["number"] + 1) if more else None}


def unique(rows):
    if len({row["id"] for row in rows}) != len(rows):
        raise RuntimeError("Bizzabo returned duplicate scoped IDs")
    return rows


LISTS = {
    "list_events": ("/v1/events", "event"),
    "list_account_contacts": ("/v1/contacts", "contact"),
    "list_event_contacts": ("/v1/events/{event}/contacts", "contact"),
    "list_event_contact_lists": ("/v1/events/{event}/contacts/lists", "contact_list"),
    "list_event_sessions": ("/v1/events/{event}/agenda/sessions", "session"),
    "list_event_speakers": ("/v1/events/{event}/speakers", "speaker"),
    "list_event_partners": ("/v1/events/{event}/partners", "partner"),
    "list_event_registrations_v2": ("/v2/events/{event}/registrations", "registration"),
    "list_event_registration_types_v2": ("/v2/events/{event}/registrationTypes", "registration_type"),
}
GETS = {
    "get_event_session": ("agenda/sessions", "session_id", "session"),
    "get_event_speaker": ("speakers", "speaker_id", "speaker"),
    "get_event_partner": ("partners", "partner_id", "partner"),
    "get_event_registration_v2": ("registrations", "registration_id", "registration"),
}


async def records(data, args):
    cfg = TypeAdapter(BizzaboOperation).validate_python(args).model_dump()
    data = runtime(data)
    identity = await account(data)
    common = {"read_completed": True, "identity_verified": True, "account_id": identity["id"]}
    op, eid = cfg["operation"], cfg.get("event_id")
    if op == "get_account":
        return {**common, "name": identity["name"], "record": identity}
    if eid is not None:
        current_event = await event(data, eid)
        common["event_id"] = eid
    if op == "get_event":
        return {**common, "record": current_event}
    if op in LISTS:
        path, kind = LISTS[op]
        params = {"page": cfg["page"], "size": cfg["size"]}
        if cfg.get("status"): params["filter"] = "status=" + cfg["status"]
        if cfg.get("sort"): params["sort"] = cfg["sort"]
        if cfg.get("contact_id_filter"): params["contactIds"] = int(cfg["contact_id_filter"])
        if cfg.get("contact_list_id"):
            found = False
            for page in range(10):
                lists = await records(data, {"operation": "list_event_contact_lists", "event_id": eid, "page": page, "size": 100})
                if any(row["id"] == cfg["contact_list_id"] for row in lists["records"]):
                    found = True
                    break
                if lists["has_more"] is not True:
                    break
            if not found:
                raise ValueError("Bizzabo contact list lacks a current event witness within ten bounded pages")
            params["listId"] = int(cfg["contact_list_id"])
        if cfg.get("list_name"): params["filter"] = "name=" + cfg["list_name"]
        raw = await request(data, "GET", path.format(event=eid), params=params)
        rows, paging = collection(raw, cfg, optional_page=op == "list_event_registrations_v2")
        return {**common, "records": unique([project(row, kind, eid) for row in rows]), **paging}
    if op in GETS:
        suffix, field, kind = GETS[op]
        path = f"/{'v2' if kind == 'registration' else 'v1'}/events/{eid}/{suffix}/{cfg[field]}"
        out = project(await request(data, "GET", path), kind, eid)
        if out["id"] != cfg[field]:
            raise ValueError("Bizzabo selected event resource differs")
        return {**common, "record": out}
    if op == "get_event_contact":
        _, out = await contact(data, eid, cfg["contact_id"])
        return {**common, "record": out}
    if op == "update_event_contact_metadata":
        before, _ = await contact(data, eid, cfg["contact_id"])
        props = before["properties"]
        if props.get("email") != cfg["expected_email"] or props.get("hasTickets") is not False or type(props.get("ticketCount")) is not int or props["ticketCount"] != 0 or props.get("ticketType") != []:
            raise ValueError("Bizzabo selected disposable contact or explicit unregistered state differs")
        mail, method, path = cfg["expected_email"], "PUT", f"/v1/events/{eid}/contacts/{cfg['contact_id']}"
    else:
        mail, method, path = cfg["email"], "POST", f"/v1/events/{eid}/contacts"
    body = {"properties": {"email": mail, "firstName": cfg["first_name"], "lastName": cfg["last_name"]}}
    written = project(await request(data, method, path, body=body), "contact", eid)
    cid = written["id"]
    if method == "PUT" and cid != cfg["contact_id"]:
        raise RuntimeError("Bizzabo contact write receipt differs; do not retry")
    raw, checked = await contact(data, eid, cid)
    if any(raw["properties"].get(k) != v for k, v in body["properties"].items()):
        raise RuntimeError("Bizzabo contact write readback differs; do not retry")
    return {**common, "mutation_completed": True, "record": checked, "name_readback_match": True}


class BizzaboNode(WorkflowNode):
    integration_type = "automation-bizzabo"
    scope_registry = ScopeRegistry(provider="bizzabo", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="Bizzabo account", identity_keys=("name", "account_id"), proves="account")
    edit_examples = ["Read current event sessions, speakers and partner metadata", "Read v2 registration metadata without signed links or billing fields", "Maintain names on explicitly owned unregistered event contacts"]
    @classmethod
    def get_config_model(cls):
        return BizzaboNodeConfig
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
                return {"valid": False, "errors": ["Connect native Bizzabo PUBLIC client credentials"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # The shared hook supplies actor/id; resolve the actor's current org like
        # other staging nodes. Client-credentials grants need no OAuth handler.
        organization_id = None
        if credential_id and user_id:
            from repositories.organization import OrgRepo
            from utils.database_pool import get_native_pool
            if pool is None:
                pool = get_native_pool()
            async with pool.acquire() as conn:
                organization_id = await OrgRepo(pool).get_primary_org_id(conn, user_id)
        return await bound_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, organization_id=organization_id)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            result = await account(runtime(credential_data))
            return {"valid": True, "identity_verified": True,
                    "proves": "account", "account_id": result["id"]}
        except ValueError:
            return {"valid": False, "error": "Bizzabo current account or public operation refused"}
        except Exception:
            return {"valid": None, "error": "Bizzabo current account access could not be judged"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        options = {"event_id": "list_events", "contact_id": "list_event_contacts", "contact_list_id": "list_event_contact_lists", "session_id": "list_event_sessions", "speaker_id": "list_event_speakers", "partner_id": "list_event_partners"}
        if field_name not in options:
            return {"options": [], "has_more": False, "next_page_token": None}
        search = normalize_search(search)
        if search and (len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise ValueError("Use a bounded Bizzabo picker search")
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"0|[1-9][0-9]{0,3}", page_token)):
            raise ValueError("Use the native Bizzabo zero-based page token")
        cfg = {"operation": options[field_name], "page": int(page_token or "0"), "size": 100}
        if field_name != "event_id":
            cfg["event_id"] = identifier((context or {}).get("event_id"))
        result = await records(credential_data, cfg)
        labels = [(row.get("name") or row.get("title") or " ".join(str(row.get(k, "")) for k in ("firstName", "lastName", "firstname", "lastname")).strip() or row["id"]) for row in result["records"]]
        out = [{"value": row["id"], "label": label} for row, label in zip(result["records"], labels)]
        return {"options": filter_options_by_search(out, search), "has_more": result["has_more"], "next_page_token": result["next_page_token"]}
    async def execute(self, inputs):
        if not isinstance(self.config, BizzaboNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect native Bizzabo PUBLIC client credentials")
        raw = (self.node_data or {}).get("credentials")
        data = await bound_credential(raw if raw is not None else self.config.credentials.model_dump(), user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id") or ((self.node_data or {}).get("credentialIds") or {}).get(FAMILY),
            workflow_id=self.workflow_id, organization_id=self.organization_id)
        return await records(data, self.config.config.model_dump())
