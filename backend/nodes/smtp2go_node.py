"""SMTP2GO v3: email delivery, sender domains, templates and suppression management.

Contract: https://developers.smtp2go.com/openapi/schema.json (v3.0.4).
All operations make one documented POST. Read operations use POST by provider design.
Sending success means API acceptance, never proof of recipient delivery.
"""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.smtp2go.com/v3"


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Smtp2GoApiKeyCredential(_Closed):
    model_config = ConfigDict(title="SMTP2GO API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.smtp2go.com/sending/apikeys/",
            "x-credential-instructions": "In SMTP2GO, open Sending > API Keys and copy an API key. Allow single_sender_emails/view for the connection check and the endpoints your workflow uses."})
    credential_type: Literal["smtp2go_api_key"] = Field("smtp2go_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", description="Paste your SMTP2GO API key without a header name or Bearer prefix.", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste an API key without spaces or control characters")
        return value


class _Operation(_Closed):
    @field_validator("*", mode="after")
    @classmethod
    def bounded_values(cls, value):
        if isinstance(value, str) and len(value) > 200000:
            raise ValueError("Text exceeds the operation bound")
        if isinstance(value, list) and len(value) > 100:
            raise ValueError("Use at most 100 values")
        return value


class SendEmail(_Operation):
    operation: Literal["send_email"] = Field("send_email", title='Send Email', description='Send or schedule email from a verified sender. A successful request confirms API acceptance, not delivery.', json_schema_extra={"ui:hidden": True})
    sender: str = Field(..., title='Sender', description='Verified sender, for example John Smith <john@example.com>.', max_length=8192)
    to: list[str] = Field(..., title='To', description='Up to 100 recipients, for example Jane Jones <jane@example.com>.', max_length=100, min_length=1)
    cc: list[str] | None = Field(None, title='CC', description='Up to 100 CC recipients in Name <name@example.com> format.', max_length=100)
    bcc: list[str] | None = Field(None, title='BCC', description='Up to 100 BCC recipients in Name <name@example.com> format.', max_length=100)
    subject: str | None = Field(None, title='Subject', description='The subject of the email to be sent, Note: if template_id if passed this field is ignored.If you would like to set a custom subject in the template_data, use a variable ({{custom_subject}} for instance) as the value of the templates subject and then set its value in template_data respectively.', max_length=8192)
    html_body: str | None = Field(None, title='HTML Body', description='A HTML encoded email body. Either html_body or text_body is required if template_id is not passed. If template_id is passed this field is ignored. Warning:To correctly track clicking of URLs you must:  Enable click tracking for the API key  Insert a full anchor HTML element (not just the URL) Include "https://" at the start of the HREF property ', max_length=200000)
    text_body: str | None = Field(None, title='Text Body', description='A plain text email body. Either html_body or text_body is required if template_id is not passed. If template_id is passed this field is ignored.', max_length=200000)
    template_id: str | None = Field(None, title='Template ID', description='The ID of the template you wish to use', max_length=8192)
    template_data: str | None = Field(None, title='Template Data', description='When a template_id is provided, include the pass-through values in the format {"variable1": "value1", "variable2": "value2"}', max_length=200000)
    schedule: str | None = Field(None, title='Schedule', description='A timestamp that when passed allows you to schedule an email for sending. Must be in the future and within the next 3 days.The api response will include a schedule_id property which can then be used alongside webhooks (An X-Smtp2go-Schedule-Id header is added to the sent email corresponds to this id). A total of 50,000 emails can be queued at any one time.', max_length=8192)
    fastaccept: bool | None = Field(None, title='Accept in Background', description='If true, the email will be accepted immediately and sent in a background process. Use webhooks if you need information about final delivery to the recipient. This will soon become the default method of sending via API.')

    @model_validator(mode="after")
    def require_content(self):
        if not self.template_id and not (self.html_body or self.text_body):
            raise ValueError("Supply text body, HTML body, or a template ID")
        if self.template_data:
            try:
                data = json.loads(self.template_data)
            except ValueError:
                raise ValueError("Template data must be a JSON object string") from None
            if not isinstance(data, dict):
                raise ValueError("Template data must be a JSON object string")
        return self

class SearchEmails(_Operation):
    operation: Literal["search_emails"] = Field("search_emails", title='Search Emails', description='View and search sent emails', json_schema_extra={"ui:hidden": True})
    start_date: str | None = Field(None, title='Start Date', description='ISO-8601 formatted datetime. Results will be inclusive of this value. Timezone is UTC. Defaults to current date at midnight.', max_length=8192)
    end_date: str | None = Field(None, title='End Date', description='ISO-8601 formatted datetime. Results will be inclusive of this value. Timezone is UTC. Defaults to current time.', max_length=8192)
    limit: int | None = Field(None, title='Limit', description='The maximum number of emails to return. Enter an integer between 1 and 5,000. Defaults to 5,000.', ge=1, le=5000)
    status_counts: bool | None = Field(None, title='Status Counts', description='If true, will return an object with counts of each unique email status')
    opened_only: bool | None = Field(None, title='Opened Only', description='If true, will return emails that have been opened by at least one recipient.Note: Only returns information for emails sent from suitable accounts with Open Tracking enabled.  See more info at Open Tracking')
    clicked_only: bool | None = Field(None, title='Clicked Only', description='If true, will return emails that have had a link clicked by at least one recipient.Note: Only returns information for emails sent from suitable accounts with Click Tracking enabled.  See more info at Click Tracking')
    ignore_case: bool | None = Field(None, title='Ignore Case', description='If true, all string searches will be case insensitive')
    filter_query: str | None = Field(None, title='Filter Query', description='If passed, will return results filtered by these search parameters. The query format is documented below', max_length=8192)
    email_id: list[str] | None = Field(None, title='Email IDs', description='If passed, will only return emails with an ID contained within this array', max_length=100)
    username: str | None = Field(None, title='Username', description='If passed, will only return emails sent by this user', max_length=8192)
    headers: list[str] | None = Field(None, title='Headers', description='If passed, will return the specified email header values', max_length=100)
    continue_token: str | None = Field(None, title='Continue Token', description='If passed, the resulting query will paginate from the previous query', max_length=8192)

class GetEmailSummary(_Operation):
    operation: Literal["get_email_summary"] = Field("get_email_summary", title='Get Email Summary', description='Email summary', json_schema_extra={"ui:hidden": True})
    username: str | None = Field(None, title='Username', description='Allows statistics to be returned for a specific user', max_length=8192)

class GetBounceStats(_Operation):
    operation: Literal["get_bounce_stats"] = Field("get_bounce_stats", title='Get Bounce Stats', description='Email bounces', json_schema_extra={"ui:hidden": True})
    username: str | None = Field(None, title='Username', description='Allows statistics to be returned for a specific user.', max_length=8192)

class GetSpamStats(_Operation):
    operation: Literal["get_spam_stats"] = Field("get_spam_stats", title='Get Spam Stats', description='Email spam', json_schema_extra={"ui:hidden": True})
    username: str | None = Field(None, title='Username', description='Allows statistics to be returned for a specific user.', max_length=8192)

class GetUnsubscribeStats(_Operation):
    operation: Literal["get_unsubscribe_stats"] = Field("get_unsubscribe_stats", title='Get Unsubscribe Stats', description='Email unsubscribes', json_schema_extra={"ui:hidden": True})
    username: str | None = Field(None, title='Username', description='Allows statistics to be returned for a specific user.', max_length=8192)

class AddSuppression(_Operation):
    operation: Literal["add_suppression"] = Field("add_suppression", title='Add Suppression', description='Add a suppression', json_schema_extra={"ui:hidden": True})
    email_address: str = Field(..., title='Email Address', description='The email address or domain you would like to suppress from deliveries', max_length=8192)
    block_description: str | None = Field(None, title='Block Description', description='The description given for suppressing the email or domain from deliveries', max_length=8192)
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class ListSuppressions(_Operation):
    operation: Literal["list_suppressions"] = Field("list_suppressions", title='List Suppressions', description='View suppressions', json_schema_extra={"ui:hidden": True})
    continue_token: str | None = Field(None, title='Continue Token', description='If returned from a request this can be passed to continue paging through the result of the results', max_length=8192)
    email_address: str | None = Field(None, title='Email Address', description='If provided, checks if a specific email address or domain is in the block list', max_length=8192)
    end_date: str | None = Field(None, title='End Date', description='ISO-8601 formatted datetime which defaults to 30 days prior to the current date at midnight. Timezone is UTC', max_length=8192)
    fuzzy: bool | None = Field(None, title='Fuzzy', description='Indicates if the search should use fuzzy matching on recipients & reasons')
    reason: str | None = Field(None, title='Reason', description='A reason string to search for', max_length=8192)
    reasons: list[str] | None = Field(None, title='Reasons', description='An array of reason strings to search for', max_length=100)
    recipient: str | None = Field(None, title='Recipient', description='A recipient string to search for', max_length=8192)
    recipients: list[str] | None = Field(None, title='Recipients', description='An array of recipient strings to search for', max_length=100)
    sort: str | None = Field(None, title='Sort', description='The direction to sort the results, either asc or desc', max_length=8192)
    start_date: str | None = Field(None, title='Start Date', description='ISO-8601 formatted datetime which defaults to the current date at midnight. Timezone is UTC', max_length=8192)
    suppression_type: str | None = Field(None, title='Suppression Type', description='If passed restricts the search to a single suppression type manual, spam, unsubscribe, bounce or compliance', max_length=8192)
    suppression_types: list[str] | None = Field(None, title='Suppression Types', description='If passed restricts the search to multiple suppression types manual, spam, unsubscribe, bounce or compliance', max_length=100)
    wildcard: str | None = Field(None, title='Wildcard', description='If provided, only suppressions with this wildcard string in name, domain, or email address fields, will be returned', max_length=8192)
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class RemoveSuppression(_Operation):
    operation: Literal["remove_suppression"] = Field("remove_suppression", title='Remove Suppression', description='Remove a suppression', json_schema_extra={"ui:hidden": True})
    email_address: str = Field(..., title='Email Address', description='The email address or domain you would like to remove from your suppression list', max_length=8192)
    reasons: list[str] = Field(..., title='Reasons', description='A list of block types you would like to remove for the given email or domain', max_length=100, min_length=1)
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class AddSenderDomain(_Operation):
    operation: Literal["add_sender_domain"] = Field("add_sender_domain", title='Add Sender Domain', description='Add a sender domain', json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., title='Domain', description='Domain to add as a sender domain', max_length=8192)
    tracking_subdomain: str | None = Field(None, title='Tracking Subdomain', description='An optional subdomain used for click or open tracking and unsubscribe links', max_length=8192)
    returnpath_subdomain: str | None = Field(None, title='Returnpath Subdomain', description='An optional subdomain to use as a return-path subdomain', max_length=8192)
    auto_verify: bool | None = Field(None, title='Auto Verify', description="If true, verify the domain now removing the need to call the 'domain/verify' endpoint or wait for the periodic verification every 7 minutes.  Note: In order to successfully complete the verification, the 'tracking_subdomain' and 'returnpath_subdomain' must be configured in the domain DNS and propagated.")
    requisition_ssl: bool | None = Field(None, title='Requisition Ssl', description='If true, requisition an SSL certificate for the tracking domain once verification is complete')
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class ListSenderDomains(_Operation):
    operation: Literal["list_sender_domains"] = Field("list_sender_domains", title='List Sender Domains', description='View sender domains', json_schema_extra={"ui:hidden": True})
    domain: str | None = Field(None, title='Domain', description='(Optional) If provided, will only retrieve records for this domain', max_length=8192)
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class VerifySenderDomain(_Operation):
    operation: Literal["verify_sender_domain"] = Field("verify_sender_domain", title='Verify Sender Domain', description='Verify a sender domain', json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., title='Domain', description='Domain to attempt verification for', max_length=8192)
    requisition_ssl: bool | None = Field(None, title='Requisition Ssl', description='If true, requisition an SSL certificate for the tracking domain once verification is complete')
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class RemoveSenderDomain(_Operation):
    operation: Literal["remove_sender_domain"] = Field("remove_sender_domain", title='Remove Sender Domain', description='Remove a sender domain', json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., title='Domain', description='Sender Domain to delete.', max_length=8192)
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class CreateTemplate(_Operation):
    operation: Literal["create_template"] = Field("create_template", title='Create Template', description='Add an email template', json_schema_extra={"ui:hidden": True})
    template_name: str = Field(..., title='Template Name', description='The name of the email template. Min length: 1 Character. Max length: 64 Characters.', max_length=8192)
    id: str = Field(..., title='Id', description='The case-sensitive ID of the email template. Min length: 5 Character. Max length: 24 Characters.', max_length=8192)
    subject: str = Field(..., title='Subject', description='The subject of the email template.', max_length=8192)
    html_body: str = Field(..., title='HTML Body', description='The HTML body of the email template.', max_length=200000)
    text_body: str = Field(..., title='Text Body', description='The Plain Text body of the email template.', max_length=200000)
    template_variables: dict[str, Any] | None = Field(None, title='Template Variables', description='The variables to use within this email template in the format {"variable1": "value1", "variable2": "value2"}')
    tags: list[str] | None = Field(None, title='Tags', description='The list of Tags to associate to this email template', max_length=100)

class UpdateTemplate(_Operation):
    operation: Literal["update_template"] = Field("update_template", title='Update Template', description='Update an email template', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Id', description='The ID of the email template that you wish to change', max_length=8192)
    new_id: str | None = Field(None, title='New Id', description='If provided, will update the email template ID', max_length=8192)
    template_name: str | None = Field(None, title='Template Name', description='If provided, will update the email template name', max_length=8192)
    subject: str | None = Field(None, title='Subject', description='If provided, will update the email template subject', max_length=8192)
    html_body: str | None = Field(None, title='HTML Body', description='If provided, will update the email template HTML body', max_length=200000)
    text_body: str | None = Field(None, title='Text Body', description='If provided, will update the email template Plain Text body', max_length=200000)
    template_variables: dict[str, Any] | None = Field(None, title='Template Variables', description='The pass-through values required by the template in the format {"variable1": "value1", "variable2": "value2"} (When template_id is provided)')
    tags: list[str] | None = Field(None, title='Tags', description='If provided, will update the email template tags', max_length=100)

class DeleteTemplate(_Operation):
    operation: Literal["delete_template"] = Field("delete_template", title='Delete Template', description='Remove an email template', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Id', description='The case-sensitive ID of the email template that you wish to remove', max_length=8192)

class ListTemplates(_Operation):
    operation: Literal["list_templates"] = Field("list_templates", title='List Templates', description='View email templates', json_schema_extra={"ui:hidden": True})
    fuzzy_search: bool | None = Field(None, title='Fuzzy Search', description='If provided, will determine whether search terms are matched exactly or using wildcards.  Default: false')
    search_terms: list[str] | None = Field(None, title='Search Terms', description='If provided, will return email templates containing any of the strings provided in name, tag, id or subject fields.', max_length=100)
    tags: list[str] | None = Field(None, title='Tags', description='If provided, will return email templates containing any of the tags provided', max_length=100)
    sort_direction: str | None = Field(None, title='Sort Direction', description='If provided, will sort the returned email templates in ascending or descending order.  Default: ascValues: asc or desc', max_length=8192)
    page_size: int | None = Field(None, title='Page Size', description='If provided, will limit the number of email templates returned. Default 100', ge=1, le=1000)
    continue_token: str | None = Field(None, title='Continue Token', description='If provided, will fetch the next page of results, following on from the previous page of results from which this continue token was returned', max_length=8192)

class GetTemplate(_Operation):
    operation: Literal["get_template"] = Field("get_template", title='Get Template', description='View template details', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Id', description='The case-sensitive ID of the email template that you wish to view', max_length=8192)

class ListSenderEmails(_Operation):
    operation: Literal["list_sender_emails"] = Field("list_sender_emails", title='List Sender Emails', description='View single sender emails', json_schema_extra={"ui:hidden": True})
    email_address: str | None = Field(None, title='Email Address', description='(Optional) If provided, only return email addresses that match value', max_length=8192)
    subaccount_id: str | None = Field(None, title='Subaccount Id', description='If you wish to make this API call on behalf of a subaccount then include its unique ID here', max_length=8192)

class RemoveScheduledEmail(_Operation):
    operation: Literal["remove_scheduled_email"] = Field("remove_scheduled_email", title='Remove Scheduled Email', description='Remove a scheduled email', json_schema_extra={"ui:hidden": True})
    schedule_id: str = Field(..., title='Schedule Id', description='The schedule_id returned from /v3/email/scheduled/search or the following endpoints [/v3/email/send, /v3/email/mime] (when schedule is passed)', max_length=8192)


Operation = Annotated[Union[SendEmail, SearchEmails, GetEmailSummary, GetBounceStats, GetSpamStats, GetUnsubscribeStats, AddSuppression, ListSuppressions, RemoveSuppression, AddSenderDomain, ListSenderDomains, VerifySenderDomain, RemoveSenderDomain, CreateTemplate, UpdateTemplate, DeleteTemplate, ListTemplates, GetTemplate, ListSenderEmails, RemoveScheduledEmail], Field(discriminator="operation")]


class Smtp2GoNodeConfig(NodeConfig[Operation, Smtp2GoApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'send_email': '/email/send', 'search_emails': '/email/search', 'get_email_summary': '/stats/email_summary', 'get_bounce_stats': '/stats/email_bounces', 'get_spam_stats': '/stats/email_spam', 'get_unsubscribe_stats': '/stats/email_unsubs', 'add_suppression': '/suppression/add', 'list_suppressions': '/suppression/view', 'remove_suppression': '/suppression/remove', 'add_sender_domain': '/domain/add', 'list_sender_domains': '/domain/view', 'verify_sender_domain': '/domain/verify', 'remove_sender_domain': '/domain/remove', 'create_template': '/template/add', 'update_template': '/template/edit', 'delete_template': '/template/delete', 'list_templates': '/template/search', 'get_template': '/template/view', 'list_sender_emails': '/single_sender_emails/view', 'remove_scheduled_email': '/email/scheduled/remove'}


# This API puts errors inside data even when the transport succeeds. Never report
# a successful workflow for those responses, or silently accept an HTML login.
def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items()
                if name.lower() not in {"api_key", "authorization", "x-smtp2go-api-key"}}
    return value


class Smtp2GoNode(WorkflowNode):
    integration_type = "automation-smtp2go"
    connection_evidence = ConnectionEvidence(noun="sender emails", operation="list_sender_emails", label_keys=("email_address",))
    edit_examples = ["Send an email from my verified sender", "List my email templates", "Suppress a recipient"]

    @classmethod
    def get_config_model(cls):
        return Smtp2GoNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        return TypeAdapter(Smtp2GoNodeConfig).validate_python(runtime_config_view(config_data, Smtp2GoNodeConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an SMTP2GO API key")
        config = self.config.config
        key = self.config.credentials.api_key
        body = config.model_dump(exclude={"operation"}, exclude_none=True)
        # No automatic retry: a timeout after a write can mean it was accepted.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await asyncio.wait_for(client.request("POST", BASE_URL + ROUTES[config.operation],
                headers={"X-Smtp2go-Api-Key": key, "Accept": "application/json"}, json=body), timeout=35)
        base = {"operation": config.operation, "http_status": response.status_code}
        # The pinned cancellation contract documents a 200 response with no body.
        if config.operation == "remove_scheduled_email" and response.status_code == 200 and not response.content:
            return {**base, "status": "success", "acknowledged": True, "removal_verified": False}
        if len(response.content) > 8_000_000:
            raise ValueError("SMTP2GO response exceeds the supported size")
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected an SMTP2GO JSON response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected an SMTP2GO response envelope")
        data = payload.get("data")
        error = payload.get("error") or (data.get("error") if isinstance(data, dict) else None)
        if response.status_code != 200 or error:
            return {**base, "status": "error", "error": _redact(error, key) if error else "SMTP2GO rejected the request"}
        if "data" not in payload:
            raise ValueError("SMTP2GO response is missing data")
        result = {**base, "status": "success", "data": _redact(data, key)}
        if config.operation == "list_sender_emails":
            if not isinstance(data, dict) or not isinstance(data.get("senders"), list) or any(
                    not isinstance(row, dict) or not isinstance(row.get("email_address"), str) for row in data["senders"]):
                raise ValueError("SMTP2GO sender email response is incomplete")
            result["items"] = result["data"]["senders"]
        if config.operation == "send_email":
            if not isinstance(data, dict) or not (data.get("email_id") or data.get("schedule_id")):
                raise ValueError("SMTP2GO did not acknowledge the email")
            result["delivery_verified"] = False
            if data.get("failed") or data.get("failures"):
                result.update(status="error", error="SMTP2GO reported email sending failures")
        # Native continuation tokens and counts remain in data for explicit paging.
        return result
