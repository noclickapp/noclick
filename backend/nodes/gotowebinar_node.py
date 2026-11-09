"""GoTo Webinar scheduling, registration and session reports.

Each operation maps to one published v1 API operation and makes one request.
OAuth client configuration selects GoTo Webinar product access.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.gotowebinar_operations import OPERATIONS
from nodes.scopes.gotowebinar import GOTOWEBINAR_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.getgo.com/G2W/rest"
IDENTITY = "https://api.getgo.com/identity/v1/Users/me"


class GoToWebinarOAuthCredential(BaseModel):
    model_config = ConfigDict(title="GoTo Webinar Account", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "gotowebinar",
            "x-oauth-scopes": GOTOWEBINAR_SCOPES.declared_scopes(),
            "x-credential-url": "https://developer.goto.com/guides/Get%20Started/02_HOW_createClient/",
            "x-credential-instructions": "Connect your GoTo account with a GoTo Webinar organizer license. Enable GoTo Webinar on the OAuth client. For manual connection, paste the access and refresh tokens from the documented OAuth token exchange; access tokens expire after one hour."})
    credential_type: Literal["gotowebinar_oauth"] = Field("gotowebinar_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Expires At")
    scope: str | None = None
    _secrets = field_validator("access_token", "refresh_token", mode="before")(clean_secret)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not parsed.tzinfo:
        raise ValueError("Use an ISO8601 date and time with a timezone")
    return parsed


class DateTimeRange(_Closed):
    startTime: str = Field(..., title="Start Time", json_schema_extra={"format": "date-time"})
    endTime: str = Field(..., title="End Time", json_schema_extra={"format": "date-time"})

    @model_validator(mode="after")
    def ordered(self):
        if _instant(self.startTime) >= _instant(self.endTime):
            raise ValueError("End time must be after start time")
        return self


class WebinarReqUpdate(_Closed):
    subject: str | None = Field(None, min_length=1, max_length=128, title="Subject")
    description: str | None = Field(None, max_length=2048, title="Description")
    timeZone: str | None = Field(None, title="Time Zone", description="IANA time zone such as America/New_York.")
    times: list[DateTimeRange] | None = Field(None, min_length=1, title="Session Times")
    locale: Literal["en_US", "de_DE", "es_ES", "fr_FR", "it_IT", "zh_CN"] | None = None

    @field_validator("timeZone")
    @classmethod
    def zone(cls, value):
        if value is not None:
            ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide at least one webinar detail to update")
        return self


class WebinarReqCreate(_Closed):
    subject: str = Field(..., min_length=1, max_length=128, title="Subject")
    description: str | None = Field(None, max_length=2048, title="Description")
    timeZone: str | None = Field(None, title="Time Zone")
    times: list[DateTimeRange] = Field(..., min_length=1, title="Session Times")
    type: Literal["single_session", "series"] = Field("single_session", title="Webinar Type")
    isPasswordProtected: bool = Field(False, strict=True, title="Password Protected")
    _zone = field_validator("timeZone")(WebinarReqUpdate.zone.__func__)

    @model_validator(mode="after")
    def session_count(self):
        if (self.type == "single_session" and len(self.times) != 1) or (self.type == "series" and len(self.times) < 2):
            raise ValueError("A single session needs one time range; a series needs two or more")
        return self


class RegistrantQAResponse(_Closed):
    questionKey: int = Field(..., gt=0, title="Question Key")
    answerKey: int | None = Field(None, gt=0, title="Answer Key")
    responseText: str | None = Field(None, title="Response Text")

    @model_validator(mode="after")
    def answer(self):
        if (self.answerKey is None) == (self.responseText is None):
            raise ValueError("Provide either an answer key or answer text")
        return self


class _Email(_Closed):
    email: str = Field(..., title="Email")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Provide an email address")
        return value


class RegistrantFields(_Email):
    firstName: str = Field(..., min_length=1, title="First Name")
    lastName: str = Field(..., min_length=1, title="Last Name")
    address: str | None = None
    city: str | None = None
    country: str | None = None
    industry: str | None = None
    jobTitle: str | None = None
    numberOfEmployees: str | None = None
    organization: str | None = None
    phone: str | None = None
    purchasingRole: str | None = None
    purchasingTimeFrame: str | None = None
    questionsAndComments: str | None = None
    responses: list[RegistrantQAResponse] | None = None
    source: str | None = None
    state: str | None = None
    zipCode: str | None = None


class PanelistReqCreate(_Email):
    name: str = Field(..., min_length=1, title="Name")


class CoorganizerReqCreate(_Closed):
    external: bool = Field(..., strict=True, title="External Co-organizer")
    email: str | None = None
    givenName: str | None = None
    organizerKey: str | None = Field(None, pattern=r"^[0-9]+$", title="Organizer Key")

    @model_validator(mode="after")
    def details(self):
        if self.external:
            if not self.email or not self.givenName or self.organizerKey is not None:
                raise ValueError("External co-organizers need email and given name only")
            _Email(email=self.email)
        elif not self.organizerKey or self.email is not None or self.givenName is not None:
            raise ValueError("Internal co-organizers need an organizer key only")
        return self


BODY_MODELS = {c.__name__: c for c in (WebinarReqCreate, WebinarReqUpdate, RegistrantFields, CoorganizerReqCreate, PanelistReqCreate)}
PATH_FIELDS = {"organizerKey": "organizer_key", "webinarKey": "webinar_key", "sessionKey": "session_key", "registrantKey": "registrant_key", "coorganizerKey": "coorganizer_key", "panelistKey": "panelist_key"}


class _Operation(_Closed):
    @model_validator(mode="after")
    def dates(self):
        start, end = getattr(self, "fromTime", None), getattr(self, "toTime", None)
        if start and end and _instant(start) >= _instant(end):
            raise ValueError("To time must be after from time")
        return self


def _make_config(name, op):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True,
        "x-display-name": name.replace("_", " ").title(), "x-is-trigger": False,
        "x-operation-kind": "read" if op["method"] == "GET" else "write"}))}
    for raw in re.findall(r"{(\w+)}", op["path"]):
        field = PATH_FIELDS[raw]
        extra = {"x-dynamic-options": {"field_name": "organizer_key", "allow_custom": True}} if raw == "organizerKey" else {}
        fields[field] = (str, Field(..., title=field.replace("_", " ").title(), pattern=r"^[0-9]+$", json_schema_extra=extra))
    for param in op["query"]:
        typ = {"string": str, "boolean": bool, "integer": int}[param["type"]]
        kwargs = {"title": re.sub(r"([a-z])([A-Z])", r"\1 \2", param["name"]).title()}
        if param["type"] == "boolean":
            kwargs["strict"] = True
            kwargs["description"] = "Send notification email only when explicitly enabled." if param["name"] != "external" else "Select external co-organizer."
        if param.get("format") == "date-time":
            kwargs["json_schema_extra"] = {"format": "date-time"}
        required = param.get("required", False)
        fields[param["name"]] = (typ if required else typ | None, Field(... if required else None, **kwargs))
    if op["body"]:
        schema = op["body"]
        array = schema.get("type") == "array"
        model = BODY_MODELS[(schema["items"] if array else schema)["$ref"].split("/")[-1]]
        fields["body"] = (list[model] if array else model, Field(..., title="Details", description="For updates supply the complete session definition; omitted details may be replaced. Registration and panelist/co-organizer creation may send provider email.", **({"min_length": 1} if array else {})))
    return create_model("GoToWebinar" + "".join(s.title() for s in name.split("_")) + "Config", __base__=_Operation, __module__=__name__, **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({c.__name__: c for c in CONFIG_MODELS.values()})
GoToWebinarConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class GoToWebinarNodeConfig(NodeConfig[GoToWebinarConfig, GoToWebinarOAuthCredential]):
    pass


async def _request(token, method, url, *, body=None, params=None, accept="application/json", statuses=(200,)):
    async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
        kwargs = {"json": body} if body is not None else {}
        response = await client.request(method, url, headers={"Authorization": "Bearer " + token, "Accept": accept}, params=params, **kwargs)
    response.raise_for_status()
    if response.status_code not in statuses:
        raise ValueError("GoTo Webinar returned an unexpected success status")
    if response.status_code in (202, 204) or not response.content:
        return None
    return response.json()


class GoToWebinarNode(WorkflowNode):
    integration_type = "automation-gotowebinar"
    credential_provider_labels = {"gotowebinar": "GoTo Webinar"}
    scope_registry = GOTOWEBINAR_SCOPES
    connection_evidence = ConnectionEvidence(field="organizer_key", noun="GoTo Webinar organizer account")

    @classmethod
    def get_config_model(cls):
        return GoToWebinarNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.gotowebinar_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="gotowebinar")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "organizer_key":
            raise ValueError("Unknown GoTo Webinar choice field")
        credential = GoToWebinarOAuthCredential.model_validate(await cls.freshen_credential(credential_data))
        identity = await _request(credential.access_token, "GET", IDENTITY)
        if not isinstance(identity, dict) or not re.fullmatch(r"[0-9]+", str(identity.get("id", ""))):
            raise ValueError("GoTo returned no organizer identity")
        label = identity.get("displayName") or identity.get("userName")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("GoTo returned no organizer name")
        options = [{"value": str(identity["id"]), "label": label}]
        return {"options": [o for o in options if not search or search.casefold() in o["label"].casefold()], "next_page_token": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GoTo Webinar account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.gotowebinar_oauth import refresh_access_token
        credential = self.config.credentials.model_dump()
        await ensure_fresh_oauth_token(credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=refresh_access_token, provider="gotowebinar", caller_path="execute")
        config = self.config.config
        op = OPERATIONS[config.operation]
        path = op["path"]
        for raw in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + raw + "}", getattr(config, PATH_FIELDS[raw]))
        body = None
        if op["body"]:
            body = [item.model_dump(exclude_none=True) for item in config.body] if isinstance(config.body, list) else config.body.model_dump(exclude_none=True)
        params = {p["name"]: getattr(config, p["name"]) for p in op["query"] if getattr(config, p["name"]) is not None}
        accept = "application/vnd.citrix.g2wapi-v1.1+json" if config.operation == "register_participant" else "application/json"
        data = await _request(credential["access_token"], op["method"], BASE + path, body=body, params=params, accept=accept, statuses=op["statuses"])
        if op["response_kind"] == "array" and not isinstance(data, list):
            raise ValueError("GoTo Webinar returned an invalid list response")
        if op["response_kind"] == "object" and not isinstance(data, dict):
            raise ValueError("GoTo Webinar returned an invalid object response")
        return {"status": "success", "operation": config.operation, "data": data,
            **({"accepted": True, "completion_verified": False} if op["method"] != "GET" else {})}
