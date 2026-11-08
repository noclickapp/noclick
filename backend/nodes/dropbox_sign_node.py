"""Dropbox Sign v3: fixed one-request actions using a pasted API key.

Contract: https://github.com/hellosign/hellosign-openapi/blob/main/openapi-fern.yaml
Auth: https://developers.hellosign.com/api/api-reference-authentication
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.hellosign.com/v3"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
ID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class DropboxSignAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dropbox Sign API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.hellosign.com/home/myAccount#api",
            "x-credential-instructions": "Paste your Dropbox Sign API key from Settings > API. NoClick uses Basic authentication with an empty password. This key is separate from a Dropbox storage token and has account-wide permissions. Live signature requests require the appropriate API plan."
        })
    credential_type: Literal["dropbox_sign_api_key"] = Field("dropbox_sign_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if ":" in value or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Basic header or colon")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Signer(_Config):
    name: str = Field(..., min_length=1)
    email_address: EmailStr
    order: int | None = Field(None, ge=0)


class _TemplateSigner(_Config):
    role: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    email_address: EmailStr


class _CC(_Config):
    role: str = Field(..., min_length=1)
    email_address: EmailStr


class _CustomField(_Config):
    name: str = Field(..., min_length=1)
    value: str | None = None
    editor: str | None = None
    required: bool = False

    @model_validator(mode="after")
    def require_editor(self):
        if self.required and not self.editor:
            raise ValueError("A required editable merge field needs its signer role in editor")
        return self


def _array(value, item_type):
    try:
        raw = value if isinstance(value, list) else json.loads(value)
        if not isinstance(raw, list) or not raw:
            raise ValueError()
        return TypeAdapter(list[item_type]).validate_python(raw)
    except Exception:
        raise ValueError("Enter a nonempty JSON array matching the field description") from None


def _json_array(value, item_type):
    # Retain validated types on the wire (e.g. integer signer order), including
    # when an upstream expression supplies an actual array rather than JSON text.
    return TypeAdapter(list[item_type]).dump_json(_array(value, item_type), exclude_none=True).decode()


class GetAccount(_Config):
    """Read the API key owner's account."""
    operation: Literal["get_account"] = "get_account"


class _Page(_Config):
    page: int = Field(1, ge=1, description="Page number; one page is returned per execution.")
    page_size: int = Field(20, ge=1, le=100)
    account_id: str | None = Field(None, description="Team member account ID, or all. Omit for the connected account.")
    query: str | None = Field(None, description="Dropbox Sign search query.")


class ListSignatureRequests(_Page):
    """List or search signature requests, including signer status."""
    operation: Literal["list_signature_requests"] = "list_signature_requests"


class _SignatureRequest(_Config):
    signature_request_id: ID


class GetSignatureRequest(_SignatureRequest):
    """Read a signature request and its signatures."""
    operation: Literal["get_signature_request"] = "get_signature_request"


class _Send(_Config):
    title: str | None = Field(None, max_length=255)
    subject: str | None = Field(None, max_length=255)
    message: str | None = Field(None, max_length=5000)
    test_mode: bool = Field(True, description="Test requests are not legally binding. Set false to send a live signature request.")
    allow_decline: bool = False


class SendSignatureRequest(_Send):
    """Send documents at public file URLs for signatures."""
    operation: Literal["send_signature_request"] = "send_signature_request"
    file_urls: str = Field(..., description='JSON array of document URLs, e.g. ["https://example.com/contract.pdf"]. Dropbox Sign downloads these; NoClick does not fetch them.', json_schema_extra=JSON_EDITOR)
    signers: str = Field(..., description='JSON array of {"name":"Jack","email_address":"jack@example.com","order":0}.', json_schema_extra=JSON_EDITOR)
    cc_email_addresses: str | None = Field(None, description="JSON array of CC email addresses.", json_schema_extra=JSON_EDITOR)
    use_text_tags: bool = Field(False, description="Parse Dropbox Sign text tags in documents.")

    @field_validator("file_urls", mode="before")
    @classmethod
    def urls(cls, value):
        for url in _array(value, str):
            if not re.match(r"^https?://[^\s/]+/", url):
                raise ValueError("Use document HTTP or HTTPS URLs")
        return _json_array(value, str)

    @field_validator("signers", mode="before")
    @classmethod
    def signer_array(cls, value):
        return _json_array(value, _Signer)

    @field_validator("cc_email_addresses", mode="before")
    @classmethod
    def cc_array(cls, value):
        return _json_array(value, EmailStr) if value is not None else None


class SendWithTemplate(_Send):
    """Send a signature request using existing template roles and merge fields."""
    operation: Literal["send_with_template"] = "send_with_template"
    template_ids: str = Field(..., description="JSON array of template IDs in document order.", json_schema_extra=JSON_EDITOR)
    signers: str = Field(..., description='JSON array of {"role":"Client","name":"Jack","email_address":"jack@example.com"}. Roles are case-sensitive.', json_schema_extra=JSON_EDITOR)
    ccs: str | None = Field(None, description="JSON array of role and email_address objects. Required when the template has CC roles.", json_schema_extra=JSON_EDITOR)
    custom_fields: str | None = Field(None, description="JSON array of name, value and optional editor/required objects. Required for template merge fields.", json_schema_extra=JSON_EDITOR)

    @field_validator("template_ids", mode="before")
    @classmethod
    def ids(cls, value):
        return _json_array(value, ID)

    @field_validator("signers", mode="before")
    @classmethod
    def signer_array(cls, value):
        return _json_array(value, _TemplateSigner)

    @field_validator("ccs", "custom_fields", mode="before")
    @classmethod
    def extra_arrays(cls, value, info):
        return _json_array(value, _CC if info.field_name == "ccs" else _CustomField) if value is not None else None


class RemindSignatureRequest(_SignatureRequest):
    """Send a reminder email to a signer."""
    operation: Literal["remind_signature_request"] = "remind_signature_request"
    email_address: EmailStr
    name: str | None = Field(None, description="Include when multiple signers share an email address.")


class UpdateSignatureRequest(_SignatureRequest):
    """Update an existing recipient's name or email address."""
    operation: Literal["update_signature_request"] = "update_signature_request"
    signature_id: ID
    email_address: EmailStr | None = None
    name: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def require_change(self):
        if self.email_address is None and self.name is None:
            raise ValueError("Supply the recipient's new name or email address")
        return self


class CancelSignatureRequest(_SignatureRequest):
    """Queue cancellation of an incomplete request; completion arrives by provider callback."""
    operation: Literal["cancel_signature_request"] = "cancel_signature_request"


class ReleaseSignatureRequestHold(_SignatureRequest):
    """Release a held signature request so it can be signed."""
    operation: Literal["release_signature_request_hold"] = "release_signature_request_hold"


class RemoveSignatureRequestAccess(_SignatureRequest):
    """Remove the connected account's access to a request; this does not cancel it."""
    operation: Literal["remove_signature_request_access"] = "remove_signature_request_access"


class ListTemplates(_Page):
    """List or search reusable templates."""
    operation: Literal["list_templates"] = "list_templates"


class _Template(_Config):
    template_id: ID


class GetTemplate(_Template):
    """Read a template's signer roles, CC roles and fields."""
    operation: Literal["get_template"] = "get_template"


class DeleteTemplate(_Template):
    """Delete a reusable template."""
    operation: Literal["delete_template"] = "delete_template"


class GetTeam(_Config):
    """Read the connected account's team."""
    operation: Literal["get_team"] = "get_team"


class GetSignatureRequestFileUrl(_SignatureRequest):
    """Get a temporary PDF download URL without downloading the document."""
    operation: Literal["get_signature_request_file_url"] = "get_signature_request_file_url"
    force_download: Literal[0, 1] = Field(1, description="1 downloads; 0 displays in the browser. The URL expires.")


class GetTemplateFileUrl(_Template):
    """Get a temporary template PDF download URL."""
    operation: Literal["get_template_file_url"] = "get_template_file_url"
    force_download: Literal[0, 1] = 1


DropboxSignConfig = Annotated[Union[
    GetAccount, ListSignatureRequests, GetSignatureRequest, SendSignatureRequest,
    SendWithTemplate, RemindSignatureRequest, UpdateSignatureRequest,
    CancelSignatureRequest, ReleaseSignatureRequestHold, RemoveSignatureRequestAccess,
    ListTemplates, GetTemplate, DeleteTemplate, GetTeam,
    GetSignatureRequestFileUrl, GetTemplateFileUrl,
], Field(discriminator="operation")]


class DropboxSignFullConfig(NodeConfig[DropboxSignConfig, DropboxSignAPIKeyCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/account", "account"),
    "list_signature_requests": ("GET", "/signature_request/list", "signature_requests"),
    "get_signature_request": ("GET", "/signature_request/{signature_request_id}", "signature_request"),
    "send_signature_request": ("POST", "/signature_request/send", "signature_request"),
    "send_with_template": ("POST", "/signature_request/send_with_template", "signature_request"),
    "remind_signature_request": ("POST", "/signature_request/remind/{signature_request_id}", "signature_request"),
    "update_signature_request": ("POST", "/signature_request/update/{signature_request_id}", "signature_request"),
    "cancel_signature_request": ("POST", "/signature_request/cancel/{signature_request_id}", None),
    "release_signature_request_hold": ("POST", "/signature_request/release_hold/{signature_request_id}", "signature_request"),
    "remove_signature_request_access": ("POST", "/signature_request/remove/{signature_request_id}", None),
    "list_templates": ("GET", "/template/list", "templates"),
    "get_template": ("GET", "/template/{template_id}", "template"),
    "delete_template": ("POST", "/template/delete/{template_id}", None),
    "get_team": ("GET", "/team", "team"),
    "get_signature_request_file_url": ("GET", "/signature_request/files_as_file_url/{signature_request_id}", "file_url"),
    "get_template_file_url": ("GET", "/template/files_as_file_url/{template_id}", "file_url"),
}


class DropboxSignNode(WorkflowNode):
    integration_type = "automation-dropbox-sign"
    connection_evidence = ConnectionEvidence(noun="signature requests", operation="list_signature_requests",
        label_keys=("title", "subject", "signature_request_id"), identity_operation="get_account",
        identity_keys=("email_address", "account_id"))

    @classmethod
    def get_config_model(cls):
        return DropboxSignFullConfig

    @staticmethod
    def _check_credential_family(data):
        credential = data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type") not in (None, "dropbox_sign_api_key"):
            raise ValueError("Attach a Dropbox Sign API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Dropbox Sign API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route, envelope = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("signature_request_id", "template_id"):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", values.pop(field))
        for field in ("file_urls", "signers", "cc_email_addresses", "template_ids", "ccs", "custom_fields"):
            if field in values:
                values[field] = json.loads(values[field])
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route,
                    auth=httpx.BasicAuth(key, ""), headers={"Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values} if values else {}))
        except httpx.HTTPError:
            return {"status": "error" if method == "GET" else "unknown", "success": False,
                "error": "Dropbox Sign request did not complete; inspect write state before retrying"}
        # An acknowledgement does not claim email delivery or readback verification.
        if response.is_success and envelope is None and not response.content:
            return {"status": "success", "success": True, "http_status": response.status_code, "acknowledged": True}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "success": False, "http_status": response.status_code,
                "error": "Dropbox Sign returned a non-JSON response"}
        if not isinstance(payload, dict):
            return {"status": "error", "success": False, "error": "Dropbox Sign returned an invalid response"}
        if not response.is_success or "error" in payload:
            error = payload.get("error")
            message = error.get("error_msg") if isinstance(error, dict) else None
            message = message if isinstance(message, str) else "Dropbox Sign rejected the request"
            return {"status": "error", "success": False, "http_status": response.status_code,
                "error": message.replace(key, "[redacted]")}
        if envelope is not None:
            expected = list if envelope in {"signature_requests", "templates"} else str if envelope == "file_url" else dict
            if not isinstance(payload.get(envelope), expected):
                return {"status": "error", "success": False, "error": "Dropbox Sign response is missing the expected resource"}
        # Keep documented resources, warnings and list_info. File URLs are returned
        # as metadata, never fetched or converted to base64 document output.
        return {**payload, "status": "success", "success": True, "http_status": response.status_code,
            **({"acknowledged": True} if envelope is None else {})}
