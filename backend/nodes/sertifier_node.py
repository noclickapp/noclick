"""Sertifier Credential API v3.3: one provider request per operation.

Contract: https://docs.sertifier.com/specs/sertifier-v3.2.yaml
Search operations return one explicit startIndex/length page. Publishing and
sending can notify recipients; their acknowledgment does not prove delivery.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://b2b.sertifier.com"
API_VERSION = "3.3"


class SertifierAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Sertifier API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.sertifier.com/",
            "x-credential-instructions": "In Sertifier, open Settings > API & Integrations and copy your organization's private API key. Paste the key here without a header name. NoClick sends it only to b2b.sertifier.com.",
        },
    )
    credential_type: Literal["sertifier_api_key"] = Field(
        "sertifier_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Private API key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="Private API key")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError(
                "Paste the private API key without whitespace or a header name"
            )
        return value


class _Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, hide_input_in_errors=True
    )


class SertifierGetDesignConfig(_Input):
    """Get Design."""

    operation: Literal["get_design"] = Field(
        "get_design",
        title="Get Design",
        description="Returns detailed information about the Design. The `id` of the Design is placed in the parameters.\n\nThe `preview` field in the response will contain the HTML of the design.\n",
        json_schema_extra={"ui:hidden": True},
    )
    design_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Design"
    )


class SertifierSearchDesignsConfig(_Input):
    """Search Designs."""

    operation: Literal["search_designs"] = Field(
        "search_designs",
        title="Search Designs",
        description="Returns the organizations Designs in paginated format. The pagination is handled with the `startIndex` and `length` keys in the request body.\nThere are two filtering options within the body:\n\n- `type` field is used for filtering between certificate and badge designs\n  - 1 -> certificate\n  - 2 -> badge\n- `searchTerm` field is searched within the titles of the designs\n\nThe `preview` field in the response will contain the HTML of the design.\n",
        json_schema_extra={"ui:hidden": True},
    )
    start_index: int = Field(0, alias="startIndex", ge=0)
    length: int = Field(50, ge=1, le=1000)
    type: int | None = Field(None, description="1 = certificate, 2 = badge")
    search_term: str | None = Field(None, alias="searchTerm")


class SertifierSkill(_Input):
    skill_id: str | None = Field(
        None,
        alias="skillId",
        description="Skill ID from /detail/searchSkills, leave blank for custom skills",
    )
    title: str = Field(..., min_length=1)
    language_code: Literal["en", "tr"] = Field(
        ..., alias="languageCode", description="Skill language"
    )


class SertifierAddDetailConfig(_Input):
    """Add Detail."""

    operation: Literal["add_detail"] = Field(
        "add_detail",
        title="Add Detail",
        description='Creates a detail.\n\nDetails for the body of the request:\n\n- `type` enum value, the type of event which the credential is being issued for\n- `title` the credential title\n- `description` the credential description\n- _Duration_ the duration of the event\n  - The duration is a combination of two fields `durationNumber` and `durationType`\n  - `durationNumber` indicates the integer value for the `durationType` enum value which is the unit time\n- `cost` enum value, the cost of the event or course\n- _Expire Date_ expire date of the credential, **not required**\n  - There are **two different options for the expire date of the credential**\n    1. Set an exact expire date for every credential sent with this _Detail_ (ex: 01/01/2023). This option uses `expireDate` (DateTime) field\n    2. Set a time span which will be added to the credential\'s issue date (ex: 2 years). This option uses `expireDateNumber` (int) and `expireDateType` (DurationType enum) fields\n  - If none of these options are used, the expire date will be set to _null_\n  - **If the expire date is set**, you have the option of customizing your expiry date reminder email schedule. With the `expiryReminderDays` field, you can send *how many days before the expire date* you want reminders to be sent by email to the recipient.\n    - You can set a *maximum of 3* reminder emails\n    - The field is a list of `int`, where each integer corresponds to the count of days before the expire date. So for example `[1, 2, 4]` means that an email will be sent 1 day, 2 days and 4 days before the credential expires.\n- `level` enum value, level of the event or course\n- `earningCriteria` the information given as earning criteria for the course or event, **not required**\n  - The input can be given as HTML code, the HTML will be rendered in the credential verification page below the "Earning Criteria" title\n- `skills` the skills related to the Detail, minimum one skill is required for the `status` to be _Ready_\n  - The skills can be obtained from the `/SearchSkills` address\n    - The `skillId` field can be retrieved from the `/SearchSkills` address, this field can be left blank to add custom skills to the Detail\n  - `languageCode` has to be _en_ or _tr_\n- `dontSendExpireDateEmail` field is a boolean field used for controlling if users should be notified automatically when the expire date of credential is approaching\n',
        json_schema_extra={"ui:hidden": True},
    )
    type: int = Field(
        ...,
        description="Detail type enum (0=Field Event, 1=Online Event, 2=Class Course, 3=Online Course, 4=Webinar, 5=Achievement, 6=License, 7=Appreciation, 8=Promotional Course, 9=Membership, 10=Graduation, 11=Hybrid Event, 12=Hybrid Course)",
    )
    title: str = Field(..., min_length=1)
    description: str | None = Field(None)
    duration_number: int | None = Field(None, alias="durationNumber")
    duration_type: int | None = Field(
        None,
        alias="durationType",
        description="Duration type enum (1=Hour, 2=Day, 3=Week, 4=Month, 5=Year, 6=Minute)",
    )
    cost: int | None = Field(None, description="Cost enum (0=Free, 1=Paid, 2=NA)")
    expire_date: date | None = Field(None, alias="expireDate")
    expire_date_number: int | None = Field(None, alias="expireDateNumber")
    expire_date_type: int | None = Field(
        None, alias="expireDateType", description="DurationType enum value"
    )
    level: int | None = Field(
        None,
        description="Level enum (0=Beginner, 1=Intermediate, 2=Advanced, 3=Experienced, 4=Professional, 5=NA)",
    )
    earning_criteria: str | None = Field(
        None, alias="earningCriteria", description="Earning criteria, can be HTML"
    )
    dont_send_expire_date_email: bool | None = Field(
        None, alias="dontSendExpireDateEmail"
    )
    skills: list[SertifierSkill] | None = Field(None, min_length=0, max_length=1000)
    expiry_reminder_days: list[int] | None = Field(
        None,
        alias="expiryReminderDays",
        description="List of days before expire date to send reminders (max 3)",
        min_length=0,
        max_length=3,
    )


class SertifierUpdateDetailConfig(_Input):
    """Update Detail."""

    operation: Literal["update_detail"] = Field(
        "update_detail",
        title="Update Detail",
        description='Update a Detail with the `id`, placed in the parameters. Only the provided fields in the request body will be updated, the rest will remain unchanged. If skills are provided, old skills will be deleted and new skills will be created in place.\n\nIf Detail `status` is _Sent_, it can **not** be updated. You can copy the Detail with the `/Copy` address if you wish to use an edited version of the original Detail.\n\nDetails for the body of the request:\n\n- `type` enum value, the type of event which the credential is being issued for\n- `title` the credential title\n- `description` the credential description\n- _Duration_ the duration of the event\n  - The duration is a combination of two fields `durationNumber` and `durationType`\n  - `durationNumber` indicates the integer value for the `durationType` enum value which is the unit time\n- `cost` enum value, the cost of the event or course\n- _Expire Date_ expire date of the credential, **not required**\n  - There are **two different options for the expire date of the credential**\n    1. Set an exact expire date for every credential sent with this _Detail_ (ex: 01/01/2023). This option uses `expireDate` (DateTime) field\n    2. Set a time span which will be added to the credential\'s issue date (ex: 2 years). This option uses `expireDateNumber` (int) and `expireDateType` (DurationType enum) fields\n  - If none of these options are used, the expire date will be set to _null_\n- `level` enum value, level of the event or course\n- `earningCriteria` the information given as earning criteria for the course or event, **not required**\n  - The input can be given as HTML code, the HTML will be rendered in the credential verification page below the "Earning Criteria" title\n- `skills` the skills related to the Detail, minimum one skill is required for the `status` to be _Ready_\n  - The skills can be obtained from the `/SearchSkills` address\n    - The `skillId` field can be retrieved from the `/SearchSkills` address, this field can be left blank to add custom skills to the Detail\n  - `languageCode` has to be _en_ or _tr_\n- `dontSendExpireDateEmail` field is a boolean field used for controlling if users should be notified automatically when the expire date of credential is approaching\n',
        json_schema_extra={"ui:hidden": True},
    )
    detail_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Detail"
    )
    type: int | None = Field(
        None,
        description="Detail type enum (0=Field Event, 1=Online Event, 2=Class Course, 3=Online Course, 4=Webinar, 5=Achievement, 6=License, 7=Appreciation, 8=Promotional Course, 9=Membership, 10=Graduation, 11=Hybrid Event, 12=Hybrid Course)",
    )
    title: str | None = Field(None)
    description: str | None = Field(None)
    duration_number: int | None = Field(None, alias="durationNumber")
    duration_type: int | None = Field(
        None,
        alias="durationType",
        description="Duration type enum (1=Hour, 2=Day, 3=Week, 4=Month, 5=Year, 6=Minute)",
    )
    cost: int | None = Field(None, description="Cost enum (0=Free, 1=Paid, 2=NA)")
    expire_date: date | None = Field(None, alias="expireDate")
    expire_date_number: int | None = Field(None, alias="expireDateNumber")
    expire_date_type: int | None = Field(
        None, alias="expireDateType", description="DurationType enum value"
    )
    level: int | None = Field(
        None,
        description="Level enum (0=Beginner, 1=Intermediate, 2=Advanced, 3=Experienced, 4=Professional, 5=NA)",
    )
    earning_criteria: str | None = Field(
        None, alias="earningCriteria", description="Earning criteria, can be HTML"
    )
    dont_send_expire_date_email: bool | None = Field(
        None, alias="dontSendExpireDateEmail"
    )
    skills: list[SertifierSkill] | None = Field(None, min_length=0, max_length=1000)
    expiry_reminder_days: list[int] | None = Field(
        None,
        alias="expiryReminderDays",
        description="List of days before expire date to send reminders (max 3)",
        min_length=0,
        max_length=3,
    )


class SertifierGetDetailConfig(_Input):
    """Get Detail."""

    operation: Literal["get_detail"] = Field(
        "get_detail",
        title="Get Detail",
        description="Gives the single Detail with the given `id` which is placed in the parameters.",
        json_schema_extra={"ui:hidden": True},
    )
    detail_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Detail"
    )


class SertifierSearchDetailsConfig(_Input):
    """Search Details."""

    operation: Literal["search_details"] = Field(
        "search_details",
        title="Search Details",
        description="Returns the organizations Details in paginated format. The pagination is handled with the `startIndex` and `length` keys in the request body.\nThere is one filtering option within the body:\n\n- `searchTerm` field is searched within the titles of the Details\n",
        json_schema_extra={"ui:hidden": True},
    )
    start_index: int = Field(
        0, alias="startIndex", description="Start index for pagination", ge=0
    )
    length: int = Field(50, description="Number of results to return", ge=1, le=1000)
    search_term: str | None = Field(
        None, alias="searchTerm", description="Search term to filter results"
    )


class SertifierGetEmailTemplateConfig(_Input):
    """Get EmailTemplate."""

    operation: Literal["get_email_template"] = Field(
        "get_email_template",
        title="Get EmailTemplate",
        description="Returns all of the details of the _EmailTemplate_. Takes the `id` of the _EmailTemplate_ in the parameters.",
        json_schema_extra={"ui:hidden": True},
    )
    emailtemplate_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the EmailTemplate"
    )


class SertifierSearchEmailTemplatesConfig(_Input):
    """Search EmailTemplates."""

    operation: Literal["search_email_templates"] = Field(
        "search_email_templates",
        title="Search EmailTemplates",
        description="Returns the organizations EmailTemplates in paginated format. The pagination is handled with the `startIndex` and `length` keys in the request body.\nThere is one filtering option within the body:\n\n- `searchTerm` field is searched within the titles of the EmailTemplates\n",
        json_schema_extra={"ui:hidden": True},
    )
    start_index: int = Field(
        0, alias="startIndex", description="Start index for pagination", ge=0
    )
    length: int = Field(50, description="Number of results to return", ge=1, le=1000)
    search_term: str | None = Field(
        None, alias="searchTerm", description="Search term to filter results"
    )


class SertifierAddCampaignConfig(_Input):
    """Add Campaign."""

    operation: Literal["add_campaign"] = Field(
        "add_campaign",
        title="Add Campaign",
        description="Creates a Campaign.\n\nDetails for the body of the request:\n\n- `title` Campaign title\n- `mailBody` Campaign mail body\n- `fromName` Campaign mail sender name\n- `fromAddress` Campaign mail sender email address\n- `emailTemplateId` the Id of the EmailTemplate which is going to be linked to the Campaign\n- `designId` the Id of the certificate Design which is going to be linked to the Campaign\n- `badgeId` the Id of the badge Design which is going to be linked to the Campaign\n- `detailId` the Id of the Detail which is going to be linked to the Campaign\n- `privateCampaign` boolean field used for controlling whether the credentials in the Campaign are shown in search results\n",
        json_schema_extra={"ui:hidden": True},
    )
    title: str = Field(..., min_length=1)
    detail_id: str = Field(..., alias="detailId", min_length=1)
    badge_id: str | None = Field(None, alias="badgeId")
    design_id: str | None = Field(None, alias="designId")
    email_template_id: str = Field(..., alias="emailTemplateId", min_length=1)
    email_from_name: str = Field(..., alias="emailFromName", min_length=1)
    email_subject: str = Field(..., alias="emailSubject", min_length=1)
    emailfrom_address: str | None = Field(None, alias="emailfromAddress")
    private_campaign: bool | None = Field(None, alias="privateCampaign")


class SertifierGetCampaignConfig(_Input):
    """Get Campaign."""

    operation: Literal["get_campaign"] = Field(
        "get_campaign",
        title="Get Campaign",
        description="Returns the _Campaign_ with the given `id`. The `id` value is given in the parameters.",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Campaign"
    )


class SertifierUpdateCampaignConfig(_Input):
    """Update Campaign."""

    operation: Literal["update_campaign"] = Field(
        "update_campaign",
        title="Update Campaign",
        description="Updates the Campaign with the given `id`. The provided fields will be updated, the rest will remain unchanged except for `designId` and `badgeId`. Those fields can be set to `null`.\n\nDetails for the body of the request:\n\n- `title` Campaign title\n- `mailBody` Campaign mail body\n- `fromName` Campaign mail sender name\n- `fromAddress` Campaign mail sender email address\n- `emailTemplateId` the Id of the EmailTemplate which is going to be linked to the Campaign\n- `designId` the Id of the certificate Design which is going to be linked to the Campaign\n- `badgeId` the Id of the badge Design which is going to be linked to the Campaign\n- `detailId` the Id of the Detail which is going to be linked to the Campaign\n",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Campaign"
    )
    title: str | None = Field(None)
    detail_id: str | None = Field(None, alias="detailId")
    badge_id: str | None = Field(None, alias="badgeId")
    design_id: str | None = Field(None, alias="designId")
    email_template_id: str | None = Field(None, alias="emailTemplateId")
    email_from_name: str | None = Field(None, alias="emailFromName")
    email_subject: str | None = Field(None, alias="emailSubject")
    emailfrom_address: str | None = Field(None, alias="emailfromAddress")
    private_campaign: bool | None = Field(None, alias="privateCampaign")


class SertifierDeleteCampaignConfig(_Input):
    """Delete Campaign."""

    operation: Literal["delete_campaign"] = Field(
        "delete_campaign",
        title="Delete Campaign",
        description="Deletes the Campaign with the given `id`. If the Campaign has _status_ **sent**, the credentials created from the Campaign will also be deleted. The `id` is passed in the parameters.\n",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Campaign"
    )


class SertifierSearchCampaignsConfig(_Input):
    """Search Campaigns."""

    operation: Literal["search_campaigns"] = Field(
        "search_campaigns",
        title="Search Campaigns",
        description="Returns the organizations Campaigns in paginated format. The pagination is handled with the `startIndex` and `length` keys in the request body.\nThere are two filtering options within the body:\n\n- `searchTerm` field is searched within the titles of the Campaigns\n- `status` field takes in the `status` enum values in an array to filter the results\n",
        json_schema_extra={"ui:hidden": True},
    )
    start_index: int = Field(0, alias="startIndex", ge=0)
    length: int = Field(50, ge=1, le=1000)
    status: list[int] | None = Field(
        None,
        description="Campaign status enum values (0=NoEntry, 1=Draft, 2=Scheduled, 3=Sent)",
        min_length=0,
        max_length=1000,
    )
    search_term: str | None = Field(None, alias="searchTerm")


class SertifierAttributeValue(_Input):
    id: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class SertifierCredentialInput(_Input):
    campaign_id: str = Field(..., alias="campaignId", min_length=1)
    name: str = Field(..., min_length=1)
    email: str | None = Field(None)
    issue_date: date | None = Field(
        None,
        alias="issueDate",
        description="Issue date, defaults to time of request if omitted",
    )
    expire_date: date | None = Field(None, alias="expireDate")
    quick_publish: bool = Field(
        False,
        alias="quickPublish",
        description="If true, credential is published immediately",
    )
    external_id: str | None = Field(None, alias="externalId")
    attributes: list[SertifierAttributeValue] | None = Field(
        None, min_length=0, max_length=1000
    )
    dont_send_email: bool = Field(
        False,
        alias="dontSendEmail",
        description="If true, no email notification is sent. Default is false",
    )


class SertifierAddCredentialsToCampaignConfig(_Input):
    """Add Credentials to Campaign."""

    operation: Literal["add_credentials_to_campaign"] = Field(
        "add_credentials_to_campaign",
        title="Add Credentials to Campaign",
        description="Add the Credentials to the Campaigns. The request body allows you to add multiple Credentials to multiple Campaigns.\n\nA Credential can be added without an email, but in this case when the credential is published, the recipient will not be notified via email.\n\nIf `quickPublish` is _true_ for a Credential, it will be directly published and sent to the Recipient. This field is widely used for not having to send a second request to publish the created Credentials. The Credential will be placed in a queue when published and the `certificateImageLink`, `badgeImageLink` and `verificationLink` fields in the response will start working once the Credential is out of the queue. They are returned in the response directly so that you can save them if needed.\n\n`externalId` is used for linking the credential with a specific entity that is in your database. It is used when you want to receive all of the credentials which are linked to a specific entity. Any kind of identifier can be used, an example would be the id of an user in your database.\n\n`attributes` are used when the Design or EmailTemplate has **custom** Attributes attached to them. The `id` of the Attributes can be received from the Attribute controller. Leave the list empty if no **custom** Attributes are used.\n\nDetails for the body of the request:\n\n- `credentials` credentials list\n  - `campaignId` id of the Campaign the Credential will be created in\n  - `name` Recipient name\n  - `email` Recipient email\n  - `issueDate` issue date of credential, will be set to the time of request if omitted\n  - `quickPublish` used for publishing the credential as soon as its created\n  - `externalId` external id of the Credential\n  - `attributes` list of attributes and the corresponding values for the Credential\n    - `id` Attribute id\n    - `value` Attribute value\n  - `dontSendEmail` controls if an email notification should be sent to the recipient. No email will be sent if set to `true`, default is `false`\n\nThe response will be a dictionary which will have the different `campaignId` values sent in the request as keys, and the Credential list which was added to that Campaign as the value.\n",
        json_schema_extra={"ui:hidden": True},
    )
    credentials: list[SertifierCredentialInput] = Field(
        ..., min_length=1, max_length=1000
    )


class SertifierSendCampaignConfig(_Input):
    """Send Campaign."""

    operation: Literal["send_campaign"] = Field(
        "send_campaign",
        title="Send Campaign",
        description="Send the Campaign and publish the Credentials. Only Campaigns which have a Detail, Design, EmailTemplate and Credentials can be sent. Also, an already sent Campaign cannot be sent again.\n\nDetails for the body of the request:\n\n- `id` id of the Campaign\n",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., min_length=1)


class SertifierScheduleCampaignConfig(_Input):
    """Schedule Campaign."""

    operation: Literal["schedule_campaign"] = Field(
        "schedule_campaign",
        title="Schedule Campaign",
        description="Schedule Campaign to be sent at a specific date and time. Only Campaigns which have a Detail, Design, EmailTemplate and Credentials can be scheduled. Also, an already sent Campaign cannot be scheduled.\n\n**The schedule time should be given in regards to UTC Time Zone!**\n\nDetails for the body of the request:\n\n- `id` id of the Campaign\n- `publishDate` the date to schedule the Campaign\n",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., min_length=1)
    publish_date: str = Field(
        ...,
        alias="publishDate",
        description="Schedule date in UTC (format: YYYY-MM-DD HH:mm)",
        min_length=1,
    )


class SertifierRecipientInput(_Input):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    attributes: list[SertifierAttributeValue] | None = Field(
        None, min_length=0, max_length=1000
    )


class SertifierAddRecipientsConfig(_Input):
    """Add Recipients."""

    operation: Literal["add_recipients"] = Field(
        "add_recipients",
        title="Add Recipients",
        description="Adds a member to your Recipients. This Recipient will be tied to the Credentials that are created with the same email address. However, if a Credential is created and there is no Recipient with a matching email address, the Recipient will be created automatically.\n",
        json_schema_extra={"ui:hidden": True},
    )
    recipients: list[SertifierRecipientInput] = Field(
        ..., min_length=1, max_length=1000
    )


class SertifierRecipientUpdateInput(_Input):
    id: str = Field(..., min_length=1)
    name: str | None = Field(None)
    email: str | None = Field(None)
    attributes: list[SertifierAttributeValue] | None = Field(
        None, min_length=0, max_length=1000
    )


class SertifierUpdateRecipientsConfig(_Input):
    """Update Recipients."""

    operation: Literal["update_recipients"] = Field(
        "update_recipients",
        title="Update Recipients",
        description="This endpoint can be used to update the `name`, `email` or `attributes` of your Recipients. The body allows to update multiple Recipients at once.\nAll credentials which are connected to this Recipient (which have the same email) will be updated as well if `updateExistingCredentials` is set to `true`.\n",
        json_schema_extra={"ui:hidden": True},
    )
    recipients: list[SertifierRecipientUpdateInput] = Field(
        ..., min_length=1, max_length=1000
    )
    update_existing_credentials: bool = Field(
        False,
        alias="updateExistingCredentials",
        description="If true, all credentials connected to this Recipient will be updated as well",
    )


class SertifierSearchRecipientsConfig(_Input):
    """Search Recipients."""

    operation: Literal["search_recipients"] = Field(
        "search_recipients",
        title="Search Recipients",
        description="Returns the organizations Recipients in paginated format. The pagination is handled with the `startIndex` and `length` keys in the request body.\nThere is one filtering option within the body:\n\n- `searchTerm` field is searched within the names and emails of the Recipients\n",
        json_schema_extra={"ui:hidden": True},
    )
    start_index: int = Field(
        0, alias="startIndex", description="Start index for pagination", ge=0
    )
    length: int = Field(50, description="Number of results to return", ge=1, le=1000)
    search_term: str | None = Field(
        None, alias="searchTerm", description="Search term to filter results"
    )


class SertifierGetCredentialConfig(_Input):
    """Get Credential."""

    operation: Literal["get_credential"] = Field(
        "get_credential",
        title="Get Credential",
        description="Returns the Credential of the given `id`. The `id` is passed to the parameters.",
        json_schema_extra={"ui:hidden": True},
    )
    credential_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Credential"
    )


class SertifierUpdateCredentialConfig(_Input):
    """Update Credential."""

    operation: Literal["update_credential"] = Field(
        "update_credential",
        title="Update Credential",
        description="Updates the Credential corresponding to the given `id`. The endpoint can be used to update the `name`, `issueDate`, `expireDate` and custom `attributes` of the Credential.",
        json_schema_extra={"ui:hidden": True},
    )
    credential_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Credential"
    )
    name: str | None = Field(None)
    issue_date: date | None = Field(None, alias="issueDate")
    expire_date: date | None = Field(None, alias="expireDate")
    attributes: list[SertifierAttributeValue] | None = Field(
        None, min_length=0, max_length=1000
    )


class SertifierDeleteCredentialConfig(_Input):
    """Delete Credential."""

    operation: Literal["delete_credential"] = Field(
        "delete_credential",
        title="Delete Credential",
        description="Deletes the credential corresponding to the given `id`. The `id` is passed in the parameters.",
        json_schema_extra={"ui:hidden": True},
    )
    credential_id: str = Field(
        ..., min_length=1, max_length=256, description="ID of the Credential"
    )


class SertifierSearchCredentialsConfig(_Input):
    """Search Credentials."""

    operation: Literal["search_credentials"] = Field(
        "search_credentials",
        title="Search Credentials",
        description="Returns the organizations Credentials in paginated format. The pagination is handled with the `startIndex` and `length` keys in the request body.\nThere are three filtering options within the body:\n\n- `searchTerm` field is searched within the name and emails of the Credentials\n- `campaignIds` field is a string array used for filtering the Credentials which belong to the given Campaigns\n- `recipientIds` field is a string array used for filtering the Credentials which belong to the given Recipients\n",
        json_schema_extra={"ui:hidden": True},
    )
    start_index: int = Field(0, alias="startIndex", ge=0)
    length: int = Field(50, ge=1, le=1000)
    status: int | None = Field(None)
    campaign_ids: list[str] | None = Field(
        None,
        alias="campaignIds",
        description="Filter by Campaign IDs",
        min_length=0,
        max_length=1000,
    )
    recipient_ids: list[str] | None = Field(
        None,
        alias="recipientIds",
        description="Filter by Recipient IDs",
        min_length=0,
        max_length=1000,
    )
    search_term: str | None = Field(None, alias="searchTerm")


class SertifierPublishCredentialsConfig(_Input):
    """Publish Credentials."""

    operation: Literal["publish_credentials"] = Field(
        "publish_credentials",
        title="Publish Credentials",
        description="Takes the `id` values of the credentials and publishes them. An email will be sent if the Credential has an email address.\n\nOne or more credentials can be published at once.\n",
        json_schema_extra={"ui:hidden": True},
    )
    ids: list[str] = Field(..., min_length=1, max_length=1000)


class SertifierGeneratePDFLinkConfig(_Input):
    """Generate PDF Link."""

    operation: Literal["generate_pdf_link"] = Field(
        "generate_pdf_link",
        title="Generate PDF Link",
        description="Generates the PDF Download Link and returns the link. The parameter can take in the `id` or the `certificateNO` of the Credential.",
        json_schema_extra={"ui:hidden": True},
    )
    credential_id_or_certificate_no: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="ID or certificateNO of the Credential",
    )


SertifierOperation = Annotated[
    Union[
        SertifierSearchDesignsConfig,
        SertifierGetDesignConfig,
        SertifierSearchEmailTemplatesConfig,
        SertifierGetEmailTemplateConfig,
        SertifierAddDetailConfig,
        SertifierUpdateDetailConfig,
        SertifierGetDetailConfig,
        SertifierSearchDetailsConfig,
        SertifierAddCampaignConfig,
        SertifierGetCampaignConfig,
        SertifierUpdateCampaignConfig,
        SertifierDeleteCampaignConfig,
        SertifierSearchCampaignsConfig,
        SertifierAddCredentialsToCampaignConfig,
        SertifierSendCampaignConfig,
        SertifierScheduleCampaignConfig,
        SertifierAddRecipientsConfig,
        SertifierUpdateRecipientsConfig,
        SertifierSearchRecipientsConfig,
        SertifierGetCredentialConfig,
        SertifierUpdateCredentialConfig,
        SertifierDeleteCredentialConfig,
        SertifierSearchCredentialsConfig,
        SertifierPublishCredentialsConfig,
        SertifierGeneratePDFLinkConfig,
    ],
    Field(discriminator="operation"),
]


class SertifierNodeConfig(NodeConfig[SertifierOperation, SertifierAPIKeyCredential]):
    pass


ROUTES = {
    "get_design": ("GET", "/design/{design_id}", [("design_id", "design_id")], False),
    "search_designs": ("POST", "/design/search", [], True),
    "add_detail": ("POST", "/detail", [], True),
    "update_detail": ("PUT", "/detail/{detail_id}", [("detail_id", "detail_id")], True),
    "get_detail": ("GET", "/detail/{detail_id}", [("detail_id", "detail_id")], False),
    "search_details": ("POST", "/detail/search", [], True),
    "get_email_template": (
        "GET",
        "/emailTemplate/{emailtemplate_id}",
        [("emailtemplate_id", "emailtemplate_id")],
        False,
    ),
    "search_email_templates": ("POST", "/emailTemplate/search", [], True),
    "add_campaign": ("POST", "/campaign", [], True),
    "get_campaign": (
        "GET",
        "/campaign/{campaign_id}",
        [("campaign_id", "campaign_id")],
        False,
    ),
    "update_campaign": (
        "PUT",
        "/campaign/{campaign_id}",
        [("campaign_id", "campaign_id")],
        True,
    ),
    "delete_campaign": (
        "DELETE",
        "/campaign/{campaign_id}",
        [("campaign_id", "campaign_id")],
        False,
    ),
    "search_campaigns": ("POST", "/campaign/search", [], True),
    "add_credentials_to_campaign": ("POST", "/campaign/addCredentials", [], True),
    "send_campaign": ("POST", "/campaign/send", [], True),
    "schedule_campaign": ("POST", "/campaign/schedule", [], True),
    "add_recipients": ("POST", "/recipient", [], True),
    "update_recipients": ("PUT", "/recipient", [], True),
    "search_recipients": ("POST", "/recipient/search", [], True),
    "get_credential": (
        "GET",
        "/credential/{credential_id}",
        [("credential_id", "credential_id")],
        False,
    ),
    "update_credential": (
        "PUT",
        "/credential/{credential_id}",
        [("credential_id", "credential_id")],
        True,
    ),
    "delete_credential": (
        "DELETE",
        "/credential/{credential_id}",
        [("credential_id", "credential_id")],
        False,
    ),
    "search_credentials": ("POST", "/credential/search", [], True),
    "publish_credentials": ("POST", "/credential/publish", [], True),
    "generate_pdf_link": (
        "GET",
        "/credential/generatePDFLink/{credential_id_OR_certificate_no}",
        [("credential_id_or_certificate_no", "credential_id_OR_certificate_no")],
        False,
    ),
}


# Only these provider request properties explicitly allow JSON null. Preserve
# a supplied null (for example to clear expiry) while omitting unset fields.
_NULLABLE = frozenset(
    {
        "expireDate",
        "expireDateNumber",
        "expireDateType",
        "earningCriteria",
        "badgeId",
        "designId",
        "emailfromAddress",
        "externalId",
    }
)


def _body(model, *, exclude=frozenset()):
    result = model.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude=exclude
    )
    for name, field in type(model).model_fields.items():
        if name in exclude:
            continue
        alias = field.alias or name
        value = getattr(model, name)
        if value is None and name in model.model_fields_set and alias in _NULLABLE:
            result[alias] = None
        elif isinstance(value, BaseModel):
            result[alias] = _body(value)
        elif isinstance(value, list):
            result[alias] = [
                _body(item) if isinstance(item, BaseModel) else item for item in value
            ]
    return result


class SertifierNode(WorkflowNode):
    integration_type = "automation-sertifier"
    connection_evidence = ConnectionEvidence(
        noun="campaigns", operation="search_campaigns", label_keys=("title", "id")
    )

    @classmethod
    def get_config_model(cls):
        return SertifierNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Sertifier API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, template, path_fields, has_body = ROUTES[op.operation]
        path = template
        for field, parameter in path_fields:
            identifier = getattr(op, field)
            if identifier in {".", ".."} or any(ord(c) < 32 for c in identifier):
                raise ValueError("Use a valid Sertifier resource ID")
            path = path.replace("{" + parameter + "}", quote(identifier, safe=""))
        body = (
            _body(op, exclude={"operation", *(field for field, _ in path_fields)})
            if has_body
            else None
        )
        headers = {
            "secretKey": key,
            "api-version": API_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with guarded_async_client(
                follow_redirects=False, trust_env=False, timeout=30.0
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    headers=headers,
                    **({"json": body} if has_body else {}),
                )
        except httpx.RequestError:
            raise ValueError(
                "Sertifier request failed; a write may have completed. Check Sertifier before retrying."
            ) from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Sertifier returned a non-JSON response") from None

        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]")
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {
                    k.replace(key, "[redacted]"): redact(v) for k, v in value.items()
                }
            return value

        if not 200 <= response.status_code < 300:
            message = payload.get("message") if isinstance(payload, dict) else None
            raise ValueError(
                redact(str(message or f"Sertifier HTTP {response.status_code}"))
            )
        if (
            not isinstance(payload, dict)
            or type(payload.get("hasError")) is not bool
            or "data" not in payload
        ):
            raise ValueError("Sertifier returned an unrecognized response envelope")
        if payload["hasError"]:
            message = (
                payload.get("message")
                or payload.get("validationErrors")
                or "Sertifier rejected the request"
            )
            raise ValueError(redact(str(message)))
        output = redact(
            {
                "status": "success",
                "success": True,
                "operation": op.operation,
                "data": payload["data"],
                "message": payload.get("message"),
            }
        )
        if op.operation.startswith("search_"):
            data = payload["data"]
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("Sertifier returned an unrecognized search page")
            output.update(
                start_index=op.start_index, length=op.length, total=data.get("total")
            )
            # Never claim all pages were fetched or infer delivery from a write acknowledgment.
        await self.emit(output)
        return output
