"""Mailjet Email API workflow node.

The operation catalogue below follows Mailjet's published Email API endpoint
categories. API key + secret are HTTP Basic credentials; there is no browser
OAuth flow for this API. The transport is deliberately fixed to api.mailjet.com.

https://dev.mailjet.com/docs/api-reference/email-api/categories/contacts
https://dev.mailjet.com/docs/api-reference/email-api/categories/templates
https://dev.mailjet.com/docs/api-reference/email-api/categories/campaigns
https://dev.mailjet.com/docs/api-reference/email-api/categories/messages
https://dev.mailjet.com/docs/api-reference/email-api/categories/webhook
https://dev.mailjet.com/docs/api-reference/email-api/categories/settings
https://dev.mailjet.com/docs/content-api/content-overview/content-overview
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import filter_options_by_search, normalize_search


API_BASE = "https://api.mailjet.com"
_PARAM = re.compile(r"\{([a-z_]+)\}")
_PICKER_SEARCH_MIN_MATCHES = 20
_PICKER_SEARCH_MAX_PAGES = 10


class MailjetApiKeyCredential(BaseModel):
    credential_type: Literal["mailjet_api_key"] = Field(
        "mailjet_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., title="Secret Key", json_schema_extra={"ui:widget": "password"})

    model_config = ConfigDict(title="Mailjet API Key", json_schema_extra={
        "x-credential-url": "https://dev.mailjet.com/docs/email-api/email-api-overview/authentication",
        "x-credential-instructions": "Mailjet → Account Settings → API Key Management. Copy the API Key and Secret Key for the same subaccount.",
    })


@dataclass(frozen=True)
class Operation:
    name: str
    category: str
    method: str
    path: str
    body: str = "none"  # none, json, or one of the concrete body builders below
    response_kind: Literal["json", "csv", "text", "binary"] = "json"


# Explicit endpoint allowlist. No user-controlled URL, method or route can be
# interpolated into the HTTP target. Only path IDs are substituted and escaped.
_OPERATIONS = [
    Operation("get_my_profile", "Account", "GET", "/v3/REST/myprofile"),
    Operation("list_users", "Account", "GET", "/v3/REST/user"),
    Operation("list_contacts", "Contacts", "GET", "/v3/REST/contact"),
    Operation("create_contact", "Contacts", "POST", "/v3/REST/contact", "contact"),
    Operation("get_contact", "Contacts", "GET", "/v3/REST/contact/{contact_id}"),
    Operation("update_contact", "Contacts", "PUT", "/v3/REST/contact/{contact_id}", "json"),
    Operation("list_contact_lists", "Contact Lists", "GET", "/v3/REST/contactslist"),
    Operation("create_contact_list", "Contact Lists", "POST", "/v3/REST/contactslist", "list"),
    Operation("get_contact_list", "Contact Lists", "GET", "/v3/REST/contactslist/{list_id}"),
    Operation("update_contact_list", "Contact Lists", "PUT", "/v3/REST/contactslist/{list_id}", "list"),
    Operation("delete_contact_list", "Contact Lists", "DELETE", "/v3/REST/contactslist/{list_id}"),
    Operation("list_contact_data", "Contact Properties", "GET", "/v3/REST/contactdata"),
    Operation("get_contact_data", "Contact Properties", "GET", "/v3/REST/contactdata/{contact_id}"),
    Operation("update_contact_data", "Contact Properties", "PUT", "/v3/REST/contactdata/{contact_id}", "json"),
    Operation("delete_contact_data", "Contact Properties", "DELETE", "/v3/REST/contactdata/{contact_id}"),
    Operation("list_contact_properties", "Contact Properties", "GET", "/v3/REST/contactmetadata"),
    Operation("create_contact_property", "Contact Properties", "POST", "/v3/REST/contactmetadata", "property"),
    Operation("get_contact_property", "Contact Properties", "GET", "/v3/REST/contactmetadata/{property_id}"),
    Operation("update_contact_property", "Contact Properties", "PUT", "/v3/REST/contactmetadata/{property_id}", "json"),
    Operation("delete_contact_property", "Contact Properties", "DELETE", "/v3/REST/contactmetadata/{property_id}"),
    Operation("get_contact_lists_for_contact", "Subscriptions", "GET", "/v3/REST/contact/{contact_id}/getcontactslists"),
    Operation("manage_contact_lists_for_contact", "Subscriptions", "POST", "/v3/REST/contact/{contact_id}/managecontactslists", "json"),
    Operation("manage_contact_in_list", "Subscriptions", "POST", "/v3/REST/contactslist/{list_id}/managecontact", "json"),
    Operation("list_list_recipients", "Subscriptions", "GET", "/v3/REST/listrecipient"),
    Operation("create_list_recipient", "Subscriptions", "POST", "/v3/REST/listrecipient", "recipient"),
    Operation("get_list_recipient", "Subscriptions", "GET", "/v3/REST/listrecipient/{recipient_id}"),
    Operation("update_list_recipient", "Subscriptions", "PUT", "/v3/REST/listrecipient/{recipient_id}", "json"),
    Operation("delete_list_recipient", "Subscriptions", "DELETE", "/v3/REST/listrecipient/{recipient_id}"),
    Operation("list_contact_list_signups", "Subscriptions", "GET", "/v3/REST/contactslistsignup"),
    Operation("get_contact_list_signup", "Subscriptions", "GET", "/v3/REST/contactslistsignup/{signup_id}"),
    Operation("manage_many_contacts", "Bulk Contacts", "POST", "/v3/REST/contact/managemanycontacts", "json"),
    Operation("get_manage_many_contacts_job", "Bulk Contacts", "GET", "/v3/REST/contact/managemanycontacts/{job_id}"),
    Operation("manage_many_list_contacts", "Bulk Contacts", "POST", "/v3/REST/contactslist/{list_id}/managemanycontacts", "json"),
    Operation("get_manage_many_list_contacts_job", "Bulk Contacts", "GET", "/v3/REST/contactslist/{list_id}/managemanycontacts/{job_id}"),
    Operation("import_contact_list", "Bulk Contacts", "POST", "/v3/REST/contactslist/{list_id}/importlist", "json"),
    Operation("get_import_contact_list_job", "Bulk Contacts", "GET", "/v3/REST/contactslist/{list_id}/importlist/{job_id}"),
    Operation("get_csv_import_job", "Bulk Contacts", "GET", "/v3/REST/csvimport/{job_id}"),
    Operation("get_csv_import_errors", "Bulk Contacts", "GET", "/v3/DATA/BatchJob/{job_id}/CSVError/text:csv", response_kind="csv"),
    Operation("verify_contact_list", "Bulk Contacts", "POST", "/v3/REST/contactslist/{list_id}/verify", "json"),
    Operation("get_verify_contact_list_job", "Bulk Contacts", "GET", "/v3/REST/contactslist/{list_id}/verify/{job_id}"),
    Operation("list_templates", "Templates", "GET", "/v3/REST/template"),
    Operation("create_template", "Templates", "POST", "/v3/REST/template", "template"),
    Operation("get_template", "Templates", "GET", "/v3/REST/template/{template_id}"),
    Operation("update_template", "Templates", "PUT", "/v3/REST/template/{template_id}", "json"),
    Operation("delete_template", "Templates", "DELETE", "/v3/REST/template/{template_id}"),
    Operation("get_template_content", "Templates", "GET", "/v3/REST/template/{template_id}/detailcontent"),
    Operation("create_template_content", "Templates", "POST", "/v3/REST/template/{template_id}/detailcontent", "json"),
    Operation("update_template_content", "Templates", "PUT", "/v3/REST/template/{template_id}/detailcontent", "json"),
    Operation("list_campaign_drafts", "Campaign Drafts", "GET", "/v3/REST/campaigndraft"),
    Operation("create_campaign_draft", "Campaign Drafts", "POST", "/v3/REST/campaigndraft", "draft"),
    Operation("get_campaign_draft", "Campaign Drafts", "GET", "/v3/REST/campaigndraft/{draft_id}"),
    Operation("update_campaign_draft", "Campaign Drafts", "PUT", "/v3/REST/campaigndraft/{draft_id}", "json"),
    Operation("get_campaign_draft_content", "Campaign Drafts", "GET", "/v3/REST/campaigndraft/{draft_id}/detailcontent"),
    Operation("create_campaign_draft_content", "Campaign Drafts", "POST", "/v3/REST/campaigndraft/{draft_id}/detailcontent", "json"),
    Operation("get_campaign_draft_schedule", "Campaign Drafts", "GET", "/v3/REST/campaigndraft/{draft_id}/schedule"),
    Operation("create_campaign_draft_schedule", "Campaign Drafts", "POST", "/v3/REST/campaigndraft/{draft_id}/schedule", "json"),
    Operation("update_campaign_draft_schedule", "Campaign Drafts", "PUT", "/v3/REST/campaigndraft/{draft_id}/schedule", "json"),
    Operation("delete_campaign_draft_schedule", "Campaign Drafts", "DELETE", "/v3/REST/campaigndraft/{draft_id}/schedule"),
    Operation("get_campaign_draft_status", "Campaign Drafts", "GET", "/v3/REST/campaigndraft/{draft_id}/status"),
    Operation("test_campaign_draft", "Campaign Drafts", "POST", "/v3/REST/campaigndraft/{draft_id}/test", "json"),
    Operation("send_campaign_draft", "Campaign Drafts", "POST", "/v3/REST/campaigndraft/{draft_id}/send"),
    Operation("list_campaigns", "Campaigns", "GET", "/v3/REST/campaign"),
    Operation("get_campaign", "Campaigns", "GET", "/v3/REST/campaign/{campaign_id}"),
    Operation("update_campaign", "Campaigns", "PUT", "/v3/REST/campaign/{campaign_id}", "json"),
    Operation("send_email", "Messages", "POST", "/v3.1/send", "send"),
    Operation("list_messages", "Messages", "GET", "/v3/REST/message"),
    Operation("get_message", "Messages", "GET", "/v3/REST/message/{message_id}"),
    Operation("get_message_history", "Messages", "GET", "/v3/REST/messagehistory/{message_id}"),
    Operation("list_message_information", "Messages", "GET", "/v3/REST/messageinformation"),
    Operation("get_message_information", "Messages", "GET", "/v3/REST/messageinformation/{message_id}"),
    Operation("list_senders", "Senders", "GET", "/v3/REST/sender"),
    Operation("create_sender", "Senders", "POST", "/v3/REST/sender", "sender"),
    Operation("get_sender", "Senders", "GET", "/v3/REST/sender/{sender_id}"),
    Operation("update_sender", "Senders", "PUT", "/v3/REST/sender/{sender_id}", "json"),
    Operation("delete_sender", "Senders", "DELETE", "/v3/REST/sender/{sender_id}"),
    Operation("validate_sender", "Senders", "POST", "/v3/REST/sender/{sender_id}/validate"),
    Operation("list_meta_senders", "Senders", "GET", "/v3/REST/metasender"),
    Operation("get_dns", "Senders", "GET", "/v3/REST/dns/{dns_id}"),
    Operation("list_dns", "Senders", "GET", "/v3/REST/dns"),
    Operation("check_dns", "Senders", "POST", "/v3/REST/dns/{dns_id}/check"),
    Operation("list_webhook_urls", "Webhooks", "GET", "/v3/REST/eventcallbackurl"),
    Operation("create_webhook_url", "Webhooks", "POST", "/v3/REST/eventcallbackurl", "webhook"),
    Operation("get_webhook_url", "Webhooks", "GET", "/v3/REST/eventcallbackurl/{webhook_id}"),
    Operation("update_webhook_url", "Webhooks", "PUT", "/v3/REST/eventcallbackurl/{webhook_id}", "json"),
    Operation("delete_webhook_url", "Webhooks", "DELETE", "/v3/REST/eventcallbackurl/{webhook_id}"),
    Operation("list_contact_filters", "Segments", "GET", "/v3/REST/contactfilter"),
    Operation("create_contact_filter", "Segments", "POST", "/v3/REST/contactfilter", "json"),
    Operation("get_contact_filter", "Segments", "GET", "/v3/REST/contactfilter/{filter_id}"),
    Operation("update_contact_filter", "Segments", "PUT", "/v3/REST/contactfilter/{filter_id}", "json"),
    Operation("delete_contact_filter", "Segments", "DELETE", "/v3/REST/contactfilter/{filter_id}"),
    Operation("list_campaign_overview", "Statistics", "GET", "/v3/REST/campaignoverview"),
    Operation("list_contact_statistics", "Statistics", "GET", "/v3/REST/contactstatistics"),
    Operation("get_contact_statistics", "Statistics", "GET", "/v3/REST/contactstatistics/{contact_id}"),
    Operation("list_recipient_statistics", "Statistics", "GET", "/v3/REST/listrecipientstatistics"),
    Operation("get_recipient_statistics", "Statistics", "GET", "/v3/REST/listrecipientstatistics/{recipient_id}"),
    Operation("list_stat_counters", "Statistics", "GET", "/v3/REST/statcounters"),
    Operation("list_link_click_statistics", "Statistics", "GET", "/v3/REST/statistics/link-click"),
    Operation("list_recipient_esp_statistics", "Statistics", "GET", "/v3/REST/statistics/recipient-esp"),
    Operation("list_top_links_clicked", "Statistics", "GET", "/v3/REST/toplinkclicked"),
    Operation("list_user_agent_statistics", "Statistics", "GET", "/v3/REST/useragentstatistics"),
    Operation("list_content_templates", "Content Templates", "GET", "/v1/REST/templates"),
    Operation("create_content_template", "Content Templates", "POST", "/v1/REST/templates", "content_template"),
    Operation("get_content_template", "Content Templates", "GET", "/v1/REST/templates/{content_template_id}"),
    Operation("update_content_template", "Content Templates", "PUT", "/v1/REST/templates/{content_template_id}", "json"),
    Operation("delete_content_template", "Content Templates", "DELETE", "/v1/REST/templates/{content_template_id}"),
    Operation("list_content_template_versions", "Content Templates", "GET", "/v1/REST/templates/{content_template_id}/contents"),
    Operation("create_content_template_version", "Content Templates", "POST", "/v1/REST/templates/{content_template_id}/contents", "content_version"),
    Operation("get_content_template_version", "Content Templates", "GET", "/v1/REST/templates/{content_template_id}/contents/types/{content_type}"),
    Operation("update_content_template_version", "Content Templates", "PUT", "/v1/REST/templates/{content_template_id}/contents/types/{content_type}", "json"),
    Operation("publish_content_template", "Content Templates", "POST", "/v1/REST/templates/{content_template_id}/contents/publish"),
    Operation("lock_content_template", "Content Templates", "POST", "/v1/REST/templates/{content_template_id}/contents/lock"),
    Operation("unlock_content_template", "Content Templates", "POST", "/v1/REST/templates/{content_template_id}/contents/unlock"),
    Operation("list_images", "Images", "GET", "/v1/REST/images"),
    Operation("get_image", "Images", "GET", "/v1/REST/images/{image_id}"),
    Operation("update_image", "Images", "PUT", "/v1/REST/images/{image_id}", "json"),
    Operation("delete_image", "Images", "DELETE", "/v1/REST/images/{image_id}"),
    Operation("list_labels", "Labels", "GET", "/v1/REST/labels"),
    Operation("create_label", "Labels", "POST", "/v1/REST/labels", "label"),
    Operation("get_label", "Labels", "GET", "/v1/REST/labels/{label_id}"),
    Operation("update_label", "Labels", "PUT", "/v1/REST/labels/{label_id}", "json"),
    Operation("delete_label", "Labels", "DELETE", "/v1/REST/labels/{label_id}"),
]

OPERATIONS = {op.name: op for op in _OPERATIONS}


def _picker_field(name: str) -> Any:
    labels = {
        "list_id": "Contact List", "contact_id": "Contact", "template_id": "Template",
        "sender_id": "Sender", "draft_id": "Campaign Draft", "campaign_id": "Campaign",
        "property_id": "Contact Property", "recipient_id": "List Recipient",
        "content_template_id": "Content Template", "image_id": "Image", "label_id": "Label",
    }
    title = labels.get(name, name.replace("_", " ").title())
    extra = None
    if name in {"list_id", "template_id", "sender_id", "draft_id", "content_template_id", "image_id", "label_id"}:
        extra = {"x-dynamic-options": {
            "field_name": name, "searchable": True, "allow_custom": True,
            "placeholder": f"Select {title.lower()}…",
        }}
    return Field(..., title=title, json_schema_extra=extra)


def _operation_model(op: Operation) -> type[BaseModel]:
    label = op.name.replace("_", " ").title()
    fields: Dict[str, Any] = {
        "operation": (Literal[op.name], Field(op.name, title=label, json_schema_extra={
            "const": op.name, "ui:hidden": True, "x-category": op.category,
            "x-display-name": label, "x-is-trigger": False,
        }))
    }
    for name in _PARAM.findall(op.path):
        if name == "content_type":
            if op.name == "update_content_template_version":
                fields[name] = (Literal["D"], Field(..., title="Content Status",
                    description="Draft only", json_schema_extra={"enum": ["D"]}))
            else:
                fields[name] = (Literal["D", "P", "A"], Field(..., title="Content Status",
                                                             description="Draft, Published, or Autosave"))
        else:
            fields[name] = (str, _picker_field(name))
    if op.method == "GET" and "{" not in op.path and op.name != "get_my_profile":
        fields["limit"] = (Optional[int], Field(None, title="Limit", ge=1, le=1000))
        fields["offset"] = (Optional[int], Field(None, title="Offset", ge=0))
    if op.name == "list_stat_counters":
        fields.update({
            "counter_source": (Literal["Campaign", "APIKey", "List", "Sender"],
                               Field(..., title="Counter Source")),
            "counter_resolution": (Literal["Highest", "Hour", "Day", "Lifetime"],
                                   Field(..., title="Counter Resolution")),
            "counter_timing": (Literal["Message", "Event"], Field(..., title="Counter Timing")),
            "source_id": (Optional[int], Field(None, title="Source ID", ge=1,
                description="Campaign, contact list, or sender ID; required except for APIKey")),
            "from_ts": (Optional[str], Field(None, title="From Timestamp",
                description="Unix timestamp or RFC3339; required unless resolution is Lifetime")),
            "to_ts": (Optional[str], Field(None, title="To Timestamp",
                description="Unix timestamp or RFC3339")),
        })
    elif op.name in {"list_link_click_statistics", "list_recipient_esp_statistics"}:
        fields["campaign_id"] = (int, Field(..., title="Campaign ID", ge=1))
    if op.body == "json":
        fields["body_json"] = (str, Field(..., title="Request Body (JSON)",
            description="JSON object with the fields documented by Mailjet for this operation",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    elif op.body == "contact":
        fields["email"] = (str, Field(..., title="Email"))
        fields["name"] = (Optional[str], Field(None, title="Name"))
        fields["excluded_from_campaigns"] = (bool, Field(False, title="Exclude from Campaigns"))
    elif op.body == "list":
        fields["name"] = (str, Field(..., title="List Name"))
    elif op.body == "recipient":
        fields["list_id"] = (int, _picker_field("list_id"))
        fields["contact_email"] = (Optional[str], Field(None, title="Contact Email"))
        fields["contact_id"] = (Optional[int], Field(None, title="Contact ID", ge=1))
        fields["is_unsubscribed"] = (bool, Field(False, title="Unsubscribed"))
    elif op.body == "property":
        fields["name"] = (str, Field(..., title="Property Name"))
        fields["datatype"] = (Literal["str", "int", "float", "bool", "datetime"],
                              Field("str", title="Data Type"))
        fields["namespace"] = (str, Field("static", title="Namespace"))
    elif op.body == "template":
        fields["name"] = (str, Field(..., title="Template Name"))
        fields["description"] = (Optional[str], Field(None, title="Description"))
        fields["locale"] = (Optional[str], Field(None, title="Locale"))
    elif op.body == "draft":
        fields["list_id"] = (int, _picker_field("list_id"))
        fields["title"] = (str, Field(..., title="Draft Title"))
        fields["subject"] = (str, Field(..., title="Subject"))
        fields["locale"] = (str, Field("en_US", title="Locale"))
        fields["sender"] = (str, Field(..., title="Sender ID"))
        fields["sender_email"] = (str, Field(..., title="Sender Email"))
    elif op.body == "sender":
        fields["email"] = (str, Field(..., title="Sender Email or Domain"))
    elif op.body == "webhook":
        fields["event_type"] = (Literal["open", "click", "bounce", "spam", "blocked", "unsub", "sent"],
                                Field(..., title="Event Type"))
        fields["url"] = (str, Field(..., title="Callback URL"))
        fields["is_backup"] = (bool, Field(False, title="Backup URL"))
    elif op.body == "content_template":
        fields["name"] = (str, Field(..., title="Template Name"))
        fields["edit_mode"] = (Literal[2, 4], Field(2, title="Edit Mode",
                                                 description="2 = HTML; 4 = MJML (publish in Mailjet UI)"))
        fields["purpose"] = (Literal["marketing", "transactional", "automation", "opt-in"],
                             Field("transactional", title="Purpose"))
        fields["description"] = (Optional[str], Field(None, title="Description"))
    elif op.body == "content_version":
        fields["locale"] = (str, Field("en_US", title="Locale"))
        fields["name"] = (Optional[str], Field(None, title="Version Name"))
        fields["text_part"] = (Optional[str], Field(None, title="Text Body", json_schema_extra={"ui:widget": "textarea"}))
        fields["html_part"] = (Optional[str], Field(None, title="HTML Body", json_schema_extra={"ui:widget": "textarea"}))
        fields["mjml_part"] = (Optional[str], Field(None, title="MJML Body", json_schema_extra={"ui:widget": "textarea"}))
    elif op.body == "label":
        fields["name"] = (str, Field(..., title="Label Name"))
        fields["color"] = (str, Field(..., title="Color", description="Hex color, for example #2385E0"))
        fields["used_for"] = (Literal["resource", "image"], Field("resource", title="Used For"))
    elif op.body == "send":
        fields.update({
            "from_email": (str, Field(..., title="From Email", description="Validated sender address")),
            "from_name": (Optional[str], Field(None, title="From Name")),
            "to_email": (str, Field(..., title="To Email")),
            "to_name": (Optional[str], Field(None, title="To Name")),
            "subject": (str, Field(..., title="Subject")),
            "text_part": (Optional[str], Field(None, title="Text Body", json_schema_extra={"ui:widget": "textarea"})),
            "html_part": (Optional[str], Field(None, title="HTML Body", json_schema_extra={"ui:widget": "textarea"})),
            "template_id": (Optional[int], Field(None, title="Template ID",
                                                description="Send API TemplateID; use ExternalID for a Content API template")),
            "sandbox_mode": (bool, Field(False, title="Sandbox Mode", description="Validate without delivering the email")),
        })
    return create_model("Mailjet" + "".join(s.title() for s in op.name.split("_")) + "Config", **fields)


_MODELS = [_operation_model(op) for op in _OPERATIONS]
MailjetOperation = Annotated[Union[tuple(_MODELS)], Discriminator("operation")]


class MailjetNodeConfig(NodeConfig[MailjetOperation, MailjetApiKeyCredential]):
    pass


def _body_object(raw: str) -> dict[str, Any]:
    try:
        body = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Request Body must be valid JSON") from exc
    if not isinstance(body, dict) or not body:
        raise ValueError("Request Body must be a nonempty JSON object")
    return body


def _request_body(op: Operation, config: BaseModel) -> Optional[dict[str, Any]]:
    if op.body == "json":
        return _body_object(config.body_json)
    if op.body == "contact":
        body = {"Email": config.email, "IsExcludedFromCampaigns": config.excluded_from_campaigns}
        if config.name:
            body["Name"] = config.name
        return body
    if op.body == "list":
        return {"Name": config.name}
    if op.body == "recipient":
        if bool(config.contact_id) == bool(config.contact_email):
            raise ValueError("Provide exactly one Contact ID or Contact Email")
        body = {"ListID": config.list_id, "IsUnsubscribed": config.is_unsubscribed}
        if config.contact_id:
            body["ContactID"] = config.contact_id
        else:
            body["ContactAlt"] = config.contact_email
        return body
    if op.body == "property":
        return {"Name": config.name, "Datatype": config.datatype, "NameSpace": config.namespace}
    if op.body == "template":
        body = {"Name": config.name}
        if config.description:
            body["Description"] = config.description
        if config.locale:
            body["Locale"] = config.locale
        return body
    if op.body == "draft":
        return {"ContactsListID": config.list_id, "Title": config.title,
                "Subject": config.subject, "Locale": config.locale,
                "Sender": config.sender, "SenderEmail": config.sender_email}
    if op.body == "sender":
        return {"Email": config.email}
    if op.body == "webhook":
        return {"EventType": config.event_type, "Url": config.url,
                "IsBackup": config.is_backup}
    if op.body == "content_template":
        body = {"Name": config.name, "EditMode": config.edit_mode, "Purposes": [config.purpose]}
        if config.description:
            body["Description"] = config.description
        return body
    if op.body == "content_version":
        if not (config.text_part or config.html_part or config.mjml_part):
            raise ValueError("Provide text, HTML, or MJML template content")
        body = {"Locale": config.locale}
        if config.name:
            body["Name"] = config.name
        for field, key in (("text_part", "TextPart"), ("html_part", "HTMLPart"),
                           ("mjml_part", "MJMLPart")):
            if getattr(config, field):
                body[key] = getattr(config, field)
        return body
    if op.body == "label":
        return {"Name": config.name, "Color": config.color, "UsedFor": config.used_for}
    if op.body == "send":
        if not (config.text_part or config.html_part or config.template_id):
            raise ValueError("Provide a text body, HTML body, or template ID")
        if config.template_id and (config.text_part or config.html_part):
            raise ValueError("Template ID cannot be combined with a text or HTML body")
        message: dict[str, Any] = {
            "From": {"Email": config.from_email},
            "To": [{"Email": config.to_email}],
            "Subject": config.subject,
        }
        if config.from_name:
            message["From"]["Name"] = config.from_name
        if config.to_name:
            message["To"][0]["Name"] = config.to_name
        for field, key in (("text_part", "TextPart"), ("html_part", "HTMLPart"),
                           ("template_id", "TemplateID")):
            if getattr(config, field):
                message[key] = getattr(config, field)
        return {"Messages": [message], "SandboxMode": config.sandbox_mode}
    return None


def _path(op: Operation, config: BaseModel) -> str:
    return _PARAM.sub(lambda match: quote(str(getattr(config, match.group(1))), safe=""), op.path)


def _stat_counters_params(config: BaseModel) -> dict[str, Any]:
    source = config.counter_source
    resolution = config.counter_resolution
    timing = config.counter_timing
    source_id = config.source_id
    from_ts = config.from_ts.strip() if config.from_ts else None
    to_ts = config.to_ts.strip() if config.to_ts else None
    if source in {"Campaign", "List", "Sender"} and source_id is None:
        raise ValueError("Source ID is required for campaign, list, and sender counters")
    if source == "APIKey" and source_id is not None:
        raise ValueError("Source ID is not used for API key counters")
    if source == "List" and (timing != "Message" or resolution != "Lifetime"):
        raise ValueError("List counters require Message timing and Lifetime resolution")
    if source == "Sender" and timing != "Message":
        raise ValueError("Sender counters require Message timing")
    if timing == "Event" and resolution == "Lifetime":
        raise ValueError("Event counters require a time resolution")
    if resolution != "Lifetime" and not from_ts:
        raise ValueError("From Timestamp is required for time-resolved counters")
    if (config.from_ts is not None and not from_ts) or (config.to_ts is not None and not to_ts):
        raise ValueError("Timestamps must not be blank")
    params: dict[str, Any] = {
        "CounterSource": source, "CounterResolution": resolution, "CounterTiming": timing,
    }
    if source_id is not None:
        params["SourceID"] = source_id
    if from_ts:
        params["FromTS"] = from_ts
    if to_ts:
        params["ToTS"] = to_ts
    return params


async def _request(credentials: MailjetApiKeyCredential, op: Operation, path: str,
                   *, params: Optional[dict[str, Any]] = None,
                   body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    try:
        accepted_type = {
            "json": "application/json", "csv": "text/csv", "text": "text/plain",
            "binary": "application/octet-stream",
        }[op.response_kind]
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                op.method, API_BASE + path, auth=(credentials.api_key, credentials.secret_key),
                headers={"Accept": accepted_type}, params=params, json=body,
            )
    except httpx.TimeoutException:
        return {"status": "error", "action": op.name, "error": "Mailjet request timed out"}
    except httpx.RequestError:
        return {"status": "error", "action": op.name, "error": "Mailjet connection failed"}

    status = response.status_code
    if status < 200 or status >= 300:
        # Mailjet can echo request data in ErrorMessage. Never expose response
        # bodies from failure paths, which may include email or credential data.
        return {"status": "error", "action": op.name, "status_code": status,
                "error": f"Mailjet returned HTTP {status}"}
    result: dict[str, Any] = {"status": "success", "action": op.name, "status_code": status}
    if not response.content:
        if (status == 202 and op.method in {"POST", "PUT"} and op.name != "send_email") or (
            status == 204 and (op.method == "DELETE" or op.name in {
                "lock_content_template", "unlock_content_template",
            })
        ):
            result["data"] = None
            return result
        return {"status": "error", "action": op.name, "status_code": status,
                "error": "Mailjet returned an empty response"}
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if op.response_kind == "json":
        if content_type != "application/json" and not content_type.endswith("+json"):
            return {"status": "error", "action": op.name, "status_code": status,
                    "error": "Mailjet returned an unexpected response type"}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "action": op.name, "status_code": status,
                    "error": "Mailjet returned invalid JSON"}
        if isinstance(data, dict) and (data.get("ErrorCode") or data.get("ErrorMessage") or data.get("Errors") or data.get("error")):
            return {"status": "error", "action": op.name, "status_code": status,
                    "error": "Mailjet reported an operation error"}
        if op.name == "create_content_template_version":
            # Unlike other Content API REST endpoints, the documented 201
            # response is one content object, not a Count/Data/Total envelope.
            if (status != 201 or not isinstance(data, dict)
                    or type(data.get("ID")) is not int or data["ID"] <= 0
                    or type(data.get("TemplateID")) is not int or data["TemplateID"] <= 0
                    or str(data["TemplateID"]) != path.rsplit("/", 2)[-2]
                    or data.get("ContentType") != "D"
                    or not isinstance(data.get("Locale"), str) or not data["Locale"].strip()):
                return {"status": "error", "action": op.name, "status_code": status,
                        "error": "Mailjet returned an invalid template content response"}
            result["data"] = data
            return result
        if "/REST/" in op.path and (
            not isinstance(data, dict) or not isinstance(data.get("Data"), list)
            or any(not isinstance(row, dict) for row in data["Data"])
            or any(key in data and (type(data[key]) is not int or data[key] < 0)
                   for key in ("Count", "Total"))
        ):
            return {"status": "error", "action": op.name, "status_code": status,
                    "error": "Mailjet returned an invalid response envelope"}
        if op.name == "send_email":
            messages = data.get("Messages") if isinstance(data, dict) else None
            if not isinstance(messages, list) or not messages or any(
                not isinstance(msg, dict) or msg.get("Status") != "success" or msg.get("Errors")
                for msg in messages
            ):
                return {"status": "error", "action": op.name, "status_code": status,
                        "error": "Mailjet did not accept every message"}
        result["data"] = data
        return result
    if op.response_kind == "csv" and content_type in {"text/csv", "application/csv"}:
        result["data"] = response.text
    elif op.response_kind == "text" and content_type == "text/plain":
        result["data"] = response.text
    elif op.response_kind == "binary" and content_type in {
        "application/octet-stream", "application/pdf", "image/png", "image/jpeg", "image/gif",
    }:
        result["data"] = BinaryOutput(response.content, content_type or "application/octet-stream",
                                      filename="mailjet-response")
    else:
        return {"status": "error", "action": op.name, "status_code": status,
                "error": "Mailjet returned an unexpected response type"}
    return result


class MailjetNode(WorkflowNode):
    integration_type = "automation-mailjet"

    connection_evidence = ConnectionEvidence(
        field="list_id", noun="contact lists", identity_operation="get_my_profile",
        identity_keys=("CompanyName", "Email"),
    )

    @classmethod
    def get_config_model(cls):
        return MailjetNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> Dict[str, Any]:
        catalog = {
            "list_id": ("list_contact_lists", "Name"),
            "template_id": ("list_templates", "Name"),
            "sender_id": ("list_senders", "Email"),
            "draft_id": ("list_campaign_drafts", "Title"),
            "content_template_id": ("list_content_templates", "Name"),
            "image_id": ("list_images", "Name"),
            "label_id": ("list_labels", "Name"),
        }
        if field_name not in catalog:
            return {"options": []}
        credentials = MailjetApiKeyCredential.model_validate(credential_data)
        operation, label_field = catalog[field_name]
        if page_token is not None and (
            not isinstance(page_token, str) or not re.fullmatch(r"[0-9]+", page_token)
        ):
            raise ValueError("Invalid option page")
        offset = int(page_token or "0")
        search = normalize_search(search)
        options = []
        seen_pages = set()
        seen_matches = set()
        for _ in range(_PICKER_SEARCH_MAX_PAGES if search else 1):
            response = await _request(credentials, OPERATIONS[operation], OPERATIONS[operation].path,
                                      params={"Limit": 100, "Offset": offset})
            if response["status"] != "success":
                raise ValueError(response["error"])
            body = response.get("data")
            if not isinstance(body, dict) or not isinstance(body.get("Data"), list):
                raise ValueError("Mailjet returned an invalid list response")
            rows = body["Data"]
            page_options = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Mailjet returned an invalid list response")
                item_id, label = row.get("ID"), row.get(label_field)
                if (isinstance(item_id, bool) or not isinstance(item_id, (str, int))
                        or not str(item_id).strip() or isinstance(item_id, int) and item_id <= 0
                        or not isinstance(label, str) or not label.strip()):
                    raise ValueError("Mailjet returned an invalid list response")
                page_options.append({"value": str(item_id), "label": label.strip()})
            if operation.startswith("list_content_") or operation in {"list_images", "list_labels"}:
                # Content API v1 reports global Total for the query.
                total = body.get("Total")
                if type(total) is not int or total < offset + len(rows):
                    raise ValueError("Mailjet returned an invalid list response")
                more = bool(rows) and offset + len(rows) < total
            else:
                # Email API v3 Count/Total describe this page unless CountOnly is
                # requested. A full page may have more rows even when Total == 100.
                more = len(rows) == 100
            next_page = str(offset + len(rows)) if more else None
            if search:
                fingerprint = tuple(option["value"] for option in page_options)
                if page_options and fingerprint in seen_pages:
                    raise ValueError("Mailjet returned a repeated option page")
                seen_pages.add(fingerprint)
                for option in filter_options_by_search(page_options, search, fields=("label",)):
                    if option["value"] not in seen_matches:
                        options.append(option)
                        seen_matches.add(option["value"])
            else:
                options = page_options
            # Sparse matches cannot scroll the dropdown to request another page.
            if not search or not next_page or len(options) >= _PICKER_SEARCH_MIN_MATCHES:
                return {"options": options, "next_page_token": next_page}
            offset = int(next_page)
        raise ValueError(
            f"Mailjet option search page limit reached; refine the search or use an ID (next offset {offset})"
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, MailjetNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Mailjet API key and secret")
        config = self.config.config
        op = OPERATIONS.get(config.operation)
        if op is None:
            raise ValueError("Unknown Mailjet operation")
        params = None
        if op.method == "GET" and "{" not in op.path and op.name != "get_my_profile":
            params = {"Limit": getattr(config, "limit", None), "Offset": getattr(config, "offset", None)}
            params = {key: value for key, value in params.items() if value is not None}
            if op.name == "list_stat_counters":
                params.update(_stat_counters_params(config))
            elif op.name in {"list_link_click_statistics", "list_recipient_esp_statistics"}:
                params["CampaignID"] = config.campaign_id
        result = await _request(self.config.credentials, op, _path(op, config),
                                params=params, body=_request_body(op, config))
        if result["status"] == "success" and op.name == "get_my_profile":
            data = result.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("Data"), list) or len(data["Data"]) != 1:
                return {"status": "error", "action": op.name, "error": "Mailjet returned an invalid profile"}
            profile = data["Data"][0]
            if not isinstance(profile, dict):
                return {"status": "error", "action": op.name, "error": "Mailjet returned an invalid profile"}
            identity = {key: value.strip() for key in ("CompanyName", "Email")
                        if isinstance(value := profile.get(key), str) and value.strip()}
            if not identity:
                return {"status": "error", "action": op.name, "error": "Mailjet returned an invalid profile"}
            result["data"] = identity
        return result
