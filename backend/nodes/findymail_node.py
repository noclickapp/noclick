"""
Findymail B2B email/phone enrichment automation node.

Provides workflow integration with Findymail (REST API) for operations including:
- Finder: find email from name, from domain, from business profile, reverse email,
  find phone, find company info, find employees
- Verifier: verify email deliverability
- Intellimatch: natural-language lead search, export status, export results
- Discovery: lookalike companies, technologies lookup/search
- Signals: list/get signals, list/create/update/delete signal monitors
- Lists: list/create/update/delete contact lists, get contacts in a list
- Credits: remaining credits, usage report
- Webhook Trigger: fire when a signal monitor matches a new buying/intent signal

Authentication: API Key (Bearer token)
API Base URL: https://app.findymail.com
Documentation: https://app.findymail.com/docs/
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

FINDYMAIL_API_BASE = "https://app.findymail.com"


# ============================================================================
# Credential Schema
# ============================================================================


class FindymailApiKeyCredential(BaseModel):
    """API Key credential for Findymail."""

    credential_type: Literal["findymail_api_key"] = Field(
        "findymail_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Findymail API token from Settings -> API Tokens",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.findymail.com/user/api-tokens"}
    )


FindymailCredential = FindymailApiKeyCredential


# ============================================================================
# Finder Operation Configs
# ============================================================================


class FindymailFindEmailFromNameConfig(BaseModel):
    """Find a verified email from a person's name and company domain."""

    operation: Literal["find_email_from_name"] = Field(
        "find_email_from_name",
        json_schema_extra={
            "const": "find_email_from_name",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Find Email From Name",
        },
        title="Find Email From Name",
    )
    name: str = Field(..., title="Full Name", description="The person's full name")
    domain: str = Field(
        ..., title="Company Domain", description="The company domain (e.g. acme.com)"
    )


class FindymailFindEmailsFromDomainConfig(BaseModel):
    """Find emails associated with a company domain."""

    operation: Literal["find_emails_from_domain"] = Field(
        "find_emails_from_domain",
        json_schema_extra={
            "const": "find_emails_from_domain",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Find Emails From Domain",
        },
        title="Find Emails From Domain",
    )
    domain: str = Field(
        ..., title="Company Domain", description="The company domain (e.g. acme.com)"
    )
    roles: str = Field(
        "Founder",
        title="Target Roles",
        description="Comma-separated target roles to search for, max 3",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional webhook for asynchronous processing",
    )


class FindymailFindFromBusinessProfileConfig(BaseModel):
    """Find an email from a LinkedIn / business profile URL."""

    operation: Literal["find_from_business_profile"] = Field(
        "find_from_business_profile",
        json_schema_extra={
            "const": "find_from_business_profile",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Find From Business Profile",
        },
        title="Find From Business Profile",
    )
    linkedin_url: str = Field(
        ...,
        title="LinkedIn / Profile URL",
        description="The LinkedIn or business profile URL",
    )


class FindymailReverseEmailConfig(BaseModel):
    """Find a LinkedIn profile from an email address."""

    operation: Literal["reverse_email"] = Field(
        "reverse_email",
        json_schema_extra={
            "const": "reverse_email",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Reverse Email Lookup",
        },
        title="Reverse Email Lookup",
    )
    email: str = Field(..., title="Email", description="The email address to look up")
    with_profile: str = Field(
        "false",
        title="Include Full Profile",
        description="Return the full profile (costs 2 credits instead of 1)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FindymailFindPhoneConfig(BaseModel):
    """Find a direct phone number from a LinkedIn URL (GDPR-compliant, no EU)."""

    operation: Literal["find_phone"] = Field(
        "find_phone",
        json_schema_extra={
            "const": "find_phone",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Find Phone",
        },
        title="Find Phone",
    )
    linkedin_url: str = Field(
        ..., title="LinkedIn URL", description="The LinkedIn profile URL"
    )


class FindymailGetCompanyConfig(BaseModel):
    """Enrich a company by domain, LinkedIn URL, or name."""

    operation: Literal["get_company"] = Field(
        "get_company",
        json_schema_extra={
            "const": "get_company",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Get Company Information",
        },
        title="Get Company Information",
    )
    domain: Optional[str] = Field(
        None, title="Company Domain", description="The company domain (e.g. acme.com)"
    )
    linkedin_url: Optional[str] = Field(
        None, title="LinkedIn URL", description="The company LinkedIn URL"
    )
    name: Optional[str] = Field(
        None, title="Company Name", description="The company name"
    )


class FindymailFindEmployeesConfig(BaseModel):
    """Find employees at a company by website and job titles."""

    operation: Literal["find_employees"] = Field(
        "find_employees",
        json_schema_extra={
            "const": "find_employees",
            "ui:hidden": True,
            "x-category": "Finder",
            "x-is-trigger": False,
            "x-display-name": "Find Employees",
        },
        title="Find Employees",
    )
    website: str = Field(
        ..., title="Company Website", description="The company website (e.g. acme.com)"
    )
    job_titles: str = Field(
        ...,
        title="Job Titles",
        description="Target job titles, comma-separated (e.g. CEO, VP Sales)",
    )
    count: Optional[str] = Field(
        None, title="Count", description="Max number of employees to return"
    )


# ============================================================================
# Verifier Operation Config
# ============================================================================


class FindymailVerifyEmailConfig(BaseModel):
    """Verify the deliverability of an email address."""

    operation: Literal["verify_email"] = Field(
        "verify_email",
        json_schema_extra={
            "const": "verify_email",
            "ui:hidden": True,
            "x-category": "Verifier",
            "x-is-trigger": False,
            "x-display-name": "Verify Email",
        },
        title="Verify Email",
    )
    email: str = Field(..., title="Email", description="The email address to verify")


# ============================================================================
# Intellimatch Operation Configs
# ============================================================================


class FindymailIntellimatchSearchConfig(BaseModel):
    """Run a natural-language lead search (kicks off an async export)."""

    operation: Literal["intellimatch_search"] = Field(
        "intellimatch_search",
        json_schema_extra={
            "const": "intellimatch_search",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Search Leads (Intellimatch)",
        },
        title="Search Leads (Intellimatch)",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Natural-language description of the leads you want",
        json_schema_extra={"ui:widget": "textarea"},
    )
    limit: Optional[str] = Field(
        None, title="Limit", description="Max number of leads to return"
    )
    find_contact: str = Field(
        "true",
        title="Find Contacts",
        description="Resolve contact details for matched leads",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    find_email: str = Field(
        "true",
        title="Find Emails",
        description="Resolve verified emails for matched leads",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    find_phone: str = Field(
        "false",
        title="Find Phone Numbers",
        description="Resolve direct phone numbers for matched leads",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    target_job_titles: Optional[str] = Field(
        None,
        title="Target Job Titles",
        description="Comma-separated job titles to target for contacts",
    )
    lead_list_id: Optional[str] = Field(
        None,
        title="Lead List",
        description="Optional contact list to add matched contacts to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "lead_list_id",
                "placeholder": "Optional: select a contact list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_contact_list",
        },
    )
    mode: Optional[str] = Field(
        None,
        title="Mode",
        description="Export mode",
        json_schema_extra={
            "enum": ["broad", "targeted"],
            "enumNames": ["Broad", "Targeted"],
            "x-enum-searchable": True,
        },
    )
    require_email: str = Field(
        "false",
        title="Require Email",
        description="Only return companies where an email was found",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    add_to_exclusion_list: str = Field(
        "false",
        title="Add To Exclusion List",
        description="Add exported companies to an exclusion list",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    exclusion_list_id: Optional[str] = Field(
        None,
        title="Exclusion List To Add To",
        description="Exclusion list to add exported companies to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "excluded_domain_list_id",
                "placeholder": "Optional: choose a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_exclusion_list",
        },
    )
    exclusion_filter_list_ids: Optional[str] = Field(
        None,
        title="Exclusion Filter List IDs",
        description="Comma-separated exclusion list IDs to filter results by",
    )


class FindymailIntellimatchStatusConfig(BaseModel):
    """Poll the status of an Intellimatch search/export job."""

    operation: Literal["intellimatch_status"] = Field(
        "intellimatch_status",
        json_schema_extra={
            "const": "intellimatch_status",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Get Export Status",
        },
        title="Get Export Status",
    )
    hash: str = Field(
        ..., title="Export Hash", description="The search hash to poll"
    )


class FindymailIntellimatchDataConfig(BaseModel):
    """Fetch paginated Intellimatch export results."""

    operation: Literal["intellimatch_data"] = Field(
        "intellimatch_data",
        json_schema_extra={
            "const": "intellimatch_data",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Get Intellimatch Results",
        },
        title="Get Intellimatch Results",
    )
    hash: str = Field(
        ..., title="Export Hash", description="The search hash"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (default 1)")
    per_page: Optional[str] = Field(
        "100", title="Per Page", description="Results per page (max 500, default 100)"
    )


class FindymailListExclusionListsConfig(BaseModel):
    """List Intellimatch exclusion lists."""

    operation: Literal["list_exclusion_lists"] = Field(
        "list_exclusion_lists",
        json_schema_extra={
            "const": "list_exclusion_lists",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "List Exclusion Lists",
        },
        title="List Exclusion Lists",
    )


class FindymailCreateExclusionListConfig(BaseModel):
    """Create an Intellimatch exclusion list."""

    operation: Literal["create_exclusion_list"] = Field(
        "create_exclusion_list",
        json_schema_extra={
            "const": "create_exclusion_list",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Create Exclusion List",
            "x-creates-resource": True,
            "x-resource-type": "findymail_exclusion_list",
            "x-resource-id-path": "data.id",
        },
        title="Create Exclusion List",
    )
    name: str = Field(..., title="List Name", description="Unique exclusion-list name")
    is_shared: str = Field(
        "false",
        title="Share With Team",
        description="Whether to share this exclusion list with your current team",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FindymailGetExclusionListConfig(BaseModel):
    """Fetch one exclusion list by ID."""

    operation: Literal["get_exclusion_list"] = Field(
        "get_exclusion_list",
        json_schema_extra={
            "const": "get_exclusion_list",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Get Exclusion List",
        },
        title="Get Exclusion List",
    )
    excluded_domain_list_id: str = Field(
        ...,
        title="Exclusion List",
        description="The exclusion list to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "excluded_domain_list_id",
                "placeholder": "Select an exclusion list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_exclusion_list",
        },
    )


class FindymailUpdateExclusionListConfig(BaseModel):
    """Update an exclusion list."""

    operation: Literal["update_exclusion_list"] = Field(
        "update_exclusion_list",
        json_schema_extra={
            "const": "update_exclusion_list",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Update Exclusion List",
        },
        title="Update Exclusion List",
    )
    excluded_domain_list_id: str = Field(
        ...,
        title="Exclusion List",
        description="The exclusion list to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "excluded_domain_list_id",
                "placeholder": "Select an exclusion list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_exclusion_list",
        },
    )
    name: str = Field(..., title="List Name", description="New exclusion-list name")
    is_shared: Optional[str] = Field(
        None,
        title="Share With Team",
        description="Set to yes to share with your current team",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FindymailDeleteExclusionListConfig(BaseModel):
    """Delete an exclusion list."""

    operation: Literal["delete_exclusion_list"] = Field(
        "delete_exclusion_list",
        json_schema_extra={
            "const": "delete_exclusion_list",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Delete Exclusion List",
        },
        title="Delete Exclusion List",
    )
    excluded_domain_list_id: str = Field(
        ...,
        title="Exclusion List",
        description="The exclusion list to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "excluded_domain_list_id",
                "placeholder": "Select an exclusion list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_exclusion_list",
        },
    )


class FindymailListExcludedDomainsConfig(BaseModel):
    """List excluded domains."""

    operation: Literal["list_excluded_domains"] = Field(
        "list_excluded_domains",
        json_schema_extra={
            "const": "list_excluded_domains",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "List Excluded Domains",
        },
        title="List Excluded Domains",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Filter domains by substring"
    )
    excluded_domain_list_id: Optional[str] = Field(
        None,
        title="Exclusion List",
        description="Optional exclusion list to filter by",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "excluded_domain_list_id",
                "placeholder": "Optional: choose a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_exclusion_list",
        },
    )
    per_page: Optional[str] = Field("15", title="Per Page", description="Domains per page")
    page: Optional[str] = Field("1", title="Page", description="Page number")


class FindymailAddExcludedDomainsConfig(BaseModel):
    """Add domains to the exclusion list."""

    operation: Literal["add_excluded_domains"] = Field(
        "add_excluded_domains",
        json_schema_extra={
            "const": "add_excluded_domains",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Add Excluded Domains",
        },
        title="Add Excluded Domains",
    )
    domains: str = Field(
        ...,
        title="Domains",
        description="Comma-separated domains to exclude",
    )
    excluded_domain_list_id: Optional[str] = Field(
        None,
        title="Exclusion List",
        description="Optional list to add domains to; leave empty for global exclusions",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "excluded_domain_list_id",
                "placeholder": "Optional: choose a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_exclusion_list",
        },
    )


class FindymailRemoveExcludedDomainsConfig(BaseModel):
    """Remove excluded domains by ID."""

    operation: Literal["remove_excluded_domains"] = Field(
        "remove_excluded_domains",
        json_schema_extra={
            "const": "remove_excluded_domains",
            "ui:hidden": True,
            "x-category": "Intellimatch",
            "x-is-trigger": False,
            "x-display-name": "Remove Excluded Domains",
        },
        title="Remove Excluded Domains",
    )
    ids: str = Field(
        ...,
        title="Domain IDs",
        description="Comma-separated excluded-domain IDs to remove",
    )


# ============================================================================
# Discovery Operation Configs
# ============================================================================


class FindymailLookalikeSearchConfig(BaseModel):
    """Find companies similar to seed companies."""

    operation: Literal["lookalike_search"] = Field(
        "lookalike_search",
        json_schema_extra={
            "const": "lookalike_search",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "Search Lookalike Companies",
        },
        title="Search Lookalike Companies",
    )
    domains: str = Field(
        ...,
        title="Seed Domains",
        description="Seed company domains, comma-separated (e.g. acme.com, globex.com)",
    )
    limit: Optional[str] = Field(
        None, title="Limit", description="Max number of lookalike companies to return"
    )


class FindymailTechnologiesLookupConfig(BaseModel):
    """Look up the tech stack detected for a domain."""

    operation: Literal["technologies_lookup"] = Field(
        "technologies_lookup",
        json_schema_extra={
            "const": "technologies_lookup",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "Lookup Technologies By Domain",
        },
        title="Lookup Technologies By Domain",
    )
    domain: str = Field(
        ..., title="Domain", description="The domain to inspect (e.g. acme.com)"
    )


class FindymailTechnologiesSearchConfig(BaseModel):
    """Search the technology catalog."""

    operation: Literal["technologies_search"] = Field(
        "technologies_search",
        json_schema_extra={
            "const": "technologies_search",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "Search Technologies",
        },
        title="Search Technologies",
    )
    query: str = Field(
        ..., title="Query", description="Technology name to search for (e.g. Shopify)"
    )


# ============================================================================
# Signals Operation Configs
# ============================================================================


class FindymailListSignalsConfig(BaseModel):
    """List buying / intent signals."""

    operation: Literal["list_signals"] = Field(
        "list_signals",
        json_schema_extra={
            "const": "list_signals",
            "ui:hidden": True,
            "x-category": "Signals",
            "x-is-trigger": False,
            "x-display-name": "List Signals",
        },
        title="List Signals",
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (default 1)")
    per_page: Optional[str] = Field(
        "50", title="Per Page", description="Results per page (max 100, default 50)"
    )


class FindymailGetSignalConfig(BaseModel):
    """Fetch one signal by its id."""

    operation: Literal["get_signal"] = Field(
        "get_signal",
        json_schema_extra={
            "const": "get_signal",
            "ui:hidden": True,
            "x-category": "Signals",
            "x-is-trigger": False,
            "x-display-name": "Get A Signal",
        },
        title="Get A Signal",
    )
    signal_id: str = Field(..., title="Signal ID", description="The signal id to fetch")


class FindymailListSignalMonitorsConfig(BaseModel):
    """List signal monitors."""

    operation: Literal["list_signal_monitors"] = Field(
        "list_signal_monitors",
        json_schema_extra={
            "const": "list_signal_monitors",
            "ui:hidden": True,
            "x-category": "Signals",
            "x-is-trigger": False,
            "x-display-name": "List Signal Monitors",
        },
        title="List Signal Monitors",
    )
    ownership: Optional[str] = Field(
        None,
        title="Ownership",
        description="Filter monitors by ownership scope",
        json_schema_extra={
            "enum": ["my", "team", "all"],
            "enumNames": ["My Monitors", "Team Monitors", "All Accessible"],
            "x-enum-searchable": True,
        },
    )


class FindymailCreateSignalMonitorConfig(BaseModel):
    """Create a signal monitor."""

    operation: Literal["create_signal_monitor"] = Field(
        "create_signal_monitor",
        json_schema_extra={
            "const": "create_signal_monitor",
            "ui:hidden": True,
            "x-category": "Signals",
            "x-is-trigger": False,
            "x-display-name": "Create Signal Monitor",
        },
        title="Create Signal Monitor",
    )
    name: str = Field(..., title="Monitor Name", description="A name for the monitor")
    signal_type: str = Field(
        ...,
        title="Signal Type",
        description="The signal source to monitor",
        json_schema_extra={
            "enum": [
                "keyword_mention",
                "new_hire",
                "job_change",
                "post_engagement",
                "company_hiring",
            ],
            "enumNames": [
                "Keyword Mention",
                "New Hire",
                "Job Change",
                "Post Engagement",
                "Company Hiring",
            ],
            "x-enum-searchable": True,
        },
    )
    keywords: Optional[str] = Field(
        None,
        title="Keywords",
        description="Comma-separated keywords. Required for keyword mentions and some post-engagement monitors.",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional HTTPS URL to receive new matching signals",
    )
    post_url: Optional[str] = Field(
        None,
        title="LinkedIn Post URL",
        description="Required for post-engagement monitors when tracking one post",
    )
    profile_url: Optional[str] = Field(
        None,
        title="LinkedIn Profile URL",
        description="Optional LinkedIn profile URL for post-engagement monitors",
    )
    engagement_types: Optional[str] = Field(
        None,
        title="Engagement Types",
        description="Comma-separated engagement types, e.g. like, comment",
    )
    enrichment_level: Optional[str] = Field(
        None,
        title="Enrichment Level",
        description="Contact enrichment level for matched signals",
        json_schema_extra={
            "enum": ["email", "email_phone"],
            "enumNames": ["Email Only", "Email and Phone"],
            "x-enum-searchable": True,
        },
    )
    lead_list_id: Optional[str] = Field(
        None,
        title="Lead List",
        description="Optional contact list to add matched contacts to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "lead_list_id",
                "placeholder": "Optional: select a contact list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_contact_list",
        },
    )
    ai_relevance_prompt: Optional[str] = Field(
        None,
        title="AI Relevance Prompt",
        description="Optional custom relevance prompt",
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_companies: Optional[str] = Field(
        None,
        title="Target Companies",
        description="Comma-separated company names or domains",
    )
    is_shared: str = Field(
        "false",
        title="Share With Team",
        description="Whether to share this monitor with your current team",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    icp_industries: Optional[str] = Field(
        None, title="ICP Industries", description="Comma-separated industries"
    )
    icp_employee_count_ranges: Optional[str] = Field(
        None,
        title="ICP Employee Count Ranges",
        description="Comma-separated employee ranges, e.g. 51-200, 201-500",
    )
    icp_countries: Optional[str] = Field(
        None,
        title="ICP Countries",
        description="Comma-separated 2-letter country codes, e.g. US, FR",
    )
    icp_job_title_keywords: Optional[str] = Field(
        None,
        title="ICP Job Title Keywords",
        description="Comma-separated job-title keywords",
    )
    icp_seniority_levels: Optional[str] = Field(
        None,
        title="ICP Seniority Levels",
        description="Comma-separated seniority levels, e.g. 11, 13, 14",
    )
    job_offer_title_keywords: Optional[str] = Field(
        None,
        title="Job Offer Title Keywords",
        description="Comma-separated job-title keywords for company-hiring monitors",
    )


class FindymailUpdateSignalMonitorConfig(BaseModel):
    """Update a signal monitor."""

    operation: Literal["update_signal_monitor"] = Field(
        "update_signal_monitor",
        json_schema_extra={
            "const": "update_signal_monitor",
            "ui:hidden": True,
            "x-category": "Signals",
            "x-is-trigger": False,
            "x-display-name": "Update Signal Monitor",
        },
        title="Update Signal Monitor",
    )
    monitor_id: str = Field(
        ..., title="Monitor ID", description="The signal monitor id to update"
    )
    name: str = Field(..., title="Monitor Name", description="New monitor name")
    keywords: Optional[str] = Field(
        None,
        title="Keywords",
        description="Comma-separated keywords for the monitor",
    )
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="New HTTPS callback URL"
    )
    engagement_types: Optional[str] = Field(
        None,
        title="Engagement Types",
        description="Comma-separated engagement types, e.g. like, comment",
    )
    enrichment_level: Optional[str] = Field(
        None,
        title="Enrichment Level",
        description="Contact enrichment level for matched signals",
        json_schema_extra={
            "enum": ["email", "email_phone"],
            "enumNames": ["Email Only", "Email and Phone"],
            "x-enum-searchable": True,
        },
    )
    lead_list_id: Optional[str] = Field(
        None,
        title="Lead List",
        description="Optional contact list to add matched contacts to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "lead_list_id",
                "placeholder": "Optional: select a contact list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_contact_list",
        },
    )
    ai_relevance_prompt: Optional[str] = Field(
        None,
        title="AI Relevance Prompt",
        description="Optional custom relevance prompt",
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_companies: Optional[str] = Field(
        None,
        title="Target Companies",
        description="Comma-separated company names or domains",
    )
    is_shared: Optional[str] = Field(
        None,
        title="Share With Team",
        description="Whether to share this monitor with your current team",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    icp_industries: Optional[str] = Field(
        None, title="ICP Industries", description="Comma-separated industries"
    )
    icp_employee_count_ranges: Optional[str] = Field(
        None,
        title="ICP Employee Count Ranges",
        description="Comma-separated employee ranges, e.g. 51-200, 201-500",
    )
    icp_countries: Optional[str] = Field(
        None,
        title="ICP Countries",
        description="Comma-separated 2-letter country codes, e.g. US, FR",
    )
    icp_job_title_keywords: Optional[str] = Field(
        None,
        title="ICP Job Title Keywords",
        description="Comma-separated job-title keywords",
    )
    icp_seniority_levels: Optional[str] = Field(
        None,
        title="ICP Seniority Levels",
        description="Comma-separated seniority levels, e.g. 11, 13, 14",
    )
    job_offer_title_keywords: Optional[str] = Field(
        None,
        title="Job Offer Title Keywords",
        description="Comma-separated job-title keywords for company-hiring monitors",
    )


class FindymailDeleteSignalMonitorConfig(BaseModel):
    """Delete a signal monitor."""

    operation: Literal["delete_signal_monitor"] = Field(
        "delete_signal_monitor",
        json_schema_extra={
            "const": "delete_signal_monitor",
            "ui:hidden": True,
            "x-category": "Signals",
            "x-is-trigger": False,
            "x-display-name": "Delete Signal Monitor",
        },
        title="Delete Signal Monitor",
    )
    monitor_id: str = Field(
        ..., title="Monitor ID", description="The signal monitor id to delete"
    )


# ============================================================================
# Lists Operation Configs
# ============================================================================


class FindymailListContactListsConfig(BaseModel):
    """List the user's saved contact lists."""

    operation: Literal["list_contact_lists"] = Field(
        "list_contact_lists",
        json_schema_extra={
            "const": "list_contact_lists",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "List Contact Lists",
        },
        title="List Contact Lists",
    )


class FindymailCreateContactListConfig(BaseModel):
    """Create a new contact list."""

    operation: Literal["create_contact_list"] = Field(
        "create_contact_list",
        json_schema_extra={
            "const": "create_contact_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Create Contact List",
            "x-creates-resource": True,
            "x-resource-type": "findymail_contact_list",
            "x-resource-id-path": "data.id",
        },
        title="Create Contact List",
    )
    name: str = Field(..., title="List Name", description="A name for the contact list")


class FindymailUpdateContactListConfig(BaseModel):
    """Rename / update a contact list."""

    operation: Literal["update_contact_list"] = Field(
        "update_contact_list",
        json_schema_extra={
            "const": "update_contact_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Update Contact List",
        },
        title="Update Contact List",
    )
    list_id: str = Field(..., title="List ID", description="The contact list id to update")
    name: str = Field(..., title="List Name", description="The new list name")
    is_shared: str = Field(
        "false",
        title="Share With Team",
        description="Whether to share the list with your team",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FindymailDeleteContactListConfig(BaseModel):
    """Delete a contact list."""

    operation: Literal["delete_contact_list"] = Field(
        "delete_contact_list",
        json_schema_extra={
            "const": "delete_contact_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact List",
        },
        title="Delete Contact List",
    )
    list_id: str = Field(..., title="List ID", description="The contact list id to delete")


class FindymailGetContactsConfig(BaseModel):
    """Retrieve contacts saved in a given list."""

    operation: Literal["get_contacts"] = Field(
        "get_contacts",
        json_schema_extra={
            "const": "get_contacts",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Get Contacts In A List",
        },
        title="Get Contacts In A List",
    )
    list_id: str = Field(
        ...,
        title="Contact List",
        description="The contact list to read",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "list_id",
                "placeholder": "Select a contact list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_contact_list",
        },
    )


# ============================================================================
# Credits Operation Configs
# ============================================================================


class FindymailGetCreditsConfig(BaseModel):
    """Return remaining finder / verifier credit balance."""

    operation: Literal["get_credits"] = Field(
        "get_credits",
        json_schema_extra={
            "const": "get_credits",
            "ui:hidden": True,
            "x-category": "Credits",
            "x-is-trigger": False,
            "x-display-name": "Get Remaining Credits",
        },
        title="Get Remaining Credits",
    )


class FindymailGetUsageSummaryConfig(BaseModel):
    """Return the per-account credit usage report."""

    operation: Literal["get_usage_summary"] = Field(
        "get_usage_summary",
        json_schema_extra={
            "const": "get_usage_summary",
            "ui:hidden": True,
            "x-category": "Credits",
            "x-is-trigger": False,
            "x-display-name": "Get Usage Summary",
        },
        title="Get Usage Summary",
    )


class FindymailGetTeamUsageSummaryConfig(BaseModel):
    """Return the per-team credit usage report."""

    operation: Literal["get_team_usage_summary"] = Field(
        "get_team_usage_summary",
        json_schema_extra={
            "const": "get_team_usage_summary",
            "ui:hidden": True,
            "x-category": "Credits",
            "x-is-trigger": False,
            "x-display-name": "Get Team Usage Summary",
        },
        title="Get Team Usage Summary",
    )
    from_date: Optional[str] = Field(
        None,
        title="From Date",
        description="Inclusive start date in YYYY-MM-DD format",
    )
    to_date: Optional[str] = Field(
        None,
        title="To Date",
        description="Inclusive end date in YYYY-MM-DD format",
    )


# ============================================================================
# Webhook Trigger Config (signal monitor)
# ============================================================================


class FindymailSignalTriggerConfig(BaseModel):
    """Fire the workflow when a signal monitor matches a new buying/intent signal."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_signal_match"] = Field(
        "on_signal_match",
        json_schema_extra={
            "const": "on_signal_match",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Signal Match",
        },
        title="On Signal Match",
    )
    monitor_name: str = Field(
        "NoClick Trigger",
        title="Monitor Name",
        description="Name for the signal monitor created to power this trigger",
    )
    signal_type: str = Field(
        "job_change",
        title="Signal Type",
        description="The signal source to monitor for this trigger",
        json_schema_extra={
            "enum": [
                "keyword_mention",
                "new_hire",
                "job_change",
                "post_engagement",
                "company_hiring",
            ],
            "enumNames": [
                "Keyword Mention",
                "New Hire",
                "Job Change",
                "Post Engagement",
                "Company Hiring",
            ],
            "x-enum-searchable": True,
        },
    )
    keywords: Optional[str] = Field(
        None,
        title="Keywords",
        description="Comma-separated keywords. Required for keyword mentions and some post-engagement monitors.",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Findymail posts new matching signals here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    post_url: Optional[str] = Field(
        None,
        title="LinkedIn Post URL",
        description="Required for post-engagement monitors when tracking one post",
    )
    profile_url: Optional[str] = Field(
        None,
        title="LinkedIn Profile URL",
        description="Optional LinkedIn profile URL for post-engagement monitors",
    )
    engagement_types: Optional[str] = Field(
        None,
        title="Engagement Types",
        description="Comma-separated engagement types, e.g. like, comment",
    )
    enrichment_level: Optional[str] = Field(
        None,
        title="Enrichment Level",
        description="Contact enrichment level for matched signals",
        json_schema_extra={
            "enum": ["email", "email_phone"],
            "enumNames": ["Email Only", "Email and Phone"],
            "x-enum-searchable": True,
        },
    )
    lead_list_id: Optional[str] = Field(
        None,
        title="Lead List",
        description="Optional contact list to add matched contacts to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "lead_list_id",
                "placeholder": "Optional: select a contact list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list ID",
            },
            "x-resource-type": "findymail_contact_list",
        },
    )
    ai_relevance_prompt: Optional[str] = Field(
        None,
        title="AI Relevance Prompt",
        description="Optional custom relevance prompt",
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_companies: Optional[str] = Field(
        None,
        title="Target Companies",
        description="Comma-separated company names or domains",
    )
    is_shared: str = Field(
        "false",
        title="Share With Team",
        description="Whether to share this monitor with your current team",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    icp_industries: Optional[str] = Field(
        None, title="ICP Industries", description="Comma-separated industries"
    )
    icp_employee_count_ranges: Optional[str] = Field(
        None,
        title="ICP Employee Count Ranges",
        description="Comma-separated employee ranges, e.g. 51-200, 201-500",
    )
    icp_countries: Optional[str] = Field(
        None,
        title="ICP Countries",
        description="Comma-separated 2-letter country codes, e.g. US, FR",
    )
    icp_job_title_keywords: Optional[str] = Field(
        None,
        title="ICP Job Title Keywords",
        description="Comma-separated job-title keywords",
    )
    icp_seniority_levels: Optional[str] = Field(
        None,
        title="ICP Seniority Levels",
        description="Comma-separated seniority levels, e.g. 11, 13, 14",
    )
    job_offer_title_keywords: Optional[str] = Field(
        None,
        title="Job Offer Title Keywords",
        description="Comma-separated job-title keywords for company-hiring monitors",
    )
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


FindymailConfig = Annotated[
    Union[
        FindymailFindEmailFromNameConfig,
        FindymailFindEmailsFromDomainConfig,
        FindymailFindFromBusinessProfileConfig,
        FindymailReverseEmailConfig,
        FindymailFindPhoneConfig,
        FindymailGetCompanyConfig,
        FindymailFindEmployeesConfig,
        FindymailVerifyEmailConfig,
        FindymailIntellimatchSearchConfig,
        FindymailIntellimatchStatusConfig,
        FindymailIntellimatchDataConfig,
        FindymailListExclusionListsConfig,
        FindymailCreateExclusionListConfig,
        FindymailGetExclusionListConfig,
        FindymailUpdateExclusionListConfig,
        FindymailDeleteExclusionListConfig,
        FindymailListExcludedDomainsConfig,
        FindymailAddExcludedDomainsConfig,
        FindymailRemoveExcludedDomainsConfig,
        FindymailLookalikeSearchConfig,
        FindymailTechnologiesLookupConfig,
        FindymailTechnologiesSearchConfig,
        FindymailListSignalsConfig,
        FindymailGetSignalConfig,
        FindymailListSignalMonitorsConfig,
        FindymailCreateSignalMonitorConfig,
        FindymailUpdateSignalMonitorConfig,
        FindymailDeleteSignalMonitorConfig,
        FindymailListContactListsConfig,
        FindymailCreateContactListConfig,
        FindymailUpdateContactListConfig,
        FindymailDeleteContactListConfig,
        FindymailGetContactsConfig,
        FindymailGetCreditsConfig,
        FindymailGetUsageSummaryConfig,
        FindymailGetTeamUsageSummaryConfig,
        FindymailSignalTriggerConfig,
    ],
    Discriminator("operation"),
]


class FindymailNodeConfig(NodeConfig[FindymailConfig, FindymailCredential]):
    """Full configuration for the Findymail node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[list]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _optional_int(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Optional[str]) -> Optional[bool]:
    if value in (None, ""):
        return None
    return str(value).lower() == "true"


def _optional_int_list(value: Optional[str]) -> Optional[list[int]]:
    values = _comma_list(value)
    if not values:
        return None
    ints = []
    for item in values:
        try:
            ints.append(int(item))
        except ValueError:
            continue
    return ints or None


def _build_icp_filters(config: Any) -> Optional[Dict[str, Any]]:
    icp_filters = {
        "industries": _comma_list(getattr(config, "icp_industries", None)),
        "employee_count_ranges": _comma_list(
            getattr(config, "icp_employee_count_ranges", None)
        ),
        "countries": _comma_list(getattr(config, "icp_countries", None)),
        "job_title_keywords": _comma_list(
            getattr(config, "icp_job_title_keywords", None)
        ),
        "seniority_levels": _optional_int_list(
            getattr(config, "icp_seniority_levels", None)
        ),
    }
    icp_filters = {key: value for key, value in icp_filters.items() if value}
    return icp_filters or None


def _build_signal_monitor_payload(config: Any, *, include_signal_type: bool) -> Dict[str, Any]:
    payload = {
        "name": getattr(config, "name", None)
        or getattr(config, "monitor_name", None),
        "signal_type": getattr(config, "signal_type", None) if include_signal_type else None,
        "keywords": _comma_list(getattr(config, "keywords", None)),
        "webhook_url": getattr(config, "webhook_url", None),
        "post_url": getattr(config, "post_url", None),
        "profile_url": getattr(config, "profile_url", None),
        "engagement_types": _comma_list(getattr(config, "engagement_types", None)),
        "enrichment_level": getattr(config, "enrichment_level", None),
        "lead_list_id": _optional_int(getattr(config, "lead_list_id", None)),
        "ai_relevance_prompt": getattr(config, "ai_relevance_prompt", None),
        "target_companies": _comma_list(getattr(config, "target_companies", None)),
        "is_shared": _optional_bool(getattr(config, "is_shared", None)),
        "icp_filters": _build_icp_filters(config),
        "job_offer_title_keywords": _comma_list(
            getattr(config, "job_offer_title_keywords", None)
        ),
    }
    return {key: value for key, value in payload.items() if value is not None}


async def _findymail_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Findymail request and return a structured result."""
    url = f"{FINDYMAIL_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") or err.get("error") or str(err)
                except Exception:
                    message = response.text
                # Surface Findymail's distinct credit/subscription error codes clearly.
                if response.status_code == 402:
                    message = f"Not enough credits: {message}"
                elif response.status_code == 423:
                    message = f"Subscription paused: {message}"
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FindymailNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                # Findymail returns some 200s as text/plain with a JSON-shaped body.
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[FindymailNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class FindymailNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Findymail B2B email/phone enrichment automation node."""

    edit_examples = [
        "Find the verified email for a prospect by name and company domain",
        "Verify whether an email address is deliverable",
        "Enrich a company by its domain to get firmographics",
        "Find direct phone numbers for a list of LinkedIn URLs",
        "Trigger a workflow when a signal monitor matches a new buying signal",
    ]

    @classmethod
    def get_config_model(cls):
        return FindymailNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (contact / exclusion lists)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        endpoint_by_field = {
            "list_id": ("/api/lists", "lists"),
            "lead_list_id": ("/api/lists", "lists"),
            "excluded_domain_list_id": (
                "/api/intellimatch/exclusion-lists",
                "lists",
            ),
        }
        endpoint_info = endpoint_by_field.get(field_name)
        if not endpoint_info:
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        api_key = credential.get("api_key")
        endpoint, collection_key = endpoint_info
        result = await _findymail_request(
            api_key, "GET", endpoint, action_name=f"load_{field_name}_options"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        lists = data if isinstance(data, list) else data.get(collection_key) or data.get("data") or []
        options = []
        for lst in lists:
            if not isinstance(lst, dict):
                continue
            lst_id = lst.get("id")
            name = lst.get("name") or f"List {lst_id}"
            if lst_id is not None:
                options.append({"label": str(name), "value": str(lst_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration (signal monitor)
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        if not api_key:
            raise ValueError("A Findymail API key is required to register the trigger")
        monitor_config = FindymailSignalTriggerConfig.model_validate(
            {**(config or {}), "webhook_url": webhook_url}
        )
        result = await _findymail_request(
            api_key,
            "POST",
            "/api/signals/monitors",
            json_body=_build_signal_monitor_payload(
                monitor_config,
                include_signal_type=True,
            ),
            action_name="create_signal_monitor",
        )
        if result.get("status") != "success":
            raise ValueError(f"Findymail signal monitor registration failed: {result.get('error')}")
        data = result.get("data") or {}
        monitor = data.get("monitor", data) if isinstance(data, dict) else {}
        external_id = monitor.get("id") if isinstance(monitor, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id is not None else None,
            # Findymail's public API documents webhook URLs but does not expose a
            # shared-secret exchange for signal monitors.
            "signing_secret": None,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_key = (credential or {}).get("api_key")
        if not external_id or not api_key:
            return
        await _findymail_request(
            api_key, "DELETE", f"/api/signals/monitors/{external_id}",
            action_name="delete_signal_monitor",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-findymail-signature") or headers.get("x-signature")
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FindymailNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, FindymailSignalTriggerConfig):
            return {
                "status": "success",
                "action": "on_signal_match",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Findymail API key.")
        api_key = credentials.api_key

        handlers = {
            "find_email_from_name": self._find_email_from_name,
            "find_emails_from_domain": self._find_emails_from_domain,
            "find_from_business_profile": self._find_from_business_profile,
            "reverse_email": self._reverse_email,
            "find_phone": self._find_phone,
            "get_company": self._get_company,
            "find_employees": self._find_employees,
            "verify_email": self._verify_email,
            "intellimatch_search": self._intellimatch_search,
            "intellimatch_status": self._intellimatch_status,
            "intellimatch_data": self._intellimatch_data,
            "list_exclusion_lists": self._list_exclusion_lists,
            "create_exclusion_list": self._create_exclusion_list,
            "get_exclusion_list": self._get_exclusion_list,
            "update_exclusion_list": self._update_exclusion_list,
            "delete_exclusion_list": self._delete_exclusion_list,
            "list_excluded_domains": self._list_excluded_domains,
            "add_excluded_domains": self._add_excluded_domains,
            "remove_excluded_domains": self._remove_excluded_domains,
            "lookalike_search": self._lookalike_search,
            "technologies_lookup": self._technologies_lookup,
            "technologies_search": self._technologies_search,
            "list_signals": self._list_signals,
            "get_signal": self._get_signal,
            "list_signal_monitors": self._list_signal_monitors,
            "create_signal_monitor": self._create_signal_monitor,
            "update_signal_monitor": self._update_signal_monitor,
            "delete_signal_monitor": self._delete_signal_monitor,
            "list_contact_lists": self._list_contact_lists,
            "create_contact_list": self._create_contact_list,
            "update_contact_list": self._update_contact_list,
            "delete_contact_list": self._delete_contact_list,
            "get_contacts": self._get_contacts,
            "get_credits": self._get_credits,
            "get_usage_summary": self._get_usage_summary,
            "get_team_usage_summary": self._get_team_usage_summary,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Finder handlers
    # ------------------------------------------------------------------
    async def _find_email_from_name(self, c: FindymailFindEmailFromNameConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/search/name",
            json_body={"name": c.name, "domain": c.domain},
            action_name="find_email_from_name",
        )

    async def _find_emails_from_domain(self, c: FindymailFindEmailsFromDomainConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/search/domain",
            json_body={
                "domain": c.domain,
                "roles": _comma_list(c.roles),
                "webhook_url": c.webhook_url,
            },
            action_name="find_emails_from_domain",
        )

    async def _find_from_business_profile(self, c: FindymailFindFromBusinessProfileConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/search/business-profile",
            json_body={"linkedin_url": c.linkedin_url},
            action_name="find_from_business_profile",
        )

    async def _reverse_email(self, c: FindymailReverseEmailConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/search/reverse-email",
            json_body={"email": c.email, "with_profile": c.with_profile == "true"},
            action_name="reverse_email",
        )

    async def _find_phone(self, c: FindymailFindPhoneConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/search/phone",
            json_body={"linkedin_url": c.linkedin_url},
            action_name="find_phone",
        )

    async def _get_company(self, c: FindymailGetCompanyConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/search/company",
            json_body={"domain": c.domain, "linkedin_url": c.linkedin_url, "name": c.name},
            action_name="get_company",
        )

    async def _find_employees(self, c: FindymailFindEmployeesConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "website": c.website,
            "job_titles": _comma_list(c.job_titles),
            "count": int(c.count) if c.count and str(c.count).isdigit() else None,
        }
        return await _findymail_request(
            api_key, "POST", "/api/search/employees", json_body=body,
            action_name="find_employees",
        )

    # ------------------------------------------------------------------
    # Verifier handler
    # ------------------------------------------------------------------
    async def _verify_email(self, c: FindymailVerifyEmailConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/verify",
            json_body={"email": c.email},
            action_name="verify_email",
        )

    # ------------------------------------------------------------------
    # Intellimatch handlers
    # ------------------------------------------------------------------
    async def _intellimatch_search(self, c: FindymailIntellimatchSearchConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "query": c.query,
            "limit": _optional_int(c.limit),
            "config": {
                "find_contact": c.find_contact == "true",
                "find_email": c.find_email == "true",
                "find_phone": c.find_phone == "true",
                "target_job_titles": _comma_list(c.target_job_titles),
                "lead_list_id": _optional_int(c.lead_list_id),
                "mode": c.mode,
                "require_email": c.require_email == "true",
                "add_to_exclusion_list": c.add_to_exclusion_list == "true",
                "exclusion_list_id": _optional_int(c.exclusion_list_id),
                "exclusion_filter_list_ids": _optional_int_list(c.exclusion_filter_list_ids),
            },
        }
        return await _findymail_request(
            api_key, "POST", "/api/intellimatch/search", json_body=body,
            action_name="intellimatch_search",
        )

    async def _intellimatch_status(self, c: FindymailIntellimatchStatusConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/intellimatch/status",
            params={"hash": c.hash},
            action_name="intellimatch_status",
        )

    async def _intellimatch_data(self, c: FindymailIntellimatchDataConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/intellimatch/data",
            params={"hash": c.hash, "page": c.page, "per_page": c.per_page},
            action_name="intellimatch_data",
        )

    async def _list_exclusion_lists(self, c: FindymailListExclusionListsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "GET",
            "/api/intellimatch/exclusion-lists",
            action_name="list_exclusion_lists",
        )

    async def _create_exclusion_list(self, c: FindymailCreateExclusionListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "POST",
            "/api/intellimatch/exclusion-lists",
            json_body={"name": c.name, "is_shared": _optional_bool(c.is_shared)},
            action_name="create_exclusion_list",
        )

    async def _get_exclusion_list(self, c: FindymailGetExclusionListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "GET",
            f"/api/intellimatch/exclusion-lists/{c.excluded_domain_list_id}",
            action_name="get_exclusion_list",
        )

    async def _update_exclusion_list(self, c: FindymailUpdateExclusionListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "PUT",
            f"/api/intellimatch/exclusion-lists/{c.excluded_domain_list_id}",
            json_body={"name": c.name, "is_shared": _optional_bool(c.is_shared)},
            action_name="update_exclusion_list",
        )

    async def _delete_exclusion_list(self, c: FindymailDeleteExclusionListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "DELETE",
            f"/api/intellimatch/exclusion-lists/{c.excluded_domain_list_id}",
            action_name="delete_exclusion_list",
        )

    async def _list_excluded_domains(self, c: FindymailListExcludedDomainsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "GET",
            "/api/intellimatch/domains",
            params={
                "query": c.query,
                "list_id": _optional_int(c.excluded_domain_list_id),
                "per_page": _optional_int(c.per_page),
                "page": _optional_int(c.page),
            },
            action_name="list_excluded_domains",
        )

    async def _add_excluded_domains(self, c: FindymailAddExcludedDomainsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "POST",
            "/api/intellimatch/domains",
            json_body={
                "domains": _comma_list(c.domains),
                "list_id": _optional_int(c.excluded_domain_list_id),
            },
            action_name="add_excluded_domains",
        )

    async def _remove_excluded_domains(self, c: FindymailRemoveExcludedDomainsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "DELETE",
            "/api/intellimatch/domains",
            json_body={"ids": _optional_int_list(c.ids)},
            action_name="remove_excluded_domains",
        )

    # ------------------------------------------------------------------
    # Discovery handlers
    # ------------------------------------------------------------------
    async def _lookalike_search(self, c: FindymailLookalikeSearchConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "domains": _comma_list(c.domains),
            "limit": _optional_int(c.limit),
        }
        return await _findymail_request(
            api_key, "POST", "/api/lookalike/search", json_body=body,
            action_name="lookalike_search",
        )

    async def _technologies_lookup(self, c: FindymailTechnologiesLookupConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/technologies",
            json_body={"domain": c.domain},
            action_name="technologies_lookup",
        )

    async def _technologies_search(self, c: FindymailTechnologiesSearchConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/technologies/search",
            params={"q": c.query},
            action_name="technologies_search",
        )

    # ------------------------------------------------------------------
    # Signals handlers
    # ------------------------------------------------------------------
    async def _list_signals(self, c: FindymailListSignalsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/signals",
            params={"page": c.page, "per_page": c.per_page},
            action_name="list_signals",
        )

    async def _get_signal(self, c: FindymailGetSignalConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", f"/api/signals/{c.signal_id}",
            action_name="get_signal",
        )

    async def _list_signal_monitors(self, c: FindymailListSignalMonitorsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/signals/monitors",
            params={"ownership": c.ownership},
            action_name="list_signal_monitors",
        )

    async def _create_signal_monitor(self, c: FindymailCreateSignalMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/signals/monitors",
            json_body=_build_signal_monitor_payload(c, include_signal_type=True),
            action_name="create_signal_monitor",
        )

    async def _update_signal_monitor(self, c: FindymailUpdateSignalMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "PATCH", f"/api/signals/monitors/{c.monitor_id}",
            json_body=_build_signal_monitor_payload(c, include_signal_type=False),
            action_name="update_signal_monitor",
        )

    async def _delete_signal_monitor(self, c: FindymailDeleteSignalMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "DELETE", f"/api/signals/monitors/{c.monitor_id}",
            action_name="delete_signal_monitor",
        )

    # ------------------------------------------------------------------
    # Lists handlers
    # ------------------------------------------------------------------
    async def _list_contact_lists(self, c: FindymailListContactListsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/lists", action_name="list_contact_lists"
        )

    async def _create_contact_list(self, c: FindymailCreateContactListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "POST", "/api/lists",
            json_body={"name": c.name},
            action_name="create_contact_list",
        )

    async def _update_contact_list(self, c: FindymailUpdateContactListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "PUT", f"/api/lists/{c.list_id}",
            json_body={"name": c.name, "isShared": _optional_bool(c.is_shared)},
            action_name="update_contact_list",
        )

    async def _delete_contact_list(self, c: FindymailDeleteContactListConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "DELETE", f"/api/lists/{c.list_id}",
            action_name="delete_contact_list",
        )

    async def _get_contacts(self, c: FindymailGetContactsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", f"/api/contacts/get/{c.list_id}",
            action_name="get_contacts",
        )

    # ------------------------------------------------------------------
    # Credits handlers
    # ------------------------------------------------------------------
    async def _get_credits(self, c: FindymailGetCreditsConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/credits", action_name="get_credits"
        )

    async def _get_usage_summary(self, c: FindymailGetUsageSummaryConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key, "GET", "/api/credits/report/summary", action_name="get_usage_summary"
        )

    async def _get_team_usage_summary(self, c: FindymailGetTeamUsageSummaryConfig, api_key: str) -> Dict[str, Any]:
        return await _findymail_request(
            api_key,
            "GET",
            "/api/credits/report/team-summary",
            params={"from": c.from_date, "to": c.to_date},
            action_name="get_team_usage_summary",
        )
