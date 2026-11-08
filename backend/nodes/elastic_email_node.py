"""Elastic Email v4 contacts, lists, templates and transactional delivery.

Contract: https://api.elasticemail.com/public/v4/swagger (4.0.0).
Each operation performs one documented request using a pasted API key. Lists
return one explicit offset page; sends report acceptance rather than delivery.
"""
from __future__ import annotations

import json

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.elasticemail.com/v4"
CREDENTIAL_TYPE = "elastic_email_api_key"
Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")]
Name = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[^\x00-\x1f\x7f]+$")]
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
LIST_EDITOR = {"ui:widget": "list"}


def _json_fields(value):
    if value is None:
        return None
    try:
        fields = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("Provide a JSON object with string values") from None
    if not isinstance(fields, dict) or any(not isinstance(v, str) for v in fields.values()):
        raise ValueError("Provide a JSON object with string values")
    return value


class ElasticEmailAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Elastic Email API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.elasticemail.com/marketing/settings/new/manage-api",
            "x-credential-instructions": "Paste an Elastic Email v4 API key. Enable ViewContacts and ViewAccount for connection evidence and account details; ModifyContacts for contact and list writes; ViewTemplates and ModifyTemplates for templates; SendHttp for sending; ViewReports for delivery status. NoClick sends the key only to api.elasticemail.com.",
        })
    credential_type: Literal["elastic_email_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def shape_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API Key", key=True)
        if any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Config):
    limit: int = Field(100, ge=1, le=1000, title="Page Size")
    offset: int = Field(0, ge=0, le=2_147_483_647, title="Offset",
        description="Fetch one page. Continue with next_offset until has_more is false.")


class _Contact(_Config):
    email: Email = Field(..., title="Contact Email")


class _List(_Config):
    name: Name = Field(..., title="List Name")


class _Template(_Config):
    name: Name = Field(..., title="Template Name")


class GetAccount(_Config):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})


class AddContacts(_Contact):
    operation: Literal["add_contacts"] = Field("add_contacts", title="Add Contact", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, max_length=500, title="First Name")
    last_name: str | None = Field(None, max_length=500, title="Last Name")
    custom_fields_json: str | None = Field(None, title="Custom Fields JSON", description='JSON object with string values, for example {"city":"New York","age":"34"}. Only existing custom fields are saved.', json_schema_extra=JSON_EDITOR)
    listnames: list[Name] | None = Field(None, max_length=100, title="Add to Lists", json_schema_extra=LIST_EDITOR)

    _custom_fields = field_validator("custom_fields_json")(_json_fields)


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(_Contact):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, max_length=500, title="First Name")
    last_name: str | None = Field(None, max_length=500, title="Last Name")
    custom_fields_json: str | None = Field(None, title="Custom Fields JSON", description="JSON object with string values.", json_schema_extra=JSON_EDITOR)

    _custom_fields = field_validator("custom_fields_json")(_json_fields)

    @model_validator(mode="after")
    def changed_field(self):
        if all(getattr(self, key) is None for key in ("first_name", "last_name", "custom_fields_json")):
            raise ValueError("Provide a contact field to update; omitted fields remain unchanged")
        return self


class DeleteContact(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class ListLists(_Page):
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})


class CreateList(_Config):
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    list_name: Name = Field(..., title="New List Name")
    emails: list[Email] = Field(..., min_length=1, max_length=1000, title="Existing Contact Emails",
        description="Explicit existing contacts to add. Elastic Email treats empty or omitted Emails as all contacts.", json_schema_extra=LIST_EDITOR)
    allow_unsubscribe: bool = Field(True, title="Allow Unsubscribe")


class GetList(_List):
    operation: Literal["get_list"] = Field("get_list", title="Get List", json_schema_extra={"ui:hidden": True})


class UpdateList(_List):
    operation: Literal["update_list"] = Field("update_list", title="Update List", json_schema_extra={"ui:hidden": True})
    new_list_name: Name | None = Field(None, title="New List Name")
    allow_unsubscribe: bool | None = Field(None, title="Allow Unsubscribe")

    @model_validator(mode="after")
    def changed_field(self):
        if self.new_list_name is None and self.allow_unsubscribe is None:
            raise ValueError("Provide a new name or unsubscribe preference")
        return self


class DeleteList(_List):
    operation: Literal["delete_list"] = Field("delete_list", title="Delete List", description="Deletes the list and its memberships; contacts remain.", json_schema_extra={"ui:hidden": True})


class ListListContacts(_List, _Page):
    operation: Literal["list_list_contacts"] = Field("list_list_contacts", title="List Contacts in List", json_schema_extra={"ui:hidden": True})


class _ListEmails(_List):
    emails: list[Email] = Field(..., min_length=1, max_length=1000, title="Contact Emails", json_schema_extra=LIST_EDITOR)


class AddListContacts(_ListEmails):
    operation: Literal["add_list_contacts"] = Field("add_list_contacts", title="Add Contacts to List", json_schema_extra={"ui:hidden": True})


class RemoveListContacts(_ListEmails):
    operation: Literal["remove_list_contacts"] = Field("remove_list_contacts", title="Remove Contacts from List", json_schema_extra={"ui:hidden": True})


class ListTemplates(_Page):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})
    scope_type: Literal["Personal", "Global"] = Field("Personal", title="Template Scope")


class _TemplateContent(_Config):
    subject: str = Field(..., min_length=1, max_length=1000, title="Subject")
    body: str = Field(..., min_length=1, max_length=1_000_000, title="Body", json_schema_extra={"ui:widget": "textarea"})
    content_type: Literal["HTML", "PlainText", "AMP", "CSS"] = Field("HTML", title="Content Type")
    template_scope: Literal["Personal", "Global"] = Field("Personal", title="Template Scope")


class CreateTemplate(_Template, _TemplateContent):
    operation: Literal["create_template"] = Field("create_template", title="Create Template", json_schema_extra={"ui:hidden": True})


class GetTemplate(_Template):
    operation: Literal["get_template"] = Field("get_template", title="Get Template", json_schema_extra={"ui:hidden": True})


class UpdateTemplate(_Template, _TemplateContent):
    operation: Literal["update_template"] = Field("update_template", title="Replace Template", description="Overwrites existing template data with the supplied subject, body and scope.", json_schema_extra={"ui:hidden": True})


class DeleteTemplate(_Template):
    operation: Literal["delete_template"] = Field("delete_template", title="Delete Template", json_schema_extra={"ui:hidden": True})


class SendTransactionalEmail(_Config):
    operation: Literal["send_transactional_email"] = Field("send_transactional_email", title="Send Transactional Email", description="To and CC recipients are visible to each other. Success means accepted, not delivered.", json_schema_extra={"ui:hidden": True})
    from_email: Name = Field(..., title="From", description="Verified sender address, optionally with a display name.")
    to: list[Email] = Field(..., min_length=1, max_length=1000, title="To", json_schema_extra=LIST_EDITOR)
    cc: list[Email] | None = Field(None, max_length=1000, title="CC", json_schema_extra=LIST_EDITOR)
    bcc: list[Email] | None = Field(None, max_length=1000, title="BCC", json_schema_extra=LIST_EDITOR)
    subject: str | None = Field(None, max_length=1000, title="Subject")
    body: str | None = Field(None, max_length=1_000_000, title="Body", json_schema_extra={"ui:widget": "textarea"})
    content_type: Literal["HTML", "PlainText"] = Field("HTML", title="Content Type")
    template_name: Name | None = Field(None, title="Template Name")
    merge_json: str | None = Field(None, title="Merge Fields JSON", description="JSON object with string values.", json_schema_extra=JSON_EDITOR)

    _merge = field_validator("merge_json")(_json_fields)
    reply_to: Name | None = Field(None, title="Reply To")
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[\x20-\x7E]+$", title="Idempotency Key",
        description="Reuse the same key and identical content only when retrying this send; retained by Elastic Email for 24 hours.")

    @model_validator(mode="after")
    def content_required(self):
        if not self.template_name and (not self.subject or not self.body):
            raise ValueError("Provide a template name or both subject and body")
        return self


class GetEmailStatus(_Config):
    operation: Literal["get_email_status"] = Field("get_email_status", title="Get Email Status", json_schema_extra={"ui:hidden": True})
    transaction_id: Name = Field(..., title="Transaction ID")
    show_failed: bool = Field(False, title="Include Failed")
    show_sent: bool = Field(False, title="Include Sent")
    show_delivered: bool = Field(False, title="Include Delivered")
    show_pending: bool = Field(False, title="Include Pending")
    show_opened: bool = Field(False, title="Include Opened")
    show_clicked: bool = Field(False, title="Include Clicked")
    show_abuse: bool = Field(False, title="Include Abuse Reports")
    show_unsubscribed: bool = Field(False, title="Include Unsubscribed")
    show_errors: bool = Field(False, title="Include Errors")
    show_message_ids: bool = Field(False, title="Include Message IDs")


ElasticEmailConfig = Annotated[Union[GetAccount, ListContacts, AddContacts, GetContact, UpdateContact,
    DeleteContact, ListLists, CreateList, GetList, UpdateList, DeleteList, ListListContacts,
    AddListContacts, RemoveListContacts, ListTemplates, CreateTemplate, GetTemplate,
    UpdateTemplate, DeleteTemplate, SendTransactionalEmail, GetEmailStatus], Field(discriminator="operation")]


class ElasticEmailFullConfig(NodeConfig[ElasticEmailConfig, ElasticEmailAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# One native operation, one provider operation. No preflight reads or hidden retries.
ROUTES = {
    "get_account": ("GET", "/account", "object"),
    "list_contacts": ("GET", "/contacts", "array"),
    "add_contacts": ("POST", "/contacts", "array"),
    "get_contact": ("GET", "/contacts/{email}", "object"),
    "update_contact": ("PUT", "/contacts/{email}", "object"),
    "delete_contact": ("DELETE", "/contacts/{email}", "empty"),
    "list_lists": ("GET", "/lists", "array"),
    "create_list": ("POST", "/lists", "object"),
    "get_list": ("GET", "/lists/{name}", "object"),
    "update_list": ("PUT", "/lists/{name}", "object"),
    "delete_list": ("DELETE", "/lists/{name}", "empty"),
    "list_list_contacts": ("GET", "/lists/{listname}/contacts", "array"),
    "add_list_contacts": ("POST", "/lists/{name}/contacts", "object"),
    "remove_list_contacts": ("POST", "/lists/{name}/contacts/remove", "empty"),
    "list_templates": ("GET", "/templates", "array"),
    "create_template": ("POST", "/templates", "object"),
    "get_template": ("GET", "/templates/{name}", "object"),
    "update_template": ("PUT", "/templates/{name}", "object"),
    "delete_template": ("DELETE", "/templates/{name}", "empty"),
    "send_transactional_email": ("POST", "/emails/transactional", "object"),
    "get_email_status": ("GET", "/emails/{transactionid}/status", "object"),
}


def _segment(value):
    if value in {".", ".."}:
        raise ValueError("Resource name cannot be a path navigation segment")
    return quote(value, safe="")


def _request_parts(config):
    method, route, shape = ROUTES[config.operation]
    values = config.model_dump(exclude_none=True)
    for placeholder, field in (("email", "email"), ("name", "name"), ("listname", "name"), ("transactionid", "transaction_id")):
        route = route.replace("{" + placeholder + "}", _segment(values[field])) if "{" + placeholder + "}" in route else route
    params, body, headers = {}, None, {}
    if isinstance(config, _Page):
        params.update(limit=config.limit, offset=config.offset)
    if isinstance(config, AddContacts):
        contact = {target: values[key] for key, target in (("email", "Email"), ("first_name", "FirstName"), ("last_name", "LastName")) if key in values}
        if config.custom_fields_json is not None:
            contact["CustomFields"] = json.loads(config.custom_fields_json)
        body = [contact]
        if config.listnames:
            params["listnames"] = config.listnames
    elif isinstance(config, UpdateContact):
        body = {target: values[key] for key, target in (("first_name", "FirstName"), ("last_name", "LastName")) if key in values}
        if config.custom_fields_json is not None:
            body["CustomFields"] = json.loads(config.custom_fields_json)
    elif isinstance(config, CreateList):
        body = {"ListName": config.list_name, "Emails": config.emails, "AllowUnsubscribe": config.allow_unsubscribe}
    elif isinstance(config, UpdateList):
        body = {target: values[key] for key, target in (("new_list_name", "NewListName"), ("allow_unsubscribe", "AllowUnsubscribe")) if key in values}
    elif isinstance(config, _ListEmails):
        body = {"Emails": config.emails}
    elif isinstance(config, ListTemplates):
        params["scopeType"] = [config.scope_type]
    elif isinstance(config, (CreateTemplate, UpdateTemplate)):
        body = {"Name": config.name, "Subject": config.subject, "Body": [{"ContentType": config.content_type, "Content": config.body, "Charset": "utf-8"}], "TemplateScope": config.template_scope}
    elif isinstance(config, SendTransactionalEmail):
        recipients = {target: values[key] for key, target in (("to", "To"), ("cc", "CC"), ("bcc", "BCC")) if key in values}
        content = {target: values[key] for key, target in (("from_email", "From"), ("subject", "Subject"), ("template_name", "TemplateName"), ("reply_to", "ReplyTo")) if key in values}
        if config.merge_json is not None:
            content["Merge"] = json.loads(config.merge_json)
        if config.body is not None:
            content["Body"] = [{"ContentType": config.content_type, "Content": config.body, "Charset": "utf-8"}]
        body = {"Recipients": recipients, "Content": content}
        if config.idempotency_key is not None:
            headers["Idempotency-Key"] = config.idempotency_key
    elif isinstance(config, GetEmailStatus):
        for key, target in (("show_failed", "showFailed"), ("show_sent", "showSent"), ("show_delivered", "showDelivered"), ("show_pending", "showPending"), ("show_opened", "showOpened"), ("show_clicked", "showClicked"), ("show_abuse", "showAbuse"), ("show_unsubscribed", "showUnsubscribed"), ("show_errors", "showErrors"), ("show_message_ids", "showMessageIDs")):
            params[target] = "true" if values[key] else "false"
    return method, route, shape, params, body, headers


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class ElasticEmailNode(WorkflowNode):
    integration_type = "automation-elastic-email"
    connection_evidence = ConnectionEvidence(noun="Elastic Email lists", operation="list_lists",
        identity_operation="get_account", label_keys=("ListName",),
        identity_keys=("Email", "Company", "PublicAccountID"))

    @classmethod
    def get_config_model(cls):
        return ElasticEmailFullConfig

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Supply an Elastic Email API key")
        operation = config.operation
        output = {"operation": operation}
        method, route, shape, params, body, extra_headers = _request_parts(config)
        headers = {"X-ElasticEmail-ApiKey": credential.api_key, "Accept": "application/json", **extra_headers}
        try:
            async with guarded_async_client(timeout=60.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, params=params, headers=headers,
                    **({"json": body} if body is not None else {}))
            output["status_code"] = response.status_code
            if not 200 <= response.status_code < 300:
                return {**output, "status": "error", "error": _redact(response.text, credential.api_key)[:2000] or "Elastic Email rejected the request"}
            if shape == "empty" and not response.content:
                return {**output, "status": "success", "acknowledged": True}
            payload = response.json()
            if isinstance(payload, dict) and any(payload.get(key) for key in ("Error", "error", "Errors", "errors")):
                return {**output, "status": "error", "error": _redact(str(payload), credential.api_key)[:2000]}
            if shape == "empty":
                return {**output, "status": "success", "acknowledged": True}
            if (shape == "array" and (not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload))) or (shape == "object" and not isinstance(payload, dict)):
                raise ValueError("Unexpected Elastic Email response shape")
            payload = _redact(payload, credential.api_key)
            result = {**output, "status": "success", "data": payload}
            if isinstance(config, _Page):
                more = len(payload) >= config.limit
                result.update(offset=config.offset, limit=config.limit, has_more=more,
                    next_offset=config.offset + len(payload) if more else None)
            if operation == "send_transactional_email":
                result.update(accepted=True, delivery_verified=False)
            return result
        except (httpx.HTTPError, SSRFError):
            return {**output, "status": "error", "error": "Elastic Email request could not be completed; inspect writes before retrying"}
        except ValueError:
            return {**output, "status": "error", "error": "Elastic Email returned an unexpected or incomplete response"}
