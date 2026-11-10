"""Learnifier learners, courses, participation, groups and awards via Admin API 1.3.1.

Routes and payload names follow https://apidocs.learnifier.com/learnifier.json;
Basic key/secret authentication follows https://learnifier.com/api/.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class LearnifierAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Learnifier API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://learnifier.com/api/",
        "x-credential-instructions": "Enter your Learnifier instance address and the API key and secret supplied by your Learnifier administrator. NoClick uses HTTP Basic authentication. Back Office reads require a Back Office API key.",
    })
    credential_type: Literal["learnifier_api_key"] = Field("learnifier_api_key", json_schema_extra={"ui:hidden": True})
    instance: str = Field(..., title="Instance URL", min_length=1, description="Your Learnifier instance, for example https://company.learnifier.com")
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="API Secret", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("instance", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Learnifier instance")
        parts = urlsplit(origin)
        if parts.scheme != "https" or parts.port is not None:
            raise ValueError("Use your Learnifier HTTPS instance without a port")
        return origin

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name, key=info.field_name == "api_key")
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or (info.field_name == "api_key" and ":" in value):
            raise ValueError("Paste the key or secret without control characters or a Basic header")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


ORG = "/orgunits/{orgid}"
PROJECT = ORG + "/projects/{projectid}"
PARTICIPANT = PROJECT + "/participants/{participantId}"
GROUP = ORG + "/usergroups/{groupid}"
USER_FIELDS = ("primaryEmail", "username", "externalId", "firstName", "lastName", "displayName", "homeOrg", "locale", "hardLock", "manager")
OPERATIONS = {
    "list_organizations": Operation("GET", "/orgunits", "Organizations"),
    "list_users": Operation("GET", ORG + "/users", "Users", ("orgid",), ("limit", "offset")),
    "get_user": Operation("GET", "/users/{userid}", "Users", ("userid",)),
    "find_user_by_email": Operation("GET", "/emailuser", "Users", ("email",), ("email",)),
    "create_user": Operation("POST", "/users", "Users", ("primaryEmail",), body=USER_FIELDS),
    "update_user": Operation("PATCH", "/users/{userid}", "Users", ("userid",), body=USER_FIELDS),
    "list_projects": Operation("GET", ORG + "/projects", "Courses", ("orgid",)),
    "get_project": Operation("GET", PROJECT, "Courses", ("orgid", "projectid")),
    "update_project": Operation("PATCH", PROJECT, "Courses", ("orgid", "projectid"), body=("name", "userTitle", "userDescription", "status", "locale", "timezone")),
    "list_participants": Operation("GET", PROJECT + "/participants", "Participation", ("orgid", "projectid"), ("completionStatus", "first_completed_since", "first_activated_since")),
    "create_participant": Operation("POST", PROJECT + "/createParticipant", "Participation", ("orgid", "projectid", "email"), body=("email", "extid", "activate")),
    "update_participant": Operation("PATCH", PARTICIPANT, "Participation", ("orgid", "projectid", "participantId"), body=("completionStatus", "expiration", "externalId")),
    "activate_participant": Operation("POST", PARTICIPANT + "/activate", "Participation", ("orgid", "projectid", "participantId")),
    "reenroll_participant": Operation("POST", PARTICIPANT + "/reenroll", "Participation", ("orgid", "projectid", "participantId")),
    "delete_participant": Operation("DELETE", PARTICIPANT, "Participation", ("orgid", "projectid", "participantId")),
    "list_groups": Operation("GET", ORG + "/usergroups", "Groups", ("orgid",)),
    "create_group": Operation("POST", ORG + "/usergroups", "Groups", ("orgid", "name"), body=("name", "parent", "externalId")),
    "list_group_members": Operation("GET", GROUP + "/members", "Groups", ("orgid", "groupid")),
    "add_group_member": Operation("POST", GROUP + "/members", "Groups", ("orgid", "groupid", "email"), body=("email",)),
    "delete_group_member": Operation("DELETE", GROUP + "/members/{uuid}", "Groups", ("orgid", "groupid", "uuid")),
    "list_awards": Operation("GET", "/awards", "Awards"),
    "list_user_awards": Operation("GET", "/userawards", "Awards", query=("userId", "awardId", "limit", "offset")),
    "create_user_award": Operation("POST", "/userawards", "Awards", ("awardId", "userId"), body=("awardId", "userId", "externalId", "issued", "expiration")),
}
QUERY_NAMES = {"first_completed_since": "filter[firstCompleted][gte]", "first_activated_since": "filter[firstActivation][gte]"}
INTEGERS = {"orgid", "projectid", "participantId", "groupid", "parent", "homeOrg", "limit", "offset"}
BOOLEANS = {"hardLock", "activate"}
TITLES = {"orgid": "Organization ID", "projectid": "Course ID", "participantId": "Participation ID", "userid": "User ID", "userId": "User ID", "groupid": "Group ID", "uuid": "Member User ID", "primaryEmail": "Email", "first_completed_since": "First Completed Since", "first_activated_since": "First Activated Since"}
DATES = {"first_completed_since", "first_activated_since", "issued", "expiration"}


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_values(self):
        for name in DATES:
            value = getattr(self, name, None)
            if value:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError(f"{name} must be an ISO 8601 timestamp") from None
                if parsed.tzinfo is None:
                    raise ValueError(f"{name} must include a timezone")
        for name in ("userid", "uuid", "userId", "awardId"):
            value = getattr(self, name, None)
            if value and (value in {".", ".."} or any(c in value for c in "/\\?#")):
                raise ValueError(f"{name} must be a single resource ID")
        op = getattr(self, "operation", "")
        if op.startswith("update_") and not any(getattr(self, field, None) is not None for field in OPERATIONS[op].body):
            raise ValueError("Provide at least one field to update")
        return self


def config_field(name, required):
    kind = int if name in INTEGERS else bool if name in BOOLEANS else str
    if name == "completionStatus":
        kind = Literal["notAttempted", "incomplete", "completed", "unknown"]
    if name == "status":
        kind = Literal["ACTIVE", "NEW", "DISABLED"]
    kwargs = {"title": TITLES.get(name, name.replace("_", " ").title())}
    if name in INTEGERS:
        kwargs["ge"] = 0 if name == "offset" else 1
    elif kind is str:
        kwargs["min_length"] = 1
    if name == "orgid":
        kwargs["json_schema_extra"] = {"x-dynamic-options": {"field_name": "orgid", "allow_custom": True}}
    if name == "projectid":
        kwargs["json_schema_extra"] = {"x-dynamic-options": {"field_name": "projectid", "depends_on": "orgid", "allow_custom": True}}
    return (kind if required else Optional[kind], Field(... if required else None, **kwargs))


def make_config(name, spec):
    fields = {field: config_field(field, field in spec.required) for field in sorted(set(spec.required + spec.query + spec.body))}
    label = name.replace("_", " ").title()
    return create_model("Learnifier" + label.replace(" ", "") + "Config", __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-category": spec.category, "x-display-name": label, "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class LearnifierOnActivatedParticipantConfig(PollTriggerConfigBase, Input):
    operation: Literal["on_participant_activated"] = Field("on_participant_activated", json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Participant Activated"})
    orgid: int = config_field("orgid", True)[1]
    projectid: int = config_field("projectid", True)[1]
    first_activated_since: Optional[str] = Field(None, title="First Activated Since", description="Optional ISO 8601 timestamp to narrow the monitored participations.")


class LearnifierOnCompletedParticipantConfig(PollTriggerConfigBase, Input):
    operation: Literal["on_course_completed"] = Field("on_course_completed", json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Course Completed"})
    orgid: int = config_field("orgid", True)[1]
    projectid: int = config_field("projectid", True)[1]
    first_completed_since: Optional[str] = Field(None, title="First Completed Since", description="Optional ISO 8601 timestamp to narrow the monitored participations.")


LearnifierOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) + (LearnifierOnActivatedParticipantConfig, LearnifierOnCompletedParticipantConfig)], Discriminator("operation")]


class LearnifierNodeConfig(NodeConfig[LearnifierOperation, LearnifierAPIKeyCredential]):
    pass


class LearnifierNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-learnifier"
    connection_evidence = ConnectionEvidence(field="orgid", noun="organizations", operation="list_organizations")

    @classmethod
    def get_config_model(cls):
        return LearnifierNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.instance + "/api/v1" + path,
                params=params, json=body, auth=httpx.BasicAuth(credential.api_key, credential.api_secret),
                headers={"Accept": "application/json", "Content-Type": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = response.text
            for secret in (credential.api_key, credential.api_secret):
                detail = detail.replace(secret, "[redacted]")
            raise ValueError(f"Learnifier API {response.status_code}: {detail[:1000]}")
        return response.json() if response.content else {"ok": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        credential = LearnifierAPIKeyCredential.model_validate(credential_data)
        if field_name == "orgid":
            response = await cls._request(credential, "GET", "/orgunits")
            rows = response["orgUnits"]
            label = "displayName"
        elif field_name == "projectid":
            context = context or {}
            config = CONFIG_MODELS["list_projects"].model_validate({"operation": "list_projects", "orgid": context.get("orgid")})
            rows = await cls._request(credential, "GET", f"/orgunits/{config.orgid}/projects")
            label = "name"
        else:
            return {"options": []}
        if not isinstance(rows, list):
            raise ValueError("Learnifier returned an unexpected resource list")
        return {"options": [{"value": str(row["id"]), "label": row.get(label) or str(row["id"])}
            for row in rows if row.get("id") is not None and (not search or search.casefold() in str(row.get(label, "")).casefold())]}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("participations")) if config.get("operation", "").startswith("on_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "participations" not in output:
            return super().resolve_agent_event(output)
        rows = output["participations"]
        if not rows:
            return None
        action = "completed the course" if output["operation"] == "on_course_completed" else "was activated in the course"
        lines = [f"User {row.get('userId') or 'unknown'} {action} {row.get('projectId')} (participation {row['id']}, status {row.get('completionStatus') or 'unknown'})." for row in rows[:20]]
        return {"text": "Learnifier, organization " + str(output["orgid"]) + ":\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Learnifier API key and secret")
        config = self.config.config
        operation = config.operation
        if isinstance(config, (LearnifierOnActivatedParticipantConfig, LearnifierOnCompletedParticipantConfig)):
            completed = operation == "on_course_completed"
            params = {"completionStatus": "completed"} if completed else {}
            timestamp_field = "firstCompleted" if completed else "firstActivation"
            since = config.first_completed_since if completed else config.first_activated_since
            if since:
                params[f"filter[{timestamp_field}][gte]"] = since
            rows = await self._request(credential, "GET", f"/orgunits/{config.orgid}/projects/{config.projectid}/participants", params=params)
            if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get("id") is None for row in rows):
                raise ValueError("Learnifier returned an unexpected participation list")
            eligible = [row for row in rows if row.get(timestamp_field)]
            fresh = await self._filter_unseen(eligible, lambda row: str(row["id"]) + ":" + str(row[timestamp_field]))
            return {"operation": operation, "orgid": config.orgid, "projectid": config.projectid, "participations": fresh, "count": len(fresh)}
        spec = OPERATIONS[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for field, value in values.items():
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        params = {QUERY_NAMES.get(field, field): values[field] for field in spec.query if field in values}
        body = {field: values[field] for field in spec.body if field in values} if spec.body else None
        result = await self._request(credential, spec.method, path, params=params or None, body=body)
        return {"status": "success", "operation": operation, "data": result}
