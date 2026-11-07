"""Oracle Eloqua REST metadata and ordinary record CRUD, never marketing execution.

Discovery is authenticated at login.eloqua.com/id and binds a documented pod to
its site/user. PUT preserves complete documented resources; it is not PATCH.
"""
import asyncio
import base64
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, normalize_search
from utils.credentials import resolve_credential_with_owner_fallback, strip_non_blob_keys
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

LOGIN = "https://login.eloqua.com"
FAMILIES = {"eloqua_basic", "eloqua_bearer_token"}
POD = r"https://secure\.p0[1234678]\.eloqua\.com"
PRIVATE_REQUEST = ContextVar("eloqua_private_http_request", default=False)
# Bounded, process-local discovery cache. Keys are credential/authority digests,
# never raw secrets; changed credentials cannot reuse an authenticated binding.
_DISCOVERY = {}
_DISCOVERY_LOCK = asyncio.Lock()


class _RequestFilter(logging.Filter):
    def filter(self, record):
        if not PRIVATE_REQUEST.get():
            return True
        record.msg, record.args = "Eloqua HTTP transport activity", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value):
        raise ValueError("Enter a positive Eloqua numeric ID")
    return value


Identifier = Annotated[str, BeforeValidator(_id)]
Text = Annotated[str, Field(min_length=1, max_length=255)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or ("credential_type" in raw and (not isinstance(raw["credential_type"], str) or raw["credential_type"] not in FAMILIES)):
        raise ValueError("Connect a native Eloqua credential")
    return raw


class _Binding(BaseModel):
    expected_site_id: Optional[Identifier] = Field(None, title="Expected Eloqua Site ID")
    expected_user_id: Optional[Identifier] = Field(None, title="Expected Eloqua User ID")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.oracle.com/en/cloud/saas/marketing/eloqua-rest-api/Authentication_Basic.html"})


class EloquaBasicCredential(_Binding):
    credential_type: Literal["eloqua_basic"] = Field("eloqua_basic", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Oracle Eloqua Basic Authentication")
    company: Text = Field(..., title="Company / Site Name", description="Eloqua login company, used as Company\\User in HTTP Basic authentication.")
    username: Text = Field(..., title="Eloqua Username")
    password: str = Field(..., min_length=1, max_length=4096, title="Eloqua Password", json_schema_extra={"ui:widget": "password"})

    @field_validator("company", "username")
    @classmethod
    def login_part(cls, value):
        if value.strip() != value or any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in value):
            raise ValueError("Supply a valid Eloqua login component")
        return value

    @field_validator("password")
    @classmethod
    def password_value(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Supply a valid Eloqua password")
        return value


class EloquaBearerTokenCredential(_Binding):
    credential_type: Literal["eloqua_bearer_token"] = Field("eloqua_bearer_token", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Oracle Eloqua Issued Bearer Token")
    access_token: str = Field(..., min_length=1, max_length=4096, title="Issued OAuth Access Token", description="Already issued by your registered Eloqua application. NoClick does not register an app or refresh this token.", json_schema_extra={"ui:widget": "password"})
    expires_at: datetime = Field(..., title="Actual Token Expiry", description="Use the issuing response's expires_in; do not assume the documentation example is your actual lifetime.")

    @field_validator("access_token")
    @classmethod
    def token_value(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid issued Eloqua token")
        return value

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supply token expiry with its timezone")
        return value


Credentials = Union[EloquaBasicCredential, EloquaBearerTokenCredential]


def _credential(raw):
    raw = _family(raw)
    try:
        result = TypeAdapter(Credentials).validate_python(raw)
        if isinstance(result, EloquaBearerTokenCredential) and result.expires_at <= datetime.now(timezone.utc):
            raise ValueError
        return result
    except Exception:
        raise ValueError("Eloqua credential is invalid or expired; reconnect") from None


def _op(value, title, group):
    return Field(value, title=title, json_schema_extra={"x-operation-group": group})


def _selector(title, name):
    return Field(..., title=title, json_schema_extra={"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}, "x-resource-type": "eloqua_" + name})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetIdentity(Settings):
    operation: Literal["get_identity"] = _op("get_identity", "Get Authenticated Site and User", "Account")


class Page(Settings):
    count: int = Field(25, ge=1, le=100, title="Page Size")
    page_token: Optional[str] = Field(None, max_length=18000, title="Continuation", json_schema_extra={"ui:hidden": True})


class ListContacts(Page):
    operation: Literal["list_contacts"] = _op("list_contacts", "List Contact Metadata", "Contacts")


class GetContact(Settings):
    operation: Literal["get_contact"] = _op("get_contact", "Get Contact Metadata", "Contacts")
    contact_id: Identifier = _selector("Contact", "contact_id")


class CreateContact(Settings):
    operation: Literal["create_contact"] = _op("create_contact", "Create Contact", "Contacts")
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")
    email_address: str = Field(..., min_length=3, max_length=254, title="Email Address", description="Stored CRM contact data; no email deployment API is called.")

    @field_validator("email_address")
    @classmethod
    def email(cls, value):
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
            raise ValueError("Supply a contact email address")
        return value


class UpdateContact(GetContact):
    operation: Literal["update_contact"] = _op("update_contact", "Rename Own Contact", "Contacts")
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")


class DeleteContact(GetContact):
    operation: Literal["delete_contact"] = _op("delete_contact", "Delete Own Contact", "Contacts")


class ListAccounts(Page):
    operation: Literal["list_accounts"] = _op("list_accounts", "List Company Account Metadata", "Company Accounts")


class GetAccount(Settings):
    operation: Literal["get_account"] = _op("get_account", "Get Company Account Metadata", "Company Accounts")
    account_id: Identifier = _selector("Company Account", "account_id")


class CreateAccount(Settings):
    operation: Literal["create_account"] = _op("create_account", "Create Company Account", "Company Accounts")
    name: Text = Field(..., title="Company Account Name")


class UpdateAccount(GetAccount):
    operation: Literal["update_account"] = _op("update_account", "Rename Own Company Account", "Company Accounts")
    name: Text = Field(..., title="Company Account Name")


class DeleteAccount(GetAccount):
    operation: Literal["delete_account"] = _op("delete_account", "Delete Own Company Account", "Company Accounts")


class ListCustomObjects(Page):
    operation: Literal["list_custom_objects"] = _op("list_custom_objects", "List Custom Object Definitions", "Custom Objects")


class GetCustomObject(Settings):
    operation: Literal["get_custom_object"] = _op("get_custom_object", "Get Custom Object Field Metadata", "Custom Objects")
    custom_object_id: Identifier = _selector("Custom Object", "custom_object_id")


class CreateCustomObject(Settings):
    operation: Literal["create_custom_object"] = _op("create_custom_object", "Create Text Custom Object", "Custom Objects")
    name: Text = Field(..., title="Custom Object Name")
    text_field_name: Text = Field(..., title="Text Field Name", description="Creates one ordinary text field; no linked-contact deletion option is enabled.")


class UpdateCustomObject(GetCustomObject):
    operation: Literal["update_custom_object"] = _op("update_custom_object", "Rename Own Custom Object", "Custom Objects")
    name: Text = Field(..., title="Custom Object Name")


class DeleteCustomObject(GetCustomObject):
    operation: Literal["delete_custom_object"] = _op("delete_custom_object", "Delete Own Empty Custom Object", "Custom Objects")


class ListCustomObjectRecords(GetCustomObject, Page):
    operation: Literal["list_custom_object_records"] = _op("list_custom_object_records", "List Custom Object Record Metadata", "Custom Object Records")


class GetCustomObjectRecord(GetCustomObject):
    operation: Literal["get_custom_object_record"] = _op("get_custom_object_record", "Get Custom Object Record Metadata", "Custom Object Records")
    record_id: Identifier = Field(..., title="Record ID in This Custom Object", json_schema_extra={"x-resource-type": "eloqua_custom_object_record_id"})


class TextFieldValue(Settings):
    field_id: Identifier = Field(..., title="Text Field ID")
    value: str = Field(..., max_length=4000, title="Text Value")


class CreateCustomObjectRecord(GetCustomObject):
    operation: Literal["create_custom_object_record"] = _op("create_custom_object_record", "Create Unlinked Text Record", "Custom Object Records")
    field_values: list[TextFieldValue] = Field(..., min_length=1, max_length=100, title="Text Field Values", description="Validated against this custom object's text fields; no contact/account mapping.")


class UpdateCustomObjectRecord(GetCustomObjectRecord):
    operation: Literal["update_custom_object_record"] = _op("update_custom_object_record", "Update Own Text Record", "Custom Object Records")
    field_values: list[TextFieldValue] = Field(..., min_length=1, max_length=100, title="Text Field Values")


class DeleteCustomObjectRecord(GetCustomObjectRecord):
    operation: Literal["delete_custom_object_record"] = _op("delete_custom_object_record", "Delete Own Unlinked Record", "Custom Object Records")


Operations = Annotated[Union[GetIdentity, ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact,
    ListAccounts, GetAccount, CreateAccount, UpdateAccount, DeleteAccount,
    ListCustomObjects, GetCustomObject, CreateCustomObject, UpdateCustomObject, DeleteCustomObject,
    ListCustomObjectRecords, GetCustomObjectRecord, CreateCustomObjectRecord, UpdateCustomObjectRecord, DeleteCustomObjectRecord], Field(discriminator="operation")]


class EloquaNodeConfig(NodeConfig[Operations, Credentials]):
    pass


class _Authority:
    def __init__(self, credential, *, credential_id=None, user_id=None, pool=None, organization_id=None, workflow_id=None):
        self.credential = _credential(credential)
        self.credential_id, self.user_id, self.pool = credential_id, user_id, pool
        self.organization_id, self.workflow_id = organization_id, workflow_id

    async def check(self):
        _credential(self.credential)
        if not self.credential_id:
            return
        if not self.user_id:
            raise ValueError("Eloqua saved credential requires an authorized actor")
        row = await resolve_credential_with_owner_fallback(self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not row:
            raise ValueError("Eloqua current credential is unavailable or revoked")
        if _credential(strip_non_blob_keys(row)).model_dump() != self.credential.model_dump():
            raise ValueError("Eloqua credential binding changed; reconnect")

    def key(self):
        return hashlib.sha256(json.dumps([self.credential.model_dump(mode="json"), self.credential_id, self.user_id,
            self.organization_id, self.workflow_id], sort_keys=True, default=str).encode()).hexdigest()


def _authorization(credential):
    if isinstance(credential, EloquaBasicCredential):
        return "Basic " + base64.b64encode((credential.company + "\\" + credential.username + ":" + credential.password).encode()).decode()
    return "Bearer " + credential.access_token


def _secrets(credential):
    values = [_authorization(credential), credential.password if isinstance(credential, EloquaBasicCredential) else credential.access_token]
    if isinstance(credential, EloquaBasicCredential):
        values.append(credential.company + "\\" + credential.username + ":" + credential.password)
    return {s for v in values for s in (v, quote(v, safe=""), base64.b64encode(v.encode()).decode(), base64.urlsafe_b64encode(v.encode()).decode(), v.encode().hex())}


def _public(value, credential):
    if any(s in json.dumps(value, ensure_ascii=False) for s in _secrets(credential)):
        raise ValueError("Eloqua response contained protected credential data")
    return value


# Exact property sets in Oracle's current official Swagger, version 2026.08.07.
COMMON = set("type id currentStatus name description permissions createdBy createdAt updatedBy updatedAt depth".split())
PROPERTIES = {
    "contact": COMMON | set("firstName lastName emailAddress emailFormatPreference isSubscribed isBounceback accountName accountId title subscriptionDate unsubscriptionDate bouncebackDate fieldValues address1 address2 address3 city province postalCode country businessPhone mobilePhone fax salesPerson".split()),
    "account": COMMON | set("fieldValues address1 address2 address3 city province postalCode country businessPhone crmSystemMappings".split()),
    "custom_object": COMMON | set("folderId sourceTemplateId createdByName updatedByName scheduledFor fields emailAddressFieldId displayNameFieldId uniqueCodeFieldId deleteLinkedCustomObjectData".split()),
    "custom_object_record": COMMON | set("folderId sourceTemplateId createdByName updatedByName scheduledFor contactId accountId uniqueCode customObjectRecordStatus fieldValues isMapped".split()),
}
FIELD_PROPERTIES = set("type id currentStatus description permissions folderId sourceTemplateId createdBy createdByName createdAt updatedBy updatedByName updatedAt scheduledFor depth name displayType dataType defaultValue internalName optionListId checkedValue uncheckedValue".split())
TYPES = {"contact": "Contact", "account": "Account", "custom_object": "CustomObject", "custom_object_record": "CustomObjectData"}
ROOTS = {"contact": ("1.0", "data/contact", "data/contacts"), "account": ("1.0", "data/account", "data/accounts"),
    "custom_object": ("2.0", "assets/customObject", "assets/customObjects")}


def _project(kind, row, credential):
    if not isinstance(row, dict) or row.get("type") != TYPES[kind]:
        raise ValueError("Eloqua resource type is invalid")
    result = {"type": TYPES[kind], "id": _id(row.get("id"))}
    for name in ("name", "firstName", "lastName", "createdBy", "createdAt", "updatedBy", "updatedAt"):
        if name in row:
            if not isinstance(row[name], str) or len(row[name]) > 255:
                raise ValueError("Eloqua metadata is invalid")
            result[name] = row[name]
    if kind == "custom_object" and "fields" in row:
        fields = row["fields"]
        if not isinstance(fields, list) or len(fields) > 500:
            raise ValueError("Eloqua custom object field metadata is invalid")
        result["fields"] = []
        for field in fields:
            if not isinstance(field, dict) or field.get("type") != "CustomObjectField":
                raise ValueError("Eloqua custom object field type is invalid")
            item = {"id": _id(field.get("id"))}
            for key in ("name", "displayType", "dataType", "internalName"):
                if key in field:
                    if not isinstance(field[key], str) or len(field[key]) > 255:
                        raise ValueError("Eloqua custom object field metadata is invalid")
                    item[key] = field[key]
            result["fields"].append(item)
        if len({f["id"] for f in result["fields"]}) != len(fields):
            raise ValueError("Eloqua custom object field IDs repeat")
    return _public(result, credential)


class EloquaRequestError(ValueError):
    def __init__(self, message, *, status=None, outcome="unverified"):
        super().__init__(message)
        self.status, self.outcome = status, outcome


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.binding = None

    async def _http(self, method, url, *, params=None, body=None, expected=(200,), empty=False):
        origin = LOGIN if url == LOGIN + "/id" else self.binding["origin"] if self.binding else None
        if origin is None:
            raise ValueError("Discover an authenticated Eloqua pod first")
        assert_exact_url_origin(url, origin)
        await self.authority.check()
        headers = {"Authorization": _authorization(self.credential), "Accept": "application/json", "Content-Type": "application/json"}
        _install_privacy()
        private = PRIVATE_REQUEST.set(True)
        try:
            with OutboundTraceProvider().get_tracer(__name__).start_as_current_span(method, kind=SpanKind.CLIENT,
                attributes={"http.request.method": method, "url.full": origin + "/[native-resource]", "url.scheme": "https", "server.address": urlsplit(origin).hostname, "server.port": 443},
                record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > 2_000_000:
                                        raise EloquaRequestError("Eloqua metadata response exceeds its bound; verify any write")
                                    content.extend(chunk)
                                status, media = response.status_code, response.headers.get("content-type", "")
                                span.set_attribute("http.response.status_code", status)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    if isinstance(error, httpx.HTTPError):
                        raise EloquaRequestError("Eloqua write outcome is unknown; verify before retrying" if method != "GET" else "Eloqua request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        if status in {401, 403}:
            _DISCOVERY.pop(self.authority.key(), None)
        if status not in expected:
            raise EloquaRequestError(f"Eloqua returned HTTP {status}; check access and verify any uncertain write", status=status, outcome="rate_limited" if status == 429 else "unverified")
        if content and bytes(content).strip().strip(b'"').lower() in {b"not authenticated", b"not authenticated."}:
            _DISCOVERY.pop(self.authority.key(), None)
            raise EloquaRequestError("Eloqua did not authenticate this credential", status=status, outcome="unauthenticated")
        if empty or status == 204:
            # Delete custom-object/record contracts specify HTTP200, no schema.
            # Preserve the acknowledgement without fabricating a JSON resource.
            return {"http_status": status, "acknowledged": True} if empty else None
        try:
            if media.split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError
            return json.loads(content)
        except Exception:
            raise EloquaRequestError("Eloqua response is not documented JSON; verify any write before retrying", status=status) from None

    async def identity(self, *, force=False):
        await self.authority.check()
        key = self.authority.key()
        async with _DISCOVERY_LOCK:
            cached = _DISCOVERY.get(key)
            if not force and cached is not None and cached[0] > time.monotonic():
                self.binding = dict(cached[1])
            else:
                payload = await self._http("GET", LOGIN + "/id")
                if not isinstance(payload, dict) or not isinstance(payload.get("site"), dict) or not isinstance(payload.get("user"), dict) or not isinstance(payload.get("urls"), dict):
                    raise ValueError("Eloqua authenticated site/user discovery is missing")
                site, user, urls = payload["site"], payload["user"], payload["urls"]
                if type(site.get("id")) is not int or type(user.get("id")) is not int:
                    raise ValueError("Eloqua discovery principal IDs are invalid")
                site_id, user_id = _id(str(site["id"])), _id(str(user["id"]))
                if not isinstance(site.get("name"), str) or not 1 <= len(site["name"]) <= 255 or not isinstance(user.get("displayName"), str) or not 1 <= len(user["displayName"]) <= 255 or not isinstance(user.get("username"), str) or not 1 <= len(user["username"]) <= 255:
                    raise ValueError("Eloqua discovery principal metadata is invalid")
                origin = urls.get("base")
                rest = ((urls.get("apis") or {}).get("rest") or {}) if isinstance(urls.get("apis"), dict) else {}
                if not isinstance(rest, dict) or not isinstance(origin, str) or not re.fullmatch(POD, origin) or rest.get("standard") != origin + "/API/REST/{version}/":
                    raise ValueError("Eloqua discovery did not return a documented matching HTTPS pod")
                if isinstance(self.credential, EloquaBasicCredential) and (site["name"] != self.credential.company or user["username"] != self.credential.username):
                    raise ValueError("Eloqua Basic discovery belongs to another company or user")
                if cached is not None and (cached[1]["site_id"], cached[1]["user_id"]) != (site_id, user_id):
                    _DISCOVERY.pop(key, None)
                    raise ValueError("Eloqua rediscovery changed site or user; reconnect")
                self.binding = {"origin": origin, "site_id": site_id, "user_id": user_id, "site_name": site["name"], "user_display_name": user["displayName"]}
                # Expiry never extends the supplied Bearer's lifetime.
                for expired in [k for k, v in _DISCOVERY.items() if v[0] <= time.monotonic()]:
                    _DISCOVERY.pop(expired, None)
                if len(_DISCOVERY) >= 128:
                    _DISCOVERY.pop(next(iter(_DISCOVERY)))
                _DISCOVERY[key] = (time.monotonic() + 300, dict(self.binding))
        c = self.credential
        if c.expected_site_id and c.expected_site_id != self.binding["site_id"] or c.expected_user_id and c.expected_user_id != self.binding["user_id"]:
            _DISCOVERY.pop(key, None)
            raise ValueError("Eloqua credential belongs to another site or user")
        await self.authority.check()
        return _public({k: v for k, v in self.binding.items() if k != "origin"}, c)

    def route(self, kind, identifier=None, *, collection=False, parent=None):
        if kind == "custom_object_record":
            _id(parent)
            version, single, multiple = "2.0", f"data/customObject/{parent}/instance", f"data/customObject/{parent}/instances"
        else:
            version, single, multiple = ROOTS[kind]
        return "/API/REST/" + version + "/" + (multiple if collection else single + ("/" + _id(identifier) if identifier else ""))

    async def request(self, method, kind, identifier=None, *, parent=None, collection=False, params=None, body=None):
        if self.binding is None:
            raise ValueError("Eloqua principal discovery is required")
        if kind not in TYPES or method not in {"GET", "POST", "PUT", "DELETE"} or collection and method != "GET" or method in {"PUT", "DELETE"} and not identifier or method == "POST" and identifier:
            raise ValueError("Unsupported Eloqua native route")
        if method == "GET" and not collection and not identifier:
            raise ValueError("Eloqua single-resource reads require an ID")
        if method == "GET":
            params = params or {"depth": "complete"}
            if set(params) != ({"depth", "count", "page"} if collection else {"depth"}) or params.get("depth") != "complete" or collection and (type(params.get("count")) is not int or not 1 <= params["count"] <= 100 or type(params.get("page")) is not int or not 1 <= params["page"] <= 100):
                raise ValueError("Unsupported Eloqua native metadata query")
        elif params is not None:
            raise ValueError("Eloqua native writes have no query overrides")
        if method in {"POST", "PUT"}:
            if not isinstance(body, dict) or not body or set(body) - PROPERTIES[kind]:
                raise ValueError("Unsupported Eloqua native payload")
            _public(body, self.credential)
        elif body is not None:
            raise ValueError("Unsupported Eloqua native payload")
        expected = (201,) if method == "POST" else (204,) if method == "DELETE" and kind in {"contact", "account"} else (200, 204) if method == "GET" and collection and kind in {"contact", "account"} else (200,)
        return await self._http(method, self.binding["origin"] + self.route(kind, identifier, parent=parent, collection=collection), params=params, body=body, expected=expected, empty=method == "DELETE")

    async def one(self, kind, identifier, parent=None):
        row = await self.request("GET", kind, identifier, parent=parent)
        projected = _project(kind, row, self.credential)
        if projected["id"] != identifier:
            raise ValueError("Eloqua selected record changed identity")
        return row, projected

    def owned(self, row, *, record=False):
        if row.get("createdBy") != self.binding["user_id"]:
            raise ValueError("Manage only records created by the current Eloqua user")
        if record and (row.get("contactId") not in {None, "0", ""} or row.get("accountId") not in {None, "0", ""} or row.get("isMapped") not in {None, "false"}):
            raise ValueError("Manage only unlinked Eloqua custom object records")

    def preserve(self, kind, row):
        if row.get("depth") != "complete" or set(row) - PROPERTIES[kind]:
            raise ValueError("Eloqua PUT requires complete, known properties; no fields were overwritten")
        # All documented properties are retained, including nested field values.
        # Only explicit native fields are subsequently changed. No implicit clear.
        for key, value in row.items():
            if key in {"fields", "fieldValues", "crmSystemMappings", "permissions"}:
                if not isinstance(value, (list, str)) or isinstance(value, list) and len(value) > 500:
                    raise ValueError("Eloqua preserved collection is invalid")
                if key in {"fields", "fieldValues"} and isinstance(value, list):
                    allowed = FIELD_PROPERTIES if key == "fields" else {"type", "id", "value", "name"}
                    if any(not isinstance(v, dict) or set(v) - allowed or any(not isinstance(x, str) and not (k == "permissions" and isinstance(x, list) and all(isinstance(p, str) for p in x)) for k, x in v.items()) for v in value):
                        raise ValueError("Eloqua preserved field definitions are invalid")
            elif not isinstance(value, str):
                raise ValueError("Eloqua preserved resource property is invalid")
        return json.loads(json.dumps(row))

    def text_values(self, cfg, definition):
        fields = definition.get("fields")
        if not isinstance(fields, list):
            raise ValueError("Load complete Eloqua custom object field metadata first")
        allowed = {f["id"] for f in fields if isinstance(f, dict) and f.get("dataType") == "text" and f.get("displayType") == "text" and isinstance(f.get("id"), str)}
        result = [{"id": f.field_id, "value": f.value} for f in cfg.field_values]
        if len({v["id"] for v in result}) != len(result) or any(v["id"] not in allowed for v in result):
            raise ValueError("Select distinct text fields belonging to this custom object")
        return result

    def scope(self, kind, count, parent):
        return hashlib.sha256(json.dumps([self.authority.key(), self.binding, kind, count, parent], sort_keys=True).encode()).hexdigest()

    async def page(self, kind, count, token=None, parent=None):
        page, seen = 1, []
        scope = self.scope(kind, count, parent)
        if token:
            try:
                encoded, signature = token.split(".")
                blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
                data = json.loads(blob)
                if not hmac.compare_digest(signature, hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()) or set(data) != {"scope", "page", "seen"} or data["scope"] != scope or type(data["page"]) is not int or not 2 <= data["page"] <= 100 or not isinstance(data["seen"], list) or len(data["seen"]) != data["page"] - 1 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in data["seen"]):
                    raise ValueError
                page, seen = data["page"], data["seen"]
            except Exception:
                raise ValueError("Eloqua continuation belongs to another key, authority, site, user, pod, parent or page size") from None
        payload = await self.request("GET", kind, collection=True, parent=parent, params={"depth": "complete", "count": count, "page": page})
        if payload is None:
            return {"data": [], "total": 0 if page == 1 else None, "next_page_token": None, "http_status": 204}
        if not isinstance(payload, dict) or not isinstance(payload.get("type"), str) or not 1 <= len(payload["type"]) <= 100 or not isinstance(payload.get("elements"), list) or type(payload.get("total")) is not int or payload["total"] < len(payload["elements"]) or type(payload.get("page")) is not int or payload["page"] != page or type(payload.get("pageSize")) is not int or payload["pageSize"] != count or len(payload["elements"]) > count:
            raise ValueError("Eloqua collection paging envelope is invalid")
        rows = [_project(kind, r, self.credential) for r in payload["elements"]]
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Eloqua collection contains duplicate record IDs")
        fingerprint = hashlib.sha256(json.dumps(sorted(r["id"] for r in rows)).encode()).hexdigest()
        if rows and fingerprint in seen:
            raise ValueError("Eloqua pagination repeated a page")
        more = page * count < payload["total"]
        if more and (not rows or page >= 100):
            raise ValueError("Eloqua continuation exceeds its bound or follows an empty page")
        next_token = None
        if more:
            blob = json.dumps({"scope": scope, "page": page + 1, "seen": seen + [fingerprint]}, separators=(",", ":")).encode()
            next_token = base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()
        return {"data": rows, "total": payload["total"], "next_page_token": next_token, "http_status": 200}


class EloquaNode(WorkflowNode):
    integration_type = "automation-eloqua"
    credential_provider_labels = {"eloqua": "Oracle Eloqua Account"}
    connection_evidence = ConnectionEvidence(noun="Eloqua site user", operation="get_identity", identity_operation="get_identity", identity_keys=("site_id", "user_id", "site_name"), proves="account")

    @classmethod
    def get_config_model(cls):
        return EloquaNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, EloquaNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("Eloqua configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["Eloqua credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials, credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            pool=self.node_data.get("_approval_pool"), organization_id=self.organization_id, workflow_id=self.workflow_id)

    async def run(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        self._native_authority = self._authority()
        await self._native_authority.check()
        return await super().run(inputs)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # These are existing Basic credentials or an already-issued token, not
        # a managed OAuth connection. Staging owns loading and its admission checks.
        return _credential(strip_non_blob_keys(_family(credential_data))).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run authenticated site/user connection evidence to verify Eloqua access"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(getattr(self, "_native_authority", None) or self._authority())
        cfg, op = self.config.config, self.config.config.operation
        identity = await client.identity(force=op == "get_identity")
        if op == "get_identity":
            return identity
        action, resource = op.split("_", 1)
        kind = {"contacts": "contact", "accounts": "account", "custom_objects": "custom_object", "custom_object_records": "custom_object_record"}.get(resource, resource)
        parent, definition = None, None
        if kind == "custom_object_record":
            parent = cfg.custom_object_id
            definition, _ = await client.one("custom_object", parent)
        if action == "list":
            return {**identity, **await client.page(kind, cfg.count, cfg.page_token, parent), **({"custom_object_id": parent} if parent else {})}
        target = getattr(cfg, {"contact": "contact_id", "account": "account_id", "custom_object": "custom_object_id", "custom_object_record": "record_id"}[kind], None) if action != "create" else None
        row, projected = await client.one(kind, target, parent) if target else (None, None)
        if action == "get":
            return {**identity, "data": projected, **({"custom_object_id": parent} if parent else {})}
        if row:
            client.owned(row, record=kind == "custom_object_record")
        if action == "delete":
            if kind == "custom_object":
                page = await client.page("custom_object_record", 1, parent=target)
                if page["data"] or page["total"] != 0 or page["next_page_token"]:
                    raise ValueError("Delete only an empty Eloqua custom object")
            receipt = await client.request("DELETE", kind, target, parent=parent)
            return {**identity, "id": target, **receipt, "effect": "Deletion acknowledged; independent authenticated absence readback remains required"}
        body = client.preserve(kind, row) if row else {}
        if kind == "contact":
            changes = {"firstName": cfg.first_name, "lastName": cfg.last_name}
            if action == "create":
                changes["emailAddress"] = cfg.email_address
        elif kind in {"account", "custom_object"}:
            changes = {"name": cfg.name}
            if kind == "custom_object" and action == "create":
                changes["fields"] = [{"name": cfg.text_field_name, "displayType": "text", "dataType": "text"}]
        else:
            values = client.text_values(cfg, definition)
            if action == "create":
                changes = {"fieldValues": values}
            else:
                existing = body.get("fieldValues")
                if not isinstance(existing, list) or any(not isinstance(v, dict) or not isinstance(v.get("id"), str) for v in existing) or len({v["id"] for v in existing}) != len(existing):
                    raise ValueError("Eloqua complete record field values are invalid")
                mapped = {v["id"]: v for v in existing}
                for value in values:
                    mapped[value["id"]] = {**mapped.get(value["id"], {}), **value}
                changes = {"fieldValues": list(mapped.values())}
        body.update(changes)
        receipt = await client.request("POST" if action == "create" else "PUT", kind, target, parent=parent, body=body)
        result = _project(kind, receipt, client.credential)
        if target and target != result["id"]:
            raise ValueError("Eloqua write receipt changed identity; verify before retrying")
        target = result["id"]
        changed, result = await client.one(kind, target, parent)
        client.owned(changed, record=kind == "custom_object_record")
        for key, expected in changes.items():
            if key == "fieldValues":
                actual = {v.get("id"): v.get("value") for v in changed.get("fieldValues", []) if isinstance(v, dict)}
                if any(actual.get(v["id"]) != v["value"] for v in client.text_values(cfg, definition)):
                    raise ValueError("Eloqua text write readback differs; verify before retrying")
            elif key == "fields":
                if not any(f.get("name") == cfg.text_field_name and f.get("dataType") == "text" and f.get("displayType") == "text" for f in changed.get("fields", []) if isinstance(f, dict)):
                    raise ValueError("Eloqua custom field readback differs; verify before retrying")
            elif changed.get(key) != expected:
                raise ValueError("Eloqua write readback differs; verify before retrying")
        return {**identity, "id": target, "data": result, "acknowledged": True, **({"custom_object_id": parent} if parent else {}),
            "effect": "Ordinary Eloqua CRM metadata changed; site automation and notification effects are unqualified"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        kinds = {"contact_id": "contact", "account_id": "account", "custom_object_id": "custom_object"}
        if field_name not in kinds:
            raise ValueError("Unsupported Eloqua selector")
        _credential(credential_data)
        client = _Client(_Authority(strip_non_blob_keys(credential_data)))
        await client.identity()
        async def fetch(token):
            page = await client.page(kinds[field_name], 50, token)
            return [{"value": r["id"], "label": r.get("name") or " ".join(v for v in (r.get("firstName"), r.get("lastName")) if v) or r["id"]} for r in page["data"]], page["next_page_token"]
        return await load_paginated_options(fetch, page_token=page_token, search=normalize_search(search))
