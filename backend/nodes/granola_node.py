"""Granola REST integration. Primary API contract: https://docs.granola.ai/api-reference.

Requests only run when an operation is explicitly executed. No automatic retries.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

class GranolaApiKeyCredential(BaseModel):
    credential_type: Literal["granola_api_key"] = Field("granola_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Granola API Key", json_schema_extra={
        "x-credential-url": "https://docs.granola.ai/authentication",
        "x-credential-instructions": "Create a personal or workspace API key in Granola Settings → Connectors → API keys. Personal keys require Business or Enterprise; workspace keys require Enterprise. Key scopes determine accessible notes and administrative operations."
    })

GranolaCredential = GranolaApiKeyCredential


class GranolaLegalHoldCustodianInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    email: str | None = Field(None, title='Email', description="The custodian's email address. Use this when your system knows employees by email rather than by Granola user id.")
    id: str | None = Field(None, title='Id', description="The custodian's Granola user id", pattern='^usr_[a-zA-Z0-9]{14}$')

    @model_validator(mode="after")
    def require_custodian(self):
        if not self.email and not self.id:
            raise ValueError("A custodian needs an email or Granola user ID.")
        return self

class GranolaListNotesConfig(BaseModel):
    'List notes'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_notes'] = Field('list_notes', json_schema_extra={'const': 'list_notes', 'ui:hidden': True, 'x-category': 'Notes', 'x-operation-name': 'List Notes'})
    created_before: Union[str, datetime] | None = Field(None, title='Created Before', description='Return notes created before this date')
    created_after: Union[str, datetime] | None = Field(None, title='Created After', description='Return notes created after this date')
    updated_after: Union[str, datetime] | None = Field(None, title='Updated After', description='Return notes updated after this date')
    folder_id: str | None = Field(None, title='Folder Id', description='Return notes in this folder and any of its child folders. Use the list folders endpoint to discover folder IDs.', pattern='^fol_[a-zA-Z0-9]{14}$', json_schema_extra={'x-dynamic-options': {'field_name': 'folder_id', 'searchable': True, 'allow_custom': True}})
    cursor: str | None = Field(None, title='Cursor', description='The cursor to continue from')
    page_size: int | None = Field(10, title='Page Size', description='Maximum number of notes to return per page', ge=1, le=30)
    space_id: str | None = Field(None, title='Space Id', description='Return notes in this space. Use the list spaces endpoint to discover space IDs.', pattern='^spa_[a-zA-Z0-9]{14}$', json_schema_extra={'x-dynamic-options': {'field_name': 'space_id', 'searchable': True, 'allow_custom': True}})

class GranolaGetNoteConfig(BaseModel):
    'Get note'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_note'] = Field('get_note', json_schema_extra={'const': 'get_note', 'ui:hidden': True, 'x-category': 'Notes', 'x-operation-name': 'Get Note'})
    note_id: str = Field(..., title='Note Id', description='The ID of the note', pattern='^not_[a-zA-Z0-9]{14}$', json_schema_extra={'x-dynamic-options': {'field_name': 'note_id', 'searchable': True, 'allow_custom': True}})
    include: Literal['transcript'] | None = Field(None, title='Include', description='Include the note transcript in the response. If it is too large to return inline, Get Note returns `TRANSCRIPT_TOO_LARGE`; retrieve it in pages from `/v1/notes/{note_id}/transcript`.')

class GranolaGetTranscriptConfig(BaseModel):
    'Get transcript'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_transcript'] = Field('get_transcript', json_schema_extra={'const': 'get_transcript', 'ui:hidden': True, 'x-category': 'Notes', 'x-operation-name': 'Get Transcript'})
    note_id: str = Field(..., title='Note Id', description='The ID of the note', pattern='^not_[a-zA-Z0-9]{14}$', json_schema_extra={'x-dynamic-options': {'field_name': 'note_id', 'searchable': True, 'allow_custom': True}})
    cursor: str | None = Field(None, title='Cursor', description='The opaque cursor returned by the previous page')
    page_size: int | None = Field(50, title='Page Size', description='The maximum number of transcript items to return', ge=1, le=100)

class GranolaListFoldersConfig(BaseModel):
    'List folders'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_folders'] = Field('list_folders', json_schema_extra={'const': 'list_folders', 'ui:hidden': True, 'x-category': 'Notes', 'x-operation-name': 'List Folders'})
    cursor: str | None = Field(None, title='Cursor', description='The cursor to continue from')
    page_size: int | None = Field(10, title='Page Size', description='Maximum number of folders to return per page', ge=1, le=30)

class GranolaListSpacesConfig(BaseModel):
    'List spaces'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_spaces'] = Field('list_spaces', json_schema_extra={'const': 'list_spaces', 'ui:hidden': True, 'x-category': 'Notes', 'x-operation-name': 'List Spaces'})
    cursor: str | None = Field(None, title='Cursor', description='The cursor to continue from')
    page_size: int | None = Field(10, title='Page Size', description='The number of spaces to return', ge=1, le=30)

class GranolaListAuditEventsConfig(BaseModel):
    'List audit events'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_audit_events'] = Field('list_audit_events', json_schema_extra={'const': 'list_audit_events', 'ui:hidden': True, 'x-category': 'Notes', 'x-operation-name': 'List Audit Events'})
    action: str | None = Field(None, title='Action', description='Return only events with this exact action, or events whose action starts with it followed by a dot (`workspace` returns `workspace.member_added` but not `workspace_automation.created`). Lowercase, as actions are.', pattern='^[a-z][a-z0-9_.-]*$')
    occurred_before: Union[str, datetime] | None = Field(None, title='Occurred Before', description='Return events that occurred before this date. Must fall within the one-year retention window; an earlier date is rejected.')
    occurred_after: Union[str, datetime] | None = Field(None, title='Occurred After', description='Return events that occurred after this date. Must fall within the one-year retention window; an earlier date is rejected.')
    cursor: str | None = Field(None, title='Cursor', description='The cursor to continue from')
    page_size: int | None = Field(10, title='Page Size', description='Maximum number of audit events to return per page', ge=1, le=30)

class GranolaCreateWebhookEndpointConfig(BaseModel):
    'Create webhook endpoint'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['create_webhook_endpoint'] = Field('create_webhook_endpoint', json_schema_extra={'const': 'create_webhook_endpoint', 'ui:hidden': True, 'x-category': 'Webhooks', 'x-operation-name': 'Create Webhook Endpoint'})
    url: str = Field(..., title='Url', description='The publicly reachable HTTPS URL to deliver events to')
    scopes: list[Literal['personal', 'public', 'workspace']] = Field(..., title='Scopes', description='Which notes to receive events for. `personal` covers notes you own, notes shared directly with you, and notes in private folders shared with you. `public` covers notes visible to everyone in the workspace. Pass both for both sets of notes. Workspace admins can disable scopes for non-admin members in the workspace\'s API settings. With a Workspace API key, pass exactly `["workspace"]` — the key\'s own scope: public workspace notes plus notes in spaces with Granola API access enabled.', min_length=1)
    events: list[Literal['note.access_granted', 'note.edited', 'note.generated']] | None = Field(['note.access_granted', 'note.edited', 'note.generated'], title='Events', description='Event names to subscribe to. Omit to subscribe to all events.', min_length=1)
    folder_ids: list[str] | None = Field(None, title='Folder Ids', description='Restrict delivery to notes in these folders or any of their subfolders. Accepts folder IDs returned by `GET /v1/folders`. Omit to receive events for every note matching `scopes`. The same filter applies to all subscribed `events`.', min_length=1, max_length=100)

class GranolaListWebhookEndpointsConfig(BaseModel):
    'List webhook endpoints'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_webhook_endpoints'] = Field('list_webhook_endpoints', json_schema_extra={'const': 'list_webhook_endpoints', 'ui:hidden': True, 'x-category': 'Webhooks', 'x-operation-name': 'List Webhook Endpoints'})

class GranolaUpdateWebhookEndpointConfig(BaseModel):
    'Update webhook endpoint'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['update_webhook_endpoint'] = Field('update_webhook_endpoint', json_schema_extra={'const': 'update_webhook_endpoint', 'ui:hidden': True, 'x-category': 'Webhooks', 'x-operation-name': 'Update Webhook Endpoint'})
    url: str | None = Field(None, title='Url', description='The publicly reachable HTTPS URL to deliver events to. Omit to leave unchanged.')
    scopes: list[Literal['personal', 'public', 'workspace']] | None = Field(None, title='Scopes', description='Which notes to receive events for; replaces the current scopes. `personal` covers notes you own, notes shared directly with you, and notes in private folders shared with you. `public` covers notes visible to everyone in the workspace. Pass both for both sets of notes. Workspace admins can disable scopes for non-admin members in the workspace\'s API settings. A workspace-managed endpoint\'s scope is fixed: only `["workspace"]` is accepted. Omit to leave unchanged.', min_length=1)
    events: list[Literal['note.access_granted', 'note.edited', 'note.generated']] | None = Field(None, title='Events', description='Event names to subscribe to; replaces the current subscriptions. Omit to leave unchanged.', min_length=1)
    folder_ids: list[str] | None = Field(None, title='Folder Ids', description='Restrict delivery to notes in these folders or any of their subfolders; replaces the current folder filter. Accepts folder IDs returned by `GET /v1/folders`. Pass an empty array to remove the filter. Omit to leave unchanged.', max_length=100)
    enabled: bool | None = Field(None, title='Enabled', description='Pause (`false`) or resume (`true`) event deliveries. A paused endpoint keeps its configuration and signing secret; events that occur while paused are not delivered later. Omit to leave unchanged.')
    webhook_endpoint_id: str = Field(..., title='Webhook Endpoint Id', description='The ID of the webhook endpoint', pattern='^whe_[a-zA-Z0-9]{14}$')

class GranolaDeleteWebhookEndpointConfig(BaseModel):
    'Delete webhook endpoint'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['delete_webhook_endpoint'] = Field('delete_webhook_endpoint', json_schema_extra={'const': 'delete_webhook_endpoint', 'ui:hidden': True, 'x-category': 'Webhooks', 'x-operation-name': 'Delete Webhook Endpoint'})
    webhook_endpoint_id: str = Field(..., title='Webhook Endpoint Id', description='The ID of the webhook endpoint', pattern='^whe_[a-zA-Z0-9]{14}$')

class GranolaCreateLegalHoldConfig(BaseModel):
    'Create legal hold'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['create_legal_hold'] = Field('create_legal_hold', json_schema_extra={'const': 'create_legal_hold', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'Create Legal Hold'})
    name: str = Field(..., title='Name', description='A name for the matter this hold preserves', min_length=1, max_length=200)
    description: Union[str, None] = Field(None, title='Description', description='Free text describing the matter', max_length=2000)
    covers_entire_workspace: bool = Field(..., title='Covers Entire Workspace', description='Whether the hold covers every member of your workspace, current and future. Required: scope is never something a caller falls into.')
    custodians: list[GranolaLegalHoldCustodianInput] | None = Field(None, title='Custodians', description='Users to name individually when the hold is created', max_length=100)

class GranolaListLegalHoldsConfig(BaseModel):
    'List legal holds'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_legal_holds'] = Field('list_legal_holds', json_schema_extra={'const': 'list_legal_holds', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'List Legal Holds'})
    cursor: str | None = Field(None, title='Cursor', description='The cursor to continue from')
    page_size: int | None = Field(10, title='Page Size', description='Maximum number of legal holds to return per page', ge=1, le=30)

class GranolaGetLegalHoldConfig(BaseModel):
    'Get legal hold'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_legal_hold'] = Field('get_legal_hold', json_schema_extra={'const': 'get_legal_hold', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'Get Legal Hold'})
    hold_id: str = Field(..., title='Hold Id', description='The legal hold id', pattern='^lgh_[a-zA-Z0-9]{14}$')

class GranolaUpdateLegalHoldConfig(BaseModel):
    'Update legal hold'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['update_legal_hold'] = Field('update_legal_hold', json_schema_extra={'const': 'update_legal_hold', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'Update Legal Hold'})
    name: str | None = Field(None, title='Name', description='A new name for the matter', min_length=1, max_length=200)
    description: Union[str, None] = Field(None, title='Description', description='New free text for the matter, or null to clear it', max_length=2000)
    covers_entire_workspace: bool | None = Field(None, title='Covers Entire Workspace', description='Whether the hold covers every member of your workspace. Toggling this never touches the custodians the hold names.')
    hold_id: str = Field(..., title='Hold Id', description='The legal hold id', pattern='^lgh_[a-zA-Z0-9]{14}$')

class GranolaReleaseLegalHoldConfig(BaseModel):
    'Release legal hold'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['release_legal_hold'] = Field('release_legal_hold', json_schema_extra={'const': 'release_legal_hold', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'Release Legal Hold'})
    hold_id: str = Field(..., title='Hold Id', description='The legal hold id', pattern='^lgh_[a-zA-Z0-9]{14}$')

class GranolaAddLegalHoldCustodiansConfig(BaseModel):
    'Add legal hold custodians'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['add_legal_hold_custodians'] = Field('add_legal_hold_custodians', json_schema_extra={'const': 'add_legal_hold_custodians', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'Add Legal Hold Custodians'})
    custodians: list[GranolaLegalHoldCustodianInput] = Field(..., title='Custodians', description='Users to name on this hold', min_length=1, max_length=100)
    hold_id: str = Field(..., title='Hold Id', description='The legal hold id', pattern='^lgh_[a-zA-Z0-9]{14}$')

class GranolaListLegalHoldCustodiansConfig(BaseModel):
    'List legal hold custodians'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_legal_hold_custodians'] = Field('list_legal_hold_custodians', json_schema_extra={'const': 'list_legal_hold_custodians', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'List Legal Hold Custodians'})
    hold_id: str = Field(..., title='Hold Id', description='The legal hold id', pattern='^lgh_[a-zA-Z0-9]{14}$')
    cursor: str | None = Field(None, title='Cursor', description='The cursor to continue from')
    page_size: int | None = Field(10, title='Page Size', description='Maximum number of custodians to return per page', ge=1, le=30)

class GranolaRemoveLegalHoldCustodianConfig(BaseModel):
    'Remove legal hold custodian'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['remove_legal_hold_custodian'] = Field('remove_legal_hold_custodian', json_schema_extra={'const': 'remove_legal_hold_custodian', 'ui:hidden': True, 'x-category': 'Legal Holds', 'x-operation-name': 'Remove Legal Hold Custodian'})
    hold_id: str = Field(..., title='Hold Id', description='The legal hold id', pattern='^lgh_[a-zA-Z0-9]{14}$')
    custodian_id: str = Field(..., title='Custodian Id', description='The custodian entry id', pattern='^lhc_[a-zA-Z0-9]{14}$')

GranolaConfig = Annotated[Union[GranolaListNotesConfig, GranolaGetNoteConfig, GranolaGetTranscriptConfig, GranolaListFoldersConfig, GranolaListSpacesConfig, GranolaListAuditEventsConfig, GranolaCreateWebhookEndpointConfig, GranolaListWebhookEndpointsConfig, GranolaUpdateWebhookEndpointConfig, GranolaDeleteWebhookEndpointConfig, GranolaCreateLegalHoldConfig, GranolaListLegalHoldsConfig, GranolaGetLegalHoldConfig, GranolaUpdateLegalHoldConfig, GranolaReleaseLegalHoldConfig, GranolaAddLegalHoldCustodiansConfig, GranolaListLegalHoldCustodiansConfig, GranolaRemoveLegalHoldCustodianConfig], Field(discriminator="operation")]

class GranolaNodeConfig(NodeConfig[GranolaConfig, GranolaCredential]):
    pass

ROUTES = {'list_notes': ('GET', '/v1/notes', [], ['created_before', 'created_after', 'updated_after', 'folder_id', 'cursor', 'page_size', 'space_id'], []), 'get_note': ('GET', '/v1/notes/{note_id}', ['note_id'], ['include'], []), 'get_transcript': ('GET', '/v1/notes/{note_id}/transcript', ['note_id'], ['cursor', 'page_size'], []), 'list_folders': ('GET', '/v1/folders', [], ['cursor', 'page_size'], []), 'list_spaces': ('GET', '/v1/spaces', [], ['cursor', 'page_size'], []), 'list_audit_events': ('GET', '/v1/audit', [], ['action', 'occurred_before', 'occurred_after', 'cursor', 'page_size'], []), 'create_webhook_endpoint': ('POST', '/v1/webhook-endpoints', [], [], ['url', 'scopes', 'events', 'folder_ids']), 'list_webhook_endpoints': ('GET', '/v1/webhook-endpoints', [], [], []), 'update_webhook_endpoint': ('PATCH', '/v1/webhook-endpoints/{webhook_endpoint_id}', ['webhook_endpoint_id'], [], ['url', 'scopes', 'events', 'folder_ids', 'enabled']), 'delete_webhook_endpoint': ('DELETE', '/v1/webhook-endpoints/{webhook_endpoint_id}', ['webhook_endpoint_id'], [], []), 'create_legal_hold': ('POST', '/v1/legal-holds', [], [], ['name', 'description', 'covers_entire_workspace', 'custodians']), 'list_legal_holds': ('GET', '/v1/legal-holds', [], ['cursor', 'page_size'], []), 'get_legal_hold': ('GET', '/v1/legal-holds/{hold_id}', ['hold_id'], [], []), 'update_legal_hold': ('PATCH', '/v1/legal-holds/{hold_id}', ['hold_id'], [], ['name', 'description', 'covers_entire_workspace']), 'release_legal_hold': ('DELETE', '/v1/legal-holds/{hold_id}', ['hold_id'], [], []), 'add_legal_hold_custodians': ('POST', '/v1/legal-holds/{hold_id}/custodians', ['hold_id'], [], ['custodians']), 'list_legal_hold_custodians': ('GET', '/v1/legal-holds/{hold_id}/custodians', ['hold_id'], ['cursor', 'page_size'], []), 'remove_legal_hold_custodian': ('DELETE', '/v1/legal-holds/{hold_id}/custodians/{custodian_id}', ['hold_id', 'custodian_id'], [], [])}

PROVIDER = "Granola"
AUTH_PREFIX = "Bearer "
API_BASE = "https://public-api.granola.ai"

def _auth(credential):
    token = credential.get("api_key", "").strip()
    if not token:
        raise ValueError("Granola API key is required.")
    return API_BASE, token

async def _request(credential: dict[str, Any], method: str, path: str,
                   *, params=None, body=None, files=None, action: str) -> dict[str, Any]:
    """One bounded request. Error responses never echo credentials or request bodies."""
    base, token = _auth(credential)
    started = time.monotonic()
    headers = {"Authorization": AUTH_PREFIX + token, "Accept": "application/json"}
    kwargs = {"params": params, "headers": headers}
    if files is not None:
        kwargs["files"] = files
    elif body is not None:
        kwargs["json"] = body
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            response = await client.request(method, base + path, **kwargs)
        timing = {"api_request": round((time.monotonic() - started) * 1000, 2)}
        if not 200 <= response.status_code < 300:
            # Provider error text can echo sensitive inputs. Keep HTTP status and retry guidance.
            return {"status": "error", "action": action,
                    "error": f"{PROVIDER} returned HTTP {response.status_code}.",
                    "status_code": response.status_code,
                    "retry_after": response.headers.get("Retry-After"), "timing_ms": timing}
        if response.status_code == 204 or not response.content:
            data = {"success": True}
        else:
            try:
                data = response.json()
            except ValueError:
                return {"status": "error", "action": action,
                        "error": f"{PROVIDER} returned a non-JSON response.",
                        "status_code": response.status_code, "timing_ms": timing}
        # Preserve pagination and provider envelopes; arrays stay arrays for downstream tables.
        return {"status": "success", "action": action, "data": data,
                "status_code": response.status_code, "timing_ms": timing}
    except httpx.TimeoutException:
        return {"status": "error", "action": action, "error": "Request timed out.",
                "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}
    except httpx.RequestError:
        return {"status": "error", "action": action, "error": "Could not reach the provider.",
                "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}


def _request_parts(config: BaseModel):
    route = ROUTES[config.operation]
    values = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    path = route[1]
    for key in route[2]:
        path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
    params = {key: values[key] for key in route[3] if key in values}
    body = {key: values[key] for key in route[4] if key in values}
    if config.operation == "update_legal_hold" and "description" in config.model_fields_set:
        body["description"] = config.description  # Explicit null clears the description.
    return route[0], path, params, body or None


class GranolaNode(WorkflowNode):
    """Granola workflow operations from the official REST API."""
    integration_type = "automation-granola"
    connection_evidence = ConnectionEvidence(operation="list_notes", noun="meeting notes")
    edit_examples = ['List notes', 'Get note', 'Get transcript']

    @classmethod
    def get_config_model(cls):
        return GranolaNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, GranolaNodeConfig):
            raise ValueError("Valid Granola configuration is required.")
        op = self.config.config
        pass
        if self.config.credentials is None:
            raise ValueError("Add a Granola credential to run this operation.")
        credential = self.config.credentials.model_dump()
        method, path, params, body = _request_parts(op)
        result = await _request(credential, method, path, params=params, body=body, action=op.operation)
        result.setdefault("timing_ms", {})["total"] = round((time.monotonic() - started) * 1000, 2)
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        endpoints = {"note_id": ("/v1/notes", "notes"), "folder_id": ("/v1/folders", "folders"), "space_id": ("/v1/spaces", "spaces")}
        if field_name not in endpoints:
            return {"options": [], "next_page_token": None}
        path, key = endpoints[field_name]
        result = await _request(credential_data, "GET", path, params={"page_size": 30, **({"cursor": page_token} if page_token else {})}, action="list_" + key)
        if result["status"] != "success":
            raise ValueError(result["error"])
        data = result["data"]
        options = [{"label": str(row.get("title") or row.get("name") or row["id"]), "value": row["id"]} for row in data.get(key, [])]
        if search:
            options = [o for o in options if search.casefold() in o["label"].casefold()]
        return {"options": options, "next_page_token": data.get("cursor") if data.get("hasMore") else None}

