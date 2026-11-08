"""Docusign eSignature workflows: templates, envelopes, recipients and documents."""

import base64
from typing import Any, Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Discriminator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.docusign_oauth import resolve_account, validate_base_uri
from nodes.scopes.docusign import DOCUSIGN_SCOPES


def _operation(name: str, label: str, category: str, **extra: Any) -> Any:
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label, **extra,
    })


def _template_options() -> dict:
    return {"x-dynamic-options": {"field_name": "template_id", "placeholder": "Select a template…",
                                  "searchable": True, "allow_custom": True,
                                  "custom_placeholder": "Or paste template ID"}}


class DocusignOAuthCredential(BaseModel):
    credential_type: Literal["docusign_oauth"] = Field("docusign_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    account_id: Optional[str] = Field(None, title="Account ID")
    account_name: Optional[str] = Field(None, title="Account Name")
    base_uri: Optional[str] = Field(None, title="Account API Base URI")
    email: Optional[str] = Field(None, title="Email")

    model_config = ConfigDict(title="Docusign OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "docusign",
        "x-oauth-scopes": DOCUSIGN_SCOPES.declared_scopes(),
        "x-credential-url": "https://apps.docusign.com/admin/apps-and-keys",
    })


class GetAccount(BaseModel):
    """Read the connected eSignature account settings."""
    operation: Literal["get_account"] = _operation("get_account", "Get Account", "Account")


class ListTemplates(BaseModel):
    """List reusable templates in the connected account."""
    operation: Literal["list_templates"] = _operation("list_templates", "List Templates", "Templates")
    count: int = Field(50, ge=1, le=100, title="Maximum Results")


class GetTemplate(BaseModel):
    """Get a template's details and recipient roles."""
    operation: Literal["get_template"] = _operation("get_template", "Get Template", "Templates")
    template_id: str = Field(..., title="Template", json_schema_extra=_template_options())


class CreateFromTemplate(BaseModel):
    """Create a draft or send an envelope from a reusable template."""
    operation: Literal["create_from_template"] = _operation(
        "create_from_template", "Send From Template", "Envelopes",
        **{"x-creates-resource": True, "x-resource-type": "docusign_envelope", "x-resource-id-path": "data.envelopeId"})
    template_id: str = Field(..., title="Template", json_schema_extra=_template_options())
    signer_name: str = Field(..., title="Signer Name")
    signer_email: str = Field(..., title="Signer Email")
    role_name: str = Field("Signer", title="Template Role Name")
    email_subject: str = Field("Please sign this document", title="Email Subject")
    send_now: bool = Field(True, title="Send Now", description="Turn off to create a draft")


class SendDocument(BaseModel):
    """Create a draft or send a PDF with an anchor-positioned signature field."""
    operation: Literal["send_document"] = _operation(
        "send_document", "Send Document for Signature", "Envelopes",
        **{"x-creates-resource": True, "x-resource-type": "docusign_envelope", "x-resource-id-path": "data.envelopeId"})
    document_base64: str = Field(..., title="Document (Base64)", description="Base64 PDF content, optionally from an upstream node")
    document_name: str = Field("Document.pdf", title="Document Name")
    signer_name: str = Field(..., title="Signer Name")
    signer_email: str = Field(..., title="Signer Email")
    email_subject: str = Field("Please sign this document", title="Email Subject")
    anchor_string: str = Field("/sig1/", title="Signature Anchor", description="Text in the PDF marking where the signature goes")
    send_now: bool = Field(True, title="Send Now", description="Turn off to create a draft")


class GetEnvelope(BaseModel):
    """Read the current envelope status and details."""
    operation: Literal["get_envelope"] = _operation("get_envelope", "Get Envelope", "Envelopes")
    envelope_id: str = Field(..., title="Envelope ID")


class ListEnvelopes(BaseModel):
    """List envelopes changed since an ISO 8601 timestamp."""
    operation: Literal["list_envelopes"] = _operation("list_envelopes", "List Recent Envelopes", "Envelopes")
    from_date: str = Field(..., title="From Date", description="ISO 8601 timestamp, for example 2026-01-01T00:00:00Z")
    count: int = Field(50, ge=1, le=100, title="Maximum Results")


class ListRecipients(BaseModel):
    """Read signer and recipient status for an envelope."""
    operation: Literal["list_recipients"] = _operation("list_recipients", "List Recipients", "Envelopes")
    envelope_id: str = Field(..., title="Envelope ID")


class ListDocuments(BaseModel):
    """List documents and certificates attached to an envelope."""
    operation: Literal["list_documents"] = _operation("list_documents", "List Envelope Documents", "Documents")
    envelope_id: str = Field(..., title="Envelope ID")


class DownloadDocument(BaseModel):
    """Download a signed PDF as a file for downstream workflow steps."""
    operation: Literal["download_document"] = _operation("download_document", "Download Signed Document", "Documents")
    envelope_id: str = Field(..., title="Envelope ID")
    document_id: str = Field("combined", title="Document ID", description="Use combined for one signed PDF")


class VoidEnvelope(BaseModel):
    """Void an in-progress envelope and notify its recipients of the reason."""
    operation: Literal["void_envelope"] = _operation("void_envelope", "Void Envelope", "Envelopes")
    envelope_id: str = Field(..., title="Envelope ID")
    reason: str = Field(..., title="Reason", description="Shown to recipients")


DocusignConfig = Annotated[Union[
    GetAccount, ListTemplates, GetTemplate, CreateFromTemplate, SendDocument,
    GetEnvelope, ListEnvelopes, ListRecipients, ListDocuments, DownloadDocument, VoidEnvelope,
], Discriminator("operation")]


class DocusignNodeConfig(NodeConfig[DocusignConfig, DocusignOAuthCredential]):
    pass


class DocusignNode(WorkflowNode):
    """Run a Docusign eSignature API operation on the user's default account."""

    integration_type = "automation-docusign"
    connection_evidence = ConnectionEvidence(operation="list_templates", noun="templates", identity_operation="get_account")
    scope_registry = DOCUSIGN_SCOPES
    edit_examples = [
        "List my Docusign templates", "Send a Docusign template for signature",
        "Check the status of a Docusign envelope", "Download a completed signed document",
    ]

    @classmethod
    def get_config_model(cls):
        return DocusignNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.docusign_oauth import refresh_access_token
        fresh = await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="docusign")
        return await resolve_account(fresh)

    async def _token(self, credential: DocusignOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.docusign_oauth import refresh_access_token
        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=refresh_access_token, provider="docusign", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, data.get(key))
        return data["access_token"]

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict, context=None) -> list[dict]:
        if field_name != "template_id":
            return []
        payload = await cls._request(credential_data, "GET", "/templates", params={"count": 100})
        return [{"value": item["templateId"], "label": item.get("name") or item["templateId"]}
                for item in payload.get("envelopeTemplates", []) if item.get("templateId")]

    @staticmethod
    async def _request(credential: dict, method: str, path: str, *, params=None, json=None, raw=False):
        credential = await resolve_account(credential)
        base = validate_base_uri(credential["base_uri"])
        account = quote(credential["account_id"], safe="")
        url = f"{base}/restapi/v2.1/accounts/{account}{path}"
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(method, url, params=params, json=json,
                                            headers={"Authorization": f"Bearer {credential['access_token']}"})
        if response.is_error:
            try:
                detail = response.json().get("message") or response.json().get("errorCode")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Docusign API error {response.status_code}: {detail or 'request failed'}")
        return response.content if raw else response.json()

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, DocusignNodeConfig):
            raise ValueError("Docusign configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Docusign account")
        token = await self._token(credential)
        auth = await resolve_account(credential.model_dump())
        for key in ("account_id", "base_uri", "account_name", "email"):
            setattr(credential, key, auth.get(key))
        auth["access_token"] = token
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        params = None
        body = None
        method = "GET"
        if isinstance(op, GetAccount):
            path = ""
        elif isinstance(op, ListTemplates):
            path, params = "/templates", {"count": op.count}
        elif isinstance(op, GetTemplate):
            path = f"/templates/{quote(op.template_id, safe='')}"
        elif isinstance(op, CreateFromTemplate):
            method, path = "POST", "/envelopes"
            body = {"templateId": op.template_id, "templateRoles": [{"email": op.signer_email,
                    "name": op.signer_name, "roleName": op.role_name}],
                    "emailSubject": op.email_subject, "status": "sent" if op.send_now else "created"}
        elif isinstance(op, SendDocument):
            method, path = "POST", "/envelopes"
            encoded = op.document_base64.removeprefix("data:application/pdf;base64,")
            try:
                document = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("Document must be valid base64 PDF") from exc
            if not document.startswith(b"%PDF-") or len(document) > 10 * 1024 * 1024:
                raise ValueError("Document must be a PDF of at most 10 MB")
            body = {"emailSubject": op.email_subject, "status": "sent" if op.send_now else "created",
                    "documents": [{"documentBase64": encoded, "name": op.document_name,
                                   "fileExtension": "pdf", "documentId": "1"}],
                    "recipients": {"signers": [{"email": op.signer_email, "name": op.signer_name,
                                               "recipientId": "1", "routingOrder": "1",
                                               "tabs": {"signHereTabs": [{"anchorString": op.anchor_string,
                                                                           "anchorUnits": "pixels"}]}}]}}
        elif isinstance(op, GetEnvelope):
            path = f"/envelopes/{quote(op.envelope_id, safe='')}"
        elif isinstance(op, ListEnvelopes):
            path, params = "/envelopes", {"from_date": op.from_date, "count": op.count}
        elif isinstance(op, ListRecipients):
            path = f"/envelopes/{quote(op.envelope_id, safe='')}/recipients"
        elif isinstance(op, ListDocuments):
            path = f"/envelopes/{quote(op.envelope_id, safe='')}/documents"
        elif isinstance(op, DownloadDocument):
            path = f"/envelopes/{quote(op.envelope_id, safe='')}/documents/{quote(op.document_id, safe='')}"
            content = await self._request(auth, method, path, raw=True)
            if len(content) > 15 * 1024 * 1024:
                raise ValueError("Signed document exceeds the 15 MB workflow output limit")
            return {"status": "success", "operation": name,
                    "data": {"content": BinaryOutput(
                        data=content, content_type="application/pdf",
                        filename=f"{op.document_id}.pdf")}}
        elif isinstance(op, VoidEnvelope):
            method = "PUT"
            path = f"/envelopes/{quote(op.envelope_id, safe='')}"
            body = {"status": "voided", "voidedReason": op.reason}
        else:
            raise ValueError(f"Unsupported Docusign operation: {name}")
        payload = await self._request(auth, method, path, params=params, json=body)
        return {"status": "success", "operation": name, "data": payload}
