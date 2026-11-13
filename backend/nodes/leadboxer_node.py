"""Leadboxer operations pinned to the provider's published v0.0.1 API contract.

One request per operation; list responses preserve provider metadata and tokens.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.leadboxer.com"


class LeadboxerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Leadboxer API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.leadboxer.com/",
            "x-credential-instructions": "Paste your Leadboxer API key and the email address of your Leadboxer user. An API license is required; contact Leadboxer for API access. NoClick sends the key in the x-api-key header to api.leadboxer.com and reads your datasets to check the connection.",
        })
    credential_type: Literal["leadboxer_api_key"] = Field("leadboxer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    email: str = Field(..., title="Account email", min_length=3, max_length=254, description="Email address of your Leadboxer user; used by endpoints that require a user email.")

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Leadboxer API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("API key must not contain whitespace")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter your Leadboxer account email")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_id(cls, value, info):
        if info.field_name == "leadId" and (value in {".", ".."} or any(c in value for c in "/\\?#")):
            raise ValueError("Use a single Leadboxer lead ID")
        return value


class ListDatasetsConfig(_Operation):
    """Get User Datasets."""
    operation: Literal["list_datasets"] = Field("list_datasets", title='Operation', json_schema_extra={"ui:hidden": True})


class ListLeadsConfig(_Operation):
    """Retrieve Leads."""
    operation: Literal["list_leads"] = Field("list_leads", title='Operation', json_schema_extra={"ui:hidden": True})
    site: str = Field(..., title='Site', min_length=1, max_length=8192, description='The Dataset ID')
    search: str = Field('*', title='Search', max_length=8192, description="Keyword or phrase to search across all searchable fields. Search is case-insensitive for text fields. Defaults to '*' to match all results.")
    limit: int = Field(50, title='Limit', ge=1, le=100, description='No of rows to return in response.')
    locale: str = Field('en_US', title='Locale', max_length=8192, description="Locale for formatting the 'prettyLastEvent' field in response. Determines the language and regional formatting (e.g., dates, text) returned by the API.")
    nextToken: str | None = Field(None, title='Next token', min_length=1, max_length=8192, description='Token returned after each request, used to fetch the next page of results. Each token is valid for 10 minutes.')
    criteriaTextFilter: str | None = Field(None, title='Criteria text filter', min_length=1, max_length=8192, description='Text-based filter expression used to filter result fields.Format: field|operator|value. Multiple filters are comma-separated.')
    criteriaNumberFilter: str | None = Field(None, title='Criteria number filter', min_length=1, max_length=8192, description='Numeric filter expression used to filter results based on numeric fields. Format: field|operator|value. Multiple filters are comma-separated. Supported numeric operators include greaterthan, lessthan, is, isnot, between, and notbetween. The between and notbetween operators use the format min-max.')
    criteriaTimeFilter: str = Field(..., title='Criteria time filter', min_length=1, max_length=8192, description='Time-based filter expression used to filter results by time field. Format: field|operator|value.\n\nAllowed fields (same as `timeField` parameter):\n- eventEsTimestamp : Last Seen\n- first_session_unix_timestamp : First Seen\n\nSupported operators:\n- exactly   → integer value (0 = Today, 1 = Yesterday)\n- lessthan  → integer value (e.g. 6 = last 7 days)\n- between   → date range in format dd/MM/yyyy-dd/MM/yyyy\n\nLocale settings are taken into account while interpreting dates and returning results.')
    criteriaFieldFilter: str | None = Field(None, title='Criteria field filter', min_length=1, max_length=8192, description='Field-based filter used to include leads based on field presence.\n\nFormat:\noperator|field1;field2\n\nAllowed operator:\n- hasanyvalue\n\nAllowed fields:\n- firstName\n- lastName\n- email\n\nMultiple fields can be provided using semicolons.')
    criteriaExitLinkFilter: str | None = Field(None, title='Criteria exit link filter', min_length=1, max_length=8192, description='Exit link filter used to include or exclude leads based on exit link values.\n\nFormat:\nfield|operator|value\n\nSupported operators:\n- contains\n- is\n- isnot\n- doesnotcontain\n\nMultiple values can be provided using semicolons.')
    criteriaLeadscoreFilter: int | None = Field(None, title='Criteria leadscore filter', ge=0, le=100, description='Minimum lead score threshold (optional). Only records with lead scores greater than the provided number (0–100) are returned.')
    criteriaDisplayFilter: str | None = Field(None, title='Criteria display filter', min_length=1, max_length=8192, description="Display filter used to control which types of leads are returned.\n\nSupported values:\n- company\n- person\n- unidentified\n\nSelecting 'unidentified' returns leads that could not be identified as a company or a person.\n\nMultiple values can be provided using semicolons.")
    timeField: Literal['eventEsTimestamp', 'first_session_unix_timestamp'] = Field('eventEsTimestamp', title='Time field', description='Time field used for filtering.\n\nAllowed values:\n- eventEsTimestamp : Last Seen\n- first_session_unix_timestamp : First Seen')
    usePresetExclusionList: Literal['use_id', 'last_most_likely_company', 'organizationName', 'organizationDomain'] | None = Field(None, title='Use preset exclusion list', description='Use a preset exclusion list of criteria to exclude from result.')
    userId: int | None = Field(None, title='User ID')
    timeZone: str = Field('Europe/Amsterdam', title='Time zone', max_length=8192, description='Time zone used when parsing timestamps and evaluating time-based filters. \nIf not provided, the default time zone is Europe/Amsterdam.')
    sortBy: str | None = Field(None, title='Sort by', min_length=1, max_length=8192, description='Sort results by a specific field and direction.\n\nFormat:\nfield|direction\n\nAllowed fields:\n- lastEvent\n- _score\n\nAllowed directions:\n- asc\n- desc')


class GetLeadConfig(_Operation):
    """Retrieve Lead Details."""
    operation: Literal["get_lead"] = Field("get_lead", title='Operation', json_schema_extra={"ui:hidden": True})
    leadId: str = Field(..., title='Lead ID', min_length=1, max_length=8192, description='Unique identifier of the lead whose information is being requested.')
    site: str = Field(..., title='Site', min_length=1, max_length=8192, description='The Dataset ID from which the lead information should be retrieved.')


class ListSessionsConfig(_Operation):
    """Retrieve Lead Sessions."""
    operation: Literal["list_sessions"] = Field("list_sessions", title='Operation', json_schema_extra={"ui:hidden": True})
    leadId: str = Field(..., title='Lead ID', min_length=1, max_length=8192, description='Display data for the given leadId. LeadId is a unique identifier of each lead.')
    limit: int = Field(..., title='Limit', ge=1, le=10000, description='The minimum number of records to be displayed in the output. Range : 1 - 10000')
    site: str = Field(..., title='Site', min_length=1, max_length=8192, description='Dataset ID (site) for which sessions are retrieved')
    userId: int | None = Field(None, title='User ID', description='UserId associated with email')
    segmentId: int | None = Field(None, title='Segment ID', ge=1, description='Filter results using a segment filters')
    minTime: int | None = Field(None, title='Min time', description='Filter sessions by minimum session duration.')
    nextToken: str | None = Field(None, title='Next token', min_length=1, max_length=8192, description='Token returned after each request, used to fetch the next page of results. Each token is valid for 10 minutes.')


class ListEventsConfig(_Operation):
    """Retrieve Lead Events."""
    operation: Literal["list_events"] = Field("list_events", title='Operation', json_schema_extra={"ui:hidden": True})
    sessionId: str = Field(..., title='Session ID', min_length=1, max_length=8192, description='Display data for the given sessionId. SessionId is a unique identifier of each session.')
    limit: int = Field(..., title='Limit', ge=1, le=100, description='The minimum number of records to be displayed in the output. Range : 1 - 100')
    site: str = Field(..., title='Site', min_length=1, max_length=8192, description='Dataset ID (site) for which events are retrieved')
    userId: int | None = Field(None, title='User ID', description='UserId associated with email')
    segmentId: int | None = Field(None, title='Segment ID', ge=1)


class LookupIpConfig(_Operation):
    """IP Address Lookup."""
    operation: Literal["lookup_ip"] = Field("lookup_ip", title='Operation', json_schema_extra={"ui:hidden": True})
    ip: str = Field(..., title='Ip', min_length=1, max_length=8192, description='IP address to lookup (IPv4|IPv6 format)')
    datasetId: str | None = Field(None, title='Dataset ID', min_length=1, max_length=8192, description='The dataset ID to associate with the operation’s credit. If not specified, a dataset linked to the account will be selected.')


class LookupDomainConfig(_Operation):
    """Domain Lookup."""
    operation: Literal["lookup_domain"] = Field("lookup_domain", title='Operation', json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., title='Domain', min_length=1, max_length=8192, description='Domain name to lookup (e.g., leadboxer.com)')
    datasetId: str | None = Field(None, title='Dataset ID', min_length=1, max_length=8192, description='The dataset ID to associate with the operation’s credit. If not specified, a dataset linked to the account will be selected.')


class LookupEmailConfig(_Operation):
    """Email Lookup (GET)."""
    operation: Literal["lookup_email"] = Field("lookup_email", title='Operation', json_schema_extra={"ui:hidden": True})
    firstName: str | None = Field(None, title='First name', min_length=1, max_length=8192, description='First name of the contact (optional hint)')
    lastName: str | None = Field(None, title='Last name', min_length=1, max_length=8192, description='Last name of the contact (optional hint)')
    companyName: str | None = Field(None, title='Company name', min_length=1, max_length=8192, description='Name of the company the contact works for (optional hint)')
    companyDomain: str | None = Field(None, title='Company domain', min_length=1, max_length=8192, description='Domain of the company the contact works for (optional hint)')
    datasetId: str | None = Field(None, title='Dataset ID', min_length=1, max_length=8192, description='The dataset ID to associate with the operation’s credit. If not specified, a dataset linked to the account will be selected.')


class ListSegmentsConfig(_Operation):
    """Retrieve Segments for a Given Site."""
    operation: Literal["list_segments"] = Field("list_segments", title='Operation', json_schema_extra={"ui:hidden": True})
    accountId: str = Field(..., title='Account ID', min_length=1, max_length=8192, description='The Leadboxer account ID associated with the segments.')
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192, description='The dataset for which to fetch segments.')


class CreateSegmentConfig(_Operation):
    """Create a New Segment."""
    operation: Literal["create_segment"] = Field("create_segment", title='Operation', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', min_length=1, max_length=8192, description='Segment name.')
    accountId: str = Field(..., title='Account ID', min_length=1, max_length=8192, description='Leadboxer accountId.')
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192, description='The dataset for which to create segment.')
    type: Literal['USER', 'ACCOUNT'] = Field(..., title='Type', description='Defines the visibility of the segment.   Possible values:   USER  – Visible only to the current user.  ACCOUNT  – Shared with all users of the account.')
    textFilter: str | None = Field(None, title='Text filter', min_length=1, max_length=8192, description='Text-based filter expression used to filter result fields.Format: field|operator|value. Multiple filters are comma-separated.')
    numberFilter: str | None = Field(None, title='Number filter', min_length=1, max_length=8192, description='Numeric filter expression used to filter results based on numeric fields. Format: field|operator|value. Multiple filters are comma-separated. Supported numeric operators include greaterthan, lessthan, is, isnot, between, and notbetween. The between and notbetween operators use the format min-max.')
    timeFilter: str | None = Field(None, title='Time filter', min_length=1, max_length=8192, description='Time-based filter expression used to filter results by time field. Format: field|operator|value.\n\nAllowed fields (same as `timeField` parameter):\n- eventEsTimestamp : Last Seen\n- first_session_unix_timestamp : First Seen\n\nSupported operators:\n- exactly   → integer value (0 = Today, 1 = Yesterday)\n- lessthan  → integer value (e.g. 6 = last 7 days)\n- between   → date range in format dd/MM/yyyy-dd/MM/yyyy\n\nLocale settings are taken into account while interpreting dates and returning results.')
    fieldFilter: str | None = Field(None, title='Field filter', min_length=1, max_length=8192, description='Field-based filter used to include leads based on field presence.\n\nFormat:\noperator|field1;field2\n\nAllowed operator:\n- hasanyvalue\n\nAllowed fields:\n- firstName\n- lastName\n- email\n\nMultiple fields can be provided using semicolons.')
    exitLinkFilter: str | None = Field(None, title='Exit link filter', min_length=1, max_length=8192, description='Exit link filter used to include or exclude leads based on exit link values.\n\nFormat:\nfield|operator|value\n\nSupported operators:\n- contains\n- is\n- isnot\n- doesnotcontain\n\nMultiple values can be provided using semicolons.')
    leadscoreFilter: int | None = Field(None, title='Leadscore filter', ge=0, le=100, description='Filters leads based on given minimum leadscore.')
    displayFilter: str | None = Field(None, title='Display filter', min_length=1, max_length=8192, description="Display filter used to control which types of leads are returned.\n\nSupported values:\n- company\n- person\n- unidentified\n\nSelecting 'unidentified' returns leads that could not be identified as a company or a person.\n\nMultiple values can be provided using semicolons.")
    fromFilter: str | None = Field(None, title='From filter', min_length=1, max_length=8192, description='Filters leads based on specified from user')
    owner: str | None = Field(None, title='Owner', min_length=1, max_length=8192, description='Filters leads based specified owner(userId)')
    hidden: str | None = Field(None, title='Hidden', min_length=1, max_length=8192, description='Filters leads based on presetInclusionList')
    search: str | None = Field(None, title='Search', min_length=1, max_length=8192, description='Keyword search.')
    emailView: Literal['NONE', 'LEAD', 'ACCOUNT'] = Field('NONE', title='Email view', description='Email view type. Possible values : NONE, LEAD, ACCOUNT ')
    notificationType: Literal['NONE', 'DAILY', 'WEEKLY'] | None = Field(None, title='Notification type', description='Set notification frequency.   Possible values:   NONE  : Do not send any notification.  DAILY  : Send notification daily.  WEEKLY  : Send notification weekly.')
    notificationMailIds: str | None = Field(None, title='Notification mail IDs', min_length=1, max_length=8192, description='List of comma separated email addresses for notification.')
    mailTemplate: str | None = Field(None, title='Mail template', min_length=1, max_length=8192, description='Set headlines for the notification email.')
    format: str | None = Field(None, title='Format', min_length=1, max_length=8192, description='Format for the segment notification. Possible values : html, csv')
    dayOfWeek: int | None = Field(None, title='Day of week', description='Day of week on which weekly notification will be sent. Possible values include numbers from 1 to 7 (where 1 refers to Monday).')
    additionalCsvFields: str | None = Field(None, title='Additional CSV fields', min_length=1, max_length=8192, description='List of comma separated fields to be included in CSV.')
    sortBy: str | None = Field(None, title='Sort by', min_length=1, max_length=8192, description='Field to sort result. Possible values :  _score  : records sorted by leadscore.  lastEvent  : records sorted by activity time. Default : _score')
    sortOrder: str | None = Field(None, title='Sort order', min_length=1, max_length=8192, description='Sort order. Possible values : asc, desc Default : desc')
    viewType: str | None = Field(None, title='View type', min_length=1, max_length=8192, description='View type. Possible values : B2B, B2C Default : B2B')
    list: str | None = Field(None, title='List', min_length=1, max_length=8192, description='Filters list file saved using List Settings Page.')
    timeField: str | None = Field(None, title='Time field', min_length=1, max_length=8192)
    csvSetName: str | None = Field(None, title='Csv set name', min_length=1, max_length=8192)


class UpdateSegmentConfig(_Operation):
    """Update Existing Segment."""
    operation: Literal["update_segment"] = Field("update_segment", title='Operation', json_schema_extra={"ui:hidden": True})
    segmentId: int = Field(..., title='Segment ID', ge=1, description='Segment ID')
    segmentName: str = Field(..., title='Segment name', min_length=1, max_length=8192, description='Segment Name')
    accountId: str = Field(..., title='Account ID', min_length=1, max_length=8192, description='Leadboxer accountId.')
    type: Literal['USER', 'ACCOUNT'] = Field(..., title='Type', description='Set visibility of the segment.   Possible values:   USER  : the segment will be private to user.  ACCOUNT  : the segment will be shared across the users of the account.')
    textFilter: str | None = Field(None, title='Text filter', min_length=1, max_length=8192, description='Text-based filter expression used to filter result fields.Format: field|operator|value. Multiple filters are comma-separated.')
    numberFilter: str | None = Field(None, title='Number filter', min_length=1, max_length=8192, description='Numeric filter expression used to filter results based on numeric fields. Format: field|operator|value. Multiple filters are comma-separated. Supported numeric operators include greaterthan, lessthan, is, isnot, between, and notbetween. The between and notbetween operators use the format min-max.')
    timeFilter: str | None = Field(None, title='Time filter', min_length=1, max_length=8192, description='Time-based filter expression used to filter results by time field. Format: field|operator|value.\n\nAllowed fields (same as `timeField` parameter):\n- eventEsTimestamp : Last Seen\n- first_session_unix_timestamp : First Seen\n\nSupported operators:\n- exactly   → integer value (0 = Today, 1 = Yesterday)\n- lessthan  → integer value (e.g. 6 = last 7 days)\n- between   → date range in format dd/MM/yyyy-dd/MM/yyyy\n\nLocale settings are taken into account while interpreting dates and returning results.')
    fieldFilter: str | None = Field(None, title='Field filter', min_length=1, max_length=8192, description='Field-based filter used to include leads based on field presence.\n\nFormat:\noperator|field1;field2\n\nAllowed operator:\n- hasanyvalue\n\nAllowed fields:\n- firstName\n- lastName\n- email\n\nMultiple fields can be provided using semicolons.')
    exitLinkFilter: str | None = Field(None, title='Exit link filter', min_length=1, max_length=8192, description='Exit link filter used to include or exclude leads based on exit link values.\n\nFormat:\nfield|operator|value\n\nSupported operators:\n- contains\n- is\n- isnot\n- doesnotcontain\n\nMultiple values can be provided using semicolons.')
    leadscoreFilter: int | None = Field(None, title='Leadscore filter', ge=0, le=100, description='Filters leads based on given minimum leadscore.')
    displayFilter: str | None = Field(None, title='Display filter', min_length=1, max_length=8192, description="Display filter used to control which types of leads are returned.\n\nSupported values:\n- company\n- person\n- unidentified\n\nSelecting 'unidentified' returns leads that could not be identified as a company or a person.\n\nMultiple values can be provided using semicolons.")
    fromFilter: str | None = Field(None, title='From filter', min_length=1, max_length=8192, description='Filters leads based on specified from user')
    owner: str | None = Field(None, title='Owner', min_length=1, max_length=8192, description='Filters leads based on specified owner')
    hidden: str | None = Field(None, title='Hidden', min_length=1, max_length=8192, description='Filters leads based on presetInclusionList')
    search: str | None = Field(None, title='Search', min_length=1, max_length=8192, description='Keyword search')
    emailView: Literal['NONE', 'LEAD', 'ACCOUNT'] = Field(..., title='Email view', description='Email view type. Possible values : NONE, LEAD, ACCOUNT ')
    notificationType: Literal['NONE', 'DAILY', 'WEEKLY'] = Field(..., title='Notification type', description='Set notification frequency.   Possible values:   NONE  : Do not send any notification.  DAILY  : Send notification daily.  WEEKLY  : Send notification weekly.')
    notificationMailIds: str | None = Field(None, title='Notification mail IDs', min_length=1, max_length=8192, description='List of comma separated email addresses for notification')
    mailTemplate: str | None = Field(None, title='Mail template', min_length=1, max_length=8192, description='Set headlines for the notification email')
    format: str | None = Field(None, title='Format', min_length=1, max_length=8192, description='Format for the segment notification. Possible values : html, csv')
    dayOfWeek: int | None = Field(None, title='Day of week', description='Day of week on which weekly notification will be sent. Possible values include numbers from 1 to 7 (where 1 refers to Monday)')
    additionalCsvFields: str | None = Field(None, title='Additional CSV fields', min_length=1, max_length=8192, description='List of comma separated fields to be included in CSV')
    sortBy: str | None = Field(None, title='Sort by', min_length=1, max_length=8192, description='Field to sort result. Possible values :  _score  : records will be sorted as per leadscore.  lastEvent  : records will be sorted as per activity time. Default : _score')
    sortOrder: str | None = Field(None, title='Sort order', min_length=1, max_length=8192, description='Sort order. Possible values : asc, desc Default : desc')
    viewType: str | None = Field(None, title='View type', min_length=1, max_length=8192, description='View type. Possible values : B2B, B2C Default : B2B')
    timeField: str | None = Field(None, title='Time field', min_length=1, max_length=8192)
    list: str | None = Field(None, title='List', min_length=1, max_length=8192)
    csvSetName: str | None = Field(None, title='Csv set name', min_length=1, max_length=8192)


class DeleteSegmentConfig(_Operation):
    """Delete Segment."""
    operation: Literal["delete_segment"] = Field("delete_segment", title='Operation', json_schema_extra={"ui:hidden": True})
    segmentId: int = Field(..., title='Segment ID', ge=1, description='Segment ID')


class UpdateLeadTagsConfig(_Operation):
    """Update Lead Tags."""
    operation: Literal["update_lead_tags"] = Field("update_lead_tags", title='Operation', json_schema_extra={"ui:hidden": True})
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192)
    leadId: str = Field(..., title='Lead ID', min_length=1, max_length=8192)
    leadTags: str = Field(..., title='Lead tags', min_length=1, max_length=8192)


class AssignLeadConfig(_Operation):
    """Assign Leads."""
    operation: Literal["assign_lead"] = Field("assign_lead", title='Operation', json_schema_extra={"ui:hidden": True})
    leadId: str = Field(..., title='Lead ID', min_length=1, max_length=8192)
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192)
    assignee: int = Field(..., title='Assignee')


class ListExclusionsConfig(_Operation):
    """Retrieve leads exclusions."""
    operation: Literal["list_exclusions"] = Field("list_exclusions", title='Operation', json_schema_extra={"ui:hidden": True})
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192)
    type: str | None = Field(None, title='Type', min_length=1, max_length=8192)


class HideLeadConfig(_Operation):
    """Hide leads."""
    operation: Literal["hide_lead"] = Field("hide_lead", title='Operation', json_schema_extra={"ui:hidden": True})
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192)
    type: Literal['use_id', 'organizationName', 'organizationDomain', 'last_most_likely_company'] = Field(..., title='Type')
    data: str = Field(..., title='Data', min_length=1, max_length=8192)


class UnhideLeadConfig(_Operation):
    """Unhide leads."""
    operation: Literal["unhide_lead"] = Field("unhide_lead", title='Operation', json_schema_extra={"ui:hidden": True})
    type: str = Field(..., title='Type', min_length=1, max_length=8192)
    data: str = Field(..., title='Data', min_length=1, max_length=8192)
    datasetId: str = Field(..., title='Dataset ID', min_length=1, max_length=8192)


# LeadBoxer's own MCP server: agents get its tools through a person's LeadBoxer sign-in.
LeadboxerMcpCredential = mcp_credential("leadboxer", "https://mcp.leadboxer.com/mcp", app="LeadBoxer")
LeadboxerCredential = Union[LeadboxerAPIKeyCredential, LeadboxerMcpCredential]


LeadboxerOperation = Annotated[Union[
    ListDatasetsConfig,
    ListLeadsConfig,
    GetLeadConfig,
    ListSessionsConfig,
    ListEventsConfig,
    LookupIpConfig,
    LookupDomainConfig,
    LookupEmailConfig,
    ListSegmentsConfig,
    CreateSegmentConfig,
    UpdateSegmentConfig,
    DeleteSegmentConfig,
    UpdateLeadTagsConfig,
    AssignLeadConfig,
    ListExclusionsConfig,
    HideLeadConfig,
    UnhideLeadConfig
], Field(discriminator="operation")]


class LeadboxerNodeConfig(NodeConfig[LeadboxerOperation, LeadboxerCredential]):
    pass


# method, path, path fields, query fields, body fields, documented success status.
ROUTES = {'list_datasets': ('GET', '/v1/users/datasets', [], ['email'], [], 200),
 'list_leads': ('GET',
                '/v1/leads',
                [],
                ['site',
                 'search',
                 'limit',
                 'locale',
                 'nextToken',
                 'criteriaTextFilter',
                 'criteriaNumberFilter',
                 'criteriaTimeFilter',
                 'criteriaFieldFilter',
                 'criteriaExitLinkFilter',
                 'criteriaLeadscoreFilter',
                 'criteriaDisplayFilter',
                 'timeField',
                 'usePresetExclusionList',
                 'userId',
                 'timeZone',
                 'sortBy'],
                [],
                200),
 'get_lead': ('GET', '/v1/leads/{leadId}', ['leadId'], ['email', 'site'], [], 200),
 'list_sessions': ('GET',
                   '/v1/leads/sessions',
                   [],
                   ['leadId', 'limit', 'site', 'email', 'userId', 'segmentId', 'minTime', 'nextToken'],
                   [],
                   200),
 'list_events': ('GET',
                 '/v1/leads/events',
                 [],
                 ['sessionId', 'limit', 'email', 'site', 'userId', 'segmentId'],
                 [],
                 200),
 'lookup_ip': ('GET', '/v1/ip-lookup', [], ['ip', 'datasetId'], [], 200),
 'lookup_domain': ('GET', '/v1/domain-lookup', [], ['domain', 'datasetId'], [], 200),
 'lookup_email': ('GET',
                  '/v1/email-lookup',
                  [],
                  ['email', 'firstName', 'lastName', 'companyName', 'companyDomain', 'datasetId'],
                  [],
                  200),
 'list_segments': ('GET', '/v1/segments', [], ['email', 'accountId', 'datasetId'], [], 200),
 'create_segment': ('POST',
                    '/v1/segments',
                    [],
                    ['email'],
                    ['name',
                     'accountId',
                     'datasetId',
                     'type',
                     'textFilter',
                     'numberFilter',
                     'timeFilter',
                     'fieldFilter',
                     'exitLinkFilter',
                     'leadscoreFilter',
                     'displayFilter',
                     'fromFilter',
                     'owner',
                     'hidden',
                     'search',
                     'emailView',
                     'notificationType',
                     'notificationMailIds',
                     'mailTemplate',
                     'format',
                     'dayOfWeek',
                     'additionalCsvFields',
                     'sortBy',
                     'sortOrder',
                     'viewType',
                     'list',
                     'timeField',
                     'csvSetName'],
                    200),
 'update_segment': ('PUT',
                    '/v1/segments/{segmentId}',
                    ['segmentId'],
                    ['segmentName'],
                    ['accountId',
                     'type',
                     'textFilter',
                     'numberFilter',
                     'timeFilter',
                     'fieldFilter',
                     'exitLinkFilter',
                     'leadscoreFilter',
                     'displayFilter',
                     'fromFilter',
                     'owner',
                     'hidden',
                     'search',
                     'emailView',
                     'notificationType',
                     'notificationMailIds',
                     'mailTemplate',
                     'format',
                     'dayOfWeek',
                     'additionalCsvFields',
                     'sortBy',
                     'sortOrder',
                     'viewType',
                     'timeField',
                     'list',
                     'csvSetName'],
                    204),
 'delete_segment': ('DELETE', '/v1/segments/{segmentId}', ['segmentId'], [], [], 204),
 'update_lead_tags': ('PUT',
                      '/v1/management/lead-tags',
                      [],
                      [],
                      ['datasetId', 'leadId', 'leadTags'],
                      204),
 'assign_lead': ('PUT', '/v1/management/assign-leads', [], [], ['leadId', 'datasetId', 'assignee'], 204),
 'list_exclusions': ('GET', '/v1/dataset-exclusion', [], ['datasetId', 'type'], [], 200),
 'hide_lead': ('POST', '/v1/dataset-exclusion', [], [], ['datasetId', 'type', 'data'], 204),
 'unhide_lead': ('DELETE', '/v1/dataset-exclusion', [], [], ['type', 'data', 'datasetId'], 204)}


def _public(value, secret):
    if isinstance(value, dict):
        return {k: _public(v, secret) for k, v in value.items()
                if k.lower().replace("_", "") not in {"apikey", "accesstoken", "refreshtoken", "password", "secret"}}
    if isinstance(value, list):
        return [_public(v, secret) for v in value]
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    return value


class LeadboxerNode(WorkflowNode):
    integration_type = "automation-leadboxer"
    credential_provider_labels = {"leadboxer": "LeadBoxer Account"}
    connection_evidence = ConnectionEvidence(
        noun="datasets", operation="list_datasets", label_keys=("humanName", "datasetId"))

    @classmethod
    def get_config_model(cls):
        return LeadboxerNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Leadboxer API key and account email")
        credential = self.config.credentials
        op = self.config.config
        values = op.model_dump(exclude_none=True)
        method, path, path_fields, query_fields, body_fields, expected_status = ROUTES[op.operation]
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        values["email"] = credential.email
        params = {k: values[k] for k in query_fields if k in values}
        body = {k: values[k] for k in body_fields if k in values} if body_fields else None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"x-api-key": credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Leadboxer request could not be completed; inspect writes before retrying") from None
        if response.status_code != expected_status:
            message = "Leadboxer request failed (HTTP " + str(response.status_code) + ")"
            if len(response.content) <= 100_000 and "json" in response.headers.get("content-type", ""):
                try:
                    problem = response.json()
                except ValueError:
                    problem = None
                if isinstance(problem, dict):
                    for field in ("detail", "message", "title"):
                        if isinstance(problem.get(field), str) and problem[field]:
                            message = _public(problem[field][:4000], credential.api_key)
                            break
            output = {"status": "error", "http_status": response.status_code,
                "message": message}
        elif expected_status == 204:
            output = {"status": "success", "http_status": 204, "acknowledged": True}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Leadboxer response exceeds the size limit")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Leadboxer returned invalid JSON") from None
            if not isinstance(payload, dict):
                raise ValueError("Leadboxer returned an unexpected response shape")
            if "errors" in payload or payload.get("success") is False:
                output = {"status": "error", "message": "Leadboxer reported an API error"}
            elif op.operation.startswith("list_"):
                if not isinstance(payload.get("data"), list):
                    raise ValueError("Leadboxer list response is missing data")
                output = {"status": "success", "data": _public(payload["data"], credential.api_key),
                    "metaData": _public(payload.get("metaData", {}), credential.api_key),
                    "http_status": expected_status}
            else:
                output = {"status": "success", "data": _public(payload, credential.api_key),
                    "http_status": expected_status}
        await self.emit(output)
        return output
