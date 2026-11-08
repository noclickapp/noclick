"""ChurchTools native people, group, calendar and wiki metadata operations.

Contracts follow the current public demo OpenAPI; Login tokens remain bound to
one public HTTPS installation and an explicitly matched authenticated person.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import ipaddress
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_serializer, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

TYPE = "churchtools"
_CURRENT_ORG = object()
_AUTH_KEY = "_churchtools_authority"
_UNAVAILABLE = "ChurchTools credential is unavailable or access changed"
_INVALID = "ChurchTools returned an unexpected response; this outcome is unverified"
ID = Annotated[StrictStr, Field(min_length=1, max_length=10, pattern=r"^[1-9][0-9]{0,9}$")]
Guid = Annotated[StrictStr, Field(min_length=36, max_length=36, pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]
Name = Annotated[StrictStr, Field(min_length=1, max_length=100)]
Positive = Annotated[StrictInt, Field(ge=1, le=2147483647)]


def _origin(value):
    if not isinstance(value, str) or value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Enter an exact public HTTPS ChurchTools origin")
    origin = normalize_https_origin(value, field_name="ChurchTools installation")
    parsed = urlsplit(origin)
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("ChurchTools HTTPS port is invalid")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not host or "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host) or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")) or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
            raise ValueError("Use the public ChurchTools installation domain")
    else:
        raise ValueError("Use the public ChurchTools installation domain")
    return origin


class ChurchToolsCredential(BaseModel):
    model_config = ConfigDict(title="ChurchTools Login Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://churchtools.academy/en/help/system-settings/api-en/api-authentication/",
        "x-credential-instructions": "Supply your already-issued profile Login token and exact person ID for this public HTTPS ChurchTools installation. The node uses Authorization: Login, never password login, token retrieval, impersonation or OAuth minting.",
    })
    credential_type: Literal["churchtools"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    instance_url: StrictStr = Field(..., title="ChurchTools Installation", description="Exact public HTTPS origin, for example https://your-church.church.tools. Custom public tenant domains are accepted; no path, private host or TLS override.")
    login_token: Annotated[StrictStr, Field(min_length=1, max_length=4096)] = Field(..., title="Login Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expected_person_id: ID = Field(..., title="Your Person ID", description="Matched against whoami with only_allow_authenticated=true. This proves this user on this installation, not operation permissions.")

    @field_validator("instance_url")
    @classmethod
    def origin(cls, value):
        return _origin(value)

    @field_validator("expected_person_id")
    @classmethod
    def person_bound(cls, value):
        if int(value) > 2147483647:
            raise ValueError("ChurchTools person ID exceeds the native bound")
        return value

    @field_validator("login_token")
    @classmethod
    def token(cls, value):
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter the exact Login token without whitespace")
        return value

    @model_serializer(mode="wrap")
    def connect_type(self, handler):
        return {**handler(self), "credential_type": TYPE}


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("A ChurchTools Login-token credential is required")
    try:
        return ChurchToolsCredential.model_validate(raw)
    except Exception:
        raise ValueError("ChurchTools credential fields are invalid") from None


def _raw_guard(data):
    raw = data.get("credentials") if isinstance(data, dict) else None
    if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != TYPE:
        raise ValueError("A ChurchTools Login-token credential is required")


def op(name, title, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def picker(name, parent=None, searchable=False):
    options = {"field_name": name, "allow_custom": True, "searchable": searchable, "custom_placeholder": "Exact installation ID"}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def bounded_ids(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str) and value.isdecimal() and int(value) > 2147483647:
            raise ValueError("ChurchTools ID exceeds the native bound")
        return value


class CheckConnection(Config):
    operation: Literal["check_connection"] = op("check_connection", "Check Authenticated Person", "Account")


class GetMasterdata(Config):
    operation: Literal["get_masterdata"] = op("get_masterdata", "Get People and Group Reference Catalogs", "Reference")


class Page(Config):
    page: Annotated[StrictInt, Field(ge=1, le=10000)] = Field(1, title="Page")
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = Field(25, title="Page Size", description="One page only; native safety bound is narrower than the person API's 500 maximum.")
    query: Optional[Annotated[StrictStr, Field(min_length=2, max_length=200)]] = None


class ListPersons(Page):
    operation: Literal["list_persons"] = op("list_persons", "List People Metadata", "People")


class Person(Config):
    person_id: ID = Field(..., json_schema_extra=picker("person_id", searchable=True))


class GetPerson(Person):
    operation: Literal["get_person"] = op("get_person", "Get Person Metadata", "People")


class PersonFields(Config):
    first_name: Name
    last_name: Name
    nickname: Optional[Annotated[StrictStr, Field(max_length=100)]] = None


class CreatePerson(PersonFields):
    operation: Literal["create_person"] = op("create_person", "Create Person Metadata", "People")
    department_id: ID = Field(..., description="Exact department ID from this installation's reference catalogs. A person must have at least one department.")


class UpdatePerson(Person, PersonFields):
    operation: Literal["update_person"] = op("update_person", "Update Person Names", "People")


class DeletePerson(Person):
    operation: Literal["delete_person"] = op("delete_person", "Delete Person", "People")


class ListGroups(Page):
    operation: Literal["list_groups"] = op("list_groups", "List Group Metadata", "Groups")


class Group(Config):
    group_id: ID = Field(..., json_schema_extra=picker("group_id", searchable=True))


class GetGroup(Group):
    operation: Literal["get_group"] = op("get_group", "Get Group Metadata", "Groups")


class CreateGroup(Config):
    operation: Literal["create_group"] = op("create_group", "Create Hidden Pending Group", "Groups")
    name: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    group_type_id: ID = Field(..., description="Exact groupTypes ID from this installation's reference catalogs. Creates pending status 2 and hidden visibility; never sets an implicit membership role.")


class UpdateGroupType(Group):
    operation: Literal["update_group_type"] = op("update_group_type", "Update Group Type", "Groups")
    group_type_id: ID


class DeleteGroup(Group):
    operation: Literal["delete_group"] = op("delete_group", "Delete Group", "Groups")


class ListCalendars(Config):
    operation: Literal["list_calendars"] = op("list_calendars", "List Calendar Metadata", "Calendars")


class Calendar(Config):
    calendar_id: ID = Field(..., json_schema_extra=picker("calendar_id"))


class GetCalendar(Calendar):
    operation: Literal["get_calendar"] = op("get_calendar", "Get Calendar Metadata", "Calendars")


class CreateCalendar(Config):
    operation: Literal["create_calendar"] = op("create_calendar", "Create Personal Calendar", "Calendars")
    name: Annotated[StrictStr, Field(min_length=2, max_length=100)]
    sort_key: Annotated[StrictInt, Field(ge=0, le=1000000)] = 10


class UpdateCalendar(Calendar):
    operation: Literal["update_calendar"] = op("update_calendar", "Rename Local Calendar", "Calendars")
    name: Annotated[StrictStr, Field(min_length=2, max_length=100)]


class DeleteCalendar(Calendar):
    operation: Literal["delete_calendar"] = op("delete_calendar", "Delete Calendar", "Calendars")


class ListAppointments(Calendar):
    operation: Literal["list_appointments"] = op("list_appointments", "List Calendar Appointment Metadata", "Calendars")
    from_date: StrictStr = Field(..., description="Inclusive YYYY-MM-DD")
    to_date: StrictStr = Field(..., description="Inclusive YYYY-MM-DD, at most 30 days after From (31 calendar dates)")

    @model_validator(mode="after")
    def dates(self):
        try:
            if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in (self.from_date, self.to_date)) or not 0 <= (date.fromisoformat(self.to_date) - date.fromisoformat(self.from_date)).days <= 30:
                raise ValueError
        except ValueError:
            raise ValueError("Use a valid date range of 1 to 31 days") from None
        return self


class GetAppointment(Calendar):
    operation: Literal["get_appointment"] = op("get_appointment", "Get Calendar Appointment Metadata", "Calendars")
    appointment_id: ID = Field(..., description="Exact appointment ID from the selected calendar, obtained with a bounded List Appointments date range. No date range is guessed by a picker.")


class ListWikiCategories(Config):
    operation: Literal["list_wiki_categories"] = op("list_wiki_categories", "List Wiki Categories", "Wiki")


class CreateWikiCategory(Config):
    operation: Literal["create_wiki_category"] = op("create_wiki_category", "Create Wiki Category", "Wiki")
    name: Annotated[StrictStr, Field(min_length=1, max_length=50)]
    sort_key: Annotated[StrictInt, Field(ge=0, le=1000000)] = 10


class WikiCategory(Config):
    wiki_category_id: ID = Field(..., json_schema_extra=picker("wiki_category_id"))


class UpdateWikiCategory(WikiCategory, CreateWikiCategory):
    operation: Literal["update_wiki_category"] = op("update_wiki_category", "Rename Wiki Category", "Wiki")


class ListWikiPages(WikiCategory):
    operation: Literal["list_wiki_pages"] = op("list_wiki_pages", "List Wiki Page Metadata", "Wiki")


class WikiPage(WikiCategory):
    page_guid: Guid = Field(..., json_schema_extra=picker("page_guid", "wiki_category_id"))


class GetWikiPage(WikiPage):
    operation: Literal["get_wiki_page"] = op("get_wiki_page", "Get Wiki Page Metadata", "Wiki")


class CreateWikiPage(WikiCategory):
    operation: Literal["create_wiki_page"] = op("create_wiki_page", "Create Wiki Page", "Wiki")
    title: Annotated[StrictStr, Field(min_length=1, max_length=190)]
    text: Annotated[StrictStr, Field(max_length=32000)] = Field(..., json_schema_extra={"ui:widget": "textarea"})


class UpdateWikiPage(WikiPage):
    operation: Literal["update_wiki_page"] = op("update_wiki_page", "Update Wiki Page Text", "Wiki")
    text: Annotated[StrictStr, Field(max_length=32000)] = Field(..., description="Creates a new page version; unrelated page flags remain unchanged.", json_schema_extra={"ui:widget": "textarea"})


class DeleteWikiPage(WikiPage):
    operation: Literal["delete_wiki_page"] = op("delete_wiki_page", "Delete Wiki Page and Versions", "Wiki")


class ChurchToolsNodeConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: Optional[ChurchToolsCredential] = None
    config: Annotated[Union[CheckConnection, GetMasterdata, ListPersons, GetPerson, CreatePerson, UpdatePerson, DeletePerson, ListGroups, GetGroup, CreateGroup, UpdateGroupType, DeleteGroup, ListCalendars, GetCalendar, CreateCalendar, UpdateCalendar, DeleteCalendar, ListAppointments, GetAppointment, ListWikiCategories, CreateWikiCategory, UpdateWikiCategory, ListWikiPages, GetWikiPage, CreateWikiPage, UpdateWikiPage, DeleteWikiPage], Field(discriminator="operation")]

@dataclass
class _Authority:
    credential: Any = field(repr=False)
    pool: Any = field(default=None, repr=False)
    credential_id: Optional[str] = None
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    workflow_id: Optional[str] = None

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=_CURRENT_ORG, workflow_id=None):
        original = _credential(raw)
        if credential_id and not user_id:
            raise ValueError(_UNAVAILABLE)
        if not credential_id:
            return cls(original)
        if pool is None:
            from utils.database_pool import get_native_pool
            pool = get_native_pool()
        if organization_id is _CURRENT_ORG:
            from wss.handlers.workflow_handler import get_user_org_context
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
        current = cls(original, pool, credential_id, user_id, organization_id, workflow_id)
        current.credential = await current._load()
        return current

    async def _load(self):
        # Staging owns ACL, revocation and workflow-owner fallback policy.
        result = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.org_id, workflow_id=self.workflow_id,
        )
        if not result:
            raise ValueError(_UNAVAILABLE)
        try:
            return _credential(result)
        except ValueError:
            raise ValueError(_UNAVAILABLE) from None

    async def require_current(self):
        if self.credential_id and await self._load() != self.credential:
            raise ValueError(_UNAVAILABLE)


class ChurchToolsApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        super().__init__({401: "ChurchTools rejected the Login token", 403: "ChurchTools denied this operation; token validity is unverified", 404: "ChurchTools resource was not found", 409: "ChurchTools resource has a dependency conflict", 429: "ChurchTools rate limit reached; retry later"}.get(status, "ChurchTools request outcome is unverified"))


async def _request(authority, method, path, *, params=None, body=None, expected=200):
    await authority.require_current()
    if allow_private_hosts():
        raise ValueError("ChurchTools requires public-host enforcement")
    headers = {"Accept": "application/json", "User-Agent": "NoClick-ChurchTools/1.0", "Authorization": "Login " + authority.credential.login_token}
    try:
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, authority.credential.instance_url + "/api/" + path, params=params, json=body, headers=headers) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 1048576:
                        raise ValueError("ChurchTools response exceeded the native bound")
                    raw.extend(chunk)
                await authority.require_current()
                if response.status_code != expected:
                    raise ChurchToolsApiError(response.status_code)
                if expected == 204:
                    if raw:
                        raise ValueError(_INVALID)
                    return None
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError(_INVALID)
                def pairs(entries):
                    result = {}
                    for key, value in entries:
                        if key in result:
                            raise ValueError
                        result[key] = value
                    return result
                try:
                    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(value, dict) or "data" not in value:
                        raise ValueError
                    return value
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError(_INVALID) from None
    except httpx.RequestError:
        await authority.require_current()
        raise ValueError("ChurchTools transport outcome is unverified") from None


def _number(value, *, minimum=1):
    if type(value) is not int or not minimum <= value <= 2147483647:
        raise ValueError(_INVALID)
    return value


def _project(raw, fields):
    if not isinstance(raw, dict):
        raise ValueError(_INVALID)
    result = {}
    for key in fields:
        if key in raw:
            value = raw[key]
            if value is not None and (type(value) not in (str, int, bool) or (isinstance(value, str) and len(value) > 4096)):
                raise ValueError(_INVALID)
            result[key] = value
    return result


def _record(raw, kind, resource_id=None, parent_id=None):
    if not isinstance(raw, dict):
        raise ValueError(_INVALID)
    if kind == "appointment":
        if not isinstance(raw.get("appointment"), dict):
            raise ValueError(_INVALID)
        raw = raw["appointment"]
        if "base" in raw:
            # List responses contain calculated occurrences of a stored series;
            # detail responses contain the stored appointment directly.
            base, calculated = raw["base"], raw.get("calculated")
            if not isinstance(base, dict) or not isinstance(calculated, dict):
                raise ValueError(_INVALID)
            if any(not isinstance(calculated.get(key), str) or not calculated[key] for key in ("startDate", "endDate")):
                raise ValueError(_INVALID)
            raw = {**base, **_project(calculated, ("startDate", "endDate"))}
    if kind == "wiki_page":
        guid = raw.get("guid")
        if not isinstance(guid, str) or not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", guid) or (resource_id and guid.lower() != resource_id.lower()):
            raise ValueError(_INVALID)
        identity = {"guid": guid}
        parent = raw.get("wikiCategory")
    else:
        record_id = _number(raw.get("id"))
        if resource_id is not None and record_id != int(resource_id):
            raise ValueError("ChurchTools returned a different resource ID")
        identity = {"id": record_id}
        parent = raw.get("calendar") if kind == "appointment" else None
    if parent_id is not None:
        if not isinstance(parent, dict) or _number(parent.get("id")) != int(parent_id):
            raise ValueError("ChurchTools resource is outside the selected parent")
        identity["calendar_id" if kind == "appointment" else "wiki_category_id"] = parent["id"]
    fields = {
        "person": ("guid", "firstName", "lastName", "nickname", "visibility", "isArchived", "securityLevelForPerson", "editSecurityLevelForPerson"),
        "group": ("guid", "name", "securityLevelForGroup"),
        "calendar": ("name", "nameTranslated", "type", "color", "sortKey", "campusId"),
        "appointment": ("title", "subtitle", "startDate", "endDate", "allDay", "isInternal", "repeatId", "version"),
        "wiki_category": ("name", "nameTranslated", "sortKey", "inMenu", "fileAccessWithoutPermission", "campusId"),
        "wiki_page": ("title", "version", "isMarkdown", "onStartpage"),
    }[kind]
    result = {**identity, **_project(raw, fields)}
    for key in ("isArchived", "allDay", "isInternal", "isMarkdown", "onStartpage", "inMenu", "fileAccessWithoutPermission"):
        if key in result and type(result[key]) is not bool:
            raise ValueError(_INVALID)
    for key in ("version", "repeatId"):
        if key in result:
            _number(result[key], minimum=0)
    for key in ("sortKey", "securityLevelForPerson", "editSecurityLevelForPerson", "securityLevelForGroup"):
        if key in result and (type(result[key]) is not int or not -2147483647 <= result[key] <= 2147483647):
            raise ValueError(_INVALID)
    name_key = "title" if kind in {"wiki_page", "appointment"} else "name"
    if kind != "person" and (not isinstance(result.get(name_key), str) or not result[name_key]):
        raise ValueError(_INVALID)
    if kind == "person" and (not isinstance(raw.get("guid"), str) or not raw["guid"]):
        raise ValueError(_INVALID)
    if kind == "group":
        result["information"] = _project(raw.get("information"), ("groupTypeId", "groupStatusId", "groupCategoryId", "campusId", "maxMembers"))
    if kind in {"wiki_category", "wiki_page"} and "permissions" in raw:
        permissions = raw["permissions"]
        if not isinstance(permissions, dict) or any(key in permissions and type(permissions[key]) is not bool for key in ("canEdit", "canDelete")):
            raise ValueError(_INVALID)
        result["permissions"] = {key: permissions[key] for key in ("canEdit", "canDelete") if key in permissions}
    return result


def _collection(raw, kind, *, args=None, parent_id=None):
    rows = raw.get("data") if isinstance(raw, dict) else None
    bound = args.limit if args is not None else 200
    if not isinstance(rows, list) or len(rows) > bound:
        raise ValueError("ChurchTools collection exceeds the native bound or is malformed")
    projected = [_record(row, kind, parent_id=parent_id) for row in rows]
    key = "guid" if kind == "wiki_page" else "id"
    identities = {(row[key], row.get("startDate"), row.get("endDate")) if kind == "appointment" else row[key] for row in projected}
    if len(identities) != len(projected):
        raise ValueError(_INVALID)
    data = {"items": projected, "automatic_paging": False}
    if args is not None:
        meta = raw.get("meta")
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        if not isinstance(pagination, dict) or _number(pagination.get("current")) != args.page:
            raise ValueError(_INVALID)
        last = _number(pagination.get("lastPage"), minimum=0)
        if last < args.page and not (last == 0 and args.page == 1 and not rows):
            raise ValueError(_INVALID)
        data.update({"page": args.page, "limit": args.limit, "next_page": args.page + 1 if args.page < last and args.page < 10000 else None})
    return data


async def _identity(authority):
    raw = await _request(authority, "GET", "whoami", params={"only_allow_authenticated": "true"})
    data = _record(raw["data"], "person", resource_id=authority.credential.expected_person_id)
    return {"person_id": data["id"], "guid": data["guid"]}


async def _masterdata(authority):
    raw = (await _request(authority, "GET", "person/masterdata"))["data"]
    if not isinstance(raw, dict):
        raise ValueError(_INVALID)
    result = {}
    for key in ("departments", "statuses", "campuses", "groupTypes", "groupStatuses", "groupCategories"):
        rows = raw.get(key)
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError(_INVALID)
        result[key] = [{"id": _number(row.get("id"), minimum=0), **_project(row, ("name", "nameTranslated"))} for row in rows if isinstance(row, dict)]
        if len(result[key]) != len(rows) or len({v["id"] for v in result[key]}) != len(rows):
            raise ValueError(_INVALID)
    return result


class ChurchToolsNode(WorkflowNode):
    integration_type = "automation-churchtools"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", identity_keys=("person_id", "guid"), noun="ChurchTools person on the configured installation", proves="account")

    @classmethod
    def get_config_model(cls):
        return ChurchToolsNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _raw_guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        authority = await _Authority.create(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        return {**authority.credential.model_dump(), _AUTH_KEY: authority}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            authority = await _Authority.create(credential_data)
            await _identity(authority)
            return {"valid": True}
        except ChurchToolsApiError as exc:
            return {"valid": False if exc.status_code == 401 else None, "error": str(exc)}
        except Exception:
            return {"valid": None, "error": "ChurchTools access is unverified"}

    async def execute(self, input_data):
        _raw_guard(self.node_data)
        if self.config.credentials is None:
            raise ValueError("ChurchTools credentials are required")
        args = self.config.config
        action = args.operation
        authority = await _Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        identity = await _identity(authority)
        writes = action.startswith(("create_", "update_", "delete_"))
        async def exact(kind, path, resource_id, parent=None):
            raw = (await _request(authority, "GET", path))["data"]
            return raw, _record(raw, kind, resource_id=resource_id, parent_id=parent)
        async def category():
            raw = await _request(authority, "GET", "wiki/categories")
            _collection(raw, "wiki_category")
            matches = [row for row in raw["data"] if row["id"] == int(args.wiki_category_id)]
            if len(matches) != 1:
                raise ValueError("ChurchTools wiki category is not accessible")
            return matches[0]
        if action == "check_connection":
            data = identity
        elif action == "get_masterdata":
            data = await _masterdata(authority)
        elif action in {"list_persons", "list_groups"}:
            params = {"page": args.page, "limit": args.limit}
            if args.query is not None:
                params["query"] = args.query
            data = _collection(await _request(authority, "GET", "persons" if action == "list_persons" else "groups", params=params), "person" if action == "list_persons" else "group", args=args)
        elif action in {"list_calendars", "list_wiki_categories"}:
            kind, path = ("calendar", "calendars") if action == "list_calendars" else ("wiki_category", "wiki/categories")
            data = _collection(await _request(authority, "GET", path), kind)
        elif action in {"get_person", "update_person", "delete_person", "get_group", "update_group_type", "delete_group", "get_calendar", "update_calendar", "delete_calendar"}:
            kind = "person" if "person" in action else "group" if "group" in action else "calendar"
            resource_id = getattr(args, kind + "_id")
            path = {"person": "persons", "group": "groups", "calendar": "calendars"}[kind] + "/" + resource_id
            raw, data = await exact(kind, path, resource_id)
            if action.startswith("delete_"):
                await _request(authority, "DELETE", path, expected=204)
                data = {"resource_id": int(resource_id), "delete_acknowledged": True, "readback_verified": False, "readback_operation": "get_" + kind}
            elif action == "update_person":
                body = {"firstName": args.first_name, "lastName": args.last_name}
                if args.nickname is not None:
                    body["nickname"] = args.nickname
                data = _record((await _request(authority, "PATCH", path, body=body))["data"], kind, resource_id)
            elif action == "update_group_type":
                catalogs = await _masterdata(authority)
                if int(args.group_type_id) not in {row["id"] for row in catalogs["groupTypes"]}:
                    raise ValueError("Group type is outside this installation's reference catalog")
                data = _record((await _request(authority, "PATCH", path, body={"groupTypeId": int(args.group_type_id)}))["data"], kind, resource_id)
            elif action == "update_calendar":
                keys = ("sortKey", "color", "campusId", "eventTemplateId", "iCalSourceUrl", "evTermineEventTypeId", "syncToEvTermine")
                if any(key not in raw for key in keys) or raw["iCalSourceUrl"] not in (None, "") or raw["syncToEvTermine"] is not False:
                    raise ValueError("Only a complete local calendar with external synchronization disabled may be renamed")
                body = {key: raw[key] for key in keys}
                body["name"] = args.name
                if type(body["sortKey"]) is not int or not -2147483647 <= body["sortKey"] <= 2147483647:
                    raise ValueError(_INVALID)
                if body["color"] is not None and (not isinstance(body["color"], str) or len(body["color"]) > 20):
                    raise ValueError(_INVALID)
                for key in ("campusId", "eventTemplateId", "evTermineEventTypeId"):
                    if body[key] is not None:
                        _number(body[key], minimum=0)
                data = _record((await _request(authority, "PUT", path, body=body))["data"], kind, resource_id)
        elif action in {"create_person", "create_group", "create_calendar"}:
            if action == "create_person":
                catalogs = await _masterdata(authority)
                if int(args.department_id) not in {row["id"] for row in catalogs["departments"]}:
                    raise ValueError("Department is outside this installation's reference catalog")
                body = {"firstName": args.first_name, "lastName": args.last_name, "departmentIds": [int(args.department_id)], "visibility": "hidden"}
                if args.nickname is not None:
                    body["nickname"] = args.nickname
                kind, path, expected = "person", "persons", 200
            elif action == "create_group":
                catalogs = await _masterdata(authority)
                if int(args.group_type_id) not in {row["id"] for row in catalogs["groupTypes"]}:
                    raise ValueError("Group type is outside this installation's reference catalog")
                body = {"name": args.name, "groupTypeId": int(args.group_type_id), "groupStatusId": 2, "visibility": "hidden"}
                kind, path, expected = "group", "groups", 201
            else:
                body = {"name": args.name, "sortKey": args.sort_key, "type": "personal", "syncToEvTermine": False, "iCalSourceUrl": None}
                kind, path, expected = "calendar", "calendars", 201
            data = _record((await _request(authority, "POST", path, body=body, expected=expected))["data"], kind)
        elif action in {"list_appointments", "get_appointment"}:
            path = "calendars/" + args.calendar_id
            await exact("calendar", path, args.calendar_id)
            path += "/appointments"
            if action == "list_appointments":
                data = _collection(await _request(authority, "GET", path, params={"from": args.from_date, "to": args.to_date}), "appointment", parent_id=args.calendar_id)
            else:
                _, data = await exact("appointment", path + "/" + args.appointment_id, args.appointment_id, args.calendar_id)
        elif action in {"create_wiki_category", "update_wiki_category"}:
            body = {"name": args.name, "sortKey": args.sort_key, "inMenu": False, "fileAccessWithoutPermission": False}
            path, expected = "wiki/categories", 201
            if action == "update_wiki_category":
                old = await category()
                for key in ("inMenu", "fileAccessWithoutPermission", "campusId"):
                    if key not in old or (key != "campusId" and type(old[key]) is not bool):
                        raise ValueError(_INVALID)
                    body[key] = old[key]
                path += "/" + args.wiki_category_id
                expected = 200
            data = _record((await _request(authority, "POST" if expected == 201 else "PUT", path, body=body, expected=expected))["data"], "wiki_category", getattr(args, "wiki_category_id", None))
        elif action in {"list_wiki_pages", "get_wiki_page", "create_wiki_page", "update_wiki_page", "delete_wiki_page"}:
            await category()
            path = "wiki/categories/" + args.wiki_category_id + "/pages"
            if action == "list_wiki_pages":
                data = _collection(await _request(authority, "GET", path), "wiki_page", parent_id=args.wiki_category_id)
            elif action == "create_wiki_page":
                data = _record((await _request(authority, "POST", path, body={"title": args.title, "text": args.text, "isMarkdown": True, "onStartpage": False}, expected=201))["data"], "wiki_page", parent_id=args.wiki_category_id)
            else:
                path += "/" + args.page_guid
                _, data = await exact("wiki_page", path, args.page_guid, args.wiki_category_id)
                if action == "update_wiki_page":
                    if data.get("permissions", {}).get("canEdit") is not True:
                        raise ValueError("ChurchTools page edit permission is not established")
                    data = _record((await _request(authority, "PATCH", path, body={"text": args.text}))["data"], "wiki_page", args.page_guid, args.wiki_category_id)
                elif action == "delete_wiki_page":
                    if data.get("permissions", {}).get("canDelete") is not True:
                        raise ValueError("ChurchTools page delete permission is not established")
                    await _request(authority, "DELETE", path, expected=204)
                    data = {"guid": args.page_guid, "wiki_category_id": int(args.wiki_category_id), "delete_acknowledged": True, "readback_verified": False, "readback_operation": "get_wiki_page"}
        else:
            raise ValueError("Unsupported ChurchTools operation")
        if writes and not action.startswith("delete_"):
            data.update({"write_acknowledged": True, "readback_verified": False})
        await authority.require_current()
        return {"status": "success", "operation": action, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"person_id", "group_id", "calendar_id", "wiki_category_id", "page_guid", "appointment_id"} or (context is not None and not isinstance(context, dict)):
            raise ValueError("Unsupported ChurchTools picker context")
        if search is not None and (not isinstance(search, str) or len(search) > 200):
            raise ValueError("Invalid ChurchTools picker search")
        args = {}
        if field_name in {"person_id", "group_id"}:
            if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", page_token)):
                raise ValueError("Invalid ChurchTools picker page")
            args = {"operation": "list_persons" if field_name == "person_id" else "list_groups", "page": int(page_token) if page_token else 1, "limit": 25, "query": search or None}
        else:
            if search or page_token:
                raise ValueError("This ChurchTools collection has no documented search or pagination; use an exact custom ID")
            args["operation"] = {"calendar_id": "list_calendars", "wiki_category_id": "list_wiki_categories", "page_guid": "list_wiki_pages", "appointment_id": "list_appointments"}[field_name]
            if field_name == "page_guid":
                args["wiki_category_id"] = (context or {}).get("wiki_category_id")
            if field_name == "appointment_id":
                # A date-window is required by native bounds but is not declared
                # as an appointment-ID dependency. Do not scan/guess it here.
                raise ValueError("Use an exact appointment ID from a bounded List Appointments result")
        config = ChurchToolsNodeConfig.model_validate({"credentials": credential_data, "config": args})
        authority = credential_data.get(_AUTH_KEY)
        if authority is not None and (not isinstance(authority, _Authority) or authority.credential != config.credentials):
            raise ValueError(_UNAVAILABLE)
        if authority is not None:
            await authority.require_current()
        node = cls(node_id="churchtools-picker", node_type="automation-churchtools", node_data={"config": args, "credentials": config.credentials.model_dump()}, config=config, sio=None, sid=None)
        if authority is not None:
            node.node_data.update({"credential_id": authority.credential_id, "_approval_pool": authority.pool})
            node.user_id, node.workflow_id, node.organization_id = authority.user_id, authority.workflow_id, authority.org_id
        result = await node.execute({})
        if authority is not None:
            await authority.require_current()
        return {"options": [{"value": row.get("guid") if field_name == "page_guid" else str(row["id"]), "label": row.get("name") or row.get("title") or " ".join(filter(None, (row.get("firstName"), row.get("lastName")))) or str(row.get("id"))} for row in result["data"]["items"]], "next_page_token": str(result["data"]["next_page"]) if result["data"].get("next_page") else None}
