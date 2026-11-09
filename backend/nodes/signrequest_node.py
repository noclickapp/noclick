"""SignRequest v1 document and signature automation.

Contract: https://signrequest.com/api/v1/schema/swagger.json (v1).
Token authentication: https://signrequest.com/api/v1/docs/#section/Getting-Started/API-Token
Each operation performs one API request; list operations return one page.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://signrequest.com/api/v1"


class SignRequestTokenCredential(BaseModel):
    model_config = ConfigDict(title="SignRequest API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://signrequest.com/#/teams",
            "x-credential-instructions": "Create an API token in your SignRequest team's API settings and paste the token here. NoClick sends it to signrequest.com using Authorization: Token. Use a sandbox team's token for testing; production sends can incur SignRequest charges.",
        })
    credential_type: Literal["signrequest_api_token"] = Field("signrequest_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without the Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Resource(_Input):
    uuid: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Resource UUID from a previous list or create operation.")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number. Each execution returns one page.")
    limit: int = Field(20, ge=1, le=100, description="Maximum results requested per page.")


class Signer(_Input):
    email: str = Field(..., min_length=1, max_length=255, json_schema_extra={"format": 'email'})
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    needs_to_sign: Optional[bool] = Field(None, description='When `false` user does not need to sign, but will receive a copy of the signed document and signing log, see: [Copy only](#section/Additional-signing-methods/Copy-only)')
    approve_only: Optional[bool] = Field(None, description='Require user to approve the document (without adding a signature), see: [Approve only](#section/Additional-signing-methods/Approve-only)')
    notify_only: Optional[bool] = Field(None, description="Send notifications about the document and a copy of the signed document and signing log, but don't require them to take any action, see: [Notify only](#section/Additional-signing-methods/Notify-only)")
    order: Optional[int] = Field(None, ge=0, le=2147483647)
    language: Optional[Literal['en', 'en-gb', 'nl', 'fr', 'de', 'he', 'da', 'fi', 'hu', 'it', 'no', 'pl', 'pt', 'es', 'sv', 'ru', 'ja']] = Field(None)
    force_language: Optional[bool] = Field(None)
    redirect_url: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'})
    redirect_url_declined: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'})
    embed_url_user_id: Optional[str] = Field(None, max_length=255)


class PrefillTag(_Input):
    external_id: Optional[str] = Field(None, max_length=255)
    text: Optional[str] = Field(None)
    checkbox_value: Optional[bool] = Field(None)
    date_value: Optional[str] = Field(None, json_schema_extra={"format": 'date'})


class _DocumentFields(_Input):
    name: Optional[str] = Field(None, max_length=255, description='Defaults to filename, including extension')
    external_id: Optional[str] = Field(None, max_length=255, description='ID used to reference document in external system')
    file_from_url: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'}, description='Publicly accessible URL of document to be downloaded by SignRequest')
    template: Optional[str] = Field(None, json_schema_extra={"format": 'uri'})
    prefill_tags: Optional[list[PrefillTag]] = Field(None, description='Prefill signer input data, see [prefill tags](#section/Preparing-a-document/Prefill-tags-templates)')
    events_callback_url: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'}, description='URL at which to receive [event callbacks](#section/Events/Events-callback) for this document')
    auto_delete_days: Optional[int] = Field(None, ge=1, le=730, description='Number of days after which a finished document (signed/cancelled/declined) will be automatically deleted')
    auto_expire_days: Optional[int] = Field(None, ge=1, le=730, description='Number of days after which a non finished document will be automatically expired')


    @field_validator("file_from_url", "template")
    @classmethod
    def source_url(cls, value):
        if value is not None and not re.match(r"^https?://[^/]+", value):
            raise ValueError("Use an absolute HTTP or HTTPS source URL")
        return value


class _SignatureFields(_Input):
    document: str = Field(..., json_schema_extra={"format": 'uri'})
    from_email: Optional[str] = Field(None, min_length=1, max_length=255, json_schema_extra={"format": 'email'}, description='Email of user sending the SignRequest (must be a validated email)')
    from_email_name: Optional[str] = Field(None, max_length=255, description='Name to be used in the `From` email header, e.g. `{from_email_name} <no-reply@signrequest.com>`')
    signers: list[Signer] = Field(..., min_length=1)
    subject: Optional[str] = Field(None, max_length=512, description='Subject of SignRequest email')
    message: Optional[str] = Field(None, description='Message to include in SignRequest email, may contain the following html tags: `a`, `abbr`, `acronym`, `b`, `blockquote`, `code`, `em`, `i`, `ul`, `li`, `ol`, and `strong`')
    who: Optional[Literal['m', 'mo', 'o']] = Field(None, description='`m`: only me, `mo`: me and others, `o`: only others')
    send_reminders: Optional[bool] = Field(None, description='Automatically remind signers to sign a document, see: [automatic reminders](#section/Working-with-a-SignRequest/Automatic-reminders)')
    is_being_prepared: Optional[bool] = Field(None, description='Have the sender of a SignRequest prepare the document before sending the request out, see: [prepare using the web interface](#section/Preparing-a-document/Prepare-using-the-web-interface)')
    disable_emails: Optional[bool] = Field(None, description='Disable all SignRequest status emails as well as the email that contains the signed documents')
    redirect_url: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'}, description='URL at which SignRequest will redirect to when a document is signed')
    redirect_url_declined: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'}, description='URL at which SignRequest will redirect to when a document is declined')


class ListDocumentsConfig(_Page):
    """Retrieve a list of Documents."""
    operation: Literal['list_documents'] = Field('list_documents', json_schema_extra={"ui:hidden": True})
    external_id: Optional[str] = Field(None)
    signrequest__who: Optional[str] = Field(None)
    signrequest__from_email: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    user__email: Optional[str] = Field(None)
    user__first_name: Optional[str] = Field(None)
    user__last_name: Optional[str] = Field(None)
    created: Optional[str] = Field(None)
    modified: Optional[str] = Field(None)


class GetDocumentConfig(_Resource):
    """Retrieve a Document."""
    operation: Literal['get_document'] = Field('get_document', json_schema_extra={"ui:hidden": True})


class CreateDocumentConfig(_DocumentFields):
    """Create a Document."""
    operation: Literal['create_document'] = Field('create_document', json_schema_extra={"ui:hidden": True})


class DeleteDocumentConfig(_Resource):
    """Delete a Document."""
    operation: Literal['delete_document'] = Field('delete_document', json_schema_extra={"ui:hidden": True})


class SearchDocumentsConfig(_Page):
    """Search documents."""
    operation: Literal['search_documents'] = Field('search_documents', json_schema_extra={"ui:hidden": True})
    q: Optional[str] = Field(None, description='Normal search query')
    autocomplete: Optional[str] = Field(None, description='Partial search query')
    name: Optional[str] = Field(None, description='Document name')
    subdomain: Optional[str] = Field(None)
    signer_emails: Optional[str] = Field(None, description='Email needed to sign/approve')
    status: Optional[str] = Field(None, description='`co`: converting, `ne`: new, `se`: sent, `vi`: viewed, `si`: signed, `do`: downloaded, `sd`: signed and downloaded, `ca`: cancelled, `de`: declined, `ec`: error converting, `es`: error sending, `xp`: expired')
    who: Optional[str] = Field(None, description='`m`: only me, `mo`: me and others, `o`: only others')
    format: Optional[str] = Field(None, description='Export format, can be `json` (default), `csv`, or `xls`')
    signer_data: Optional[float] = Field(None, description='Set to `1` to export with each signer on a separate row')


class ListDocumentAttachmentsConfig(_Page):
    """Retrieve a list of Document Attachments."""
    operation: Literal['list_document_attachments'] = Field('list_document_attachments', json_schema_extra={"ui:hidden": True})
    document__uuid: Optional[str] = Field(None)
    document__external_id: Optional[str] = Field(None)
    created: Optional[str] = Field(None)


class GetDocumentAttachmentConfig(_Resource):
    """Retrieve a Document Attachment."""
    operation: Literal['get_document_attachment'] = Field('get_document_attachment', json_schema_extra={"ui:hidden": True})


class CreateDocumentAttachmentConfig(_Input):
    """Create a Document Attachment."""
    operation: Literal['create_document_attachment'] = Field('create_document_attachment', json_schema_extra={"ui:hidden": True})
    document: str = Field(..., json_schema_extra={"format": 'uri'})
    file_from_url: str = Field(..., max_length=2100, json_schema_extra={"format": 'uri'}, description='Publicly accessible URL of document to be downloaded by SignRequest')
    name: Optional[str] = Field(None, max_length=255, description='Defaults to filename, including extension')


class ListSignrequestsConfig(_Page):
    """Retrieve a list of SignRequests."""
    operation: Literal['list_signrequests'] = Field('list_signrequests', json_schema_extra={"ui:hidden": True})
    who: Optional[str] = Field(None)
    from_email: Optional[str] = Field(None)


class GetSignrequestConfig(_Resource):
    """Retrieve a SignRequest."""
    operation: Literal['get_signrequest'] = Field('get_signrequest', json_schema_extra={"ui:hidden": True})


class CreateSignrequestConfig(_SignatureFields):
    """Create a SignRequest."""
    operation: Literal['create_signrequest'] = Field('create_signrequest', json_schema_extra={"ui:hidden": True})


class QuickCreateSignrequestConfig(_DocumentFields):
    """Quick create a SignRequest."""
    operation: Literal['quick_create_signrequest'] = Field('quick_create_signrequest', json_schema_extra={"ui:hidden": True})
    from_email: Optional[str] = Field(None, min_length=1, max_length=255, json_schema_extra={"format": 'email'}, description='Email of user sending the SignRequest (must be a validated email)')
    from_email_name: Optional[str] = Field(None, max_length=255, description='Name to be used in the `From` email header, e.g. `{from_email_name} <no-reply@signrequest.com>`')
    signers: list[Signer] = Field(..., min_length=1)
    subject: Optional[str] = Field(None, max_length=512, description='Subject of SignRequest email')
    message: Optional[str] = Field(None, description='Message to include in SignRequest email, may contain the following html tags: `a`, `abbr`, `acronym`, `b`, `blockquote`, `code`, `em`, `i`, `ul`, `li`, `ol`, and `strong`')
    who: Optional[Literal['m', 'mo', 'o']] = Field(None, description='`m`: only me, `mo`: me and others, `o`: only others')
    send_reminders: Optional[bool] = Field(None, description='Automatically remind signers to sign a document, see: [automatic reminders](#section/Working-with-a-SignRequest/Automatic-reminders)')
    is_being_prepared: Optional[bool] = Field(None, description='Have the sender of a SignRequest prepare the document before sending the request out, see: [prepare using the web interface](#section/Preparing-a-document/Prepare-using-the-web-interface)')
    disable_emails: Optional[bool] = Field(None, description='Disable all SignRequest status emails as well as the email that contains the signed documents')
    redirect_url: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'}, description='URL at which SignRequest will redirect to when a document is signed')
    redirect_url_declined: Optional[str] = Field(None, max_length=2100, json_schema_extra={"format": 'uri'}, description='URL at which SignRequest will redirect to when a document is declined')


class CancelSignrequestConfig(_Resource):
    """Cancel a SignRequest."""
    operation: Literal['cancel_signrequest'] = Field('cancel_signrequest', json_schema_extra={"ui:hidden": True})


class ResendSignrequestEmailConfig(_Resource):
    """Resend a SignRequest."""
    operation: Literal['resend_signrequest_email'] = Field('resend_signrequest_email', json_schema_extra={"ui:hidden": True})


class ForwardSignerConfig(_Resource):
    """Forward a SignRequest to a different signer by email."""
    operation: Literal['forward_signer'] = Field('forward_signer', json_schema_extra={"ui:hidden": True})
    signer_email_to_forward: str = Field(..., min_length=1, json_schema_extra={"format": 'email'}, description='Email of the signer that forwards the SignRequest.')
    signer_email_to_forward_to: str = Field(..., min_length=1, json_schema_extra={"format": 'email'}, description='Email of the new signer to forward this SignRequest to.')
    forwarded_reason: Optional[str] = Field(None, min_length=1, max_length=1000, description='A reason why this SignRequest is forwarded (optional), this will be visible to all parties involved')


class ListTemplatesConfig(_Page):
    """Retrieve a list of Templates."""
    operation: Literal['list_templates'] = Field('list_templates', json_schema_extra={"ui:hidden": True})


class GetTemplateConfig(_Resource):
    """Retrieve a Template."""
    operation: Literal['get_template'] = Field('get_template', json_schema_extra={"ui:hidden": True})


class ListEventsConfig(_Page):
    """Retrieve a list of Events."""
    operation: Literal['list_events'] = Field('list_events', json_schema_extra={"ui:hidden": True})
    document__uuid: Optional[str] = Field(None)
    document__external_id: Optional[str] = Field(None)
    document__signrequest__who: Optional[str] = Field(None)
    document__signrequest__from_email: Optional[str] = Field(None)
    document__status: Optional[str] = Field(None)
    document__user__email: Optional[str] = Field(None)
    document__user__first_name: Optional[str] = Field(None)
    document__user__last_name: Optional[str] = Field(None)
    delivered: Optional[str] = Field(None)
    delivered_on: Optional[str] = Field(None)
    timestamp: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    event_type: Optional[str] = Field(None)


class GetEventConfig(_Resource):
    """Retrieve an Event."""
    operation: Literal['get_event'] = Field('get_event', json_schema_extra={"ui:hidden": True})


class ListTeamsConfig(_Page):
    """Retrieve a list of Teams."""
    operation: Literal['list_teams'] = Field('list_teams', json_schema_extra={"ui:hidden": True})


class GetTeamConfig(_Input):
    """Retrieve a Team."""
    operation: Literal['get_team'] = Field('get_team', json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


SignRequestOperation = Annotated[Union[
    ListDocumentsConfig,
    GetDocumentConfig,
    CreateDocumentConfig,
    DeleteDocumentConfig,
    SearchDocumentsConfig,
    ListDocumentAttachmentsConfig,
    GetDocumentAttachmentConfig,
    CreateDocumentAttachmentConfig,
    ListSignrequestsConfig,
    GetSignrequestConfig,
    CreateSignrequestConfig,
    QuickCreateSignrequestConfig,
    CancelSignrequestConfig,
    ResendSignrequestEmailConfig,
    ForwardSignerConfig,
    ListTemplatesConfig,
    GetTemplateConfig,
    ListEventsConfig,
    GetEventConfig,
    ListTeamsConfig,
    GetTeamConfig
], Field(discriminator="operation")]


class SignRequestConfig(NodeConfig[SignRequestOperation, SignRequestTokenCredential]):
    pass


ROUTES = {'list_documents': ('GET', '/documents/', 200), 'get_document': ('GET', '/documents/{uuid}/', 200), 'create_document': ('POST', '/documents/', 201), 'delete_document': ('DELETE', '/documents/{uuid}/', 204), 'search_documents': ('GET', '/documents-search/', 200), 'list_document_attachments': ('GET', '/document-attachments/', 200), 'get_document_attachment': ('GET', '/document-attachments/{uuid}/', 200), 'create_document_attachment': ('POST', '/document-attachments/', 201), 'list_signrequests': ('GET', '/signrequests/', 200), 'get_signrequest': ('GET', '/signrequests/{uuid}/', 200), 'create_signrequest': ('POST', '/signrequests/', 201), 'quick_create_signrequest': ('POST', '/signrequest-quick-create/', 201), 'cancel_signrequest': ('POST', '/signrequests/{uuid}/cancel_signrequest/', 201), 'resend_signrequest_email': ('POST', '/signrequests/{uuid}/resend_signrequest_email/', 201), 'forward_signer': ('POST', '/signrequests/{uuid}/forward_signer/', 201), 'list_templates': ('GET', '/templates/', 200), 'get_template': ('GET', '/templates/{uuid}/', 200), 'list_events': ('GET', '/events/', 200), 'get_event': ('GET', '/events/{uuid}/', 200), 'list_teams': ('GET', '/teams/', 200), 'get_team': ('GET', '/teams/{subdomain}/', 200)}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class SignRequestNode(WorkflowNode):
    integration_type = "automation-signrequest"
    connection_evidence = ConnectionEvidence(noun="documents", operation="list_documents", label_keys=("name", "uuid"))

    @classmethod
    def get_config_model(cls):
        return SignRequestConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SignRequest API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path, expected_status = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("uuid", "subdomain"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        if config.operation in {"create_document", "quick_create_signrequest"}:
            if bool(values.get("file_from_url")) == bool(values.get("template")):
                raise ValueError("Supply exactly one document source: file_from_url or template")
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values else {})
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Token " + token, "Accept": "application/json"}, **kwargs)
        if response.status_code != expected_status:
            message = response.text[:2000]
            output = {"status": "error", "http_status": response.status_code,
                "message": _redact(message, token), "action": config.operation}
        elif expected_status == 204:
            output = {"status": "success", "action": config.operation, "deleted": True}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("SignRequest response exceeds the JSON size limit")
            body = response.json()
            if not isinstance(body, dict) or "errors" in body:
                raise ValueError("SignRequest returned an unexpected response")
            output = {"status": "success", "action": config.operation}
            if method == "GET" and "{" not in ROUTES[config.operation][1]:
                if not isinstance(body.get("results"), list) or type(body.get("count")) is not int:
                    raise ValueError("SignRequest returned an invalid result page")
                if any(not isinstance(item, dict) for item in body["results"]):
                    raise ValueError("SignRequest returned invalid result records")
                output.update(data=body["results"], count=body["count"],
                    has_more=bool(body.get("next")), next_page=config.page + 1 if body.get("next") else None)
            else:
                output["data"] = body
        output = _redact(output, token)
        await self.emit(output)
        return output
