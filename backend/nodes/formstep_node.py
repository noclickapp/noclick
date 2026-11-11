"""Formstep API v1: workspace-scoped tokens, fixed RPC methods and signed webhooks.

Contract: https://docs.formstep.io/openapi.json (v1).
Webhook signing: https://docs.formstep.io/developers/webhooks-reference/#signing
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


class FormstepAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Formstep API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.formstep.io/developers/api-tokens/",
        "x-credential-instructions": "In Formstep, open OAuth and API Keys in the sidebar. Create a token for the workspace you want to automate and paste it here. Tokens can access one workspace only.",
    })
    credential_type: Literal["formstep_api_token"] = Field("formstep_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if any(char.isspace() for char in value):
            raise ValueError("Paste the API token without a Bearer prefix")
        return value


class FormstepDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documentId: str
    field: Optional[str] = None
    name: Optional[str] = None


class FormstepOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormstepGetAccountConfig(FormstepOperation):
    """Get information about the authenticated user."""
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Account', "x-category": 'Account'})

class FormstepListWorkspacesConfig(FormstepOperation):
    """List the workspaces your token can reach."""
    operation: Literal['list_workspaces'] = Field('list_workspaces', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Workspaces', "x-category": 'Workspaces'})

class FormstepListFormsConfig(FormstepOperation):
    """List forms in a workspace."""
    operation: Literal['list_forms'] = Field('list_forms', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Forms', "x-category": 'Forms'})
    workspaceId: str = Field(..., title='Workspace id', description='Workspace ID.')
    folderId: Optional[str] = Field(None, title='Folder id', description='Filter by folder. Pass `null` for root-level forms only. Omit to list all.')
    query: Optional[str] = Field(None, title='Query', description='Fuzzy name search. Results capped at `limit`; not cursor-paginated.')
    limit: Optional[int] = Field(20, title='Limit', description='Page size (1–100).', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', description='Pagination cursor from a previous response (`nextCursor`).')

class FormstepGetFormConfig(FormstepOperation):
    """Get full details for a single form, including questions, cover, logo, and a preview URL."""
    operation: Literal['get_form'] = Field('get_form', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Form', "x-category": 'Forms'})
    formId: str = Field(..., title='Form id', description='Form ID.')

class FormstepCreateFormConfig(FormstepOperation):
    """Create a new empty form."""
    operation: Literal['create_form'] = Field('create_form', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Form', "x-category": 'Forms'})
    name: str = Field(..., title='Name', description='Form name (1–255 characters).', min_length=1, max_length=255)
    workspaceId: str = Field(..., title='Workspace id', description='Workspace ID.')
    folderId: Optional[str] = Field(None, title='Folder id', description='Place the form in a folder. Omit to create at workspace root.')

class FormstepUpdateFormConfig(FormstepOperation):
    """Rename a form, move it between folders, or change its emoji."""
    operation: Literal['update_form'] = Field('update_form', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Form', "x-category": 'Forms'})
    formId: str = Field(..., title='Form id', description='Form ID.')
    name: Optional[str] = Field(None, title='Name', description='New form name (1–255 characters).', min_length=1, max_length=255)
    folderId: Optional[str] = Field(None, title='Folder id', description='Move form to a folder. Pass `null` to move to workspace root.')
    emoji: Optional[str] = Field(None, title='Emoji', description='Form emoji (max 10 characters). Pass `null` to clear.', max_length=10)

    @model_validator(mode="after")
    def has_update(self):
        if self.name is None and not self.model_fields_set.intersection({"folderId", "emoji"}):
            raise ValueError("Provide a name, folder or emoji to update")
        return self

class FormstepPublishFormConfig(FormstepOperation):
    """Publish a form so it can accept responses, and freeze its field keys into a new snapshot."""
    operation: Literal['publish_form'] = Field('publish_form', json_schema_extra={"ui:hidden": True, "x-display-name": 'Publish Form', "x-category": 'Forms'})
    formId: str = Field(..., title='Form id', description='Form ID.')

class FormstepUnpublishFormConfig(FormstepOperation):
    """Take a form offline."""
    operation: Literal['unpublish_form'] = Field('unpublish_form', json_schema_extra={"ui:hidden": True, "x-display-name": 'Unpublish Form', "x-category": 'Forms'})
    formId: str = Field(..., title='Form id', description='Form ID.')

class FormstepDeleteFormConfig(FormstepOperation):
    """Move a form to trash."""
    operation: Literal['delete_form'] = Field('delete_form', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete Form', "x-category": 'Forms'})
    formId: str = Field(..., title='Form id', description='Form ID.')

class FormstepListFieldsConfig(FormstepOperation):
    """List every field of a form's current published version, with the key to address each one by."""
    operation: Literal['list_fields'] = Field('list_fields', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Fields', "x-category": 'Fields'})
    formId: str = Field(..., title='Form id', description='Form ID. A form that has never been published answers `published: false` with no items.')

class FormstepListSubmissionsConfig(FormstepOperation):
    """List a form's submissions, newest page first, with cursor pagination."""
    operation: Literal['list_submissions'] = Field('list_submissions', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Submissions', "x-category": 'Submissions'})
    formId: str = Field(..., title='Form id', description='Form ID.')
    includeDrafts: Optional[bool] = Field(False, title='Include drafts', description='Include responses that were started but never submitted.')
    translationLanguage: Optional[str] = Field(None, title='Translation language', description='Attach stored AI translations of the answers under `items[].translation.display`. `items[].answers` and `items[].display` always stay the original.')
    limit: Optional[int] = Field(20, title='Limit', description='Page size (1–100).', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', description='Pagination cursor from a previous response (`nextCursor`).')

class FormstepCreateRequestConfig(FormstepOperation):
    """Create a request."""
    operation: Literal['create_request'] = Field('create_request', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Request', "x-category": 'Requests'})
    formId: str = Field(..., title='Form id', description='The published form to assign.')
    recipient: Optional[Json[dict[str, str]]] = Field(None, title='Recipient', description='An email is required when `delivery` is `"email"`; otherwise it only identifies the person in the Requests page and on their answers.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    prefill: Optional[Json[dict[str, Any]]] = Field(None, title='Prefill', description='Initial answers by field key. The recipient sees them and can change them.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    readonly: Optional[Json[list[str]]] = Field(None, title='Readonly', description='Prefilled keys the recipient cannot change. Every key here must also appear in `prefill`, and a locked required field must be prefilled with a non-empty value.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    context: Optional[Json[dict[str, Any]]] = Field(None, title='Context', description="Values for the form's hidden fields, by field key. Trusted, unchangeable, and echoed back in the callback. An unknown key is rejected with `UNKNOWN_FIELD_KEY`.", json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    metadata: Optional[Json[dict[str, Any]]] = Field(None, title='Metadata', description='Your own bookkeeping. Never reaches the form; comes back in callbacks and reads.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    language: Optional[str] = Field(None, title='Language', description="One of the form's published languages. Defaults to the form's own default.")
    delivery: Optional[Literal['none', 'email']] = Field('none', title='Delivery', description='`"email"` to have Formstep send the invitation (needs a recipient email, and Pro or Business or one of a Free account\'s 10 free invitations, which go only to the account\'s own address), or `"none"` to deliver the link yourself.')
    reminders: Optional[Json[list[str]]] = Field(None, title='Reminders', description="Override the form's reminder schedule for this request. An empty array switches reminders off.", json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    expiresAt: Optional[float] = Field(None, title='Expires at', description='Epoch milliseconds. Defaults to 30 days out; 365 days is the maximum.')
    callbackUrl: Optional[str] = Field(None, title='Callback url', description='Where Formstep POSTs the callback when the request ends. HTTPS only, and the host must resolve to a public address.')
    externalId: Optional[str] = Field(None, title='External id', description='Your own id for this request. Filterable in `requests.list`.')
    idempotencyKey: Optional[str] = Field(None, title='Idempotency key', description='Repeating it with the same body returns the original request with `deduplicated: true`. A different body is rejected. Keys live 30 days.')
    domainId: Optional[str] = Field(None, title='Domain id', description='Mint the link on one of your custom domains. REST API only.')
    documents: Optional[Json[list[FormstepDocument]]] = Field(None, title='Documents', description='Files handed to this one recipient, uploaded first with `documents.create`.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    test: Optional[bool] = Field(False, title='Test', description='A dry run: nothing is emailed, the callback carries `"test": true`, and the submission counts nowhere.')

    @model_validator(mode="after")
    def valid_request(self):
        if self.delivery == "email" and not (self.recipient or {}).get("email"):
            raise ValueError("Email delivery requires a recipient email")
        if self.readonly and any(key not in (self.prefill or {}) for key in self.readonly):
            raise ValueError("Every readonly key must also be prefilled")
        return self

class FormstepGetRequestConfig(FormstepOperation):
    """Get one request in full: status, outcome, what was prefilled, its timeline, and, once completed, `answers` and `display` keyed by field key."""
    operation: Literal['get_request'] = Field('get_request', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Request', "x-category": 'Requests'})
    requestId: str = Field(..., title='Request id', description='Request ID.')

class FormstepListRequestsConfig(FormstepOperation):
    """List requests in a workspace or on one form, newest first."""
    operation: Literal['list_requests'] = Field('list_requests', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Requests', "x-category": 'Requests'})
    workspaceId: Optional[str] = Field(None, title='Workspace id', description='Scope to a workspace. Give this or `formId`.')
    formId: Optional[str] = Field(None, title='Form id', description='Scope to one form.')
    status: Optional[Literal['pending', 'completed', 'expired', 'canceled']] = Field(None, title='Status', description='')
    outcome: Optional[Literal['approve', 'decline', 'changes']] = Field(None, title='Outcome', description='Implies completed requests only, and overrides `status`.')
    externalId: Optional[str] = Field(None, title='External id', description='Your own id, to find the request a run created.')
    includeTest: Optional[bool] = Field(False, title='Include test', description='Include requests created with `test: true`.')
    limit: Optional[int] = Field(25, title='Limit', description='Page size (1–100).', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', description='Pagination cursor from a previous response (`nextCursor`).')

    @model_validator(mode="after")
    def has_scope(self):
        if not self.workspaceId and not self.formId:
            raise ValueError("Choose a workspace or form")
        return self

class FormstepRemindRequestConfig(FormstepOperation):
    """Email the recipient now, without touching the reminder schedule."""
    operation: Literal['remind_request'] = Field('remind_request', json_schema_extra={"ui:hidden": True, "x-display-name": 'Remind Request', "x-category": 'Requests'})
    requestId: str = Field(..., title='Request id', description='Request ID. Must still be pending, and not a test request.')

class FormstepCancelRequestConfig(FormstepOperation):
    """Withdraw a pending request."""
    operation: Literal['cancel_request'] = Field('cancel_request', json_schema_extra={"ui:hidden": True, "x-display-name": 'Cancel Request', "x-category": 'Requests'})
    requestId: str = Field(..., title='Request id', description='Request ID.')
    reason: Optional[str] = Field(None, title='Reason', description='Your note for why, kept on the request and sent in the callback.')

class FormstepListShareLinksConfig(FormstepOperation):
    """List share links for a form."""
    operation: Literal['list_share_links'] = Field('list_share_links', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Share Links', "x-category": 'Share Links'})
    formId: str = Field(..., title='Form id', description='Form ID.')
    includeRevoked: Optional[bool] = Field(None, title='Include revoked', description='Include revoked links in the result.')
    limit: Optional[int] = Field(20, title='Limit', description='Page size (1–100).', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', description='Pagination cursor from a previous response (`nextCursor`).')

class FormstepCreateShareLinkConfig(FormstepOperation):
    """Create a share link for a form."""
    operation: Literal['create_share_link'] = Field('create_share_link', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Share Link', "x-category": 'Share Links'})
    formId: str = Field(..., title='Form id', description='Form ID. The form must be published; call `forms.publish` first.')
    expiresAt: Optional[int] = Field(None, title='Expires at', description='Expiration as a future Unix timestamp in milliseconds. `0` is not accepted here.')
    maxClaims: Optional[int] = Field(None, title='Max claims', description='Maximum number of times this link can be used. Must be positive.', ge=1)

class FormstepListFoldersConfig(FormstepOperation):
    """List folders in a workspace."""
    operation: Literal['list_folders'] = Field('list_folders', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Folders', "x-category": 'Folders'})
    workspaceId: str = Field(..., title='Workspace id', description='Workspace ID.')
    limit: Optional[int] = Field(20, title='Limit', description='Page size (1–100).', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', description='Pagination cursor from a previous response (`nextCursor`).')

class FormstepCreateFolderConfig(FormstepOperation):
    """Create a folder in a workspace."""
    operation: Literal['create_folder'] = Field('create_folder', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Folder', "x-category": 'Folders'})
    workspaceId: str = Field(..., title='Workspace id', description='Workspace ID.')
    name: str = Field(..., title='Name', description='Folder name (1–255 characters).', min_length=1, max_length=255)
    parentId: Optional[str] = Field(None, title='Parent id', description='Parent folder ID for nesting. Omit for root level.')


EVENT_TYPES = {
    "submission_created": "submission.completed",
    "request_completed": "request.completed",
}


class FormstepOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Formstep Event", "x-category": "Triggers"})
    formId: str = Field(..., title="Form ID")
    event_type: Literal["submission_created", "request_completed"] = Field("submission_created", title="Event")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

FormstepConfig = Annotated[Union[FormstepGetAccountConfig, FormstepListWorkspacesConfig, FormstepListFormsConfig, FormstepGetFormConfig, FormstepCreateFormConfig, FormstepUpdateFormConfig, FormstepPublishFormConfig, FormstepUnpublishFormConfig, FormstepDeleteFormConfig, FormstepListFieldsConfig, FormstepListSubmissionsConfig, FormstepCreateRequestConfig, FormstepGetRequestConfig, FormstepListRequestsConfig, FormstepRemindRequestConfig, FormstepCancelRequestConfig, FormstepListShareLinksConfig, FormstepCreateShareLinkConfig, FormstepListFoldersConfig, FormstepCreateFolderConfig, FormstepOnEventConfig], Field(discriminator="operation")]


class FormstepNodeConfig(NodeConfig[FormstepConfig, FormstepAPITokenCredential]):
    pass


METHODS = {'get_account': 'me.get', 'list_workspaces': 'workspaces.list', 'list_forms': 'forms.list', 'get_form': 'forms.get', 'create_form': 'forms.create', 'update_form': 'forms.update', 'publish_form': 'forms.publish', 'unpublish_form': 'forms.unpublish', 'delete_form': 'forms.delete', 'list_fields': 'fields.list', 'list_submissions': 'submissions.list', 'create_request': 'requests.create', 'get_request': 'requests.get', 'list_requests': 'requests.list', 'remind_request': 'requests.remind', 'cancel_request': 'requests.cancel', 'list_share_links': 'shareLinks.list', 'create_share_link': 'shareLinks.create', 'list_folders': 'folders.list', 'create_folder': 'folders.create'}

class FormstepNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-formstep"
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="workspaces", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return FormstepNodeConfig

    @staticmethod
    async def _request(token, method, params=None):
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request("POST", "https://api.formstep.io/api/v1",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json={"method": method, "params": params or {}})
        try:
            envelope = response.json()
        except ValueError:
            raise ValueError(f"Formstep returned an invalid response (HTTP {response.status_code})") from None
        if not isinstance(envelope, dict):
            raise ValueError("Formstep returned an invalid response envelope")
        if response.is_error or envelope.get("ok") is not True:
            error = envelope.get("error") or {}
            raise ValueError(f"Formstep {error.get('code', response.status_code)}: {error.get('message', 'Request failed')}")
        if "data" not in envelope:
            raise ValueError("Formstep returned no result data")
        return envelope["data"]

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, FormstepOnEventConfig):
            return self.no_event_output(op.operation)
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Formstep with an API token")
        # exclude_unset preserves explicit nulls (move to root / clear emoji)
        # while leaving omitted optional parameters to the provider defaults.
        params = op.model_dump(mode="json", by_alias=True, exclude_unset=True, exclude={"operation"})
        # Empty optional controls mean omit, except the API's explicit clear /
        # root-folder parameters, where null has a documented meaning.
        params = {key: value for key, value in params.items()
            if value is not None or key in {"folderId", "parentId", "emoji"}}
        if params.get("documents"):
            params["documents"] = [{key: value for key, value in document.items() if value is not None}
                for document in params["documents"]]
        data = await self._request(credential.api_token, METHODS[op.operation], params)
        output = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = FormstepOnEventConfig.model_validate(config)
        token = FormstepAPITokenCredential.model_validate(credential).api_token
        secret = secrets.token_hex(32)
        params = {"formId": op.formId, "targetUrl": webhook_url,
            "provider": "n8n", "eventType": op.event_type, "signingSecret": secret}
        # Provider is a bookkeeping label only; the published API enum offers
        # zapier/make/n8n and gives them identical delivery behavior.
        result = await cls._request(token, "webhooks.create", params)
        if not result.get("subscriptionId"):
            raise ValueError("Formstep did not return a subscription ID")
        return {"external_webhook_id": result["subscriptionId"], "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier and credential:
            token = FormstepAPITokenCredential.model_validate(credential).api_token
            await cls._request(token, "webhooks.delete", {"subscriptionId": identifier})

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: config.get(key) for key in ("formId", "event_type")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        header = next((v for k, v in headers.items() if k.lower() == "x-formstep-signature"), "")
        if not secret or not isinstance(header, str):
            return False
        parts = dict(part.strip().split("=", 1) for part in header.split(",") if "=" in part)
        timestamp, received = parts.get("t", ""), parts.get("sha256", "")
        if len(received) != 64 or any(char not in "0123456789abcdef" for char in received):
            return False
        if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12 or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") == EVENT_TYPES.get(config.get("event_type", "submission_created"))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("type") not in EVENT_TYPES.values():
            return super().resolve_agent_event(output)
        data = output.get("data") or {}
        kind = output["type"]
        request_event = kind.startswith("request.")
        record = data.get("request" if request_event else "submission") or {}
        form = data.get("form") or {}
        identifier = record.get("id")
        who = record.get("recipient") if request_event else record.get("respondentEmail")
        lines = [f"Formstep {kind}: {form.get('name') or 'form response'}",
            f"Who: {json.dumps(who, ensure_ascii=False)}",
            f"Form ID: {form.get('id')}",
            f"{'Request' if request_event else 'Submission'} ID: {identifier}",
            f"Event ID: {output.get('id')}"]
        if kind not in {"request.expired", "request.canceled"}:
            lines.append("Answers: " + json.dumps(data.get("display") or data.get("answers") or {}, ensure_ascii=False))
        if request_event:
            lines.append(f"To act: get_request requestId={identifier}")
        else:
            lines.append(f"To act: list_submissions formId={form.get('id')}")
        return {"text": "\n".join(lines), "conversation_key": str(identifier), "title": f"Formstep {kind}"}
