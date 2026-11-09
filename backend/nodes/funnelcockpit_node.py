"""FunnelCockpit public API: contacts, funnels, members, forms and webinars.

Each operation performs one request. List operations return one provider page;
use the documented page/limit inputs to retrieve subsequent pages.
Contract: https://api.funnelcockpit.com/openapi.json (1.0.0).
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client


class FunnelCockpitAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="FunnelCockpit API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.funnelcockpit.com/",
            "x-credential-instructions": "Paste your FunnelCockpit private API key from your account's API settings. NoClick sends it directly in the Authorization header, without a Bearer prefix. The connection check reads your account name and email from /me.",
        })
    credential_type: Literal["funnelcockpit_api_key"] = Field("funnelcockpit_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Private API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def private_key(cls, value):
        value = clean_secret(value, field_name="Private API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the private API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_path_id(cls, value, info):
        if info.field_name in {"funnelId", "membersAreaId", "crmId", "formId", "surveyId", "webinarId"} and value is not None:
            if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
                raise ValueError("Use a single FunnelCockpit resource ID")
        return value


class FunnelCockpitGetCurrentUserConfig(_Input):
    """Verify the current API user. """
    operation: Literal["get_current_user"] = Field("get_current_user", title='Get Current User', json_schema_extra={"ui:hidden": True})

class FunnelCockpitListFunnelsConfig(_Input):
    """List funnels. """
    operation: Literal["list_funnels"] = Field("list_funnels", title='List Funnels', json_schema_extra={"ui:hidden": True})

class FunnelCockpitListFunnelPagesConfig(_Input):
    """List funnel pages. """
    operation: Literal["list_funnel_pages"] = Field("list_funnel_pages", title='List Funnel Pages', json_schema_extra={"ui:hidden": True})
    funnelId: str | None = Field(None, min_length=1, max_length=10000, description='Optional funnel ID filter.', title='Funnel ID')

class FunnelCockpitListMembersAreasConfig(_Input):
    """List members areas. """
    operation: Literal["list_members_areas"] = Field("list_members_areas", title='List Members Areas', json_schema_extra={"ui:hidden": True})
    funnelId: str | None = Field(None, min_length=1, max_length=10000, description='Optional funnel ID filter.', title='Funnel ID')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitCreateOrUpdateMembersAreaMemberConfig(_Input):
    """Create or update a members area member without a password. New members receive a password setup email. Existing active members keep their password, sessions, two-factor settings and current access groups. Inactive, blocked and administrator accounts cannot be updated. No login credentials are returned. Enrollment delivery is queued; check enrollmentFailed and enrollmentQueued in the response."""
    operation: Literal["create_or_update_members_area_member"] = Field("create_or_update_members_area_member", title='Create Or Update Members Area Member', json_schema_extra={"ui:hidden": True})
    membersAreaId: str = Field(..., min_length=1, max_length=10000, description='Members area ID.', title='Members Area ID')
    email: str = Field(..., min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title='Email')
    firstName: str = Field(..., min_length=1, max_length=200, title='First Name')
    lastName: str | None = Field(None, min_length=1, max_length=200, title='Last Name')
    groupId: str = Field(..., min_length=1, max_length=200, title='Group ID')

class FunnelCockpitListMembersAreaMembersConfig(_Input):
    """List members area members. """
    operation: Literal["list_members_area_members"] = Field("list_members_area_members", title='List Members Area Members', json_schema_extra={"ui:hidden": True})
    membersAreaId: str = Field(..., min_length=1, max_length=10000, description='Members area ID.', title='Members Area ID')
    email: str | None = Field(None, min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", description='Optional email filter.', title='Email')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListEmailContactsConfig(_Input):
    """List email contacts. Returns email contacts for the current API user."""
    operation: Literal["list_email_contacts"] = Field("list_email_contacts", title='List Email Contacts', json_schema_extra={"ui:hidden": True})
    tagId: str | None = Field(None, min_length=1, max_length=10000, title='Tag ID')
    email: str | None = Field(None, min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title='Email')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListEmailFieldsConfig(_Input):
    """List email contact fields. """
    operation: Literal["list_email_fields"] = Field("list_email_fields", title='List Email Fields', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListEmailTagsConfig(_Input):
    """List email tags. """
    operation: Literal["list_email_tags"] = Field("list_email_tags", title='List Email Tags', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitCreateOrUpdateEmailContactConfig(_Input):
    """Create or update an email contact. Creates or updates an email contact and supports legacy opt-in form submissions."""
    operation: Literal["create_or_update_email_contact"] = Field("create_or_update_email_contact", title='Create Or Update Email Contact', json_schema_extra={"ui:hidden": True})
    provider: Literal['funnelcockpit'] = Field('funnelcockpit', description='Uses FunnelCockpit email contacts.', title='Provider')
    email: str = Field(..., min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title='Email')
    firstName: str | None = Field(None, min_length=1, max_length=10000, title='First Name')
    lastName: str | None = Field(None, min_length=1, max_length=10000, title='Last Name')
    tagId: str | None = Field(None, min_length=1, max_length=10000, title='Tag ID')
    funnelId: str | None = Field(None, min_length=1, max_length=10000, title='Funnel ID')
    company: str | None = Field(None, min_length=1, max_length=10000, title='Company')
    phone: str | None = Field(None, min_length=1, max_length=10000, title='Phone')
    street: str | None = Field(None, min_length=1, max_length=10000, title='Street')
    houseNumber: str | None = Field(None, min_length=1, max_length=10000, title='House Number')
    zip: str | None = Field(None, min_length=1, max_length=10000, title='Zip')
    city: str | None = Field(None, min_length=1, max_length=10000, title='City')
    country: str | None = Field(None, min_length=1, max_length=10000, title='Country')
    utmCampaign: str | None = Field(None, min_length=1, max_length=10000, title='UTM Campaign')
    utmMedium: str | None = Field(None, min_length=1, max_length=10000, title='UTM Medium')
    utmSource: str | None = Field(None, min_length=1, max_length=10000, title='UTM Source')
    utmTerm: str | None = Field(None, min_length=1, max_length=10000, title='UTM Term')
    utmContent: str | None = Field(None, min_length=1, max_length=10000, title='UTM Content')
    thanksPageUrl: HttpUrl | None = Field(None, title='Thanks Page URL')
    confirmPageUrl: HttpUrl | None = Field(None, title='Confirm Page URL')

class FunnelCockpitSubscribeEmailContactConfig(_Input):
    """Subscribe an email contact. Subscribes an email address to a FunnelCockpit email tag. This endpoint is also used by public opt-in flows."""
    operation: Literal["subscribe_email_contact"] = Field("subscribe_email_contact", title='Subscribe Email Contact', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title='Email')
    firstName: str | None = Field(None, min_length=1, max_length=10000, title='First Name')
    lastName: str | None = Field(None, min_length=1, max_length=10000, title='Last Name')
    tagId: str = Field(..., min_length=1, max_length=10000, title='Tag ID')
    company: str | None = Field(None, min_length=1, max_length=10000, title='Company')
    phone: str | None = Field(None, min_length=1, max_length=10000, title='Phone')
    street: str | None = Field(None, min_length=1, max_length=10000, title='Street')
    houseNumber: str | None = Field(None, min_length=1, max_length=10000, title='House Number')
    zip: str | None = Field(None, min_length=1, max_length=10000, title='Zip')
    city: str | None = Field(None, min_length=1, max_length=10000, title='City')
    country: str | None = Field(None, min_length=1, max_length=10000, title='Country')
    utmCampaign: str | None = Field(None, min_length=1, max_length=10000, title='UTM Campaign')
    utmMedium: str | None = Field(None, min_length=1, max_length=10000, title='UTM Medium')
    utmSource: str | None = Field(None, min_length=1, max_length=10000, title='UTM Source')
    utmTerm: str | None = Field(None, min_length=1, max_length=10000, title='UTM Term')
    utmContent: str | None = Field(None, min_length=1, max_length=10000, title='UTM Content')
    thanksPageUrl: HttpUrl | None = Field(None, title='Thanks Page URL')
    confirmPageUrl: HttpUrl | None = Field(None, title='Confirm Page URL')
    digistore24AffiliateId: str | None = Field(None, min_length=1, max_length=10000, title='Digistore24 Affiliate ID')
    recaptchaResponse: str | None = Field(None, min_length=1, max_length=10000, title='Recaptcha Response')

class FunnelCockpitAssignEmailTagConfig(_Input):
    """Assign an email tag to a contact. """
    operation: Literal["assign_email_tag"] = Field("assign_email_tag", title='Assign Email Tag', json_schema_extra={"ui:hidden": True})
    contactId: str = Field(..., min_length=1, max_length=10000, title='Contact ID')
    tagId: str = Field(..., min_length=1, max_length=10000, title='Tag ID')

class FunnelCockpitListCrmsConfig(_Input):
    """List CRMs. """
    operation: Literal["list_crms"] = Field("list_crms", title='List CRMs', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListCrmContactsConfig(_Input):
    """List CRM contacts. Returns CRM contacts for a CRM."""
    operation: Literal["list_crm_contacts"] = Field("list_crm_contacts", title='List CRM Contacts', json_schema_extra={"ui:hidden": True})
    crmId: str = Field(..., min_length=1, max_length=10000, description='CRM ID.', title='CRM ID')
    crmTagId: str | None = Field(None, min_length=1, max_length=10000, description='Optional CRM tag/lead group filter.', title='CRM Tag ID')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitCreateOrUpdateCrmContactConfig(_Input):
    """Create or update a CRM contact. Creates or updates a CRM contact. Lead group assignment requires the CRM owner’s valid private API key in the Authorization header. Public submissions ignore lead group assignments. Existing assignments are preserved."""
    operation: Literal["create_or_update_crm_contact"] = Field("create_or_update_crm_contact", title='Create Or Update CRM Contact', json_schema_extra={"ui:hidden": True})
    crmId: str = Field(..., min_length=1, max_length=10000, description='CRM ID.', title='CRM ID')
    crmTagIds: list[Annotated[str, Field(min_length=1)]] | None = Field(None, max_length=100, title='CRM Tag Ids')
    email: str = Field(..., min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title='Email')
    firstName: str | None = Field(None, min_length=1, max_length=10000, title='First Name')
    lastName: str | None = Field(None, min_length=1, max_length=10000, title='Last Name')
    avatarUrl: HttpUrl | None = Field(None, title='Avatar URL')
    phone: str | None = Field(None, min_length=1, max_length=10000, title='Phone')
    street: str | None = Field(None, min_length=1, max_length=10000, title='Street')
    houseNumber: str | None = Field(None, min_length=1, max_length=10000, title='House Number')
    city: str | None = Field(None, min_length=1, max_length=10000, title='City')
    country: str | None = Field(None, min_length=1, max_length=10000, title='Country')
    zip: str | None = Field(None, min_length=1, max_length=10000, title='Zip')
    company: str | None = Field(None, min_length=1, max_length=10000, title='Company')
    website: str | None = Field(None, min_length=1, max_length=10000, title='Website')
    notes: str | None = Field(None, min_length=1, max_length=10000, title='Notes')
    utmSource: str | None = Field(None, min_length=1, max_length=10000, title='UTM Source')
    utmMedium: str | None = Field(None, min_length=1, max_length=10000, title='UTM Medium')
    utmCampaign: str | None = Field(None, min_length=1, max_length=10000, title='UTM Campaign')
    utmTerm: str | None = Field(None, min_length=1, max_length=10000, title='UTM Term')
    utmContent: str | None = Field(None, min_length=1, max_length=10000, title='UTM Content')

class FunnelCockpitListCrmTagsConfig(_Input):
    """List CRM tags. """
    operation: Literal["list_crm_tags"] = Field("list_crm_tags", title='List CRM Tags', json_schema_extra={"ui:hidden": True})
    crmId: str = Field(..., min_length=1, max_length=10000, description='CRM ID.', title='CRM ID')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListFormsConfig(_Input):
    """List forms. """
    operation: Literal["list_forms"] = Field("list_forms", title='List Forms', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListFormSubmissionsConfig(_Input):
    """List form submissions. Returns form submissions for a form."""
    operation: Literal["list_form_submissions"] = Field("list_form_submissions", title='List Form Submissions', json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1, max_length=10000, description='Form ID.', title='Form ID')
    pageSize: int | None = Field(None, strict=True, ge=1, le=25, title='Page Size')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListSurveysConfig(_Input):
    """List surveys. """
    operation: Literal["list_surveys"] = Field("list_surveys", title='List Surveys', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListSurveyResultsConfig(_Input):
    """List survey results. Returns survey results for a survey."""
    operation: Literal["list_survey_results"] = Field("list_survey_results", title='List Survey Results', json_schema_extra={"ui:hidden": True})
    surveyId: str = Field(..., min_length=1, max_length=10000, description='Survey ID.', title='Survey ID')
    pageSize: int | None = Field(None, strict=True, ge=1, le=100, title='Page Size')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListWebinarsConfig(_Input):
    """List webinars. Returns webinars for a valid private API key. For legacy compatibility, missing or invalid API keys return HTTP 200 with an empty body."""
    operation: Literal["list_webinars"] = Field("list_webinars", title='List Webinars', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListWebinarViewersConfig(_Input):
    """List webinar viewers. Returns webinar viewers for a webinar."""
    operation: Literal["list_webinar_viewers"] = Field("list_webinar_viewers", title='List Webinar Viewers', json_schema_extra={"ui:hidden": True})
    webinarId: str = Field(..., min_length=1, max_length=10000, description='Webinar ID.', title='Webinar ID')
    limit: int | None = Field(None, strict=True, ge=1, description='Maximum number of records to return.', title='Limit')
    page: int | None = Field(None, strict=True, ge=0, description='Zero-based page number.', title='Page')

class FunnelCockpitListWebinarDatesConfig(_Input):
    """List upcoming webinar dates. Returns upcoming webinar dates."""
    operation: Literal["list_webinar_dates"] = Field("list_webinar_dates", title='List Webinar Dates', json_schema_extra={"ui:hidden": True})
    webinarId: str = Field(..., min_length=1, max_length=10000, description='Webinar ID.', title='Webinar ID')
    count: int = Field(3, strict=True, ge=1, title='Count')
    nextFullHourOneOnly: bool | None = Field(None, strict=True, title='Next Full Hour One Only')

class FunnelCockpitCreateWebinarViewerConfig(_Input):
    """Create a webinar viewer. Creates a webinar viewer."""
    operation: Literal["create_webinar_viewer"] = Field("create_webinar_viewer", title='Create Webinar Viewer', json_schema_extra={"ui:hidden": True})
    webinarId: str = Field(..., min_length=1, max_length=10000, title='Webinar ID')
    email: str = Field(..., min_length=1, max_length=10000, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title='Email')
    firstName: str | None = Field(None, min_length=1, max_length=10000, title='First Name')
    lastName: str | None = Field(None, min_length=1, max_length=10000, title='Last Name')
    webinarStartDate: AwareDatetime = Field(..., title='Webinar Start Date')
    emailContactId: str | None = Field(None, min_length=1, max_length=10000, title='Email Contact ID')


Operation = Annotated[Union[
    FunnelCockpitGetCurrentUserConfig,
    FunnelCockpitListFunnelsConfig,
    FunnelCockpitListFunnelPagesConfig,
    FunnelCockpitListMembersAreasConfig,
    FunnelCockpitCreateOrUpdateMembersAreaMemberConfig,
    FunnelCockpitListMembersAreaMembersConfig,
    FunnelCockpitListEmailContactsConfig,
    FunnelCockpitListEmailFieldsConfig,
    FunnelCockpitListEmailTagsConfig,
    FunnelCockpitCreateOrUpdateEmailContactConfig,
    FunnelCockpitSubscribeEmailContactConfig,
    FunnelCockpitAssignEmailTagConfig,
    FunnelCockpitListCrmsConfig,
    FunnelCockpitListCrmContactsConfig,
    FunnelCockpitCreateOrUpdateCrmContactConfig,
    FunnelCockpitListCrmTagsConfig,
    FunnelCockpitListFormsConfig,
    FunnelCockpitListFormSubmissionsConfig,
    FunnelCockpitListSurveysConfig,
    FunnelCockpitListSurveyResultsConfig,
    FunnelCockpitListWebinarsConfig,
    FunnelCockpitListWebinarViewersConfig,
    FunnelCockpitListWebinarDatesConfig,
    FunnelCockpitCreateWebinarViewerConfig,
], Field(discriminator="operation")]


class FunnelCockpitConfig(NodeConfig[Operation, FunnelCockpitAPIKeyCredential]):
    pass


# Fixed routes and explicit parameter locations; arbitrary URLs and bodies are not accepted.
ROUTES = {'get_current_user': ('GET', '/me', [], [], []),
 'list_funnels': ('GET', '/funnels', [], [], []),
 'list_funnel_pages': ('GET', '/funnel-pages', [], ['funnelId'], []),
 'list_members_areas': ('GET', '/members-areas', [], ['funnelId', 'limit', 'page'], []),
 'create_or_update_members_area_member': ('POST',
                                          '/members-area/{membersAreaId}/members',
                                          ['membersAreaId'],
                                          [],
                                          ['email', 'firstName', 'lastName', 'groupId']),
 'list_members_area_members': ('GET',
                               '/members-area/{membersAreaId}/members',
                               ['membersAreaId'],
                               ['email', 'limit', 'page'],
                               []),
 'list_email_contacts': ('GET', '/email/contacts', [], ['tagId', 'email', 'limit', 'page'], []),
 'list_email_fields': ('GET', '/email/fields', [], ['limit', 'page'], []),
 'list_email_tags': ('GET', '/email/tags', [], ['limit', 'page'], []),
 'create_or_update_email_contact': ('POST',
                                    '/add-email-subscriber',
                                    [],
                                    [],
                                    ['provider',
                                     'email',
                                     'firstName',
                                     'lastName',
                                     'tagId',
                                     'funnelId',
                                     'company',
                                     'phone',
                                     'street',
                                     'houseNumber',
                                     'zip',
                                     'city',
                                     'country',
                                     'utmCampaign',
                                     'utmMedium',
                                     'utmSource',
                                     'utmTerm',
                                     'utmContent',
                                     'thanksPageUrl',
                                     'confirmPageUrl']),
 'subscribe_email_contact': ('POST',
                             '/email/subscribe',
                             [],
                             [],
                             ['email',
                              'firstName',
                              'lastName',
                              'tagId',
                              'company',
                              'phone',
                              'street',
                              'houseNumber',
                              'zip',
                              'city',
                              'country',
                              'utmCampaign',
                              'utmMedium',
                              'utmSource',
                              'utmTerm',
                              'utmContent',
                              'thanksPageUrl',
                              'confirmPageUrl',
                              'digistore24AffiliateId',
                              'recaptchaResponse']),
 'assign_email_tag': ('POST', '/email/tag', [], [], ['contactId', 'tagId']),
 'list_crms': ('GET', '/crms', [], ['limit', 'page'], []),
 'list_crm_contacts': ('GET', '/crm/{crmId}/contacts', ['crmId'], ['crmTagId', 'limit', 'page'], []),
 'create_or_update_crm_contact': ('POST',
                                  '/crm/{crmId}/contact',
                                  ['crmId'],
                                  [],
                                  ['crmTagIds',
                                   'email',
                                   'firstName',
                                   'lastName',
                                   'avatarUrl',
                                   'phone',
                                   'street',
                                   'houseNumber',
                                   'city',
                                   'country',
                                   'zip',
                                   'company',
                                   'website',
                                   'notes',
                                   'utmSource',
                                   'utmMedium',
                                   'utmCampaign',
                                   'utmTerm',
                                   'utmContent']),
 'list_crm_tags': ('GET', '/crm/{crmId}/tags', ['crmId'], ['limit', 'page'], []),
 'list_forms': ('GET', '/forms', [], ['limit', 'page'], []),
 'list_form_submissions': ('GET',
                           '/form/{formId}/submissions',
                           ['formId'],
                           ['pageSize', 'limit', 'page'],
                           []),
 'list_surveys': ('GET', '/surveys', [], ['limit', 'page'], []),
 'list_survey_results': ('GET',
                         '/survey/{surveyId}/results',
                         ['surveyId'],
                         ['pageSize', 'limit', 'page'],
                         []),
 'list_webinars': ('GET', '/webinars', [], ['limit', 'page'], []),
 'list_webinar_viewers': ('GET', '/webinar/{webinarId}/viewers', ['webinarId'], ['limit', 'page'], []),
 'list_webinar_dates': ('GET',
                        '/webinar/{webinarId}/dates',
                        ['webinarId'],
                        ['count', 'nextFullHourOneOnly'],
                        []),
 'create_webinar_viewer': ('POST',
                           '/webinar/add-viewer',
                           [],
                           [],
                           ['webinarId',
                            'email',
                            'firstName',
                            'lastName',
                            'webinarStartDate',
                            'emailContactId'])}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value


class FunnelCockpitNode(WorkflowNode):
    integration_type = "automation-funnelcockpit"
    connection_evidence = ConnectionEvidence(noun="FunnelCockpit account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return FunnelCockpitConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a FunnelCockpit private API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route, path_fields, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for field in path_fields:
            route = route.replace("{" + field + "}", quote(values[field], safe=""))
        params = {field: values[field] for field in query_fields if field in values}
        body = {field: values[field] for field in body_fields if field in values}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, "https://api.funnelcockpit.com" + route,
                    headers={"Authorization": key, "Accept": "application/json"}, params=params,
                    **({"json": body} if method == "POST" else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 5_000_000:
                            raise ValueError("FunnelCockpit response exceeds the supported size")
                    status = response.status_code
                    if status != 200:
                        message = "FunnelCockpit request rejected"
                        try:
                            error = json.loads(raw)
                            if isinstance(error, dict):
                                detail = error.get("message") or error.get("error")
                                if isinstance(detail, str):
                                    message = detail[:1000].replace(key, "[redacted]")
                        except (ValueError, UnicodeError):
                            pass
                        output = {"status": "error", "error": message, "status_code": status}
                    elif config.operation == "assign_email_tag" and not raw.strip():
                        output = {"status": "success", "data": None}
                    else:
                        media = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        if media != "application/json":
                            raise ValueError("Expected a JSON response from FunnelCockpit")
                        payload = json.loads(raw)
                        if not isinstance(payload, (dict, list)):
                            raise ValueError("Unexpected FunnelCockpit response shape")
                        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors") or payload.get("success") is False):
                            raise ValueError("FunnelCockpit reported an unsuccessful operation")
                        if config.operation.startswith("list_") and not isinstance(payload, list):
                            raise ValueError("Expected a FunnelCockpit list response")
                        if config.operation == "get_current_user":
                            if not isinstance(payload, dict) or not payload.get("name") or not payload.get("email"):
                                raise ValueError("FunnelCockpit did not return an account identity")
                        output = {"status": "success", "data": payload}
        except (httpx.HTTPError, SSRFError):
            raise ValueError("FunnelCockpit request did not complete; inspect the provider before retrying a write") from None
        # The API key is never returned, including if a provider echoes it.
        output = _redact(output, key)
        await self.emit(output)
        return output
