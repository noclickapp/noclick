"""
Apollo.io REST API automation node.

Provides workflow integration with Apollo.io for operations including:
- Enrichment: People and organization data enrichment (single and bulk)
- Search: Find prospects by demographics, search organizations, news articles
- Accounts: Create, update, bulk operations, search, view accounts
- Contacts: Create, update, bulk operations, search, view contacts
- Deals: Create, list, view, update deals
- Sequences: Search sequences, add contacts, update status, email stats
- Tasks: Create and search tasks
- Calls: Create, search, and update call records
- Miscellaneous: Lists, custom fields, users, email accounts, usage stats

Authentication: API Key (Bearer token)
API Base URL: https://api.apollo.io/api/v1
Documentation: https://docs.apollo.io/
Rate Limit: Varies by plan
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.crm_records import APOLLO_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

APOLLO_API_BASE = "https://api.apollo.io/api/v1"

# ============================================================================
# Credential Schema
# ============================================================================


class ApolloAPIKeyCredential(BaseModel):
    """
    API Key credential for Apollo.io.

    Get your API key at: https://developer.apollo.io/keys#/keys
    """

    credential_type: Literal["apollo_api_key"] = Field(
        "apollo_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Apollo.io API Key",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={"x-credential-url": "https://developer.apollo.io/keys#/keys"})


class ApolloOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Apollo.io."""

    credential_type: Literal["apollo_oauth"] = Field(
        "apollo_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    expires_at: Optional[str] = Field(None, description="ISO 8601 expiry timestamp")
    scope: str = Field("", description="Granted OAuth scopes")
    email: Optional[str] = Field(None, description="Connected Apollo account email")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "apollo",
        "x-oauth-scopes": [
            "read_user_profile",
            "people_match", "people_bulk_match",
            "organizations_enrich", "organizations_bulk_enrich", "organizations_search", "organization_read",
            "mixed_people_api_search", "mixed_companies_search",
            "contacts_search", "contact_read", "contact_write", "contact_update",
            "contacts_bulk_create", "contacts_bulk_update",
            "contact_stages_list", "contact_stages_update", "contact_owners_update",
            "account_read", "account_write", "account_update", "accounts_search",
            "account_bulk_create", "account_stages_list", "account_stages_update", "account_owners_update",
            "opportunity_read", "opportunity_write", "opportunity_update", "opportunities_list", "opportunity_stages_list",
            "emailer_campaigns_search", "emailer_campaigns_create", "emailer_campaigns_update",
            "emailer_campaigns_add_contact_ids", "emailer_campaigns_remove_or_stop_contact_ids",
            "emailer_schedules_list", "emailer_messages_search",
            "tasks_create", "tasks_list",
            "notes_list", "users_list", "tags_list",
            "custom_fields_list", "custom_field_write",
            "lists_create", "lists_update", "lists_add_entities", "lists_remove_entities",
            "organizations_job_posting", "organizations_news_articles",
            "person_read",
        ],
    })


ApolloCredential = Union[ApolloAPIKeyCredential, ApolloOAuthCredential]


# ============================================================================
# Enrichment Operation Configs
# ============================================================================


class ApolloPeopleEnrichmentConfig(BaseModel):
    """Enrich data for a single person"""

    operation: Literal["enrich_single_person"] = Field(
        "enrich_single_person",
        json_schema_extra={
            "const": "enrich_single_person",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Enrich Single Person",
        },
        title="Enrich Single Person",
    )
    first_name: Optional[str] = Field(
        None, title="First Name", description="Person's first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="Person's last name"
    )
    email: Optional[str] = Field(
        None, title="Email", description="Person's email address"
    )
    domain: Optional[str] = Field(
        None, title="Domain", description="Company domain (e.g., apollo.io)"
    )
    organization_name: Optional[str] = Field(
        None, title="Organization Name", description="Name of the person's organization"
    )
    linkedin_url: Optional[str] = Field(
        None, title="LinkedIn URL", description="Person's LinkedIn profile URL"
    )
    reveal_personal_emails: Optional[bool] = Field(
        False,
        title="Reveal Personal Emails",
        description="Include personal email addresses in results",
    )
    reveal_phone_number: Optional[bool] = Field(
        False,
        title="Reveal Phone Number",
        description="Include phone numbers in results",
    )


class ApolloBulkPeopleEnrichmentConfig(BaseModel):
    """Enrich data for up to 10 people at once"""

    operation: Literal["enrich_multiple_people"] = Field(
        "enrich_multiple_people",
        json_schema_extra={
            "const": "enrich_multiple_people",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Enrich Multiple People",
        },
        title="Enrich Multiple People",
    )
    details: List[Dict[str, Any]] = Field(
        ...,
        title="People Details",
        description="Array of people to enrich (max 10). Each object can have: first_name, last_name, email, domain, organization_name, linkedin_url",
    )
    reveal_personal_emails: Optional[bool] = Field(
        False,
        title="Reveal Personal Emails",
        description="Include personal email addresses in results",
    )
    reveal_phone_number: Optional[bool] = Field(
        False,
        title="Reveal Phone Number",
        description="Include phone numbers in results",
    )


class ApolloOrganizationEnrichmentConfig(BaseModel):
    """Enrich data for a single organization"""

    operation: Literal["enrich_single_organization"] = Field(
        "enrich_single_organization",
        json_schema_extra={
            "const": "enrich_single_organization",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Enrich Single Organization",
        },
        title="Enrich Single Organization",
    )
    domain: str = Field(
        ..., title="Domain", description="Organization's domain (e.g., apollo.io)"
    )


class ApolloBulkOrganizationEnrichmentConfig(BaseModel):
    """Enrich data for up to 10 organizations at once"""

    operation: Literal["enrich_multiple_organizations"] = Field(
        "enrich_multiple_organizations",
        json_schema_extra={
            "const": "enrich_multiple_organizations",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Enrich Multiple Organizations",
        },
        title="Enrich Multiple Organizations",
    )
    domains: List[str] = Field(
        ...,
        title="Domains",
        description="Array of organization domains to enrich (max 10)",
    )


# ============================================================================
# Search Operation Configs
# ============================================================================


class ApolloPeopleSearchConfig(BaseModel):
    """Search Apollo's database for prospects"""

    operation: Literal["search_people_in_apollo"] = Field(
        "search_people_in_apollo",
        json_schema_extra={
            "const": "search_people_in_apollo",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Search People in Apollo",
        },
        title="Search People in Apollo",
    )
    q_keywords: Optional[str] = Field(
        None, title="Keywords", description="Keywords to search for in person profiles"
    )
    person_titles: Optional[List[str]] = Field(
        None,
        title="Job Titles",
        description="Filter by job titles (e.g., ['CEO', 'CTO'])",
    )
    person_seniorities: Optional[List[str]] = Field(
        None,
        title="Seniorities",
        description="Filter by seniority levels",
        json_schema_extra={
            "items": {
                "enum": [
                    "owner",
                    "founder",
                    "c_suite",
                    "partner",
                    "vp",
                    "head",
                    "director",
                    "manager",
                    "senior",
                    "entry",
                    "intern",
                ]
            }
        },
    )
    person_locations: Optional[List[str]] = Field(
        None,
        title="Locations",
        description="Filter by locations (e.g., ['San Francisco, CA', 'New York, NY'])",
    )
    organization_domains: Optional[List[str]] = Field(
        None, title="Organization Domains", description="Filter by company domains"
    )
    organization_num_employees_ranges: Optional[List[str]] = Field(
        None,
        title="Employee Count Ranges",
        description="Filter by employee count ranges",
        json_schema_extra={
            "items": {
                "enum": [
                    "1,10",
                    "11,20",
                    "21,50",
                    "51,100",
                    "101,200",
                    "201,500",
                    "501,1000",
                    "1001,2000",
                    "2001,5000",
                    "5001,10000",
                    "10001,",
                ]
            }
        },
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number (1-indexed)", ge=1
    )
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page (max 100)", ge=1, le=100
    )


class ApolloOrganizationSearchConfig(BaseModel):
    """Search for organizations in Apollo's database"""

    operation: Literal["search_organizations_in_apollo"] = Field(
        "search_organizations_in_apollo",
        json_schema_extra={
            "const": "search_organizations_in_apollo",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Search Organizations in Apollo",
        },
        title="Search Organizations in Apollo",
    )
    q_organization_keyword_tags: Optional[List[str]] = Field(
        None,
        title="Keyword Tags",
        description="Organization keyword tags to search for",
    )
    organization_locations: Optional[List[str]] = Field(
        None, title="Locations", description="Filter by organization locations"
    )
    organization_num_employees_ranges: Optional[List[str]] = Field(
        None,
        title="Employee Count Ranges",
        description="Filter by employee count ranges",
        json_schema_extra={
            "items": {
                "enum": [
                    "1,10",
                    "11,20",
                    "21,50",
                    "51,100",
                    "101,200",
                    "201,500",
                    "501,1000",
                    "1001,2000",
                    "2001,5000",
                    "5001,10000",
                    "10001,",
                ]
            }
        },
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page (max 100)", ge=1, le=100
    )


class ApolloOrganizationJobPostingsConfig(BaseModel):
    """Get job postings for an organization"""

    operation: Literal["get_organization_job_postings"] = Field(
        "get_organization_job_postings",
        json_schema_extra={
            "const": "get_organization_job_postings",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Job Postings",
        },
        title="Get Organization Job Postings",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="Apollo organization ID"
    )


class ApolloGetOrganizationInfoConfig(BaseModel):
    """Get complete information for an organization"""

    operation: Literal["get_organization_details"] = Field(
        "get_organization_details",
        json_schema_extra={
            "const": "get_organization_details",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Details",
        },
        title="Get Organization Details",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="Apollo organization ID"
    )


class ApolloSearchNewsArticlesConfig(BaseModel):
    """Search for news articles about organizations"""

    operation: Literal["search_organization_news_articles"] = Field(
        "search_organization_news_articles",
        json_schema_extra={
            "const": "search_organization_news_articles",
            "ui:hidden": True,
            "x-category": "News",
            "x-is-trigger": False,
            "x-display-name": "Search Organization News Articles",
        },
        title="Search Organization News Articles",
    )
    organization_ids: Optional[List[str]] = Field(
        None, title="Organization IDs", description="Filter by organization IDs"
    )
    q_keywords: Optional[str] = Field(
        None, title="Keywords", description="Keywords to search for in news articles"
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page (max 100)", ge=1, le=100
    )


# ============================================================================
# Account Operation Configs
# ============================================================================


class ApolloCreateAccountConfig(BaseModel):
    """Create a new account in Apollo"""

    operation: Literal["create_account"] = Field(
        "create_account",
        json_schema_extra={
            "const": "create_account",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create Account",
        },
        title="Create Account",
    )
    name: str = Field(
        ..., title="Account Name", description="Name of the account/company"
    )
    domain: Optional[str] = Field(None, title="Domain", description="Company domain")
    phone_number: Optional[str] = Field(
        None, title="Phone Number", description="Company phone number"
    )
    raw_address: Optional[str] = Field(
        None, title="Address", description="Company address"
    )
    owner_id: Optional[str] = Field(
        None, title="Owner ID", description="User ID of the account owner",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


class ApolloUpdateAccountConfig(BaseModel):
    """Update an existing account"""

    operation: Literal["update_account_details"] = Field(
        "update_account_details",
        json_schema_extra={
            "const": "update_account_details",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Account Details",
        },
        title="Update Account Details",
    )
    account_id: str = Field(
        ..., title="Account ID", description="ID of the account to update"
    )
    name: Optional[str] = Field(
        None, title="Account Name", description="New name for the account"
    )
    domain: Optional[str] = Field(None, title="Domain", description="New domain")
    phone_number: Optional[str] = Field(
        None, title="Phone Number", description="New phone number"
    )
    raw_address: Optional[str] = Field(None, title="Address", description="New address")
    owner_id: Optional[str] = Field(
        None, title="Owner ID", description="New owner user ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


class ApolloSearchAccountsConfig(BaseModel):
    """Search for accounts"""

    operation: Literal["search_accounts"] = Field(
        "search_accounts",
        json_schema_extra={
            "const": "search_accounts",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Search Accounts",
        },
        title="Search Accounts",
    )
    q_organization_name: Optional[str] = Field(
        None, title="Organization Name", description="Search by organization name"
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page", ge=1, le=100
    )


class ApolloViewAccountConfig(BaseModel):
    """View a single account"""

    operation: Literal["get_account_details"] = Field(
        "get_account_details",
        json_schema_extra={
            "const": "get_account_details",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account Details",
        },
        title="Get Account Details",
    )
    account_id: str = Field(
        ..., title="Account ID", description="ID of the account to view"
    )


class ApolloListAccountStagesConfig(BaseModel):
    """List all account stages"""

    operation: Literal["list_account_stages"] = Field(
        "list_account_stages",
        json_schema_extra={
            "const": "list_account_stages",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Account Stages",
        },
        title="List Account Stages",
    )


class ApolloBulkCreateAccountsConfig(BaseModel):
    """Create multiple accounts at once"""

    operation: Literal["create_multiple_accounts"] = Field(
        "create_multiple_accounts",
        json_schema_extra={
            "const": "create_multiple_accounts",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create Multiple Accounts",
        },
        title="Create Multiple Accounts",
    )
    accounts: List[Dict[str, Any]] = Field(
        ...,
        title="Accounts",
        description="Array of account objects to create. Each object can have: name, domain, phone_number, raw_address, owner_id",
    )


class ApolloBulkUpdateAccountsConfig(BaseModel):
    """Update multiple accounts at once"""

    operation: Literal["update_multiple_accounts"] = Field(
        "update_multiple_accounts",
        json_schema_extra={
            "const": "update_multiple_accounts",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Multiple Accounts",
        },
        title="Update Multiple Accounts",
    )
    accounts: List[Dict[str, Any]] = Field(
        ...,
        title="Accounts",
        description="Array of account objects with updates. Each object must include 'id' and fields to update",
    )


class ApolloUpdateAccountStagesConfig(BaseModel):
    """Update account stage for multiple accounts"""

    operation: Literal["update_account_stage_bulk"] = Field(
        "update_account_stage_bulk",
        json_schema_extra={
            "const": "update_account_stage_bulk",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Account Stage Bulk",
        },
        title="Update Account Stage Bulk",
    )
    account_ids: List[str] = Field(
        ..., title="Account IDs", description="IDs of accounts to update"
    )
    account_stage_id: str = Field(
        ..., title="Account Stage ID", description="New account stage ID to set",
        json_schema_extra={"x-dynamic-options": {"field_name": "account_stage_id", "placeholder": "Select stage...", "searchable": True, "allow_custom": True}},
    )


class ApolloUpdateAccountOwnersConfig(BaseModel):
    """Update owner for multiple accounts"""

    operation: Literal["update_account_ownership"] = Field(
        "update_account_ownership",
        json_schema_extra={
            "const": "update_account_ownership",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Account Ownership",
        },
        title="Update Account Ownership",
    )
    account_ids: List[str] = Field(
        ..., title="Account IDs", description="IDs of accounts to update"
    )
    owner_id: str = Field(
        ..., title="Owner ID", description="New owner user ID to assign",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


# ============================================================================
# Contact Operation Configs
# ============================================================================


class ApolloCreateContactConfig(BaseModel):
    """Create a new contact"""

    operation: Literal["create_contact"] = Field(
        "create_contact",
        json_schema_extra={
            "const": "create_contact",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Create Contact",
        },
        title="Create Contact",
    )
    first_name: str = Field(..., title="First Name", description="Contact's first name")
    last_name: str = Field(..., title="Last Name", description="Contact's last name")
    email: Optional[str] = Field(
        None, title="Email", description="Contact's email address"
    )
    title: Optional[str] = Field(
        None, title="Job Title", description="Contact's job title"
    )
    organization_name: Optional[str] = Field(
        None, title="Organization Name", description="Contact's company name"
    )
    account_id: Optional[str] = Field(
        None, title="Account ID", description="Link to existing account"
    )
    phone_numbers: Optional[List[Dict[str, str]]] = Field(
        None,
        title="Phone Numbers",
        description="Array of phone numbers [{raw_number: '...', type: 'mobile'}]",
    )
    owner_id: Optional[str] = Field(
        None, title="Owner ID", description="User ID of the contact owner",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )
    label_names: Optional[List[str]] = Field(
        None, title="Labels", description="Label names to apply to contact"
    )


class ApolloUpdateContactConfig(BaseModel):
    """Update an existing contact"""

    operation: Literal["update_contact_details"] = Field(
        "update_contact_details",
        json_schema_extra={
            "const": "update_contact_details",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Details",
        },
        title="Update Contact Details",
    )
    contact_id: str = Field(
        ..., title="Contact ID", description="ID of the contact to update"
    )
    first_name: Optional[str] = Field(
        None, title="First Name", description="New first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="New last name"
    )
    email: Optional[str] = Field(None, title="Email", description="New email address")
    title: Optional[str] = Field(None, title="Job Title", description="New job title")
    organization_name: Optional[str] = Field(
        None, title="Organization Name", description="New company name"
    )
    account_id: Optional[str] = Field(
        None, title="Account ID", description="Link to account"
    )
    owner_id: Optional[str] = Field(
        None, title="Owner ID", description="New owner user ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


class ApolloSearchContactsConfig(BaseModel):
    """Search for contacts"""

    operation: Literal["search_contacts"] = Field(
        "search_contacts",
        json_schema_extra={
            "const": "search_contacts",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Search Contacts",
        },
        title="Search Contacts",
    )
    q_keywords: Optional[str] = Field(
        None, title="Keywords", description="Keywords to search for"
    )
    contact_stage_ids: Optional[List[str]] = Field(
        None, title="Stage IDs", description="Filter by contact stage IDs",
        json_schema_extra={"x-dynamic-options": {"field_name": "contact_stage_ids", "placeholder": "Select stages...", "searchable": True, "allow_custom": True}},
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page", ge=1, le=100
    )


class ApolloViewContactConfig(BaseModel):
    """View a single contact"""

    operation: Literal["get_contact_details"] = Field(
        "get_contact_details",
        json_schema_extra={
            "const": "get_contact_details",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Details",
        },
        title="Get Contact Details",
    )
    contact_id: str = Field(
        ..., title="Contact ID", description="ID of the contact to view"
    )


class ApolloListContactStagesConfig(BaseModel):
    """List all contact stages"""

    operation: Literal["list_contact_stages"] = Field(
        "list_contact_stages",
        json_schema_extra={
            "const": "list_contact_stages",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "List Contact Stages",
        },
        title="List Contact Stages",
    )


class ApolloBulkCreateContactsConfig(BaseModel):
    """Create multiple contacts at once"""

    operation: Literal["create_multiple_contacts"] = Field(
        "create_multiple_contacts",
        json_schema_extra={
            "const": "create_multiple_contacts",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Create Multiple Contacts",
        },
        title="Create Multiple Contacts",
    )
    contacts: List[Dict[str, Any]] = Field(
        ...,
        title="Contacts",
        description="Array of contact objects to create. Each object can have: first_name, last_name, email, title, organization_name, account_id, phone_numbers, owner_id, label_names",
    )
    run_dedupe: Optional[bool] = Field(
        False,
        title="Run Deduplication",
        description="Enable deduplication to update existing contacts instead of creating duplicates",
    )


class ApolloBulkUpdateContactsConfig(BaseModel):
    """Update multiple contacts at once"""

    operation: Literal["update_multiple_contacts"] = Field(
        "update_multiple_contacts",
        json_schema_extra={
            "const": "update_multiple_contacts",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Multiple Contacts",
        },
        title="Update Multiple Contacts",
    )
    contacts: List[Dict[str, Any]] = Field(
        ...,
        title="Contacts",
        description="Array of contact objects with updates. Each object must include 'id' and fields to update",
    )


class ApolloUpdateContactStagesConfig(BaseModel):
    """Update contact stage for multiple contacts"""

    operation: Literal["update_contact_stage_bulk"] = Field(
        "update_contact_stage_bulk",
        json_schema_extra={
            "const": "update_contact_stage_bulk",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Stage Bulk",
        },
        title="Update Contact Stage Bulk",
    )
    contact_ids: List[str] = Field(
        ..., title="Contact IDs", description="IDs of contacts to update"
    )
    contact_stage_id: str = Field(
        ..., title="Contact Stage ID", description="New contact stage ID to set",
        json_schema_extra={"x-dynamic-options": {"field_name": "contact_stage_id", "placeholder": "Select stage...", "searchable": True, "allow_custom": True}},
    )


class ApolloUpdateContactOwnersConfig(BaseModel):
    """Update owner for multiple contacts"""

    operation: Literal["update_contact_ownership"] = Field(
        "update_contact_ownership",
        json_schema_extra={
            "const": "update_contact_ownership",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Ownership",
        },
        title="Update Contact Ownership",
    )
    contact_ids: List[str] = Field(
        ..., title="Contact IDs", description="IDs of contacts to update"
    )
    owner_id: str = Field(
        ..., title="Owner ID", description="New owner user ID to assign",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


# ============================================================================
# Deal Operation Configs
# ============================================================================


class ApolloCreateDealConfig(BaseModel):
    """Create a new deal"""

    operation: Literal["create_deal"] = Field(
        "create_deal",
        json_schema_extra={
            "const": "create_deal",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Create Deal",
        },
        title="Create Deal",
    )
    name: str = Field(..., title="Deal Name", description="Name of the deal")
    deal_stage_id: str = Field(
        ..., title="Deal Stage ID", description="ID of the deal stage",
        json_schema_extra={"x-dynamic-options": {"field_name": "deal_stage_id", "placeholder": "Select deal stage...", "searchable": True, "allow_custom": True}},
    )
    amount: Optional[float] = Field(None, title="Amount", description="Deal value")
    closed_date: Optional[str] = Field(
        None, title="Close Date", description="Expected close date (ISO 8601)"
    )
    account_id: Optional[str] = Field(
        None, title="Account ID", description="Associated account ID"
    )
    contact_ids: Optional[List[str]] = Field(
        None, title="Contact IDs", description="Associated contact IDs"
    )
    owner_id: Optional[str] = Field(
        None, title="Owner ID", description="Deal owner user ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


class ApolloListDealsConfig(BaseModel):
    """List all deals"""

    operation: Literal["list_deals"] = Field(
        "list_deals",
        json_schema_extra={
            "const": "list_deals",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "List Deals",
        },
        title="List Deals",
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page", ge=1, le=100
    )


class ApolloViewDealConfig(BaseModel):
    """View a single deal"""

    operation: Literal["get_deal_details"] = Field(
        "get_deal_details",
        json_schema_extra={
            "const": "get_deal_details",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Get Deal Details",
        },
        title="Get Deal Details",
    )
    deal_id: str = Field(..., title="Deal ID", description="ID of the deal to view")


class ApolloUpdateDealConfig(BaseModel):
    """Update an existing deal"""

    operation: Literal["update_deal_details"] = Field(
        "update_deal_details",
        json_schema_extra={
            "const": "update_deal_details",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Update Deal Details",
        },
        title="Update Deal Details",
    )
    deal_id: str = Field(..., title="Deal ID", description="ID of the deal to update")
    name: Optional[str] = Field(None, title="Deal Name", description="New deal name")
    deal_stage_id: Optional[str] = Field(
        None, title="Deal Stage ID", description="New deal stage ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "deal_stage_id", "placeholder": "Select deal stage...", "searchable": True, "allow_custom": True}},
    )
    amount: Optional[float] = Field(None, title="Amount", description="New deal value")
    closed_date: Optional[str] = Field(
        None, title="Close Date", description="New expected close date"
    )
    owner_id: Optional[str] = Field(
        None, title="Owner ID", description="New owner user ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select owner...", "searchable": True, "allow_custom": True}},
    )


class ApolloListDealStagesConfig(BaseModel):
    """List all deal stages"""

    operation: Literal["list_deal_stages"] = Field(
        "list_deal_stages",
        json_schema_extra={
            "const": "list_deal_stages",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "List Deal Stages",
        },
        title="List Deal Stages",
    )


# ============================================================================
# Sequence Operation Configs
# ============================================================================


class ApolloSearchSequencesConfig(BaseModel):
    """Search for sequences"""

    operation: Literal["search_outreach_sequences"] = Field(
        "search_outreach_sequences",
        json_schema_extra={
            "const": "search_outreach_sequences",
            "ui:hidden": True,
            "x-category": "Sequence and Email",
            "x-is-trigger": False,
            "x-display-name": "Search Outreach Sequences",
        },
        title="Search Outreach Sequences",
    )
    q_name: Optional[str] = Field(
        None, title="Name", description="Search by sequence name"
    )


class ApolloAddContactsToSequenceConfig(BaseModel):
    """Add contacts to a sequence"""

    operation: Literal["add_contacts_to_outreach_sequence"] = Field(
        "add_contacts_to_outreach_sequence",
        json_schema_extra={
            "const": "add_contacts_to_outreach_sequence",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Add Contacts to Outreach Sequence",
        },
        title="Add Contacts to Outreach Sequence",
    )
    sequence_id: str = Field(
        ..., title="Sequence ID", description="ID of the sequence",
        json_schema_extra={"x-dynamic-options": {"field_name": "sequence_id", "placeholder": "Select sequence...", "searchable": True, "allow_custom": True}},
    )
    contact_ids: List[str] = Field(
        ..., title="Contact IDs", description="IDs of contacts to add"
    )
    emailer_campaign_id: Optional[str] = Field(
        None,
        title="Emailer Campaign ID",
        description="ID of the emailer campaign (if using email)",
        json_schema_extra={"x-dynamic-options": {"field_name": "sequence_id", "placeholder": "Select sequence...", "searchable": True, "allow_custom": True}},
    )
    send_email_from_email_account_id: Optional[str] = Field(
        None,
        title="Email Account ID",
        description="ID of the email account to send from",
        json_schema_extra={"x-dynamic-options": {"field_name": "email_account_id", "placeholder": "Select email account...", "searchable": True, "allow_custom": True}},
    )


class ApolloUpdateContactSequenceStatusConfig(BaseModel):
    """Update a contact's status in a sequence"""

    operation: Literal["update_contact_sequence_status"] = Field(
        "update_contact_sequence_status",
        json_schema_extra={
            "const": "update_contact_sequence_status",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Sequence Status",
        },
        title="Update Contact Sequence Status",
    )
    contact_id: str = Field(..., title="Contact ID", description="ID of the contact")
    sequence_id: str = Field(
        ..., title="Sequence ID", description="ID of the sequence",
        json_schema_extra={"x-dynamic-options": {"field_name": "sequence_id", "placeholder": "Select sequence...", "searchable": True, "allow_custom": True}},
    )
    status: str = Field(
        ...,
        title="Status",
        description="New status for the contact",
        json_schema_extra={"enum": ["active", "paused", "finished", "bounced"]},
    )


class ApolloSearchEmailsConfig(BaseModel):
    """Search for outreach emails in sequences"""

    operation: Literal["search_sequence_emails"] = Field(
        "search_sequence_emails",
        json_schema_extra={
            "const": "search_sequence_emails",
            "ui:hidden": True,
            "x-category": "Sequence and Email",
            "x-is-trigger": False,
            "x-display-name": "Search Sequence Emails",
        },
        title="Search Sequence Emails",
    )
    emailer_campaign_id: Optional[str] = Field(
        None, title="Sequence ID", description="Filter by sequence/emailer campaign ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "sequence_id", "placeholder": "Select sequence...", "searchable": True, "allow_custom": True}},
    )
    contact_id: Optional[str] = Field(
        None, title="Contact ID", description="Filter by contact ID"
    )
    email_status: Optional[str] = Field(
        None,
        title="Email Status",
        description="Filter by email status",
        json_schema_extra={
            "enum": ["sent", "opened", "clicked", "replied", "bounced", "scheduled"]
        },
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page", ge=1, le=100
    )


class ApolloGetEmailStatsConfig(BaseModel):
    """Get email statistics for a sequence"""

    operation: Literal["get_sequence_email_statistics"] = Field(
        "get_sequence_email_statistics",
        json_schema_extra={
            "const": "get_sequence_email_statistics",
            "ui:hidden": True,
            "x-category": "Sequence and Email",
            "x-is-trigger": False,
            "x-display-name": "Get Sequence Email Statistics",
        },
        title="Get Sequence Email Statistics",
    )
    sequence_id: str = Field(
        ..., title="Sequence ID", description="ID of the sequence to get stats for",
        json_schema_extra={"x-dynamic-options": {"field_name": "sequence_id", "placeholder": "Select sequence...", "searchable": True, "allow_custom": True}},
    )


# ============================================================================
# Task Operation Configs
# ============================================================================


class ApolloCreateTaskConfig(BaseModel):
    """Create a new task"""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
        title="Create Task",
    )
    contact_id: Optional[str] = Field(
        None, title="Contact ID", description="Associated contact ID"
    )
    account_id: Optional[str] = Field(
        None, title="Account ID", description="Associated account ID"
    )
    user_id: Optional[str] = Field(
        None, title="Assigned User ID", description="User to assign the task to",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select user...", "searchable": True, "allow_custom": True}},
    )
    due_at: Optional[str] = Field(
        None, title="Due Date", description="Task due date (ISO 8601)"
    )
    priority: Optional[str] = Field(
        "normal",
        title="Priority",
        description="Task priority",
        json_schema_extra={"enum": ["high", "normal", "low"]},
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Task description/notes",
        json_schema_extra={"ui:widget": "textarea"},
    )
    type: Optional[str] = Field(
        "action_item",
        title="Type",
        description="Task type",
        json_schema_extra={
            "enum": ["action_item", "call", "email", "linkedin_interact"]
        },
    )


class ApolloSearchTasksConfig(BaseModel):
    """Search for tasks"""

    operation: Literal["search_tasks"] = Field(
        "search_tasks",
        json_schema_extra={
            "const": "search_tasks",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Tasks",
        },
        title="Search Tasks",
    )
    user_id: Optional[str] = Field(
        None, title="User ID", description="Filter by assigned user",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select user...", "searchable": True, "allow_custom": True}},
    )
    contact_id: Optional[str] = Field(
        None, title="Contact ID", description="Filter by associated contact"
    )
    open_factor_id: Optional[str] = Field(
        None, title="Open Factor ID", description="Filter by open factor"
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page", ge=1, le=100
    )


# ============================================================================
# Call Operation Configs
# ============================================================================


class ApolloCreateCallRecordConfig(BaseModel):
    """Create a call record"""

    operation: Literal["create_call_activity_record"] = Field(
        "create_call_activity_record",
        json_schema_extra={
            "const": "create_call_activity_record",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Call Activity Record",
        },
        title="Create Call Activity Record",
    )
    contact_id: str = Field(
        ..., title="Contact ID", description="ID of the contact the call was with"
    )
    user_id: Optional[str] = Field(
        None, title="User ID", description="ID of the user who made the call",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select user...", "searchable": True, "allow_custom": True}},
    )
    phone_number: Optional[str] = Field(
        None, title="Phone Number", description="Phone number called"
    )
    duration: Optional[int] = Field(
        None, title="Duration (seconds)", description="Call duration in seconds"
    )
    outcome: Optional[str] = Field(
        None,
        title="Outcome",
        description="Call outcome",
        json_schema_extra={
            "enum": ["connected", "no_answer", "voicemail", "wrong_number", "busy"]
        },
    )
    direction: Optional[str] = Field(
        "outbound",
        title="Direction",
        description="Call direction",
        json_schema_extra={"enum": ["inbound", "outbound"]},
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Notes about the call",
        json_schema_extra={"ui:widget": "textarea"},
    )
    called_at: Optional[str] = Field(
        None, title="Called At", description="When the call occurred (ISO 8601)"
    )


class ApolloSearchCallsConfig(BaseModel):
    """Search for call records"""

    operation: Literal["search_call_records"] = Field(
        "search_call_records",
        json_schema_extra={
            "const": "search_call_records",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Call Records",
        },
        title="Search Call Records",
    )
    contact_id: Optional[str] = Field(
        None, title="Contact ID", description="Filter by contact ID"
    )
    user_id: Optional[str] = Field(
        None, title="User ID", description="Filter by user ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "owner_id", "placeholder": "Select user...", "searchable": True, "allow_custom": True}},
    )
    outcome: Optional[str] = Field(
        None,
        title="Outcome",
        description="Filter by outcome",
        json_schema_extra={
            "enum": ["connected", "no_answer", "voicemail", "wrong_number", "busy"]
        },
    )
    page: Optional[int] = Field(1, title="Page", description="Page number", ge=1)
    per_page: Optional[int] = Field(
        25, title="Per Page", description="Results per page", ge=1, le=100
    )


class ApolloUpdateCallRecordConfig(BaseModel):
    """Update a call record"""

    operation: Literal["update_call_record"] = Field(
        "update_call_record",
        json_schema_extra={
            "const": "update_call_record",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Update Call Record",
        },
        title="Update Call Record",
    )
    call_id: str = Field(
        ..., title="Call ID", description="ID of the call record to update"
    )
    duration: Optional[int] = Field(
        None, title="Duration (seconds)", description="New call duration in seconds"
    )
    outcome: Optional[str] = Field(
        None,
        title="Outcome",
        description="New call outcome",
        json_schema_extra={
            "enum": ["connected", "no_answer", "voicemail", "wrong_number", "busy"]
        },
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="New notes about the call",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# User/Utility Operation Configs
# ============================================================================


class ApolloGetUsersConfig(BaseModel):
    """Get list of users in the organization"""

    operation: Literal["get_organization_users"] = Field(
        "get_organization_users",
        json_schema_extra={
            "const": "get_organization_users",
            "ui:hidden": True,
            "x-category": "Workspace Configuration",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Users",
        },
        title="Get Organization Users",
    )


class ApolloGetEmailAccountsConfig(BaseModel):
    """Get list of email accounts"""

    operation: Literal["get_email_account_list"] = Field(
        "get_email_account_list",
        json_schema_extra={
            "const": "get_email_account_list",
            "ui:hidden": True,
            "x-category": "Sequence and Email",
            "x-is-trigger": False,
            "x-display-name": "Get Email Account List",
        },
        title="Get Email Account List",
    )


class ApolloGetUsageStatsConfig(BaseModel):
    """Get API usage statistics and rate limits"""

    operation: Literal["get_api_usage_and_limits"] = Field(
        "get_api_usage_and_limits",
        json_schema_extra={
            "const": "get_api_usage_and_limits",
            "ui:hidden": True,
            "x-category": "Workspace Configuration",
            "x-is-trigger": False,
            "x-display-name": "Get Api Usage and Limits",
        },
        title="Get Api Usage and Limits",
    )


class ApolloGetListsConfig(BaseModel):
    """Get all lists in the organization"""

    operation: Literal["get_organization_lists"] = Field(
        "get_organization_lists",
        json_schema_extra={
            "const": "get_organization_lists",
            "ui:hidden": True,
            "x-category": "Workspace Configuration",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Lists",
        },
        title="Get Organization Lists",
    )


class ApolloGetCustomFieldsConfig(BaseModel):
    """Get all custom fields in the organization"""

    operation: Literal["get_organization_custom_fields"] = Field(
        "get_organization_custom_fields",
        json_schema_extra={
            "const": "get_organization_custom_fields",
            "ui:hidden": True,
            "x-category": "Workspace Configuration",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Custom Fields",
        },
        title="Get Organization Custom Fields",
    )
    field_type: Optional[str] = Field(
        None,
        title="Field Type",
        description="Filter by field type",
        json_schema_extra={"enum": ["contact", "account", "opportunity"]},
    )


class ApolloCreateCustomFieldConfig(BaseModel):
    """Create a custom field"""

    operation: Literal["create_custom_field"] = Field(
        "create_custom_field",
        json_schema_extra={
            "const": "create_custom_field",
            "ui:hidden": True,
            "x-category": "Workspace Configuration",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    name: str = Field(..., title="Field Name", description="Name of the custom field")
    field_type: str = Field(
        ...,
        title="Field Type",
        description="Type of entity this field applies to",
        json_schema_extra={"enum": ["contact", "account", "opportunity"]},
    )
    widget_type: Optional[str] = Field(
        "text",
        title="Widget Type",
        description="Input widget type for the field",
        json_schema_extra={
            "enum": ["text", "textarea", "number", "date", "dropdown", "checkbox"]
        },
    )
    options: Optional[List[str]] = Field(
        None, title="Options", description="Options for dropdown fields"
    )


# ============================================================================
# Discriminated Union
# ============================================================================

ApolloConfig = Annotated[
    Union[
        # Enrichment operations (4)
        ApolloPeopleEnrichmentConfig,
        ApolloBulkPeopleEnrichmentConfig,
        ApolloOrganizationEnrichmentConfig,
        ApolloBulkOrganizationEnrichmentConfig,
        # Search operations (5)
        ApolloPeopleSearchConfig,
        ApolloOrganizationSearchConfig,
        ApolloOrganizationJobPostingsConfig,
        ApolloGetOrganizationInfoConfig,
        ApolloSearchNewsArticlesConfig,
        # Account operations (9)
        ApolloCreateAccountConfig,
        ApolloUpdateAccountConfig,
        ApolloSearchAccountsConfig,
        ApolloViewAccountConfig,
        ApolloListAccountStagesConfig,
        ApolloBulkCreateAccountsConfig,
        ApolloBulkUpdateAccountsConfig,
        ApolloUpdateAccountStagesConfig,
        ApolloUpdateAccountOwnersConfig,
        # Contact operations (9)
        ApolloCreateContactConfig,
        ApolloUpdateContactConfig,
        ApolloSearchContactsConfig,
        ApolloViewContactConfig,
        ApolloListContactStagesConfig,
        ApolloBulkCreateContactsConfig,
        ApolloBulkUpdateContactsConfig,
        ApolloUpdateContactStagesConfig,
        ApolloUpdateContactOwnersConfig,
        # Deal operations (5)
        ApolloCreateDealConfig,
        ApolloListDealsConfig,
        ApolloViewDealConfig,
        ApolloUpdateDealConfig,
        ApolloListDealStagesConfig,
        # Sequence operations (5)
        ApolloSearchSequencesConfig,
        ApolloAddContactsToSequenceConfig,
        ApolloUpdateContactSequenceStatusConfig,
        ApolloSearchEmailsConfig,
        ApolloGetEmailStatsConfig,
        # Task operations (2)
        ApolloCreateTaskConfig,
        ApolloSearchTasksConfig,
        # Call operations (3)
        ApolloCreateCallRecordConfig,
        ApolloSearchCallsConfig,
        ApolloUpdateCallRecordConfig,
        # User/Utility operations (6)
        ApolloGetUsersConfig,
        ApolloGetEmailAccountsConfig,
        ApolloGetUsageStatsConfig,
        ApolloGetListsConfig,
        ApolloGetCustomFieldsConfig,
        ApolloCreateCustomFieldConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class ApolloNodeConfig(NodeConfig[ApolloConfig, ApolloCredential]):
    """Full configuration for Apollo node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class ApolloNode(WorkflowNode):
    """
    Apollo.io automation node.

    Executes Apollo.io API operations for workflow automation.
    Supports 48 operations across enrichment, search, accounts, contacts,
    deals, sequences, tasks, calls, and utility functions.

    Authentication: Supports both API Key and OAuth 2.0 credentials.
    """

    edit_examples = [
        "Enrich a list of emails with company info and job titles",
        "Search for prospects by job title and company in USA",
        'Create a new contact and add to "Q3 Outreach" sequence',
        'Bulk update contact status to "qualified" and set call date',
        "Search organizations by revenue and industry sectors",
        "Create a deal with forecast close date and probability",
        "Get email and call stats for a specific outreach sequence",
    ]

    scope_registry = APOLLO_SCOPES
    connection_evidence = ConnectionEvidence(
        field="sequence_id",
        noun="sequences",
    )
    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return ApolloNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "apollo_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.apollo_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token,
        )

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        """Dynamic dropdown options for owner/user, stages, sequences, and email accounts."""
        import httpx

        def _auth_headers(cred):
            if cred.get("credential_type") == "apollo_oauth":
                return {"Authorization": f"Bearer {cred['access_token']}", "Content-Type": "application/json"}
            api_key = cred.get("api_key", "")
            return {"X-Api-Key": api_key, "Content-Type": "application/json"}

        async def _get(endpoint, params=None):
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{APOLLO_API_BASE}{endpoint}", headers=_auth_headers(credential_data or {}), params=params)
                return r.json() if r.status_code == 200 else {}

        async def _post(endpoint, body=None):
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{APOLLO_API_BASE}{endpoint}", headers=_auth_headers(credential_data or {}), json=body or {})
                return r.json() if r.status_code == 200 else {}

        if field_name == "owner_id":
            data = await _get("/users/search", params={"per_page": "200"})
            users = data.get("users") or []
            options = []
            for u in users:
                uid = u.get("id")
                if not uid:
                    continue
                name = u.get("name", "")
                email = u.get("email", "")
                label = f"{name} ({email})" if name and email else name or email or str(uid)
                options.append({"label": label, "value": str(uid)})
            return {"options": options}

        if field_name == "contact_stage_id":
            data = await _get("/contact_stages")
            return {"options": [
                {"label": s.get("name", s.get("id")), "value": str(s["id"])}
                for s in (data.get("contact_stages") or []) if s.get("id")
            ]}

        if field_name == "account_stage_id":
            data = await _get("/account_stages")
            return {"options": [
                {"label": s.get("name", s.get("id")), "value": str(s["id"])}
                for s in (data.get("account_stages") or []) if s.get("id")
            ]}

        if field_name == "deal_stage_id":
            data = await _get("/opportunity_stages")
            return {"options": [
                {"label": s.get("name", s.get("id")), "value": str(s["id"])}
                for s in (data.get("opportunity_stages") or []) if s.get("id")
            ]}

        if field_name == "sequence_id":
            data = await _post("/emailer_campaigns/search", {"per_page": 200})
            return {"options": [
                {"label": s.get("name", str(s.get("id", ""))), "value": str(s["id"])}
                for s in (data.get("emailer_campaigns") or []) if s.get("id")
            ]}

        if field_name == "email_account_id":
            data = await _get("/email_accounts")
            return {"options": [
                {"label": a.get("email", str(a.get("id", ""))), "value": str(a["id"])}
                for a in (data.get("email_accounts") or []) if a.get("id")
            ]}

        return {"options": []}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, ApolloNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Apollo.io API Key.")

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Enrichment operations (4)
            "enrich_single_person": self._handle_people_enrichment,
            "enrich_multiple_people": self._handle_bulk_people_enrichment,
            "enrich_single_organization": self._handle_organization_enrichment,
            "enrich_multiple_organizations": self._handle_bulk_organization_enrichment,
            # Search operations (5)
            "search_people_in_apollo": self._handle_people_search,
            "search_organizations_in_apollo": self._handle_organization_search,
            "get_organization_job_postings": self._handle_organization_job_postings,
            "get_organization_details": self._handle_get_organization_info,
            "search_organization_news_articles": self._handle_search_news_articles,
            # Account operations (9)
            "create_account": self._handle_create_account,
            "update_account_details": self._handle_update_account,
            "search_accounts": self._handle_search_accounts,
            "get_account_details": self._handle_view_account,
            "list_account_stages": self._handle_list_account_stages,
            "create_multiple_accounts": self._handle_bulk_create_accounts,
            "update_multiple_accounts": self._handle_bulk_update_accounts,
            "update_account_stage_bulk": self._handle_update_account_stages,
            "update_account_ownership": self._handle_update_account_owners,
            # Contact operations (9)
            "create_contact": self._handle_create_contact,
            "update_contact_details": self._handle_update_contact,
            "search_contacts": self._handle_search_contacts,
            "get_contact_details": self._handle_view_contact,
            "list_contact_stages": self._handle_list_contact_stages,
            "create_multiple_contacts": self._handle_bulk_create_contacts,
            "update_multiple_contacts": self._handle_bulk_update_contacts,
            "update_contact_stage_bulk": self._handle_update_contact_stages,
            "update_contact_ownership": self._handle_update_contact_owners,
            # Deal operations (5)
            "create_deal": self._handle_create_deal,
            "list_deals": self._handle_list_deals,
            "get_deal_details": self._handle_view_deal,
            "update_deal_details": self._handle_update_deal,
            "list_deal_stages": self._handle_list_deal_stages,
            # Sequence operations (5)
            "search_outreach_sequences": self._handle_search_sequences,
            "add_contacts_to_outreach_sequence": self._handle_add_contacts_to_sequence,
            "update_contact_sequence_status": self._handle_update_contact_sequence_status,
            "search_sequence_emails": self._handle_search_emails,
            "get_sequence_email_statistics": self._handle_get_email_stats,
            # Task operations (2)
            "create_task": self._handle_create_task,
            "search_tasks": self._handle_search_tasks,
            # Call operations (3)
            "create_call_activity_record": self._handle_create_call_record,
            "search_call_records": self._handle_search_calls,
            "update_call_record": self._handle_update_call_record,
            # User/Utility operations (6)
            "get_organization_users": self._handle_get_users,
            "get_email_account_list": self._handle_get_email_accounts,
            "get_api_usage_and_limits": self._handle_get_usage_stats,
            "get_organization_lists": self._handle_get_lists,
            "get_organization_custom_fields": self._handle_get_custom_fields,
            "create_custom_field": self._handle_create_custom_field,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        # Pass through iteration context if we're inside an iteration loop
        # This allows downstream nodes to access the current iteration item
        if inputs:
            for key, value in inputs.items():
                if isinstance(value, dict) and value.get("isIterationNode"):
                    result["iteration_item"] = value.get("item")
                    result["iteration_index"] = value.get("index")
                    result["iteration_total"] = value.get("total")
                    logger.info(
                        f"[ApolloNode] Passing through iteration context from {key}: item keys={list(value.get('item', {}).keys()) if isinstance(value.get('item'), dict) else 'not a dict'}"
                    )
                    break

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: ApolloCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Apollo API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: API credentials
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        url = f"{APOLLO_API_BASE}{endpoint}"

        if isinstance(credentials, ApolloOAuthCredential):
            headers = {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            }
        else:
            headers = {
                "X-Api-Key": credentials.api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            }

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get(
                            "error", error_data.get("message", str(error_data))
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[ApolloNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[ApolloNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Enrichment Handlers
    # =========================================================================

    async def _handle_people_enrichment(
        self, config: ApolloPeopleEnrichmentConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Enrich data for a single person."""
        body: Dict[str, Any] = {}

        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name
        if config.email:
            body["email"] = config.email
        if config.domain:
            body["domain"] = config.domain
        if config.organization_name:
            body["organization_name"] = config.organization_name
        if config.linkedin_url:
            body["linkedin_url"] = config.linkedin_url
        if config.reveal_personal_emails is not None:
            body["reveal_personal_emails"] = config.reveal_personal_emails
        if config.reveal_phone_number is not None:
            body["reveal_phone_number"] = config.reveal_phone_number

        # Validate that we have enough information to enrich
        has_identifier = any(
            [
                config.email,
                config.domain,
                config.linkedin_url,
                (config.first_name and config.last_name and config.organization_name),
            ]
        )

        if not has_identifier:
            logger.warning(
                f"[ApolloNode] Insufficient data for enrichment. "
                f"Need: email OR domain OR linkedin_url OR (first+last+org). "
                f"Got: first_name={bool(config.first_name)}, last_name={bool(config.last_name)}, "
                f"email={bool(config.email)}, domain={bool(config.domain)}, "
                f"linkedin_url={bool(config.linkedin_url)}, org={bool(config.organization_name)}"
            )
            return {
                "status": "error",
                "action": "enrich_single_person",
                "error": "Insufficient identifying information. Need at least: email OR domain OR linkedin_url OR (first_name + last_name + organization_name)",
                "status_code": 400,
                "timing_ms": {"api_request": 0},
            }

        logger.info(f"[ApolloNode] Enriching person with body: {body}")

        return await self._make_request(
            method="POST",
            endpoint="/people/match",
            credentials=credentials,
            json_body=body,
            action_name="enrich_single_person",
        )

    async def _handle_bulk_people_enrichment(
        self, config: ApolloBulkPeopleEnrichmentConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Enrich data for multiple people."""
        body: Dict[str, Any] = {"details": config.details}

        if config.reveal_personal_emails:
            body["reveal_personal_emails"] = config.reveal_personal_emails
        if config.reveal_phone_number:
            body["reveal_phone_number"] = config.reveal_phone_number

        return await self._make_request(
            method="POST",
            endpoint="/people/bulk_match",
            credentials=credentials,
            json_body=body,
            action_name="enrich_multiple_people",
        )

    async def _handle_organization_enrichment(
        self, config: ApolloOrganizationEnrichmentConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Enrich data for a single organization."""
        return await self._make_request(
            method="GET",
            endpoint="/organizations/enrich",
            credentials=credentials,
            params={"domain": config.domain},
            action_name="enrich_single_organization",
        )

    async def _handle_bulk_organization_enrichment(
        self,
        config: ApolloBulkOrganizationEnrichmentConfig,
        credentials: ApolloCredential,
    ) -> Dict[str, Any]:
        """Enrich data for multiple organizations."""
        return await self._make_request(
            method="POST",
            endpoint="/organizations/bulk_enrich",
            credentials=credentials,
            json_body={"domains": config.domains},
            action_name="enrich_multiple_organizations",
        )

    # =========================================================================
    # Search Handlers
    # =========================================================================

    async def _handle_people_search(
        self, config: ApolloPeopleSearchConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for people/prospects."""
        body: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.q_keywords:
            body["q_keywords"] = config.q_keywords
        if config.person_titles:
            body["person_titles"] = config.person_titles
        if config.person_seniorities:
            body["person_seniorities"] = config.person_seniorities
        if config.person_locations:
            body["person_locations"] = config.person_locations
        if config.organization_domains:
            body["organization_domains"] = config.organization_domains
        if config.organization_num_employees_ranges:
            body[
                "organization_num_employees_ranges"
            ] = config.organization_num_employees_ranges

        return await self._make_request(
            method="POST",
            endpoint="/mixed_people/api_search",
            credentials=credentials,
            json_body=body,
            action_name="search_people_in_apollo",
        )

    async def _handle_organization_search(
        self, config: ApolloOrganizationSearchConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for organizations."""
        body: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.q_organization_keyword_tags:
            body["q_organization_keyword_tags"] = config.q_organization_keyword_tags
        if config.organization_locations:
            body["organization_locations"] = config.organization_locations
        if config.organization_num_employees_ranges:
            body[
                "organization_num_employees_ranges"
            ] = config.organization_num_employees_ranges

        return await self._make_request(
            method="POST",
            endpoint="/mixed_companies/search",
            credentials=credentials,
            json_body=body,
            action_name="search_organizations_in_apollo",
        )

    async def _handle_organization_job_postings(
        self, config: ApolloOrganizationJobPostingsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get job postings for an organization."""
        return await self._make_request(
            method="GET",
            endpoint=f"/organizations/{config.organization_id}/job_postings",
            credentials=credentials,
            action_name="get_organization_job_postings",
        )

    # =========================================================================
    # Account Handlers
    # =========================================================================

    async def _handle_create_account(
        self, config: ApolloCreateAccountConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create a new account."""
        body: Dict[str, Any] = {"name": config.name}

        if config.domain:
            body["domain"] = config.domain
        if config.phone_number:
            body["phone_number"] = config.phone_number
        if config.raw_address:
            body["raw_address"] = config.raw_address
        if config.owner_id:
            body["owner_id"] = config.owner_id

        return await self._make_request(
            method="POST",
            endpoint="/accounts",
            credentials=credentials,
            json_body=body,
            action_name="create_account",
        )

    async def _handle_update_account(
        self, config: ApolloUpdateAccountConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update an existing account."""
        body: Dict[str, Any] = {}

        if config.name is not None:
            body["name"] = config.name
        if config.domain is not None:
            body["domain"] = config.domain
        if config.phone_number is not None:
            body["phone_number"] = config.phone_number
        if config.raw_address is not None:
            body["raw_address"] = config.raw_address
        if config.owner_id is not None:
            body["owner_id"] = config.owner_id

        return await self._make_request(
            method="PATCH",
            endpoint=f"/accounts/{config.account_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_account_details",
        )

    async def _handle_search_accounts(
        self, config: ApolloSearchAccountsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for accounts."""
        body: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.q_organization_name:
            body["q_organization_name"] = config.q_organization_name

        return await self._make_request(
            method="POST",
            endpoint="/accounts/search",
            credentials=credentials,
            json_body=body,
            action_name="search_accounts",
        )

    async def _handle_view_account(
        self, config: ApolloViewAccountConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """View a single account."""
        return await self._make_request(
            method="GET",
            endpoint=f"/accounts/{config.account_id}",
            credentials=credentials,
            action_name="get_account_details",
        )

    async def _handle_list_account_stages(
        self, config: ApolloListAccountStagesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """List all account stages."""
        return await self._make_request(
            method="GET",
            endpoint="/account_stages",
            credentials=credentials,
            action_name="list_account_stages",
        )

    # =========================================================================
    # Contact Handlers
    # =========================================================================

    async def _handle_create_contact(
        self, config: ApolloCreateContactConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create a new contact."""
        body: Dict[str, Any] = {
            "first_name": config.first_name,
            "last_name": config.last_name,
        }

        if config.email:
            body["email"] = config.email
        if config.title:
            body["title"] = config.title
        if config.organization_name:
            body["organization_name"] = config.organization_name
        if config.account_id:
            body["account_id"] = config.account_id
        if config.phone_numbers:
            body["phone_numbers"] = config.phone_numbers
        if config.owner_id:
            body["owner_id"] = config.owner_id
        if config.label_names:
            body["label_names"] = config.label_names

        return await self._make_request(
            method="POST",
            endpoint="/contacts",
            credentials=credentials,
            json_body=body,
            action_name="create_contact",
        )

    async def _handle_update_contact(
        self, config: ApolloUpdateContactConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update an existing contact."""
        body: Dict[str, Any] = {}

        if config.first_name is not None:
            body["first_name"] = config.first_name
        if config.last_name is not None:
            body["last_name"] = config.last_name
        if config.email is not None:
            body["email"] = config.email
        if config.title is not None:
            body["title"] = config.title
        if config.organization_name is not None:
            body["organization_name"] = config.organization_name
        if config.account_id is not None:
            body["account_id"] = config.account_id
        if config.owner_id is not None:
            body["owner_id"] = config.owner_id

        return await self._make_request(
            method="PATCH",
            endpoint=f"/contacts/{config.contact_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_contact_details",
        )

    async def _handle_search_contacts(
        self, config: ApolloSearchContactsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for contacts."""
        body: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.q_keywords:
            body["q_keywords"] = config.q_keywords
        if config.contact_stage_ids:
            body["contact_stage_ids"] = config.contact_stage_ids

        return await self._make_request(
            method="POST",
            endpoint="/contacts/search",
            credentials=credentials,
            json_body=body,
            action_name="search_contacts",
        )

    async def _handle_view_contact(
        self, config: ApolloViewContactConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """View a single contact."""
        return await self._make_request(
            method="GET",
            endpoint=f"/contacts/{config.contact_id}",
            credentials=credentials,
            action_name="get_contact_details",
        )

    async def _handle_list_contact_stages(
        self, config: ApolloListContactStagesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """List all contact stages."""
        return await self._make_request(
            method="GET",
            endpoint="/contact_stages",
            credentials=credentials,
            action_name="list_contact_stages",
        )

    # =========================================================================
    # Deal Handlers
    # =========================================================================

    async def _handle_create_deal(
        self, config: ApolloCreateDealConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create a new deal."""
        body: Dict[str, Any] = {
            "name": config.name,
            "deal_stage_id": config.deal_stage_id,
        }

        if config.amount is not None:
            body["amount"] = config.amount
        if config.closed_date:
            body["closed_date"] = config.closed_date
        if config.account_id:
            body["account_id"] = config.account_id
        if config.contact_ids:
            body["contact_ids"] = config.contact_ids
        if config.owner_id:
            body["owner_id"] = config.owner_id

        return await self._make_request(
            method="POST",
            endpoint="/deals",
            credentials=credentials,
            json_body=body,
            action_name="create_deal",
        )

    async def _handle_list_deals(
        self, config: ApolloListDealsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """List all deals."""
        return await self._make_request(
            method="GET",
            endpoint="/deals",
            credentials=credentials,
            params={"page": config.page or 1, "per_page": config.per_page or 25},
            action_name="list_deals",
        )

    async def _handle_view_deal(
        self, config: ApolloViewDealConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """View a single deal."""
        return await self._make_request(
            method="GET",
            endpoint=f"/deals/{config.deal_id}",
            credentials=credentials,
            action_name="get_deal_details",
        )

    async def _handle_update_deal(
        self, config: ApolloUpdateDealConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update an existing deal."""
        body: Dict[str, Any] = {}

        if config.name is not None:
            body["name"] = config.name
        if config.deal_stage_id is not None:
            body["deal_stage_id"] = config.deal_stage_id
        if config.amount is not None:
            body["amount"] = config.amount
        if config.closed_date is not None:
            body["closed_date"] = config.closed_date
        if config.owner_id is not None:
            body["owner_id"] = config.owner_id

        return await self._make_request(
            method="PATCH",
            endpoint=f"/deals/{config.deal_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_deal_details",
        )

    async def _handle_list_deal_stages(
        self, config: ApolloListDealStagesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """List all deal stages."""
        return await self._make_request(
            method="GET",
            endpoint="/opportunity_stages",
            credentials=credentials,
            action_name="list_deal_stages",
        )

    # =========================================================================
    # Sequence Handlers
    # =========================================================================

    async def _handle_search_sequences(
        self, config: ApolloSearchSequencesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for sequences."""
        body: Dict[str, Any] = {}

        if config.q_name:
            body["q_name"] = config.q_name

        return await self._make_request(
            method="POST",
            endpoint="/emailer_campaigns/search",
            credentials=credentials,
            json_body=body,
            action_name="search_outreach_sequences",
        )

    async def _handle_add_contacts_to_sequence(
        self, config: ApolloAddContactsToSequenceConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Add contacts to a sequence."""
        body: Dict[str, Any] = {"contact_ids": config.contact_ids}

        if config.emailer_campaign_id:
            body["emailer_campaign_id"] = config.emailer_campaign_id
        if config.send_email_from_email_account_id:
            body[
                "send_email_from_email_account_id"
            ] = config.send_email_from_email_account_id

        return await self._make_request(
            method="POST",
            endpoint=f"/emailer_campaigns/{config.sequence_id}/add_contact_ids",
            credentials=credentials,
            json_body=body,
            action_name="add_contacts_to_outreach_sequence",
        )

    async def _handle_update_contact_sequence_status(
        self,
        config: ApolloUpdateContactSequenceStatusConfig,
        credentials: ApolloCredential,
    ) -> Dict[str, Any]:
        """Update a contact's status in a sequence."""
        return await self._make_request(
            method="POST",
            endpoint="/emailer_campaigns/update_contact_status",
            credentials=credentials,
            json_body={
                "contact_id": config.contact_id,
                "emailer_campaign_id": config.sequence_id,
                "status": config.status,
            },
            action_name="update_contact_sequence_status",
        )

    # =========================================================================
    # Task Handlers
    # =========================================================================

    async def _handle_create_task(
        self, config: ApolloCreateTaskConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create a new task."""
        body: Dict[str, Any] = {}

        if config.contact_id:
            body["contact_id"] = config.contact_id
        if config.account_id:
            body["account_id"] = config.account_id
        if config.user_id:
            body["user_id"] = config.user_id
        if config.due_at:
            body["due_at"] = config.due_at
        if config.priority:
            body["priority"] = config.priority
        if config.note:
            body["note"] = config.note
        if config.type:
            body["type"] = config.type

        return await self._make_request(
            method="POST",
            endpoint="/tasks",
            credentials=credentials,
            json_body=body,
            action_name="create_task",
        )

    async def _handle_search_tasks(
        self, config: ApolloSearchTasksConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for tasks."""
        body: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.user_id:
            body["user_id"] = config.user_id
        if config.contact_id:
            body["contact_id"] = config.contact_id
        if config.open_factor_id:
            body["open_factor_id"] = config.open_factor_id

        return await self._make_request(
            method="POST",
            endpoint="/tasks/search",
            credentials=credentials,
            json_body=body,
            action_name="search_tasks",
        )

    # =========================================================================
    # User/Utility Handlers
    # =========================================================================

    async def _handle_get_users(
        self, config: ApolloGetUsersConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get list of users in the organization."""
        return await self._make_request(
            method="GET",
            endpoint="/users/search",
            credentials=credentials,
            action_name="get_organization_users",
        )

    async def _handle_get_email_accounts(
        self, config: ApolloGetEmailAccountsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get list of email accounts."""
        return await self._make_request(
            method="GET",
            endpoint="/email_accounts",
            credentials=credentials,
            action_name="get_email_account_list",
        )

    async def _handle_get_usage_stats(
        self, config: ApolloGetUsageStatsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get API usage statistics and rate limits."""
        return await self._make_request(
            method="POST",
            endpoint="/auth/health",
            credentials=credentials,
            json_body={},
            action_name="get_api_usage_and_limits",
        )

    # =========================================================================
    # New Search Handlers
    # =========================================================================

    async def _handle_get_organization_info(
        self, config: ApolloGetOrganizationInfoConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get complete information for an organization."""
        return await self._make_request(
            method="GET",
            endpoint=f"/organizations/{config.organization_id}",
            credentials=credentials,
            action_name="get_organization_details",
        )

    async def _handle_search_news_articles(
        self, config: ApolloSearchNewsArticlesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for news articles about organizations."""
        body: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.organization_ids:
            body["organization_ids"] = config.organization_ids
        if config.q_keywords:
            body["q_keywords"] = config.q_keywords

        return await self._make_request(
            method="POST",
            endpoint="/organizations/search_news_articles",
            credentials=credentials,
            json_body=body,
            action_name="search_organization_news_articles",
        )

    # =========================================================================
    # New Account Handlers
    # =========================================================================

    async def _handle_bulk_create_accounts(
        self, config: ApolloBulkCreateAccountsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create multiple accounts at once."""
        return await self._make_request(
            method="POST",
            endpoint="/accounts/bulk",
            credentials=credentials,
            json_body={"accounts": config.accounts},
            action_name="create_multiple_accounts",
        )

    async def _handle_bulk_update_accounts(
        self, config: ApolloBulkUpdateAccountsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update multiple accounts at once."""
        return await self._make_request(
            method="POST",
            endpoint="/accounts/bulk_update",
            credentials=credentials,
            json_body={"accounts": config.accounts},
            action_name="update_multiple_accounts",
        )

    async def _handle_update_account_stages(
        self, config: ApolloUpdateAccountStagesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update account stage for multiple accounts."""
        return await self._make_request(
            method="POST",
            endpoint="/accounts/bulk_update_stages",
            credentials=credentials,
            json_body={
                "account_ids": config.account_ids,
                "account_stage_id": config.account_stage_id,
            },
            action_name="update_account_stage_bulk",
        )

    async def _handle_update_account_owners(
        self, config: ApolloUpdateAccountOwnersConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update owner for multiple accounts."""
        return await self._make_request(
            method="POST",
            endpoint="/accounts/bulk_update_owners",
            credentials=credentials,
            json_body={"account_ids": config.account_ids, "owner_id": config.owner_id},
            action_name="update_account_ownership",
        )

    # =========================================================================
    # New Contact Handlers
    # =========================================================================

    async def _handle_bulk_create_contacts(
        self, config: ApolloBulkCreateContactsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create multiple contacts at once."""
        body: Dict[str, Any] = {"contacts": config.contacts}
        if config.run_dedupe:
            body["run_dedupe"] = config.run_dedupe

        return await self._make_request(
            method="POST",
            endpoint="/contacts/bulk",
            credentials=credentials,
            json_body=body,
            action_name="create_multiple_contacts",
        )

    async def _handle_bulk_update_contacts(
        self, config: ApolloBulkUpdateContactsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update multiple contacts at once."""
        return await self._make_request(
            method="POST",
            endpoint="/contacts/bulk_update",
            credentials=credentials,
            json_body={"contacts": config.contacts},
            action_name="update_multiple_contacts",
        )

    async def _handle_update_contact_stages(
        self, config: ApolloUpdateContactStagesConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update contact stage for multiple contacts."""
        return await self._make_request(
            method="POST",
            endpoint="/contacts/bulk_update_stages",
            credentials=credentials,
            json_body={
                "contact_ids": config.contact_ids,
                "contact_stage_id": config.contact_stage_id,
            },
            action_name="update_contact_stage_bulk",
        )

    async def _handle_update_contact_owners(
        self, config: ApolloUpdateContactOwnersConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update owner for multiple contacts."""
        return await self._make_request(
            method="POST",
            endpoint="/contacts/bulk_update_owners",
            credentials=credentials,
            json_body={"contact_ids": config.contact_ids, "owner_id": config.owner_id},
            action_name="update_contact_ownership",
        )

    # =========================================================================
    # New Sequence/Email Handlers
    # =========================================================================

    async def _handle_search_emails(
        self, config: ApolloSearchEmailsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for outreach emails in sequences."""
        params: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.emailer_campaign_id:
            params["emailer_campaign_id"] = config.emailer_campaign_id
        if config.contact_id:
            params["contact_id"] = config.contact_id
        if config.email_status:
            params["email_status"] = config.email_status

        return await self._make_request(
            method="GET",
            endpoint="/emailer_messages/search",
            credentials=credentials,
            params=params,
            action_name="search_sequence_emails",
        )

    async def _handle_get_email_stats(
        self, config: ApolloGetEmailStatsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get email statistics for a sequence."""
        return await self._make_request(
            method="GET",
            endpoint=f"/emailer_campaigns/{config.sequence_id}/stats",
            credentials=credentials,
            action_name="get_sequence_email_statistics",
        )

    # =========================================================================
    # Call Handlers
    # =========================================================================

    async def _handle_create_call_record(
        self, config: ApolloCreateCallRecordConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create a call record."""
        body: Dict[str, Any] = {"contact_id": config.contact_id}

        if config.user_id:
            body["user_id"] = config.user_id
        if config.phone_number:
            body["phone_number"] = config.phone_number
        if config.duration is not None:
            body["duration"] = config.duration
        if config.outcome:
            body["outcome"] = config.outcome
        if config.direction:
            body["direction"] = config.direction
        if config.note:
            body["note"] = config.note
        if config.called_at:
            body["called_at"] = config.called_at

        return await self._make_request(
            method="POST",
            endpoint="/phone_calls",
            credentials=credentials,
            json_body=body,
            action_name="create_call_activity_record",
        )

    async def _handle_search_calls(
        self, config: ApolloSearchCallsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Search for call records."""
        params: Dict[str, Any] = {
            "page": config.page or 1,
            "per_page": config.per_page or 25,
        }

        if config.contact_id:
            params["contact_id"] = config.contact_id
        if config.user_id:
            params["user_id"] = config.user_id
        if config.outcome:
            params["outcome"] = config.outcome

        return await self._make_request(
            method="GET",
            endpoint="/phone_calls/search",
            credentials=credentials,
            params=params,
            action_name="search_call_records",
        )

    async def _handle_update_call_record(
        self, config: ApolloUpdateCallRecordConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Update a call record."""
        body: Dict[str, Any] = {}

        if config.duration is not None:
            body["duration"] = config.duration
        if config.outcome:
            body["outcome"] = config.outcome
        if config.note:
            body["note"] = config.note

        return await self._make_request(
            method="PUT",
            endpoint=f"/phone_calls/{config.call_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_call_record",
        )

    # =========================================================================
    # New Utility Handlers
    # =========================================================================

    async def _handle_get_lists(
        self, config: ApolloGetListsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get all lists in the organization."""
        return await self._make_request(
            method="GET",
            endpoint="/labels",
            credentials=credentials,
            action_name="get_organization_lists",
        )

    async def _handle_get_custom_fields(
        self, config: ApolloGetCustomFieldsConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Get all custom fields in the organization."""
        params: Dict[str, Any] = {}
        if config.field_type:
            params["field_type"] = config.field_type

        return await self._make_request(
            method="GET",
            endpoint="/typed_custom_fields",
            credentials=credentials,
            params=params if params else None,
            action_name="get_organization_custom_fields",
        )

    async def _handle_create_custom_field(
        self, config: ApolloCreateCustomFieldConfig, credentials: ApolloCredential
    ) -> Dict[str, Any]:
        """Create a custom field."""
        body: Dict[str, Any] = {"name": config.name, "field_type": config.field_type}

        if config.widget_type:
            body["widget_type"] = config.widget_type
        if config.options:
            body["options"] = config.options

        return await self._make_request(
            method="POST",
            endpoint="/typed_custom_fields",
            credentials=credentials,
            json_body=body,
            action_name="create_custom_field",
        )
