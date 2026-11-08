"""GoTo Training scheduling, registration and reporting actions.

Contract: https://developer.goto.com/resources/GoToTrainingV1.yml (1.0.0).
Each action sends exactly one request; redirects are never followed.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.go_to_training_operations import OPERATIONS
from nodes.scopes.go_to_training import GO_TO_TRAINING_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.getgo.com/G2T/rest"
IDENTITY = "https://api.getgo.com/identity/v1/Users/me"


class GoToTrainingOAuthCredential(BaseModel):
    model_config = ConfigDict(title="GoTo Training Account", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "go_to_training",
            "x-oauth-scopes": GO_TO_TRAINING_SCOPES.declared_scopes(),
            "x-credential-url": "https://developer.goto.com/guides/Get%20Started/02_HOW_createClient/",
            "x-credential-instructions": "Connect your GoTo account. Your OAuth client must have GoTo Training enabled. A GoTo Training organizer license is required for training operations."})
    credential_type: Literal["go_to_training_oauth"] = Field("go_to_training_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Expires At")
    scope: str | None = None
    _secrets = field_validator("access_token", "refresh_token", mode="before")(clean_secret)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DateTimeRange(_Closed):
    startDate: str = Field(..., title="Start Date", json_schema_extra={"format": "date-time"})
    endDate: str = Field(..., title="End Date", json_schema_extra={"format": "date-time"})

    @model_validator(mode="after")
    def ordered(self):
        start = datetime.fromisoformat(self.startDate.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.endDate.replace("Z", "+00:00"))
        if not start.tzinfo or not end.tzinfo or start >= end:
            raise ValueError("Use timezone-aware start and end dates with end after start")
        return self


class RegistrationSettings(_Closed):
    disableConfirmationEmail: bool = Field(..., strict=True, title="Disable Confirmation Email")
    disableWebRegistration: bool = Field(..., strict=True, title="Disable Web Registration")


class TrainingReqCreate(_Closed):
    name: str = Field(..., min_length=1, title="Name")
    description: str | None = None
    timeZone: str = Field(..., title="Time Zone", description="IANA time zone, for example America/New_York.")
    times: list[DateTimeRange] = Field(..., min_length=1, title="Session Times")
    registrationSettings: RegistrationSettings | None = None
    organizers: list[int] | None = Field(None, title="Co-organizer Keys")

    @field_validator("timeZone")
    @classmethod
    def zone(cls, value):
        ZoneInfo(value)
        return value


class TrainingNameDescription(_Closed):
    name: str = Field(..., min_length=1, title="Name")
    description: str | None = None


class TrainingOrganizers(_Closed):
    organizers: list[int] = Field(..., title="Organizer Keys")
    notifyOrganizers: bool | None = Field(None, strict=True, title="Notify Organizers", description="Send email notifying organizers of the change.")


class RegistrantReqCreate(_Closed):
    email: str = Field(..., min_length=3, title="Email")
    givenName: str = Field(..., min_length=1, title="First Name")
    surname: str = Field(..., min_length=1, title="Last Name")

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Supply a registrant email address")
        return value


class TrainingTimes(_Closed):
    timeZone: str = Field(..., title="Time Zone")
    times: list[DateTimeRange] = Field(..., min_length=1, title="Session Times")
    notifyRegistrants: bool | None = Field(None, strict=True, title="Notify Registrants", description="GoTo defaults to sending email if omitted.")
    notifyTrainers: bool | None = Field(None, strict=True, title="Notify Trainers", description="GoTo defaults to sending email if omitted.")
    _zone = field_validator("timeZone")(TrainingReqCreate.zone.__func__)


BODY_MODELS = {cls.__name__: cls for cls in (TrainingReqCreate, TrainingNameDescription, TrainingOrganizers, RegistrantReqCreate, RegistrationSettings, TrainingTimes, DateTimeRange)}
PATH_FIELDS = {"organizerKey": "organizer_key", "trainingKey": "training_key", "registrantKey": "registrant_key", "sessionKey": "session_key"}


def _make_config(name, op):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": op["label"], "x-is-trigger": False, "x-operation-kind": "read" if op["method"] == "GET" or name == "list_sessions_by_date" else "write"}, description=op["description"]))}
    for raw in re.findall(r"{(\w+)}", op["path"]):
        field = PATH_FIELDS[raw]
        extra = {"x-dynamic-options": {"field_name": "organizer_key", "allow_custom": True}} if raw == "organizerKey" else {}
        fields[field] = (str, Field(..., title=field.replace("_", " ").title(), pattern=r"^[0-9]+$", json_schema_extra=extra))
    if op["body"]:
        fields["body"] = (BODY_MODELS[op["body"]], Field(..., title="Details", description=op["description"]))
    return create_model("GoToTraining" + "".join(v.title() for v in name.split("_")) + "Config", __base__=_Closed, __module__=__name__, **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({cls.__name__: cls for cls in CONFIG_MODELS.values()})
GoToTrainingConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class GoToTrainingNodeConfig(NodeConfig[GoToTrainingConfig, GoToTrainingOAuthCredential]):
    pass


async def _request(token, method, url, body=None):
    async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
        kwargs = {"json": body} if body is not None else {}
        response = await client.request(method, url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


class GoToTrainingNode(WorkflowNode):
    integration_type = "automation-go-to-training"
    scope_registry = GO_TO_TRAINING_SCOPES
    connection_evidence = ConnectionEvidence(field="organizer_key", noun="GoTo organizer account")

    @classmethod
    def get_config_model(cls):
        return GoToTrainingNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.go_to_training_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="go_to_training")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "organizer_key":
            raise ValueError("Unknown GoTo Training picker")
        data = await cls.freshen_credential(credential_data)
        identity = await _request(data["access_token"], "GET", IDENTITY)
        if not isinstance(identity, dict) or not re.fullmatch(r"[0-9]+", str(identity.get("id", ""))):
            raise ValueError("GoTo returned no organizer identity")
        label = identity.get("displayName") or identity.get("userName")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("GoTo returned no organizer name")
        options = [{"value": str(identity["id"]), "label": label}]
        return {"options": [o for o in options if not search or search.casefold() in o["label"].casefold()], "next_page_token": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GoTo Training account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.go_to_training_oauth import refresh_access_token
        credential = self.config.credentials.model_dump()
        await ensure_fresh_oauth_token(credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=refresh_access_token, provider="go_to_training", caller_path="execute")
        config = self.config.config
        op = OPERATIONS[config.operation]
        path = op["path"]
        for raw in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + raw + "}", getattr(config, PATH_FIELDS[raw]))
        body = config.body.model_dump(exclude_none=True) if op["body"] else None
        result = await _request(credential["access_token"], op["method"], BASE + path, body)
        return {"status": "success", "operation": config.operation, "data": result}
