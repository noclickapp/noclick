"""Lettr Email API 1.0.0: fixed, single-request operations.

Published contract: https://docs.lettr.com/openapi.json
List operations return one page and retain the provider pagination metadata.
Mutations are never retried automatically.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import AnyUrl, BaseModel, ConfigDict, EmailStr, Field, Json, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.lettr.com/api"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class LettrAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Lettr API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.lettr.com/api-keys",
        "x-credential-instructions": "Create a Full Access API key in your Lettr dashboard under API Keys, then paste it without the Bearer prefix. Sending Only keys cannot read connection evidence or manage resources. NoClick sends it only to app.lettr.com. Connecting reads your sending domains and team information.",
    })
    credential_type: Literal["lettr_api_key"] = Field("lettr_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def editor_values(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for name, field in cls.model_fields.items():
            key = field.alias or name
            for candidate in {key, name}:
                if (field.json_schema_extra or {}).get("ui:widget") == "code_editor" and isinstance(value.get(candidate), (dict, list)):
                    value[candidate] = json.dumps(value[candidate])
        return value

class LettrSendEmailConfigOptions(_Input):
    click_tracking: StrictBool | None = Field(None, description='Enable click tracking for links in the email')
    open_tracking: StrictBool | None = Field(None, description='Enable open tracking via tracking pixel')
    transactional: StrictBool | None = Field(True, description='Mark email as transactional (not marketing). **Defaults to `true`.** Transactional mail bypasses unsubscribe suppression, so any send a recipient can opt out of must explicitly set this to `false`.')
    inline_css: StrictBool | None = Field(None, description='Inline CSS styles in HTML content')
    perform_substitutions: StrictBool | None = Field(None, description='Perform variable substitutions in content')


class LettrSendEmailConfigAttachmentsItem(_Input):
    name: str = Field(..., max_length=255, description='Filename of the attachment')
    type: str = Field(..., max_length=255, description='MIME type of the attachment')
    data: str = Field(..., pattern='^[A-Za-z0-9+/=]+$', description='Base64 encoded file content (no line breaks)')


class LettrScheduleEmailConfigOptions(_Input):
    click_tracking: StrictBool | None = Field(None, description='Enable click tracking for links in the email')
    open_tracking: StrictBool | None = Field(None, description='Enable open tracking via tracking pixel')
    transactional: StrictBool | None = Field(True, description='Mark email as transactional (not marketing). **Defaults to `true`.** Transactional mail bypasses unsubscribe suppression, so any send a recipient can opt out of must explicitly set this to `false`.')
    inline_css: StrictBool | None = Field(None, description='Inline CSS styles in HTML content')
    perform_substitutions: StrictBool | None = Field(None, description='Perform variable substitutions in content')


class LettrScheduleEmailConfigAttachmentsItem(_Input):
    name: str = Field(..., max_length=255, description='Filename of the attachment')
    type: str = Field(..., max_length=255, description='MIME type of the attachment')
    data: str = Field(..., pattern='^[A-Za-z0-9+/=]+$', description='Base64 encoded file content (no line breaks)')


class LettrDoubleOptIn(_Input):
    from_email: EmailStr = Field(..., alias='from', max_length=255)
    from_name: str | None = Field(None, max_length=255)
    subject: str = Field(..., max_length=998)
    template_slug: str = Field(..., max_length=255)
    redirect_url: AnyUrl = Field(..., max_length=2048)


class LettrCheckConnectionConfig(_Input):
    """Validate API Key."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class LettrSendEmailConfig(_Input):
    """Send Email."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, alias='Idempotency-Key', min_length=1, max_length=255, pattern='^[A-Za-z0-9._-]{1,255}$')
    from_email: EmailStr = Field(..., alias='from', max_length=255, description='Sender email address')
    from_name: str | None = Field(None, max_length=255, description='Sender display name')
    subject: str | None = Field(None, max_length=998, description="Email subject line. Required when not using a template. When using `template_slug`, defaults to the template's subject (or template name as fallback). If provided alongside a template, overrides the template subject.")
    to: Json[list[EmailStr]] = Field(..., json_schema_extra=_JSON_EDITOR, min_length=1, max_length=50, description='Recipient email addresses')
    cc: Json[list[EmailStr]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Carbon copy recipient email addresses')
    bcc: Json[list[EmailStr]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Blind carbon copy recipient email addresses')
    reply_to: EmailStr | None = Field(None, max_length=255, description='Reply-To email address')
    reply_to_name: str | None = Field(None, max_length=255, description='Reply-To display name')
    html: str | None = Field(None, description='HTML content of the email. At least one of `html` or `text` is required, but providing both is recommended for best compatibility across email clients.')
    text: str | None = Field(None, description='Plain text content of the email. At least one of `html` or `text` is required, but providing both is recommended for best compatibility across email clients.')
    amp_html: str | None = Field(None, description='AMP HTML content for supported email clients')
    project_id: int | None = Field(None, description="Project ID containing the template. If not provided when using template_slug, the team's default project will be used.")
    template_slug: str | None = Field(None, max_length=255, description="Template slug to use for email content. When provided, the template's HTML will be used instead of the html field.")
    template_version: int | None = Field(None, ge=1, description='Specific template version to use. If not provided, the active version will be used.')
    tag: str | None = Field(None, max_length=64, description='Tag for tracking and analytics. Automatically set from template_slug if not provided.')
    metadata: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Custom metadata attached to the email for tracking purposes')
    headers: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Custom email headers. Up to 10 headers allowed. Standard envelope headers (From, To, Subject, etc.), SparkPost internal headers (X-MSYS-API), and List-Unsubscribe and List-Unsubscribe-Post headers are managed by the system and cannot be set manually.')
    substitution_data: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Variables for template substitution in email content')
    options: Json[LettrSendEmailConfigOptions] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Email delivery options')
    attachments: Json[list[LettrSendEmailConfigAttachmentsItem]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='File attachments. When provided, each attachment must include name, type, and data.')

    @model_validator(mode="after")
    def content_required(self):
        if not (self.html or self.text or self.template_slug):
            raise ValueError("Supply HTML, text, or a template slug")
        if not self.template_slug and not self.subject:
            raise ValueError("Supply a subject when sending without a template")
        return self


class LettrListEmailsConfig(_Input):
    """List Sent Emails."""
    operation: Literal["list_emails"] = Field("list_emails", json_schema_extra={"ui:hidden": True})
    per_page: int | None = Field(25, ge=1, le=100)
    cursor: str | None = Field(None)
    recipients: EmailStr | None = Field(None)
    from_email: date | None = Field(None, alias='from')
    to: date | None = Field(None)


class LettrListEmailEventsConfig(_Input):
    """List Email Events."""
    operation: Literal["list_email_events"] = Field("list_email_events", json_schema_extra={"ui:hidden": True})
    events: Json[list[Literal['injection', 'delivery', 'bounce', 'delay', 'out_of_band', 'spam_complaint', 'policy_rejection', 'click', 'open', 'initial_open', 'amp_click', 'amp_open', 'amp_initial_open', 'generation_failure', 'generation_rejection', 'list_unsubscribe', 'link_unsubscribe']]] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    recipients: Json[list[EmailStr]] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    from_email: date | None = Field(None, alias='from')
    to: date | None = Field(None)
    per_page: int | None = Field(25, ge=1, le=100)
    cursor: str | None = Field(None)
    transmissions: str | None = Field(None)
    bounce_classes: str | None = Field(None)


class LettrGetEmailConfig(_Input):
    """Get Email Detail."""
    operation: Literal["get_email"] = Field("get_email", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., alias='requestId')
    from_email: date | None = Field(None, alias='from')
    to: date | None = Field(None)


class LettrScheduleEmailConfig(_Input):
    """Schedule Email."""
    operation: Literal["schedule_email"] = Field("schedule_email", json_schema_extra={"ui:hidden": True})
    from_email: EmailStr = Field(..., alias='from', max_length=255, description='Sender email address')
    from_name: str | None = Field(None, max_length=255, description='Sender display name')
    subject: str | None = Field(None, max_length=998, description="Email subject line. Required when not using a template. When using `template_slug`, defaults to the template's subject (or template name as fallback). If provided alongside a template, overrides the template subject.")
    to: Json[list[EmailStr]] = Field(..., json_schema_extra=_JSON_EDITOR, min_length=1, max_length=50, description='Recipient email addresses')
    cc: Json[list[EmailStr]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Carbon copy recipient email addresses')
    bcc: Json[list[EmailStr]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Blind carbon copy recipient email addresses')
    reply_to: EmailStr | None = Field(None, max_length=255, description='Reply-To email address')
    reply_to_name: str | None = Field(None, max_length=255, description='Reply-To display name')
    html: str | None = Field(None, description='HTML content of the email. At least one of `html` or `text` is required, but providing both is recommended for best compatibility across email clients.')
    text: str | None = Field(None, description='Plain text content of the email. At least one of `html` or `text` is required, but providing both is recommended for best compatibility across email clients.')
    amp_html: str | None = Field(None, description='AMP HTML content for supported email clients')
    project_id: int | None = Field(None, description="Project ID containing the template. If not provided when using template_slug, the team's default project will be used.")
    template_slug: str | None = Field(None, max_length=255, description="Template slug to use for email content. When provided, the template's HTML will be used instead of the html field.")
    template_version: int | None = Field(None, ge=1, description='Specific template version to use. If not provided, the active version will be used.')
    tag: str | None = Field(None, max_length=64, description='Tag for tracking and analytics. Automatically set from template_slug if not provided.')
    metadata: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Custom metadata attached to the email for tracking purposes')
    headers: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Custom email headers. Up to 10 headers allowed. Standard envelope headers (From, To, Subject, etc.), SparkPost internal headers (X-MSYS-API), and List-Unsubscribe and List-Unsubscribe-Post headers are managed by the system and cannot be set manually.')
    substitution_data: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Variables for template substitution in email content')
    options: Json[LettrScheduleEmailConfigOptions] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Email delivery options')
    attachments: Json[list[LettrScheduleEmailConfigAttachmentsItem]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='File attachments. When provided, each attachment must include name, type, and data.')
    scheduled_at: datetime = Field(..., description='The UTC date/time when the email should be sent. Must be at least 5 minutes in the future and within 30 days.')

    @model_validator(mode="after")
    def content_required(self):
        if not (self.html or self.text or self.template_slug):
            raise ValueError("Supply HTML, text, or a template slug")
        if not self.template_slug and not self.subject:
            raise ValueError("Supply a subject when sending without a template")
        return self


class LettrListScheduledEmailsConfig(_Input):
    """List Scheduled Emails."""
    operation: Literal["list_scheduled_emails"] = Field("list_scheduled_emails", json_schema_extra={"ui:hidden": True})
    status: Literal['scheduled', 'sending', 'sent', 'cancelled', 'failed'] | None = Field(None)
    per_page: int | None = Field(25, ge=1, le=100)
    page: int | None = Field(1, ge=1)


class LettrGetScheduledEmailConfig(_Input):
    """Get Scheduled Email."""
    operation: Literal["get_scheduled_email"] = Field("get_scheduled_email", json_schema_extra={"ui:hidden": True})
    transmission_id: str = Field(..., alias='transmissionId')


class LettrCancelScheduledEmailConfig(_Input):
    """Cancel Scheduled Email."""
    operation: Literal["cancel_scheduled_email"] = Field("cancel_scheduled_email", json_schema_extra={"ui:hidden": True})
    transmission_id: str = Field(..., alias='transmissionId')


class LettrListDomainsConfig(_Input):
    """List Domains."""
    operation: Literal["list_domains"] = Field("list_domains", json_schema_extra={"ui:hidden": True})


class LettrCreateDomainConfig(_Input):
    """Create Domain."""
    operation: Literal["create_domain"] = Field("create_domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., max_length=255, pattern='^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\\.)+[a-zA-Z]{2,}$', description='The domain name to register (e.g., example.com)')


class LettrGetDomainConfig(_Input):
    """Get Domain."""
    operation: Literal["get_domain"] = Field("get_domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(...)


class LettrDeleteDomainConfig(_Input):
    """Delete Domain."""
    operation: Literal["delete_domain"] = Field("delete_domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(...)


class LettrVerifyDomainConfig(_Input):
    """Verify Domain."""
    operation: Literal["verify_domain"] = Field("verify_domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(...)


class LettrListTemplatesConfig(_Input):
    """List Templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    project_id: int | None = Field(None, ge=1)
    folder_id: int | None = Field(None, ge=1)
    purpose: Literal['transactional', 'campaign'] | None = Field(None)
    per_page: int | None = Field(25, ge=1, le=100)
    page: int | None = Field(1, ge=1)


class LettrCreateTemplateConfig(_Input):
    """Create Template."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=255, description='Name of the template')
    project_id: int | None = Field(None, ge=1, description="Project ID to create the template in. If not provided, uses the team's default project.")
    folder_id: int | None = Field(None, ge=1, description='Folder ID to create the template in. Must belong to the same module as `purpose`. If not provided, the first folder of that module is used, and one is created when the project has none.')
    html: str | None = Field(None, description='HTML content for custom HTML templates. Required if `json` is not provided. Mutually exclusive with `json`.')
    content_json: str | None = Field(None, alias='json', description='JSON content for Topol visual editor templates. Required if `html` is not provided. Mutually exclusive with `html`.')
    purpose: Literal['transactional', 'campaign'] | None = Field('transactional', description='Module the template belongs to. `transactional` templates are the ones you send single emails with; `campaign` templates are the ones the campaign builder can pick. Defaults to `transactional`.')

    @model_validator(mode="after")
    def template_content(self):
        if self.html is not None and self.content_json is not None:
            raise ValueError("Supply HTML or Topol JSON, never both")
        if not (self.html or self.content_json):
            raise ValueError("Supply HTML or Topol JSON")
        if self.content_json is not None:
            json.loads(self.content_json)
        return self


class LettrGetTemplateConfig(_Input):
    """Get Template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)
    project_id: int | None = Field(None, ge=1)


class LettrUpdateTemplateConfig(_Input):
    """Update Template."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)
    project_id: int | None = Field(None, ge=1, description="Project ID to find the template in. If not provided, uses the team's default project.")
    name: str | None = Field(None, max_length=255, description='New name for the template')
    html: str | None = Field(None, description='New HTML content for the template. Creates a new active version. Mutually exclusive with `json`.')
    content_json: str | None = Field(None, alias='json', description='New JSON content for Topol visual editor templates. Creates a new active version. Mutually exclusive with `html`.')

    @model_validator(mode="after")
    def template_content(self):
        if self.html is not None and self.content_json is not None:
            raise ValueError("Supply HTML or Topol JSON, never both")
        if self.content_json is not None:
            json.loads(self.content_json)
        return self


class LettrDeleteTemplateConfig(_Input):
    """Delete Template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)
    project_id: int | None = Field(None, ge=1)


class LettrGetTemplateMergeTagsConfig(_Input):
    """Get Template Merge Tags."""
    operation: Literal["get_template_merge_tags"] = Field("get_template_merge_tags", json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)
    project_id: int | None = Field(None, ge=1)
    version: int | None = Field(None, ge=1)


class LettrListContactsConfig(_Input):
    """List audience contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(20, ge=1, le=100)
    search: str | None = Field(None, max_length=255)
    status: Literal['subscribed', 'unsubscribed', 'bounced', 'complained', 'unverified'] | None = Field(None)
    list_id: UUID | None = Field(None)
    segment_id: UUID | None = Field(None)


class LettrCreateContactConfig(_Input):
    """Create a contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., max_length=255)
    list_id: UUID | None = Field(None, description='Optional list to add the contact to. Must be a list of your team, otherwise the response is `422` with `errors.list_id`.')
    properties: Json[dict[str, str]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Custom property values. Each key must match a property defined for the team.')
    double_opt_in: Json[LettrDoubleOptIn] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Double opt-in configuration. When provided, the contact receives a confirmation email and is created in `unverified` status until they click the confirmation link.')


class LettrGetContactConfig(_Input):
    """Show a contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID = Field(..., alias='contactId')


class LettrUpdateContactConfig(_Input):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID = Field(..., alias='contactId')
    email: EmailStr | None = Field(None, max_length=255, description='New email address (must remain unique within the team)')
    status: Literal['subscribed', 'unsubscribed'] | None = Field(None)
    properties: Json[dict[str, Annotated[str, Field(max_length=1000)] | None]] | None = Field(None, json_schema_extra=_JSON_EDITOR, description='Partial property update. A property set to null is removed.')


class LettrDeleteContactConfig(_Input):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID = Field(..., alias='contactId')

LettrConfig = Annotated[Union[LettrCheckConnectionConfig, LettrSendEmailConfig, LettrListEmailsConfig, LettrListEmailEventsConfig, LettrGetEmailConfig, LettrScheduleEmailConfig, LettrListScheduledEmailsConfig, LettrGetScheduledEmailConfig, LettrCancelScheduledEmailConfig, LettrListDomainsConfig, LettrCreateDomainConfig, LettrGetDomainConfig, LettrDeleteDomainConfig, LettrVerifyDomainConfig, LettrListTemplatesConfig, LettrCreateTemplateConfig, LettrGetTemplateConfig, LettrUpdateTemplateConfig, LettrDeleteTemplateConfig, LettrGetTemplateMergeTagsConfig, LettrListContactsConfig, LettrCreateContactConfig, LettrGetContactConfig, LettrUpdateContactConfig, LettrDeleteContactConfig], Field(discriminator="operation")]

ROUTES = {'check_connection': {'method': 'GET',
                      'path': '/auth/check',
                      'path_fields': [],
                      'query_fields': [],
                      'header_fields': [],
                      'body_fields': [],
                      'csv_fields': []},
 'send_email': {'method': 'POST',
                'path': '/emails',
                'path_fields': [],
                'query_fields': [],
                'header_fields': ['Idempotency-Key'],
                'body_fields': ['from',
                                'from_name',
                                'subject',
                                'to',
                                'cc',
                                'bcc',
                                'reply_to',
                                'reply_to_name',
                                'html',
                                'text',
                                'amp_html',
                                'project_id',
                                'template_slug',
                                'template_version',
                                'tag',
                                'metadata',
                                'headers',
                                'substitution_data',
                                'options',
                                'attachments'],
                'csv_fields': []},
 'list_emails': {'method': 'GET',
                 'path': '/emails',
                 'path_fields': [],
                 'query_fields': ['per_page', 'cursor', 'recipients', 'from', 'to'],
                 'header_fields': [],
                 'body_fields': [],
                 'csv_fields': []},
 'list_email_events': {'method': 'GET',
                       'path': '/emails/events',
                       'path_fields': [],
                       'query_fields': ['events',
                                        'recipients',
                                        'from',
                                        'to',
                                        'per_page',
                                        'cursor',
                                        'transmissions',
                                        'bounce_classes'],
                       'header_fields': [],
                       'body_fields': [],
                       'csv_fields': ['events', 'recipients']},
 'get_email': {'method': 'GET',
               'path': '/emails/{requestId}',
               'path_fields': ['requestId'],
               'query_fields': ['from', 'to'],
               'header_fields': [],
               'body_fields': [],
               'csv_fields': []},
 'schedule_email': {'method': 'POST',
                    'path': '/emails/scheduled',
                    'path_fields': [],
                    'query_fields': [],
                    'header_fields': [],
                    'body_fields': ['from',
                                    'from_name',
                                    'subject',
                                    'to',
                                    'cc',
                                    'bcc',
                                    'reply_to',
                                    'reply_to_name',
                                    'html',
                                    'text',
                                    'amp_html',
                                    'project_id',
                                    'template_slug',
                                    'template_version',
                                    'tag',
                                    'metadata',
                                    'headers',
                                    'substitution_data',
                                    'options',
                                    'attachments',
                                    'scheduled_at'],
                    'csv_fields': []},
 'list_scheduled_emails': {'method': 'GET',
                           'path': '/emails/scheduled',
                           'path_fields': [],
                           'query_fields': ['status', 'per_page', 'page'],
                           'header_fields': [],
                           'body_fields': [],
                           'csv_fields': []},
 'get_scheduled_email': {'method': 'GET',
                         'path': '/emails/scheduled/{transmissionId}',
                         'path_fields': ['transmissionId'],
                         'query_fields': [],
                         'header_fields': [],
                         'body_fields': [],
                         'csv_fields': []},
 'cancel_scheduled_email': {'method': 'DELETE',
                            'path': '/emails/scheduled/{transmissionId}',
                            'path_fields': ['transmissionId'],
                            'query_fields': [],
                            'header_fields': [],
                            'body_fields': [],
                            'csv_fields': []},
 'list_domains': {'method': 'GET',
                  'path': '/domains',
                  'path_fields': [],
                  'query_fields': [],
                  'header_fields': [],
                  'body_fields': [],
                  'csv_fields': []},
 'create_domain': {'method': 'POST',
                   'path': '/domains',
                   'path_fields': [],
                   'query_fields': [],
                   'header_fields': [],
                   'body_fields': ['domain'],
                   'csv_fields': []},
 'get_domain': {'method': 'GET',
                'path': '/domains/{domain}',
                'path_fields': ['domain'],
                'query_fields': [],
                'header_fields': [],
                'body_fields': [],
                'csv_fields': []},
 'delete_domain': {'method': 'DELETE',
                   'path': '/domains/{domain}',
                   'path_fields': ['domain'],
                   'query_fields': [],
                   'header_fields': [],
                   'body_fields': [],
                   'csv_fields': []},
 'verify_domain': {'method': 'POST',
                   'path': '/domains/{domain}/verify',
                   'path_fields': ['domain'],
                   'query_fields': [],
                   'header_fields': [],
                   'body_fields': [],
                   'csv_fields': []},
 'list_templates': {'method': 'GET',
                    'path': '/templates',
                    'path_fields': [],
                    'query_fields': ['project_id', 'folder_id', 'purpose', 'per_page', 'page'],
                    'header_fields': [],
                    'body_fields': [],
                    'csv_fields': []},
 'create_template': {'method': 'POST',
                     'path': '/templates',
                     'path_fields': [],
                     'query_fields': [],
                     'header_fields': [],
                     'body_fields': ['name', 'project_id', 'folder_id', 'html', 'json', 'purpose'],
                     'csv_fields': []},
 'get_template': {'method': 'GET',
                  'path': '/templates/{slug}',
                  'path_fields': ['slug'],
                  'query_fields': ['project_id'],
                  'header_fields': [],
                  'body_fields': [],
                  'csv_fields': []},
 'update_template': {'method': 'PUT',
                     'path': '/templates/{slug}',
                     'path_fields': ['slug'],
                     'query_fields': [],
                     'header_fields': [],
                     'body_fields': ['project_id', 'name', 'html', 'json'],
                     'csv_fields': []},
 'delete_template': {'method': 'DELETE',
                     'path': '/templates/{slug}',
                     'path_fields': ['slug'],
                     'query_fields': ['project_id'],
                     'header_fields': [],
                     'body_fields': [],
                     'csv_fields': []},
 'get_template_merge_tags': {'method': 'GET',
                             'path': '/templates/{slug}/merge-tags',
                             'path_fields': ['slug'],
                             'query_fields': ['project_id', 'version'],
                             'header_fields': [],
                             'body_fields': [],
                             'csv_fields': []},
 'list_contacts': {'method': 'GET',
                   'path': '/audience/contacts',
                   'path_fields': [],
                   'query_fields': ['page', 'per_page', 'search', 'status', 'list_id', 'segment_id'],
                   'header_fields': [],
                   'body_fields': [],
                   'csv_fields': []},
 'create_contact': {'method': 'POST',
                    'path': '/audience/contacts',
                    'path_fields': [],
                    'query_fields': [],
                    'header_fields': [],
                    'body_fields': ['email', 'list_id', 'properties', 'double_opt_in'],
                    'csv_fields': []},
 'get_contact': {'method': 'GET',
                 'path': '/audience/contacts/{contactId}',
                 'path_fields': ['contactId'],
                 'query_fields': [],
                 'header_fields': [],
                 'body_fields': [],
                 'csv_fields': []},
 'update_contact': {'method': 'PATCH',
                    'path': '/audience/contacts/{contactId}',
                    'path_fields': ['contactId'],
                    'query_fields': [],
                    'header_fields': [],
                    'body_fields': ['email', 'status', 'properties'],
                    'csv_fields': []},
 'delete_contact': {'method': 'DELETE',
                    'path': '/audience/contacts/{contactId}',
                    'path_fields': ['contactId'],
                    'query_fields': [],
                    'header_fields': [],
                    'body_fields': [],
                    'csv_fields': []}}

class LettrFullConfig(NodeConfig[LettrConfig, LettrAPIKeyCredential]):
    pass


class LettrNode(WorkflowNode):
    integration_type = "automation-lettr"
    connection_evidence = ConnectionEvidence(noun="sending domains", operation="list_domains", label_keys=("domain",), identity_operation="check_connection")

    @classmethod
    def get_config_model(cls):
        return LettrFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            return {"status": "error", "message": "Attach a Lettr API key"}
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True)
        path = route["path"]
        for name in route["path_fields"]:
            value = str(values[name])
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#"):
                return {"status": "error", "message": "Use a single Lettr resource identifier"}
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {name: values[name] for name in route["query_fields"] if name in values}
        for name in route["csv_fields"]:
            if name in params:
                params[name] = ",".join(params[name])
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"}
        headers.update({name: values[name] for name in route["header_fields"] if name in values})
        body = {name: values[name] for name in route["body_fields"] if name in values}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], BASE + path, params=params, headers=headers,
                    **({"json": body} if route["body_fields"] else {}))
            if not 200 <= response.status_code < 300:
                message = "Lettr request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"][:1000].replace(self.config.credentials.api_key, "[redacted]")
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code, "message": message}
            if response.status_code == 204:
                return {"status": "success", "data": None}
            if len(response.content) > 10_000_000:
                raise ValueError("Lettr response exceeded the JSON size limit")
            body = response.json()
            if not isinstance(body, dict) or body.get("success") is False or body.get("error_code"):
                raise ValueError("Lettr returned an unsuccessful response")
            result = {"status": "success", "data": body}
            if config.operation == "list_domains":
                domains = body.get("data", {}).get("domains")
                if not isinstance(domains, list):
                    raise ValueError("Lettr did not return sending domains")
                result["items"] = domains
            elif config.operation == "check_connection":
                team = body.get("data", {}).get("team_id")
                if not isinstance(team, int) or isinstance(team, bool):
                    raise ValueError("Lettr did not return the team ID")
                result["name"] = "Lettr team " + str(team)
            return result
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return {"status": "error", "message": "Lettr request could not be confirmed"}
