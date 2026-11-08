"""YouCanBookMe protected profile metadata and bounded account booking queries.

Individual bookings are documented as public: protected account/profile ancestry
is checked first, and neither a public booking nor an empty list proves identity.
"""
from __future__ import annotations
import base64
import contextvars
from datetime import datetime
import hashlib
import hmac
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qsl, urljoin, urlsplit
from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.youcanbookme import YOUCANBOOKME_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN = "https://api.youcanbook.me"
MAX_JSON = 2 * 1024 * 1024
MAX_COLLECTION = 1000
RESOURCE_ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
PROFILE_FIELDS = "id,accountId,title,description,status,subdomain,locale,timeZone,createdAt,updatedAt"
TEAM_FIELDS = PROFILE_FIELDS + ",teamMembers,teamMembers.active,teamMembers.items,teamMembers.items.id,teamMembers.items.name,teamMembers.items.description"
TYPE_FIELDS = PROFILE_FIELDS + ",appointmentTypes,appointmentTypes.active,appointmentTypes.items,appointmentTypes.items.id,appointmentTypes.items.name,appointmentTypes.items.description,appointmentTypes.items.slotLength,appointmentTypes.items.numberOfSlots"
BOOKING_FIELDS = "id,accountId,profileId,title,ref,createdAt,updatedAt,startsAt,endsAt,timeZone,tentative,cancelled,noShow"
_PRIVATE = contextvars.ContextVar("youcanbookme_private_transport", default=False)

class _PrivateFilter(logging.Filter):
    def filter(self, record): return not _PRIVATE.get()

for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks_proxy"):
    logging.getLogger(_name).addFilter(_PrivateFilter())

class YouCanBookMeDenied(ValueError): pass
class YouCanBookMeUnavailable(ValueError): pass

def _text(value, maximum=256, *, empty=False, multiline=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= maximum or any((ord(c) < 32 and not (multiline and c in "\n\t\r")) or ord(c) == 127 for c in value):
        raise ValueError("Supply bounded YouCanBookMe text without unsupported controls.")
    return value

def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise YouCanBookMeUnavailable("YouCanBookMe returned a malformed resource identifier.")
    return value

def _date(value, *, aware=False):
    value = _text(value, 64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value or (aware and parsed.utcoffset() is None): raise ValueError()
    except Exception: raise ValueError("Use a valid ISO datetime with an offset for booking query boundaries.") from None
    return value

class YouCanBookMeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="YouCanBookMe Account API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://support.youcanbook.me/hc/en-us/articles/17321549364375-Accessing-your-account-API-key"})
    credential_type: Literal["youcanbookme_api_key"] = Field("youcanbookme_api_key", json_schema_extra={"ui:hidden": True})
    account_id: RESOURCE_ID = Field(..., description="Exact account ID paired with this issued key. Team account access requires the organization owner's matching account/key; entitlement is not assumed.")
    auth_username: str = Field(..., max_length=320, repr=False, description="HTTP Basic username: this account ID or its account email. Do not enter a login password here.")
    api_key: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"}, description="Already issued account API key, used as the HTTP Basic password. This is not your account login password, OAuth token or a key-issuance action.")
    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 32768 or any(ord(c) < 33 or ord(c) > 126 for c in value): raise ValueError("Supply the issued YouCanBookMe API key without whitespace.")
        return value
    @field_validator("auth_username", mode="before")
    @classmethod
    def username(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 320 or ":" in value or any(ord(c) < 33 or ord(c) > 126 for c in value): raise ValueError("Use the account ID or account email as the Basic username.")
        return value
    @model_validator(mode="after")
    def paired_username(self):
        if self.auth_username != self.account_id and not re.fullmatch(r"[^@\s:]+@[^@\s:]+\.[^@\s:]+", self.auth_username): raise ValueError("The Basic username must be this account ID or an account email.")
        return self

def _credential(value):
    if isinstance(value, YouCanBookMeAPIKeyCredential): return value
    if not isinstance(value, dict) or value.get("credential_type") != "youcanbookme_api_key": raise ValueError("Attach the native YouCanBookMe account API-key family.")
    try: return YouCanBookMeAPIKeyCredential.model_validate({key: item for key, item in value.items() if key not in ("token_version", "updated_at")})
    except Exception: raise ValueError("Check the current YouCanBookMe account ID, Basic username and issued API key.") from None

def _op(value, label, category="Metadata"):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

def _selector(kind, parents=()):
    return {"x-resource-type": "youcanbookme_" + kind, "x-dynamic-options": {"field_name": kind + "_id", "searchable": True, "allow_custom": True, **({"depends_on": list(parents)} if parents else {})}}

class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
class _Page(_Config):
    per_page: int = Field(25, strict=True, ge=1, le=100, description="Native page of the bounded profile or embedded-item collection, not an invented provider limit parameter.")
    page_token: Optional[str] = Field(None, max_length=8192, description="Native continuation bound to the current account, credential, parents and filters. Never a provider URL.")
    search: str = Field("", max_length=128, description="Bounded native label filter.")
    @field_validator("search", mode="before")
    @classmethod
    def text(cls, value): return _text(value, 128, empty=True)
class _Profile(_Config):
    profile_id: RESOURCE_ID = Field(..., json_schema_extra=_selector("profile"), description="An existing profile returned by this account's protected profile list.")
class YouCanBookMeTestConfig(_Config):
    operation: Literal["test_connection"] = _op("test_connection", "Test Protected Account Profiles", "Connection")
class YouCanBookMeAccountConfig(_Config):
    operation: Literal["get_account_scope"] = _op("get_account_scope", "Inspect Account Scope from Protected Profiles", "Connection")
class YouCanBookMeProfilesConfig(_Page):
    operation: Literal["list_profiles"] = _op("list_profiles", "List Account Profiles")
class YouCanBookMeProfileConfig(_Profile):
    operation: Literal["get_profile"] = _op("get_profile", "Get Profile Metadata")
class YouCanBookMeTeamMembersConfig(_Profile, _Page):
    operation: Literal["list_team_members"] = _op("list_team_members", "List Profile Team Members")
class YouCanBookMeTeamMemberConfig(_Profile):
    operation: Literal["get_team_member"] = _op("get_team_member", "Get Profile Team Member Metadata")
    team_member_id: RESOURCE_ID = Field(..., json_schema_extra=_selector("team_member", ("profile_id",)))
class YouCanBookMeAppointmentTypesConfig(_Profile, _Page):
    operation: Literal["list_appointment_types"] = _op("list_appointment_types", "List Profile Appointment Types")
class YouCanBookMeAppointmentTypeConfig(_Profile):
    operation: Literal["get_appointment_type"] = _op("get_appointment_type", "Get Profile Appointment Type Metadata")
    appointment_type_id: RESOURCE_ID = Field(..., json_schema_extra=_selector("appointment_type", ("profile_id",)))
class YouCanBookMeBookingConfig(_Profile):
    operation: Literal["get_booking"] = _op("get_booking", "Read Booking Metadata with Protected Ancestry", "Bookings")
    booking_id: RESOURCE_ID = Field(..., description="Existing booking ID, not an arbitrary URL or an intent. Public booking access alone is not credential proof.")
class YouCanBookMeQueryConfig(_Config):
    operation: Literal["query_bookings"] = _op("query_bookings", "Query Bounded Account Bookings", "Bookings")
    profile_id: Optional[RESOURCE_ID] = Field(None, json_schema_extra=_selector("profile"), description="Optional existing protected profile filter; otherwise this account's profiles only.")
    from_time: str = Field(..., max_length=64, description="Required ISO datetime with offset, transmitted as from. StartsAt and createdAt sorting are documented by vendor staff.")
    to_time: Optional[str] = Field(None, max_length=64, description="Optional ISO datetime with offset, transmitted as to.")
    direction: Literal["forwards", "backwards"] = Field("forwards")
    time_criteria: Literal["startsAt", "createdAt"] = Field("startsAt")
    sort_by: Literal["startsAt", "createdAt"] = Field("startsAt")
    page_size: int = Field(50, strict=True, ge=10, le=500)
    status: Optional[Literal["tentative", "rejected", "cancelled", "upcoming", "inProgress", "finished", "noShow"]] = Field(None, description="One documented status filter. Returned status text is preserved: vendor has also documented later snake_case responses.")
    search_text: Optional[str] = Field(None, min_length=3, max_length=256)
    search_criteria: Literal["title", "form", "ref"] = Field("title", description="One documented searchTextCriteria filter; no guessed array encoding.")
    page_token: Optional[str] = Field(None, max_length=8192)
    @field_validator("from_time", "to_time", mode="before")
    @classmethod
    def date(cls, value): return None if value is None else _date(value, aware=True)
    @field_validator("search_text", mode="before")
    @classmethod
    def text(cls, value): return None if value is None else _text(value, 256)
    @model_validator(mode="after")
    def interval(self):
        if self.to_time:
            start = datetime.fromisoformat(self.from_time.replace("Z", "+00:00")); end = datetime.fromisoformat(self.to_time.replace("Z", "+00:00"))
            if (self.direction == "forwards" and end < start) or (self.direction == "backwards" and end > start): raise ValueError("The end boundary must follow the chosen query direction.")
        return self

YouCanBookMeOperation = Annotated[Union[YouCanBookMeTestConfig, YouCanBookMeAccountConfig, YouCanBookMeProfilesConfig, YouCanBookMeProfileConfig, YouCanBookMeTeamMembersConfig, YouCanBookMeTeamMemberConfig, YouCanBookMeAppointmentTypesConfig, YouCanBookMeAppointmentTypeConfig, YouCanBookMeBookingConfig, YouCanBookMeQueryConfig], Discriminator("operation")]
class YouCanBookMeNodeConfig(NodeConfig[YouCanBookMeOperation, YouCanBookMeAPIKeyCredential]): pass

def _row(raw):
    if not isinstance(raw, dict): raise YouCanBookMeUnavailable("YouCanBookMe metadata response is malformed.")
    return raw

def _metadata(raw, allowed, result):
    for key in allowed:
        value = raw.get(key)
        if value is None: continue
        if key in ("createdAt", "updatedAt", "startsAt", "endsAt", "starts", "ends"): result[key] = _date(value, aware=key in ("createdAt", "updatedAt"))
        elif key in ("tentative", "cancelled", "noShow", "active"):
            if type(value) is not bool: raise YouCanBookMeUnavailable("YouCanBookMe Boolean metadata is malformed.")
            result[key] = value
        elif key == "numberOfSlots":
            if type(value) is not int or not 0 <= value <= 100000: raise YouCanBookMeUnavailable("YouCanBookMe slot metadata is malformed.")
            result[key] = value
        else: result[key] = _text(value, 2048 if key == "description" else 512, empty=True, multiline=key == "description")
    return result

def _profile(raw, account, selected=None):
    raw = _row(raw)
    if raw.get("accountId") != account: raise YouCanBookMeDenied("YouCanBookMe returned a profile from a different selected account.")
    ident = _id(raw.get("id"))
    if selected and ident != selected: raise YouCanBookMeDenied("YouCanBookMe returned a different selected profile.")
    result = _metadata(raw, ("title", "description", "status", "subdomain", "locale", "timeZone", "createdAt", "updatedAt"), {"id": ident, "account_id": account})
    if result.get("status") not in (None, "ONLINE", "OFFLINE"): raise YouCanBookMeUnavailable("YouCanBookMe returned an unexpected profile status.")
    return result

def _collection(raw):
    if not isinstance(raw, list) or len(raw) > MAX_COLLECTION: raise YouCanBookMeUnavailable("YouCanBookMe collection exceeds its bound or is malformed.")
    return raw

def _unique(items):
    if len({item["id"] for item in items}) != len(items): raise YouCanBookMeUnavailable("YouCanBookMe duplicated a resource identity.")
    return items

def _embedded(raw, kind, account, profile):
    section = _row(_row(raw).get(kind))
    rows = _collection(section.get("items"))
    fields = ("name", "description") if kind == "teamMembers" else ("name", "description", "slotLength", "numberOfSlots")
    items = _unique([_metadata(_row(row), fields, {"id": _id(row.get("id")), "account_id": account, "profile_id": profile}) for row in rows])
    active = section.get("active")
    if active is not None and type(active) is not bool: raise YouCanBookMeUnavailable("YouCanBookMe embedded metadata is malformed.")
    return items, active

def _booking(raw, account, profiles, selected=None, profile=None, *, query=False):
    raw = _row(raw)
    if raw.get("accountId") != account: raise YouCanBookMeDenied("YouCanBookMe booking belongs to a different selected account.")
    parent = raw.get("bookingPageId") if query else raw.get("profileId")
    if parent not in profiles or (profile and parent != profile): raise YouCanBookMeDenied("YouCanBookMe booking is outside the currently protected profile scope.")
    if raw.get("profileId") is not None and raw.get("bookingPageId") is not None and raw["profileId"] != raw["bookingPageId"]: raise YouCanBookMeDenied("YouCanBookMe booking profile metadata disagrees.")
    ident = _id(raw.get("id"))
    if selected and ident != selected: raise YouCanBookMeDenied("YouCanBookMe returned a different booking ID.")
    return _metadata(raw, ("title", "ref", "createdAt", "updatedAt", "startsAt", "endsAt", "starts", "ends", "timeZone", "tentative", "cancelled", "noShow", "status"), {"id": ident, "account_id": account, "profile_id": _id(parent)})

def _ticket(credential, authority, config, *, payload=None, token=None):
    scope = hashlib.sha256(json.dumps([credential.model_dump(), authority, config.model_dump(exclude={"page_token"})], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if token is None:
        body = base64.urlsafe_b64encode(json.dumps({"v": 1, "scope": scope, "payload": payload}, separators=(",", ":")).encode()).decode().rstrip("=")
        result = body + "." + hmac.new(credential.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if len(result) > 8192: raise YouCanBookMeUnavailable("YouCanBookMe continuation exceeds its native bound.")
        return result
    try:
        if not isinstance(token, str) or len(token) > 8192: raise ValueError()
        body, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, hmac.new(credential.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if set(data) != {"v", "scope", "payload"} or data["v"] != 1 or data["scope"] != scope or not isinstance(data["payload"], dict): raise ValueError()
        return data["payload"]
    except Exception: raise ValueError("YouCanBookMe continuation does not match current credential, account, parents and filters.") from None

def _query_params(config):
    values = [("from", config.from_time), ("direction", config.direction), ("searchTimeRangeCriteria", config.time_criteria), ("sortBy", config.sort_by), ("pageSize", str(config.page_size))]
    if config.to_time: values.append(("to", config.to_time))
    if config.profile_id: values.append(("bookingPageIds", config.profile_id))
    if config.status: values.append(("statuses", config.status))
    if config.search_text: values.extend((("searchText", config.search_text), ("searchTextCriteria", config.search_criteria)))
    return values

def _bound_query(values, original, config):
    if len(values) > 12 or any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(isinstance(item, str) for item in pair) for pair in values): raise YouCanBookMeUnavailable("YouCanBookMe pagination parameters are malformed.")
    values = [tuple(pair) for pair in values]
    if len({key for key, _ in values}) != len(values): raise YouCanBookMeUnavailable("YouCanBookMe duplicated a pagination parameter.")
    current, before = dict(values), dict(original)
    if set(current) - (set(before) | {"fromBookingId"}) or set(before) - set(current): raise YouCanBookMeUnavailable("YouCanBookMe pagination changed the selected query shape.")
    for key in set(before) - {"from"}:
        if current.get(key) != before[key]: raise YouCanBookMeUnavailable("YouCanBookMe pagination changed account filters, size or direction.")
    try:
        position = datetime.fromisoformat(_date(current["from"], aware=True).replace("Z", "+00:00"))
        start = datetime.fromisoformat(config.from_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(config.to_time.replace("Z", "+00:00")) if config.to_time else None
        if config.direction == "forwards" and (position < start or (end is not None and position > end)): raise ValueError()
        if config.direction == "backwards" and (position > start or (end is not None and position < end)): raise ValueError()
        if "fromBookingId" in current: _id(current["fromBookingId"])
    except Exception: raise YouCanBookMeUnavailable("YouCanBookMe continuation is outside the selected time window.") from None
    return values

def _next_query(response, path, original, config):
    header = response.headers.get("link")
    if header is None: return None
    if len(header) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in header): raise YouCanBookMeUnavailable("YouCanBookMe Link metadata is malformed.")
    relation = "next" if config.direction == "forwards" else "prev"
    relations = set()
    for member in re.split(r",\s*(?=<)", header):
        match = re.fullmatch(r'\s*<([^<>]+)>\s*;\s*rel\s*=\s*"(next|prev)"\s*', member)
        if not match or match[2] in relations: raise YouCanBookMeUnavailable("YouCanBookMe Link relations are malformed or duplicated.")
        relations.add(match[2])
        parsed = urlsplit(urljoin(ORIGIN + path, match[1]))
        if parsed.scheme != "https" or parsed.netloc != "api.youcanbook.me" or parsed.path != path or parsed.fragment: raise YouCanBookMeUnavailable("YouCanBookMe Link origin or account changed; no URL is followed.")
        try: values = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except Exception: raise YouCanBookMeUnavailable("YouCanBookMe Link query is malformed.") from None
        if match[2] == relation: next_values = _bound_query(values, original, config)
    return next_values if relation in relations else None

class YouCanBookMeNode(WorkflowNode):
    integration_type = "automation-youcanbookme"
    scope_registry = YOUCANBOOKME_SCOPES
    connection_evidence = ConnectionEvidence(noun="account profiles", field="profile_id", identity_operation="test_connection", identity_keys=("account_id",), label_keys=("label", "title", "id"))
    edit_examples = ["List my protected booking profiles", "Read team-member metadata on a selected profile", "Query bookings in a bounded time window", "Inspect appointment types without creating a booking"]
    @classmethod
    def get_config_model(cls): return YouCanBookMeNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        credential = _credential(config_data["credentials"]) if isinstance(config_data, dict) and config_data.get("credentials") is not None else None
        try:
            view = runtime_config_view(config_data, YouCanBookMeNodeConfig)
            if credential is not None: view["credentials"] = credential.model_dump()
            if isinstance(view.get("config"), dict):
                view["config"] = {key: value for key, value in view["config"].items() if not key.endswith("__label") and key not in ("_settings", "agent_tool_operations")}
                if not view["config"]: view.pop("config")
            return TypeAdapter(YouCanBookMeNodeConfig).validate_python(view)
        except Exception: raise ValueError("Check the native YouCanBookMe operation, current credential and typed fields.") from None
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Account API keys do not refresh; the shared loader owns saved access.
        return _credential(credential_data).model_dump()
    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential = _credential(credential_data)
            raw, _ = await cls._request("/v1/profiles", credential=credential, params=[("ownerId", credential.account_id)])
            profiles = _unique([_profile(row, credential.account_id) for row in _collection(raw)])
            if not profiles: return {"valid": None, "error": "An empty protected profile list cannot verify account identity."}
        except YouCanBookMeDenied:
            return {"valid": False, "error": "YouCanBookMe refused the current key or selected account/profile permission."}
        except ValueError:
            return {"valid": None, "error": "YouCanBookMe account access could not be verified."}
        return {"valid": True}
    @classmethod
    async def _request(cls, path, *, credential, params=None, query_config=None, original=None):
        query_path = "/v1/accounts/" + credential.account_id + "/bookings/query"
        if path not in ("/v1/profiles", query_path) and not re.fullmatch(r"/v1/(?:profiles|bookings)/[A-Za-z0-9][A-Za-z0-9_-]{0,127}", path): raise ValueError("Unsupported native YouCanBookMe read path.")
        params = params or []
        allowed = {"ownerId"} if path == "/v1/profiles" else {"fields"} if path != query_path else {"from", "to", "direction", "searchTimeRangeCriteria", "sortBy", "pageSize", "bookingPageIds", "statuses", "searchText", "searchTextCriteria", "fromBookingId"}
        if any(key not in allowed for key, _ in params): raise ValueError("Unsupported native YouCanBookMe read query.")
        if path == "/v1/profiles" and params != [("ownerId", credential.account_id)]: raise ValueError("YouCanBookMe profiles must be scoped to the selected account.")
        if path.startswith("/v1/profiles/") and params not in ([("fields", PROFILE_FIELDS)], [("fields", TEAM_FIELDS)], [("fields", TYPE_FIELDS)]): raise ValueError("Use the native bounded profile field control.")
        if path.startswith("/v1/bookings/") and params != [("fields", BOOKING_FIELDS)]: raise ValueError("Use the native bounded booking field control.")
        if path == query_path and (query_config is None or original is None): raise ValueError("The native bookings query requires its bound typed filters.")
        assert_exact_url_origin(ORIGIN + path, ORIGIN)
        authorization = "Basic " + base64.b64encode((credential.auth_username + ":" + credential.api_key).encode()).decode()
        private = _PRIVATE.set(True)
        try:
            async with guarded_async_client( trust_env=False, follow_redirects=False, timeout=25) as client:
                async with client.stream("GET", ORIGIN + path, headers={"Authorization": authorization, "Accept": "application/json", "User-Agent": "NoClick/1.0 (+https://www.noclick.com)"}, params=params) as response:
                    if response.status_code in (401, 403): raise YouCanBookMeDenied("YouCanBookMe refused the current key or read permission; raw details withheld.")
                    if response.status_code != 200: raise YouCanBookMeUnavailable("YouCanBookMe request is unverified, including missing/rate/service errors; no retry or raw response disclosure.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_JSON: raise YouCanBookMeUnavailable("YouCanBookMe exceeded its native response bound.")
                        content.extend(chunk)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise YouCanBookMeUnavailable("YouCanBookMe returned an unexpected content type.")
                    payload = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and any(payload.get(key) not in (None, [], {}) for key in ("error", "errors", "exception"))): raise YouCanBookMeUnavailable("YouCanBookMe returned an error despite HTTP success.")
                    return payload, _next_query(response, path, original, query_config) if path == query_path else None
        except (YouCanBookMeDenied, YouCanBookMeUnavailable): raise
        except Exception: raise YouCanBookMeUnavailable("YouCanBookMe transport or response could not be verified; key, account email, URLs and raw details withheld.") from None
        finally: _PRIVATE.reset(private)

    async def execute(self, inputs):
        credential, config = _credential(self.config.credentials), self.config.config
        if config is None: raise ValueError("Choose a native YouCanBookMe operation.")
        self.scope_registry.enforce_credential_type(config.operation, credential.credential_type)
        authority = None
        calls = 0
        async def call(path, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 4: raise YouCanBookMeUnavailable("YouCanBookMe exceeded its native request budget.")
            return await self._request(path, credential=credential, **kwargs)
        raw, _ = await call("/v1/profiles", params=[("ownerId", credential.account_id)])
        profiles = _unique([_profile(row, credential.account_id) for row in _collection(raw)])
        known = {row["id"] for row in profiles}
        operation = config.operation
        if operation in ("test_connection", "get_account_scope"):
            if operation == "test_connection" and not profiles: raise YouCanBookMeUnavailable("YouCanBookMe returned an empty protected collection; account identity and access cannot be verified.")
            return {"status": "success", "data": {"selected_account_id": credential.account_id, **({"account_id": credential.account_id} if profiles else {}), "observed_profiles": len(profiles), "reachable": True, "authentication_verified": True if profiles else None, "account_identity_verified": True if profiles else None, "subject_identity_verified": None, "paid_entitlement_verified": None}}
        selected = getattr(config, "profile_id", None)
        if selected and selected not in known: raise YouCanBookMeDenied("The selected YouCanBookMe profile is absent from this account's protected list.")
        if operation == "list_profiles": items = profiles
        elif operation == "query_bookings":
            original = _query_params(config)
            cursor = _ticket(credential, authority, config, token=config.page_token) if config.page_token else {}
            params, seen = original, []
            if cursor:
                if set(cursor) != {"position", "seen"} or not isinstance(cursor["position"], dict) or set(cursor["position"]) - {"from", "fromBookingId"} or "from" not in cursor["position"] or not isinstance(cursor["seen"], list) or len(cursor["seen"]) >= 50 or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in cursor["seen"]): raise ValueError("YouCanBookMe continuation is malformed or exhausted.")
                params = _bound_query([(key, value) for key, value in original if key != "from"] + list(cursor["position"].items()), original, config); seen = cursor["seen"]
            raw, next_query = await call("/v1/accounts/" + credential.account_id + "/bookings/query", params=params, query_config=config, original=original)
            if not isinstance(raw, list) or len(raw) > config.page_size: raise YouCanBookMeUnavailable("YouCanBookMe booking page exceeds its requested bound or is malformed.")
            items = _unique([_booking(row, credential.account_id, known, profile=selected, query=True) for row in raw])
            marker = hashlib.sha256(json.dumps(sorted(params), separators=(",", ":")).encode()).hexdigest()
            token = None
            if next_query:
                next_marker = hashlib.sha256(json.dumps(sorted(next_query), separators=(",", ":")).encode()).hexdigest()
                if not items or next_marker in seen + [marker]: raise YouCanBookMeUnavailable("YouCanBookMe pagination did not advance.")
                token = _ticket(credential, authority, config, payload={"position": {key: value for key, value in next_query if key in ("from", "fromBookingId")}, "seen": seen + [marker]})
            return {"status": "success", "data": {"items": items, "next_page_token": token, "pagination_source": "provider_link", "direction": config.direction, "authentication_verified": True if profiles else None, "account_identity_verified": True if profiles else None, "subject_identity_verified": None, "paid_entitlement_verified": None}}
        else:
            fields = TEAM_FIELDS if operation in ("list_team_members", "get_team_member") else TYPE_FIELDS if operation in ("list_appointment_types", "get_appointment_type") else PROFILE_FIELDS
            raw, _ = await call("/v1/profiles/" + selected, params=[("fields", fields)])
            profile = _profile(raw, credential.account_id, selected)
            if operation == "get_profile": return {"status": "success", "data": profile}
            if operation == "get_booking":
                booking, _ = await call("/v1/bookings/" + config.booking_id, params=[("fields", BOOKING_FIELDS)])
                return {"status": "success", "data": {**_booking(booking, credential.account_id, known, config.booking_id, selected), "public_representation": True, "booking_response_authentication_verified": None}}
            kind = "teamMembers" if operation in ("list_team_members", "get_team_member") else "appointmentTypes"
            items, active = _embedded(raw, kind, credential.account_id, selected)
            if operation in ("get_team_member", "get_appointment_type"):
                target = config.team_member_id if kind == "teamMembers" else config.appointment_type_id
                item = next((row for row in items if row["id"] == target), None)
                if item is None: raise YouCanBookMeDenied("The selected member or appointment type is absent from the current protected profile.")
                return {"status": "success", "data": {**item, "section_active": active}}
        filtered = [row for row in items if config.search.casefold() in (row.get("title") or row.get("name") or row["id"]).casefold()]
        snapshot = hashlib.sha256(json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cursor = _ticket(credential, authority, config, token=config.page_token) if config.page_token else {}
        offset = cursor.get("offset", 0)
        if cursor and (set(cursor) != {"offset", "snapshot"} or type(offset) is not int or not 0 < offset < len(filtered) or cursor["snapshot"] != snapshot): raise ValueError("YouCanBookMe bounded collection changed; restart native pagination.")
        page = filtered[offset:offset + config.per_page]
        token = _ticket(credential, authority, config, payload={"offset": offset + len(page), "snapshot": snapshot}) if offset + len(page) < len(filtered) else None
        return {"status": "success", "data": {"items": page, "next_page_token": token, "pagination_source": "native_bounded_collection", "snapshot_verified": True}}

    @classmethod
    async def load_field_options(cls, field_name, user_id=None, *, credential_data=None, credential_id=None, context=None, search=None, page_token=None, **kwargs):
        operations = {"profile_id": "list_profiles", "team_member_id": "list_team_members", "appointment_type_id": "list_appointment_types"}
        if field_name not in operations: return {"options": [], "next_page_token": None}
        context = context or {}; user_id = user_id or context.get("_user_id")
        saved = await cls.freshen_credential(credential_data)
        arguments = {"per_page": 100, "page_token": page_token, "search": _text(search, 128, empty=True) if search else ""}
        if field_name != "profile_id":
            if not context.get("profile_id"): return {"options": [], "next_page_token": None}
            arguments["profile_id"] = _id(context["profile_id"])
        from nodes.core.run_op import run_node_operation
        result = await run_node_operation(node_type="automation-youcanbookme", operation=operations[field_name], arguments=arguments, credential_data=saved, credential_id=credential_id, user_id=user_id, pool=kwargs.get("pool"), organization_id=kwargs.get("organization_id"), workflow_id=kwargs.get("workflow_id"))
        if result.get("executed") is False or result.get("status") in ("pending_approval", "rejected"): return result
        page = result["data"]
        return {"options": [{"value": row["id"], "label": row.get("title") or row.get("name") or row["id"], "metadata": {"account_id": _credential(saved).account_id, **({"profile_id": arguments["profile_id"]} if "profile_id" in arguments else {})}} for row in page["items"]], "next_page_token": page["next_page_token"]}
