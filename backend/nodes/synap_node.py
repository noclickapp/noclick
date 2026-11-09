"""Synap v3 learning and assessment automation using a personal access token.

The published OpenAPI 3.0.0 contract defines each action; Synap Academy defines
webhook bodies and HTTP Basic delivery authentication. No OAuth app is needed.
"""
from __future__ import annotations

import base64
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.synap.ac/v3"
CONTRACT = "https://api-stage.synap.ac/v3/schema"
AUTH_DOC = "https://synap.ac/docs/api/authentication"
WEBHOOK_DOC = "https://academy.synap.ac/doc/integrations/webhooks"
EVENTS = ("user.registered", "user.updated", "attempt.complete", "learningRecord.updated", "learningRecord.deleted")


class SynapPATCredential(BaseModel):
    model_config = ConfigDict(title="Synap Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "api_key", "x-credential-url": AUTH_DOC,
            "x-credential-instructions": "In your Synap portal, open Settings → Automations → API and create a personal access token. Paste the entire token, including p:, and your Portal ID. V3 API access requires a Business or Enterprise plan. NoClick reads your user groups to check the connection; the token acts as its issuing administrator."})
    credential_type: Literal["synap_pat"] = Field("synap_pat", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token", json_schema_extra={"ui:widget": "password"})
    portal_id: str = Field(..., min_length=1, max_length=128, title="Portal ID", description="Your Synap organisation's Portal ID, sent as X-Syn-Portal-Id.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value

    @field_validator("portal_id")
    @classmethod
    def portal(cls, value):
        return resource_id(value)


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Use a single Synap resource ID")
    return value


def text(title, required=False, **kwargs):
    if title == "User group ID":
        kwargs["json_schema_extra"] = {"x-dynamic-options": {"field_name": "group_id", "searchable": True, "allow_custom": True}}
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1, **kwargs))


def identifier(title):
    return text(title, True, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


PAGE = {"limit": (int, Field(50, ge=1, le=200, title="Page size")),
        "offset": (int, Field(0, ge=0, le=1000000, title="Page offset"))}
USER = {"user_id": identifier("User ID")}
GROUP = {"group_id": identifier("User group ID")}
RECORD = {"record_id": identifier("Learning record ID")}
NAME = {"name": text("Name", True)}


@dataclass(frozen=True)
class Action:
    label: str
    method: str
    path: str
    kind: str
    fields: dict


ACTIONS = {
    "list_users": Action("Find Users", "GET", "/users", "User", {**PAGE, "email": text("Email address"), "search": text("Search"), "group_id": text("User group ID")}),
    "get_user": Action("Get User", "GET", "/users/{user_id}", "User", USER),
    "create_user": Action("Register User", "POST", "/user-registrations", "UserRegistration", {**NAME, "email": text("Email address", True), "password": (str, Field(..., min_length=8, title="Initial password", description="At least one uppercase letter, lowercase letter and digit.", json_schema_extra={"ui:widget": "password"})), "group_id": text("User group ID"), "welcome_email_disabled": (bool, Field(True, title="Disable welcome email"))}),
    "update_user": Action("Update User", "PATCH", "/users/{user_id}", "User", {**USER, "name": text("Name"), "email": text("Email address"), "external_id": text("External ID"), "is_disabled": (Optional[bool], Field(None, title="Disable account"))}),
    "list_groups": Action("List User Groups", "GET", "/user-groups", "UserGroup", {**PAGE, "search": text("Search group names")}),
    "get_group": Action("Get User Group", "GET", "/user-groups/{group_id}", "UserGroup", GROUP),
    "create_group": Action("Create User Group", "POST", "/user-groups", "UserGroup", {**NAME, "description": text("Description"), "user_type_id": identifier("User type ID")}),
    "update_group": Action("Update User Group", "PATCH", "/user-groups/{group_id}", "UserGroup", {**GROUP, **NAME, "description": text("Description")}),
    "add_user_to_group": Action("Add User to Group", "POST", "/user-groups/{group_id}/relationships/users", "User", {**GROUP, **USER}),
    "remove_user_from_group": Action("Remove User from Group", "DELETE", "/user-groups/{group_id}/relationships/users", "User", {**GROUP, **USER}),
    "invite_user_to_group": Action("Invite User to Group", "POST", "/user-groups/{group_id}/relationships/users", "Invite", {**GROUP, "email": text("Email address", True), "name": text("Name"), "personal_message": text("Personal message")}),
    "list_exams": Action("List Exams", "GET", "/exam-v-2s", "ExamV2", {**PAGE, "search": text("Search exams")}),
    "get_exam": Action("Get Exam", "GET", "/exam-v-2s/{exam_id}", "ExamV2", {"exam_id": identifier("Exam ID")}),
    "list_attempts": Action("List Attempts", "GET", "/attempts", "Attempt", {**PAGE, "exam_id": text("Exam ID"), "user_id": text("User ID"), "is_completed": (Optional[bool], Field(None, title="Completed only"))}),
    "get_attempt": Action("Get Attempt", "GET", "/attempts/{attempt_id}", "Attempt", {"attempt_id": identifier("Attempt ID")}),
    "get_assignment": Action("Get Assignment", "GET", "/assignments/{assignment_id}", "Assignment", {"assignment_id": identifier("Assignment ID")}),
    "get_learning_record": Action("Get Learning Record", "GET", "/learning-records/{record_id}", "LearningRecord", RECORD),
    "create_learning_record": Action("Create Learning Record", "POST", "/learning-records", "LearningRecord", {**USER, **NAME, "achieved_on": text("Achieved on", True), "score": (Optional[float], Field(None, ge=0, le=100, title="Score (percent)")), "visible_to_student": (bool, Field(True, title="Visible to student"))}),
    "update_learning_record": Action("Update Learning Record", "PATCH", "/learning-records/{record_id}", "LearningRecord", {**RECORD, **NAME, "achieved_on": text("Achieved on"), "score": (Optional[float], Field(None, ge=0, le=100, title="Score (percent)")), "visible_to_student": (Optional[bool], Field(None, title="Visible to student"))}),
    "delete_learning_record": Action("Delete Learning Record", "DELETE", "/learning-records/{record_id}", "LearningRecord", RECORD),
}


class ActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


MODELS = {}
for action_name, action in ACTIONS.items():
    model = create_model("Synap" + "".join(x.title() for x in action_name.split("_")) + "Config", __base__=ActionConfig, __module__=__name__,
        operation=(Literal[action_name], Field(action_name, title=action.label, json_schema_extra={"ui:hidden": True, "x-display-name": action.label, "x-is-trigger": False})), **action.fields)
    MODELS[action_name] = model
    globals()[model.__name__] = model


class SynapOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Synap Event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Synap Event"})
    event_type: Literal[*EVENTS] = Field("user.registered", title="Event", description="User registered or updated, attempt completed after marking, or learning record updated or deleted.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


SynapConfig = Annotated[Union[tuple(MODELS.values()) + (SynapOnEventConfig,)], Field(discriminator="operation")]


class SynapNodeConfig(NodeConfig[SynapConfig, SynapPATCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k not in {"password", "basicAuth", "loginCode"}}
    return value


class SynapNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-synap"
    connection_evidence = ConnectionEvidence(field="group_id", noun="user groups")
    edit_examples = ["Find a learner by email", "Add this user to a study group", "Record a learner's external qualification", "When a learner completes an attempt, notify our team"]

    @classmethod
    def get_config_model(cls):
        return SynapNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = credential if isinstance(credential, SynapPATCredential) else SynapPATCredential.model_validate(credential)
        headers = {"Authorization": "Bearer " + credential.api_token, "X-Syn-Portal-Id": credential.portal_id,
                   "Accept": "application/vnd.api+json"}
        if body is not None:
            headers["Content-Type"] = "application/vnd.api+json"
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body, headers=headers)
        except httpx.HTTPError:
            raise ValueError("Synap request did not finish; inspect writes before retrying") from None
        if response.is_error or response.is_redirect:
            data = (body or {}).get("data")
            attributes = data.get("attributes", {}) if isinstance(data, dict) else {}
            private = (credential.api_token, attributes.get("password"), (attributes.get("basicAuth") or {}).get("password"))
            try:
                errors = response.json().get("errors", [])
                for secret in private:
                    if secret:
                        errors = _redact(errors, secret)
                detail = json.dumps(errors)
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"Synap HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return {"acknowledged": True, "http_status": 204}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Synap returned an unreadable response; inspect writes before retrying") from None
        if not isinstance(payload, dict) or "errors" in payload or "data" not in payload:
            raise ValueError("Synap response did not contain JSON:API data")
        # 202 is a background job acknowledgement, never a completed mutation.
        return {**payload, "http_status": response.status_code, "pending": response.status_code == 202}

    @classmethod
    def _wire(cls, op):
        action = ACTIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = action.path
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(resource_id(values.pop(key)), safe=""))
        params, body = {}, None
        if op.operation.startswith("list_"):
            # OpenAPI form/explode defaults: page's properties are separate keys.
            params.update(limit=values.pop("limit"), offset=values.pop("offset"))
            filters = {}
            if "search" in values:
                if op.operation == "list_groups":
                    filters["search"] = values.pop("search")
                else:
                    params["search"] = values.pop("search")
            if op.operation == "list_users":
                filters = {"userGroupType": "allUsers", **({"emailAddress": values["email"]} if "email" in values else {}), **({"userGroup": values["group_id"]} if "group_id" in values else {})}
                # The users filter is explicitly explode=false in the contract.
                params["filter"] = ",".join(str(x).lower() if isinstance(x, bool) else str(x) for pair in filters.items() for x in pair)
            else:
                mappings = {"list_attempts": {"exam_id": "examId", "user_id": "owner", "is_completed": "isCompleted"}}
                filters.update({target: values[source] for source, target in mappings.get(op.operation, {}).items() if source in values})
                # The attempts filter also explicitly sets explode=false.
                if op.operation == "list_attempts" and filters:
                    params["filter"] = ",".join(str(x).lower() if isinstance(x, bool) else str(x) for pair in filters.items() for x in pair)
                else:
                    params.update({key: str(value).lower() if isinstance(value, bool) else value for key, value in filters.items()})
        elif action.method in {"POST", "PATCH", "DELETE"}:
            if op.operation in {"add_user_to_group", "remove_user_from_group"}:
                body = {"data": [{"type": "User", "id": resource_id(values["user_id"])}]}
            elif op.operation == "invite_user_to_group":
                body = {"data": [{"type": "Invite", "attributes": {({"personal_message": "personalMessage"}.get(k, k)): v for k, v in values.items()}}]}
            elif action.method != "DELETE":
                mappings = {"email": "emailAddress", "external_id": "externalId", "is_disabled": "isDisabled", "achieved_on": "achievedOn", "visible_to_student": "visibleToStudent", "welcome_email_disabled": "welcomeEmailDisabled"}
                attrs = {mappings.get(k, k): v for k, v in values.items() if k not in {"user_id", "group_id", "user_type_id"}}
                data = {"type": action.kind, "attributes": attrs}
                if action.method == "PATCH":
                    data["id"] = path.rsplit("/", 1)[1]
                if op.operation == "create_group":
                    data["relationships"] = {"userType": {"data": {"type": "UserType", "id": resource_id(values["user_type_id"])}}}
                elif op.operation == "create_learning_record":
                    data["relationships"] = {"owner": {"data": {"type": "User", "id": resource_id(values["user_id"])}}}
                elif op.operation == "create_user":
                    data["relationships"] = {"userGroups": {"data": [{"type": "UserGroup", "id": resource_id(values["group_id"])}]}} if "group_id" in values else {}
                if op.operation == "update_user" and not attrs:
                    raise ValueError("Provide a user field to update")
                body = {"data": data}
        return action, path, params or None, body

    async def execute(self, inputs):
        if not self.config or self.config.credentials is None:
            raise ValueError("Connect a Synap personal access token and Portal ID")
        op = self.config.config
        if isinstance(op, SynapOnEventConfig):
            payload = self.node_data.get("config", {}).get("_triggerPayload")
            if payload is None:
                return self.no_event_output("Waiting for a Synap event")
            output = self.resolve_trigger_payload(payload, {"event_type": op.event_type})
        else:
            action, path, params, body = self._wire(op)
            result = await self._request(self.config.credentials, action.method, path, params=params, body=body)
            output = {"status": "success", "operation": op.operation, **result}
            if op.operation.startswith("list_"):
                if not isinstance(result.get("data"), list):
                    raise ValueError("Synap did not return a list")
                output["next_offset"] = op.offset + len(result["data"]) if len(result["data"]) == op.limit else None
            elif action.method == "GET" and not isinstance(result.get("data"), dict):
                raise ValueError("Synap did not return a resource")
        output = _redact(output, self.config.credentials.api_token)
        await self.emit(output)
        return output

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, *, page_token=None, search=None):
        if field_name != "group_id":
            return []
        offset = int(page_token or 0)
        op = MODELS["list_groups"](offset=offset, search=search)
        action, path, params, body = cls._wire(op)
        result = await cls._request(credential_data, action.method, path, params=params)
        rows = result.get("data")
        if not isinstance(rows, list):
            raise ValueError("Synap did not return user groups")
        return {"options": [{"value": resource_id(row["id"]), "label": str(row.get("attributes", {}).get("name") or row["id"])} for row in rows],
                "next_page_token": str(offset + len(rows)) if len(rows) == op.limit else None}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = config.get("event_type", "user.registered")
        if event not in EVENTS:
            raise ValueError("Choose a supported Synap event")
        secret = secrets.token_urlsafe(32)
        result = await cls._request(credential, "POST", "/webhook-subscriptions", body={"data": {"type": "WebhookSubscription", "attributes": {
            "eventName": event, "targetUrl": webhook_url, "name": f"NoClick {node_id}", "active": True,
            "basicAuth": {"username": "noclick", "password": secret}}}})
        data = result.get("data", {})
        if result.get("pending") or data.get("type") != "WebhookSubscription" or not data.get("id"):
            raise ValueError("Synap did not confirm a webhook subscription; inspect before retrying")
        return {"external_webhook_id": resource_id(data["id"]), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if config.get("external_webhook_id"):
            await cls._request(credential, "DELETE", "/webhook-subscriptions/" + quote(resource_id(str(config["external_webhook_id"])), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type", "user.registered")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Synap documents HTTP Basic authentication, not a body signature.
        secret = config.get("signing_secret")
        if not secret:
            return False
        header = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        expected = "Basic " + base64.b64encode(("noclick:" + secret).encode()).decode()
        return isinstance(header, str) and hmac.compare_digest(header.encode(), expected.encode())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = (payload.get("meta") or {}).get("eventName")
        return event is None or event == config.get("event_type", "user.registered")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": "on_event", "event_type": config.get("event_type", "user.registered"),
                "data": {k: v for k, v in payload.items() if k != "_webhook"}}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event_type") not in EVENTS or not isinstance(output.get("data"), dict):
            return super().resolve_agent_event(output)
        data, event = output["data"], output["event_type"]
        if event.startswith("learningRecord."):
            user, record = data.get("user", {}), data.get("learningRecord", {})
            uid, rid = user.get("id"), record.get("objectId")
            if not uid or not rid:
                return None
            title = f"{user.get('name') or uid}: learning record {event.split('.')[-1]}"
            text = f"Synap: {title}\nLearner: {user.get('email') or uid} (user_id={uid})\nRecord: {record.get('name') or rid} (record_id={rid})\nPortal: {data.get('portal', {}).get('id', '')}\nAt: {data.get('meta', {}).get('timestamp', '')}"
            if event == "learningRecord.updated":
                text += f"\nScore: {record.get('score', 'unavailable')}; achieved: {record.get('achievedOn', '')}\nChanged fields: {', '.join(data.get('updatedFields', []))}\nTo act: get_learning_record record_id={rid}; get_user user_id={uid}."
            else:
                text += f"\nTo act: get_user user_id={uid}. The learning record was deleted."
            return {"text": text, "title": title, "conversation_key": str(uid)}
        if event == "attempt.complete":
            user, attempt, test = data.get("user", {}), data.get("attempt", {}), data.get("test", {})
            uid, aid = user.get("id"), attempt.get("id")
            if not uid or not aid:
                return None
            title = f"{user.get('name') or uid} completed {test.get('title') or 'an attempt'}"
            lines = [f"Synap: {title}", f"Learner: {user.get('email') or uid} (user_id={uid})", f"Attempt: attempt_id={aid}; test_id={test.get('id', '')}",
                     f"Score: {attempt.get('score', data.get('score', 'unavailable'))}; completed: {attempt.get('timeCompleted', data.get('timeCompleted', ''))}",
                     f"Portal: {data.get('portal', {}).get('id', '')}", f"To act: get_attempt attempt_id={aid}; get_user user_id={uid}."]
            return {"text": "\n".join(lines), "title": title, "conversation_key": str(aid)}
        uid = data.get("objectId")
        if not uid:
            return None
        title = f"{data.get('name') or uid}: {'registered' if event == 'user.registered' else 'account updated'}"
        return {"text": f"Synap: {title}\nEmail: {data.get('email', '')}\nUser: user_id={uid}\nGroups: {', '.join(data.get('usergroups', []))}\nRegistered: {data.get('timeRegistered', '')}\nAttributes: {json.dumps(data.get('customAttributes', {}))}\nPrevious values: {json.dumps(data.get('previousValues', {}))}\nTo act: get_user or update_user user_id={uid}.", "title": title, "conversation_key": str(uid)}
