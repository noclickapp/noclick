"""Enginemailer n8n v1 API, authenticated with a pasted API key.

Contract: https://connect.enginemailer.com/swagger/N8Nv1/swagger.json
Write fields: https://github.com/Enginemailer-Official/n8n-nodes-enginemailer/tree/main/nodes/Enginemailer/v1/actions/subscriber
Every operation makes one request; event reads return one bounded polling batch.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://connect.enginemailer.com/api/N8N/v1"
CREDENTIAL_TYPE = "enginemailer_api_key"


class EnginemailerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Enginemailer API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://portal.enginemailer.com/Account/UserProfile",
            "x-credential-instructions": "In Enginemailer, open your account's API Keys and copy an API key. Paste only the key here. NoClick sends it in the APIKEY header to connect.enginemailer.com.",
            "x-help-url": "https://enginemailer.zendesk.com/hc/en-us/articles/360057634711-Manage-API-keys-for-your-account",
        },
    )
    credential_type: Literal["enginemailer_api_key"] = Field(
        CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API Key",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or any(
            c.isspace() or ord(c) < 32 or ord(c) > 126 for c in value
        ):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Polling(_Input):
    limit: int = Field(
        50,
        ge=1,
        le=1000,
        title="Batch Limit",
        description="One batch only. A full batch may leave more events; use lastpollingdate to select the next polling window.",
    )
    lastpollingdate: str | None = Field(
        None,
        max_length=100,
        title="Last Polling Date",
        description="Provider polling timestamp; omission uses the API's default window.",
    )


class _Email(_Input):
    email: str = Field(..., min_length=3, max_length=254, title="Subscriber Email")

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use a subscriber email address")
        return value


class CustomField(_Input):
    customfield_key: str = Field(..., min_length=1, max_length=200)
    customfield_value: str = Field(..., max_length=10000)


class SubstitutionTag(_Input):
    Key: str = Field(..., min_length=1, max_length=200)
    Value: str = Field(..., max_length=10000)


class CheckConnection(_Input):
    operation: Literal["check_connection"] = Field(
        "check_connection",
        title="Check Connection",
        json_schema_extra={"ui:hidden": True},
    )


class ListNewSubscribers(_Polling):
    operation: Literal["list_new_subscribers"] = Field(
        "list_new_subscribers",
        title="List New Subscribers",
        json_schema_extra={"ui:hidden": True},
    )
    source: str | None = Field(None, max_length=200)
    filter_form: int | None = Field(None, ge=0)
    filter_page: int | None = Field(None, ge=0)
    filter_popup: int | None = Field(None, ge=0)


class ListUnsubscribeEvents(_Polling):
    operation: Literal["list_unsubscribe_events"] = Field(
        "list_unsubscribe_events",
        title="List Unsubscribe Events",
        json_schema_extra={"ui:hidden": True},
    )
    filter: str | None = Field(None, max_length=200)
    filter_campaign: int | None = Field(None, ge=0)
    filter_autoresponder: int | None = Field(None, ge=0)


class ListModifiedSubscribers(_Polling):
    operation: Literal["list_modified_subscribers"] = Field(
        "list_modified_subscribers",
        title="List Modified Subscribers",
        json_schema_extra={"ui:hidden": True},
    )


class ListDeletedSubscribers(_Polling):
    operation: Literal["list_deleted_subscribers"] = Field(
        "list_deleted_subscribers",
        title="List Deleted Subscribers",
        json_schema_extra={"ui:hidden": True},
    )


class ListTaggedSubscribers(_Polling):
    operation: Literal["list_tagged_subscribers"] = Field(
        "list_tagged_subscribers",
        title="List Tagged Subscribers",
        json_schema_extra={"ui:hidden": True},
    )
    filter_subcategory: int | None = Field(None, ge=0)


class ListUntaggedSubscribers(_Polling):
    operation: Literal["list_untagged_subscribers"] = Field(
        "list_untagged_subscribers",
        title="List Untagged Subscribers",
        json_schema_extra={"ui:hidden": True},
    )
    filter_subcategory: int | None = Field(None, ge=0)


class ListAutoresponderTriggered(_Polling):
    operation: Literal["list_autoresponder_triggered"] = Field(
        "list_autoresponder_triggered",
        title="List Autoresponder Triggered",
        json_schema_extra={"ui:hidden": True},
    )
    filter_autoresponder: int | None = Field(None, ge=0)


class ListAutoresponderCompleted(_Polling):
    operation: Literal["list_autoresponder_completed"] = Field(
        "list_autoresponder_completed",
        title="List Autoresponder Completed",
        json_schema_extra={"ui:hidden": True},
    )
    filter_autoresponder: int | None = Field(None, ge=0)


class ListSubcategories(_Input):
    operation: Literal["list_subcategories"] = Field(
        "list_subcategories",
        title="List Subcategories",
        json_schema_extra={"ui:hidden": True},
    )


class ListForms(_Input):
    operation: Literal["list_forms"] = Field(
        "list_forms", title="List Forms", json_schema_extra={"ui:hidden": True}
    )


class ListPages(_Input):
    operation: Literal["list_pages"] = Field(
        "list_pages", title="List Pages", json_schema_extra={"ui:hidden": True}
    )


class ListPopups(_Input):
    operation: Literal["list_popups"] = Field(
        "list_popups", title="List Popups", json_schema_extra={"ui:hidden": True}
    )


class ListAutoresponders(_Input):
    operation: Literal["list_autoresponders"] = Field(
        "list_autoresponders",
        title="List Autoresponders",
        json_schema_extra={"ui:hidden": True},
    )


class ListCampaigns(_Input):
    operation: Literal["list_campaigns"] = Field(
        "list_campaigns", title="List Campaigns", json_schema_extra={"ui:hidden": True}
    )


class ListDomains(_Input):
    operation: Literal["list_domains"] = Field(
        "list_domains", title="List Domains", json_schema_extra={"ui:hidden": True}
    )


class ListTemplates(_Input):
    operation: Literal["list_templates"] = Field(
        "list_templates", title="List Templates", json_schema_extra={"ui:hidden": True}
    )


class AddUpdateSubscriber(_Email):
    operation: Literal["add_update_subscriber"] = Field(
        "add_update_subscriber",
        title="Add or Update Subscriber",
        json_schema_extra={"ui:hidden": True},
    )
    sourcetype: str = Field("Signup from website", max_length=500, title="Source Type")
    subcategories: list[int] = Field(default_factory=list, title="Subcategory IDs")
    customfields: list[CustomField] = Field(default_factory=list, title="Custom Fields")
    updatetype: Literal["Overwrite", "Append", "Ignore"] = Field(
        "Ignore",
        title="Existing Data",
        description="Ignore leaves existing data; Overwrite replaces it; Append applies to subcategories only.",
    )


class UnsubscribeSubscriber(_Email):
    operation: Literal["unsubscribe_subscriber"] = Field(
        "unsubscribe_subscriber",
        title="Unsubscribe Subscriber",
        json_schema_extra={"ui:hidden": True},
    )


class DeleteSubscriber(_Email):
    operation: Literal["delete_subscriber"] = Field(
        "delete_subscriber",
        title="Delete Subscriber",
        json_schema_extra={"ui:hidden": True},
    )


class TagSubscriber(_Email):
    operation: Literal["tag_subscriber"] = Field(
        "tag_subscriber", title="Tag Subscriber", json_schema_extra={"ui:hidden": True}
    )
    subcategories: list[int] = Field(
        ..., min_length=1, max_length=1000, title="Subcategory IDs"
    )


class UntagSubscriber(_Email):
    operation: Literal["untag_subscriber"] = Field(
        "untag_subscriber",
        title="Untag Subscriber",
        json_schema_extra={"ui:hidden": True},
    )
    subcategories: list[int] = Field(
        ..., min_length=1, max_length=1000, title="Subcategory IDs"
    )


class FindSubscriber(_Email):
    operation: Literal["find_subscriber"] = Field(
        "find_subscriber",
        title="Find Subscriber",
        json_schema_extra={"ui:hidden": True},
    )


class SendEmail(_Email):
    operation: Literal["send_email"] = Field(
        "send_email", title="Send HTML Email", json_schema_extra={"ui:hidden": True}
    )
    type: Literal["html"] = Field("html", title="Content Type")
    html: str = Field(
        ...,
        min_length=1,
        max_length=1000000,
        title="HTML Content",
        json_schema_extra={"ui:show-if": {"type": "html"}, "ui:widget": "textarea"},
    )
    subject: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        title="Subject",
        json_schema_extra={"ui:show-if": {"type": "html"}},
    )
    sender_email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        title="Sender Email",
        json_schema_extra={"ui:show-if": {"type": "html"}},
    )
    sender_name: str | None = Field(None, max_length=500, title="Sender Name")
    substitution_tags: list[SubstitutionTag] | None = Field(
        None, title="Substitution Tags"
    )
    cc_emails: str | None = Field(
        None,
        max_length=2600,
        title="CC Emails",
        description="Up to 10 comma-separated email addresses.",
    )

    @field_validator("sender_email")
    @classmethod
    def sender(cls, value):
        return _Email.email_address(value) if value is not None else value

    @field_validator("cc_emails")
    @classmethod
    def copies(cls, value):
        if value is not None:
            addresses = value.split(",")
            if len(addresses) > 10:
                raise ValueError("Use at most ten CC emails")
            for address in addresses:
                _Email.email_address(address.strip())
        return value


Operation = Annotated[
    Union[
        CheckConnection,
        ListNewSubscribers,
        ListUnsubscribeEvents,
        ListModifiedSubscribers,
        ListDeletedSubscribers,
        ListTaggedSubscribers,
        ListUntaggedSubscribers,
        ListAutoresponderTriggered,
        ListAutoresponderCompleted,
        ListSubcategories,
        ListForms,
        ListPages,
        ListPopups,
        ListAutoresponders,
        ListCampaigns,
        ListDomains,
        ListTemplates,
        AddUpdateSubscriber,
        UnsubscribeSubscriber,
        DeleteSubscriber,
        TagSubscriber,
        UntagSubscriber,
        FindSubscriber,
        SendEmail,
    ],
    Field(discriminator="operation"),
]


class EnginemailerConfig(NodeConfig[Operation, EnginemailerAPIKeyCredential]):
    pass


ROUTES = {
    "check_connection": ("GET", "/connect"),
    "list_new_subscribers": ("GET", "/newsubscribers"),
    "list_unsubscribe_events": ("GET", "/unsubscribe"),
    "list_modified_subscribers": ("GET", "/subscribersmodified"),
    "list_deleted_subscribers": ("GET", "/subscribersdeleted"),
    "list_tagged_subscribers": ("GET", "/subscriberstagged"),
    "list_untagged_subscribers": ("GET", "/subscribersuntagged"),
    "list_autoresponder_triggered": ("GET", "/subscriberautorespondertriggered"),
    "list_autoresponder_completed": ("GET", "/subscriberautorespondercompleted"),
    "list_subcategories": ("GET", "/listsubcategories"),
    "list_forms": ("GET", "/listforms"),
    "list_pages": ("GET", "/listpages"),
    "list_popups": ("GET", "/listpopups"),
    "list_autoresponders": ("GET", "/listautoresponders"),
    "list_campaigns": ("GET", "/listcampaigns"),
    "list_domains": ("GET", "/listdomains"),
    "list_templates": ("GET", "/listtemplates"),
    "add_update_subscriber": ("POST", "/addupdatesubscriber"),
    "unsubscribe_subscriber": ("POST", "/unsubscribe"),
    "delete_subscriber": ("POST", "/deletesubscriber"),
    "tag_subscriber": ("POST", "/tagtosubcategory"),
    "untag_subscriber": ("POST", "/untagtosubcategory"),
    "find_subscriber": ("POST", "/findsubscriber"),
    "send_email": ("POST", "/sendemail"),
}


class EnginemailerNode(WorkflowNode):
    integration_type = "automation-enginemailer"
    connection_evidence = ConnectionEvidence(
        operation="list_subcategories",
        noun="subcategories",
        label_keys=("Name", "name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return EnginemailerConfig

    @staticmethod
    def _check_credential(data):
        raw = data.get("credentials")
        if raw is not None and (
            not isinstance(raw, dict)
            or raw.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE
        ):
            raise ValueError("Attach an Enginemailer API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Enginemailer API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers={
                    "APIKEY": self.config.credentials.api_key,
                    "Accept": "application/json",
                },
                **({"params": values} if method == "GET" else {"json": values}),
            )
        if not 200 <= response.status_code < 300:
            # Preserve provider text, while removing an echoed key and never exposing HTML.
            message = "Enginemailer rejected the request"
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = str(
                        body.get("message")
                        or body.get("Message")
                        or body.get("error")
                        or message
                    )
            except ValueError:
                pass
            message = message.replace(self.config.credentials.api_key, "[redacted]")[
                :1000
            ]
            raise ValueError(f"Enginemailer HTTP {response.status_code}: {message}")
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if len(response.content) > 10_000_000 or not (
            mime == "application/json" or mime.endswith("+json")
        ):
            raise ValueError("Expected a bounded Enginemailer JSON response")
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Expected an Enginemailer JSON object or array")
        if isinstance(body, dict) and (
            body.get("error")
            or body.get("Error")
            or body.get("errors")
            or body.get("success") is False
            or body.get("Success") is False
        ):
            raise ValueError(
                str(body).replace(self.config.credentials.api_key, "[redacted]")[:1000]
            )
        # Preserve object envelopes and wrap arrays for workflow output consumers.
        # An HTTP acknowledgement does not establish email delivery or write readback.
        return {"data": body} if isinstance(body, list) else body
