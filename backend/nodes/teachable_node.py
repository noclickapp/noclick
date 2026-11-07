"""Teachable v2 Admin metadata/management and separately supplied user OAuth.

The documented OAuth refresh endpoint and resource requests are closed v2
paths. No billing, subscriptions, lesson content, streaming URLs or sessions.
"""
from __future__ import annotations
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.teachable import TEACHABLE_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN = "https://developers.teachable.com"
TOKEN_PATH = "/v2/current_user/oauth2/token"
TYPES = ("teachable_api_key", "teachable_supplied_oauth")
ID = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,19}$")]
MAX_BODY = 8 * 1024 * 1024
_PRIVATE = contextvars.ContextVar("teachable_private", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record): return not _PRIVATE.get()


for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks_proxy"):
    logging.getLogger(_name).addFilter(_PrivateFilter())


def _text(value, maximum=256):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Supply bounded Teachable text without control characters.")
    return value


def _id(value):
    if type(value) is int: value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value): raise ValueError("Supply an actual positive Teachable resource ID.")
    return value


def _instant(value):
    try:
        parsed = datetime.fromisoformat(_text(value, 64).replace("Z", "+00:00"))
        if parsed.tzinfo is None: raise ValueError()
        return parsed
    except Exception: raise ValueError("Supply a timezone-qualified Teachable timestamp.") from None


class _Credential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.teachable.com/v2.0/docs/oauth-quickstart-guide"})
    expected_course_id: Optional[ID] = Field(None, description="Optional actual course anchor. A protected course read must match; this is not a school identity claim.")
    allow_management_writes: bool = Field(False, strict=True, description="Off by default. Allows student creation, name update and enrollment/removal. These change real school records and access; notification suppression and billing effects are not promised.")
    @field_validator("expected_course_id", "expected_user_id", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value): return None if value in (None, "") else _id(value)
    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def secret(cls, value, info):
        if info.field_name in ("api_key", "access_token", "refresh_token", "client_id", "client_secret") and value is not None:
            if not isinstance(value, str) or not 1 <= len(value) <= 32768 or any(ord(c) < 33 or ord(c) > 126 for c in value): raise ValueError("Supply existing Teachable credential material without whitespace.")
        return value


class TeachableAPIKeyCredential(_Credential):
    model_config = ConfigDict(title="Teachable Admin API Key")
    credential_type: Literal["teachable_api_key"] = Field(TYPES[0], json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, title="Admin API Key", json_schema_extra={"ui:widget": "password"}, description="Existing school Settings → API key. Sent as apiKey; not an end-user OAuth bearer. Current v2 is beta and Support access is a human prerequisite, not verified by setup.")


class TeachableSuppliedOAuthCredential(_Credential):
    model_config = ConfigDict(title="Teachable Supplied User OAuth v2")
    credential_type: Literal["teachable_supplied_oauth"] = Field(TYPES[1], json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing v2 User OAuth Access Token", json_schema_extra={"ui:widget": "password"})
    api_version: Literal["v2"] = Field("v2", json_schema_extra={"ui:hidden": True}, description="Existing grant from a newly registered v2 OAuth app. Legacy v1 credentials are incompatible; v2 beta access requires Teachable Support.")
    expected_user_id: ID = Field(..., description="Actual Teachable user ID. Current-user me must match before resource requests; do not use an Admin API key here.")
    expires_at: Optional[str] = Field(None, description="Actual token expiry when known; no lifetime is invented for supplied tokens.")
    refresh_token: Optional[str] = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    client_id: Optional[str] = Field(None, repr=False, description="Actual existing v2 school-registered OAuth app, only needed with its refresh token.")
    client_secret: Optional[str] = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    @field_validator("expires_at", mode="before")
    @classmethod
    def expiry(cls, value):
        if value is not None: _instant(value)
        return value
    @model_validator(mode="after")
    def refresh_context(self):
        if any((self.refresh_token, self.client_id, self.client_secret)) and not all((self.refresh_token, self.client_id, self.client_secret)): raise ValueError("Supply the complete actual refresh-token and OAuth client context, or omit it.")
        return self


TeachableCredential = Union[TeachableAPIKeyCredential, TeachableSuppliedOAuthCredential]


def _credential(value):
    if isinstance(value, (TeachableAPIKeyCredential, TeachableSuppliedOAuthCredential)): return value
    if not isinstance(value, dict) or value.get("credential_type") not in TYPES: raise ValueError("Attach a native Teachable Admin key or supplied user OAuth grant.")
    try: return TypeAdapter(TeachableCredential).validate_python({k: v for k, v in value.items() if k not in ("token_version", "updated_at")})
    except Exception: raise ValueError("Check the native Teachable credential, actual user/course anchor and write policy.") from None


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    @field_validator("course_id", "user_id", "lecture_id", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value): return _id(value)


def _op(value, label, category="Metadata"):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _resource(kind, parent=None):
    options = {"field_name": kind + "_id", "searchable": True, "allow_custom": True}
    if parent: options["depends_on"] = parent
    return {"x-resource-type": "teachable_" + kind, "x-dynamic-options": options}


class _Page(_Config):
    limit: int = Field(50, strict=True, ge=1, le=100)
    page_token: Optional[str] = Field(None, max_length=8192, description="Native continuation bound to current grant, operation and parent IDs.")


class _Course(_Config):
    course_id: ID = Field(..., json_schema_extra=_resource("course"))


class _CoursePage(_Course, _Page): pass


class _User(_Config):
    user_id: ID = Field(..., json_schema_extra=_resource("user"))


class _CourseUser(_Course, _User): pass


class TeachableTestConfig(_Config):
    operation: Literal["test_connection"] = _op("test_connection", "Test Connection")
class TeachableCoursesConfig(_Page):
    operation: Literal["list_courses"] = _op("list_courses", "List School Courses")
class TeachableCourseConfig(_Course):
    operation: Literal["get_course"] = _op("get_course", "Get School Course")
class TeachableSectionsConfig(_CoursePage):
    operation: Literal["list_course_sections"] = _op("list_course_sections", "List Course Sections")
class TeachableLecturesConfig(_CoursePage):
    operation: Literal["list_course_lectures"] = _op("list_course_lectures", "List Lecture Metadata")
class TeachableEnrollmentsConfig(_CoursePage):
    operation: Literal["list_course_enrollments"] = _op("list_course_enrollments", "List Course Enrollments")
class TeachableUserEnrollmentsConfig(_CourseUser, _Page):
    operation: Literal["get_user_enrollments"] = _op("get_user_enrollments", "Get User Enrollments")
class TeachableProgressConfig(_CourseUser):
    operation: Literal["get_course_progress"] = _op("get_course_progress", "Get User Course Progress")
class TeachableLectureCompletionConfig(_CourseUser):
    operation: Literal["get_lecture_completion"] = _op("get_lecture_completion", "Get User Lecture Completion")
    lecture_id: ID = Field(..., json_schema_extra=_resource("lecture", "course_id"))
class TeachableUsersConfig(_Page):
    operation: Literal["list_users"] = _op("list_users", "List User Metadata")
class TeachableUserConfig(_User):
    operation: Literal["get_user"] = _op("get_user", "Get User Metadata")
class TeachableCreateStudentConfig(_Config):
    operation: Literal["create_student"] = _op("create_student", "Create Student", "Management")
    name: str = Field(..., min_length=1, max_length=256)
    email: str = Field(..., min_length=3, max_length=254, description="Actual student address sent only to Teachable; excluded from workflow outputs. Marketing emails are disabled in this request.")
    @field_validator("name", "email")
    @classmethod
    def text(cls, value, info):
        value = _text(value, 254 if info.field_name == "email" else 256)
        if info.field_name == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value): raise ValueError("Supply a valid student email address.")
        return value
class TeachableUpdateNameConfig(_User):
    operation: Literal["update_user_name"] = _op("update_user_name", "Update User Name", "Management")
    name: str = Field(..., min_length=1, max_length=256)
    @field_validator("name")
    @classmethod
    def text(cls, value): return _text(value)
class TeachableEnrollConfig(_CourseUser):
    operation: Literal["enroll_user"] = _op("enroll_user", "Enroll User", "Management")
class TeachableUnenrollConfig(_CourseUser):
    operation: Literal["unenroll_user"] = _op("unenroll_user", "Remove Course Enrollment", "Management")
class TeachableMeConfig(_Config):
    operation: Literal["get_current_user"] = _op("get_current_user", "Get OAuth User")
class TeachableMyCoursesConfig(_Page):
    operation: Literal["list_my_courses"] = _op("list_my_courses", "List My Courses")
class TeachableMyCourseConfig(_Course):
    operation: Literal["get_my_course"] = _op("get_my_course", "Get My Course")
class TeachableMyProgressConfig(_CoursePage):
    operation: Literal["get_my_progress"] = _op("get_my_progress", "Get My Course Progress")
class TeachableMyCompletionConfig(_Course):
    operation: Literal["get_my_course_completion"] = _op("get_my_course_completion", "Get My Course Completion")


TeachableOperation = Annotated[Union[TeachableTestConfig, TeachableCoursesConfig, TeachableCourseConfig, TeachableSectionsConfig, TeachableLecturesConfig, TeachableEnrollmentsConfig, TeachableUserEnrollmentsConfig, TeachableProgressConfig, TeachableLectureCompletionConfig, TeachableUsersConfig, TeachableUserConfig, TeachableCreateStudentConfig, TeachableUpdateNameConfig, TeachableEnrollConfig, TeachableUnenrollConfig, TeachableMeConfig, TeachableMyCoursesConfig, TeachableMyCourseConfig, TeachableMyProgressConfig, TeachableMyCompletionConfig], Discriminator("operation")]


class TeachableNodeConfig(NodeConfig):
    credentials: Optional[TeachableCredential] = None
    config: TeachableOperation = Field(default_factory=TeachableTestConfig)


class TeachableDenied(ValueError): pass
class TeachableUnavailable(ValueError): pass
class _Rejected(TeachableUnavailable): pass
class _Missing(_Rejected): pass
class _Unknown(TeachableUnavailable): pass


def _data(raw):
    if not isinstance(raw, dict) or "data" not in raw: raise _Unknown("Teachable omitted the documented data envelope.")
    return raw["data"]


def _record(row, kind, expected=None):
    if not isinstance(row, dict): raise _Unknown("Teachable returned invalid resource metadata.")
    rid = _id(row.get("id"))
    if expected is not None and rid != _id(expected): raise TeachableDenied("Teachable resource differs from the selected parent or user.")
    result = {"id": rid, "name": _text(row.get("name"))}
    for key in ("created_at", "updated_at"):
        if key in row: _instant(row[key]); result[key] = row[key]
    if kind == "user": result["role"] = _text(row.get("role"), 64)
    if kind == "course":
        if type(row.get("is_published")) is not bool: raise _Unknown("Teachable omitted course publication metadata.")
        result["is_published"] = row["is_published"]
        if "is_listed" in row:
            if type(row["is_listed"]) is not bool: raise _Unknown("Teachable returned invalid listing metadata.")
            result["is_listed"] = row["is_listed"]
    if kind in ("section", "lecture"):
        if type(row.get("position")) is not int or row["position"] < 0: raise _Unknown("Teachable returned invalid position metadata.")
        result["position"] = row["position"]
    if kind == "lecture":
        for key in ("is_published", "free_preview"):
            if type(row.get(key)) is not bool: raise _Unknown("Teachable omitted lecture flags.")
            result[key] = row[key]
        if "section" in row:
            if not isinstance(row["section"], dict): raise _Unknown("Teachable returned invalid lecture section metadata.")
            result["section_id"] = _id(row["section"].get("id"))
    return result


def _percent(value):
    if type(value) is not int or not 0 <= value <= 100: raise _Unknown("Teachable returned invalid percent-complete metadata.")
    return value


def _times(row, result, keys):
    for key in keys:
        if key not in row: continue
        if row[key] is not None: _instant(row[key])
        result[key] = row[key]
    return result


def _enrollment(row, expected_user=None):
    if not isinstance(row, dict) or not isinstance(row.get("user"), dict) or row.get("status") not in ("active", "completed", "expired", "disabled"): raise _Unknown("Teachable returned invalid enrollment metadata.")
    if any(key not in row for key in ("enrolled_at", "created_at", "updated_at")): raise _Unknown("Teachable omitted documented enrollment timestamps.")
    user = _id(row["user"].get("id"))
    if expected_user and user != expected_user: raise TeachableDenied("Enrollment belongs to a different selected user.")
    sale = row.get("sale")
    if sale is not None and not isinstance(sale, dict): raise _Unknown("Teachable returned invalid sale-reference metadata.")
    out = {"user_id": user, "sale_id": _id(sale.get("id")) if sale is not None else None, "status": row["status"]}
    _times(row, out, ("enrolled_at", "created_at", "updated_at", "expires_at"))
    if "progress" in row:
        if not isinstance(row["progress"], dict): raise _Unknown("Teachable returned invalid enrollment progress.")
        out["progress"] = _times(row["progress"], {"percent_complete": _percent(row["progress"].get("percent_complete"))}, ("completed_at",))
    return out


def _completion(row, course=False):
    if not isinstance(row, dict) or type(row.get("completed")) is not bool or "completed_at" not in row: raise _Unknown("Teachable omitted actual completion metadata.")
    out = _times(row, {"completed": row["completed"]}, ("completed_at",))
    if course: out["percent_complete"] = _percent(row.get("percent_complete"))
    return out


def _progress(row, course, maximum):
    if not isinstance(row, dict) or not isinstance(row.get("sections"), list) or len(row["sections"]) > maximum: raise _Unknown("Teachable progress exceeded the bounded section window.")
    # The schema calls this field id without promising it equals course_id.
    # The protected course/read route binds the parent; retain its actual ID.
    out = _times(row, {"course_id": course, "progress_id": _id(row.get("id")), "percent_complete": _percent(row.get("percent_complete")), "sections": []}, ("enrolled_at", "completed_at"))
    count = 0
    for section in row["sections"]:
        if not isinstance(section, dict): raise _Unknown("Teachable returned invalid progress section metadata.")
        item = {"id": _id(section.get("id")), "name": _text(section.get("name")), "percent_complete": _percent(section.get("percent_complete"))}
        if "lectures" in section:
            if not isinstance(section["lectures"], list): raise _Unknown("Teachable returned invalid progress lecture metadata.")
            count += len(section["lectures"])
            if count > 5000: raise _Unknown("Teachable lecture progress exceeds the native bound.")
            item["lectures"] = []
            for lecture in section["lectures"]:
                if not isinstance(lecture, dict) or type(lecture.get("is_completed")) is not bool: raise _Unknown("Teachable omitted actual lecture completion.")
                item["lectures"].append(_times(lecture, {"id": _id(lecture.get("id")), "name": _text(lecture.get("name")), "is_completed": lecture["is_completed"]}, ("completed_at",)))
        out["sections"].append(item)
    return out


def _paging(raw, page, limit, count):
    meta = raw.get("meta") if isinstance(raw, dict) else None
    if not isinstance(meta, dict) or any(type(meta.get(k)) is not int for k in ("page", "per_page", "total_count", "total_pages")): raise _Unknown("Teachable omitted documented v2 pagination metadata.")
    if meta["page"] != page or meta["per_page"] != limit or not 0 <= count <= limit or not 0 <= meta["total_count"] <= 100000000 or not 0 <= meta["total_pages"] <= 10000000 or (meta["total_pages"] and page > meta["total_pages"]) or (meta["total_pages"] == 0 and (count or meta["total_count"])): raise _Unknown("Teachable pagination changed the requested bounded window.")
    return meta["total_pages"] > page


def _cursor(credential, operation, path, limit, *, token=None, next_page=None):
    scope = hashlib.sha256(json.dumps([credential.model_dump(), operation, path, limit], sort_keys=True).encode()).hexdigest()
    secret = (getattr(credential, "api_key", None) or credential.access_token).encode()
    try:
        if token:
            encoded, mac = token.split("."); raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            if not hmac.compare_digest(mac, hmac.new(secret, raw, hashlib.sha256).hexdigest()): raise ValueError()
            data = json.loads(raw)
            if set(data) != {"scope", "page"} or data["scope"] != scope or type(data["page"]) is not int or not 1 <= data["page"] <= 10000: raise ValueError()
            return data["page"]
        if next_page > 10000: raise ValueError()
        raw = json.dumps({"scope": scope, "page": next_page}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    except Exception: raise ValueError("Teachable continuation differs from the current grant, policy, operation or selected parent.") from None


class _RefreshToken(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: str


class TeachableNode(WorkflowNode):
    integration_type = "automation-teachable"
    credential_provider_labels = {"teachable": "Teachable API"}
    scope_registry = TEACHABLE_SCOPES
    connection_evidence = ConnectionEvidence(noun="Teachable API", operation="test_connection", proves="reachability", label_keys=(), identity_keys=())
    edit_examples = ["List school courses", "Read student course progress", "Read my courses with a supplied OAuth grant", "Explicitly enable student enrollment management"]
    @classmethod
    def get_config_model(cls): return TeachableNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        credential = _credential(data["credentials"]) if isinstance(data, dict) and data.get("credentials") is not None else None
        try:
            view = runtime_config_view(data, TeachableNodeConfig)
            if credential is not None: view["credentials"] = credential.model_dump()
            if isinstance(view.get("config"), dict):
                view["config"] = {k: v for k, v in view["config"].items() if not k.endswith("__label") and k not in ("_settings", "agent_tool_operations")}
                if not view["config"]: view.pop("config")
            return TypeAdapter(TeachableNodeConfig).validate_python(view)
        except Exception: raise ValueError("Check the native Teachable operation and typed resource/management fields.") from None
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        data = credential_data
        credential = _credential(data)
        loaded = {**data, **credential.model_dump()}
        if not isinstance(credential, TeachableSuppliedOAuthCredential):
            return loaded
        if not credential.expires_at or _instant(credential.expires_at) > datetime.now(timezone.utc):
            return loaded
        if not credential.refresh_token or not credential_id or not user_id:
            raise TeachableDenied("The supplied Teachable OAuth grant expired; supply a fresh grant or complete saved refresh context.")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        async def refresh(refresh_token, client_id=None, client_secret=None):
            raw = await cls._transport("POST", TOKEN_PATH, body={"grant_type": "refresh_token", "client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token}, expected=200)
            if not isinstance(raw, dict) or not isinstance(raw.get("token_type"), str) or raw["token_type"].lower() != "bearer":
                raise _Unknown("Teachable refresh did not return a verified bearer grant.")
            seconds = raw.get("expires_in")
            if isinstance(seconds, str) and seconds.isascii() and seconds.isdecimal(): seconds = int(seconds)
            if type(seconds) is not int or not 1 <= seconds <= 86400:
                raise _Unknown("Teachable refresh omitted actual bounded expiry metadata.")
            fresh = _credential({**credential.model_dump(), "access_token": raw.get("access_token"), "refresh_token": raw.get("refresh_token"), "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()})
            return _RefreshToken(access_token=fresh.access_token, refresh_token=fresh.refresh_token, expires_at=fresh.expires_at)
        await ensure_fresh_oauth_token(pool=pool, credential_id=credential_id, user_id=user_id, credential=loaded, refresh=refresh, provider="teachable", caller_path="native", is_expired=lambda value: _instant(value) <= datetime.now(timezone.utc))
        _credential(loaded)
        return loaded
    @classmethod
    async def validate_credential_access(cls, credential_data):
        from nodes.core.run_op import run_node_operation
        credential = _credential(credential_data)
        # Staging's validation hook has no row ID to persist a rotated grant.
        # Leave refresh to a saved-credential execution or lookup.
        if isinstance(credential, TeachableSuppliedOAuthCredential) and credential.expires_at and _instant(credential.expires_at) <= datetime.now(timezone.utc):
            return {"valid": None, "reason": "The supplied token expired. Refresh the saved connection through a workflow or supply a fresh grant."}
        try:
            await run_node_operation(node_type="automation-teachable", operation="test_connection", arguments={}, user_id=None, credential_data=credential_data)
        except TeachableDenied:
            return {"valid": False, "reason": "Teachable refused the credential or selected user/course access."}
        except TeachableUnavailable:
            return {"valid": None, "reason": "Teachable access could not be verified. Try again later."}
        return {"valid": True}
    @classmethod
    async def _transport(cls, method, path, *, credential=None, body=None, params=None, expected=200):
        admin = bool(re.fullmatch(r"/v2/(?:users(?:/[1-9][0-9]{0,19})?|products/courses(?:/[1-9][0-9]{0,19}(?:/(?:sections|lectures(?:/[1-9][0-9]{0,19}(?:/users/[1-9][0-9]{0,19}/completion)?)?|enrollments(?:/[1-9][0-9]{0,19})?|users/[1-9][0-9]{0,19}/progress))?)?)", path))
        oauth = bool(re.fullmatch(r"/v2/current_user/(?:me|products/courses(?:/[1-9][0-9]{0,19}(?:/(?:progress|completion))?)?)", path))
        mint = path == TOKEN_PATH and method == "POST" and credential is None
        if not mint and (not (admin or oauth) or credential is None or (admin and credential.credential_type != TYPES[0]) or (oauth and credential.credential_type != TYPES[1])): raise TeachableDenied("This Teachable path requires its native Admin key or user OAuth family.")
        if not mint and method != "GET" and not ((path == "/v2/users" and method == "POST") or (re.fullmatch(r"/v2/users/[1-9][0-9]{0,19}", path) and method == "PATCH") or (re.fullmatch(r"/v2/products/courses/[1-9][0-9]{0,19}/enrollments/[1-9][0-9]{0,19}", path) and method in ("PUT", "DELETE"))): raise ValueError("Unsupported native Teachable method.")
        assert_exact_url_origin(ORIGIN + path, ORIGIN)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential is not None: headers["apiKey" if admin else "Authorization"] = credential.api_key if admin else "Bearer " + credential.access_token
        private = _PRIVATE.set(True)
        try:
            async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25) as client:
                async with client.stream(method, ORIGIN + path, headers=headers, json=body, params=params) as response:
                    status = response.status_code
                    if status in (401, 403) or (mint and status == 400): raise TeachableDenied("Teachable authentication, OAuth scope or user permission was refused.")
                    if status == 402: raise _Rejected("Teachable API access is gated by the school plan; an authorized human must resolve access. No purchase or upgrade was performed.")
                    if status == 404: raise _Missing("Teachable did not find this selected resource.")
                    if status in (400, 405, 409, 415, 422, 429): raise _Rejected("Teachable rejected the request or rate limit; provider error contents withheld, no automatic retry.")
                    if status != expected: raise _Unknown("Teachable completion status was not verified; no automatic retry.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_BODY: raise _Unknown("Teachable response exceeded the native byte bound.")
                        content.extend(chunk)
                    if expected == 204:
                        if content: raise _Unknown("Teachable204 contained unexpected response bytes.")
                        return None
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise _Unknown("Teachable did not return the documented JSON response.")
                    return json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (TeachableDenied, TeachableUnavailable): raise
        except Exception: raise _Unknown("Teachable request or response could not be verified; no automatic retry.") from None
        finally: _PRIVATE.reset(private)

    async def execute(self, inputs):
        config, supplied = self.config.config, _credential(self.config.credentials)
        saved = await self.freshen_credential(supplied.model_dump(), credential_id=self.node_data.get("credential_id"), user_id=self.user_id, pool=self.node_data.get("_approval_pool"))
        credential = _credential(saved)
        operation = config.operation
        requirement = self.scope_registry.require(operation)
        if not requirement.satisfied_by(credential.credential_type): raise TeachableDenied("Use the documented Teachable credential family for this operation.")
        writing = operation in ("create_student", "update_user_name", "enroll_user", "unenroll_user")
        if writing and not credential.allow_management_writes: raise TeachableDenied("Management writes are disabled on this current Teachable credential.")
        calls = 0; write_started = False
        secrets = [v for k, v in credential.model_dump().items() if k in ("api_key", "access_token", "refresh_token", "client_id", "client_secret") and v]
        async def call(method, path, *, body=None, params=None, expected=200):
            nonlocal calls, write_started
            if calls >= 32: raise _Unknown("Teachable local request budget exceeded.")
            if any(secret in json.dumps([body, params], allow_nan=False) for secret in secrets): raise ValueError("Keep credential material out of Teachable resource fields.")
            calls += 1
            if method != "GET": write_started = True
            return await self._transport(method, path, credential=credential, body=body, params=params, expected=expected)
        def result(data):
            if any(secret in json.dumps(data, allow_nan=False) for secret in secrets): raise _Unknown("Teachable metadata echoed credential material; output withheld.")
            return {"action": operation, "data": data, **({"status": "unknown"} if data.get("outcome") == "unknown" else {})}
        oauth = isinstance(credential, TeachableSuppliedOAuthCredential)
        prefix = "/v2/current_user/products/courses" if oauth else "/v2/products/courses"
        me = None
        if oauth:
            me = _record(_data(await call("GET", "/v2/current_user/me")), "user", credential.expected_user_id)
        if credential.expected_course_id:
            _record(_data(await call("GET", prefix + "/" + credential.expected_course_id)), "course", credential.expected_course_id)
        if operation == "test_connection":
            if not oauth:
                raw = await call("GET", prefix, params={"page": 1, "per_page": 1})
                rows = _data(raw)
                if not isinstance(rows, list): raise _Unknown("Teachable omitted the protected course list.")
                _paging(raw, 1, 1, len(rows))
                for row in rows: _record(row, "course")
            return result({"reachable": True, "authentication_verified": True, "account_identity_verified": False, "grant_scope_verified": None, "subject_verified": True if oauth else None, "subject_id": me["id"] if oauth else None, "school_identity_verified": False})
        if operation == "get_current_user": return result(me)
        course = getattr(config, "course_id", None)
        if course:
            if credential.expected_course_id and course != credential.expected_course_id: raise TeachableDenied("Selected course differs from the saved Teachable anchor.")
            course_row = _record(_data(await call("GET", prefix + "/" + course)), "course", course)
            if operation in ("get_course", "get_my_course"): return result(course_row)
        user = getattr(config, "user_id", None)
        if user:
            user_row = _record(_data(await call("GET", "/v2/users/" + user)), "user", user)
            if operation == "get_user": return result(user_row)
        path, kind = None, None
        if operation in ("list_courses", "list_my_courses"): path, kind = prefix, "course"
        elif operation == "list_users": path, kind = "/v2/users", "user"
        elif operation == "list_course_sections": path, kind = prefix + "/" + course + "/sections", "section"
        elif operation == "list_course_lectures": path, kind = prefix + "/" + course + "/lectures", "lecture"
        elif operation in ("list_course_enrollments", "get_user_enrollments"): path, kind = prefix + "/" + course + "/enrollments" + ("/" + user if user else ""), "enrollment"
        elif operation == "get_my_progress": path = prefix + "/" + course + "/progress"
        if path:
            page = _cursor(credential, operation, path, config.limit, token=config.page_token) if config.page_token else 1
            params = {"page": page, "per_page": config.limit}
            if kind in ("section", "lecture"): params.update(sort_by="position", sort_direction="asc")
            raw = await call("GET", path, params=params)
            rows = _data(raw)
            if operation == "get_my_progress":
                output = _progress(rows, course, config.limit); count = len(output["sections"])
            else:
                if not isinstance(rows, list) or len(rows) > config.limit: raise _Unknown("Teachable list exceeded its requested bound.")
                items = [_enrollment(row, user) if kind == "enrollment" else _record(row, kind) for row in rows]
                if kind != "enrollment" and len({row["id"] for row in items}) != len(items): raise _Unknown("Teachable duplicated resource IDs in a page.")
                output = {"items": items}; count = len(items)
            following = _paging(raw, page, config.limit, count)
            output.update(has_more=following, next_page_token=_cursor(credential, operation, path, config.limit, next_page=page + 1) if following else None)
            if course: output["course_id"] = course
            if user: output["user_id"] = user
            return result(output)
        if operation == "get_course_progress": return result(_progress(_data(await call("GET", prefix + "/" + course + "/users/" + user + "/progress")), course, 500))
        if operation == "get_my_course_completion": return result({"course_id": course, **_completion(_data(await call("GET", prefix + "/" + course + "/completion")), True)})
        if operation == "get_lecture_completion":
            lecture = config.lecture_id
            _record(_data(await call("GET", prefix + "/" + course + "/lectures/" + lecture)), "lecture", lecture)
            return result({"course_id": course, "user_id": user, "lecture_id": lecture, **_completion(_data(await call("GET", prefix + "/" + course + "/lectures/" + lecture + "/users/" + user + "/completion")))})
        receipt_id, acknowledged = None, False
        try:
            if operation in ("create_student", "update_user_name"):
                path = "/v2/users" + ("/" + user if user else "")
                body = {"name": config.name}
                if operation == "create_student": body.update(email=config.email, role="student", allow_marketing_emails=False)
                raw = await call("POST" if not user else "PATCH", path, body=body, expected=201 if not user else 200)
                acknowledged = True
                row = _record(_data(raw), "user", user); receipt_id = row["id"]
                read = _data(await call("GET", "/v2/users/" + receipt_id))
                output = _record(read, "user", receipt_id)
                if output["name"] != config.name or (not user and (output["role"] != "student" or read.get("email") != config.email)): raise _Unknown("Teachable student/name change was not read back.")
            else:
                path = prefix + "/" + course + "/enrollments/" + user
                removal = operation == "unenroll_user"
                raw = await call("DELETE" if removal else "PUT", path, expected=204 if removal else 200)
                acknowledged = True
                receipt = None if removal else _enrollment(_data(raw), user)
                receipt_id = receipt["sale_id"] if receipt else None
                items, page = [], 1
                while True:
                    try: read = await call("GET", path, params={"page": page, "per_page": 100})
                    except _Missing:
                        if removal: break
                        raise
                    rows = _data(read)
                    if not isinstance(rows, list) or len(rows) > 100: raise _Unknown("Teachable enrollment readback exceeded its bound.")
                    items.extend(_enrollment(row, user) for row in rows)
                    following = _paging(read, page, 100, len(rows))
                    if not following: break
                    page += 1
                    if page > 10: raise _Unknown("Teachable enrollment readback exceeded its page budget.")
                if removal:
                    if any(row["status"] in ("active", "completed") for row in items): raise _Unknown("Teachable active enrollment removal was not read back.")
                elif receipt["status"] not in ("active", "completed") or not any(row["status"] in ("active", "completed") and row["sale_id"] == receipt_id for row in items): raise _Unknown("Teachable enrollment receipt was not read back.")
                output = {"course_id": course, "user_id": user, "items": items, "active_enrollment_absent": True if removal else False}
            return result({**output, "receipt_id": receipt_id, "readback_verified": True, "billing_effect_verified": None, "notification_delivery_verified": None})
        except (TeachableDenied, _Rejected):
            if not acknowledged: raise
        except Exception:
            if not write_started: raise
        return result({"outcome": "unknown", "receipt_id": receipt_id, "readback_verified": False, "billing_effect_verified": None, "notification_delivery_verified": None, "message": "The management change may have occurred. Inspect the actual school record before repeating; no automatic retry or rollback."})

    @classmethod
    async def load_field_options(cls, field_name, user_id=None, *, credential_data=None, credential_id=None, context=None, search=None, page_token=None, **kwargs):
        if field_name not in ("course_id", "user_id", "lecture_id"): return {"options": [], "next_page_token": None}
        context = context or {}; user_id = user_id or context.get("_user_id")
        if field_name == "lecture_id" and not context.get("course_id"): raise ValueError("Choose the course before loading Teachable lectures.")
        saved = await cls.freshen_credential(credential_data, credential_id=credential_id, user_id=user_id, pool=kwargs.get("pool"))
        credential = _credential(saved)
        if field_name != "course_id" and credential.credential_type != TYPES[0]: raise TeachableDenied("Teachable user/lecture pickers require the Admin API key.")
        from nodes.core.run_op import run_node_operation
        operation = ("list_my_courses" if credential.credential_type == TYPES[1] else "list_courses") if field_name == "course_id" else "list_users" if field_name == "user_id" else "list_course_lectures"
        args = {"limit": 100, "page_token": page_token}
        if field_name == "lecture_id": args["course_id"] = _id(context["course_id"])
        output = await run_node_operation(node_type="automation-teachable", operation=operation, arguments=args, user_id=user_id, credential_id=credential_id, credential_data=saved, pool=kwargs.get("pool"), organization_id=kwargs.get("organization_id"), workflow_id=kwargs.get("workflow_id"))
        if output.get("executed") is False or output.get("status") in ("pending_approval", "rejected"): return output
        query = _text(search, 128).casefold() if search else None
        rows = [{"value": row["id"], "label": row["name"]} for row in output["data"]["items"]]
        return {"options": [row for row in rows if query is None or query in row["label"].casefold()], "next_page_token": output["data"]["next_page_token"]}
