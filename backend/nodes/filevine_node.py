"""Filevine v2 API: fixed, single-request operations using a pasted bearer token.

Contract: https://api.stoplight.io/projects/cHJqOjI0MjAxOA/branches/main/export/reference/FV.App.API.json
Tokens are issued by Filevine Identity; this node does not create or renew them.
Lists return a single page and the provider's pagination metadata.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import jwt
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, AfterValidator, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.filevineapp.com"
CREDENTIAL_TYPE = "filevine_access_token"


def _native_id(value):
    if int(value) > 2147483647:
        raise ValueError("Filevine native IDs must fit a positive int32")
    return value


ResourceId = Annotated[str, Field(min_length=1, max_length=10, pattern=r"^[1-9][0-9]*$", description="Filevine native numeric ID."), AfterValidator(_native_id)]


class FilevineAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Filevine Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.filevine.io/",
            "x-credential-instructions": "Paste a Filevine Identity bearer access token and your Filevine organisation ID. Use the access_token returned by the Identity token exchange, not the personal access token used to obtain it. The token needs fv.api.gateway.access, tenant and filevine.v2.api.* access. Triggers also need filevine.v2.webhooks. Paste only the token without Bearer. Access tokens expire; replace it here when it expires. NoClick does not renew this token.",
        })
    credential_type: Literal["filevine_access_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=16384, title="Access token", json_schema_extra={"ui:widget": "password"})
    org_id: int = Field(..., gt=0, le=2147483647, title="Organisation ID", description="The numeric Filevine organisation ID sent as x-fv-orgid.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the access token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    offset: int = Field(0, ge=0, le=2147483647, description="Zero-based offset. Read next_offset from the previous page; no automatic pagination.")


class _LimitedPage(_Page):
    limit: int = Field(50, ge=1, le=100, description="Maximum records for this page.")


class FilevineListProjectsConfig(_LimitedPage):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    search_term: Optional[str] = Field(None, max_length=500)


class FilevineGetProjectConfig(_Input):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: ResourceId


class FilevineListContactsConfig(_LimitedPage):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    search_term: Optional[str] = Field(None, max_length=500)


class FilevineGetContactConfig(_Input):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceId


class FilevineCreateProjectConfig(_Input):
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    project_type_id: ResourceId
    client_id: ResourceId
    project_name: str = Field(..., min_length=1, max_length=10000)
    description: Optional[str] = Field(None, min_length=1, max_length=10000)


class FilevineUpdateProjectConfig(_Input):
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: ResourceId
    project_name: Optional[str] = Field(None, min_length=1, max_length=10000)
    description: Optional[str] = Field(None, min_length=1, max_length=10000)
    phase_id: Optional[ResourceId] = None

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to update")
        return self


class FilevineCreateContactConfig(_Input):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=10000)
    last_name: Optional[str] = Field(None, min_length=1, max_length=10000)
    primary_email: Optional[str] = Field(None, min_length=3, max_length=320)
    notes: Optional[str] = Field(None, min_length=1, max_length=10000)


class FilevineUpdateContactConfig(_Input):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceId
    first_name: Optional[str] = Field(None, min_length=1, max_length=10000)
    last_name: Optional[str] = Field(None, min_length=1, max_length=10000)
    primary_email: Optional[str] = Field(None, min_length=3, max_length=320)
    notes: Optional[str] = Field(None, min_length=1, max_length=10000)

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to update")
        return self


class FilevineListNotesConfig(_Page):
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})


class FilevineGetNoteConfig(_Input):
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: ResourceId


class FilevineCreateNoteConfig(_Input):
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    project_id: ResourceId
    body: str = Field(..., min_length=1, max_length=10000)
    subject: Optional[str] = Field(None, min_length=1, max_length=10000)


class FilevineListProjectNotesConfig(_Page):
    operation: Literal["list_project_notes"] = Field("list_project_notes", json_schema_extra={"ui:hidden": True})
    project_id: ResourceId


class FilevineListTasksConfig(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})


class FilevineGetTaskConfig(_Input):
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: ResourceId


class FilevineCreateTaskConfig(_Input):
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    project_id: ResourceId
    body: str = Field(..., min_length=1, max_length=10000)
    subject: Optional[str] = Field(None, min_length=1, max_length=10000)
    assignee_id: ResourceId
    target_date: datetime = Field(..., description="Task due date in ISO 8601 date-time format.")


class FilevineAssignTaskConfig(_Input):
    operation: Literal["assign_task"] = Field("assign_task", json_schema_extra={"ui:hidden": True})
    task_id: ResourceId
    assignee_id: ResourceId


class FilevineListProjectTasksConfig(_Page):
    operation: Literal["list_project_tasks"] = Field("list_project_tasks", json_schema_extra={"ui:hidden": True})
    project_id: ResourceId


class FilevineListCommentsConfig(_LimitedPage):
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})
    note_id: ResourceId


class FilevineCreateCommentConfig(_Input):
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    note_id: ResourceId
    body: str = Field(..., min_length=1, max_length=10000)


class FilevineGetCurrentUserConfig(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class FilevineListProjectTypesConfig(_LimitedPage):
    operation: Literal["list_project_types"] = Field("list_project_types", json_schema_extra={"ui:hidden": True})


class FilevineListProjectPhasesConfig(_LimitedPage):
    operation: Literal["list_project_phases"] = Field("list_project_phases", json_schema_extra={"ui:hidden": True})
    project_type_id: ResourceId


# Event names and payload schemas: https://developer.filevine.io/docs/v2-us/b16689da4bcd4-webhook-payloads
TRIGGER_EVENTS = {
    "on_project_created": ("Project", "Created", "On New Project"),
    "on_project_updated": ("Project", "Updated", "On Project Updated"),
    "on_project_phase_changed": ("Project", "PhaseChanged", "On Project Phase Changed"),
    "on_contact_created": ("Contact", "Created", "On New Contact"),
    "on_contact_updated": ("Contact", "Updated", "On Contact Updated"),
    "on_note_created": ("Note", "Created", "On New Note or Task"),
    "on_note_assigned": ("Note", "Assigned", "On Task Assigned"),
    "on_note_completed": ("Note", "Completed", "On Task Completed"),
}


class FilevineWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with Filevine automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


TRIGGER_CONFIGS = {
    name: create_model("Filevine" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=FilevineWebhookConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": label})),
        event_id=(str, Field(..., min_length=1, max_length=500, title="Filevine Event",
            description="The matching event from your Filevine organisation, selected automatically when unique.",
            json_schema_extra={"x-dynamic-options": {"field_name": name}})))
    for name, (_, _, label) in TRIGGER_EVENTS.items()
}
globals().update({model.__name__: model for model in TRIGGER_CONFIGS.values()})


@lru_cache(maxsize=1)
def _webhook_keys():
    # Published by https://identity.filevine.com/.well-known/openid-configuration.
    return jwt.PyJWKClient("https://identity.filevine.com/.well-known/openid-configuration/jwks", lifespan=3600, timeout=10)


FilevineConfig = Annotated[Union[
    FilevineListProjectsConfig,
    FilevineGetProjectConfig,
    FilevineListContactsConfig,
    FilevineGetContactConfig,
    FilevineCreateProjectConfig,
    FilevineUpdateProjectConfig,
    FilevineCreateContactConfig,
    FilevineUpdateContactConfig,
    FilevineListNotesConfig,
    FilevineGetNoteConfig,
    FilevineCreateNoteConfig,
    FilevineListProjectNotesConfig,
    FilevineListTasksConfig,
    FilevineGetTaskConfig,
    FilevineCreateTaskConfig,
    FilevineAssignTaskConfig,
    FilevineListProjectTasksConfig,
    FilevineListCommentsConfig,
    FilevineCreateCommentConfig,
    FilevineGetCurrentUserConfig,
    FilevineListProjectTypesConfig,
    FilevineListProjectPhasesConfig,
    *TRIGGER_CONFIGS.values()
], Field(discriminator="operation")]


class FilevineFullConfig(NodeConfig[FilevineConfig, FilevineAccessTokenCredential]):
    pass


ROUTES = {'list_projects': ('GET', '/fv-app/v2/Projects'),
 'get_project': ('GET', '/fv-app/v2/Projects/{project_id}'),
 'list_contacts': ('GET', '/fv-app/v2/Contacts'),
 'get_contact': ('GET', '/fv-app/v2/Contacts/{contact_id}'),
 'create_project': ('POST', '/fv-app/v2/Projects'),
 'update_project': ('PATCH', '/fv-app/v2/Projects/{project_id}'),
 'create_contact': ('POST', '/fv-app/v2/Contacts'),
 'update_contact': ('PATCH', '/fv-app/v2/Contacts/{contact_id}'),
 'list_notes': ('GET', '/fv-app/v2/Notes'),
 'get_note': ('GET', '/fv-app/v2/Notes/{note_id}'),
 'create_note': ('POST', '/fv-app/v2/Notes'),
 'list_project_notes': ('GET', '/fv-app/v2/Projects/{project_id}/Notes'),
 'list_tasks': ('GET', '/fv-app/v2/tasks'),
 'get_task': ('GET', '/fv-app/v2/tasks/{task_id}'),
 'create_task': ('POST', '/fv-app/v2/tasks'),
 'list_project_tasks': ('GET', '/fv-app/v2/projects/{project_id}/tasks'),
 'list_comments': ('GET', '/fv-app/v2/Notes/{note_id}/Comments'),
 'create_comment': ('POST', '/fv-app/v2/Notes/{note_id}/Comments'),
 'get_current_user': ('GET', '/fv-app/v2/Users/Me'),
 'list_project_types': ('GET', '/fv-app/v2/ProjectTypes'),
 'list_project_phases': ('GET', '/fv-app/v2/ProjectTypes/{project_type_id}/phases'),
 'assign_task': ('PATCH', '/fv-app/v2/tasks/{task_id}/assign/{assignee_id}')}
BODY_FIELDS = {'create_project': {'project_type_id': 'ProjectTypeId',
                    'client_id': 'ClientId',
                    'project_name': 'ProjectName',
                    'description': 'Description'},
 'update_project': {'project_name': 'ProjectName',
                    'description': 'Description',
                    'phase_id': 'PhaseId'},
 'create_contact': {'first_name': 'FirstName',
                    'last_name': 'LastName',
                    'primary_email': 'PrimaryEmail',
                    'notes': 'Notes'},
 'update_contact': {'first_name': 'FirstName',
                    'last_name': 'LastName',
                    'primary_email': 'PrimaryEmail',
                    'notes': 'Notes'},
 'create_note': {'project_id': 'ProjectId', 'body': 'Body', 'subject': 'Subject'},
 'create_task': {'project_id': 'ProjectId',
                 'body': 'Body',
                 'subject': 'Subject',
                 'assignee_id': 'AssigneeId',
                 'target_date': 'TargetDate'},
 'create_comment': {'body': 'Body'}}
IDENTIFIER_FIELDS = {'create_project': ('project_type_id', 'client_id'),
 'update_project': ('phase_id',),
 'create_note': ['project_id'],
 'create_task': ['project_id', 'assignee_id']}
QUERY_FIELDS = {'list_projects': {'search_term': 'searchTerm'}, 'list_contacts': {'search_term': 'searchTerm'}}
LIST_OPERATIONS = frozenset(['list_projects', 'list_contacts', 'list_notes', 'list_project_notes', 'list_tasks', 'list_project_tasks', 'list_comments', 'list_project_types', 'list_project_phases'])


def _safe_response(value, token):
    """Never echo the credential or the password field in Filevine's user schema."""
    if isinstance(value, dict):
        return {k: _safe_response(v, token) for k, v in value.items()
                if k.lower() not in {"password", "access_token", "refresh_token", "client_secret"}}
    if isinstance(value, list):
        return [_safe_response(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class FilevineNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_signing_secret_not_issued = True
    integration_type = "automation-filevine"
    connection_evidence = ConnectionEvidence(
        noun="Filevine projects", operation="list_projects", identity_operation="get_current_user",
        label_keys=("ProjectName", "Name", "ProjectId"),
        identity_keys=("UserName", "Email"),
    )

    @classmethod
    def get_config_model(cls):
        return FilevineFullConfig

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        credential = FilevineAccessTokenCredential.model_validate(credential)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.access_token,
                         "x-fv-orgid": str(credential.org_id), "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if method == "DELETE" and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Filevine webhook HTTP {response.status_code}")
        return response.json()

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in TRIGGER_EVENTS:
            return {"options": []}
        kind, action, label = TRIGGER_EVENTS[field_name]
        events = await cls._webhook_request(credential_data, "GET", "/fv-app/v2/webhooks/Events")
        if not isinstance(events, list):
            raise ValueError("Filevine did not return the available webhook events")
        return {"options": [{"value": str(event["Id"]), "label": event.get("Name") or label}
                            for event in events if isinstance(event, dict) and event.get("Id")
                            and event.get("ObjectType") == kind and event.get("EventType") == action]}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_id": (config or {}).get("event_id")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        _, _, label = TRIGGER_EVENTS[config["operation"]]
        event_id = TRIGGER_CONFIGS[config["operation"]].model_validate(config).event_id
        subscription = await cls._webhook_request(credential, "POST", "/fv-app/v2/webhooks/subscription",
            body={"Name": f"NoClick {node_id}", "Description": label, "EventIds": [event_id], "Endpoint": webhook_url})
        if not isinstance(subscription, dict) or not subscription.get("Id"):
            raise ValueError("Filevine did not return a webhook subscription ID")
        return {"external_webhook_id": str(subscription["Id"])}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_id = (config or {}).get("external_webhook_id")
        if subscription_id and credential:
            await cls._webhook_request(credential, "DELETE",
                "/fv-app/v2/webhooks/subscription/" + quote(str(subscription_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://developer.filevine.io/docs/v2-us/15de82e461c3e-webhook-security
        authorization = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        if not authorization.startswith("Bearer "):
            return False
        token = authorization[7:]
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS512":
                return False
            key = _webhook_keys().get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS512"], issuer="https://identity.filevine.com",
                audience="filevine-v2-webhooks", options={"require": ["exp", "iss", "aud"]})
            scopes = claims.get("scope", [])
            if isinstance(scopes, str):
                scopes = scopes.split()
            return isinstance(scopes, list) and "filevine-v2-webhooks-access" in scopes
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = TRIGGER_EVENTS.get((config or {}).get("operation"))
        return bool(event and isinstance(payload, dict) and payload.get("Object") == event[0]
                    and payload.get("Event") == event[1])

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if cls.filter_trigger_payload(payload, config):
            return {"status": "success", "data": {k: v for k, v in payload.items() if k != "_webhook"}}
        return None

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        payload = output.get("data", output)
        if not isinstance(payload, dict):
            return None
        kind, action = payload.get("Object"), payload.get("Event")
        if (kind, action) not in {(v[0], v[1]) for v in TRIGGER_EVENTS.values()}:
            return None
        project_id = payload.get("ProjectId")
        object_id = payload.get("ObjectId") or {}
        lines = [f"Filevine {kind} {action}", f"Organisation ID: {payload.get('OrgId')}"]
        if payload.get("UserId") is not None:
            lines.append(f"By user ID: {payload['UserId']}")
        if project_id is not None:
            lines.append(f"Project ID: {project_id}; use get_project project_id={project_id} to read the case.")
        if kind == "Contact" and object_id.get("PersonId") is not None:
            contact_id = object_id["PersonId"]
            lines.append(f"Contact ID: {contact_id}; use get_contact contact_id={contact_id} to read the contact.")
        if kind == "Note" and object_id.get("NoteId") is not None:
            note_id = object_id["NoteId"]
            lines.append(f"Note/task ID: {note_id}; use get_note note_id={note_id} for the content.")
            if action == "Assigned" and object_id.get("AssigneeId") is not None:
                lines.append(f"Assigned to user ID: {object_id['AssigneeId']}")
        if kind == "Project" and action == "PhaseChanged":
            lines.append(f"Phase ID: {object_id.get('PhaseId')}; project type ID: {object_id.get('ProjectTypeId')}")
            other = payload.get("Other") or {}
            if other.get("PhaseName"):
                lines.append(f"Phase: {other['PhaseName']}")
        lines.append(f"Event timestamp: {payload.get('Timestamp')}")
        conversation = (f"contact:{object_id.get('PersonId')}" if kind == "Contact" else
                        f"project:{project_id}" if project_id is not None else f"note:{object_id.get('NoteId')}")
        return {"text": "\n".join(lines), "conversation_key": f"filevine:{payload.get('OrgId')}:{conversation}",
                "title": f"Filevine {kind} {action}"}

    async def execute(self, inputs):
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Filevine access token first")
        if isinstance(op, FilevineWebhookConfig):
            return {"status": "success", "data": {}, "no_event": True}
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, mode="json")
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {api: values[field] for field, api in QUERY_FIELDS.get(op.operation, {}).items() if field in values}
        for field in ("offset", "limit"):
            if field in values:
                params[field] = values[field]
        body = None
        if op.operation in BODY_FIELDS:
            body = {}
            for field, api in BODY_FIELDS[op.operation].items():
                if field in values:
                    body[api] = {"Native": int(values[field])} if field in IDENTIFIER_FIELDS.get(op.operation, ()) else values[field]
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + credential.access_token,
                         "x-fv-orgid": str(credential.org_id), "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code < 200 or response.status_code >= 300:
            # Keep provider rejection words for the shared connection verdict, but redact secrets.
            detail = response.text[:1000].replace(credential.access_token, "[redacted]")
            raise ValueError(f"Filevine HTTP {response.status_code}: {detail}")
        if len(response.content) > 10_000_000:
            raise ValueError("Filevine response exceeds the 10 MB limit")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Filevine did not return JSON") from None
        if not isinstance(data, dict):
            raise ValueError("Expected a Filevine JSON object")
        if any(data.get(key) for key in ("error", "Error", "errors", "Errors")):
            raise ValueError("Filevine returned an error response")
        data = _safe_response(data, credential.access_token)
        if op.operation == "get_current_user" and not any(
            isinstance(data.get(key), str) and data[key].strip() for key in ("UserName", "Email")
        ):
            raise ValueError("Filevine current user response has no account identity")
        if op.operation in LIST_OPERATIONS:
            items = data.get("Items")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("Expected Filevine Items list")
            has_more = data.get("HasMore", False)
            if not isinstance(has_more, bool):
                raise ValueError("Expected Filevine HasMore boolean")
            # Offset is a record position, not a page number. Never follow Links.
            next_offset = values.get("offset", 0) + len(items) if has_more and items else None
            return {"status": "success", "items": items, "data": data,
                    "has_more": has_more, "next_offset": next_offset}
        return {"status": "success", "data": data}
