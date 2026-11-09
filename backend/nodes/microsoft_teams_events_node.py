"""Teams webinar automation using delegated Microsoft Graph v1.0.

Work/school accounts in the global cloud only. The catalog excludes application-only
APIs (notably tenant-wide webinar and registration listing), and unpublished actions.
Contract: https://learn.microsoft.com/graph/api/resources/virtualeventwebinar
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft_teams_events import TEAMS_EVENTS_SCOPES

ROOT = "https://graph.microsoft.com/v1.0"
WEBINARS = "/solutions/virtualEvents/webinars"


class TeamsEventsOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Microsoft Teams Events OAuth", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "microsoft",
        "x-oauth-scopes": sorted(TEAMS_EVENTS_SCOPES.declared_scopes()),
        "x-credential-url": "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "x-credential-instructions": "Connect your Microsoft work or school account. Teams webinars require an eligible Teams license and organizer or coorganizer access. Only the Microsoft global cloud is supported.",
    })
    credential_type: Literal["microsoft_teams_events_oauth"] = Field("microsoft_teams_events_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field("", title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field("", title="Token expiry", description="ISO 8601 timestamp, if known.")
    email: str = Field("", title="Account email")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def safe_ids(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if value.strip() in ("", ".", "..") or any(c in value for c in "/\\?#%") or any(ord(c) < 32 for c in value):
                raise ValueError("Paste a single Microsoft Graph resource ID")
        return value

    @model_validator(mode="after")
    def validate_values(self):
        values = self.model_dump()
        if values.get("operation") == "update_webinar" and not any(values.get(k) is not None for k in ("display_name", "description")):
            raise ValueError("Supply a name or description to update")
        if values.get("operation") == "create_webinar":
            try:
                start, end = (datetime.fromisoformat(values[k]) for k in ("start_time", "end_time"))
                if start >= end:
                    raise ValueError("End must follow start")
            except (TypeError, ValueError) as exc:
                raise ValueError("Use ISO 8601 start and end times, with end after start") from exc
        if values.get("answer_input_type") in ("singleChoice", "multiChoice") and not values.get("answer_choices"):
            raise ValueError("Choice questions require answer choices")
        return self


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: str = ""
    collection: bool = False


OPERATIONS = {
    "get_account": Operation("GET", "/me"),
    "list_my_webinars": Operation("GET", WEBINARS + "/getByUserRole(role='{role}')", ("role",), collection=True),
    "get_webinar": Operation("GET", WEBINARS + "/{webinar_id}", ("webinar_id",)),
    "create_webinar": Operation("POST", WEBINARS, ("display_name", "description", "start_time", "end_time", "time_zone", "audience"), "webinar"),
    "update_webinar": Operation("PATCH", WEBINARS + "/{webinar_id}", ("webinar_id", "display_name", "description"), "webinar_update"),
    "create_presenter": Operation("POST", WEBINARS + "/{webinar_id}/presenters", ("webinar_id", "user_id", "tenant_id"), "presenter"),
    "update_presenter": Operation("PATCH", WEBINARS + "/{webinar_id}/presenters/{presenter_id}", ("webinar_id", "presenter_id", "bio", "company", "job_title"), "presenter_update"),
    "get_registration_configuration": Operation("GET", WEBINARS + "/{webinar_id}/registrationConfiguration", ("webinar_id",)),
    "list_registration_questions": Operation("GET", WEBINARS + "/{webinar_id}/registrationConfiguration/questions", ("webinar_id",), collection=True),
    "create_registration_question": Operation("POST", WEBINARS + "/{webinar_id}/registrationConfiguration/questions", ("webinar_id", "display_name", "answer_input_type", "answer_choices", "is_required"), "question"),
    "delete_registration_question": Operation("DELETE", WEBINARS + "/{webinar_id}/registrationConfiguration/questions/{question_id}", ("webinar_id", "question_id")),
    "get_registration": Operation("GET", WEBINARS + "/{webinar_id}/registrations/{registration_id}", ("webinar_id", "registration_id")),
    "list_sessions": Operation("GET", WEBINARS + "/{webinar_id}/sessions", ("webinar_id",), collection=True),
    "get_session": Operation("GET", WEBINARS + "/{webinar_id}/sessions/{session_id}", ("webinar_id", "session_id")),
}


def _model(name, spec):
    title = name.replace("_", " ").title()
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": title, "x-category": "Account" if name == "get_account" else "Webinars", "x-is-trigger": False}))}
    for key in spec.fields:
        if key == "role":
            fields[key] = (Literal["organizer", "coOrganizer"], Field("organizer", title="Your role"))
        elif key == "audience":
            fields[key] = (Literal["everyone", "organization"], Field("organization", title="Audience"))
        elif key == "answer_input_type":
            fields[key] = (Literal["text", "multilineText", "singleChoice", "multiChoice", "boolean"], Field("text", title="Answer type"))
        elif key == "answer_choices":
            fields[key] = (list[str], Field(default_factory=list, max_length=100, title="Answer choices"))
        elif key == "is_required":
            fields[key] = (bool, Field(False, title="Required answer"))
        elif name == "update_webinar" and key in ("display_name", "description"):
            fields[key] = (str | None, Field(None, min_length=1, max_length=10000, title=key.replace("_", " ").title()))
        else:
            fields[key] = (str, Field(..., min_length=1, max_length=10000 if key in ("description", "bio") else 512, title=key.replace("_", " ").title(), description={"start_time": "Local ISO 8601 date and time, for example 2026-12-01T10:00:00", "end_time": "Local ISO 8601 date and time after the start", "time_zone": "Windows time zone, for example Pacific Standard Time"}.get(key)))
    if spec.collection:
        fields["next_link"] = (str | None, Field(None, title="Next page link", description="Use next_link returned by this operation for the same webinar and role."))
    return create_model("TeamsEvents" + name.title().replace("_", "") + "Config", __base__=Input, **fields)


MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
TeamsEventsOperation = Annotated[Union[tuple(MODELS.values())], Field(discriminator="operation")]


class TeamsEventsNodeConfig(NodeConfig[TeamsEventsOperation, TeamsEventsOAuthCredential]):
    pass


def _typed(kind, **values):
    return {"@odata.type": "#microsoft.graph." + kind, **values}


def _body(spec, values):
    def text(value):
        return _typed("itemBody", contentType="text", content=value)
    if spec.body in ("webinar", "webinar_update"):
        body = _typed("virtualEventWebinar")
        if values.get("display_name") is not None:
            body["displayName"] = values["display_name"]
        if values.get("description") is not None:
            body["description"] = text(values["description"])
        if spec.body == "webinar":
            body.update(audience=values["audience"], startDateTime=_typed("dateTimeTimeZone", dateTime=values["start_time"], timeZone=values["time_zone"]), endDateTime=_typed("dateTimeTimeZone", dateTime=values["end_time"], timeZone=values["time_zone"]))
        return body
    if spec.body == "presenter":
        return _typed("virtualEventPresenter", identity=_typed("communicationsUserIdentity", id=values["user_id"], tenantId=values["tenant_id"]))
    if spec.body == "presenter_update":
        return _typed("virtualEventPresenter", presenterDetails=_typed("virtualEventPresenterDetails", bio=text(values["bio"]), company=values["company"], jobTitle=values["job_title"]))
    if spec.body == "question":
        body = _typed("virtualEventRegistrationCustomQuestion", displayName=values["display_name"], answerInputType=values["answer_input_type"], isRequired=values["is_required"])
        if values["answer_choices"]:
            body["answerChoices"] = values["answer_choices"]
        return body
    return None


class MicrosoftTeamsEventsNode(WorkflowNode):
    integration_type = "automation-microsoft-teams-events"
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = TEAMS_EVENTS_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_my_webinars", noun="webinars", identity_operation="get_account")
    edit_examples = ["Create a Teams webinar", "Find webinars I organize", "Add a webinar presenter", "Read a webinar registration or session"]

    @classmethod
    def get_config_model(cls):
        return TeamsEventsNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, TeamsEventsNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Microsoft work or school account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        credential = self.config.credentials
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id, credential=data, refresh=refresh_access_token, provider="microsoft", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in data:
                setattr(credential, key, data[key])
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"})
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        url = ROOT + path
        if spec.collection and values.get("next_link"):
            continuation = urlsplit(values["next_link"])
            expected = urlsplit(url)
            if (continuation.scheme, continuation.netloc, continuation.path) != (expected.scheme, expected.netloc, expected.path) or continuation.fragment:
                raise ValueError("Next page link must belong to this Microsoft Graph operation")
            url = values["next_link"]
        kwargs = {"headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
        body = _body(spec, values)
        if body is not None:
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(spec.method, url, **kwargs)
        if response.is_error:
            try:
                error = response.json().get("error", {})
                message = error.get("message", "Request rejected") if isinstance(error, dict) else str(error)
            except (ValueError, AttributeError):
                message = response.reason_phrase
            # Do not return headers, request bodies or credentials in provider errors.
            for secret in (token, credential.refresh_token):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"Microsoft Teams Events ({response.status_code}): {message}")
        result = {"status": "success", "operation": config.operation}
        if response.status_code == 204 or not response.content:
            return result
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Microsoft Graph returned an unexpected response")
        if spec.collection:
            if not isinstance(payload.get("value"), list):
                raise ValueError("Microsoft Graph returned no collection")
            result.update(items=payload["value"], count=len(payload["value"]))
            if payload.get("@odata.nextLink"):
                # Expose continuation metadata without ever fetching an arbitrary URL.
                result["next_link"] = payload["@odata.nextLink"]
        else:
            result["data"] = payload
        return result
