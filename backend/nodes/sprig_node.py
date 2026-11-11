"""Sprig user, export and Study APIs, pinned to the provider's OpenAPI contracts.

https://docs.sprig.com/reference/sprig-api.json (2.2.1)
https://docs.sprig.com/reference/study-api-v2.json (1.0.0)
"""
from dataclasses import dataclass
import json
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    versioned: bool = False


PAGE = ("limit", "cursor")
EXPORT = ("start", "end", "cursor", "limit")
STUDY = "/v2/studies/{study_id}"
OPERATIONS = {
    "list_responses": Operation("List Responses", "Exports", "GET", "/v1/responses", query=(*EXPORT, "sid", "with_snapshots", "with_urls", "with_meta", "with_custom_metadata", "with_deleted_responses")),
    "list_surveys": Operation("Export Surveys", "Exports", "GET", "/v1/surveys", query=(*EXPORT, "status")),
    "list_themes": Operation("List Themes", "Exports", "GET", "/v1/themes", query=("start", "end", "cursor", "sid")),
    "upsert_user": Operation("Upsert User", "Users", "POST", "/v2/users", ("user_id",), body=("user_id", "email_address", "attributes_json", "events_json")),
    "get_user": Operation("Get User", "Users", "GET", "/v2/users/{user_id}", ("user_id",)),
    "purge_visitors": Operation("Purge Visitors", "Users", "POST", "/v2/purge/visitors", ("user_ids_json",), body=("user_ids_json", "delay_seconds")),
    "list_studies": Operation("List Studies", "Studies", "GET", "/v2/studies", query=(*PAGE, "status", "type", "platform")),
    "create_study": Operation("Create Draft Study", "Studies", "POST", "/v2/studies", ("name", "type"), body=("name", "type", "platform")),
    "get_study": Operation("Get Study", "Studies", "GET", STUDY, ("study_id",)),
    "update_study": Operation("Update Study", "Studies", "PATCH", STUDY, ("study_id", "version"), body=("name", "status"), versioned=True),
    "delete_study": Operation("Delete Draft Study", "Studies", "DELETE", STUDY, ("study_id", "version"), versioned=True),
    "get_targeting": Operation("Get Study Targeting", "Targeting", "GET", STUDY + "/targeting", ("study_id",)),
    "edit_targeting": Operation("Replace Study Targeting", "Targeting", "PUT", STUDY + "/targeting", ("study_id", "version", "event_id"), body=("event_id", "audience_json", "delay_seconds"), versioned=True),
    "clear_targeting": Operation("Clear Study Targeting", "Targeting", "DELETE", STUDY + "/targeting", ("study_id", "version"), versioned=True),
    "get_layout": Operation("Get Study Layout", "Studies", "GET", STUDY + "/layout", ("study_id",)),
    "list_questions": Operation("List Questions", "Questions", "GET", STUDY + "/questions", ("study_id",), query=PAGE),
    "create_question": Operation("Create Open Text Question", "Questions", "POST", STUDY + "/questions", ("study_id", "version", "title"), body=("title", "required"), versioned=True),
    "get_question": Operation("Get Question", "Questions", "GET", STUDY + "/questions/{question_id}", ("study_id", "question_id")),
    "update_question": Operation("Update Question", "Questions", "PATCH", STUDY + "/questions/{question_id}", ("study_id", "question_id", "version"), query=("cascade",), body=("title", "required"), versioned=True),
    "delete_question": Operation("Delete Question", "Questions", "DELETE", STUDY + "/questions/{question_id}", ("study_id", "question_id", "version"), query=("cascade",), versioned=True),
    "validate_study": Operation("Validate Study", "Studies", "POST", STUDY + "/validate", ("study_id",)),
    "list_invitations": Operation("List Invitations", "Invitations", "GET", STUDY + "/invitations", ("study_id", "status"), query=PAGE + ("status",)),
    "create_invitations": Operation("Create Invitations", "Invitations", "POST", STUDY + "/invitations", ("study_id", "count", "idempotency_key"), body=("count", "idempotency_key")),
}


class SprigAPIKeyCredential(BaseModel):
    credential_type: Literal["sprig_api_key"] = Field("sprig_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Sprig API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.sprig.com/integrations",
        "x-credential-instructions": "In Sprig, open Integrations > Sources > Enrichment > Data Import API and copy the API key for your Production or Development environment. Study API availability and export access depend on your Sprig account. Use the key alone, without API-Key or Bearer.",
    })

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without its authorization prefix")
        return value


class SprigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_values(self):
        values = self.model_dump(exclude_none=True)
        if values.get("user_id") in {".", ".."}:
            raise ValueError("Use a user ID, not a path segment")
        for key in ("study_id", "question_id", "event_id"):
            if key in values:
                UUID(values[key])
        if values.get("operation") == "create_study":
            if values.get("type") == "SURVEY" and values.get("platform"):
                raise ValueError("Platform applies only to in-product surveys")
            if values.get("type") == "IN_PRODUCT_SURVEY" and not values.get("platform"):
                raise ValueError("Choose WEB or MOBILE for an in-product survey")
        if values.get("operation") == "update_study":
            if not (values.get("name") or values.get("status")):
                raise ValueError("Supply a name or a lifecycle status")
            if values.get("name") and values.get("status"):
                raise ValueError("Change settings and lifecycle status in separate operations")
        if values.get("operation") == "update_question" and not ({"title", "required"} & values.keys()):
            raise ValueError("Supply a title or required flag")
        if values.get("start") is not None and values.get("end") is not None and values["end"] < values["start"]:
            raise ValueError("End must be at or after start")
        return self


def _field(name, required, operation):
    typ = str
    kwargs = {}
    default = ... if required else None
    if name in {"version", "start", "end", "sid", "count", "delay_seconds", "limit"}:
        typ = int
        kwargs["ge"] = 0 if name in {"start", "end", "sid", "delay_seconds"} else 1
        if name == "limit": kwargs["le"] = 1000 if operation in {"list_responses", "list_surveys"} else 50
        if name == "count": kwargs["le"] = 10000
        if name == "delay_seconds" and operation == "edit_targeting": kwargs["le"] = 999
    elif name == "required" or name.startswith("with_"):
        typ = bool
    elif name == "type": typ = Literal["SURVEY", "IN_PRODUCT_SURVEY"]
    elif name == "platform": typ = Literal["WEB", "MOBILE"]
    elif name == "cascade": typ = Literal["true", "false"]
    elif name == "status":
        typ = (Literal["OPEN", "SPENT", "EXPIRED"] if operation == "list_invitations" else
               Literal["IN_PROGRESS", "PAUSED", "COMPLETED", "ARCHIVED"] if operation == "update_study" else
               Literal["DRAFT", "IN_PROGRESS", "PAUSED", "COMPLETED", "ARCHIVED", "NEW"] if operation == "list_surveys" else
               Literal["DRAFT", "IN_PROGRESS", "PAUSED", "COMPLETED", "ARCHIVED"])
    if typ is str: kwargs["min_length"] = 1
    if name == "title": kwargs["max_length"] = 500
    if name == "cursor": kwargs["max_length"] = 999
    extra = {"ui:widget": "textarea"} if name.endswith("_json") else {}
    if name in {"study_id", "question_id", "event_id"}: extra["format"] = "uuid"
    description = {
        "version": "Study.version from your last read. Sent as a quoted If-Match header; stale writes are refused.",
        "start": "Earliest creation time, Unix milliseconds. Omit for all available history.",
        "end": "Latest creation time, Unix milliseconds.",
        "user_ids_json": "JSON array of 1 to 100 external user IDs. Purges users and their related data.",
        "attributes_json": "JSON object of user attributes.",
        "events_json": "JSON array of historical events: event (existing event name) and timestamp (Unix milliseconds). Does not trigger SDK studies.",
        "audience_json": "JSON audience rule from the Study API; omit to target every visitor.",
        "delay_seconds": "Targeting display delay, or purge delay. Omit purge delay to retain Sprig's ten day default.",
    }.get(name)
    return (typ if required else Optional[typ], Field(default, title=name.replace("_", " ").replace("json", "JSON").title(), description=description, json_schema_extra=extra or None, **kwargs))


def _make_config(name, op):
    fields = {f: _field(f, f in op.required, name) for f in sorted(set(op.required + op.query + op.body))}
    return create_model("Sprig" + "".join(p.title() for p in name.split("_")) + "Config", __base__=SprigInput,
        operation=(Literal[name], Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-is-trigger": False, "x-category": op.category, "x-display-name": op.label})), **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class SprigOnNewResponseConfig(PollTriggerConfigBase):
    operation: Literal["on_new_response"] = Field("on_new_response", json_schema_extra={
        "const": "on_new_response", "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Response"})
    sid: Optional[int] = Field(None, title="Survey ID", ge=0)
    start: Optional[int] = Field(None, title="Created Since (Unix Milliseconds)", ge=0,
        description="Optional creation-time lower bound. Set for large accounts to keep the poll under 10,000 responses.")


SprigConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (SprigOnNewResponseConfig,)], Discriminator("operation")]


class SprigNodeConfig(NodeConfig[SprigConfig, SprigAPIKeyCredential]):
    pass


def _json(value, kind, field):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must contain valid JSON") from None
    if not isinstance(parsed, kind):
        raise ValueError(f"{field} must contain a JSON {kind.__name__}")
    return parsed


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]") if secret in value else value
    if isinstance(value, list):
        redacted = [_redact(v, secret) for v in value]
        return value if all(a is b for a, b in zip(value, redacted)) else redacted
    if isinstance(value, dict):
        redacted = {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
        return value if all(k in redacted and redacted[k] is v for k, v in value.items()) else redacted
    return value


class SprigNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-sprig"
    connection_evidence = ConnectionEvidence(operation="list_studies", noun="studies")
    edit_examples = ["Upsert a Sprig user", "Export Sprig responses", "Create a draft Sprig study", "Watch for new Sprig responses"]

    @classmethod
    def get_config_model(cls):
        return SprigNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None, version=None):
        headers = {"Authorization": ("Bearer " if path.startswith("/v1/") else "API-Key ") + key, "Accept": "application/json"}
        if version is not None: headers["If-Match"] = f'"{version}"'
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, "https://api.sprig.com" + path, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            detail = response.text[:1500].replace(key, "[redacted]")
            raise ValueError(f"Sprig API error {response.status_code}: {detail}")
        data = response.json() if response.content else None
        return _redact(data, key), response.headers.get("ETag")

    @staticmethod
    def _body(op, values):
        names = {"user_id": "userId", "email_address": "emailAddress", "delay_seconds": "delaySeconds", "idempotency_key": "idempotencyKey"}
        body = {}
        for field in op.body:
            if field not in values: continue
            value = values[field]
            if field.endswith("_json"):
                value = _json(value, list if field in {"events_json", "user_ids_json"} else dict, field)
                target = {"user_ids_json": "userIds", "attributes_json": "attributes", "events_json": "events", "audience_json": "audience"}[field]
            else: target = names.get(field, field)
            body[target] = value
        if "userIds" in body and (not 1 <= len(body["userIds"]) <= 100 or not all(isinstance(i, str) and i for i in body["userIds"])):
            raise ValueError("Supply 1 to 100 nonempty user IDs")
        if "events" in body and not all(isinstance(e, dict) and set(e) <= {"event", "timestamp"} and isinstance(e.get("event"), str) and type(e.get("timestamp")) is int for e in body["events"]):
            raise ValueError("Each historical event needs event and timestamp")
        if "title" in body: body["title"] = {"html": body["title"]}
        return body

    async def _poll_responses(self, key, config):
        items, cursor, visited = [], None, set()
        for _ in range(10):
            params = {"limit": 1000}
            if config.sid is not None: params["sid"] = config.sid
            if config.start is not None: params["start"] = config.start
            if cursor: params["cursor"] = cursor
            data, _ = await self._request(key, "GET", "/v1/responses", params=params)
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("Sprig returned an invalid response page")
            items.extend(data["data"])
            cursor = data.get("cursor")
            # The export cursor identifies a position, not a promise of another
            # full page. A short page completes this bounded export read.
            if not cursor or len(data["data"]) < params["limit"]: break
            if cursor in visited: raise ValueError("Sprig returned a repeated response cursor")
            visited.add(cursor)
        else:
            raise ValueError("Sprig response poll exceeds 10,000 responses; narrow Created Since or Survey ID")
        def identity(item):
            # A response belongs to a respondent's submission group and a question.
            if not isinstance(item, dict) or item.get("responseGroupUid") is None or item.get("questionId") is None:
                raise ValueError("Sprig response is missing submission group or question ID")
            return json.dumps([item["responseGroupUid"], item["questionId"]])
        items = list({identity(item): item for item in items}.values())
        fresh = await self._filter_unseen(items, identity)
        return {"responses": fresh, "new_response_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_response_count")) if config.get("operation") == "on_new_response" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not isinstance(output.get("responses"), list):
            return super().resolve_agent_event(output)
        responses = output["responses"]
        if not responses: return None
        lines = [f"- Respondent {r.get('externalUserId') or r.get('visitorUuid') or r.get('visitorId')}: {str(r.get('questionText') or '')[:300]} — {json.dumps(r.get('response'), ensure_ascii=False)[:600]} (survey {r.get('surveyId')}, question {r.get('questionId')}, submission {r.get('responseGroupUid')})" for r in responses[:5]]
        if len(responses) > 5: lines.append(f"- … and {len(responses) - 5} more responses")
        return {"text": f"Sprig: {len(responses)} new response(s):\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, SprigNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Sprig API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if isinstance(config, SprigOnNewResponseConfig): return await self._poll_responses(key, config)
        name = config.operation
        op = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for field in ("study_id", "question_id", "user_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {field: values[field] for field in op.query if field in values}
        for field in params:
            if isinstance(params[field], bool): params[field] = str(params[field]).lower()
        body = self._body(op, values) if op.body else None
        if name == "create_question": body["type"] = "OPEN_TEXT"
        if name == "edit_targeting":
            body = {"triggers": [{"id": body.pop("event_id")}], "audience": body.get("audience"), "delaySeconds": body.get("delaySeconds", 0)}
        data, etag = await self._request(key, op.method, path, params=params or None, body=body, version=values.get("version") if op.versioned else None)
        return {"status": "success", "operation": name, "data": data, "etag": etag}
