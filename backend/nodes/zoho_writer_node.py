"""Zoho Writer document/template actions against the provider's OpenAPI 1.0.0.

Lists return one offset page. The poll trigger scans at most 2,000 documents
per tick and refuses to consume a partial scan. No download URLs are followed.
"""
from __future__ import annotations
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.zoho_writer_oauth import OAUTH_PROVIDER
from nodes.scopes.zoho_writer import ZOHO_WRITER_SCOPES
from utils.ssrf import guarded_async_client

class ZohoWriterOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Zoho Writer OAuth", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "zoho_writer",
            "x-oauth-scopes": sorted(ZOHO_WRITER_SCOPES.declared_scopes()),
            "x-credential-url": "https://api-console.zoho.com/",
            "x-credential-instructions": "Connect your US data centre Zoho account, or paste an existing OAuth access token. Pasted tokens expire unless refresh details are supplied. Document, template and search permissions are requested."})
    credential_type: Literal["zoho_writer_oauth"] = Field("zoho_writer_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, repr=False, title="Access token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, repr=False, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token expiry", description="ISO 8601 expiry of the OAuth token, when known.")
    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None: return value
        return clean_secret(value, field_name="OAuth token")

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    @field_validator("*", mode="after")
    @classmethod
    def resource_id(cls, value, info):
        if value is not None and info.field_name.endswith("_id") and info.field_name != "version_id":
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}", value):
                raise ValueError("Use a single Zoho resource ID")
        return value
    @model_validator(mode="after")
    def content_choice(self):
        sources = ("text", "template_id") if getattr(self, "operation", None) == "create_document" else ("text", "document_id") if getattr(self, "operation", None) == "create_template" else ()
        if sum(getattr(self, key, None) is not None for key in sources) > 1:
            raise ValueError("Choose one source for the content")
        if getattr(self, "date_type", None) == "custom_date":
            if self.start_time is None or self.end_time is None or self.start_time >= self.end_time:
                raise ValueError("Provide an increasing start and end time for a custom date range")
        return self

class MetadataUpdate(_Input):
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=200)
    favourite: bool | None = None
    mark_as_final: bool | None = None
    lock: bool | None = None
    state: Literal["mark_as_complete"] | None = None
    track_changes: Literal["enable", "disable"] | None = None
    @model_validator(mode="after")
    def one_change(self):
        if len(self.model_dump(exclude_none=True)) != 1:
            raise ValueError("Provide exactly one metadata change")
        return self

# method, fixed provider path, request media type, operation fields
OPS = {
    'create_document': ('POST', '/writer/api/v1/documents', 'multipart/form-data', {
        'text': (str | None, Field(None, max_length=100000, description='The plain text content to populate the new document with.')),
        'template_id': (str | None, Field(None, description='The unique ID of an existing template to copy as the new document.')),
        'filename': (str | None, Field(None, max_length=255, description='A name for the new document.')),
        'resource_type': (Literal['fillable', 'merge', 'sign', 'label'] | None, Field(None, description='The type of document to create.')),
        'folder_id': (str | None, Field(None, max_length=100, description='The ID of the folder in which to place the new document.')),
    }),
    'list_documents': ('GET', '/writer/api/v1/documents', None, {
        'offset': (int, Field(0, ge=0)),
        'limit': (int, Field(50, ge=1, le=100)),
        'sortby': (Literal['created_time', 'modified_time', 'shared_time', 'name'] | None, Field(None)),
        'sort_order_by': (Literal['ascending', 'descending'], Field('descending')),
        'category': (Literal['all', 'owned_by_me', 'shared_to_me', 'favourite', 'trashed', 'recent'], Field('all')),
        'resource_type': (str | None, Field(None)),
    }),
    'search_documents': ('GET', '/writer/api/v1/documents/search', None, {
        'query': (str, Field(..., max_length=10000)),
        'team_id': (str | None, Field(None)),
        'offset': (int, Field(0, ge=0)),
        'limit': (int, Field(50, ge=1, le=100)),
        'sortby': (Literal['name', 'created_time', 'modified_time'] | None, Field(None)),
        'sort_order_by': (Literal['ascending', 'descending'], Field('descending')),
        'date_type': (Literal['today', 'yesterday', 'last_week', 'last_month', 'last_year', 'custom_date'] | None, Field(None)),
        'start_time': (int | None, Field(None, ge=0)),
        'end_time': (int | None, Field(None, ge=0)),
    }),
    'get_document': ('GET', '/writer/api/v1/documents/{document_id}', None, {
        'document_id': (str, Field(...)),
    }),
    'get_document_metrics': ('GET', '/writer/api/v1/documents/{document_id}/metrics', None, {
        'document_id': (str, Field(...)),
    }),
    'get_document_fields': ('GET', '/writer/api/v1/documents/{document_id}/fields', None, {
        'document_id': (str, Field(...)),
    }),
    'update_document_metadata': ('POST', '/writer/api/v1/documents/{document_id}/meta', 'application/json', {
        'document_id': (str, Field(...)),
        'operations': (MetadataUpdate, Field(..., title="Metadata change")),
    }),
    'copy_document': ('POST', '/writer/api/v1/documents/{document_id}/copy', 'application/json', {
        'document_id': (str, Field(...)),
        'document_name': (str | None, Field(None, max_length=255, description='A unique name for the copied document.')),
        'format': (Literal['docx', 'zdoc', 'odt', 'html', 'pdf', 'epub', 'rtf', 'txt'], Field('zdoc', description='The format in which to store the copied document.')),
        'folder_id': (str | None, Field(None, max_length=100, description='The ID of the folder in which to store the copy. Defaults to "My Folders".')),
        'resource_type': (Literal['fillable', 'merge', 'sign'] | None, Field(None, description='Overrides the document type assigned to the copy.')),
        'from': (Literal['publish', 'editor', 'version', 'dashboard'] | None, Field(None, description='Indicates the context the copy request originated from. When set to `publish`, the copy always excludes tracked changes and comments, overriding `options.include_changes` and `options.include_comments`.\n')),
        'version_id': (int | None, Field(None, ge=0, description='The ID of the specific document version to copy. If omitted, the latest version is copied.')),
    }),
    'trash_document': ('DELETE', '/writer/api/v1/documents/{document_id}/trash', None, {
        'document_id': (str, Field(...)),
    }),
    'restore_document': ('POST', '/writer/api/v1/documents/{document_id}/restore', None, {
        'document_id': (str, Field(...)),
    }),
    'list_templates': ('GET', '/writer/api/v1/templates', None, {
        'type': (Literal['personal', 'organization'], Field('personal')),
        'offset': (int, Field(0, ge=0)),
        'limit': (int, Field(50, ge=1, le=100)),
        'sortby': (Literal['name', 'created_time', 'modified_time'] | None, Field(None)),
        'team_id': (str | None, Field(None)),
    }),
    'create_template': ('POST', '/writer/api/v1/templates', 'multipart/form-data', {
        'text': (str | None, Field(None, max_length=100000, description='The plain text content to populate the new template with.')),
        'document_id': (str | None, Field(None, description="The unique ID of an existing document or template to duplicate as the new template's content. The authenticated user must have copy access to this resource.\n")),
        'name': (str | None, Field(None, max_length=255, description='A unique name for the new template. If omitted, a default untitled name is used.\n')),
        'type': (Literal['personal', 'organization'], Field('personal', description='The category under which the template is created. Creating an `organization` template requires the template admin role in Zoho WorkDrive and a non-Personal Edition WorkDrive plan.')),
        'team_id': (str | None, Field(None, description='The unique ID of the team/organization in which to create the template. Applicable only when `type` is `organization`.\n')),
    }),
    'get_template': ('GET', '/writer/api/v1/templates/{template_id}', None, {
        'template_id': (str, Field(...)),
    }),
    'copy_template': ('POST', '/writer/api/v1/templates/{template_id}/copy', 'application/json', {
        'template_id': (str, Field(...)),
        'type': (Literal['personal', 'organization'], Field('personal', description='The category under which the copied template is created. Copying to `organization` requires the template admin role in Zoho WorkDrive and a non-Personal Edition WorkDrive plan.')),
        'name': (str | None, Field(None, max_length=255, description='A unique name for the copied template. If omitted, defaults to "Copy of" followed by the source template\'s name.\n')),
        'save_as': (Literal['document', 'template'], Field('template', description='Whether the copy is saved as a template or converted into a standalone document.\n')),
        'team_id': (str | None, Field(None, description='The unique ID of the team/organization library to copy the template into. Applicable only when copying a public template.\n')),
    }),
    'delete_template': ('DELETE', '/writer/api/v1/templates/{template_id}/delete', None, {
        'template_id': (str, Field(...)),
    }),
    'publish_document': ('POST', '/writer/api/v1/documents/{document_id}/publish', 'application/json', {
        'document_id': (str, Field(...)),
        'scope': (Literal['external', 'organization'], Field('external', description='The audience for the published document. `external` publishes the document publicly on the web, and `organization` restricts access to members of the organization.\n')),
        'auto_republish': (bool, Field(True, description='When set to `true` (default), the document is republished automatically whenever it is edited. Set to `false` to publish only the current version — later edits require another call to this operation to update the published copy.\n')),
    }),
    'unpublish_document': ('DELETE', '/writer/api/v1/documents/{document_id}/publish', None, {
        'document_id': (str, Field(...)),
    }),
}
OP_MODELS = {
    name: create_model("ZohoWriter" + "".join(w.title() for w in name.split("_")) + "Config",
        __base__=_Input,
        operation=(Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra={
            "ui:hidden": True, "x-operation-kind": "read" if spec[0] == "GET" else "write",
            "x-is-trigger": False})), **spec[3])
    for name, spec in OPS.items()
}
globals().update({model.__name__: model for model in OP_MODELS.values()})

class ZohoWriterOnNewOrUpdatedDocumentConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_document"] = Field("on_new_or_updated_document", title="On New or Updated Document", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-operation-kind": "read", "x-category": "Triggers"})
    category: Literal["all", "owned_by_me", "shared_to_me", "favourite"] = Field("all", title="Document category")

OperationConfig = Annotated[Union[tuple(OP_MODELS.values()) + (ZohoWriterOnNewOrUpdatedDocumentConfig,)], Field(discriminator="operation")]
class ZohoWriterConfig(NodeConfig[OperationConfig, ZohoWriterOAuthCredential]):
    pass

class ZohoWriterNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zoho-writer"
    scope_registry = ZOHO_WRITER_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_documents", noun="documents", label_keys=("document_name", "document_id"))
    @classmethod
    def get_config_model(cls): return ZohoWriterConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.refresh, provider="zoho_writer")

    async def _request(self, credential, method, path, *, params=None, body=None, media=None):
        kwargs = {"params": params} if params else {}
        if media == "multipart/form-data":
            # Text-only multipart still needs a boundary, even when creating a blank document.
            kwargs["files"] = {k: (None, str(v)) for k, v in (body or {}).items()} or {("name" if path == "/writer/api/v1/templates" else "filename"): (None, "Untitled")}
        elif media:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://www.zohoapis.com" + path,
                headers={"Authorization": "Bearer " + credential["access_token"], "Accept": "application/json"}, **kwargs)
        if response.status_code == 204 or (200 <= response.status_code < 300 and not response.content):
            return {"status": "success", "http_status": response.status_code, "data": {}}
        try: data = response.json()
        except ValueError: raise ValueError(f"Zoho Writer returned HTTP {response.status_code} with a non-JSON response") from None
        if not 200 <= response.status_code < 300 or isinstance(data, dict) and (data.get("error") or data.get("errorcode") or data.get("error_code")):
            message = str(data)
            for key in ("access_token", "refresh_token"):
                if credential.get(key): message = message.replace(credential[key], "[redacted]")
            raise ValueError(f"Zoho Writer HTTP {response.status_code}: {message[:1000]}")
        if not isinstance(data, (dict, list)): raise ValueError("Zoho Writer returned an unexpected response shape")
        return {"status": "success", "http_status": response.status_code, "data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        documents = output.get("documents") if isinstance(output, dict) else None
        if not isinstance(documents, list): return super().resolve_agent_event(output)
        if not documents: return None
        lines = [f"Zoho Writer: {len(documents)} new or updated document(s)"]
        for row in documents[:20]:
            people = row.get("lastmodified_by") or []
            who = ", ".join(person.get("display_name", "") for person in people if isinstance(person, dict))
            lines.append(f"{row.get('document_name') or row['document_id']} — modified {row['modified_time']}" + (f" by {who}" if who else ""))
            lines.append(f"Document ID: {row['document_id']}")
            if row.get("open_url"): lines.append(f"Open: {row['open_url']}")
        lines.append("Use get_document with a document_id to inspect the document, or update_document_metadata to change its metadata.")
        return {"text": "\n".join(lines), "title": "Zoho Writer document changes"}

    async def _poll_documents(self, credential, config):
        documents = []
        for offset in range(0, 2000, 100):
            result = await self._request(credential, "GET", "/writer/api/v1/documents", params={
                "offset": offset, "limit": 100, "category": config.category,
                "sortby": "modified_time", "sort_order_by": "descending"})
            data = result["data"]
            rows = data.get("documents") if isinstance(data, dict) else None
            if not isinstance(rows, list): raise ValueError("Zoho Writer document list is missing")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("document_id"), str) or not isinstance(row.get("modified_time"), str):
                    raise ValueError("Zoho Writer document identity or modification time is missing")
            documents.extend(rows)
            if len(rows) < 100: break
        else: raise ValueError("More than 2,000 documents: narrow the document category before polling")
        fresh = await self._filter_unseen(documents, lambda row: row["document_id"] + ":" + row["modified_time"])
        return {"status": "success", "documents": fresh, "new_or_updated_document_count": len(fresh)}

    async def execute(self, inputs):
        if not self.config.credentials: raise ValueError("Connect a Zoho Writer account")
        credential = self.config.credentials.model_dump(exclude_none=True)
        if credential.get("refresh_token"):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=credential, refresh=OAUTH_PROVIDER.refresh, provider="zoho_writer", caller_path="execute")
        config = self.config.config
        if isinstance(config, ZohoWriterOnNewOrUpdatedDocumentConfig):
            return await self._poll_documents(credential, config)
        method, path, media, _ = OPS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        return await self._request(credential, method, path, params=values if method == "GET" else None,
            body=values if media else None, media=media)
