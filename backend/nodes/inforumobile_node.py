"""InforUMobile v2 RPC operations, pinned to the provider's Postman collection.

Each action issues one POST. No retries on message sends or other writes.
The provider's StatusId envelope is checked even for HTTP 200 responses.
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

DOCS = "https://documenter.getpostman.com/view/15332030/TzeWFTF1"
BASE = "https://capi.inforu.co.il"


class InforUMobileCredential(BaseModel):
    model_config = ConfigDict(title="InforUMobile API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Enter your InforUMobile username and API token. NoClick encodes username:token as HTTP Basic authentication. Connecting reads your contact groups; it sends no messages."})
    credential_type: Literal["inforumobile_api_token"] = Field("inforumobile_api_token", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=256, title="Username")
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter the InforUMobile username without a colon or control characters")
        return value

    @field_validator("api_token")
    @classmethod
    def valid_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without whitespace or an Authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Text = Annotated[str, Field(min_length=1, max_length=100000)]
Identifier = Annotated[str, Field(min_length=1, max_length=512)]


class PhoneRecipient(_Input):
    Phone: Identifier


class SmsSettings(_Input):
    Sender: str = Field(..., min_length=1, max_length=14, description="Whitelisted sender: up to 11 characters without spaces, or up to 14 phone digits.")

    @field_validator("Sender")
    @classmethod
    def valid_sender(cls, value):
        if any(c.isspace() for c in value) or (len(value) > 11 and not value.isdigit()):
            raise ValueError("Use a sender of up to 11 characters or a phone of up to 14 digits")
        return value


class TemplateParameter(_Input):
    Name: Identifier
    Type: Literal["Contact", "Custom", "Text"]
    Value: Text


class TemplateRecipient(PhoneRecipient):
    CouponCode: str | None = None


class EmailRecipient(_Input):
    Email: Identifier
    FirstName: str | None = None


class Contact(_Input):
    Email: str | None = None
    PhoneNumber: str | None = None
    FirstName: str | None = None
    LastName: str | None = None
    AddToGroupName: str | None = None

    @model_validator(mode="after")
    def identifier(self):
        if not (self.Email or self.PhoneNumber):
            raise ValueError("Each contact needs Email or PhoneNumber")
        return self


class ContactSelector(_Input):
    Type: Literal["Phone", "Email", "ContactRefId", "ContactId"]
    Value: Identifier


class UnsubscribeSelector(_Input):
    Type: Literal["Phone", "Email"]
    Value: Identifier


class SendSms(_Input):
    """Send an SMS to explicit recipients using a whitelisted sender."""
    operation: Literal["send_sms"] = "send_sms"
    Message: Text
    Recipients: list[PhoneRecipient] = Field(..., min_length=1, max_length=100)
    Settings: SmsSettings


class SendWhatsAppTemplate(_Input):
    """Send an existing WhatsApp template to explicit recipients."""
    operation: Literal["send_whatsapp_template"] = "send_whatsapp_template"
    TemplateId: Identifier
    TemplateParameters: list[TemplateParameter] = Field(..., max_length=100)
    Recipients: list[TemplateRecipient] = Field(..., min_length=1, max_length=100)


class ListWhatsAppTemplates(_Input):
    """Read the connected user's WhatsApp templates."""
    operation: Literal["list_whatsapp_templates"] = "list_whatsapp_templates"


class GetWhatsAppTemplate(_Input):
    operation: Literal["get_whatsapp_template"] = "get_whatsapp_template"
    TemplateId: Identifier


class SendEmail(_Input):
    """Send a new email campaign with explicit recipients and content."""
    operation: Literal["send_email"] = "send_email"
    CampaignName: Identifier
    CampaignRefId: str | None = None
    FromAddress: Identifier
    ReplyAddress: str | None = None
    FromName: str | None = None
    Subject: Text
    Body: Text
    IncludeContacts: list[EmailRecipient] = Field(..., min_length=1, max_length=100)


class SendEmailCampaign(_Input):
    """Send an existing campaign to explicit recipients; optionally duplicate it."""
    operation: Literal["send_email_campaign"] = "send_email_campaign"
    CampaignId: Identifier
    Duplicate: Literal[0, 1] = Field(..., description="0 sends the existing campaign; 1 duplicates it.")
    IncludeContacts: list[EmailRecipient] = Field(..., min_length=1, max_length=100)


class UpsertContacts(_Input):
    """Create or update up to ten contacts for a final synchronous response."""
    operation: Literal["upsert_contacts"] = "upsert_contacts"
    List: list[Contact] = Field(..., min_length=1, max_length=10)


class GetContact(ContactSelector):
    operation: Literal["get_contact"] = "get_contact"
    Configuration: Literal["WithGroups", "WithoutGroups"] = "WithoutGroups"


class ListContacts(_Input):
    """Read a contact page. Pass Data.LastFetchedId to continue."""
    operation: Literal["list_contacts"] = "list_contacts"
    FilterBy: Literal["CreatedDate", "UpdatedDate"]
    FromDate: str = Field(..., description="YYYY/MM/DD, inclusive")
    ToDate: str = Field(..., description="YYYY/MM/DD, inclusive")
    OnlyForGroupId: str | None = None
    LastFetchedId: int = Field(0, ge=0)

    @field_validator("FromDate", "ToDate")
    @classmethod
    def date_value(cls, value):
        datetime.strptime(value, "%Y/%m/%d")
        return value


class DeleteContacts(_Input):
    """Delete explicit contacts from all their groups."""
    operation: Literal["delete_contacts"] = "delete_contacts"
    List: list[ContactSelector] = Field(..., min_length=1, max_length=100)


class UpsertGroup(_Input):
    operation: Literal["upsert_group"] = "upsert_group"
    GroupName: Identifier
    GroupId: int = Field(..., ge=0, description="0 creates a group; an existing ID updates it.")


class GetGroup(_Input):
    operation: Literal["get_group"] = "get_group"
    GetGroupBy: Literal["GroupId", "GroupNumber", "GroupName"]
    Value: Identifier


class ListGroups(_Input):
    """Read the account's contact groups. The pinned request has no filters."""
    operation: Literal["list_groups"] = "list_groups"


class DeleteGroup(_Input):
    """Delete groups by explicit identifier. GroupName can match multiple groups."""
    operation: Literal["delete_group"] = "delete_group"
    DeleteGroupBy: Literal["GroupId", "GroupNumber", "GroupName"]
    Value: Identifier
    Configuration: Literal["WithoutDeleteContacts", "WithDeleteContacts", "EmptyGroupOnly"] = "WithoutDeleteContacts"


class Unsubscribe(_Input):
    operation: Literal["unsubscribe"] = "unsubscribe"
    UnsubscribeReason: Text
    List: list[UnsubscribeSelector] = Field(..., min_length=1, max_length=100)


class CheckUnsubscribed(_Input):
    operation: Literal["check_unsubscribed"] = "check_unsubscribed"
    List: list[ContactSelector] = Field(..., min_length=1, max_length=100)


class GetUnsubscribeHistory(ContactSelector):
    operation: Literal["get_unsubscribe_history"] = "get_unsubscribe_history"


class ListUnsubscribed(_Input):
    """Read an unsubscribe page; continue with the returned LastFetchedId."""
    operation: Literal["list_unsubscribed"] = "list_unsubscribed"
    FromDate: str = Field(..., description="YYYY/MM/DD, inclusive")
    ToDate: str = Field(..., description="YYYY/MM/DD, inclusive")
    Type: Literal["Phone", "Email"]
    LastFetchedId: int = Field(0, ge=0)

    @field_validator("FromDate", "ToDate")
    @classmethod
    def date_value(cls, value):
        datetime.strptime(value, "%Y/%m/%d")
        return value


class ListUnsubscribeHistory(ListUnsubscribed):
    operation: Literal["list_unsubscribe_history"] = "list_unsubscribe_history"
    Action: Literal["All", "Unsubscribe", "Reactivate"] = "All"


class GetQuota(_Input):
    """Read remaining SMS, email and voice quotas for this account or a child level."""
    operation: Literal["get_quota"] = "get_quota"
    QuotaUsageType: Literal["", "SMS", "Email", "IVR"] | None = None
    Level: Literal["Partner", "Customer", "Project", "User"] | None = None
    LevelValue: str | None = None


InforUMobileConfig = Annotated[Union[SendSms, SendWhatsAppTemplate,
    ListWhatsAppTemplates, GetWhatsAppTemplate, SendEmail, SendEmailCampaign,
    UpsertContacts, GetContact, ListContacts,
    DeleteContacts, UpsertGroup, GetGroup, ListGroups, DeleteGroup, Unsubscribe,
    CheckUnsubscribed, GetUnsubscribeHistory, ListUnsubscribed, ListUnsubscribeHistory,
    GetQuota], Field(discriminator="operation")]


class InforUMobileFullConfig(NodeConfig[InforUMobileConfig, InforUMobileCredential]):
    pass


# Exact paths, including case and trailing slashes, from the pinned collection.
ROUTES = {
    "send_sms": "/api/v2/SMS/SendSms",
    "send_whatsapp_template": "/api/v2/WhatsApp/SendWhatsApp",
    "list_whatsapp_templates": "/api/v2/WhatsApp/GetTemplateList",
    "get_whatsapp_template": "/api/v2/WhatsApp/GetTemplate",
    "send_email": "/api/v2/Umail/Message/Send",
    "send_email_campaign": "/api/v2/Umail/Campaign/Send/",
    "upsert_contacts": "/api/v2/Contact/CreateOrUpdateContacts",
    "get_contact": "/api/v2/Contact/GetContact",
    "list_contacts": "/api/v2/Contact/GetContactList",
    "delete_contacts": "/api/v2/Contact/DeleteContacts",
    "upsert_group": "/api/v2/Contact/CreateOrUpdateGroup",
    "get_group": "/api/v2/Contact/GetGroup",
    "list_groups": "/api/v2/Contact/GetGroupList",
    "delete_group": "/api/v2/Contact/DeleteGroup",
    "unsubscribe": "/api/V2/Contact/Unsubscribe",
    "check_unsubscribed": "/api/v2/Contact/CheckIfUnsubscribe",
    "get_unsubscribe_history": "/api/v2/Contact/GetUnsubscribeHistory",
    "list_unsubscribed": "/api/v2/Contact/GetUnsubscribeList",
    "list_unsubscribe_history": "/api/v2/Contact/GetUnsubscribeHistoryList",
    "get_quota": "/api/v2/Admin/GetQuota",
}


class InforUMobileNode(WorkflowNode):
    integration_type = "automation-inforumobile"
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="contact groups",
        label_keys=("GroupName", "GroupId"))

    @classmethod
    def get_config_model(cls):
        return InforUMobileFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an InforUMobile API token")
        config = self.config.config
        credentials = self.config.credentials
        encoded = base64.b64encode(f"{credentials.username}:{credentials.api_token}".encode()).decode()
        media = "application/json; charset=utf-8" if config.operation in {
            "send_sms", "send_email", "send_email_campaign", "get_quota"} else "application/json"
        headers = {"Authorization": "Basic " + encoded, "Accept": "application/json", "Content-Type": media}
        body = config.model_dump(exclude={"operation"}, exclude_none=True)
        if config.operation == "get_quota" and not config.QuotaUsageType:
            # The shared config lens normalizes an empty picker to None. The
            # documented empty string asks for every quota product.
            body["QuotaUsageType"] = ""
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST", BASE + ROUTES[config.operation],
                headers=headers, json={"Data": body})
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"InforUMobile returned a non-JSON response (HTTP {response.status_code})") from None
        if not isinstance(payload, dict) or type(payload.get("StatusId")) is not int:
            raise ValueError("InforUMobile returned an unexpected response envelope")
        if response.is_error or payload["StatusId"] != 1:
            message = str(payload.get("StatusDescription") or f"HTTP {response.status_code}")
            # Keep the provider's rejection wording while excluding credential echoes.
            for secret in (credentials.api_token, encoded):
                message = message.replace(secret, "[redacted]")
            raise ValueError(f"{message} (HTTP {response.status_code})")
        if not 200 <= response.status_code < 300:
            raise ValueError(f"InforUMobile returned HTTP {response.status_code}")
        data = payload.get("Data")
        result = {"status": "success", "data": data, "response": payload}
        if config.operation == "list_groups":
            if not isinstance(data, dict) or not isinstance(data.get("List"), list):
                raise ValueError("InforUMobile returned an unexpected group list")
            result["items"] = data["List"]
        await self.emit(result)
        return result
