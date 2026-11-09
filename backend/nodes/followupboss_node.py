"""Follow Up Boss CRM records and signed people webhooks.

Requests use supplied registered system identification. Manual people creation
bypasses lead automations; record operations invoke no communication endpoints.
"""
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
from urllib.parse import quote

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, normalize_search
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin


def _http_client(**kwargs):
    return httpx.AsyncClient(**kwargs)


ORIGIN, BASE = "https://api.followupboss.com", "https://api.followupboss.com/v1"
FAMILIES = {"followupboss_api_key", "followupboss_bearer_token"}
PRIVATE_REQUEST = ContextVar("followupboss_private_http_request", default=None)
_BACKOFF = {}


class _RequestFilter(logging.Filter):
    def filter(self, record):
        safe = PRIVATE_REQUEST.get()
        if safe is None:
            return True
        record.msg, record.args = "Follow Up Boss HTTP transport activity", ()
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
        raise ValueError("Enter a positive Follow Up Boss numeric ID")
    return value


Identifier = Annotated[str, BeforeValidator(_id)]
Text = Annotated[str, Field(min_length=1, max_length=255)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or ("credential_type" in raw and (not isinstance(raw["credential_type"], str) or raw["credential_type"] not in FAMILIES)):
        raise ValueError("Connect a native Follow Up Boss credential")
    return {k: v for k, v in raw.items() if k not in {"token_version", "updated_at"}}


class _System(BaseModel):
    system: str = Field(..., min_length=1, max_length=255, title="Registered System Name", description="Your application's actual registered X-System; NoClick registration is not supplied.")
    system_key: str = Field(..., min_length=1, max_length=4096, title="Registered System Key", json_schema_extra={"ui:widget": "password"})
    expected_account_id: Optional[Identifier] = Field(None, title="Expected Account ID")
    expected_user_id: Optional[Identifier] = Field(None, title="Expected User ID")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.followupboss.com/reference/identification"})

    @field_validator("system", "system_key")
    @classmethod
    def header_value(cls, value):
        if value != value.strip() or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid registered system header")
        return value


class FollowUpBossAPIKeyCredential(_System):
    model_config = ConfigDict(title="Follow Up Boss API Key")
    credential_type: Literal["followupboss_api_key"] = Field("followupboss_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="User API Key", description="Used as Basic username with an empty password.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if ":" in value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid Follow Up Boss API key")
        return value


class FollowUpBossBearerTokenCredential(_System):
    model_config = ConfigDict(title="Follow Up Boss Access Token", json_schema_extra={"title": "Follow Up Boss Access Token", "x-credential-type": "api_key", "x-credential-url": "https://docs.followupboss.com/reference/authentication"})
    credential_type: Literal["followupboss_bearer_token"] = Field("followupboss_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Supplied OAuth Access Token", description="Already issued token, without automatic registration, exchange or refresh.", json_schema_extra={"ui:widget": "password"})
    expires_at: datetime = Field(..., title="Actual Token Expiry", description="Finite timezone-qualified expiry; reconnect when expired.")

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid Bearer token")
        return value

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supply an expiry with its timezone")
        return value


Credentials = Union[FollowUpBossAPIKeyCredential, FollowUpBossBearerTokenCredential]


def _credential(raw):
    raw = _family(raw)
    try:
        value = TypeAdapter(Credentials).validate_python(raw)
        if isinstance(value, FollowUpBossBearerTokenCredential) and value.expires_at <= datetime.now(timezone.utc):
            raise ValueError
        return value
    except Exception:
        raise ValueError("Follow Up Boss credential is invalid or expired; reconnect") from None


def _op(value, title, group):
    return Field(value, title=title, json_schema_extra={"x-operation-group": group})


def _selector(title, name):
    return Field(..., title=title, json_schema_extra={"ui:widget": "select", "ui:options": {"loadOptions": name == "person_id", "dependsOn": []}, "x-resource-type": "followupboss_" + name})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetMe(Settings):
    operation: Literal["get_me"] = _op("get_me", "Get Current User and Account", "Account")


class Page(Settings):
    page_token: Optional[str] = Field(None, max_length=18000, title="Continuation", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100, title="Page Size")


class ListPeople(Page):
    operation: Literal["list_people"] = _op("list_people", "List People and Tag Metadata", "People")
    name: Optional[Text] = Field(None, title="Name Contains")
    tag: Optional[Text] = Field(None, title="Tag", description="One exact tag filter; tags are returned on people.")

    @field_validator("tag")
    @classmethod
    def single_tag(cls, value):
        if value is not None and "," in value:
            raise ValueError("Supply one tag")
        return value


class GetPerson(Settings):
    operation: Literal["get_person"] = _op("get_person", "Get Person Metadata", "People")
    person_id: Identifier = _selector("Person", "person_id")


class PersonNames(Settings):
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")


class CreatePerson(PersonNames):
    operation: Literal["create_person"] = _op("create_person", "Create Person (Deduplicate)", "People")
    email: Annotated[str, Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")] = Field(..., title="Email for Deduplication", description="Stored on the person; no email is sent.")


class UpdatePerson(PersonNames):
    operation: Literal["update_person"] = _op("update_person", "Update Person Name", "People")
    person_id: Identifier = _selector("Person", "person_id")


class DeletePerson(GetPerson):
    operation: Literal["delete_person"] = _op("delete_person", "Delete Person", "People")


class ListStages(Page):
    operation: Literal["list_stages"] = _op("list_stages", "List Stage Metadata", "Stages")


class GetNote(GetPerson):
    operation: Literal["get_note"] = _op("get_note", "Get Note Metadata", "Notes")
    note_id: Identifier = Field(..., title="Note ID", json_schema_extra={"x-resource-type": "followupboss_note_id"})


class NoteFields(GetPerson):
    subject: Text = Field(..., title="Subject")
    body: str = Field(..., min_length=1, max_length=10000, title="Plain Text Body")


class CreateNote(NoteFields):
    operation: Literal["create_note"] = _op("create_note", "Create Plain Note", "Notes")


class UpdateNote(NoteFields):
    operation: Literal["update_note"] = _op("update_note", "Update Plain Note", "Notes")
    note_id: Identifier = Field(..., title="Note ID")


class DeleteNote(GetNote):
    operation: Literal["delete_note"] = _op("delete_note", "Delete Note", "Notes")


class ListTasks(Page):
    operation: Literal["list_tasks"] = _op("list_tasks", "List Own Tasks", "Tasks")
    person_id: Optional[Identifier] = Field(None, title="Person ID")
    completed: Optional[bool] = Field(None, title="Completed")


class GetTask(GetPerson):
    operation: Literal["get_task"] = _op("get_task", "Get Own Task", "Tasks")
    task_id: Identifier = Field(..., title="Task ID", json_schema_extra={"x-resource-type": "followupboss_task_id"})


class CreateTask(GetPerson):
    operation: Literal["create_task"] = _op("create_task", "Create Own Follow Up Task", "Tasks")
    name: Text = Field(..., title="Task Name", description="Self-assigned Follow Up task; no reminder field is sent.")


class UpdateTask(CreateTask):
    operation: Literal["update_task"] = _op("update_task", "Rename Own Follow Up Task", "Tasks")
    task_id: Identifier = Field(..., title="Task ID")


class CompleteTask(GetTask):
    operation: Literal["complete_task"] = _op("complete_task", "Complete Own Follow Up Task", "Tasks")


class DeleteTask(GetTask):
    operation: Literal["delete_task"] = _op("delete_task", "Delete Own Follow Up Task", "Tasks")


PEOPLE_EVENTS = ("peopleCreated", "peopleUpdated", "peopleDeleted", "peopleTagsCreated", "peopleStageUpdated")


class OnPeopleEvent(WebhookTriggerConfigBase, Settings):
    operation: Literal["on_people_event"] = Field("on_people_event", title="On People Event", json_schema_extra={
        "x-is-trigger": True, "x-operation-group": "Triggers", "x-display-name": "On People Event"})
    event_type: Literal[*PEOPLE_EVENTS] = Field("peopleCreated", title="Event", description="Requires the account owner's credential and a registered system.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


Operations = Annotated[Union[GetMe, ListPeople, GetPerson, CreatePerson, UpdatePerson, DeletePerson, ListStages,
    GetNote, CreateNote, UpdateNote, DeleteNote, ListTasks, GetTask, CreateTask, UpdateTask, CompleteTask, DeleteTask, OnPeopleEvent], Field(discriminator="operation")]


class FollowUpBossNodeConfig(NodeConfig[Operations, Credentials]):
    pass


class _Authority:
    """Typed credential supplied by staging's shared credential admission path."""
    def __init__(self, credential):
        self.credential = _credential(credential)

    async def check(self):
        _credential(self.credential)


def _secrets(credential):
    key = credential.api_key if isinstance(credential, FollowUpBossAPIKeyCredential) else credential.access_token
    values = [key, credential.system_key]
    if isinstance(credential, FollowUpBossAPIKeyCredential):
        values.append(base64.b64encode((key + ":").encode()).decode())
    return {form for v in values for form in (v, quote(v, safe=""), base64.b64encode(v.encode()).decode(), base64.urlsafe_b64encode(v.encode()).decode(), v.encode().hex())}


def _public(value, credential):
    text = json.dumps(value, ensure_ascii=False)
    if any(s in text for s in _secrets(credential)):
        raise ValueError("Follow Up Boss response contained protected credential data")
    return value


PUBLIC = {
    "me": ("id", "account", "name", "role", "timeZone", "isOwner"),
    "people": ("id", "name", "firstName", "lastName", "stage", "stageId", "tags", "assignedUserId", "created", "updated", "lastActivity"),
    "stages": ("id", "name", "orderWeight", "isProtected", "peopleCount"),
    "notes": ("id", "personId", "created", "updated", "isHtml", "type"),
    "tasks": ("id", "personId", "assignedUserId", "name", "type", "isCompleted", "created", "updated", "completed", "dueDate", "dueDateTime"),
}


def _project(kind, row, credential):
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
        raise ValueError("Follow Up Boss resource identity is invalid")
    result = {k: row[k] for k in PUBLIC[kind] if k in row}
    for k, v in result.items():
        if v is not None and not isinstance(v, (str, int, bool, list)):
            raise ValueError("Follow Up Boss metadata shape is invalid")
        if isinstance(v, str) and len(v) > 10000:
            raise ValueError("Follow Up Boss metadata text is too large")
        if isinstance(v, list) and (k != "tags" or len(v) > 1000 or any(not isinstance(t, str) or len(t) > 255 for t in v)):
            raise ValueError("Follow Up Boss tags shape is invalid")
        if k in {"account", "personId", "assignedUserId", "stageId"} and v is not None and (type(v) is not int or v <= 0):
            raise ValueError("Follow Up Boss parent identity is invalid")
        if k in {"isHtml", "isCompleted"} and v is not None and (type(v) not in {int, bool} or v not in (0, 1)):
            raise ValueError("Follow Up Boss completion flag is invalid")
    return _public(result, credential)


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.account_id, self.user_id = None, None
        self.last_status = None

    def _key(self):
        c = self.credential
        key = c.api_key if isinstance(c, FollowUpBossAPIKeyCredential) else c.access_token
        return (key + "\0" + c.system + "\0" + c.system_key).encode()

    async def request(self, method, path, *, params=None, body=None):
        valid = method == "GET" and path in {"/me", "/people", "/stages", "/tasks"}
        valid = valid or method == "POST" and path in {"/people", "/notes", "/tasks", "/webhooks"}
        valid = valid or method in {"GET", "PUT", "DELETE"} and re.fullmatch(r"/(?:people|notes|tasks|webhooks)/[1-9][0-9]{0,15}", path)
        if not valid:
            raise ValueError("Unsupported Follow Up Boss native route")
        await self.authority.check()
        backoff_key = hashlib.sha256(self._key()).hexdigest()
        account_key = (self.credential.system, self.account_id)
        if max(_BACKOFF.get(backoff_key, 0), _BACKOFF.get(account_key, 0)) > time.monotonic():
            raise ValueError("Follow Up Boss is still throttled; wait before another request")
        if body is not None:
            _public(body, self.credential)
        headers = {"Accept": "application/json", "Content-Type": "application/json", "X-System": self.credential.system, "X-System-Key": self.credential.system_key}
        headers["Authorization"] = "Basic " + base64.b64encode((self.credential.api_key + ":").encode()).decode() if isinstance(self.credential, FollowUpBossAPIKeyCredential) else "Bearer " + self.credential.access_token
        url = BASE + path
        assert_exact_url_origin(url, ORIGIN)
        _install_privacy()
        private = PRIVATE_REQUEST.set((method, BASE + "/[native-resource]"))
        try:
            tracer = OutboundTraceProvider().get_tracer(__name__)
            with tracer.start_as_current_span(method, kind=SpanKind.CLIENT, attributes={"http.request.method": method,
                    "url.full": BASE + "/[native-resource]", "url.scheme": "https", "server.address": "api.followupboss.com", "server.port": 443},
                    record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with _http_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > 2_000_000:
                                        raise ValueError("Follow Up Boss response exceeds its metadata limit")
                                    content.extend(chunk)
                                status, media = response.status_code, response.headers.get("content-type", "")
                                retry = response.headers.get("retry-after", "")
                                span.set_attribute("http.response.status_code", status)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    # Never record exceptions containing request URLs/headers.
                    if isinstance(error, httpx.HTTPError):
                        raise ValueError("Follow Up Boss write outcome is unknown; verify before retrying" if method != "GET" else "Follow Up Boss request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        self.last_status = status
        if status == 429:
            seconds = int(retry) if re.fullmatch(r"[0-9]{1,9}", retry) else 60
            deadline = time.monotonic() + seconds
            _BACKOFF[backoff_key] = deadline
            if self.account_id:
                _BACKOFF[account_key] = deadline
            raise ValueError("Follow Up Boss request was throttled and not processed; wait for Retry-After before another request")
        expected = {200, 201} if method == "POST" and path == "/people" else {200}
        if status not in expected:
            raise ValueError(f"Follow Up Boss returned HTTP {status}; access or outcome is unverified")
        if method == "DELETE":
            # The documented success response is an empty acknowledgement.
            return {}
        if media.split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Follow Up Boss response was not JSON")
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:
            raise ValueError("Follow Up Boss JSON response is invalid") from None
        return payload

    async def identity(self):
        row = _project("me", await self.request("GET", "/me"), self.credential)
        if type(row.get("account")) is not int or not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("Follow Up Boss principal or account evidence is missing")
        self.account_id, self.user_id = row["account"], row["id"]
        c = self.credential
        if c.expected_account_id and int(c.expected_account_id) != self.account_id or c.expected_user_id and int(c.expected_user_id) != self.user_id:
            raise ValueError("Follow Up Boss credential belongs to another account or user")
        return row

    async def one(self, kind, identifier, person_id=None):
        params = {"fields": ",".join(PUBLIC["people"])} if kind == "people" else None
        row = _project(kind, await self.request("GET", "/" + kind + "/" + identifier, params=params), self.credential)
        if row["id"] != int(identifier) or person_id is not None and row.get("personId") != int(person_id):
            raise ValueError("Follow Up Boss selected resource or person does not match")
        return row

    def _scope(self, kind, params):
        return hashlib.sha256(json.dumps([self.account_id, self.user_id, kind, params], sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _encode(self, kind, params, state):
        blob = json.dumps({"scope": self._scope(kind, params), **state}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self._key(), blob, hashlib.sha256).hexdigest()

    def _decode(self, kind, params, token):
        try:
            encoded, signature = token.split(".")
            blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            data = json.loads(blob)
            if not hmac.compare_digest(signature, hmac.new(self._key(), blob, hashlib.sha256).hexdigest()) or set(data) != {"scope", "next", "offset", "seen", "page"} or data["scope"] != self._scope(kind, params):
                raise ValueError
            if type(data["page"]) is not int or not 2 <= data["page"] <= 100 or type(data["offset"]) is not int or not 0 <= data["offset"] <= 10000 or not isinstance(data["seen"], list) or len(data["seen"]) > 99 or any(not isinstance(s, str) or not re.fullmatch(r"[a-f0-9]{64}", s) for s in data["seen"]):
                raise ValueError
            if data["next"] is not None and (not isinstance(data["next"], str) or not 1 <= len(data["next"]) <= 4096):
                raise ValueError
            return data
        except Exception:
            raise ValueError("Follow Up Boss continuation belongs to another credential, account, resource or filter") from None

    async def page(self, kind, params, token=None):
        state = self._decode(kind, params, token) if token else {"next": None, "offset": 0, "seen": [], "page": 1}
        sent = dict(params)
        if state["next"] is not None:
            sent["next"] = state["next"]
        else:
            sent["offset"] = state["offset"]
        payload = await self.request("GET", "/" + kind, params=sent)
        info, rows = payload.get("_metadata"), payload.get(kind)
        if not isinstance(info, dict) or info.get("collection") != kind or not isinstance(rows, list) or len(rows) > params["limit"] or any(type(info.get(k)) is not int or info[k] < 0 for k in ("offset", "limit", "total")) or info["limit"] != params["limit"]:
            raise ValueError("Follow Up Boss page envelope is invalid")
        if state["next"] is None and info["offset"] != state["offset"]:
            raise ValueError("Follow Up Boss page offset changed")
        data = [_project(kind, row, self.credential) for row in rows]
        if len({r["id"] for r in data}) != len(data):
            raise ValueError("Follow Up Boss page repeated a resource")
        if kind == "tasks" and any(r.get("assignedUserId") != self.user_id or params.get("personId") and r.get("personId") != params["personId"] for r in data):
            raise ValueError("Follow Up Boss task scope changed")
        nav = info.get("next")
        more = info["offset"] + len(rows) < info["total"]
        continuation = None
        if nav is not None or more:
            if not rows or state["page"] >= 100:
                raise ValueError("Follow Up Boss continuation exceeds its bound")
            if nav is not None:
                if not isinstance(nav, str) or not 1 <= len(nav) <= 4096:
                    raise ValueError("Follow Up Boss opaque cursor is invalid")
                digest = hashlib.sha256(nav.encode()).hexdigest()
                if digest in state["seen"]:
                    raise ValueError("Follow Up Boss opaque cursor repeated")
                _public(nav, self.credential)
                seen = state["seen"] + [digest]
            else:
                # All collection endpoints document offset pagination.
                seen = state["seen"]
            offset = info["offset"] + len(rows)
            if offset > 10000:
                raise ValueError("Follow Up Boss offset exceeds its bound")
            continuation = self._encode(kind, params, {"next": nav, "offset": offset, "seen": seen, "page": state["page"] + 1})
        return {"data": data, "next_page_token": continuation, "total": info["total"]}


class FollowUpBossNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-followupboss"
    credential_provider_labels = {"followupboss": "Follow Up Boss Account"}
    connection_evidence = ConnectionEvidence(noun="user account", operation="get_me", identity_operation="get_me", identity_keys=("name",), proves="account")

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = OnPeopleEvent.model_validate({"event_type": (config or {}).get("event_type", "peopleCreated")}).event_type
        client = _Client(_Authority(credential))
        row = await client.request("POST", "/webhooks", body={"event": event, "url": webhook_url})
        if type(row.get("id")) is not int or row["id"] <= 0:
            raise ValueError("Follow Up Boss did not return a webhook ID")
        return {"external_webhook_id": str(row["id"]), "signing_secret": client.credential.system_key}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if credential and config.get("external_webhook_id"):
            identifier = _id(str(config["external_webhook_id"]))
            await _Client(_Authority(credential)).request("DELETE", "/webhooks/" + identifier)

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "peopleCreated")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://docs.followupboss.com/reference/webhooks-guide#verify-the-request
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "fub-signature"), "")
        if not secret or not isinstance(signature, str):
            return False
        digest = hmac.new(str(secret).encode(), base64.b64encode(body), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, digest)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event") == (config or {}).get("event_type", "peopleCreated")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        ids = payload.get("resourceIds")
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
            raise ValueError("Follow Up Boss event requires positive person IDs")
        output = {key: payload[key] for key in ("event", "eventCreated", "resourceIds", "uri") if key in payload}
        if payload["event"] == "peopleTagsCreated":
            output["tags"] = payload["data"]["tags"]
        elif payload["event"] == "peopleStageUpdated":
            output["stage"] = payload["data"]["stage"]
        return output

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("event") if isinstance(output, dict) else None
        if event not in PEOPLE_EVENTS:
            return super().resolve_agent_event(output)
        ids = output.get("resourceIds") or []
        labels = {"peopleCreated": "People created", "peopleUpdated": "People updated", "peopleDeleted": "People deleted",
                  "peopleTagsCreated": "Tags added to people", "peopleStageUpdated": "People's stages changed"}
        text = f"Follow Up Boss: {labels[event]} at {output.get('eventCreated')}. Person IDs: {', '.join(map(str, ids))}."
        if event == "peopleTagsCreated":
            text += f" Tags: {', '.join(output['tags'])}."
        elif event == "peopleStageUpdated":
            text += f" Stage: {output['stage']}."
        if output.get("uri"):
            text += f" Resource: {output['uri']}. Use get_person with each person_id to read current details."
        return {"text": text, "conversation_key": str(ids[0]) if len(ids) == 1 else None}

    @classmethod
    def get_config_model(cls):
        return FollowUpBossNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, FollowUpBossNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("Follow Up Boss configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["Follow Up Boss credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Supplied tokens have no refresh flow; fail clearly when expired.
        return _credential(credential_data).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run current user connection evidence to verify account access"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        if isinstance(self.config.config, OnPeopleEvent):
            return self.resolve_trigger_payload(inputs, self.config.config.model_dump()) or {}
        client = _Client(self._authority())
        identity = await client.identity()
        cfg, base = self.config.config, {"account_id": client.account_id, "user_id": client.user_id}
        op = cfg.operation
        if op == "get_me":
            return {**base, "name": identity["name"], "data": identity}
        if op in {"list_people", "list_stages", "list_tasks"}:
            kind = op[5:]
            params = {"limit": cfg.limit}
            if kind == "people":
                params.update(fields=",".join(PUBLIC["people"]), sort="id", includeTrash="false", includeUnclaimed="false")
                if cfg.name:
                    params["name"] = cfg.name
                if cfg.tag:
                    params["tags"] = cfg.tag
            elif kind == "stages":
                params["sort"] = "id"
            else:
                params["assignedUserId"] = client.user_id
                if cfg.person_id:
                    await client.one("people", cfg.person_id)
                    params["personId"] = int(cfg.person_id)
                if cfg.completed is not None:
                    params["isCompleted"] = str(cfg.completed).lower()
            return {**base, **await client.page(kind, params, cfg.page_token)}
        kind = "people" if "person" in op else "notes" if "note" in op else "tasks"
        action = op.split("_", 1)[0]
        target = getattr(cfg, {"people": "person_id", "notes": "note_id", "tasks": "task_id"}[kind], None) if action != "create" else None
        # Read a selected record when returning it or enforcing own-task scope.
        existing = await client.one(kind, target, cfg.person_id if kind != "people" else None) if target and (action == "get" or kind == "tasks") else None
        if kind == "tasks" and existing and existing.get("assignedUserId") != client.user_id:
            raise ValueError("Only the current user's task can be used")
        if action == "get":
            return {**base, "data": existing}
        if kind == "tasks" and existing and existing.get("type") != "Follow Up":
            raise ValueError("Choose an own Follow Up task for management")
        if action == "delete":
            await client.request("DELETE", "/" + kind + "/" + target)
            return {**base, "deleted": True, "id": int(target), "effect": "CRM record deleted; independent readback is required"}
        if kind == "people":
            body = {"firstName": cfg.first_name, "lastName": cfg.last_name}
            if action == "create":
                body.update(emails=[{"value": cfg.email, "type": "work"}], assignedUserId=client.user_id)
        elif kind == "notes":
            body = {"personId": int(cfg.person_id), "subject": cfg.subject, "body": cfg.body, "isHtml": False}
        else:
            body = {"isCompleted": True} if action == "complete" else {"name": cfg.name}
            if action == "create":
                body.update(personId=int(cfg.person_id), assignedUserId=client.user_id, type="Follow Up", isCompleted=False)
        row = await client.request("POST" if action == "create" else "PUT", "/" + kind + ("/" + target if target else ""),
            params={"deduplicate": "true"} if kind == "people" and action == "create" else None, body=body)
        if row == {} and kind in {"people", "notes"}:
            # POST /people, PUT /people/:id and POST /notes document {}.
            # No resource id or creation claim can be inferred from that body.
            return {**base, "data": {}, "acknowledged": True, "id": int(target) if target else None,
                    "created": None, "effect": "CRM write accepted; read the record to confirm its current state"}
        data = _project(kind, row, client.credential)
        if target and data["id"] != int(target) or kind != "people" and data.get("personId") != int(cfg.person_id) or kind == "tasks" and data.get("assignedUserId") != client.user_id:
            raise ValueError("Follow Up Boss write identity changed; verify before retrying")
        if action == "complete" and data.get("isCompleted") not in (True, 1):
            raise ValueError("Follow Up Boss task was not returned as completed; verify before retrying")
        return {**base, "data": data, "created": client.last_status == 201 if kind == "people" and action == "create" else action == "create", "effect": "CRM record management; no communication endpoint was invoked"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != "person_id":
            raise ValueError("Unsupported Follow Up Boss selector")
        _credential(credential_data)
        authority = _Authority(credential_data)
        client = _Client(authority)
        await client.identity()
        async def fetch(token):
            page = await client.page("people", {"limit": 100, "fields": ",".join(PUBLIC["people"]), "sort": "id", "includeTrash": "false", "includeUnclaimed": "false"}, token)
            return [{"value": str(r["id"]), "label": r.get("name") or str(r["id"])} for r in page["data"]], page["next_page_token"]
        return await load_paginated_options(fetch, page_token=page_token, search=normalize_search(search), cap=1000)
