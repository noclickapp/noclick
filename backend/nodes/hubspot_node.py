"""
HubSpot CRM API automation node.

Provides comprehensive workflow integration with HubSpot CRM including:
- CRM Objects: Contacts, Companies, Deals, Tickets, Leads, Products, Line Items, Quotes, Notes, Tasks
- Activities/Engagements: Calls, Meetings, Emails
- Commerce: Orders, Carts, Invoices, Payments
- Cross-Object Operations: Associations, Batch Operations
- System: Properties, Pipelines, Owners
- Lists & Segmentation: Lists (Segments) API v3 (v1 sunset Apr 30, 2026)
- Schema: Custom Object Schemas (foundation for custom objects)
- Marketing: Marketing Events API (webinars, conferences), Campaigns API (ROI tracking)
- Analytics & Events: Custom Events API (behavioral tracking, legacy sunset Aug 1, 2025)

Total Operations: 141
Authentication: OAuth 2.0 or Private App Access Token
API Base URL: https://api.hubapi.com
Documentation: https://developers.hubspot.com/docs/reference/api/overview
"""

import logging
import time
import json
import json as json_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator, ConfigDict
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from nodes.scopes.hubspot import HUBSPOT_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

HUBSPOT_API_BASE = "https://api.hubapi.com"

# Internal helper calls (token introspection / id resolution) — excluded from the
# 403 scope-error translation to avoid recursion and irrelevant rewrites.
_INTERNAL_ACTION_NAMES = frozenset({
    "resolve_user_id", "resolve_portal_id", "scope_check",
    "get_access_token_info", "list_api_scopes", "validate_access_token",
})

# ============================================================================
# Credential Schema
# ============================================================================


class HubSpotOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for HubSpot.

    OAuth tokens are obtained via OAuth flow, recommended for multi-account apps.
    Register OAuth app at: https://developers.hubspot.com/
    """

    credential_type: Literal["hubspot_oauth"] = Field(
        "hubspot_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    hub_id: Optional[str] = Field(None, title="Hub ID")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "hubspot",
            "x-credential-url": "https://developers.hubspot.com/docs/apps/developer-platform/list-apps/listing-your-app/create-an-app-listing-setup-guide",
            "x-credential-instructions": (
                "Sign in with your HubSpot account to authorize NoClick. "
                "See the setup guide for detailed installation and configuration instructions."
            ),
            # Required (guaranteed) scopes — the core CRM every HubSpot tier has.
            # The install URL additionally requests ~40 tier-gated scopes as
            # optional_scope (frontend .../hubspot.authorize.tsx), granted per
            # account tier. Keep in sync with the app config requiredScopes
            # (project noclick-oauth-app / app-hsmeta.json).
            "x-oauth-scopes": [
                "oauth",
                "crm.objects.contacts.read", "crm.objects.contacts.write",
                "crm.objects.companies.read", "crm.objects.companies.write",
                "crm.objects.deals.read", "crm.objects.deals.write",
                "tickets",
            ],
        }
    )


class HubSpotPATCredential(BaseModel):
    """
    Private App Access Token credential for HubSpot.

    Get your PAT at: https://app.hubspot.com/private-apps/
    Private app tokens don't expire and are recommended for internal integrations.
    """

    credential_type: Literal["hubspot_pat"] = Field(
        "hubspot_pat", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Private App Access Token",
        description="Your HubSpot Private App access token",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.hubspot.com/private-apps/",
            "x-credential-instructions": (
                "Create a private app in HubSpot to get your access token. "
                "See the setup guide for detailed installation and configuration instructions."
            ),
        }
    )


# Union type - OAuth shown first in UI (best UX), PAT as alternative
HubSpotCredential = Union[HubSpotOAuthCredential, HubSpotPATCredential]


# ============================================================================
# Contact Operation Configs
# ============================================================================


class HubSpotListContactsConfig(BaseModel):
    model_config = ConfigDict(title="List Contacts")
    """List all contacts with pagination"""
    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
            "x-keywords": [
                "all contacts",
                "browse contacts",
                "people list",
                "contacts directory",
            ],
        },
        title="List Contacts",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of contacts to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return (e.g., 'email,firstname,lastname')",
    )


class HubSpotGetContactConfig(BaseModel):
    model_config = ConfigDict(title="Get Contact")
    """Get a specific contact by ID"""
    operation: Literal["get_contact"] = Field(
        "get_contact",
        json_schema_extra={
            "const": "get_contact",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Get Contact",
            "x-keywords": [
                "one contact",
                "contact details",
                "contact by id",
                "fetch single contact",
                "person record",
            ],
        },
        title="Get Contact",
    )
    contact_id: str = Field(
        ..., title="Contact ID", description="The unique identifier of the contact"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateContactConfig(BaseModel):
    model_config = ConfigDict(title="Create Contact")
    """Create a new contact"""
    operation: Literal["create_contact"] = Field(
        "create_contact",
        json_schema_extra={
            "const": "create_contact",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Create Contact",
            "x-keywords": [
                "add contact",
                "new contact",
                "add person",
                "save contact",
                "register lead",
            ],
        },
        title="Create Contact",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Contact's email address"
    )
    firstname: Optional[str] = Field(
        None, title="First Name", description="Contact's first name"
    )
    lastname: Optional[str] = Field(
        None, title="Last Name", description="Contact's last name"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="Contact's phone number"
    )
    company: Optional[str] = Field(
        None, title="Company", description="Contact's company name"
    )
    website: Optional[str] = Field(
        None, title="Website", description="Contact's website URL"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateContactConfig(BaseModel):
    model_config = ConfigDict(title="Update Contact")
    """Update an existing contact"""
    operation: Literal["update_contact"] = Field(
        "update_contact",
        json_schema_extra={
            "const": "update_contact",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact",
            "x-keywords": [
                "edit contact",
                "change contact",
                "update person",
                "modify contact fields",
                "patch contact",
            ],
        },
        title="Update Contact",
    )
    contact_id: str = Field(
        ...,
        title="Contact ID",
        description="The unique identifier of the contact to update",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Contact's email address"
    )
    firstname: Optional[str] = Field(
        None, title="First Name", description="Contact's first name"
    )
    lastname: Optional[str] = Field(
        None, title="Last Name", description="Contact's last name"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="Contact's phone number"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteContactConfig(BaseModel):
    model_config = ConfigDict(title="Delete Contact")
    """Delete a contact"""
    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        json_schema_extra={
            "const": "delete_contact",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact",
            "x-keywords": [
                "remove contact",
                "delete person",
                "archive contact",
                "drop contact",
            ],
        },
        title="Delete Contact",
    )
    contact_id: str = Field(
        ...,
        title="Contact ID",
        description="The unique identifier of the contact to delete",
    )


class HubSpotSearchContactsConfig(BaseModel):
    model_config = ConfigDict(title="Search Contacts")
    """Search for contacts"""
    operation: Literal["search_contacts"] = Field(
        "search_contacts",
        json_schema_extra={
            "const": "search_contacts",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Search Contacts",
            "x-keywords": [
                "find contact",
                "query contacts",
                "filter contacts",
                "lookup person",
                "search people",
            ],
        },
        title="Search Contacts",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Text to search for across default searchable properties",
    )
    filter_property: Optional[str] = Field(
        None,
        title="Filter Property",
        description="Property name to filter on (e.g., 'email', 'firstname')",
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Company Operation Configs
# ============================================================================


class HubSpotListCompaniesConfig(BaseModel):
    model_config = ConfigDict(title="List Companies")
    """List all companies with pagination"""
    operation: Literal["list_companies"] = Field(
        "list_companies",
        json_schema_extra={
            "const": "list_companies",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "List Companies",
            "x-keywords": [
                "all companies",
                "browse companies",
                "accounts list",
                "organizations directory",
            ],
        },
        title="List Companies",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of companies to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return (e.g., 'name,domain,industry')",
    )


class HubSpotGetCompanyConfig(BaseModel):
    model_config = ConfigDict(title="Get Company")
    """Get a specific company by ID"""
    operation: Literal["get_company"] = Field(
        "get_company",
        json_schema_extra={
            "const": "get_company",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Get Company",
            "x-keywords": [
                "one company",
                "company details",
                "company by id",
                "fetch single company",
                "account record",
            ],
        },
        title="Get Company",
    )
    company_id: str = Field(
        ..., title="Company ID", description="The unique identifier of the company"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateCompanyConfig(BaseModel):
    model_config = ConfigDict(title="Create Company")
    """Create a new company"""
    operation: Literal["create_company"] = Field(
        "create_company",
        json_schema_extra={
            "const": "create_company",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Create Company",
            "x-keywords": [
                "add company",
                "new company",
                "add account",
                "save company",
                "register organization",
            ],
        },
        title="Create Company",
    )
    name: str = Field(..., title="Company Name", description="The name of the company")
    domain: Optional[str] = Field(
        None,
        title="Domain",
        description="Company's website domain (e.g., 'example.com')",
    )
    industry: Optional[str] = Field(
        None, title="Industry", description="Company's industry"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="Company's phone number"
    )
    city: Optional[str] = Field(None, title="City", description="Company's city")
    state: Optional[str] = Field(
        None, title="State/Region", description="Company's state or region"
    )
    country: Optional[str] = Field(
        None, title="Country", description="Company's country"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateCompanyConfig(BaseModel):
    model_config = ConfigDict(title="Update Company")
    """Update an existing company"""
    operation: Literal["update_company"] = Field(
        "update_company",
        json_schema_extra={
            "const": "update_company",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Update Company",
            "x-keywords": [
                "edit company",
                "change company",
                "update account",
                "modify company fields",
                "patch company",
            ],
        },
        title="Update Company",
    )
    company_id: str = Field(
        ...,
        title="Company ID",
        description="The unique identifier of the company to update",
    )
    name: Optional[str] = Field(
        None, title="Company Name", description="The name of the company"
    )
    domain: Optional[str] = Field(
        None, title="Domain", description="Company's website domain"
    )
    industry: Optional[str] = Field(
        None, title="Industry", description="Company's industry"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteCompanyConfig(BaseModel):
    model_config = ConfigDict(title="Delete Company")
    """Delete a company"""
    operation: Literal["delete_company"] = Field(
        "delete_company",
        json_schema_extra={
            "const": "delete_company",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Delete Company",
            "x-keywords": [
                "remove company",
                "delete account",
                "archive company",
                "drop organization",
            ],
        },
        title="Delete Company",
    )
    company_id: str = Field(
        ...,
        title="Company ID",
        description="The unique identifier of the company to delete",
    )


class HubSpotSearchCompaniesConfig(BaseModel):
    model_config = ConfigDict(title="Search Companies")
    """Search for companies"""
    operation: Literal["search_companies"] = Field(
        "search_companies",
        json_schema_extra={
            "const": "search_companies",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Search Companies",
            "x-keywords": [
                "find company",
                "query companies",
                "filter companies",
                "lookup account",
                "search organizations",
            ],
        },
        title="Search Companies",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Text to search for across default searchable properties",
    )
    filter_property: Optional[str] = Field(
        None,
        title="Filter Property",
        description="Property name to filter on (e.g., 'name', 'domain')",
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Deal Operation Configs
# ============================================================================


class HubSpotListDealsConfig(BaseModel):
    model_config = ConfigDict(title="List Deals")
    """List all deals with pagination"""
    operation: Literal["list_deals"] = Field(
        "list_deals",
        json_schema_extra={
            "const": "list_deals",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "List Deals",
            "x-keywords": [
                "all deals",
                "browse deals",
                "opportunities list",
                "pipeline deals",
            ],
        },
        title="List Deals",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of deals to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return (e.g., 'dealname,amount,dealstage')",
    )


class HubSpotGetDealConfig(BaseModel):
    model_config = ConfigDict(title="Get Deal")
    """Get a specific deal by ID"""
    operation: Literal["get_deal"] = Field(
        "get_deal",
        json_schema_extra={
            "const": "get_deal",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Get Deal",
            "x-keywords": [
                "one deal",
                "deal details",
                "deal by id",
                "fetch single deal",
                "opportunity record",
            ],
        },
        title="Get Deal",
    )
    deal_id: str = Field(
        ..., title="Deal ID", description="The unique identifier of the deal"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateDealConfig(BaseModel):
    model_config = ConfigDict(title="Create Deal")
    """Create a new deal"""
    operation: Literal["create_deal"] = Field(
        "create_deal",
        json_schema_extra={
            "const": "create_deal",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Create Deal",
            "x-keywords": [
                "add deal",
                "new deal",
                "add opportunity",
                "open deal",
                "register deal",
            ],
        },
        title="Create Deal",
    )
    dealname: str = Field(..., title="Deal Name", description="The name of the deal")
    dealstage: Optional[str] = Field(
        None,
        title="Deal Stage",
        description="The stage of the deal (e.g., 'appointmentscheduled', 'qualifiedtobuy')",
    )
    pipeline: Optional[str] = Field(
        None, title="Pipeline", description="The pipeline ID for the deal"
    )
    amount: Optional[str] = Field(
        None, title="Amount", description="The monetary value of the deal"
    )
    closedate: Optional[str] = Field(
        None,
        title="Close Date",
        description="Expected close date (ISO 8601 format, e.g., '2024-12-31')",
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateDealConfig(BaseModel):
    model_config = ConfigDict(title="Update Deal")
    """Update an existing deal"""
    operation: Literal["update_deal"] = Field(
        "update_deal",
        json_schema_extra={
            "const": "update_deal",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Update Deal",
            "x-keywords": [
                "edit deal",
                "change deal",
                "update opportunity",
                "move deal stage",
                "patch deal",
            ],
        },
        title="Update Deal",
    )
    deal_id: str = Field(
        ..., title="Deal ID", description="The unique identifier of the deal to update"
    )
    dealname: Optional[str] = Field(
        None, title="Deal Name", description="The name of the deal"
    )
    dealstage: Optional[str] = Field(
        None, title="Deal Stage", description="The stage of the deal"
    )
    amount: Optional[str] = Field(
        None, title="Amount", description="The monetary value of the deal"
    )
    closedate: Optional[str] = Field(
        None, title="Close Date", description="Expected close date (ISO 8601 format)"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteDealConfig(BaseModel):
    model_config = ConfigDict(title="Delete Deal")
    """Delete a deal"""
    operation: Literal["delete_deal"] = Field(
        "delete_deal",
        json_schema_extra={
            "const": "delete_deal",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Delete Deal",
            "x-keywords": [
                "remove deal",
                "delete opportunity",
                "archive deal",
                "drop deal",
            ],
        },
        title="Delete Deal",
    )
    deal_id: str = Field(
        ..., title="Deal ID", description="The unique identifier of the deal to delete"
    )


class HubSpotSearchDealsConfig(BaseModel):
    model_config = ConfigDict(title="Search Deals")
    """Search for deals"""
    operation: Literal["search_deals"] = Field(
        "search_deals",
        json_schema_extra={
            "const": "search_deals",
            "ui:hidden": True,
            "x-category": "Deal",
            "x-is-trigger": False,
            "x-display-name": "Search Deals",
            "x-keywords": [
                "find deal",
                "query deals",
                "filter deals",
                "lookup opportunity",
                "search pipeline",
            ],
        },
        title="Search Deals",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Text to search for across default searchable properties",
    )
    filter_property: Optional[str] = Field(
        None,
        title="Filter Property",
        description="Property name to filter on (e.g., 'dealname', 'dealstage')",
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Ticket Operation Configs
# ============================================================================


class HubSpotListTicketsConfig(BaseModel):
    model_config = ConfigDict(title="List Tickets")
    """List all tickets with pagination"""
    operation: Literal["list_support_tickets"] = Field(
        "list_support_tickets",
        json_schema_extra={
            "const": "list_support_tickets",
            "ui:hidden": True,
            "x-category": "Ticket",
            "x-is-trigger": False,
            "x-display-name": "List Support Tickets",
            "x-keywords": [
                "all tickets",
                "browse tickets",
                "support queue",
                "open tickets list",
            ],
        },
        title="List Support Tickets",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of tickets to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return (e.g., 'subject,content,hs_pipeline_stage')",
    )


class HubSpotGetTicketConfig(BaseModel):
    model_config = ConfigDict(title="Get Ticket")
    """Get a specific ticket by ID"""
    operation: Literal["get_support_ticket"] = Field(
        "get_support_ticket",
        json_schema_extra={
            "const": "get_support_ticket",
            "ui:hidden": True,
            "x-category": "Ticket",
            "x-is-trigger": False,
            "x-display-name": "Get Support Ticket",
            "x-keywords": [
                "one ticket",
                "ticket details",
                "ticket by id",
                "fetch single ticket",
                "support case",
            ],
        },
        title="Get Support Ticket",
    )
    ticket_id: str = Field(
        ..., title="Ticket ID", description="The unique identifier of the ticket"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateTicketConfig(BaseModel):
    model_config = ConfigDict(title="Create Ticket")
    """Create a new ticket"""
    operation: Literal["create_support_ticket"] = Field(
        "create_support_ticket",
        json_schema_extra={
            "const": "create_support_ticket",
            "ui:hidden": True,
            "x-category": "Ticket",
            "x-is-trigger": False,
            "x-display-name": "Create Support Ticket",
            "x-keywords": [
                "add ticket",
                "new ticket",
                "open ticket",
                "log support case",
                "raise ticket",
            ],
        },
        title="Create Support Ticket",
    )
    subject: str = Field(
        ..., title="Subject", description="The subject/title of the ticket"
    )
    content: Optional[str] = Field(
        None,
        title="Content",
        description="The ticket description/content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_pipeline: Optional[str] = Field(
        None, title="Pipeline", description="The pipeline ID for the ticket"
    )
    hs_pipeline_stage: Optional[str] = Field(
        None,
        title="Pipeline Stage",
        description="The stage of the ticket within the pipeline",
    )
    hs_ticket_priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Ticket priority",
        json_schema_extra={"enum": ["LOW", "MEDIUM", "HIGH"]},
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateTicketConfig(BaseModel):
    model_config = ConfigDict(title="Update Ticket")
    """Update an existing ticket"""
    operation: Literal["update_support_ticket"] = Field(
        "update_support_ticket",
        json_schema_extra={
            "const": "update_support_ticket",
            "ui:hidden": True,
            "x-category": "Ticket",
            "x-is-trigger": False,
            "x-display-name": "Update Support Ticket",
            "x-keywords": [
                "edit ticket",
                "change ticket",
                "update support case",
                "patch ticket",
                "modify ticket",
            ],
        },
        title="Update Support Ticket",
    )
    ticket_id: str = Field(
        ...,
        title="Ticket ID",
        description="The unique identifier of the ticket to update",
    )
    subject: Optional[str] = Field(
        None, title="Subject", description="The subject/title of the ticket"
    )
    content: Optional[str] = Field(
        None,
        title="Content",
        description="The ticket description/content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_pipeline_stage: Optional[str] = Field(
        None,
        title="Pipeline Stage",
        description="The stage of the ticket within the pipeline",
    )
    hs_ticket_priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Ticket priority",
        json_schema_extra={"enum": ["LOW", "MEDIUM", "HIGH"]},
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteTicketConfig(BaseModel):
    model_config = ConfigDict(title="Delete Ticket")
    """Delete a ticket"""
    operation: Literal["delete_support_ticket"] = Field(
        "delete_support_ticket",
        json_schema_extra={
            "const": "delete_support_ticket",
            "ui:hidden": True,
            "x-category": "Ticket",
            "x-is-trigger": False,
            "x-display-name": "Delete Support Ticket",
            "x-keywords": [
                "remove ticket",
                "delete support case",
                "archive ticket",
                "drop ticket",
            ],
        },
        title="Delete Support Ticket",
    )
    ticket_id: str = Field(
        ...,
        title="Ticket ID",
        description="The unique identifier of the ticket to delete",
    )


class HubSpotSearchTicketsConfig(BaseModel):
    model_config = ConfigDict(title="Search Tickets")
    """Search for tickets"""
    operation: Literal["search_support_tickets"] = Field(
        "search_support_tickets",
        json_schema_extra={
            "const": "search_support_tickets",
            "ui:hidden": True,
            "x-category": "Ticket",
            "x-is-trigger": False,
            "x-display-name": "Search Support Tickets",
            "x-keywords": [
                "find ticket",
                "query tickets",
                "filter tickets",
                "lookup support case",
                "search cases",
            ],
        },
        title="Search Support Tickets",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Text to search for across default searchable properties",
    )
    filter_property: Optional[str] = Field(
        None,
        title="Filter Property",
        description="Property name to filter on (e.g., 'subject', 'hs_pipeline_stage')",
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Lead Operation Configs (NEW - HubSpot Leads object)
# ============================================================================


class HubSpotListLeadsConfig(BaseModel):
    model_config = ConfigDict(title="List Leads")
    """List all leads with pagination"""
    operation: Literal["list_leads"] = Field(
        "list_leads",
        json_schema_extra={
            "const": "list_leads",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "List Leads",
            "x-keywords": [
                "all leads",
                "browse leads",
                "prospects list",
                "leads directory",
            ],
        },
        title="List Leads",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of leads to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetLeadConfig(BaseModel):
    model_config = ConfigDict(title="Get Lead")
    """Get a specific lead by ID"""
    operation: Literal["get_lead"] = Field(
        "get_lead",
        json_schema_extra={
            "const": "get_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Get Lead",
            "x-keywords": [
                "one lead",
                "lead details",
                "lead by id",
                "fetch single lead",
                "prospect record",
            ],
        },
        title="Get Lead",
    )
    lead_id: str = Field(
        ..., title="Lead ID", description="The unique identifier of the lead"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateLeadConfig(BaseModel):
    model_config = ConfigDict(title="Create Lead")
    """Create a new lead"""
    operation: Literal["create_lead"] = Field(
        "create_lead",
        json_schema_extra={
            "const": "create_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Create Lead",
            "x-keywords": [
                "add lead",
                "new lead",
                "add prospect",
                "capture lead",
                "register prospect",
            ],
        },
        title="Create Lead",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Lead's email address"
    )
    firstname: Optional[str] = Field(
        None, title="First Name", description="Lead's first name"
    )
    lastname: Optional[str] = Field(
        None, title="Last Name", description="Lead's last name"
    )
    company: Optional[str] = Field(
        None, title="Company", description="Lead's company name"
    )
    phone: Optional[str] = Field(None, title="Phone", description="Lead's phone number")
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateLeadConfig(BaseModel):
    model_config = ConfigDict(title="Update Lead")
    """Update an existing lead"""
    operation: Literal["update_lead"] = Field(
        "update_lead",
        json_schema_extra={
            "const": "update_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Update Lead",
            "x-keywords": [
                "edit lead",
                "change lead",
                "update prospect",
                "patch lead",
                "modify lead fields",
            ],
        },
        title="Update Lead",
    )
    lead_id: str = Field(
        ..., title="Lead ID", description="The unique identifier of the lead to update"
    )
    email: Optional[str] = Field(
        None, title="Email", description="Lead's email address"
    )
    firstname: Optional[str] = Field(
        None, title="First Name", description="Lead's first name"
    )
    lastname: Optional[str] = Field(
        None, title="Last Name", description="Lead's last name"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteLeadConfig(BaseModel):
    model_config = ConfigDict(title="Delete Lead")
    """Delete a lead"""
    operation: Literal["delete_lead"] = Field(
        "delete_lead",
        json_schema_extra={
            "const": "delete_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Delete Lead",
            "x-keywords": [
                "remove lead",
                "delete prospect",
                "archive lead",
                "drop lead",
            ],
        },
        title="Delete Lead",
    )
    lead_id: str = Field(
        ..., title="Lead ID", description="The unique identifier of the lead to delete"
    )


class HubSpotSearchLeadsConfig(BaseModel):
    model_config = ConfigDict(title="Search Leads")
    """Search for leads"""
    operation: Literal["search_leads"] = Field(
        "search_leads",
        json_schema_extra={
            "const": "search_leads",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Search Leads",
            "x-keywords": [
                "find lead",
                "query leads",
                "filter leads",
                "lookup prospect",
                "search prospects",
            ],
        },
        title="Search Leads",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Text to search for across default searchable properties",
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Product Operation Configs
# ============================================================================


class HubSpotListProductsConfig(BaseModel):
    model_config = ConfigDict(title="List Products")
    """List all products with pagination"""
    operation: Literal["list_products"] = Field(
        "list_products",
        json_schema_extra={
            "const": "list_products",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "List Products",
            "x-keywords": [
                "all products",
                "browse products",
                "catalog list",
                "product catalog",
            ],
        },
        title="List Products",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of products to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetProductConfig(BaseModel):
    model_config = ConfigDict(title="Get Product")
    """Get a specific product by ID"""
    operation: Literal["get_product"] = Field(
        "get_product",
        json_schema_extra={
            "const": "get_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Get Product",
            "x-keywords": [
                "one product",
                "product details",
                "product by id",
                "fetch single product",
                "catalog item",
            ],
        },
        title="Get Product",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The unique identifier of the product"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateProductConfig(BaseModel):
    model_config = ConfigDict(title="Create Product")
    """Create a new product"""
    operation: Literal["create_product"] = Field(
        "create_product",
        json_schema_extra={
            "const": "create_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Create Product",
            "x-keywords": [
                "add product",
                "new product",
                "add catalog item",
                "save product",
                "register product",
            ],
        },
        title="Create Product",
    )
    name: str = Field(..., title="Product Name", description="The name of the product")
    price: Optional[str] = Field(None, title="Price", description="Product price")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Product description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_sku: Optional[str] = Field(None, title="SKU", description="Product SKU")
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateProductConfig(BaseModel):
    model_config = ConfigDict(title="Update Product")
    """Update an existing product"""
    operation: Literal["update_product"] = Field(
        "update_product",
        json_schema_extra={
            "const": "update_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Update Product",
            "x-keywords": [
                "edit product",
                "change product",
                "update catalog item",
                "patch product",
                "modify product",
            ],
        },
        title="Update Product",
    )
    product_id: str = Field(
        ...,
        title="Product ID",
        description="The unique identifier of the product to update",
    )
    name: Optional[str] = Field(
        None, title="Product Name", description="The name of the product"
    )
    price: Optional[str] = Field(None, title="Price", description="Product price")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Product description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteProductConfig(BaseModel):
    model_config = ConfigDict(title="Delete Product")
    """Delete a product"""
    operation: Literal["delete_product"] = Field(
        "delete_product",
        json_schema_extra={
            "const": "delete_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Product",
            "x-keywords": [
                "remove product",
                "delete catalog item",
                "archive product",
                "drop product",
            ],
        },
        title="Delete Product",
    )
    product_id: str = Field(
        ...,
        title="Product ID",
        description="The unique identifier of the product to delete",
    )


class HubSpotSearchProductsConfig(BaseModel):
    model_config = ConfigDict(title="Search Products")
    """Search for products"""
    operation: Literal["search_products"] = Field(
        "search_products",
        json_schema_extra={
            "const": "search_products",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Search Products",
            "x-keywords": [
                "find product",
                "query products",
                "filter products",
                "lookup catalog item",
                "search catalog",
            ],
        },
        title="Search Products",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Line Item Operation Configs
# ============================================================================


class HubSpotListLineItemsConfig(BaseModel):
    model_config = ConfigDict(title="List Line Items")
    """List all line items with pagination"""
    operation: Literal["list_line_items"] = Field(
        "list_line_items",
        json_schema_extra={
            "const": "list_line_items",
            "ui:hidden": True,
            "x-category": "Line Item",
            "x-is-trigger": False,
            "x-display-name": "List Line Items",
            "x-keywords": [
                "all line items",
                "browse line items",
                "deal line items",
                "quote line items",
            ],
        },
        title="List Line Items",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of line items to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetLineItemConfig(BaseModel):
    model_config = ConfigDict(title="Get Line Item")
    """Get a specific line item by ID"""
    operation: Literal["get_line_item"] = Field(
        "get_line_item",
        json_schema_extra={
            "const": "get_line_item",
            "ui:hidden": True,
            "x-category": "Line Item",
            "x-is-trigger": False,
            "x-display-name": "Get Line Item",
            "x-keywords": [
                "one line item",
                "line item details",
                "line item by id",
                "fetch single line item",
            ],
        },
        title="Get Line Item",
    )
    line_item_id: str = Field(
        ..., title="Line Item ID", description="The unique identifier of the line item"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateLineItemConfig(BaseModel):
    model_config = ConfigDict(title="Create Line Item")
    """Create a new line item"""
    operation: Literal["create_line_item"] = Field(
        "create_line_item",
        json_schema_extra={
            "const": "create_line_item",
            "ui:hidden": True,
            "x-category": "Line Item",
            "x-is-trigger": False,
            "x-display-name": "Create Line Item",
            "x-keywords": [
                "add line item",
                "new line item",
                "add deal item",
                "attach line item",
            ],
        },
        title="Create Line Item",
    )
    name: str = Field(..., title="Name", description="Line item name")
    quantity: Optional[str] = Field(None, title="Quantity", description="Quantity")
    price: Optional[str] = Field(None, title="Price", description="Unit price")
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateLineItemConfig(BaseModel):
    model_config = ConfigDict(title="Update Line Item")
    """Update an existing line item"""
    operation: Literal["update_line_item"] = Field(
        "update_line_item",
        json_schema_extra={
            "const": "update_line_item",
            "ui:hidden": True,
            "x-category": "Line Item",
            "x-is-trigger": False,
            "x-display-name": "Update Line Item",
            "x-keywords": [
                "edit line item",
                "change line item",
                "update deal item",
                "patch line item",
            ],
        },
        title="Update Line Item",
    )
    line_item_id: str = Field(
        ...,
        title="Line Item ID",
        description="The unique identifier of the line item to update",
    )
    name: Optional[str] = Field(None, title="Name", description="Line item name")
    quantity: Optional[str] = Field(None, title="Quantity", description="Quantity")
    price: Optional[str] = Field(None, title="Price", description="Unit price")
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteLineItemConfig(BaseModel):
    model_config = ConfigDict(title="Delete Line Item")
    """Delete a line item"""
    operation: Literal["delete_line_item"] = Field(
        "delete_line_item",
        json_schema_extra={
            "const": "delete_line_item",
            "ui:hidden": True,
            "x-category": "Line Item",
            "x-is-trigger": False,
            "x-display-name": "Delete Line Item",
            "x-keywords": [
                "remove line item",
                "delete deal item",
                "archive line item",
                "drop line item",
            ],
        },
        title="Delete Line Item",
    )
    line_item_id: str = Field(
        ...,
        title="Line Item ID",
        description="The unique identifier of the line item to delete",
    )


class HubSpotSearchLineItemsConfig(BaseModel):
    model_config = ConfigDict(title="Search Line Items")
    """Search for line items"""
    operation: Literal["search_line_items"] = Field(
        "search_line_items",
        json_schema_extra={
            "const": "search_line_items",
            "ui:hidden": True,
            "x-category": "Line Item",
            "x-is-trigger": False,
            "x-display-name": "Search Line Items",
            "x-keywords": [
                "find line item",
                "query line items",
                "filter line items",
                "lookup deal item",
            ],
        },
        title="Search Line Items",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Quote Operation Configs
# ============================================================================


class HubSpotListQuotesConfig(BaseModel):
    model_config = ConfigDict(title="List Quotes")
    """List all quotes with pagination"""
    operation: Literal["list_quotes"] = Field(
        "list_quotes",
        json_schema_extra={
            "const": "list_quotes",
            "ui:hidden": True,
            "x-category": "Quote",
            "x-is-trigger": False,
            "x-display-name": "List Quotes",
            "x-keywords": ["sales quotes", "all quotes", "price quotes", "proposals"],
        },
        title="List Quotes",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of quotes to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetQuoteConfig(BaseModel):
    model_config = ConfigDict(title="Get Quote")
    """Get a specific quote by ID"""
    operation: Literal["get_quote"] = Field(
        "get_quote",
        json_schema_extra={
            "const": "get_quote",
            "ui:hidden": True,
            "x-category": "Quote",
            "x-is-trigger": False,
            "x-display-name": "Get Quote",
            "x-keywords": [
                "fetch quote",
                "quote details",
                "sales quote",
                "proposal",
                "quote by id",
            ],
        },
        title="Get Quote",
    )
    quote_id: str = Field(
        ..., title="Quote ID", description="The unique identifier of the quote"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateQuoteConfig(BaseModel):
    model_config = ConfigDict(title="Create Quote")
    """Create a new quote"""
    operation: Literal["create_quote"] = Field(
        "create_quote",
        json_schema_extra={
            "const": "create_quote",
            "ui:hidden": True,
            "x-category": "Quote",
            "x-is-trigger": False,
            "x-display-name": "Create Quote",
            "x-keywords": [
                "new quote",
                "draft quote",
                "generate quote",
                "make proposal",
                "build sales quote",
            ],
        },
        title="Create Quote",
    )
    hs_title: str = Field(
        ..., title="Quote Title", description="The title of the quote"
    )
    hs_expiration_date: Optional[str] = Field(
        None,
        title="Expiration Date",
        description="Quote expiration date (ISO 8601 format)",
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateQuoteConfig(BaseModel):
    model_config = ConfigDict(title="Update Quote")
    """Update an existing quote"""
    operation: Literal["update_quote"] = Field(
        "update_quote",
        json_schema_extra={
            "const": "update_quote",
            "ui:hidden": True,
            "x-category": "Quote",
            "x-is-trigger": False,
            "x-display-name": "Update Quote",
            "x-keywords": [
                "edit quote",
                "modify quote",
                "change quote",
                "revise proposal",
                "update sales quote",
            ],
        },
        title="Update Quote",
    )
    quote_id: str = Field(
        ...,
        title="Quote ID",
        description="The unique identifier of the quote to update",
    )
    hs_title: Optional[str] = Field(
        None, title="Quote Title", description="The title of the quote"
    )
    hs_expiration_date: Optional[str] = Field(
        None, title="Expiration Date", description="Quote expiration date"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteQuoteConfig(BaseModel):
    model_config = ConfigDict(title="Delete Quote")
    """Delete a quote"""
    operation: Literal["delete_quote"] = Field(
        "delete_quote",
        json_schema_extra={
            "const": "delete_quote",
            "ui:hidden": True,
            "x-category": "Quote",
            "x-is-trigger": False,
            "x-display-name": "Delete Quote",
            "x-keywords": [
                "remove quote",
                "delete proposal",
                "trash quote",
                "discard sales quote",
            ],
        },
        title="Delete Quote",
    )
    quote_id: str = Field(
        ...,
        title="Quote ID",
        description="The unique identifier of the quote to delete",
    )


class HubSpotSearchQuotesConfig(BaseModel):
    model_config = ConfigDict(title="Search Quotes")
    """Search for quotes"""
    operation: Literal["search_quotes"] = Field(
        "search_quotes",
        json_schema_extra={
            "const": "search_quotes",
            "ui:hidden": True,
            "x-category": "Quote",
            "x-is-trigger": False,
            "x-display-name": "Search Quotes",
            "x-keywords": [
                "find quotes",
                "filter quotes",
                "query proposals",
                "lookup sales quotes",
            ],
        },
        title="Search Quotes",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Note Operation Configs
# ============================================================================


class HubSpotListNotesConfig(BaseModel):
    model_config = ConfigDict(title="List Notes")
    """List all notes with pagination"""
    operation: Literal["list_note_activities"] = Field(
        "list_note_activities",
        json_schema_extra={
            "const": "list_note_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "List Note Activities",
            "x-keywords": [
                "all notes",
                "notes log",
                "crm notes",
                "engagement notes",
                "view notes",
            ],
        },
        title="List Note Activities",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of notes to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetNoteConfig(BaseModel):
    model_config = ConfigDict(title="Get Note")
    """Get a specific note by ID"""
    operation: Literal["get_note_activity"] = Field(
        "get_note_activity",
        json_schema_extra={
            "const": "get_note_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Get Note Activity",
            "x-keywords": ["note details", "single note", "note by id", "read note"],
        },
        title="Get Note Activity",
    )
    note_id: str = Field(
        ..., title="Note ID", description="The unique identifier of the note"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateNoteConfig(BaseModel):
    model_config = ConfigDict(title="Create Note")
    """Create a new note"""
    operation: Literal["create_note_activity"] = Field(
        "create_note_activity",
        json_schema_extra={
            "const": "create_note_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Note Activity",
            "x-keywords": [
                "log note",
                "add note",
                "write note",
                "attach note",
                "record note",
            ],
        },
        title="Create Note Activity",
    )
    hs_note_body: str = Field(
        ...,
        title="Note Body",
        description="The content of the note",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_timestamp: Optional[str] = Field(
        None, title="Timestamp", description="Timestamp for the note (ISO 8601 format)"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateNoteConfig(BaseModel):
    model_config = ConfigDict(title="Update Note")
    """Update an existing note"""
    operation: Literal["update_note_activity"] = Field(
        "update_note_activity",
        json_schema_extra={
            "const": "update_note_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Update Note Activity",
            "x-keywords": [
                "edit note",
                "modify note",
                "revise note",
                "change note text",
            ],
        },
        title="Update Note Activity",
    )
    note_id: str = Field(
        ..., title="Note ID", description="The unique identifier of the note to update"
    )
    hs_note_body: Optional[str] = Field(
        None,
        title="Note Body",
        description="The content of the note",
        json_schema_extra={"ui:widget": "textarea"},
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteNoteConfig(BaseModel):
    model_config = ConfigDict(title="Delete Note")
    """Delete a note"""
    operation: Literal["delete_note_activity"] = Field(
        "delete_note_activity",
        json_schema_extra={
            "const": "delete_note_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Delete Note Activity",
            "x-keywords": ["remove note", "delete note", "trash note"],
        },
        title="Delete Note Activity",
    )
    note_id: str = Field(
        ..., title="Note ID", description="The unique identifier of the note to delete"
    )


class HubSpotSearchNotesConfig(BaseModel):
    model_config = ConfigDict(title="Search Notes")
    """Search for notes"""
    operation: Literal["search_note_activities"] = Field(
        "search_note_activities",
        json_schema_extra={
            "const": "search_note_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Note Activities",
            "x-keywords": ["find notes", "filter notes", "query notes", "lookup notes"],
        },
        title="Search Note Activities",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Task Operation Configs
# ============================================================================


class HubSpotListTasksConfig(BaseModel):
    model_config = ConfigDict(title="List Tasks")
    """List all tasks with pagination"""
    operation: Literal["list_task_activities"] = Field(
        "list_task_activities",
        json_schema_extra={
            "const": "list_task_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "List Task Activities",
            "x-keywords": [
                "all tasks",
                "todo list",
                "task log",
                "crm tasks",
                "view tasks",
            ],
        },
        title="List Task Activities",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of tasks to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetTaskConfig(BaseModel):
    model_config = ConfigDict(title="Get Task")
    """Get a specific task by ID"""
    operation: Literal["get_task_activity"] = Field(
        "get_task_activity",
        json_schema_extra={
            "const": "get_task_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Get Task Activity",
            "x-keywords": ["task details", "single task", "task by id", "read todo"],
        },
        title="Get Task Activity",
    )
    task_id: str = Field(
        ..., title="Task ID", description="The unique identifier of the task"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateTaskConfig(BaseModel):
    model_config = ConfigDict(title="Create Task")
    """Create a new task"""
    operation: Literal["create_task_activity"] = Field(
        "create_task_activity",
        json_schema_extra={
            "const": "create_task_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Task Activity",
            "x-keywords": [
                "log task",
                "add task",
                "new todo",
                "assign task",
                "schedule followup",
            ],
        },
        title="Create Task Activity",
    )
    hs_task_subject: str = Field(
        ..., title="Task Subject", description="The subject of the task"
    )
    hs_task_body: Optional[str] = Field(
        None,
        title="Task Body",
        description="Task description/body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_task_status: Optional[str] = Field(
        None,
        title="Task Status",
        description="Task status",
        json_schema_extra={
            "enum": ["NOT_STARTED", "IN_PROGRESS", "COMPLETED", "WAITING", "DEFERRED"]
        },
    )
    hs_task_priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Task priority",
        json_schema_extra={"enum": ["LOW", "MEDIUM", "HIGH"]},
    )
    hs_timestamp: Optional[str] = Field(
        None, title="Due Date", description="Task due date (ISO 8601 format)"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateTaskConfig(BaseModel):
    model_config = ConfigDict(title="Update Task")
    """Update an existing task"""
    operation: Literal["update_task_activity"] = Field(
        "update_task_activity",
        json_schema_extra={
            "const": "update_task_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Update Task Activity",
            "x-keywords": [
                "edit task",
                "modify task",
                "complete task",
                "change todo",
                "reassign task",
            ],
        },
        title="Update Task Activity",
    )
    task_id: str = Field(
        ..., title="Task ID", description="The unique identifier of the task to update"
    )
    hs_task_subject: Optional[str] = Field(
        None, title="Task Subject", description="The subject of the task"
    )
    hs_task_body: Optional[str] = Field(
        None,
        title="Task Body",
        description="Task description/body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_task_status: Optional[str] = Field(
        None,
        title="Task Status",
        description="Task status",
        json_schema_extra={
            "enum": ["NOT_STARTED", "IN_PROGRESS", "COMPLETED", "WAITING", "DEFERRED"]
        },
    )
    hs_task_priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Task priority",
        json_schema_extra={"enum": ["LOW", "MEDIUM", "HIGH"]},
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteTaskConfig(BaseModel):
    model_config = ConfigDict(title="Delete Task")
    """Delete a task"""
    operation: Literal["delete_task_activity"] = Field(
        "delete_task_activity",
        json_schema_extra={
            "const": "delete_task_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Delete Task Activity",
            "x-keywords": ["remove task", "delete task", "trash todo"],
        },
        title="Delete Task Activity",
    )
    task_id: str = Field(
        ..., title="Task ID", description="The unique identifier of the task to delete"
    )


class HubSpotSearchTasksConfig(BaseModel):
    model_config = ConfigDict(title="Search Tasks")
    """Search for tasks"""
    operation: Literal["search_task_activities"] = Field(
        "search_task_activities",
        json_schema_extra={
            "const": "search_task_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Task Activities",
            "x-keywords": ["find tasks", "filter tasks", "query todos", "lookup tasks"],
        },
        title="Search Task Activities",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Call Operation Configs (Activity/Engagement)
# ============================================================================


class HubSpotListCallsConfig(BaseModel):
    model_config = ConfigDict(title="List Calls")
    """List all calls with pagination"""
    operation: Literal["list_call_activities"] = Field(
        "list_call_activities",
        json_schema_extra={
            "const": "list_call_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "List Call Activities",
            "x-keywords": [
                "all calls",
                "call log",
                "phone log",
                "logged calls",
                "view calls",
            ],
        },
        title="List Call Activities",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of calls to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetCallConfig(BaseModel):
    model_config = ConfigDict(title="Get Call")
    """Get a specific call by ID"""
    operation: Literal["get_call_activity"] = Field(
        "get_call_activity",
        json_schema_extra={
            "const": "get_call_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Get Call Activity",
            "x-keywords": [
                "call details",
                "single call",
                "call by id",
                "read call log",
            ],
        },
        title="Get Call Activity",
    )
    call_id: str = Field(
        ..., title="Call ID", description="The unique identifier of the call"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateCallConfig(BaseModel):
    model_config = ConfigDict(title="Create Call")
    """Create a new call record"""
    operation: Literal["create_call_activity"] = Field(
        "create_call_activity",
        json_schema_extra={
            "const": "create_call_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Call Activity",
            "x-keywords": ["log call", "record call", "add call", "track phone call"],
        },
        title="Create Call Activity",
    )
    hs_call_title: Optional[str] = Field(
        None, title="Call Title", description="Title of the call"
    )
    hs_call_body: Optional[str] = Field(
        None,
        title="Call Body/Notes",
        description="Call notes/body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_call_duration: Optional[str] = Field(
        None, title="Duration (ms)", description="Call duration in milliseconds"
    )
    hs_call_status: Optional[str] = Field(
        None,
        title="Call Status",
        description="Status of the call",
        json_schema_extra={
            "enum": [
                "BUSY",
                "CALLING_CRM_USER",
                "CANCELED",
                "COMPLETED",
                "CONNECTING",
                "FAILED",
                "IN_PROGRESS",
                "NO_ANSWER",
                "QUEUED",
                "RINGING",
            ]
        },
    )
    hs_timestamp: Optional[str] = Field(
        None, title="Timestamp", description="Timestamp of the call (ISO 8601)"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateCallConfig(BaseModel):
    model_config = ConfigDict(title="Update Call")
    """Update an existing call record"""
    operation: Literal["update_call_activity"] = Field(
        "update_call_activity",
        json_schema_extra={
            "const": "update_call_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Update Call Activity",
            "x-keywords": [
                "edit call",
                "modify call log",
                "change call notes",
                "update call record",
            ],
        },
        title="Update Call Activity",
    )
    call_id: str = Field(
        ..., title="Call ID", description="The unique identifier of the call to update"
    )
    hs_call_title: Optional[str] = Field(
        None, title="Call Title", description="Title of the call"
    )
    hs_call_body: Optional[str] = Field(
        None,
        title="Call Body/Notes",
        description="Call notes/body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_call_duration: Optional[str] = Field(
        None, title="Duration (ms)", description="Call duration in milliseconds"
    )
    hs_call_status: Optional[str] = Field(
        None, title="Call Status", description="Status of the call"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteCallConfig(BaseModel):
    model_config = ConfigDict(title="Delete Call")
    """Delete a call record"""
    operation: Literal["delete_call_activity"] = Field(
        "delete_call_activity",
        json_schema_extra={
            "const": "delete_call_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Delete Call Activity",
            "x-keywords": ["remove call", "delete call log", "trash call"],
        },
        title="Delete Call Activity",
    )
    call_id: str = Field(
        ..., title="Call ID", description="The unique identifier of the call to delete"
    )


class HubSpotSearchCallsConfig(BaseModel):
    model_config = ConfigDict(title="Search Calls")
    """Search for calls"""
    operation: Literal["search_call_activities"] = Field(
        "search_call_activities",
        json_schema_extra={
            "const": "search_call_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Call Activities",
            "x-keywords": [
                "find calls",
                "filter calls",
                "query call log",
                "lookup phone calls",
            ],
        },
        title="Search Call Activities",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Meeting Operation Configs (Activity/Engagement)
# ============================================================================


class HubSpotListMeetingsConfig(BaseModel):
    model_config = ConfigDict(title="List Meetings")
    """List all meetings with pagination"""
    operation: Literal["list_meeting_activities"] = Field(
        "list_meeting_activities",
        json_schema_extra={
            "const": "list_meeting_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "List Meeting Activities",
            "x-keywords": [
                "all meetings",
                "meeting log",
                "logged meetings",
                "crm meetings",
                "view meetings",
            ],
        },
        title="List Meeting Activities",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of meetings to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetMeetingConfig(BaseModel):
    model_config = ConfigDict(title="Get Meeting")
    """Get a specific meeting by ID"""
    operation: Literal["get_meeting_activity"] = Field(
        "get_meeting_activity",
        json_schema_extra={
            "const": "get_meeting_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Get Meeting Activity",
            "x-keywords": [
                "meeting details",
                "single meeting",
                "meeting by id",
                "read meeting",
            ],
        },
        title="Get Meeting Activity",
    )
    meeting_id: str = Field(
        ..., title="Meeting ID", description="The unique identifier of the meeting"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateMeetingConfig(BaseModel):
    model_config = ConfigDict(title="Create Meeting")
    """Create a new meeting record"""
    operation: Literal["create_meeting_activity"] = Field(
        "create_meeting_activity",
        json_schema_extra={
            "const": "create_meeting_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Meeting Activity",
            "x-keywords": [
                "log meeting",
                "record meeting",
                "add meeting",
                "book appointment",
            ],
        },
        title="Create Meeting Activity",
    )
    hs_meeting_title: str = Field(
        ..., title="Meeting Title", description="Title of the meeting"
    )
    hs_meeting_body: Optional[str] = Field(
        None,
        title="Meeting Notes",
        description="Meeting notes/description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_meeting_start_time: Optional[str] = Field(
        None, title="Start Time", description="Meeting start time (ISO 8601)"
    )
    hs_meeting_end_time: Optional[str] = Field(
        None, title="End Time", description="Meeting end time (ISO 8601)"
    )
    hs_meeting_outcome: Optional[str] = Field(
        None,
        title="Meeting Outcome",
        description="Outcome of the meeting",
        json_schema_extra={
            "enum": ["SCHEDULED", "COMPLETED", "RESCHEDULED", "NO_SHOW", "CANCELED"]
        },
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateMeetingConfig(BaseModel):
    model_config = ConfigDict(title="Update Meeting")
    """Update an existing meeting record"""
    operation: Literal["update_meeting_activity"] = Field(
        "update_meeting_activity",
        json_schema_extra={
            "const": "update_meeting_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Update Meeting Activity",
            "x-keywords": [
                "edit meeting",
                "modify meeting",
                "reschedule meeting",
                "change appointment",
            ],
        },
        title="Update Meeting Activity",
    )
    meeting_id: str = Field(
        ...,
        title="Meeting ID",
        description="The unique identifier of the meeting to update",
    )
    hs_meeting_title: Optional[str] = Field(
        None, title="Meeting Title", description="Title of the meeting"
    )
    hs_meeting_body: Optional[str] = Field(
        None,
        title="Meeting Notes",
        description="Meeting notes/description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_meeting_outcome: Optional[str] = Field(
        None, title="Meeting Outcome", description="Outcome of the meeting"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteMeetingConfig(BaseModel):
    model_config = ConfigDict(title="Delete Meeting")
    """Delete a meeting record"""
    operation: Literal["delete_meeting_activity"] = Field(
        "delete_meeting_activity",
        json_schema_extra={
            "const": "delete_meeting_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Delete Meeting Activity",
            "x-keywords": ["remove meeting", "delete meeting", "cancel appointment"],
        },
        title="Delete Meeting Activity",
    )
    meeting_id: str = Field(
        ...,
        title="Meeting ID",
        description="The unique identifier of the meeting to delete",
    )


class HubSpotSearchMeetingsConfig(BaseModel):
    model_config = ConfigDict(title="Search Meetings")
    """Search for meetings"""
    operation: Literal["search_meeting_activities"] = Field(
        "search_meeting_activities",
        json_schema_extra={
            "const": "search_meeting_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Meeting Activities",
            "x-keywords": [
                "find meetings",
                "filter meetings",
                "query meetings",
                "lookup appointments",
            ],
        },
        title="Search Meeting Activities",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Email Operation Configs (Activity/Engagement)
# ============================================================================


class HubSpotListEmailsConfig(BaseModel):
    model_config = ConfigDict(title="List Emails")
    """List all email engagements with pagination"""
    operation: Literal["list_email_activities"] = Field(
        "list_email_activities",
        json_schema_extra={
            "const": "list_email_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "List Email Activities",
            "x-keywords": [
                "all logged emails",
                "email log",
                "logged emails",
                "crm email history",
                "view emails",
            ],
        },
        title="List Email Activities",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of emails to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetEmailConfig(BaseModel):
    model_config = ConfigDict(title="Get Email")
    """Get a specific email engagement by ID"""
    operation: Literal["get_email_activity"] = Field(
        "get_email_activity",
        json_schema_extra={
            "const": "get_email_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Get Email Activity",
            "x-keywords": [
                "email details",
                "single logged email",
                "email by id",
                "read logged email",
            ],
        },
        title="Get Email Activity",
    )
    email_id: str = Field(
        ..., title="Email ID", description="The unique identifier of the email"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateEmailConfig(BaseModel):
    model_config = ConfigDict(title="Create Email")
    """Create a new email engagement record"""
    operation: Literal["create_email_activity"] = Field(
        "create_email_activity",
        json_schema_extra={
            "const": "create_email_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Create Email Activity",
            "x-keywords": [
                "log email",
                "record email",
                "add email engagement",
                "track email",
            ],
        },
        title="Create Email Activity",
    )
    hs_email_subject: str = Field(
        ..., title="Email Subject", description="Subject of the email"
    )
    hs_email_text: Optional[str] = Field(
        None,
        title="Email Body",
        description="Email body/text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_email_direction: Optional[str] = Field(
        None,
        title="Direction",
        description="Email direction",
        json_schema_extra={"enum": ["EMAIL", "INCOMING_EMAIL", "FORWARDED_EMAIL"]},
    )
    hs_email_status: Optional[str] = Field(
        None,
        title="Status",
        description="Email status",
        json_schema_extra={
            "enum": ["BOUNCED", "FAILED", "SCHEDULED", "SENDING", "SENT"]
        },
    )
    hs_timestamp: Optional[str] = Field(
        None, title="Timestamp", description="Email timestamp (ISO 8601)"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateEmailConfig(BaseModel):
    model_config = ConfigDict(title="Update Email")
    """Update an existing email engagement record"""
    operation: Literal["update_email_activity"] = Field(
        "update_email_activity",
        json_schema_extra={
            "const": "update_email_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Update Email Activity",
            "x-keywords": [
                "edit logged email",
                "modify email engagement",
                "change email record",
            ],
        },
        title="Update Email Activity",
    )
    email_id: str = Field(
        ...,
        title="Email ID",
        description="The unique identifier of the email to update",
    )
    hs_email_subject: Optional[str] = Field(
        None, title="Email Subject", description="Subject of the email"
    )
    hs_email_text: Optional[str] = Field(
        None,
        title="Email Body",
        description="Email body/text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    hs_email_status: Optional[str] = Field(
        None, title="Status", description="Email status"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteEmailConfig(BaseModel):
    model_config = ConfigDict(title="Delete Email")
    """Delete an email engagement record"""
    operation: Literal["delete_email_activity"] = Field(
        "delete_email_activity",
        json_schema_extra={
            "const": "delete_email_activity",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Activity",
            "x-keywords": [
                "remove logged email",
                "delete email engagement",
                "trash logged email",
            ],
        },
        title="Delete Email Activity",
    )
    email_id: str = Field(
        ...,
        title="Email ID",
        description="The unique identifier of the email to delete",
    )


class HubSpotSearchEmailsConfig(BaseModel):
    model_config = ConfigDict(title="Search Emails")
    """Search for email engagements"""
    operation: Literal["search_email_activities"] = Field(
        "search_email_activities",
        json_schema_extra={
            "const": "search_email_activities",
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "Search Email Activities",
            "x-keywords": [
                "find logged emails",
                "filter email engagements",
                "query email log",
                "lookup logged emails",
            ],
        },
        title="Search Email Activities",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Commerce: Order Operation Configs
# ============================================================================


class HubSpotListOrdersConfig(BaseModel):
    model_config = ConfigDict(title="List Orders")
    """List all orders with pagination"""
    operation: Literal["list_orders"] = Field(
        "list_orders",
        json_schema_extra={
            "const": "list_orders",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "List Orders",
            "x-keywords": [
                "all orders",
                "order list",
                "commerce orders",
                "view orders",
                "purchases",
            ],
        },
        title="List Orders",
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of orders to return (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotGetOrderConfig(BaseModel):
    model_config = ConfigDict(title="Get Order")
    """Get a specific order by ID"""
    operation: Literal["get_order"] = Field(
        "get_order",
        json_schema_extra={
            "const": "get_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Get Order",
            "x-keywords": [
                "order details",
                "single order",
                "order by id",
                "read order",
            ],
        },
        title="Get Order",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The unique identifier of the order"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotCreateOrderConfig(BaseModel):
    model_config = ConfigDict(title="Create Order")
    """Create a new order"""
    operation: Literal["create_order"] = Field(
        "create_order",
        json_schema_extra={
            "const": "create_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Create Order",
            "x-keywords": [
                "new order",
                "add order",
                "place order",
                "make purchase order",
            ],
        },
        title="Create Order",
    )
    hs_order_name: Optional[str] = Field(
        None, title="Order Name", description="Name/title of the order"
    )
    hs_order_amount: Optional[str] = Field(
        None, title="Order Amount", description="Total order amount"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateOrderConfig(BaseModel):
    model_config = ConfigDict(title="Update Order")
    """Update an existing order"""
    operation: Literal["update_order"] = Field(
        "update_order",
        json_schema_extra={
            "const": "update_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Update Order",
            "x-keywords": [
                "edit order",
                "modify order",
                "change order",
                "update purchase",
            ],
        },
        title="Update Order",
    )
    order_id: str = Field(
        ...,
        title="Order ID",
        description="The unique identifier of the order to update",
    )
    hs_order_name: Optional[str] = Field(
        None, title="Order Name", description="Name/title of the order"
    )
    hs_order_amount: Optional[str] = Field(
        None, title="Order Amount", description="Total order amount"
    )
    additional_properties: Optional[str] = Field(
        None,
        title="Additional Properties",
        description="JSON object with additional properties to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteOrderConfig(BaseModel):
    model_config = ConfigDict(title="Delete Order")
    """Delete an order"""
    operation: Literal["delete_order"] = Field(
        "delete_order",
        json_schema_extra={
            "const": "delete_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Delete Order",
            "x-keywords": ["remove order", "delete order", "cancel order"],
        },
        title="Delete Order",
    )
    order_id: str = Field(
        ...,
        title="Order ID",
        description="The unique identifier of the order to delete",
    )


class HubSpotSearchOrdersConfig(BaseModel):
    model_config = ConfigDict(title="Search Orders")
    """Search for orders"""
    operation: Literal["search_orders"] = Field(
        "search_orders",
        json_schema_extra={
            "const": "search_orders",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Search Orders",
            "x-keywords": [
                "find orders",
                "filter orders",
                "query purchases",
                "lookup orders",
            ],
        },
        title="Search Orders",
    )
    query: Optional[str] = Field(
        None, title="Search Query", description="Text to search for"
    )
    filter_property: Optional[str] = Field(
        None, title="Filter Property", description="Property name to filter on"
    )
    filter_operator: Optional[str] = Field(
        "EQ",
        title="Filter Operator",
        description="Filter operator",
        json_schema_extra={
            "enum": [
                "EQ",
                "NEQ",
                "LT",
                "LTE",
                "GT",
                "GTE",
                "CONTAINS_TOKEN",
                "NOT_CONTAINS_TOKEN",
            ]
        },
    )
    filter_value: Optional[str] = Field(
        None, title="Filter Value", description="Value to filter by"
    )
    limit: Optional[int] = Field(
        10,
        title="Limit",
        description="Maximum number of results (max 100)",
        ge=1,
        le=100,
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


# ============================================================================
# Owners API Config (System API)
# ============================================================================


class HubSpotListOwnersConfig(BaseModel):
    model_config = ConfigDict(title="List Owners")
    """List all owners (users) in the HubSpot account"""
    operation: Literal["list_account_owners"] = Field(
        "list_account_owners",
        json_schema_extra={
            "const": "list_account_owners",
            "ui:hidden": True,
            "x-category": "Owner",
            "x-is-trigger": False,
            "x-display-name": "List Account Owners",
            "x-keywords": [
                "all owners",
                "crm owners",
                "sales reps",
                "assigned owners",
                "account managers",
            ],
        },
        title="List Account Owners",
    )
    limit: Optional[int] = Field(
        100,
        title="Limit",
        description="Maximum number of owners to return",
        ge=1,
        le=500,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )


# ============================================================================
# Associations API Configs (Cross-Object Operations)
# ============================================================================


class HubSpotCreateAssociationConfig(BaseModel):
    model_config = ConfigDict(title="Create Association")
    """Create an association between two CRM objects"""
    operation: Literal["create_record_association"] = Field(
        "create_record_association",
        json_schema_extra={
            "const": "create_record_association",
            "ui:hidden": True,
            "x-category": "Association",
            "x-is-trigger": False,
            "x-display-name": "Create Record Association",
            "x-keywords": [
                "link records",
                "associate records",
                "connect contact to deal",
                "relate objects",
                "add association",
            ],
        },
        title="Create Record Association",
    )
    from_object_type: str = Field(
        ...,
        title="From Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    from_object_id: str = Field(
        ..., title="From Object ID", description="ID of the source object"
    )
    to_object_type: str = Field(
        ...,
        title="To Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    to_object_id: str = Field(
        ..., title="To Object ID", description="ID of the target object"
    )
    association_type_id: str = Field(
        ...,
        title="Association Type ID",
        description="Association type ID (e.g., '1' for contact_to_company)",
    )


class HubSpotDeleteAssociationConfig(BaseModel):
    model_config = ConfigDict(title="Delete Association")
    """Delete an association between two CRM objects"""
    operation: Literal["delete_record_association"] = Field(
        "delete_record_association",
        json_schema_extra={
            "const": "delete_record_association",
            "ui:hidden": True,
            "x-category": "Association",
            "x-is-trigger": False,
            "x-display-name": "Delete Record Association",
            "x-keywords": [
                "unlink records",
                "remove association",
                "disconnect records",
                "detach objects",
            ],
        },
        title="Delete Record Association",
    )
    from_object_type: str = Field(
        ...,
        title="From Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    from_object_id: str = Field(
        ..., title="From Object ID", description="ID of the source object"
    )
    to_object_type: str = Field(
        ...,
        title="To Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    to_object_id: str = Field(
        ..., title="To Object ID", description="ID of the target object"
    )
    association_type_id: str = Field(
        ..., title="Association Type ID", description="Association type ID to remove"
    )


class HubSpotListAssociationsConfig(BaseModel):
    model_config = ConfigDict(title="List Associations")
    """List all associations for a specific object"""
    operation: Literal["list_record_associations"] = Field(
        "list_record_associations",
        json_schema_extra={
            "const": "list_record_associations",
            "ui:hidden": True,
            "x-category": "Association",
            "x-is-trigger": False,
            "x-display-name": "List Record Associations",
            "x-keywords": [
                "view associations",
                "linked records",
                "related records",
                "show connections",
            ],
        },
        title="List Record Associations",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    object_id: str = Field(..., title="Object ID", description="ID of the object")
    to_object_type: str = Field(
        ...,
        title="To Object Type",
        description="Target object type to filter associations",
    )


# ============================================================================
# Properties API Configs (System API)
# ============================================================================


class HubSpotListPropertiesConfig(BaseModel):
    model_config = ConfigDict(title="List Properties")
    """List all properties for a CRM object type"""
    operation: Literal["list_custom_properties"] = Field(
        "list_custom_properties",
        json_schema_extra={
            "const": "list_custom_properties",
            "ui:hidden": True,
            "x-category": "Property",
            "x-is-trigger": False,
            "x-display-name": "List Custom Properties",
            "x-keywords": [
                "all properties",
                "property fields",
                "custom fields",
                "view properties",
                "object fields",
            ],
        },
        title="List Custom Properties",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals', 'tickets')",
    )
    data_sensitivity: Optional[str] = Field(
        None,
        title="Data Sensitivity",
        description="Set to 'sensitive' to include sensitive properties (Enterprise only)",
    )


class HubSpotGetPropertyConfig(BaseModel):
    model_config = ConfigDict(title="Get Property")
    """Get a specific property by name"""
    operation: Literal["get_custom_property"] = Field(
        "get_custom_property",
        json_schema_extra={
            "const": "get_custom_property",
            "ui:hidden": True,
            "x-category": "Property",
            "x-is-trigger": False,
            "x-display-name": "Get Custom Property",
            "x-keywords": [
                "property details",
                "single property",
                "field definition",
                "read property",
            ],
        },
        title="Get Custom Property",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    property_name: str = Field(
        ...,
        title="Property Name",
        description="Internal name of the property (e.g., 'email', 'firstname')",
    )


class HubSpotCreatePropertyConfig(BaseModel):
    model_config = ConfigDict(title="Create Property")
    """Create a new custom property for a CRM object"""
    operation: Literal["create_custom_property"] = Field(
        "create_custom_property",
        json_schema_extra={
            "const": "create_custom_property",
            "ui:hidden": True,
            "x-category": "Property",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Property",
            "x-keywords": [
                "new property",
                "add custom field",
                "define property",
                "make field",
            ],
        },
        title="Create Custom Property",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    group_name: str = Field(
        ...,
        title="Group Name",
        description="Property group (e.g., 'contactinformation')",
    )
    name: str = Field(
        ..., title="Name", description="Internal property name (e.g., 'favorite_food')"
    )
    label: str = Field(
        ..., title="Label", description="Display label (e.g., 'Favorite Food')"
    )
    type: str = Field(
        ...,
        title="Type",
        description="Data type",
        json_schema_extra={
            "enum": ["string", "number", "date", "datetime", "enumeration", "bool"]
        },
    )
    field_type: str = Field(
        ...,
        title="Field Type",
        description="UI field type",
        json_schema_extra={
            "enum": [
                "text",
                "textarea",
                "number",
                "date",
                "select",
                "radio",
                "checkbox",
                "booleancheckbox",
                "calculation_equation",
            ]
        },
    )
    description: Optional[str] = Field(
        None, title="Description", description="Property description"
    )
    has_unique_value: Optional[bool] = Field(
        None,
        title="Has Unique Value",
        description="Whether values must be unique across records (max 10 per object)",
    )


class HubSpotUpdatePropertyConfig(BaseModel):
    model_config = ConfigDict(title="Update Property")
    """Update an existing property"""
    operation: Literal["update_custom_property"] = Field(
        "update_custom_property",
        json_schema_extra={
            "const": "update_custom_property",
            "ui:hidden": True,
            "x-category": "Property",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Property",
            "x-keywords": [
                "edit property",
                "modify field",
                "change property",
                "rename field",
            ],
        },
        title="Update Custom Property",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    property_name: str = Field(
        ...,
        title="Property Name",
        description="Internal name of the property to update",
    )
    label: Optional[str] = Field(None, title="Label", description="New display label")
    description: Optional[str] = Field(
        None, title="Description", description="New description"
    )
    group_name: Optional[str] = Field(
        None, title="Group Name", description="New property group"
    )
    additional_fields: Optional[str] = Field(
        None,
        title="Additional Fields",
        description="JSON object with additional fields to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotArchivePropertyConfig(BaseModel):
    model_config = ConfigDict(title="Archive Property")
    """Archive (delete) a property"""
    operation: Literal["archive_custom_property"] = Field(
        "archive_custom_property",
        json_schema_extra={
            "const": "archive_custom_property",
            "ui:hidden": True,
            "x-category": "Property",
            "x-is-trigger": False,
            "x-display-name": "Archive Custom Property",
            "x-keywords": [
                "remove property",
                "archive field",
                "disable property",
                "hide custom field",
            ],
        },
        title="Archive Custom Property",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    property_name: str = Field(
        ...,
        title="Property Name",
        description="Internal name of the property to archive",
    )


# ============================================================================
# Pipelines API Configs (System API)
# ============================================================================


class HubSpotListPipelinesConfig(BaseModel):
    model_config = ConfigDict(title="List Pipelines")
    """List all pipelines for an object type"""
    operation: Literal["list_pipelines"] = Field(
        "list_pipelines",
        json_schema_extra={
            "const": "list_pipelines",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "List Pipelines",
            "x-keywords": [
                "deal pipelines",
                "all pipelines",
                "sales pipelines",
                "ticket pipelines",
            ],
        },
        title="List Pipelines",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )


class HubSpotGetPipelineConfig(BaseModel):
    model_config = ConfigDict(title="Get Pipeline")
    """Get a specific pipeline by ID"""
    operation: Literal["get_pipeline"] = Field(
        "get_pipeline",
        json_schema_extra={
            "const": "get_pipeline",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Get Pipeline",
            "x-keywords": [
                "pipeline details",
                "single pipeline",
                "fetch pipeline",
                "one pipeline",
            ],
        },
        title="Get Pipeline",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )


class HubSpotCreatePipelineConfig(BaseModel):
    model_config = ConfigDict(title="Create Pipeline")
    """Create a new pipeline"""
    operation: Literal["create_pipeline"] = Field(
        "create_pipeline",
        json_schema_extra={
            "const": "create_pipeline",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Create Pipeline",
            "x-keywords": [
                "new pipeline",
                "add pipeline",
                "build sales pipeline",
                "set up pipeline",
            ],
        },
        title="Create Pipeline",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    label: str = Field(..., title="Label", description="Display name for the pipeline")
    display_order: Optional[int] = Field(
        None,
        title="Display Order",
        description="Order in which the pipeline is displayed",
    )
    stages: Optional[str] = Field(
        None,
        title="Stages",
        description="JSON array of stage objects with label and metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdatePipelineConfig(BaseModel):
    model_config = ConfigDict(title="Update Pipeline")
    """Update an existing pipeline"""
    operation: Literal["update_pipeline"] = Field(
        "update_pipeline",
        json_schema_extra={
            "const": "update_pipeline",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Update Pipeline",
            "x-keywords": [
                "edit pipeline",
                "rename pipeline",
                "patch pipeline",
                "modify pipeline",
            ],
        },
        title="Update Pipeline",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ...,
        title="Pipeline ID",
        description="The unique identifier of the pipeline to update",
    )
    label: Optional[str] = Field(
        None, title="Label", description="New display name for the pipeline"
    )
    display_order: Optional[int] = Field(
        None, title="Display Order", description="New display order"
    )


class HubSpotReplacePipelineConfig(BaseModel):
    model_config = ConfigDict(title="Replace Pipeline")
    """Replace (overwrite) an existing pipeline"""
    operation: Literal["replace_pipeline"] = Field(
        "replace_pipeline",
        json_schema_extra={
            "const": "replace_pipeline",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Replace Pipeline",
            "x-keywords": [
                "overwrite pipeline",
                "replace whole pipeline",
                "full pipeline update",
                "put pipeline",
            ],
        },
        title="Replace Pipeline",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ...,
        title="Pipeline ID",
        description="The unique identifier of the pipeline to replace",
    )
    label: str = Field(..., title="Label", description="Display name for the pipeline")
    display_order: Optional[int] = Field(
        None,
        title="Display Order",
        description="Order in which the pipeline is displayed",
    )
    stages: str = Field(
        ...,
        title="Stages",
        description="JSON array of stage objects with label and metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeletePipelineConfig(BaseModel):
    model_config = ConfigDict(title="Delete Pipeline")
    """Delete a pipeline"""
    operation: Literal["delete_pipeline"] = Field(
        "delete_pipeline",
        json_schema_extra={
            "const": "delete_pipeline",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Delete Pipeline",
            "x-keywords": ["remove pipeline", "drop pipeline", "destroy pipeline"],
        },
        title="Delete Pipeline",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ...,
        title="Pipeline ID",
        description="The unique identifier of the pipeline to delete",
    )


# ============================================================================
# Pipeline Stages API Configs
# ============================================================================


class HubSpotListPipelineStagesConfig(BaseModel):
    model_config = ConfigDict(title="List Pipeline Stages")
    """List all stages in a pipeline"""
    operation: Literal["list_pipeline_stages"] = Field(
        "list_pipeline_stages",
        json_schema_extra={
            "const": "list_pipeline_stages",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "List Pipeline Stages",
            "x-keywords": [
                "deal stages",
                "pipeline stages",
                "all stages",
                "ticket stages",
                "stage list",
            ],
        },
        title="List Pipeline Stages",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )


class HubSpotGetPipelineStageConfig(BaseModel):
    model_config = ConfigDict(title="Get Pipeline Stage")
    """Get a specific pipeline stage by ID"""
    operation: Literal["get_pipeline_stage"] = Field(
        "get_pipeline_stage",
        json_schema_extra={
            "const": "get_pipeline_stage",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Get Pipeline Stage",
            "x-keywords": [
                "stage details",
                "single stage",
                "fetch stage",
                "one deal stage",
            ],
        },
        title="Get Pipeline Stage",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )
    stage_id: str = Field(
        ..., title="Stage ID", description="The unique identifier of the stage"
    )


class HubSpotCreatePipelineStageConfig(BaseModel):
    model_config = ConfigDict(title="Create Pipeline Stage")
    """Create a new pipeline stage"""
    operation: Literal["create_pipeline_stage"] = Field(
        "create_pipeline_stage",
        json_schema_extra={
            "const": "create_pipeline_stage",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Create Pipeline Stage",
            "x-keywords": [
                "new stage",
                "add deal stage",
                "build pipeline stage",
                "add status",
            ],
        },
        title="Create Pipeline Stage",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )
    label: str = Field(..., title="Label", description="Display name for the stage")
    display_order: Optional[int] = Field(
        None, title="Display Order", description="Order in which the stage is displayed"
    )
    metadata: Optional[str] = Field(
        None,
        title="Metadata",
        description="JSON object with stage metadata (e.g., probability for deals)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdatePipelineStageConfig(BaseModel):
    model_config = ConfigDict(title="Update Pipeline Stage")
    """Update an existing pipeline stage"""
    operation: Literal["update_pipeline_stage"] = Field(
        "update_pipeline_stage",
        json_schema_extra={
            "const": "update_pipeline_stage",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Update Pipeline Stage",
            "x-keywords": [
                "edit stage",
                "rename stage",
                "patch stage",
                "modify deal stage",
            ],
        },
        title="Update Pipeline Stage",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )
    stage_id: str = Field(
        ...,
        title="Stage ID",
        description="The unique identifier of the stage to update",
    )
    label: Optional[str] = Field(
        None, title="Label", description="New display name for the stage"
    )
    display_order: Optional[int] = Field(
        None, title="Display Order", description="New display order"
    )
    metadata: Optional[str] = Field(
        None,
        title="Metadata",
        description="JSON object with updated metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotReplacePipelineStageConfig(BaseModel):
    model_config = ConfigDict(title="Replace Pipeline Stage")
    """Replace (overwrite) an existing pipeline stage"""
    operation: Literal["replace_pipeline_stage"] = Field(
        "replace_pipeline_stage",
        json_schema_extra={
            "const": "replace_pipeline_stage",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Replace Pipeline Stage",
            "x-keywords": [
                "overwrite stage",
                "replace whole stage",
                "full stage update",
                "put stage",
            ],
        },
        title="Replace Pipeline Stage",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )
    stage_id: str = Field(
        ...,
        title="Stage ID",
        description="The unique identifier of the stage to replace",
    )
    label: str = Field(..., title="Label", description="Display name for the stage")
    display_order: Optional[int] = Field(
        None, title="Display Order", description="Order in which the stage is displayed"
    )
    metadata: str = Field(
        ...,
        title="Metadata",
        description="JSON object with stage metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeletePipelineStageConfig(BaseModel):
    model_config = ConfigDict(title="Delete Pipeline Stage")
    """Delete a pipeline stage"""
    operation: Literal["delete_pipeline_stage"] = Field(
        "delete_pipeline_stage",
        json_schema_extra={
            "const": "delete_pipeline_stage",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Delete Pipeline Stage",
            "x-keywords": ["remove stage", "drop deal stage", "destroy stage"],
        },
        title="Delete Pipeline Stage",
    )
    object_type: str = Field(
        ..., title="Object Type", description="Object type (e.g., 'deals', 'tickets')"
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="The unique identifier of the pipeline"
    )
    stage_id: str = Field(
        ...,
        title="Stage ID",
        description="The unique identifier of the stage to delete",
    )


# ============================================================================
# Batch Operations API Configs (Generic for all CRM objects)
# ============================================================================


class HubSpotBatchCreateConfig(BaseModel):
    model_config = ConfigDict(title="Batch Create")
    """Create multiple CRM objects in a single batch"""
    operation: Literal["batch_create_records"] = Field(
        "batch_create_records",
        json_schema_extra={
            "const": "batch_create_records",
            "ui:hidden": True,
            "x-category": "Bulk Operation",
            "x-is-trigger": False,
            "x-display-name": "Batch Create Records",
            "x-keywords": [
                "bulk create",
                "mass insert",
                "create many records",
                "batch add objects",
            ],
        },
        title="Batch Create Records",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    inputs: str = Field(
        ...,
        title="Inputs",
        description="JSON array of objects with 'properties' field for each record to create",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotBatchReadConfig(BaseModel):
    model_config = ConfigDict(title="Batch Read")
    """Read multiple CRM objects by IDs in a single batch"""
    operation: Literal["batch_read_records"] = Field(
        "batch_read_records",
        json_schema_extra={
            "const": "batch_read_records",
            "ui:hidden": True,
            "x-category": "Bulk Operation",
            "x-is-trigger": False,
            "x-display-name": "Batch Read Records",
            "x-keywords": [
                "bulk fetch",
                "mass read",
                "read many records",
                "batch get objects",
            ],
        },
        title="Batch Read Records",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    inputs: str = Field(
        ...,
        title="Inputs",
        description="JSON array of objects with 'id' field for each record to read",
        json_schema_extra={"ui:widget": "textarea"},
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Comma-separated list of properties to return",
    )


class HubSpotBatchUpdateConfig(BaseModel):
    model_config = ConfigDict(title="Batch Update")
    """Update multiple CRM objects in a single batch"""
    operation: Literal["batch_update_records"] = Field(
        "batch_update_records",
        json_schema_extra={
            "const": "batch_update_records",
            "ui:hidden": True,
            "x-category": "Bulk Operation",
            "x-is-trigger": False,
            "x-display-name": "Batch Update Records",
            "x-keywords": [
                "bulk update",
                "mass edit",
                "update many records",
                "batch patch objects",
            ],
        },
        title="Batch Update Records",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    inputs: str = Field(
        ...,
        title="Inputs",
        description="JSON array of objects with 'id' and 'properties' fields for each record to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotBatchArchiveConfig(BaseModel):
    model_config = ConfigDict(title="Batch Archive")
    """Archive (delete) multiple CRM objects in a single batch"""
    operation: Literal["batch_archive_records"] = Field(
        "batch_archive_records",
        json_schema_extra={
            "const": "batch_archive_records",
            "ui:hidden": True,
            "x-category": "Bulk Operation",
            "x-is-trigger": False,
            "x-display-name": "Batch Archive Records",
            "x-keywords": [
                "bulk delete",
                "mass archive",
                "archive many records",
                "batch remove objects",
            ],
        },
        title="Batch Archive Records",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    inputs: str = Field(
        ...,
        title="Inputs",
        description="JSON array of objects with 'id' field for each record to archive",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotBatchUpsertConfig(BaseModel):
    model_config = ConfigDict(title="Batch Upsert")
    """Create or update multiple CRM objects by unique property in a single batch"""
    operation: Literal["batch_upsert_records"] = Field(
        "batch_upsert_records",
        json_schema_extra={
            "const": "batch_upsert_records",
            "ui:hidden": True,
            "x-category": "Bulk Operation",
            "x-is-trigger": False,
            "x-display-name": "Batch Upsert Records",
            "x-keywords": [
                "bulk upsert",
                "mass merge",
                "create or update records",
                "batch sync objects",
            ],
        },
        title="Batch Upsert Records",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., 'contacts', 'companies', 'deals')",
    )
    inputs: str = Field(
        ...,
        title="Inputs",
        description="JSON array of objects with 'properties', 'idProperty', and optionally 'id' fields",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Lists (Segments) API v3 Configs
# CRITICAL: v1 API sunset April 30, 2026
# ============================================================================


class HubSpotListListsConfig(BaseModel):
    model_config = ConfigDict(title="List Lists")
    """List all lists/segments"""
    operation: Literal["list_contact_lists"] = Field(
        "list_contact_lists",
        json_schema_extra={
            "const": "list_contact_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List Contact Lists",
            "x-keywords": [
                "contact lists",
                "all lists",
                "marketing lists",
                "subscriber lists",
            ],
        },
        title="List Contact Lists",
    )
    limit: Optional[int] = Field(
        100,
        title="Limit",
        description="Maximum number of lists to return",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After", description="Pagination cursor from previous response"
    )


class HubSpotGetListConfig(BaseModel):
    model_config = ConfigDict(title="Get List")
    """Get a specific list by ID"""
    operation: Literal["get_contact_list"] = Field(
        "get_contact_list",
        json_schema_extra={
            "const": "get_contact_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get Contact List",
            "x-keywords": [
                "list details",
                "single contact list",
                "fetch list",
                "one list",
            ],
        },
        title="Get Contact List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to retrieve"
    )
    include_filters: Optional[bool] = Field(
        True,
        title="Include Filters",
        description="Include list filter criteria in response",
    )


class HubSpotCreateListConfig(BaseModel):
    model_config = ConfigDict(title="Create List")
    """Create a new list/segment"""
    operation: Literal["create_contact_list"] = Field(
        "create_contact_list",
        json_schema_extra={
            "const": "create_contact_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Create Contact List",
            "x-keywords": [
                "new contact list",
                "add list",
                "make marketing list",
                "build subscriber list",
            ],
        },
        title="Create Contact List",
    )
    name: str = Field(..., title="List Name", description="Name of the list")
    object_type_id: str = Field(
        "contacts",
        title="Object Type",
        description="Object type for the list (e.g., 'contacts', 'companies')",
    )
    processing_type: Literal["MANUAL", "SNAPSHOT", "DYNAMIC"] = Field(
        "MANUAL",
        title="Processing Type",
        description="MANUAL (static), SNAPSHOT (one-time filter), or DYNAMIC (auto-updating)",
    )
    filter_branch: Optional[str] = Field(
        None,
        title="Filter Criteria",
        description="JSON object defining list filters (for SNAPSHOT/DYNAMIC lists)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateListConfig(BaseModel):
    model_config = ConfigDict(title="Update List")
    """Update an existing list"""
    operation: Literal["update_contact_list"] = Field(
        "update_contact_list",
        json_schema_extra={
            "const": "update_contact_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Update Contact List",
            "x-keywords": [
                "edit list",
                "rename contact list",
                "modify list",
                "patch list",
            ],
        },
        title="Update Contact List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to update"
    )
    name: Optional[str] = Field(
        None, title="List Name", description="Updated name of the list"
    )
    processing_type: Optional[Literal["MANUAL", "SNAPSHOT", "DYNAMIC"]] = Field(
        None, title="Processing Type", description="Updated processing type"
    )
    filter_branch: Optional[str] = Field(
        None,
        title="Filter Criteria",
        description="Updated JSON filter criteria",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteListConfig(BaseModel):
    model_config = ConfigDict(title="Delete List")
    """Delete a list"""
    operation: Literal["delete_contact_list"] = Field(
        "delete_contact_list",
        json_schema_extra={
            "const": "delete_contact_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact List",
            "x-keywords": ["remove contact list", "drop list", "destroy list"],
        },
        title="Delete Contact List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to delete"
    )


class HubSpotBatchAddListMembersConfig(BaseModel):
    model_config = ConfigDict(title="Batch Add List Members")
    """Add members to a list in batch (NEW Oct 2025)"""
    operation: Literal["add_contacts_to_list_batch"] = Field(
        "add_contacts_to_list_batch",
        json_schema_extra={
            "const": "add_contacts_to_list_batch",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Add Contacts to List Batch",
            "x-keywords": [
                "bulk add contacts",
                "enroll contacts",
                "add members to list",
                "push contacts into list",
            ],
        },
        title="Add Contacts to List Batch",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to add members to"
    )
    record_ids: str = Field(
        ...,
        title="Record IDs",
        description="JSON array of record IDs to add to the list",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Schema API Configs (Custom Object Schemas)
# Foundation for custom objects - manage object types, properties, associations
# ============================================================================


class HubSpotListSchemasConfig(BaseModel):
    model_config = ConfigDict(title="List Schemas")
    """List all custom object schemas"""
    operation: Literal["list_custom_object_schemas"] = Field(
        "list_custom_object_schemas",
        json_schema_extra={
            "const": "list_custom_object_schemas",
            "ui:hidden": True,
            "x-category": "Custom Object",
            "x-is-trigger": False,
            "x-display-name": "List Custom Object Schemas",
            "x-keywords": [
                "custom objects",
                "object schemas",
                "all schemas",
                "custom object types",
                "object definitions",
            ],
        },
        title="List Custom Object Schemas",
    )
    include_standard: Optional[bool] = Field(
        False,
        title="Include Standard Objects",
        description="Include standard HubSpot objects (contacts, companies, etc.)",
    )


class HubSpotGetSchemaConfig(BaseModel):
    model_config = ConfigDict(title="Get Schema")
    """Get a specific custom object schema"""
    operation: Literal["get_custom_object_schema"] = Field(
        "get_custom_object_schema",
        json_schema_extra={
            "const": "get_custom_object_schema",
            "ui:hidden": True,
            "x-category": "Custom Object",
            "x-is-trigger": False,
            "x-display-name": "Get Custom Object Schema",
            "x-keywords": [
                "schema details",
                "single custom object",
                "fetch object schema",
                "one schema",
            ],
        },
        title="Get Custom Object Schema",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Fully qualified name or objectTypeId of the schema",
    )


class HubSpotCreateSchemaConfig(BaseModel):
    model_config = ConfigDict(title="Create Schema")
    """Create a new custom object schema"""
    operation: Literal["create_custom_object_schema"] = Field(
        "create_custom_object_schema",
        json_schema_extra={
            "const": "create_custom_object_schema",
            "ui:hidden": True,
            "x-category": "Custom Object",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Object Schema",
            "x-keywords": [
                "new custom object",
                "add object schema",
                "define custom object",
                "build object type",
            ],
        },
        title="Create Custom Object Schema",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Internal name for the object (lowercase, underscores)",
    )
    labels: str = Field(
        ...,
        title="Labels",
        description="JSON object with singular and plural labels",
        json_schema_extra={"ui:widget": "textarea"},
    )
    primary_display_property: str = Field(
        ...,
        title="Primary Display Property",
        description="Property name to use as the primary display",
    )
    properties: str = Field(
        ...,
        title="Properties",
        description="JSON array of property definitions",
        json_schema_extra={"ui:widget": "textarea"},
    )
    associated_objects: Optional[str] = Field(
        None,
        title="Associated Objects",
        description="JSON array of object types to associate with",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateSchemaConfig(BaseModel):
    model_config = ConfigDict(title="Update Schema")
    """Update an existing custom object schema"""
    operation: Literal["update_custom_object_schema"] = Field(
        "update_custom_object_schema",
        json_schema_extra={
            "const": "update_custom_object_schema",
            "ui:hidden": True,
            "x-category": "Custom Object",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Object Schema",
            "x-keywords": [
                "edit object schema",
                "modify custom object",
                "patch schema",
                "change object definition",
            ],
        },
        title="Update Custom Object Schema",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Fully qualified name of the schema to update",
    )
    labels: Optional[str] = Field(
        None,
        title="Labels",
        description="Updated JSON labels object",
        json_schema_extra={"ui:widget": "textarea"},
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="Updated JSON array of property definitions",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteSchemaConfig(BaseModel):
    model_config = ConfigDict(title="Delete Schema")
    """Delete a custom object schema"""
    operation: Literal["delete_custom_object_schema"] = Field(
        "delete_custom_object_schema",
        json_schema_extra={
            "const": "delete_custom_object_schema",
            "ui:hidden": True,
            "x-category": "Custom Object",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Object Schema",
            "x-keywords": [
                "remove custom object",
                "delete object schema",
                "drop object type",
            ],
        },
        title="Delete Custom Object Schema",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Fully qualified name of the schema to delete",
    )
    archived: Optional[bool] = Field(
        False, title="Archive Only", description="Archive instead of permanent deletion"
    )


class HubSpotPurgeSchemaConfig(BaseModel):
    model_config = ConfigDict(title="Purge Schema")
    """Purge all data for a custom object schema"""
    operation: Literal["purge_custom_object_schema"] = Field(
        "purge_custom_object_schema",
        json_schema_extra={
            "const": "purge_custom_object_schema",
            "ui:hidden": True,
            "x-category": "Custom Object",
            "x-is-trigger": False,
            "x-display-name": "Purge Custom Object Schema",
            "x-keywords": [
                "permanently delete schema",
                "purge custom object",
                "hard delete object",
                "wipe schema",
            ],
        },
        title="Purge Custom Object Schema",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Fully qualified name of the schema to purge",
    )


# ============================================================================
# Marketing Events API Configs (Webinars, Conferences, Events)
# High business value - Track event registrations and attendance
# ============================================================================


class HubSpotListMarketingEventsConfig(BaseModel):
    model_config = ConfigDict(title="List Marketing Events")
    """List all marketing events"""
    operation: Literal["list_marketing_events"] = Field(
        "list_marketing_events",
        json_schema_extra={
            "const": "list_marketing_events",
            "ui:hidden": True,
            "x-category": "Marketing Event",
            "x-is-trigger": False,
            "x-display-name": "List Marketing Events",
            "x-keywords": [
                "marketing events",
                "all events",
                "webinars",
                "event campaigns",
            ],
        },
        title="List Marketing Events",
    )
    limit: Optional[int] = Field(
        100,
        title="Limit",
        description="Maximum number of events to return",
        ge=1,
        le=100,
    )


class HubSpotGetMarketingEventConfig(BaseModel):
    model_config = ConfigDict(title="Get Marketing Event")
    """Get a specific marketing event"""
    operation: Literal["get_marketing_event"] = Field(
        "get_marketing_event",
        json_schema_extra={
            "const": "get_marketing_event",
            "ui:hidden": True,
            "x-category": "Marketing Event",
            "x-is-trigger": False,
            "x-display-name": "Get Marketing Event",
            "x-keywords": [
                "event details",
                "single marketing event",
                "fetch event",
                "one webinar",
            ],
        },
        title="Get Marketing Event",
    )
    external_event_id: str = Field(
        ...,
        title="External Event ID",
        description="Your unique identifier for the event",
    )


class HubSpotCreateMarketingEventConfig(BaseModel):
    model_config = ConfigDict(title="Create Marketing Event")
    """Create a new marketing event"""
    operation: Literal["create_marketing_event"] = Field(
        "create_marketing_event",
        json_schema_extra={
            "const": "create_marketing_event",
            "ui:hidden": True,
            "x-category": "Marketing Event",
            "x-is-trigger": False,
            "x-display-name": "Create Marketing Event",
            "x-keywords": [
                "new marketing event",
                "add webinar",
                "make event",
                "schedule marketing event",
            ],
        },
        title="Create Marketing Event",
    )
    event_name: str = Field(
        ..., title="Event Name", description="Name of the marketing event"
    )
    event_type: str = Field(
        ...,
        title="Event Type",
        description="Type of event (WEBINAR, CONFERENCE, WORKSHOP, etc.)",
    )
    start_date_time: str = Field(
        ..., title="Start Date/Time", description="ISO 8601 timestamp for event start"
    )
    external_event_id: str = Field(
        ...,
        title="External Event ID",
        description="Your unique identifier for the event",
    )
    end_date_time: Optional[str] = Field(
        None, title="End Date/Time", description="ISO 8601 timestamp for event end"
    )
    event_url: Optional[str] = Field(
        None, title="Event URL", description="URL for the event"
    )
    event_description: Optional[str] = Field(
        None, title="Description", description="Event description"
    )
    custom_properties: Optional[str] = Field(
        None,
        title="Custom Properties",
        description="JSON object with custom event properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateMarketingEventConfig(BaseModel):
    model_config = ConfigDict(title="Update Marketing Event")
    """Update an existing marketing event"""
    operation: Literal["update_marketing_event"] = Field(
        "update_marketing_event",
        json_schema_extra={
            "const": "update_marketing_event",
            "ui:hidden": True,
            "x-category": "Marketing Event",
            "x-is-trigger": False,
            "x-display-name": "Update Marketing Event",
            "x-keywords": [
                "edit marketing event",
                "modify webinar",
                "patch event",
                "change event",
            ],
        },
        title="Update Marketing Event",
    )
    external_event_id: str = Field(
        ...,
        title="External Event ID",
        description="Your unique identifier for the event",
    )
    event_name: Optional[str] = Field(
        None, title="Event Name", description="Updated event name"
    )
    start_date_time: Optional[str] = Field(
        None, title="Start Date/Time", description="Updated start time"
    )
    end_date_time: Optional[str] = Field(
        None, title="End Date/Time", description="Updated end time"
    )
    event_cancelled: Optional[bool] = Field(
        None, title="Event Cancelled", description="Mark event as cancelled"
    )


class HubSpotDeleteMarketingEventConfig(BaseModel):
    model_config = ConfigDict(title="Delete Marketing Event")
    """Delete a marketing event"""
    operation: Literal["delete_marketing_event"] = Field(
        "delete_marketing_event",
        json_schema_extra={
            "const": "delete_marketing_event",
            "ui:hidden": True,
            "x-category": "Marketing Event",
            "x-is-trigger": False,
            "x-display-name": "Delete Marketing Event",
            "x-keywords": ["remove marketing event", "drop webinar", "cancel event"],
        },
        title="Delete Marketing Event",
    )
    external_event_id: str = Field(
        ...,
        title="External Event ID",
        description="Your unique identifier for the event",
    )


class HubSpotCreateAttendanceConfig(BaseModel):
    model_config = ConfigDict(title="Create Attendance")
    """Create/update attendance records for an event"""
    operation: Literal["create_event_attendance"] = Field(
        "create_event_attendance",
        json_schema_extra={
            "const": "create_event_attendance",
            "ui:hidden": True,
            "x-category": "Event Attendance",
            "x-is-trigger": False,
            "x-display-name": "Create Event Attendance",
            "x-keywords": [
                "record event attendance",
                "mark attendee",
                "register attendee",
                "log rsvp",
                "add event attendee",
                "track attendance",
            ],
        },
        title="Create Event Attendance",
    )
    external_event_id: str = Field(
        ..., title="External Event ID", description="Event identifier"
    )
    inputs: str = Field(
        ...,
        title="Attendance Records",
        description="JSON array with email, attendanceStatus (REGISTERED, ATTENDED, CANCELLED, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotGetAttendanceConfig(BaseModel):
    model_config = ConfigDict(title="Get Attendance")
    """Get attendance records for an event"""
    operation: Literal["get_event_attendance"] = Field(
        "get_event_attendance",
        json_schema_extra={
            "const": "get_event_attendance",
            "ui:hidden": True,
            "x-category": "Event Attendance",
            "x-is-trigger": False,
            "x-display-name": "Get Event Attendance",
            "x-keywords": [
                "check event attendance",
                "view attendee status",
                "rsvp status",
                "attendance state",
                "who attended",
            ],
        },
        title="Get Event Attendance",
    )
    external_event_id: str = Field(
        ..., title="External Event ID", description="Event identifier"
    )


class HubSpotDeleteAttendanceConfig(BaseModel):
    model_config = ConfigDict(title="Delete Attendance")
    """Delete attendance record for a participant"""
    operation: Literal["delete_event_attendance"] = Field(
        "delete_event_attendance",
        json_schema_extra={
            "const": "delete_event_attendance",
            "ui:hidden": True,
            "x-category": "Event Attendance",
            "x-is-trigger": False,
            "x-display-name": "Delete Event Attendance",
            "x-keywords": [
                "remove event attendee",
                "cancel attendance",
                "unregister attendee",
                "withdraw rsvp",
            ],
        },
        title="Delete Event Attendance",
    )
    external_event_id: str = Field(
        ..., title="External Event ID", description="Event identifier"
    )
    subscriber_email: str = Field(
        ..., title="Subscriber Email", description="Email of the participant to remove"
    )


# ============================================================================
# Campaigns API Configs (Multi-channel Campaign Management)
# Major Update: July 9, 2025 - Budget/Spend endpoints, UTM properties support
# ============================================================================


class HubSpotListCampaignsConfig(BaseModel):
    model_config = ConfigDict(title="List Campaigns")
    """List all campaigns"""
    operation: Literal["list_marketing_campaigns"] = Field(
        "list_marketing_campaigns",
        json_schema_extra={
            "const": "list_marketing_campaigns",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Marketing Campaigns",
            "x-keywords": [
                "browse marketing campaigns",
                "all campaigns",
                "campaign list",
                "marketing campaigns",
            ],
        },
        title="List Marketing Campaigns",
    )
    limit: Optional[int] = Field(
        100,
        title="Limit",
        description="Maximum number of campaigns to return",
        ge=1,
        le=100,
    )


class HubSpotGetCampaignConfig(BaseModel):
    model_config = ConfigDict(title="Get Campaign")
    """Get a specific campaign by ID"""
    operation: Literal["get_marketing_campaign"] = Field(
        "get_marketing_campaign",
        json_schema_extra={
            "const": "get_marketing_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Get Marketing Campaign",
            "x-keywords": [
                "campaign details",
                "single campaign",
                "fetch one campaign",
                "marketing campaign info",
            ],
        },
        title="Get Marketing Campaign",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The ID of the campaign to retrieve"
    )


class HubSpotCreateCampaignConfig(BaseModel):
    model_config = ConfigDict(title="Create Campaign")
    """Create a new campaign"""
    operation: Literal["create_marketing_campaign"] = Field(
        "create_marketing_campaign",
        json_schema_extra={
            "const": "create_marketing_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Create Marketing Campaign",
            "x-keywords": [
                "new marketing campaign",
                "start campaign",
                "launch campaign",
                "set up campaign",
            ],
        },
        title="Create Marketing Campaign",
    )
    name: str = Field(..., title="Campaign Name", description="Name of the campaign")


class HubSpotUpdateCampaignConfig(BaseModel):
    model_config = ConfigDict(title="Update Campaign")
    """Update an existing campaign"""
    operation: Literal["update_marketing_campaign"] = Field(
        "update_marketing_campaign",
        json_schema_extra={
            "const": "update_marketing_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Update Marketing Campaign",
            "x-keywords": [
                "edit marketing campaign",
                "rename campaign",
                "change campaign details",
            ],
        },
        title="Update Marketing Campaign",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The ID of the campaign to update"
    )
    name: Optional[str] = Field(
        None, title="Campaign Name", description="Updated campaign name"
    )
    hs_utm: Optional[str] = Field(
        None,
        title="UTM Properties",
        description="JSON object with UTM tracking parameters (NEW July 2025)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteCampaignConfig(BaseModel):
    model_config = ConfigDict(title="Delete Campaign")
    """Delete a campaign"""
    operation: Literal["delete_marketing_campaign"] = Field(
        "delete_marketing_campaign",
        json_schema_extra={
            "const": "delete_marketing_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Delete Marketing Campaign",
            "x-keywords": [
                "remove marketing campaign",
                "trash campaign",
                "drop campaign",
            ],
        },
        title="Delete Marketing Campaign",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The ID of the campaign to delete"
    )


class HubSpotGetCampaignAssetsConfig(BaseModel):
    model_config = ConfigDict(title="Get Campaign Assets")
    """Get assets associated with a campaign"""
    operation: Literal["get_campaign_assets"] = Field(
        "get_campaign_assets",
        json_schema_extra={
            "const": "get_campaign_assets",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign Assets",
            "x-keywords": [
                "campaign assets",
                "campaign attachments",
                "assets used in campaign",
                "linked campaign content",
            ],
        },
        title="Get Campaign Assets",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The ID of the campaign"
    )
    asset_type: str = Field(
        ...,
        title="Asset Type",
        description="Type of assets to retrieve (e.g., 'EMAIL', 'LANDING_PAGE', 'FORM')",
    )


class HubSpotManageCampaignBudgetConfig(BaseModel):
    model_config = ConfigDict(title="Manage Campaign Budget")
    """Manage campaign budget items (NEW July 2025)"""
    operation: Literal["update_campaign_budget"] = Field(
        "update_campaign_budget",
        json_schema_extra={
            "const": "update_campaign_budget",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign Budget",
            "x-keywords": [
                "change campaign budget",
                "set campaign spend",
                "campaign budget",
                "adjust budget",
            ],
        },
        title="Update Campaign Budget",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The ID of the campaign"
    )
    budget_operation: Literal["create", "update", "delete"] = Field(
        ..., title="Budget Operation", description="Budget operation to perform"
    )
    budget_data: Optional[str] = Field(
        None,
        title="Budget Data",
        description="JSON object with budget item data (amount, currency, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# CMS HubDB API Configs (Database Tables for Dynamic Content)
# v3 API - v2 sunsetted Jan 31, 2024
# ============================================================================


class HubSpotListHubDBTablesConfig(BaseModel):
    model_config = ConfigDict(title="List HubDB Tables")
    """List all HubDB tables"""
    operation: Literal["list_hubdb_tables"] = Field(
        "list_hubdb_tables",
        json_schema_extra={
            "const": "list_hubdb_tables",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "List Hubdb Tables",
            "x-keywords": [
                "hubdb tables",
                "content database tables",
                "list cms database",
                "database tables",
            ],
        },
        title="List Hubdb Tables",
    )


class HubSpotGetHubDBTableConfig(BaseModel):
    model_config = ConfigDict(title="Get HubDB Table")
    """Get a specific HubDB table"""
    operation: Literal["get_hubdb_table"] = Field(
        "get_hubdb_table",
        json_schema_extra={
            "const": "get_hubdb_table",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Get Hubdb Table",
            "x-keywords": [
                "hubdb table details",
                "read content database table",
                "fetch hubdb schema",
            ],
        },
        title="Get Hubdb Table",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID or name")
    draft: bool = Field(
        False, title="Draft", description="Get draft version instead of published"
    )


class HubSpotCreateHubDBTableConfig(BaseModel):
    model_config = ConfigDict(title="Create HubDB Table")
    """Create a new HubDB table"""
    operation: Literal["create_hubdb_table"] = Field(
        "create_hubdb_table",
        json_schema_extra={
            "const": "create_hubdb_table",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Create Hubdb Table",
            "x-keywords": [
                "new hubdb table",
                "add hubdb table",
                "build cms table",
                "make data table",
            ],
        },
        title="Create Hubdb Table",
    )
    name: str = Field(..., title="Table Name", description="Name of the table")
    label: str = Field(..., title="Label", description="Display label for the table")
    columns: str = Field(
        ...,
        title="Columns",
        description="JSON array of column definitions",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateHubDBTableConfig(BaseModel):
    model_config = ConfigDict(title="Update HubDB Table")
    """Update a HubDB table"""
    operation: Literal["update_hubdb_table"] = Field(
        "update_hubdb_table",
        json_schema_extra={
            "const": "update_hubdb_table",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Update Hubdb Table",
            "x-keywords": [
                "edit hubdb table",
                "change table schema",
                "modify hubdb table",
                "rename data table",
            ],
        },
        title="Update Hubdb Table",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID or name")
    label: Optional[str] = Field(None, title="Label", description="Updated label")


class HubSpotPublishHubDBTableConfig(BaseModel):
    model_config = ConfigDict(title="Publish HubDB Table")
    """Publish HubDB table (draft to live)"""
    operation: Literal["publish_hubdb_table"] = Field(
        "publish_hubdb_table",
        json_schema_extra={
            "const": "publish_hubdb_table",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Publish Hubdb Table",
            "x-keywords": [
                "go live hubdb",
                "publish data table",
                "push table live",
                "make table live",
            ],
        },
        title="Publish Hubdb Table",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID to publish")


class HubSpotDeleteHubDBTableConfig(BaseModel):
    model_config = ConfigDict(title="Delete HubDB Table")
    """Delete a HubDB table"""
    operation: Literal["delete_hubdb_table"] = Field(
        "delete_hubdb_table",
        json_schema_extra={
            "const": "delete_hubdb_table",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Delete Hubdb Table",
            "x-keywords": ["remove hubdb table", "drop data table", "trash cms table"],
        },
        title="Delete Hubdb Table",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID to delete")


class HubSpotListHubDBRowsConfig(BaseModel):
    model_config = ConfigDict(title="List HubDB Rows")
    """List rows in a HubDB table"""
    operation: Literal["list_hubdb_rows"] = Field(
        "list_hubdb_rows",
        json_schema_extra={
            "const": "list_hubdb_rows",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "List Hubdb Rows",
            "x-keywords": [
                "all table rows",
                "browse hubdb rows",
                "show data rows",
                "view table entries",
            ],
        },
        title="List Hubdb Rows",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID")
    draft: bool = Field(
        False, title="Draft", description="Get draft version instead of published"
    )


class HubSpotGetHubDBRowConfig(BaseModel):
    model_config = ConfigDict(title="Get HubDB Row")
    """Get a specific HubDB row"""
    operation: Literal["get_hubdb_row"] = Field(
        "get_hubdb_row",
        json_schema_extra={
            "const": "get_hubdb_row",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Get Hubdb Row",
            "x-keywords": [
                "single table row",
                "fetch hubdb row",
                "one data row",
                "read table entry",
            ],
        },
        title="Get Hubdb Row",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID")
    row_id: str = Field(..., title="Row ID", description="Row ID")
    draft: bool = Field(
        False, title="Draft", description="Get draft version instead of published"
    )


class HubSpotCreateHubDBRowConfig(BaseModel):
    model_config = ConfigDict(title="Create HubDB Row")
    """Create a new row in HubDB table"""
    operation: Literal["create_hubdb_row"] = Field(
        "create_hubdb_row",
        json_schema_extra={
            "const": "create_hubdb_row",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Create Hubdb Row",
            "x-keywords": [
                "new table row",
                "add hubdb row",
                "insert data row",
                "append table entry",
            ],
        },
        title="Create Hubdb Row",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID")
    values: str = Field(
        ...,
        title="Row Values",
        description="JSON object with column values",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateHubDBRowConfig(BaseModel):
    model_config = ConfigDict(title="Update HubDB Row")
    """Update a HubDB row"""
    operation: Literal["update_hubdb_row"] = Field(
        "update_hubdb_row",
        json_schema_extra={
            "const": "update_hubdb_row",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Update Hubdb Row",
            "x-keywords": [
                "edit table row",
                "change hubdb row",
                "modify data row",
                "patch table entry",
            ],
        },
        title="Update Hubdb Row",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID")
    row_id: str = Field(..., title="Row ID", description="Row ID")
    values: str = Field(
        ...,
        title="Row Values",
        description="JSON object with updated values",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteHubDBRowConfig(BaseModel):
    model_config = ConfigDict(title="Delete HubDB Row")
    """Delete a HubDB row"""
    operation: Literal["delete_hubdb_row"] = Field(
        "delete_hubdb_row",
        json_schema_extra={
            "const": "delete_hubdb_row",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Delete Hubdb Row",
            "x-keywords": ["remove table row", "drop hubdb row", "erase data row"],
        },
        title="Delete Hubdb Row",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID")
    row_id: str = Field(..., title="Row ID", description="Row ID to delete")


class HubSpotCloneHubDBTableConfig(BaseModel):
    model_config = ConfigDict(title="Clone HubDB Table")
    """Clone a HubDB table"""
    operation: Literal["clone_hubdb_table"] = Field(
        "clone_hubdb_table",
        json_schema_extra={
            "const": "clone_hubdb_table",
            "ui:hidden": True,
            "x-category": "Database (HubDB)",
            "x-is-trigger": False,
            "x-display-name": "Clone Hubdb Table",
            "x-keywords": [
                "duplicate hubdb table",
                "copy data table",
                "clone cms table",
            ],
        },
        title="Clone Hubdb Table",
    )
    table_id: str = Field(..., title="Table ID", description="Table ID to clone")
    new_name: str = Field(
        ..., title="New Name", description="Name for the cloned table"
    )


# ============================================================================
# Communication Preferences (Subscription) API Configs
# v3/v4 API - Manage email/SMS subscription preferences
# ============================================================================


class HubSpotGetSubscriptionStatusConfig(BaseModel):
    model_config = ConfigDict(title="Get Subscription Status")
    """Get subscription status for an email"""
    operation: Literal["get_contact_subscription_status"] = Field(
        "get_contact_subscription_status",
        json_schema_extra={
            "const": "get_contact_subscription_status",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Subscription Status",
            "x-keywords": [
                "email opt status",
                "subscription state",
                "is subscribed",
                "consent status",
                "communication preferences",
            ],
        },
        title="Get Contact Subscription Status",
    )
    email: str = Field(
        ..., title="Email Address", description="Email to check subscription status"
    )


class HubSpotSubscribeContactConfig(BaseModel):
    model_config = ConfigDict(title="Subscribe Contact")
    """Subscribe a contact to subscription types"""
    operation: Literal["subscribe_contact_to_list"] = Field(
        "subscribe_contact_to_list",
        json_schema_extra={
            "const": "subscribe_contact_to_list",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Subscribe Contact to List",
            "x-keywords": [
                "opt in contact",
                "add to mailing",
                "subscribe email",
                "join newsletter",
            ],
        },
        title="Subscribe Contact to List",
    )
    email: str = Field(..., title="Email Address", description="Email to subscribe")
    subscription_id: str = Field(
        ..., title="Subscription Type ID", description="ID of subscription type"
    )
    legal_basis: Optional[str] = Field(
        None,
        title="Legal Basis",
        description="Legal basis for subscription (LEGITIMATE_INTEREST_CLIENT, etc.)",
    )
    legal_basis_explanation: Optional[str] = Field(
        None, title="Legal Basis Explanation", description="Explanation for legal basis"
    )


class HubSpotUnsubscribeContactConfig(BaseModel):
    model_config = ConfigDict(title="Unsubscribe Contact")
    """Unsubscribe a contact from subscription types"""
    operation: Literal["unsubscribe_contact_from_list"] = Field(
        "unsubscribe_contact_from_list",
        json_schema_extra={
            "const": "unsubscribe_contact_from_list",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Unsubscribe Contact from List",
            "x-keywords": [
                "opt out contact",
                "remove from mailing",
                "unsubscribe email",
                "leave newsletter",
            ],
        },
        title="Unsubscribe Contact from List",
    )
    email: str = Field(..., title="Email Address", description="Email to unsubscribe")
    subscription_id: str = Field(
        ..., title="Subscription Type ID", description="ID of subscription type"
    )


class HubSpotListSubscriptionTypesConfig(BaseModel):
    model_config = ConfigDict(title="List Subscription Types")
    """List all subscription types"""
    operation: Literal["list_subscription_types"] = Field(
        "list_subscription_types",
        json_schema_extra={
            "const": "list_subscription_types",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Subscription Types",
            "x-keywords": [
                "email types",
                "consent options",
                "communication preferences",
                "subscription kinds",
                "opt in options",
            ],
        },
        title="List Subscription Types",
    )


# ============================================================================
# CMS Pages API Configs
# ============================================================================


class HubSpotListPagesConfig(BaseModel):
    model_config = ConfigDict(title="List Pages")
    """List all site pages"""
    operation: Literal["list_website_pages"] = Field(
        "list_website_pages",
        json_schema_extra={
            "const": "list_website_pages",
            "ui:hidden": True,
            "x-category": "Website Page",
            "x-is-trigger": False,
            "x-display-name": "List Website Pages",
            "x-keywords": [
                "all site pages",
                "browse cms pages",
                "show landing pages",
                "view web pages",
            ],
        },
        title="List Website Pages",
    )


class HubSpotGetPageConfig(BaseModel):
    model_config = ConfigDict(title="Get Page")
    """Get a specific page"""
    operation: Literal["get_website_page"] = Field(
        "get_website_page",
        json_schema_extra={
            "const": "get_website_page",
            "ui:hidden": True,
            "x-category": "Website Page",
            "x-is-trigger": False,
            "x-display-name": "Get Website Page",
            "x-keywords": [
                "single site page",
                "fetch cms page",
                "one landing page",
                "read web page",
            ],
        },
        title="Get Website Page",
    )
    page_id: str = Field(..., title="Page ID", description="The page ID")


class HubSpotCreatePageConfig(BaseModel):
    model_config = ConfigDict(title="Create Page")
    """Create a new page"""
    operation: Literal["create_website_page"] = Field(
        "create_website_page",
        json_schema_extra={
            "const": "create_website_page",
            "ui:hidden": True,
            "x-category": "Website Page",
            "x-is-trigger": False,
            "x-display-name": "Create Website Page",
            "x-keywords": [
                "new site page",
                "add landing page",
                "build cms page",
                "make web page",
            ],
        },
        title="Create Website Page",
    )
    name: str = Field(..., title="Page Name", description="Name of the page")
    html_title: str = Field(
        ..., title="HTML Title", description="HTML title tag content"
    )


class HubSpotUpdatePageConfig(BaseModel):
    model_config = ConfigDict(title="Update Page")
    """Update a page"""
    operation: Literal["update_website_page"] = Field(
        "update_website_page",
        json_schema_extra={
            "const": "update_website_page",
            "ui:hidden": True,
            "x-category": "Website Page",
            "x-is-trigger": False,
            "x-display-name": "Update Website Page",
            "x-keywords": [
                "edit site page",
                "change landing page",
                "modify cms page",
                "patch web page",
            ],
        },
        title="Update Website Page",
    )
    page_id: str = Field(..., title="Page ID", description="The page ID")
    name: Optional[str] = Field(None, title="Page Name", description="Updated name")


class HubSpotDeletePageConfig(BaseModel):
    model_config = ConfigDict(title="Delete Page")
    """Delete a page"""
    operation: Literal["delete_website_page"] = Field(
        "delete_website_page",
        json_schema_extra={
            "const": "delete_website_page",
            "ui:hidden": True,
            "x-category": "Website Page",
            "x-is-trigger": False,
            "x-display-name": "Delete Website Page",
            "x-keywords": ["remove site page", "drop landing page", "trash cms page"],
        },
        title="Delete Website Page",
    )
    page_id: str = Field(..., title="Page ID", description="The page ID to delete")


class HubSpotPublishPageConfig(BaseModel):
    model_config = ConfigDict(title="Publish Page")
    """Publish a page"""
    operation: Literal["publish_website_page"] = Field(
        "publish_website_page",
        json_schema_extra={
            "const": "publish_website_page",
            "ui:hidden": True,
            "x-category": "Website Page",
            "x-is-trigger": False,
            "x-display-name": "Publish Website Page",
            "x-keywords": [
                "go live page",
                "publish landing page",
                "push page live",
                "make page live",
            ],
        },
        title="Publish Website Page",
    )
    page_id: str = Field(..., title="Page ID", description="The page ID to publish")


# ============================================================================
# CMS Blogs API Configs
# ============================================================================


class HubSpotListBlogPostsConfig(BaseModel):
    model_config = ConfigDict(title="List Blog Posts")
    """List all blog posts"""
    operation: Literal["list_blog_posts"] = Field(
        "list_blog_posts",
        json_schema_extra={
            "const": "list_blog_posts",
            "ui:hidden": True,
            "x-category": "Blog Post",
            "x-is-trigger": False,
            "x-display-name": "List Blog Posts",
            "x-keywords": [
                "all blog articles",
                "browse blog posts",
                "show articles",
                "view blog entries",
            ],
        },
        title="List Blog Posts",
    )


class HubSpotGetBlogPostConfig(BaseModel):
    model_config = ConfigDict(title="Get Blog Post")
    """Get a specific blog post"""
    operation: Literal["get_blog_post"] = Field(
        "get_blog_post",
        json_schema_extra={
            "const": "get_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Post",
            "x-is-trigger": False,
            "x-display-name": "Get Blog Post",
            "x-keywords": [
                "single blog article",
                "fetch blog post",
                "one article",
                "read blog entry",
            ],
        },
        title="Get Blog Post",
    )
    post_id: str = Field(..., title="Post ID", description="The blog post ID")


class HubSpotCreateBlogPostConfig(BaseModel):
    model_config = ConfigDict(title="Create Blog Post")
    """Create a new blog post"""
    operation: Literal["create_blog_post"] = Field(
        "create_blog_post",
        json_schema_extra={
            "const": "create_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Post",
            "x-is-trigger": False,
            "x-display-name": "Create Blog Post",
            "x-keywords": [
                "new blog article",
                "add blog post",
                "write article",
                "draft blog entry",
            ],
        },
        title="Create Blog Post",
    )
    name: str = Field(..., title="Post Name", description="Name of the blog post")
    post_body: str = Field(
        ..., title="Post Body", description="HTML content of the post"
    )


class HubSpotUpdateBlogPostConfig(BaseModel):
    model_config = ConfigDict(title="Update Blog Post")
    """Update a blog post"""
    operation: Literal["update_blog_post"] = Field(
        "update_blog_post",
        json_schema_extra={
            "const": "update_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Post",
            "x-is-trigger": False,
            "x-display-name": "Update Blog Post",
            "x-keywords": [
                "edit blog article",
                "change blog post",
                "modify article",
                "patch blog entry",
            ],
        },
        title="Update Blog Post",
    )
    post_id: str = Field(..., title="Post ID", description="The blog post ID")
    name: Optional[str] = Field(None, title="Post Name", description="Updated name")


class HubSpotDeleteBlogPostConfig(BaseModel):
    model_config = ConfigDict(title="Delete Blog Post")
    """Delete a blog post"""
    operation: Literal["delete_blog_post"] = Field(
        "delete_blog_post",
        json_schema_extra={
            "const": "delete_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Post",
            "x-is-trigger": False,
            "x-display-name": "Delete Blog Post",
            "x-keywords": ["remove blog article", "drop blog post", "trash article"],
        },
        title="Delete Blog Post",
    )
    post_id: str = Field(..., title="Post ID", description="The blog post ID to delete")


class HubSpotListBlogAuthorsConfig(BaseModel):
    model_config = ConfigDict(title="List Blog Authors")
    """List all blog authors"""
    operation: Literal["list_blog_authors"] = Field(
        "list_blog_authors",
        json_schema_extra={
            "const": "list_blog_authors",
            "ui:hidden": True,
            "x-category": "Blog Author",
            "x-is-trigger": False,
            "x-display-name": "List Blog Authors",
            "x-keywords": [
                "all blog writers",
                "browse authors",
                "show contributors",
                "blog bylines",
            ],
        },
        title="List Blog Authors",
    )


class HubSpotGetBlogAuthorConfig(BaseModel):
    model_config = ConfigDict(title="Get Blog Author")
    """Get a specific blog author"""
    operation: Literal["get_blog_author"] = Field(
        "get_blog_author",
        json_schema_extra={
            "const": "get_blog_author",
            "ui:hidden": True,
            "x-category": "Blog Author",
            "x-is-trigger": False,
            "x-display-name": "Get Blog Author",
            "x-keywords": [
                "single blog writer",
                "fetch author",
                "one contributor",
                "read blog byline",
            ],
        },
        title="Get Blog Author",
    )
    author_id: str = Field(..., title="Author ID", description="The author ID")


class HubSpotCreateBlogAuthorConfig(BaseModel):
    model_config = ConfigDict(title="Create Blog Author")
    """Create a new blog author"""
    operation: Literal["create_blog_author"] = Field(
        "create_blog_author",
        json_schema_extra={
            "const": "create_blog_author",
            "ui:hidden": True,
            "x-category": "Blog Author",
            "x-is-trigger": False,
            "x-display-name": "Create Blog Author",
            "x-keywords": [
                "new blog writer",
                "add author",
                "make contributor",
                "register byline",
            ],
        },
        title="Create Blog Author",
    )
    full_name: str = Field(..., title="Full Name", description="Author's full name")
    email: str = Field(..., title="Email", description="Author's email")


class HubSpotListBlogTopicsConfig(BaseModel):
    model_config = ConfigDict(title="List Blog Topics")
    """List all blog topics"""
    operation: Literal["list_blog_topics"] = Field(
        "list_blog_topics",
        json_schema_extra={
            "const": "list_blog_topics",
            "ui:hidden": True,
            "x-category": "Blog Topic",
            "x-is-trigger": False,
            "x-display-name": "List Blog Topics",
            "x-keywords": [
                "all blog tags",
                "browse topics",
                "show blog categories",
                "content tags",
            ],
        },
        title="List Blog Topics",
    )


class HubSpotGetBlogTopicConfig(BaseModel):
    model_config = ConfigDict(title="Get Blog Topic")
    """Get a specific blog topic"""
    operation: Literal["get_blog_topic"] = Field(
        "get_blog_topic",
        json_schema_extra={
            "const": "get_blog_topic",
            "ui:hidden": True,
            "x-category": "Blog Topic",
            "x-is-trigger": False,
            "x-display-name": "Get Blog Topic",
            "x-keywords": [
                "single blog tag",
                "fetch topic",
                "one blog category",
                "read content tag",
            ],
        },
        title="Get Blog Topic",
    )
    topic_id: str = Field(..., title="Topic ID", description="The topic ID")


# ============================================================================
# CMS Files API Configs
# ============================================================================


class HubSpotListFilesConfig(BaseModel):
    model_config = ConfigDict(title="List Files")
    """List all files in file manager"""
    operation: Literal["list_files"] = Field(
        "list_files",
        json_schema_extra={
            "const": "list_files",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Files",
            "x-keywords": [
                "all media files",
                "browse file manager",
                "show uploads",
                "view attachments",
            ],
        },
        title="List Files",
    )


class HubSpotGetFileConfig(BaseModel):
    model_config = ConfigDict(title="Get File")
    """Get a specific file"""
    operation: Literal["get_file"] = Field(
        "get_file",
        json_schema_extra={
            "const": "get_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File",
            "x-keywords": [
                "single media file",
                "fetch one file",
                "read attachment",
                "file details",
            ],
        },
        title="Get File",
    )
    file_id: str = Field(..., title="File ID", description="The file ID")


class HubSpotUploadFileConfig(BaseModel):
    model_config = ConfigDict(title="Upload File")
    """Upload a file to file manager"""
    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={
            "const": "upload_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File",
            "x-keywords": [
                "add media file",
                "import attachment",
                "push file",
                "put file",
            ],
        },
        title="Upload File",
    )
    file_data: str = Field(
        ...,
        title="File Data",
        description=(
            "JSON with the file to import from a URL. Required: `access` "
            "(PRIVATE | PUBLIC_INDEXABLE | PUBLIC_NOT_INDEXABLE) and `url`. "
            "Optional: `folderPath` (e.g. \"/\"), `name`, `overwrite`. "
            "Example: {\"access\":\"PUBLIC_INDEXABLE\",\"url\":\"https://…/logo.png\",\"folderPath\":\"/\"}"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateFileConfig(BaseModel):
    model_config = ConfigDict(title="Update File")
    """Update file properties"""
    operation: Literal["update_file"] = Field(
        "update_file",
        json_schema_extra={
            "const": "update_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Update File",
            "x-keywords": [
                "edit file meta",
                "rename media file",
                "change attachment",
                "modify file",
            ],
        },
        title="Update File",
    )
    file_id: str = Field(..., title="File ID", description="The file ID to update")
    file_data: str = Field(
        ...,
        title="File Data",
        description="JSON object with updated file properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteFileConfig(BaseModel):
    model_config = ConfigDict(title="Delete File")
    """Delete a file"""
    operation: Literal["delete_file"] = Field(
        "delete_file",
        json_schema_extra={
            "const": "delete_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File",
            "x-keywords": ["remove media file", "drop attachment", "trash upload"],
        },
        title="Delete File",
    )
    file_id: str = Field(..., title="File ID", description="The file ID to delete")


# ============================================================================
# CMS Domains API Configs
# ============================================================================


class HubSpotListDomainsConfig(BaseModel):
    model_config = ConfigDict(title="List Domains")
    """List all domains"""
    operation: Literal["list_domains"] = Field(
        "list_domains",
        json_schema_extra={
            "const": "list_domains",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "List Domains",
            "x-keywords": [
                "all connected domains",
                "browse domains",
                "show site domains",
                "hosted domains",
            ],
        },
        title="List Domains",
    )


class HubSpotGetDomainConfig(BaseModel):
    model_config = ConfigDict(title="Get Domain")
    """Get a specific domain"""
    operation: Literal["get_domain"] = Field(
        "get_domain",
        json_schema_extra={
            "const": "get_domain",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain",
            "x-keywords": [
                "single domain",
                "fetch domain",
                "read site domain",
                "domain details",
            ],
        },
        title="Get Domain",
    )
    domain_id: str = Field(..., title="Domain ID", description="The domain ID")


# ============================================================================
# CMS URL Mappings API Configs
# ============================================================================


class HubSpotListUrlMappingsConfig(BaseModel):
    model_config = ConfigDict(title="List URL Mappings")
    """List all URL redirects/mappings"""
    operation: Literal["list_url_redirects"] = Field(
        "list_url_redirects",
        json_schema_extra={
            "const": "list_url_redirects",
            "ui:hidden": True,
            "x-category": "URL Mapping",
            "x-is-trigger": False,
            "x-display-name": "List Url Redirects",
            "x-keywords": [
                "all url redirects",
                "browse redirects",
                "show url mappings",
                "forwarding rules",
            ],
        },
        title="List Url Redirects",
    )


class HubSpotGetUrlMappingConfig(BaseModel):
    model_config = ConfigDict(title="Get URL Mapping")
    """Get a specific URL mapping"""
    operation: Literal["get_url_redirect"] = Field(
        "get_url_redirect",
        json_schema_extra={
            "const": "get_url_redirect",
            "ui:hidden": True,
            "x-category": "URL Mapping",
            "x-is-trigger": False,
            "x-display-name": "Get Url Redirect",
            "x-keywords": [
                "single url redirect",
                "fetch redirect",
                "read url mapping",
                "one forwarding rule",
            ],
        },
        title="Get Url Redirect",
    )
    mapping_id: str = Field(..., title="Mapping ID", description="The URL mapping ID")


class HubSpotCreateUrlMappingConfig(BaseModel):
    model_config = ConfigDict(title="Create URL Mapping")
    """Create a new URL redirect"""
    operation: Literal["create_url_redirect"] = Field(
        "create_url_redirect",
        json_schema_extra={
            "const": "create_url_redirect",
            "ui:hidden": True,
            "x-category": "URL Mapping",
            "x-is-trigger": False,
            "x-display-name": "Create Url Redirect",
            "x-keywords": [
                "new url redirect",
                "add redirect",
                "make url mapping",
                "set forwarding rule",
            ],
        },
        title="Create Url Redirect",
    )
    route_prefix: str = Field(
        ..., title="Route Prefix", description="The URL path to redirect from"
    )
    destination: str = Field(
        ..., title="Destination", description="The destination URL"
    )
    redirect_style: int = Field(
        301, title="Redirect Type", description="301 (permanent) or 302 (temporary)"
    )


class HubSpotUpdateUrlMappingConfig(BaseModel):
    model_config = ConfigDict(title="Update URL Mapping")
    """Update an existing URL mapping"""
    operation: Literal["update_url_redirect"] = Field(
        "update_url_redirect",
        json_schema_extra={
            "const": "update_url_redirect",
            "ui:hidden": True,
            "x-category": "URL Mapping",
            "x-is-trigger": False,
            "x-display-name": "Update Url Redirect",
            "x-keywords": [
                "edit url redirect",
                "change redirect",
                "modify url mapping",
                "patch forwarding rule",
            ],
        },
        title="Update Url Redirect",
    )
    mapping_id: str = Field(..., title="Mapping ID", description="The URL mapping ID")
    mapping_data: str = Field(
        ...,
        title="Mapping Data",
        description="JSON object with updated mapping properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteUrlMappingConfig(BaseModel):
    model_config = ConfigDict(title="Delete URL Mapping")
    """Delete a URL mapping"""
    operation: Literal["delete_url_redirect"] = Field(
        "delete_url_redirect",
        json_schema_extra={
            "const": "delete_url_redirect",
            "ui:hidden": True,
            "x-category": "URL Mapping",
            "x-is-trigger": False,
            "x-display-name": "Delete Url Redirect",
            "x-keywords": ["remove url redirect", "drop redirect", "trash url mapping"],
        },
        title="Delete Url Redirect",
    )
    mapping_id: str = Field(
        ..., title="Mapping ID", description="The URL mapping ID to delete"
    )


# ============================================================================
# CMS Site Search API Configs
# ============================================================================


class HubSpotSearchContentConfig(BaseModel):
    model_config = ConfigDict(title="Search Content")
    """Search CMS content"""
    operation: Literal["search_website_content"] = Field(
        "search_website_content",
        json_schema_extra={
            "const": "search_website_content",
            "ui:hidden": True,
            "x-category": "Content Search",
            "x-is-trigger": False,
            "x-display-name": "Search Website Content",
            "x-keywords": [
                "site search",
                "find page content",
                "query cms content",
                "lookup site content",
            ],
        },
        title="Search Website Content",
    )
    query: str = Field(..., title="Search Query", description="Search term")
    limit: int = Field(20, title="Limit", description="Number of results to return")


# ============================================================================
# Conversations API Configs
# ============================================================================


class HubSpotListConversationThreadsConfig(BaseModel):
    model_config = ConfigDict(title="List Conversation Threads")
    """List conversation threads"""
    operation: Literal["list_conversation_threads"] = Field(
        "list_conversation_threads",
        json_schema_extra={
            "const": "list_conversation_threads",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "List Conversation Threads",
            "x-keywords": [
                "all inbox threads",
                "browse conversations",
                "show chat threads",
                "help desk inbox",
            ],
        },
        title="List Conversation Threads",
    )


class HubSpotGetConversationThreadConfig(BaseModel):
    model_config = ConfigDict(title="Get Conversation Thread")
    """Get a specific conversation thread"""
    operation: Literal["get_conversation_thread"] = Field(
        "get_conversation_thread",
        json_schema_extra={
            "const": "get_conversation_thread",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation Thread",
            "x-keywords": [
                "single inbox thread",
                "fetch conversation",
                "one chat thread",
                "read help desk thread",
            ],
        },
        title="Get Conversation Thread",
    )
    thread_id: str = Field(
        ..., title="Thread ID", description="The conversation thread ID"
    )


class HubSpotListMessagesConfig(BaseModel):
    model_config = ConfigDict(title="List Messages")
    """List messages in a thread"""
    operation: Literal["list_conversation_messages"] = Field(
        "list_conversation_messages",
        json_schema_extra={
            "const": "list_conversation_messages",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "List Conversation Messages",
            "x-keywords": [
                "thread messages",
                "inbox replies",
                "show chat messages",
                "conversation history",
            ],
        },
        title="List Conversation Messages",
    )
    thread_id: str = Field(
        ..., title="Thread ID", description="The conversation thread ID"
    )


class HubSpotSendMessageConfig(BaseModel):
    model_config = ConfigDict(title="Send Message")
    """Send a message in a conversation"""
    operation: Literal["send_conversation_message"] = Field(
        "send_conversation_message",
        json_schema_extra={
            "const": "send_conversation_message",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Send Conversation Message",
            "x-keywords": [
                "reply in inbox",
                "send chat message",
                "respond to thread",
                "answer conversation",
            ],
        },
        title="Send Conversation Message",
    )
    thread_id: str = Field(
        ..., title="Thread ID", description="The conversation thread ID"
    )
    message: str = Field(..., title="Message", description="Message content")
    sender_id: Optional[str] = Field(
        None, title="Sender ID", description="ID of the sender (user or visitor)"
    )


class HubSpotListChannelsConfig(BaseModel):
    model_config = ConfigDict(title="List Channels")
    """List conversation channels"""
    operation: Literal["list_communication_channels"] = Field(
        "list_communication_channels",
        json_schema_extra={
            "const": "list_communication_channels",
            "ui:hidden": True,
            "x-category": "Communication Channel",
            "x-is-trigger": False,
            "x-display-name": "List Communication Channels",
            "x-keywords": [
                "all inbox channels",
                "browse comm channels",
                "connected messaging channels",
                "chat sources",
            ],
        },
        title="List Communication Channels",
    )


class HubSpotGetChannelConfig(BaseModel):
    model_config = ConfigDict(title="Get Channel")
    """Get a specific conversation channel"""
    operation: Literal["get_communication_channel"] = Field(
        "get_communication_channel",
        json_schema_extra={
            "const": "get_communication_channel",
            "ui:hidden": True,
            "x-category": "Communication Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Communication Channel",
            "x-keywords": [
                "single inbox channel",
                "fetch comm channel",
                "read messaging channel",
                "one chat source",
            ],
        },
        title="Get Communication Channel",
    )
    channel_id: str = Field(..., title="Channel ID", description="The channel ID")


class HubSpotIdentifyVisitorConfig(BaseModel):
    model_config = ConfigDict(title="Identify Visitor")
    """Identify a visitor in conversations"""
    operation: Literal["identify_website_visitor"] = Field(
        "identify_website_visitor",
        json_schema_extra={
            "const": "identify_website_visitor",
            "ui:hidden": True,
            "x-category": "Visitor",
            "x-is-trigger": False,
            "x-display-name": "Identify Website Visitor",
            "x-keywords": [
                "identify visitor",
                "match visitor to contact",
                "resolve anonymous visitor",
                "tie visitor to contact",
                "track web visitor",
            ],
        },
        title="Identify Website Visitor",
    )
    email: str = Field(..., title="Email", description="Visitor email")
    token: str = Field(..., title="Token", description="Visitor identification token")


class HubSpotGetVisitorConfig(BaseModel):
    model_config = ConfigDict(title="Get Visitor")
    """Get visitor information"""
    operation: Literal["get_visitor"] = Field(
        "get_visitor",
        json_schema_extra={
            "const": "get_visitor",
            "ui:hidden": True,
            "x-category": "Visitor",
            "x-is-trigger": False,
            "x-display-name": "Get Visitor",
            "x-keywords": [
                "fetch visitor",
                "visitor details",
                "website visitor info",
                "lookup visitor",
            ],
        },
        title="Get Visitor",
    )
    visitor_id: str = Field(..., title="Visitor ID", description="The visitor ID")


class HubSpotUpdateConversationStatusConfig(BaseModel):
    model_config = ConfigDict(title="Update Conversation Status")
    """Update conversation thread status"""
    operation: Literal["update_conversation_status"] = Field(
        "update_conversation_status",
        json_schema_extra={
            "const": "update_conversation_status",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Update Conversation Status",
            "x-keywords": [
                "close conversation",
                "reopen conversation",
                "mark thread resolved",
                "change inbox status",
                "archive conversation",
            ],
        },
        title="Update Conversation Status",
    )
    thread_id: str = Field(
        ..., title="Thread ID", description="The conversation thread ID"
    )
    status: str = Field(
        ..., title="Status", description="New status (OPEN, CLOSED, etc.)"
    )


# ============================================================================
# Automation & Workflows API Configs
# ============================================================================


class HubSpotListWorkflowsConfig(BaseModel):
    model_config = ConfigDict(title="List Workflows")
    """List all workflows"""
    operation: Literal["list_workflows"] = Field(
        "list_workflows",
        json_schema_extra={
            "const": "list_workflows",
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflows",
            "x-keywords": [
                "browse automation workflows",
                "all automation flows",
                "show hubspot workflows",
                "list automations",
            ],
        },
        title="List Workflows",
    )


class HubSpotGetWorkflowConfig(BaseModel):
    model_config = ConfigDict(title="Get Workflow")
    """Get a specific workflow"""
    operation: Literal["get_workflow"] = Field(
        "get_workflow",
        json_schema_extra={
            "const": "get_workflow",
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow",
            "x-keywords": [
                "fetch automation workflow",
                "workflow details",
                "lookup automation flow",
                "single workflow",
            ],
        },
        title="Get Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID", description="The workflow ID")


class HubSpotEnrollInWorkflowConfig(BaseModel):
    model_config = ConfigDict(title="Enroll In Workflow")
    """Enroll a contact in a workflow"""
    operation: Literal["enroll_contact_in_workflow"] = Field(
        "enroll_contact_in_workflow",
        json_schema_extra={
            "const": "enroll_contact_in_workflow",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Enroll Contact in Workflow",
            "x-keywords": [
                "enroll in workflow",
                "add contact to automation",
                "trigger workflow for contact",
                "start automation for contact",
            ],
        },
        title="Enroll Contact in Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID", description="The workflow ID")
    contact_email: str = Field(
        ..., title="Contact Email", description="Email of contact to enroll"
    )


class HubSpotUnenrollFromWorkflowConfig(BaseModel):
    model_config = ConfigDict(title="Unenroll From Workflow")
    """Unenroll a contact from a workflow"""
    operation: Literal["unenroll_contact_from_workflow"] = Field(
        "unenroll_contact_from_workflow",
        json_schema_extra={
            "const": "unenroll_contact_from_workflow",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Unenroll Contact from Workflow",
            "x-keywords": [
                "unenroll from workflow",
                "remove contact from automation",
                "stop workflow for contact",
                "exit automation",
            ],
        },
        title="Unenroll Contact from Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID", description="The workflow ID")
    contact_email: str = Field(
        ..., title="Contact Email", description="Email of contact to unenroll"
    )


class HubSpotListSequencesConfig(BaseModel):
    model_config = ConfigDict(title="List Sequences")
    """List all sequences"""
    operation: Literal["list_sequences"] = Field(
        "list_sequences",
        json_schema_extra={
            "const": "list_sequences",
            "ui:hidden": True,
            "x-category": "Sequence",
            "x-is-trigger": False,
            "x-display-name": "List Sequences",
            "x-keywords": [
                "browse sales sequences",
                "all email sequences",
                "show sequences",
                "list outreach sequences",
            ],
        },
        title="List Sequences",
    )


class HubSpotGetSequenceConfig(BaseModel):
    model_config = ConfigDict(title="Get Sequence")
    """Get a specific sequence"""
    operation: Literal["get_sequence"] = Field(
        "get_sequence",
        json_schema_extra={
            "const": "get_sequence",
            "ui:hidden": True,
            "x-category": "Sequence",
            "x-is-trigger": False,
            "x-display-name": "Get Sequence",
            "x-keywords": [
                "fetch sales sequence",
                "sequence details",
                "lookup email sequence",
                "single sequence",
            ],
        },
        title="Get Sequence",
    )
    sequence_id: str = Field(..., title="Sequence ID", description="The sequence ID")


class HubSpotEnrollInSequenceConfig(BaseModel):
    model_config = ConfigDict(title="Enroll In Sequence")
    """Enroll a contact in a sequence"""
    operation: Literal["enroll_contact_in_sequence"] = Field(
        "enroll_contact_in_sequence",
        json_schema_extra={
            "const": "enroll_contact_in_sequence",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Enroll Contact in Sequence",
            "x-keywords": [
                "enroll in sequence",
                "add contact to sequence",
                "start sequence for contact",
                "begin outreach sequence",
            ],
        },
        title="Enroll Contact in Sequence",
    )
    sequence_id: str = Field(..., title="Sequence ID", description="The sequence ID")
    contact_email: str = Field(
        ..., title="Contact Email", description="Email of contact to enroll"
    )


class HubSpotUnenrollFromSequenceConfig(BaseModel):
    model_config = ConfigDict(title="Unenroll From Sequence")
    """Unenroll a contact from a sequence"""
    operation: Literal["unenroll_contact_from_sequence"] = Field(
        "unenroll_contact_from_sequence",
        json_schema_extra={
            "const": "unenroll_contact_from_sequence",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Unenroll Contact from Sequence",
            "x-keywords": [
                "unenroll from sequence",
                "remove contact from sequence",
                "stop sequence for contact",
                "exit sequence",
            ],
        },
        title="Unenroll Contact from Sequence",
    )
    sequence_id: str = Field(..., title="Sequence ID", description="The sequence ID")
    contact_email: str = Field(
        ..., title="Contact Email", description="Email of contact to unenroll"
    )


# ============================================================================
# Settings & Account API Configs
# ============================================================================


class HubSpotListUsersConfig(BaseModel):
    model_config = ConfigDict(title="List Users")
    """List all users"""
    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Users",
            "x-keywords": [
                "browse hubspot users",
                "all portal users",
                "show account users",
                "list seats",
            ],
        },
        title="List Users",
    )


class HubSpotGetUserConfig(BaseModel):
    model_config = ConfigDict(title="Get User")
    """Get a specific user"""
    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User",
            "x-keywords": [
                "fetch hubspot user",
                "user details",
                "lookup portal user",
                "single user",
            ],
        },
        title="Get User",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")


class HubSpotCreateUserConfig(BaseModel):
    model_config = ConfigDict(title="Create User")
    """Create a new user (Enterprise only)"""
    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Create User",
            "x-keywords": [
                "invite user",
                "add hubspot user",
                "provision seat",
                "onboard teammate",
            ],
        },
        title="Create User",
    )
    user_data: str = Field(
        ...,
        title="User Data",
        description="JSON object with user details (email, roleId, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateUserConfig(BaseModel):
    model_config = ConfigDict(title="Update User")
    """Update a user (Enterprise only)"""
    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Update User",
            "x-keywords": [
                "edit hubspot user",
                "change user role",
                "modify portal user",
                "update user permissions",
            ],
        },
        title="Update User",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")
    user_data: str = Field(
        ...,
        title="User Data",
        description="JSON object with updated user properties",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotDeleteUserConfig(BaseModel):
    model_config = ConfigDict(title="Delete User")
    """Delete a user (Enterprise only)"""
    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Delete User",
            "x-keywords": [
                "remove hubspot user",
                "deactivate user",
                "revoke seat",
                "offboard teammate",
            ],
        },
        title="Delete User",
    )
    user_id: str = Field(..., title="User ID", description="The user ID to delete")


class HubSpotListBusinessUnitsConfig(BaseModel):
    model_config = ConfigDict(title="List Business Units")
    """List all business units"""
    operation: Literal["list_business_units"] = Field(
        "list_business_units",
        json_schema_extra={
            "const": "list_business_units",
            "ui:hidden": True,
            "x-category": "Business Unit",
            "x-is-trigger": False,
            "x-display-name": "List Business Units",
            "x-keywords": [
                "browse business units",
                "all brand units",
                "show business units",
                "list brands",
            ],
        },
        title="List Business Units",
    )


class HubSpotGetBusinessUnitConfig(BaseModel):
    model_config = ConfigDict(title="Get Business Unit")
    """Get a specific business unit"""
    operation: Literal["get_business_unit"] = Field(
        "get_business_unit",
        json_schema_extra={
            "const": "get_business_unit",
            "ui:hidden": True,
            "x-category": "Business Unit",
            "x-is-trigger": False,
            "x-display-name": "Get Business Unit",
            "x-keywords": [
                "fetch business unit",
                "business unit details",
                "lookup brand unit",
                "single business unit",
            ],
        },
        title="Get Business Unit",
    )
    business_unit_id: str = Field(
        ..., title="Business Unit ID", description="The business unit ID"
    )


class HubSpotGetAccountInfoConfig(BaseModel):
    model_config = ConfigDict(title="Get Account Info")
    """Get account information"""
    operation: Literal["get_account_info"] = Field(
        "get_account_info",
        json_schema_extra={
            "const": "get_account_info",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account Info",
            "x-keywords": [
                "account details",
                "portal info",
                "hub account settings",
                "account metadata",
                "company account info",
            ],
        },
        title="Get Account Info",
    )


class HubSpotListAuditLogsConfig(BaseModel):
    model_config = ConfigDict(title="List Audit Logs")
    """List audit logs (Enterprise only)"""
    operation: Literal["list_audit_logs"] = Field(
        "list_audit_logs",
        json_schema_extra={
            "const": "list_audit_logs",
            "ui:hidden": True,
            "x-category": "Audit Log",
            "x-is-trigger": False,
            "x-display-name": "List Audit Logs",
            "x-keywords": [
                "browse audit logs",
                "activity history",
                "change log",
                "security log",
                "who did what",
            ],
        },
        title="List Audit Logs",
    )
    after: Optional[str] = Field(
        None, title="After", description="Cursor for pagination"
    )


class HubSpotListGoalsConfig(BaseModel):
    model_config = ConfigDict(title="List Goals")
    """List all goals"""
    operation: Literal["list_goals"] = Field(
        "list_goals",
        json_schema_extra={
            "const": "list_goals",
            "ui:hidden": True,
            "x-category": "Goal",
            "x-is-trigger": False,
            "x-display-name": "List Goals",
            "x-keywords": [
                "browse sales goals",
                "all targets",
                "show goals",
                "list quotas",
            ],
        },
        title="List Goals",
    )


class HubSpotGetGoalConfig(BaseModel):
    model_config = ConfigDict(title="Get Goal")
    """Get a specific goal"""
    operation: Literal["get_goal"] = Field(
        "get_goal",
        json_schema_extra={
            "const": "get_goal",
            "ui:hidden": True,
            "x-category": "Goal",
            "x-is-trigger": False,
            "x-display-name": "Get Goal",
            "x-keywords": [
                "fetch sales goal",
                "goal details",
                "lookup target",
                "single goal",
            ],
        },
        title="Get Goal",
    )
    goal_id: str = Field(..., title="Goal ID", description="The goal ID")


class HubSpotListTeamsConfig(BaseModel):
    model_config = ConfigDict(title="List Teams")
    """List all teams"""
    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
            "x-keywords": [
                "browse teams",
                "all sales teams",
                "show teams",
                "list groups",
            ],
        },
        title="List Teams",
    )


class HubSpotGetTeamConfig(BaseModel):
    model_config = ConfigDict(title="Get Team")
    """Get a specific team"""
    operation: Literal["get_team"] = Field(
        "get_team",
        json_schema_extra={
            "const": "get_team",
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
            "x-keywords": [
                "fetch team",
                "team details",
                "lookup sales team",
                "single team",
            ],
        },
        title="Get Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team ID")


class HubSpotListRolesConfig(BaseModel):
    model_config = ConfigDict(title="List Roles")
    """List all user roles"""
    operation: Literal["list_roles"] = Field(
        "list_roles",
        json_schema_extra={
            "const": "list_roles",
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "List Roles",
            "x-keywords": [
                "browse permission roles",
                "all access roles",
                "show roles",
                "list permission sets",
            ],
        },
        title="List Roles",
    )


class HubSpotGetRoleConfig(BaseModel):
    model_config = ConfigDict(title="Get Role")
    """Get a specific role"""
    operation: Literal["get_role"] = Field(
        "get_role",
        json_schema_extra={
            "const": "get_role",
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Get Role",
            "x-keywords": [
                "fetch permission role",
                "role details",
                "lookup access role",
                "single role",
            ],
        },
        title="Get Role",
    )
    role_id: str = Field(..., title="Role ID", description="The role ID")


# ============================================================================
# Data Management API Configs
# ============================================================================


class HubSpotCreateExportConfig(BaseModel):
    model_config = ConfigDict(title="Create Export")
    """Create a data export"""
    operation: Literal["create_data_export"] = Field(
        "create_data_export",
        json_schema_extra={
            "const": "create_data_export",
            "ui:hidden": True,
            "x-category": "Data Import/Export",
            "x-is-trigger": False,
            "x-display-name": "Create Data Export",
            "x-keywords": [
                "export crm data",
                "start data export",
                "kick off export",
                "request export",
            ],
        },
        title="Create Data Export",
    )
    export_type: str = Field(
        ...,
        title="Export Type",
        description="Type of export (CONTACTS, COMPANIES, DEALS, etc.)",
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="JSON array of properties to include",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotGetExportStatusConfig(BaseModel):
    model_config = ConfigDict(title="Get Export Status")
    """Get export status"""
    operation: Literal["get_export_status"] = Field(
        "get_export_status",
        json_schema_extra={
            "const": "get_export_status",
            "ui:hidden": True,
            "x-category": "Data Import/Export",
            "x-is-trigger": False,
            "x-display-name": "Get Export Status",
            "x-keywords": [
                "check export status",
                "export progress",
                "is export done",
                "export job state",
            ],
        },
        title="Get Export Status",
    )
    export_id: str = Field(..., title="Export ID", description="The export ID")


class HubSpotDownloadExportConfig(BaseModel):
    model_config = ConfigDict(title="Download Export")
    """Download completed export"""
    operation: Literal["download_data_export"] = Field(
        "download_data_export",
        json_schema_extra={
            "const": "download_data_export",
            "ui:hidden": True,
            "x-category": "Data Import/Export",
            "x-is-trigger": False,
            "x-display-name": "Download Data Export",
            "x-keywords": [
                "download export file",
                "grab exported data",
                "retrieve export",
                "fetch export file",
            ],
        },
        title="Download Data Export",
    )
    export_id: str = Field(..., title="Export ID", description="The export ID")


class HubSpotCreateImportConfig(BaseModel):
    model_config = ConfigDict(title="Create Import")
    """Create a data import"""
    operation: Literal["create_data_import"] = Field(
        "create_data_import",
        json_schema_extra={
            "const": "create_data_import",
            "ui:hidden": True,
            "x-category": "Data Import/Export",
            "x-is-trigger": False,
            "x-display-name": "Create Data Import",
            "x-keywords": [
                "import crm data",
                "start data import",
                "bulk import records",
                "upload import file",
            ],
        },
        title="Create Data Import",
    )
    import_data: str = Field(
        ...,
        title="Import Data",
        description=(
            "The importRequest JSON (name, files[].fileName/fileFormat/"
            "fileImportPage.columnMappings). Sent as the multipart importRequest part."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    file_url: str = Field(
        ...,
        title="File URL",
        description="URL of the CSV/spreadsheet to import (fetched and uploaded as the file part).",
    )


class HubSpotGetImportStatusConfig(BaseModel):
    model_config = ConfigDict(title="Get Import Status")
    """Get import status"""
    operation: Literal["get_import_status"] = Field(
        "get_import_status",
        json_schema_extra={
            "const": "get_import_status",
            "ui:hidden": True,
            "x-category": "Data Import/Export",
            "x-is-trigger": False,
            "x-display-name": "Get Import Status",
            "x-keywords": [
                "check import status",
                "import progress",
                "is import done",
                "import job state",
            ],
        },
        title="Get Import Status",
    )
    import_id: str = Field(..., title="Import ID", description="The import ID")


# ============================================================================
# OAuth API Configs
# ============================================================================


class HubSpotGetAccessTokenInfoConfig(BaseModel):
    model_config = ConfigDict(title="Get Access Token Info")
    """Get access token information"""
    operation: Literal["get_access_token_info"] = Field(
        "get_access_token_info",
        json_schema_extra={
            "const": "get_access_token_info",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Access Token Info",
            "x-keywords": [
                "token details",
                "inspect access token",
                "token metadata",
                "whose token is this",
            ],
        },
        title="Get Access Token Info",
    )


class HubSpotRevokeAccessTokenConfig(BaseModel):
    model_config = ConfigDict(title="Revoke Access Token")
    """Revoke an access token"""
    operation: Literal["revoke_access_token"] = Field(
        "revoke_access_token",
        json_schema_extra={
            "const": "revoke_access_token",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Revoke Access Token",
            "x-keywords": [
                "revoke oauth token",
                "invalidate token",
                "disconnect token",
                "kill access token",
            ],
        },
        title="Revoke Access Token",
    )
    token: str = Field(..., title="Token", description="The access token to revoke")


class HubSpotListScopesConfig(BaseModel):
    model_config = ConfigDict(title="List Scopes")
    """List OAuth scopes for current token"""
    operation: Literal["list_api_scopes"] = Field(
        "list_api_scopes",
        json_schema_extra={
            "const": "list_api_scopes",
            "ui:hidden": True,
            "x-category": "API Scope",
            "x-is-trigger": False,
            "x-display-name": "List Api Scopes",
            "x-keywords": [
                "browse api scopes",
                "available permissions",
                "oauth scopes",
                "list granted scopes",
            ],
        },
        title="List Api Scopes",
    )


class HubSpotValidateTokenConfig(BaseModel):
    model_config = ConfigDict(title="Validate Token")
    """Validate an access token"""
    operation: Literal["validate_access_token"] = Field(
        "validate_access_token",
        json_schema_extra={
            "const": "validate_access_token",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Validate Access Token",
            "x-keywords": [
                "check token valid",
                "verify access token",
                "is token good",
                "test token",
            ],
        },
        title="Validate Access Token",
    )


# ============================================================================
# Feedback Submissions API Configs
# ============================================================================


class HubSpotListFeedbackSubmissionsConfig(BaseModel):
    model_config = ConfigDict(title="List Feedback Submissions")
    """List feedback submissions"""
    operation: Literal["list_feedback_submissions"] = Field(
        "list_feedback_submissions",
        json_schema_extra={
            "const": "list_feedback_submissions",
            "ui:hidden": True,
            "x-category": "Feedback Submission",
            "x-is-trigger": False,
            "x-display-name": "List Feedback Submissions",
            "x-keywords": [
                "list survey responses",
                "nps responses",
                "csat results",
                "customer feedback responses",
                "survey submissions",
                "all feedback entries",
            ],
        },
        title="List Feedback Submissions",
    )


class HubSpotGetFeedbackSubmissionConfig(BaseModel):
    model_config = ConfigDict(title="Get Feedback Submission")
    """Get a specific feedback submission"""
    operation: Literal["get_feedback_submission"] = Field(
        "get_feedback_submission",
        json_schema_extra={
            "const": "get_feedback_submission",
            "ui:hidden": True,
            "x-category": "Feedback Submission",
            "x-is-trigger": False,
            "x-display-name": "Get Feedback Submission",
            "x-keywords": [
                "single survey response",
                "view feedback entry",
                "one nps response",
                "feedback submission details",
                "specific survey reply",
            ],
        },
        title="Get Feedback Submission",
    )
    submission_id: str = Field(
        ..., title="Submission ID", description="The feedback submission ID"
    )


# ============================================================================
# Custom Events API Configs (Behavioral Tracking)
# CRITICAL: Replaces legacy Analytics Events API (sunset Aug 1, 2025)
# ============================================================================


class HubSpotSendCustomEventConfig(BaseModel):
    model_config = ConfigDict(title="Send Custom Event")
    """Send a custom behavioral event"""
    operation: Literal["send_custom_event"] = Field(
        "send_custom_event",
        json_schema_extra={
            "const": "send_custom_event",
            "ui:hidden": True,
            "x-category": "Custom Event",
            "x-is-trigger": False,
            "x-display-name": "Send Custom Event",
            "x-keywords": [
                "track custom event",
                "fire custom event",
                "log behavioral event",
                "emit event",
                "record analytics event",
            ],
        },
        title="Send Custom Event",
    )
    event_name: str = Field(
        ...,
        title="Event Name",
        description="Name of the custom event (must match event definition)",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Contact email to associate event with"
    )
    utk: Optional[str] = Field(
        None, title="User Token (UTK)", description="HubSpot user token cookie value"
    )
    object_id: Optional[str] = Field(
        None, title="Object ID", description="CRM object ID to associate event with"
    )
    properties: Optional[str] = Field(
        None,
        title="Event Properties",
        description="JSON object with custom event properties",
        json_schema_extra={"ui:widget": "textarea"},
    )
    occurred_at: Optional[str] = Field(
        None,
        title="Occurred At",
        description="ISO 8601 timestamp when event occurred (defaults to now)",
    )


class HubSpotListEventDefinitionsConfig(BaseModel):
    model_config = ConfigDict(title="List Event Definitions")
    """List all custom event definitions"""
    operation: Literal["list_custom_event_definitions"] = Field(
        "list_custom_event_definitions",
        json_schema_extra={
            "const": "list_custom_event_definitions",
            "ui:hidden": True,
            "x-category": "Custom Event",
            "x-is-trigger": False,
            "x-display-name": "List Custom Event Definitions",
            "x-keywords": [
                "custom event definitions",
                "behavioral event types",
                "event schema list",
                "defined custom events",
            ],
        },
        title="List Custom Event Definitions",
    )


class HubSpotCreateEventDefinitionConfig(BaseModel):
    model_config = ConfigDict(title="Create Event Definition")
    """Create a new custom event definition"""
    operation: Literal["create_custom_event_definition"] = Field(
        "create_custom_event_definition",
        json_schema_extra={
            "const": "create_custom_event_definition",
            "ui:hidden": True,
            "x-category": "Custom Event",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Event Definition",
            "x-keywords": [
                "define custom event",
                "new event definition",
                "register behavioral event",
                "set up event type",
            ],
        },
        title="Create Custom Event Definition",
    )
    name: str = Field(
        ...,
        title="Event Name",
        description="Unique name for the event (lowercase, underscores allowed)",
    )
    label: str = Field(
        ..., title="Display Label", description="Human-readable label for the event"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of what this event tracks"
    )
    property_definitions: Optional[str] = Field(
        None,
        title="Property Definitions",
        description="JSON array of property definitions with name, label, type, description",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HubSpotUpdateEventDefinitionConfig(BaseModel):
    model_config = ConfigDict(title="Update Event Definition")
    """Update an existing custom event definition"""
    operation: Literal["update_custom_event_definition"] = Field(
        "update_custom_event_definition",
        json_schema_extra={
            "const": "update_custom_event_definition",
            "ui:hidden": True,
            "x-category": "Custom Event",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Event Definition",
            "x-keywords": [
                "edit event definition",
                "change custom event schema",
                "modify event type",
            ],
        },
        title="Update Custom Event Definition",
    )
    event_name: str = Field(
        ..., title="Event Name", description="Name of the event definition to update"
    )
    label: Optional[str] = Field(
        None, title="Display Label", description="Updated human-readable label"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Updated description"
    )
    property_definitions: Optional[str] = Field(
        None,
        title="Property Definitions",
        description="JSON array of updated property definitions",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


def _hubspot_trigger_field(value: str, display: str, keywords: Optional[list] = None):
    """Build the hidden `operation` discriminator Field for a HubSpot trigger."""
    extra = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(value, json_schema_extra=extra, title=display)


class _HubSpotEventTriggerBase(BaseModel):
    """Shared fields for HubSpot per-event triggers.

    Each per-event trigger op is a separate operation (On Contact Created, etc.)
    so the user picks the specific trigger rather than a generic event field; the
    subscription type is resolved from the operation via ``_trigger_event_map``.
    """

    subscription_status: Optional[str] = Field(
        default=None,
        title="Status",
        json_schema_extra={"ui:widget": "readonly", "ui:loadValue": True},
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class HubSpotOnContactCreatedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a contact is created in the HubSpot account."""

    operation: Literal["on_contact_created"] = _hubspot_trigger_field(
        "on_contact_created",
        "On Contact Created",
        keywords=[
            "when new contact",
            "on contact added",
            "new lead added",
            "contact created trigger",
            "when someone signs up",
        ],
    )


class HubSpotOnContactUpdatedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a contact property changes in the HubSpot account."""

    operation: Literal["on_contact_updated"] = _hubspot_trigger_field(
        "on_contact_updated",
        "On Contact Updated",
        keywords=[
            "when contact changes",
            "on contact property change",
            "contact updated trigger",
            "when contact edited",
            "contact field changed",
        ],
    )


class HubSpotOnContactDeletedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a contact is deleted in the HubSpot account."""

    operation: Literal["on_contact_deleted"] = _hubspot_trigger_field(
        "on_contact_deleted",
        "On Contact Deleted",
        keywords=[
            "when contact removed",
            "on contact deleted",
            "contact deletion trigger",
            "when contact gone",
        ],
    )


class HubSpotOnDealCreatedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a deal is created in the HubSpot account."""

    operation: Literal["on_deal_created"] = _hubspot_trigger_field(
        "on_deal_created",
        "On Deal Created",
        keywords=[
            "when new deal",
            "on deal added",
            "new opportunity created",
            "deal created trigger",
            "when deal opened",
        ],
    )


class HubSpotOnDealUpdatedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a deal property changes in the HubSpot account."""

    operation: Literal["on_deal_updated"] = _hubspot_trigger_field(
        "on_deal_updated",
        "On Deal Updated",
        keywords=[
            "when deal changes",
            "on deal stage change",
            "deal updated trigger",
            "when deal moves stage",
            "deal field changed",
        ],
    )


class HubSpotOnCompanyCreatedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a company is created in the HubSpot account."""

    operation: Literal["on_company_created"] = _hubspot_trigger_field(
        "on_company_created",
        "On Company Created",
        keywords=[
            "when new company",
            "on company added",
            "new account created",
            "company created trigger",
            "new organization added",
        ],
    )


class HubSpotOnTicketCreatedConfig(_HubSpotEventTriggerBase):
    """Trigger: fires when a ticket is created in the HubSpot account."""

    operation: Literal["on_ticket_created"] = _hubspot_trigger_field(
        "on_ticket_created",
        "On Ticket Created",
        keywords=[
            "when new ticket",
            "on ticket opened",
            "new support ticket",
            "ticket created trigger",
            "support request opened",
        ],
    )


HubSpotConfig = Annotated[
    Union[
        # Trigger operations (7)
        HubSpotOnContactCreatedConfig,
        HubSpotOnContactUpdatedConfig,
        HubSpotOnContactDeletedConfig,
        HubSpotOnDealCreatedConfig,
        HubSpotOnDealUpdatedConfig,
        HubSpotOnCompanyCreatedConfig,
        HubSpotOnTicketCreatedConfig,
        # Contact operations (6)
        HubSpotListContactsConfig,
        HubSpotGetContactConfig,
        HubSpotCreateContactConfig,
        HubSpotUpdateContactConfig,
        HubSpotDeleteContactConfig,
        HubSpotSearchContactsConfig,
        # Company operations (6)
        HubSpotListCompaniesConfig,
        HubSpotGetCompanyConfig,
        HubSpotCreateCompanyConfig,
        HubSpotUpdateCompanyConfig,
        HubSpotDeleteCompanyConfig,
        HubSpotSearchCompaniesConfig,
        # Deal operations (6)
        HubSpotListDealsConfig,
        HubSpotGetDealConfig,
        HubSpotCreateDealConfig,
        HubSpotUpdateDealConfig,
        HubSpotDeleteDealConfig,
        HubSpotSearchDealsConfig,
        # Ticket operations (6)
        HubSpotListTicketsConfig,
        HubSpotGetTicketConfig,
        HubSpotCreateTicketConfig,
        HubSpotUpdateTicketConfig,
        HubSpotDeleteTicketConfig,
        HubSpotSearchTicketsConfig,
        # Lead operations (6)
        HubSpotListLeadsConfig,
        HubSpotGetLeadConfig,
        HubSpotCreateLeadConfig,
        HubSpotUpdateLeadConfig,
        HubSpotDeleteLeadConfig,
        HubSpotSearchLeadsConfig,
        # Product operations (6)
        HubSpotListProductsConfig,
        HubSpotGetProductConfig,
        HubSpotCreateProductConfig,
        HubSpotUpdateProductConfig,
        HubSpotDeleteProductConfig,
        HubSpotSearchProductsConfig,
        # Line Item operations (6)
        HubSpotListLineItemsConfig,
        HubSpotGetLineItemConfig,
        HubSpotCreateLineItemConfig,
        HubSpotUpdateLineItemConfig,
        HubSpotDeleteLineItemConfig,
        HubSpotSearchLineItemsConfig,
        # Quote operations (6)
        HubSpotListQuotesConfig,
        HubSpotGetQuoteConfig,
        HubSpotCreateQuoteConfig,
        HubSpotUpdateQuoteConfig,
        HubSpotDeleteQuoteConfig,
        HubSpotSearchQuotesConfig,
        # Note operations (6)
        HubSpotListNotesConfig,
        HubSpotGetNoteConfig,
        HubSpotCreateNoteConfig,
        HubSpotUpdateNoteConfig,
        HubSpotDeleteNoteConfig,
        HubSpotSearchNotesConfig,
        # Task operations (6)
        HubSpotListTasksConfig,
        HubSpotGetTaskConfig,
        HubSpotCreateTaskConfig,
        HubSpotUpdateTaskConfig,
        HubSpotDeleteTaskConfig,
        HubSpotSearchTasksConfig,
        # Call operations (6)
        HubSpotListCallsConfig,
        HubSpotGetCallConfig,
        HubSpotCreateCallConfig,
        HubSpotUpdateCallConfig,
        HubSpotDeleteCallConfig,
        HubSpotSearchCallsConfig,
        # Meeting operations (6)
        HubSpotListMeetingsConfig,
        HubSpotGetMeetingConfig,
        HubSpotCreateMeetingConfig,
        HubSpotUpdateMeetingConfig,
        HubSpotDeleteMeetingConfig,
        HubSpotSearchMeetingsConfig,
        # Email operations (6)
        HubSpotListEmailsConfig,
        HubSpotGetEmailConfig,
        HubSpotCreateEmailConfig,
        HubSpotUpdateEmailConfig,
        HubSpotDeleteEmailConfig,
        HubSpotSearchEmailsConfig,
        # Order operations (6)
        HubSpotListOrdersConfig,
        HubSpotGetOrderConfig,
        HubSpotCreateOrderConfig,
        HubSpotUpdateOrderConfig,
        HubSpotDeleteOrderConfig,
        HubSpotSearchOrdersConfig,
        # Owners API (1)
        HubSpotListOwnersConfig,
        # Associations API (3)
        HubSpotCreateAssociationConfig,
        HubSpotDeleteAssociationConfig,
        HubSpotListAssociationsConfig,
        # Properties API (5)
        HubSpotListPropertiesConfig,
        HubSpotGetPropertyConfig,
        HubSpotCreatePropertyConfig,
        HubSpotUpdatePropertyConfig,
        HubSpotArchivePropertyConfig,
        # Pipelines API (6)
        HubSpotListPipelinesConfig,
        HubSpotGetPipelineConfig,
        HubSpotCreatePipelineConfig,
        HubSpotUpdatePipelineConfig,
        HubSpotReplacePipelineConfig,
        HubSpotDeletePipelineConfig,
        # Pipeline Stages API (6)
        HubSpotListPipelineStagesConfig,
        HubSpotGetPipelineStageConfig,
        HubSpotCreatePipelineStageConfig,
        HubSpotUpdatePipelineStageConfig,
        HubSpotReplacePipelineStageConfig,
        HubSpotDeletePipelineStageConfig,
        # Batch Operations API (5)
        HubSpotBatchCreateConfig,
        HubSpotBatchReadConfig,
        HubSpotBatchUpdateConfig,
        HubSpotBatchArchiveConfig,
        HubSpotBatchUpsertConfig,
        # Lists (Segments) API v3 (6)
        HubSpotListListsConfig,
        HubSpotGetListConfig,
        HubSpotCreateListConfig,
        HubSpotUpdateListConfig,
        HubSpotDeleteListConfig,
        HubSpotBatchAddListMembersConfig,
        # Schema API (6)
        HubSpotListSchemasConfig,
        HubSpotGetSchemaConfig,
        HubSpotCreateSchemaConfig,
        HubSpotUpdateSchemaConfig,
        HubSpotDeleteSchemaConfig,
        HubSpotPurgeSchemaConfig,
        # Marketing Events API (8)
        HubSpotListMarketingEventsConfig,
        HubSpotGetMarketingEventConfig,
        HubSpotCreateMarketingEventConfig,
        HubSpotUpdateMarketingEventConfig,
        HubSpotDeleteMarketingEventConfig,
        HubSpotCreateAttendanceConfig,
        HubSpotGetAttendanceConfig,
        HubSpotDeleteAttendanceConfig,
        # Campaigns API (7)
        HubSpotListCampaignsConfig,
        HubSpotGetCampaignConfig,
        HubSpotCreateCampaignConfig,
        HubSpotUpdateCampaignConfig,
        HubSpotDeleteCampaignConfig,
        HubSpotGetCampaignAssetsConfig,
        HubSpotManageCampaignBudgetConfig,
        # Custom Events API (4)
        HubSpotSendCustomEventConfig,
        HubSpotListEventDefinitionsConfig,
        HubSpotCreateEventDefinitionConfig,
        HubSpotUpdateEventDefinitionConfig,
        # CMS HubDB API (12)
        HubSpotListHubDBTablesConfig,
        HubSpotGetHubDBTableConfig,
        HubSpotCreateHubDBTableConfig,
        HubSpotUpdateHubDBTableConfig,
        HubSpotPublishHubDBTableConfig,
        HubSpotDeleteHubDBTableConfig,
        HubSpotListHubDBRowsConfig,
        HubSpotGetHubDBRowConfig,
        HubSpotCreateHubDBRowConfig,
        HubSpotUpdateHubDBRowConfig,
        HubSpotDeleteHubDBRowConfig,
        HubSpotCloneHubDBTableConfig,
        # Communication Preferences API (4)
        HubSpotGetSubscriptionStatusConfig,
        HubSpotSubscribeContactConfig,
        HubSpotUnsubscribeContactConfig,
        HubSpotListSubscriptionTypesConfig,
        # CMS Pages API (6)
        HubSpotListPagesConfig,
        HubSpotGetPageConfig,
        HubSpotCreatePageConfig,
        HubSpotUpdatePageConfig,
        HubSpotDeletePageConfig,
        HubSpotPublishPageConfig,
        # CMS Blogs API (10)
        HubSpotListBlogPostsConfig,
        HubSpotGetBlogPostConfig,
        HubSpotCreateBlogPostConfig,
        HubSpotUpdateBlogPostConfig,
        HubSpotDeleteBlogPostConfig,
        HubSpotListBlogAuthorsConfig,
        HubSpotGetBlogAuthorConfig,
        HubSpotCreateBlogAuthorConfig,
        HubSpotListBlogTopicsConfig,
        HubSpotGetBlogTopicConfig,
        # CMS Files API (5)
        HubSpotListFilesConfig,
        HubSpotGetFileConfig,
        HubSpotUploadFileConfig,
        HubSpotUpdateFileConfig,
        HubSpotDeleteFileConfig,
        # CMS Domains API (2)
        HubSpotListDomainsConfig,
        HubSpotGetDomainConfig,
        # CMS URL Mappings API (5)
        HubSpotListUrlMappingsConfig,
        HubSpotGetUrlMappingConfig,
        HubSpotCreateUrlMappingConfig,
        HubSpotUpdateUrlMappingConfig,
        HubSpotDeleteUrlMappingConfig,
        # CMS Site Search API (1)
        HubSpotSearchContentConfig,
        # Conversations API (10)
        HubSpotListConversationThreadsConfig,
        HubSpotGetConversationThreadConfig,
        HubSpotListMessagesConfig,
        HubSpotSendMessageConfig,
        HubSpotListChannelsConfig,
        HubSpotGetChannelConfig,
        HubSpotIdentifyVisitorConfig,
        HubSpotGetVisitorConfig,
        HubSpotUpdateConversationStatusConfig,
        # Automation & Workflows API (8)
        HubSpotListWorkflowsConfig,
        HubSpotGetWorkflowConfig,
        HubSpotEnrollInWorkflowConfig,
        HubSpotUnenrollFromWorkflowConfig,
        HubSpotListSequencesConfig,
        HubSpotGetSequenceConfig,
        HubSpotEnrollInSequenceConfig,
        HubSpotUnenrollFromSequenceConfig,
        # Settings & Account API (15)
        HubSpotListUsersConfig,
        HubSpotGetUserConfig,
        HubSpotCreateUserConfig,
        HubSpotUpdateUserConfig,
        HubSpotDeleteUserConfig,
        HubSpotListBusinessUnitsConfig,
        HubSpotGetBusinessUnitConfig,
        HubSpotGetAccountInfoConfig,
        HubSpotListAuditLogsConfig,
        HubSpotListGoalsConfig,
        HubSpotGetGoalConfig,
        HubSpotListTeamsConfig,
        HubSpotGetTeamConfig,
        HubSpotListRolesConfig,
        HubSpotGetRoleConfig,
        # Data Management API (5)
        HubSpotCreateExportConfig,
        HubSpotGetExportStatusConfig,
        HubSpotDownloadExportConfig,
        HubSpotCreateImportConfig,
        HubSpotGetImportStatusConfig,
        # OAuth API (4)
        HubSpotGetAccessTokenInfoConfig,
        HubSpotRevokeAccessTokenConfig,
        HubSpotListScopesConfig,
        HubSpotValidateTokenConfig,
        # Feedback Submissions API (2)
        HubSpotListFeedbackSubmissionsConfig,
        HubSpotGetFeedbackSubmissionConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class HubSpotNodeConfig(NodeConfig[HubSpotConfig, HubSpotCredential]):
    """Full configuration for HubSpot node including credentials"""

    credentials: HubSpotCredential = Field(
        ..., description="HubSpot API credentials (OAuth or Private App Access Token)"
    )


# ============================================================================
# Node Implementation
# ============================================================================


class HubSpotNode(AppEventTriggerMixin, WorkflowNode):
    """
    HubSpot CRM automation node.

    Executes HubSpot CRM API operations for workflow automation.
    Supports 247 operations across multiple API categories:

    CRM Objects (78 operations):
    - Contacts, Companies, Deals, Tickets (core CRM)
    - Leads, Products, Line Items, Quotes (sales objects)
    - Notes, Tasks (activity tracking)
    - Calls, Meetings, Emails (engagement tracking)

    Commerce (6 operations):
    - Orders

    CRM System APIs (23 operations):
    - Owners API (1 operation)
    - Properties API (5 operations)
    - Pipelines API (6 operations)
    - Pipeline Stages API (6 operations)

    Cross-Object Operations (3 operations):
    - Associations API

    Batch Operations (5 operations):
    - Batch create, read, update, archive, upsert for all CRM objects

    Lists & Segmentation (6 operations):
    - Lists (Segments) API v3 (list, get, create, update, delete, batch add members)
    - CRITICAL: v1 API sunset April 30, 2026

    Schema API (6 operations):
    - Custom Object Schemas (list, get, create, update, delete, purge)
    - Foundation for custom objects

    Marketing & Campaigns (15 operations):
    - Marketing Events API (8 ops) - Webinars, conferences, attendance tracking
    - Campaigns API (7 ops) - Multi-channel campaigns, budget management

    Analytics & Events (4 operations):
    - Custom Events API (send events, manage event definitions)
    - CRITICAL: Replaces legacy Analytics Events API (sunset Aug 1, 2025)

    CMS (46 operations):
    - HubDB API (12 ops) - Database tables and rows management
    - Pages API (6 ops) - Site pages CRUD operations
    - Blogs API (10 ops) - Blog posts, authors, topics
    - Files API (5 ops) - File manager operations
    - Domains API (2 ops) - Domain management
    - URL Mappings API (5 ops) - URL redirects and mappings
    - Site Search API (2 ops) - Content search functionality
    - Communication Preferences API (4 ops) - Subscription management

    Conversations (10 operations):
    - Threads, messages, channels management
    - Visitor identification and tracking
    - Conversation status updates

    Automation & Workflows (8 operations):
    - Workflows API (4 ops) - Workflow enrollment and management
    - Sequences API (4 ops) - Sales sequence automation

    Settings & Account (15 operations):
    - User management (5 ops) - User provisioning (Enterprise)
    - Business Units (2 ops) - Multi-unit account management
    - Account Info (1 op) - Account details
    - Audit Logs (1 op) - Security audit trail (Enterprise)
    - Goals (2 ops) - Goal tracking
    - Teams (2 ops) - Team management
    - Roles (2 ops) - Permission management

    Data Management (5 operations):
    - Exports (3 ops) - Data export and download
    - Imports (2 ops) - Bulk data imports

    Webhooks (4 operations):
    - Subscription management for real-time event notifications

    Extensions (5 operations):
    - Calling SDK (3 ops) - Third-party calling integration
    - Video Conferencing (2 ops) - Meeting integration

    OAuth (5 operations):
    - Token management and validation

    Social Media (6 operations):
    - Social post publishing and scheduling
    - Channel management

    Feedback (2 operations):
    - Feedback submission tracking

    Authentication:
    - OAuth 2.0 (recommended for multi-account apps)
    - Private App Access Tokens (recommended for internal integrations)
    """

    edit_examples = [
        "Create contact with email and phone, add to list, set properties",
        "Search contacts by email domain and batch update pipeline stage",
        "Create deal for specific company and link associated contact",
        "Get deal properties and update close date, add follow-up task",
        "List all contacts in 'Trial Users' list and send email sequence",
        "Create support ticket with priority and assign to agent",
        "Batch import 500 leads into HubSpot with company information",
    ]

    _app_provider = "hubspot"
    _trigger_event_map = {
        "on_contact_created": ["contact.creation"],
        "on_contact_updated": ["contact.propertyChange"],
        "on_contact_deleted": ["contact.deletion"],
        "on_deal_created": ["deal.creation"],
        "on_deal_updated": ["deal.propertyChange"],
        "on_company_created": ["company.creation"],
        "on_ticket_created": ["ticket.creation"],
    }

    scope_registry = HUBSPOT_SCOPES

    connection_evidence = ConnectionEvidence(
        operation="list_pipelines",
        # Deal pipelines are the ones a HubSpot user has named themselves.
        operation_arguments={"object_type": "deals"},
        noun="deal pipelines",
        identity_operation="get_account_info",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return HubSpotNodeConfig

    # ========================================================================
    # App-event trigger (on_hubspot_event)
    # ========================================================================

    @classmethod
    async def _resolve_tenant_id(cls, credential: Dict[str, Any]) -> Optional[str]:
        """Return the HubSpot portalId — from the credential, or via the
        account-info endpoint for a private-app token."""
        hub_id = credential.get("hub_id")
        if hub_id:
            return str(hub_id)
        token = credential.get("access_token")
        if not token:
            return None
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{HUBSPOT_API_BASE}/integrations/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            portal_id = response.json().get("portalId")
            return str(portal_id) if portal_id else None

    async def _trigger_on_hubspot_event(self, op_config, credentials) -> Dict[str, Any]:
        """Output when the trigger node is run manually from the editor.

        In a live workflow the node fires from a HubSpot webhook delivery,
        fanned out by the app-level webhook receiver."""
        return {
            "message": (
                "This trigger fires when a subscribed HubSpot event occurs in "
                "the account. It outputs the HubSpot event payload."
            ),
            "event_types": self._trigger_event_map.get(op_config.operation, []),
        }

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
        if not config or not isinstance(config, HubSpotNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your HubSpot Private App access token."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Trigger operations
            "on_contact_created": self._trigger_on_hubspot_event,
            "on_contact_updated": self._trigger_on_hubspot_event,
            "on_contact_deleted": self._trigger_on_hubspot_event,
            "on_deal_created": self._trigger_on_hubspot_event,
            "on_deal_updated": self._trigger_on_hubspot_event,
            "on_company_created": self._trigger_on_hubspot_event,
            "on_ticket_created": self._trigger_on_hubspot_event,
            # Contact operations
            "list_contacts": self._handle_list_contacts,
            "get_contact": self._handle_get_contact,
            "create_contact": self._handle_create_contact,
            "update_contact": self._handle_update_contact,
            "delete_contact": self._handle_delete_contact,
            "search_contacts": self._handle_search_contacts,
            # Company operations
            "list_companies": self._handle_list_companies,
            "get_company": self._handle_get_company,
            "create_company": self._handle_create_company,
            "update_company": self._handle_update_company,
            "delete_company": self._handle_delete_company,
            "search_companies": self._handle_search_companies,
            # Deal operations
            "list_deals": self._handle_list_deals,
            "get_deal": self._handle_get_deal,
            "create_deal": self._handle_create_deal,
            "update_deal": self._handle_update_deal,
            "delete_deal": self._handle_delete_deal,
            "search_deals": self._handle_search_deals,
            # Ticket operations
            "list_support_tickets": self._handle_list_tickets,
            "get_support_ticket": self._handle_get_ticket,
            "create_support_ticket": self._handle_create_ticket,
            "update_support_ticket": self._handle_update_ticket,
            "delete_support_ticket": self._handle_delete_ticket,
            "search_support_tickets": self._handle_search_tickets,
            # Lead operations
            "list_leads": self._handle_list_leads,
            "get_lead": self._handle_get_lead,
            "create_lead": self._handle_create_lead,
            "update_lead": self._handle_update_lead,
            "delete_lead": self._handle_delete_lead,
            "search_leads": self._handle_search_leads,
            # Product operations
            "list_products": self._handle_list_products,
            "get_product": self._handle_get_product,
            "create_product": self._handle_create_product,
            "update_product": self._handle_update_product,
            "delete_product": self._handle_delete_product,
            "search_products": self._handle_search_products,
            # Line Item operations
            "list_line_items": self._handle_list_line_items,
            "get_line_item": self._handle_get_line_item,
            "create_line_item": self._handle_create_line_item,
            "update_line_item": self._handle_update_line_item,
            "delete_line_item": self._handle_delete_line_item,
            "search_line_items": self._handle_search_line_items,
            # Quote operations
            "list_quotes": self._handle_list_quotes,
            "get_quote": self._handle_get_quote,
            "create_quote": self._handle_create_quote,
            "update_quote": self._handle_update_quote,
            "delete_quote": self._handle_delete_quote,
            "search_quotes": self._handle_search_quotes,
            # Note operations
            "list_note_activities": self._handle_list_notes,
            "get_note_activity": self._handle_get_note,
            "create_note_activity": self._handle_create_note,
            "update_note_activity": self._handle_update_note,
            "delete_note_activity": self._handle_delete_note,
            "search_note_activities": self._handle_search_notes,
            # Task operations
            "list_task_activities": self._handle_list_tasks,
            "get_task_activity": self._handle_get_task,
            "create_task_activity": self._handle_create_task,
            "update_task_activity": self._handle_update_task,
            "delete_task_activity": self._handle_delete_task,
            "search_task_activities": self._handle_search_tasks,
            # Call operations
            "list_call_activities": self._handle_list_calls,
            "get_call_activity": self._handle_get_call,
            "create_call_activity": self._handle_create_call,
            "update_call_activity": self._handle_update_call,
            "delete_call_activity": self._handle_delete_call,
            "search_call_activities": self._handle_search_calls,
            # Meeting operations
            "list_meeting_activities": self._handle_list_meetings,
            "get_meeting_activity": self._handle_get_meeting,
            "create_meeting_activity": self._handle_create_meeting,
            "update_meeting_activity": self._handle_update_meeting,
            "delete_meeting_activity": self._handle_delete_meeting,
            "search_meeting_activities": self._handle_search_meetings,
            # Email operations
            "list_email_activities": self._handle_list_emails,
            "get_email_activity": self._handle_get_email,
            "create_email_activity": self._handle_create_email,
            "update_email_activity": self._handle_update_email,
            "delete_email_activity": self._handle_delete_email,
            "search_email_activities": self._handle_search_emails,
            # Order operations
            "list_orders": self._handle_list_orders,
            "get_order": self._handle_get_order,
            "create_order": self._handle_create_order,
            "update_order": self._handle_update_order,
            "delete_order": self._handle_delete_order,
            "search_orders": self._handle_search_orders,
            # Owners API
            "list_account_owners": self._handle_list_owners,
            # Associations API
            "create_record_association": self._handle_create_association,
            "delete_record_association": self._handle_delete_association,
            "list_record_associations": self._handle_list_associations,
            # Properties API
            "list_custom_properties": self._handle_list_properties,
            "get_custom_property": self._handle_get_property,
            "create_custom_property": self._handle_create_property,
            "update_custom_property": self._handle_update_property,
            "archive_custom_property": self._handle_archive_property,
            # Pipelines API
            "list_pipelines": self._handle_list_pipelines,
            "get_pipeline": self._handle_get_pipeline,
            "create_pipeline": self._handle_create_pipeline,
            "update_pipeline": self._handle_update_pipeline,
            "replace_pipeline": self._handle_replace_pipeline,
            "delete_pipeline": self._handle_delete_pipeline,
            # Pipeline Stages API
            "list_pipeline_stages": self._handle_list_pipeline_stages,
            "get_pipeline_stage": self._handle_get_pipeline_stage,
            "create_pipeline_stage": self._handle_create_pipeline_stage,
            "update_pipeline_stage": self._handle_update_pipeline_stage,
            "replace_pipeline_stage": self._handle_replace_pipeline_stage,
            "delete_pipeline_stage": self._handle_delete_pipeline_stage,
            # Batch Operations API
            "batch_create_records": self._handle_batch_create,
            "batch_read_records": self._handle_batch_read,
            "batch_update_records": self._handle_batch_update,
            "batch_archive_records": self._handle_batch_archive,
            "batch_upsert_records": self._handle_batch_upsert,
            # Lists (Segments) API v3
            "list_contact_lists": self._handle_list_lists,
            "get_contact_list": self._handle_get_list,
            "create_contact_list": self._handle_create_list,
            "update_contact_list": self._handle_update_list,
            "delete_contact_list": self._handle_delete_list,
            "add_contacts_to_list_batch": self._handle_batch_add_list_members,
            # Schema API
            "list_custom_object_schemas": self._handle_list_schemas,
            "get_custom_object_schema": self._handle_get_schema,
            "create_custom_object_schema": self._handle_create_schema,
            "update_custom_object_schema": self._handle_update_schema,
            "delete_custom_object_schema": self._handle_delete_schema,
            "purge_custom_object_schema": self._handle_purge_schema,
            # Marketing Events API
            "list_marketing_events": self._handle_list_marketing_events,
            "get_marketing_event": self._handle_get_marketing_event,
            "create_marketing_event": self._handle_create_marketing_event,
            "update_marketing_event": self._handle_update_marketing_event,
            "delete_marketing_event": self._handle_delete_marketing_event,
            "create_event_attendance": self._handle_create_attendance,
            "get_event_attendance": self._handle_get_attendance,
            "delete_event_attendance": self._handle_delete_attendance,
            # Campaigns API
            "list_marketing_campaigns": self._handle_list_campaigns,
            "get_marketing_campaign": self._handle_get_campaign,
            "create_marketing_campaign": self._handle_create_campaign,
            "update_marketing_campaign": self._handle_update_campaign,
            "delete_marketing_campaign": self._handle_delete_campaign,
            "get_campaign_assets": self._handle_get_campaign_assets,
            "update_campaign_budget": self._handle_manage_campaign_budget,
            # Custom Events API
            "send_custom_event": self._handle_send_custom_event,
            "list_custom_event_definitions": self._handle_list_event_definitions,
            "create_custom_event_definition": self._handle_create_event_definition,
            "update_custom_event_definition": self._handle_update_event_definition,
            # CMS HubDB API
            "list_hubdb_tables": self._handle_list_hubdb_tables,
            "get_hubdb_table": self._handle_get_hubdb_table,
            "create_hubdb_table": self._handle_create_hubdb_table,
            "update_hubdb_table": self._handle_update_hubdb_table,
            "publish_hubdb_table": self._handle_publish_hubdb_table,
            "delete_hubdb_table": self._handle_delete_hubdb_table,
            "list_hubdb_rows": self._handle_list_hubdb_rows,
            "get_hubdb_row": self._handle_get_hubdb_row,
            "create_hubdb_row": self._handle_create_hubdb_row,
            "update_hubdb_row": self._handle_update_hubdb_row,
            "delete_hubdb_row": self._handle_delete_hubdb_row,
            "clone_hubdb_table": self._handle_clone_hubdb_table,
            # Communication Preferences API
            "get_contact_subscription_status": self._handle_get_subscription_status,
            "subscribe_contact_to_list": self._handle_subscribe_contact,
            "unsubscribe_contact_from_list": self._handle_unsubscribe_contact,
            "list_subscription_types": self._handle_list_subscription_types,
            # CMS Pages API
            "list_website_pages": self._handle_list_pages,
            "get_website_page": self._handle_get_page,
            "create_website_page": self._handle_create_page,
            "update_website_page": self._handle_update_page,
            "delete_website_page": self._handle_delete_page,
            "publish_website_page": self._handle_publish_page,
            # CMS Blogs API
            "list_blog_posts": self._handle_list_blog_posts,
            "get_blog_post": self._handle_get_blog_post,
            "create_blog_post": self._handle_create_blog_post,
            "update_blog_post": self._handle_update_blog_post,
            "delete_blog_post": self._handle_delete_blog_post,
            "list_blog_authors": self._handle_list_blog_authors,
            "get_blog_author": self._handle_get_blog_author,
            "create_blog_author": self._handle_create_blog_author,
            "list_blog_topics": self._handle_list_blog_topics,
            "get_blog_topic": self._handle_get_blog_topic,
            # CMS Files API
            "list_files": self._handle_list_files,
            "get_file": self._handle_get_file,
            "upload_file": self._handle_upload_file,
            "update_file": self._handle_update_file,
            "delete_file": self._handle_delete_file,
            # CMS Domains API
            "list_domains": self._handle_list_domains,
            "get_domain": self._handle_get_domain,
            # CMS URL Mappings API
            "list_url_redirects": self._handle_list_url_mappings,
            "get_url_redirect": self._handle_get_url_mapping,
            "create_url_redirect": self._handle_create_url_mapping,
            "update_url_redirect": self._handle_update_url_mapping,
            "delete_url_redirect": self._handle_delete_url_mapping,
            # CMS Site Search API
            "search_website_content": self._handle_search_content,
            # Conversations API
            "list_conversation_threads": self._handle_list_conversation_threads,
            "get_conversation_thread": self._handle_get_conversation_thread,
            "list_conversation_messages": self._handle_list_messages,
            "send_conversation_message": self._handle_send_message,
            "list_communication_channels": self._handle_list_channels,
            "get_communication_channel": self._handle_get_channel,
            "identify_website_visitor": self._handle_identify_visitor,
            "get_visitor": self._handle_get_visitor,
            "update_conversation_status": self._handle_update_conversation_status,
            # Automation & Workflows API
            "list_workflows": self._handle_list_workflows,
            "get_workflow": self._handle_get_workflow,
            "enroll_contact_in_workflow": self._handle_enroll_in_workflow,
            "unenroll_contact_from_workflow": self._handle_unenroll_from_workflow,
            "list_sequences": self._handle_list_sequences,
            "get_sequence": self._handle_get_sequence,
            "enroll_contact_in_sequence": self._handle_enroll_in_sequence,
            "unenroll_contact_from_sequence": self._handle_unenroll_from_sequence,
            # Settings & Account API
            "list_users": self._handle_list_users,
            "get_user": self._handle_get_user,
            "create_user": self._handle_create_user,
            "update_user": self._handle_update_user,
            "delete_user": self._handle_delete_user,
            "list_business_units": self._handle_list_business_units,
            "get_business_unit": self._handle_get_business_unit,
            "get_account_info": self._handle_get_account_info,
            "list_audit_logs": self._handle_list_audit_logs,
            "list_goals": self._handle_list_goals,
            "get_goal": self._handle_get_goal,
            "list_teams": self._handle_list_teams,
            "get_team": self._handle_get_team,
            "list_roles": self._handle_list_roles,
            "get_role": self._handle_get_role,
            # Data Management API
            "create_data_export": self._handle_create_export,
            "get_export_status": self._handle_get_export_status,
            "download_data_export": self._handle_download_export,
            "create_data_import": self._handle_create_import,
            "get_import_status": self._handle_get_import_status,
            # OAuth API
            "get_access_token_info": self._handle_get_access_token_info,
            "revoke_access_token": self._handle_revoke_access_token,
            "list_api_scopes": self._handle_list_scopes,
            "validate_access_token": self._handle_validate_token,
            # Feedback Submissions API
            "list_feedback_submissions": self._handle_list_feedback_submissions,
            "get_feedback_submission": self._handle_get_feedback_submission,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Un-mask errors. ~159 handlers hardcode top-level status="success" while
        # the real HubSpot response (nested under "data") carries the true
        # error + status_code — so a 403/404/400 was being reported as success.
        # Propagate the inner failure so callers/agents see the real outcome.
        result = self._normalize_result(result)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    @staticmethod
    def _normalize_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """Surface the true status/status_code when a handler wrapped a failed
        _make_request result under "data" but hardcoded top-level success."""
        if not isinstance(result, dict):
            return result
        inner = result.get("data")
        if isinstance(inner, dict):
            if result.get("status") == "success" and inner.get("status") == "error":
                result["status"] = "error"
                result["error"] = inner.get("error")
                result["status_code"] = inner.get("status_code")
            elif "status_code" not in result and "status_code" in inner:
                result["status_code"] = inner.get("status_code")
        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring HubSpot OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating private-app tokens."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.hubspot_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="hubspot",
        )

    async def _ensure_fresh_token(self, credentials) -> str:
        """Return a valid HubSpot access token, refreshing + persisting if
        expired. Private-app tokens (PAT) are long-lived and returned as-is."""
        if not isinstance(credentials, HubSpotOAuthCredential):
            return credentials.access_token

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.hubspot_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="hubspot",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: HubSpotCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        files: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the HubSpot API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: API credentials (OAuth or PAT)
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        url = f"{HUBSPOT_API_BASE}{endpoint}"

        # OAuth access tokens expire (~30 min) and are refreshed; PATs are
        # long-lived and returned as-is.
        access_token = await self._ensure_fresh_token(credentials)

        headers = {"Authorization": f"Bearer {access_token}"}
        # For multipart/form-data uploads, let httpx set the Content-Type (with
        # boundary) itself — forcing application/json breaks the upload.
        if files is None:
            headers["Content-Type"] = "application/json"

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if files is not None:
                    response = await client.request(
                        method=method, url=url, headers=headers, params=params,
                        files=files, data=data,
                    )
                else:
                    response = await client.request(
                        method=method, url=url, headers=headers, params=params,
                        json=json_body,
                    )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    error_data = None
                    try:
                        error_data = response.json()
                        error_message = error_data.get("message", str(error_data))
                    except Exception:
                        error_message = error_text

                    # HubSpot returns a generic "app hasn't been granted all
                    # required scopes" 403 even when the scope IS granted but the
                    # account's plan tier doesn't include the feature. That's
                    # misleading. Translate it into an accurate message.
                    if (
                        response.status_code == 403
                        and isinstance(error_data, dict)
                        and action_name not in _INTERNAL_ACTION_NAMES
                    ):
                        translated = await self._translate_scope_error(
                            credentials, error_data
                        )
                        if translated:
                            error_message = translated

                    logger.error(f"[HubSpotNode] API error: {error_message}")
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
                logger.exception(f"[HubSpotNode] Request failed: {e}")
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
    # Generic CRM Object Helpers
    # =========================================================================

    async def _list_objects(
        self,
        object_type: str,
        limit: Optional[int],
        after: Optional[str],
        properties: Optional[str],
        credentials: HubSpotCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Generic list objects handler."""
        params: Dict[str, Any] = {}
        if limit:
            params["limit"] = limit
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties

        return await self._make_request(
            method="GET",
            endpoint=f"/crm/v3/objects/{object_type}",
            credentials=credentials,
            params=params if params else None,
            action_name=action_name,
        )

    async def _get_object(
        self,
        object_type: str,
        object_id: str,
        properties: Optional[str],
        credentials: HubSpotCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Generic get object handler."""
        params = {}
        if properties:
            params["properties"] = properties

        return await self._make_request(
            method="GET",
            endpoint=f"/crm/v3/objects/{object_type}/{object_id}",
            credentials=credentials,
            params=params if params else None,
            action_name=action_name,
        )

    async def _create_object(
        self,
        object_type: str,
        properties: Dict[str, Any],
        credentials: HubSpotCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Generic create object handler."""
        body = {"properties": properties}

        return await self._make_request(
            method="POST",
            endpoint=f"/crm/v3/objects/{object_type}",
            credentials=credentials,
            json_body=body,
            action_name=action_name,
        )

    async def _update_object(
        self,
        object_type: str,
        object_id: str,
        properties: Dict[str, Any],
        credentials: HubSpotCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Generic update object handler."""
        body = {"properties": properties}

        return await self._make_request(
            method="PATCH",
            endpoint=f"/crm/v3/objects/{object_type}/{object_id}",
            credentials=credentials,
            json_body=body,
            action_name=action_name,
        )

    async def _delete_object(
        self,
        object_type: str,
        object_id: str,
        credentials: HubSpotCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Generic delete object handler."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/crm/v3/objects/{object_type}/{object_id}",
            credentials=credentials,
            action_name=action_name,
        )

    async def _search_objects(
        self,
        object_type: str,
        query: Optional[str],
        filter_property: Optional[str],
        filter_operator: Optional[str],
        filter_value: Optional[str],
        limit: Optional[int],
        properties: Optional[str],
        credentials: HubSpotCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Generic search objects handler."""
        body: Dict[str, Any] = {}

        if query:
            body["query"] = query

        if filter_property and filter_value:
            body["filterGroups"] = [
                {
                    "filters": [
                        {
                            "propertyName": filter_property,
                            "operator": filter_operator or "EQ",
                            "value": filter_value,
                        }
                    ]
                }
            ]

        if limit:
            body["limit"] = limit

        if properties:
            body["properties"] = properties.split(",")

        return await self._make_request(
            method="POST",
            endpoint=f"/crm/v3/objects/{object_type}/search",
            credentials=credentials,
            json_body=body,
            action_name=action_name,
        )

    def _parse_additional_properties(
        self, additional_properties: Optional[str]
    ) -> Dict[str, Any]:
        """Parse additional properties JSON string."""
        if not additional_properties:
            return {}
        try:
            import json

            return json.loads(additional_properties)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                f"[HubSpotNode] Failed to parse additional_properties: {additional_properties}"
            )
            return {}

    # =========================================================================
    # Contact Operation Handlers
    # =========================================================================

    async def _handle_list_contacts(
        self, config: HubSpotListContactsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all contacts."""
        return await self._list_objects(
            object_type="contacts",
            limit=config.limit,
            after=config.after,
            properties=config.properties,
            credentials=credentials,
            action_name="list_contacts",
        )

    async def _handle_get_contact(
        self, config: HubSpotGetContactConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific contact."""
        return await self._get_object(
            object_type="contacts",
            object_id=config.contact_id,
            properties=config.properties,
            credentials=credentials,
            action_name="get_contact",
        )

    async def _handle_create_contact(
        self, config: HubSpotCreateContactConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new contact."""
        properties: Dict[str, Any] = {}
        if config.email:
            properties["email"] = config.email
        if config.firstname:
            properties["firstname"] = config.firstname
        if config.lastname:
            properties["lastname"] = config.lastname
        if config.phone:
            properties["phone"] = config.phone
        if config.company:
            properties["company"] = config.company
        if config.website:
            properties["website"] = config.website

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._create_object(
            object_type="contacts",
            properties=properties,
            credentials=credentials,
            action_name="create_contact",
        )

    async def _handle_update_contact(
        self, config: HubSpotUpdateContactConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing contact."""
        properties: Dict[str, Any] = {}
        if config.email is not None:
            properties["email"] = config.email
        if config.firstname is not None:
            properties["firstname"] = config.firstname
        if config.lastname is not None:
            properties["lastname"] = config.lastname
        if config.phone is not None:
            properties["phone"] = config.phone

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._update_object(
            object_type="contacts",
            object_id=config.contact_id,
            properties=properties,
            credentials=credentials,
            action_name="update_contact",
        )

    async def _handle_delete_contact(
        self, config: HubSpotDeleteContactConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a contact."""
        return await self._delete_object(
            object_type="contacts",
            object_id=config.contact_id,
            credentials=credentials,
            action_name="delete_contact",
        )

    async def _handle_search_contacts(
        self, config: HubSpotSearchContactsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for contacts."""
        return await self._search_objects(
            object_type="contacts",
            query=config.query,
            filter_property=config.filter_property,
            filter_operator=config.filter_operator,
            filter_value=config.filter_value,
            limit=config.limit,
            properties=config.properties,
            credentials=credentials,
            action_name="search_contacts",
        )

    # =========================================================================
    # Company Operation Handlers
    # =========================================================================

    async def _handle_list_companies(
        self, config: HubSpotListCompaniesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all companies."""
        return await self._list_objects(
            object_type="companies",
            limit=config.limit,
            after=config.after,
            properties=config.properties,
            credentials=credentials,
            action_name="list_companies",
        )

    async def _handle_get_company(
        self, config: HubSpotGetCompanyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific company."""
        return await self._get_object(
            object_type="companies",
            object_id=config.company_id,
            properties=config.properties,
            credentials=credentials,
            action_name="get_company",
        )

    async def _handle_create_company(
        self, config: HubSpotCreateCompanyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new company."""
        properties: Dict[str, Any] = {"name": config.name}
        if config.domain:
            properties["domain"] = config.domain
        if config.industry:
            properties["industry"] = config.industry
        if config.phone:
            properties["phone"] = config.phone
        if config.city:
            properties["city"] = config.city
        if config.state:
            properties["state"] = config.state
        if config.country:
            properties["country"] = config.country

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._create_object(
            object_type="companies",
            properties=properties,
            credentials=credentials,
            action_name="create_company",
        )

    async def _handle_update_company(
        self, config: HubSpotUpdateCompanyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing company."""
        properties: Dict[str, Any] = {}
        if config.name is not None:
            properties["name"] = config.name
        if config.domain is not None:
            properties["domain"] = config.domain
        if config.industry is not None:
            properties["industry"] = config.industry

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._update_object(
            object_type="companies",
            object_id=config.company_id,
            properties=properties,
            credentials=credentials,
            action_name="update_company",
        )

    async def _handle_delete_company(
        self, config: HubSpotDeleteCompanyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a company."""
        return await self._delete_object(
            object_type="companies",
            object_id=config.company_id,
            credentials=credentials,
            action_name="delete_company",
        )

    async def _handle_search_companies(
        self, config: HubSpotSearchCompaniesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for companies."""
        return await self._search_objects(
            object_type="companies",
            query=config.query,
            filter_property=config.filter_property,
            filter_operator=config.filter_operator,
            filter_value=config.filter_value,
            limit=config.limit,
            properties=config.properties,
            credentials=credentials,
            action_name="search_companies",
        )

    # =========================================================================
    # Deal Operation Handlers
    # =========================================================================

    async def _handle_list_deals(
        self, config: HubSpotListDealsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all deals."""
        return await self._list_objects(
            object_type="deals",
            limit=config.limit,
            after=config.after,
            properties=config.properties,
            credentials=credentials,
            action_name="list_deals",
        )

    async def _handle_get_deal(
        self, config: HubSpotGetDealConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific deal."""
        return await self._get_object(
            object_type="deals",
            object_id=config.deal_id,
            properties=config.properties,
            credentials=credentials,
            action_name="get_deal",
        )

    async def _handle_create_deal(
        self, config: HubSpotCreateDealConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new deal."""
        properties: Dict[str, Any] = {"dealname": config.dealname}
        if config.dealstage:
            properties["dealstage"] = config.dealstage
        if config.pipeline:
            properties["pipeline"] = config.pipeline
        if config.amount:
            properties["amount"] = config.amount
        if config.closedate:
            properties["closedate"] = config.closedate

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._create_object(
            object_type="deals",
            properties=properties,
            credentials=credentials,
            action_name="create_deal",
        )

    async def _handle_update_deal(
        self, config: HubSpotUpdateDealConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing deal."""
        properties: Dict[str, Any] = {}
        if config.dealname is not None:
            properties["dealname"] = config.dealname
        if config.dealstage is not None:
            properties["dealstage"] = config.dealstage
        if config.amount is not None:
            properties["amount"] = config.amount
        if config.closedate is not None:
            properties["closedate"] = config.closedate

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._update_object(
            object_type="deals",
            object_id=config.deal_id,
            properties=properties,
            credentials=credentials,
            action_name="update_deal",
        )

    async def _handle_delete_deal(
        self, config: HubSpotDeleteDealConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a deal."""
        return await self._delete_object(
            object_type="deals",
            object_id=config.deal_id,
            credentials=credentials,
            action_name="delete_deal",
        )

    async def _handle_search_deals(
        self, config: HubSpotSearchDealsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for deals."""
        return await self._search_objects(
            object_type="deals",
            query=config.query,
            filter_property=config.filter_property,
            filter_operator=config.filter_operator,
            filter_value=config.filter_value,
            limit=config.limit,
            properties=config.properties,
            credentials=credentials,
            action_name="search_deals",
        )

    # =========================================================================
    # Ticket Operation Handlers
    # =========================================================================

    async def _handle_list_tickets(
        self, config: HubSpotListTicketsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all tickets."""
        return await self._list_objects(
            object_type="tickets",
            limit=config.limit,
            after=config.after,
            properties=config.properties,
            credentials=credentials,
            action_name="list_support_tickets",
        )

    async def _handle_get_ticket(
        self, config: HubSpotGetTicketConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific ticket."""
        return await self._get_object(
            object_type="tickets",
            object_id=config.ticket_id,
            properties=config.properties,
            credentials=credentials,
            action_name="get_support_ticket",
        )

    async def _handle_create_ticket(
        self, config: HubSpotCreateTicketConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new ticket."""
        properties: Dict[str, Any] = {"subject": config.subject}
        if config.content:
            properties["content"] = config.content
        # HubSpot rejects ticket creation without a pipeline stage
        # ("Some required properties were not set"). When the stage is unset,
        # default to the stock Support pipeline ("0") and its first stage
        # ("1") so a subject-only create succeeds; explicit values always win.
        if config.hs_pipeline_stage:
            properties["hs_pipeline_stage"] = config.hs_pipeline_stage
            if config.hs_pipeline:
                properties["hs_pipeline"] = config.hs_pipeline
        else:
            properties["hs_pipeline"] = config.hs_pipeline or "0"
            properties["hs_pipeline_stage"] = "1"
        if config.hs_ticket_priority:
            properties["hs_ticket_priority"] = config.hs_ticket_priority

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._create_object(
            object_type="tickets",
            properties=properties,
            credentials=credentials,
            action_name="create_support_ticket",
        )

    async def _handle_update_ticket(
        self, config: HubSpotUpdateTicketConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing ticket."""
        properties: Dict[str, Any] = {}
        if config.subject is not None:
            properties["subject"] = config.subject
        if config.content is not None:
            properties["content"] = config.content
        if config.hs_pipeline_stage is not None:
            properties["hs_pipeline_stage"] = config.hs_pipeline_stage
        if config.hs_ticket_priority is not None:
            properties["hs_ticket_priority"] = config.hs_ticket_priority

        # Merge additional properties
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )

        return await self._update_object(
            object_type="tickets",
            object_id=config.ticket_id,
            properties=properties,
            credentials=credentials,
            action_name="update_support_ticket",
        )

    async def _handle_delete_ticket(
        self, config: HubSpotDeleteTicketConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a ticket."""
        return await self._delete_object(
            object_type="tickets",
            object_id=config.ticket_id,
            credentials=credentials,
            action_name="delete_support_ticket",
        )

    async def _handle_search_tickets(
        self, config: HubSpotSearchTicketsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for tickets."""
        return await self._search_objects(
            object_type="tickets",
            query=config.query,
            filter_property=config.filter_property,
            filter_operator=config.filter_operator,
            filter_value=config.filter_value,
            limit=config.limit,
            properties=config.properties,
            credentials=credentials,
            action_name="search_support_tickets",
        )

    # =========================================================================
    # Lead Operation Handlers
    # =========================================================================

    async def _handle_list_leads(
        self, config: HubSpotListLeadsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all leads."""
        return await self._list_objects(
            "leads",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_leads",
        )

    async def _handle_get_lead(
        self, config: HubSpotGetLeadConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific lead."""
        return await self._get_object(
            "leads", config.lead_id, config.properties, credentials, "get_lead"
        )

    async def _handle_create_lead(
        self, config: HubSpotCreateLeadConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new lead."""
        properties: Dict[str, Any] = {}
        if config.email:
            properties["email"] = config.email
        if config.firstname:
            properties["firstname"] = config.firstname
        if config.lastname:
            properties["lastname"] = config.lastname
        if config.company:
            properties["company"] = config.company
        if config.phone:
            properties["phone"] = config.phone
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "leads", properties, credentials, "create_lead"
        )

    async def _handle_update_lead(
        self, config: HubSpotUpdateLeadConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing lead."""
        properties: Dict[str, Any] = {}
        if config.email is not None:
            properties["email"] = config.email
        if config.firstname is not None:
            properties["firstname"] = config.firstname
        if config.lastname is not None:
            properties["lastname"] = config.lastname
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "leads", config.lead_id, properties, credentials, "update_lead"
        )

    async def _handle_delete_lead(
        self, config: HubSpotDeleteLeadConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a lead."""
        return await self._delete_object(
            "leads", config.lead_id, credentials, "delete_lead"
        )

    async def _handle_search_leads(
        self, config: HubSpotSearchLeadsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for leads."""
        return await self._search_objects(
            "leads",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_leads",
        )

    # =========================================================================
    # Product Operation Handlers
    # =========================================================================

    async def _handle_list_products(
        self, config: HubSpotListProductsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all products."""
        return await self._list_objects(
            "products",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_products",
        )

    async def _handle_get_product(
        self, config: HubSpotGetProductConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific product."""
        return await self._get_object(
            "products", config.product_id, config.properties, credentials, "get_product"
        )

    async def _handle_create_product(
        self, config: HubSpotCreateProductConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new product."""
        properties: Dict[str, Any] = {"name": config.name}
        if config.price:
            properties["price"] = config.price
        if config.description:
            properties["description"] = config.description
        if config.hs_sku:
            properties["hs_sku"] = config.hs_sku
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "products", properties, credentials, "create_product"
        )

    async def _handle_update_product(
        self, config: HubSpotUpdateProductConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing product."""
        properties: Dict[str, Any] = {}
        if config.name is not None:
            properties["name"] = config.name
        if config.price is not None:
            properties["price"] = config.price
        if config.description is not None:
            properties["description"] = config.description
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "products", config.product_id, properties, credentials, "update_product"
        )

    async def _handle_delete_product(
        self, config: HubSpotDeleteProductConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a product."""
        return await self._delete_object(
            "products", config.product_id, credentials, "delete_product"
        )

    async def _handle_search_products(
        self, config: HubSpotSearchProductsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for products."""
        return await self._search_objects(
            "products",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_products",
        )

    # =========================================================================
    # Line Item Operation Handlers
    # =========================================================================

    async def _handle_list_line_items(
        self, config: HubSpotListLineItemsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all line items."""
        return await self._list_objects(
            "line_items",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_line_items",
        )

    async def _handle_get_line_item(
        self, config: HubSpotGetLineItemConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific line item."""
        return await self._get_object(
            "line_items",
            config.line_item_id,
            config.properties,
            credentials,
            "get_line_item",
        )

    async def _handle_create_line_item(
        self, config: HubSpotCreateLineItemConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new line item."""
        properties: Dict[str, Any] = {"name": config.name}
        if config.quantity:
            properties["quantity"] = config.quantity
        if config.price:
            properties["price"] = config.price
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "line_items", properties, credentials, "create_line_item"
        )

    async def _handle_update_line_item(
        self, config: HubSpotUpdateLineItemConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing line item."""
        properties: Dict[str, Any] = {}
        if config.name is not None:
            properties["name"] = config.name
        if config.quantity is not None:
            properties["quantity"] = config.quantity
        if config.price is not None:
            properties["price"] = config.price
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "line_items",
            config.line_item_id,
            properties,
            credentials,
            "update_line_item",
        )

    async def _handle_delete_line_item(
        self, config: HubSpotDeleteLineItemConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a line item."""
        return await self._delete_object(
            "line_items", config.line_item_id, credentials, "delete_line_item"
        )

    async def _handle_search_line_items(
        self, config: HubSpotSearchLineItemsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for line items."""
        return await self._search_objects(
            "line_items",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_line_items",
        )

    # =========================================================================
    # Quote Operation Handlers
    # =========================================================================

    async def _handle_list_quotes(
        self, config: HubSpotListQuotesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all quotes."""
        return await self._list_objects(
            "quotes",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_quotes",
        )

    async def _handle_get_quote(
        self, config: HubSpotGetQuoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific quote."""
        return await self._get_object(
            "quotes", config.quote_id, config.properties, credentials, "get_quote"
        )

    async def _handle_create_quote(
        self, config: HubSpotCreateQuoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new quote."""
        properties: Dict[str, Any] = {"hs_title": config.hs_title}
        if config.hs_expiration_date:
            properties["hs_expiration_date"] = config.hs_expiration_date
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "quotes", properties, credentials, "create_quote"
        )

    async def _handle_update_quote(
        self, config: HubSpotUpdateQuoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing quote."""
        properties: Dict[str, Any] = {}
        if config.hs_title is not None:
            properties["hs_title"] = config.hs_title
        if config.hs_expiration_date is not None:
            properties["hs_expiration_date"] = config.hs_expiration_date
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "quotes", config.quote_id, properties, credentials, "update_quote"
        )

    async def _handle_delete_quote(
        self, config: HubSpotDeleteQuoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a quote."""
        return await self._delete_object(
            "quotes", config.quote_id, credentials, "delete_quote"
        )

    async def _handle_search_quotes(
        self, config: HubSpotSearchQuotesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for quotes."""
        return await self._search_objects(
            "quotes",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_quotes",
        )

    # =========================================================================
    # Note Operation Handlers
    # =========================================================================

    async def _handle_list_notes(
        self, config: HubSpotListNotesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all notes."""
        return await self._list_objects(
            "notes",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_notes",
        )

    async def _handle_get_note(
        self, config: HubSpotGetNoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific note."""
        return await self._get_object(
            "notes", config.note_id, config.properties, credentials, "get_note_activity"
        )

    async def _handle_create_note(
        self, config: HubSpotCreateNoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new note."""
        properties: Dict[str, Any] = {"hs_note_body": config.hs_note_body}
        if config.hs_timestamp:
            properties["hs_timestamp"] = config.hs_timestamp
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "notes", properties, credentials, "create_note"
        )

    async def _handle_update_note(
        self, config: HubSpotUpdateNoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing note."""
        properties: Dict[str, Any] = {}
        if config.hs_note_body is not None:
            properties["hs_note_body"] = config.hs_note_body
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "notes", config.note_id, properties, credentials, "update_note"
        )

    async def _handle_delete_note(
        self, config: HubSpotDeleteNoteConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a note."""
        return await self._delete_object(
            "notes", config.note_id, credentials, "delete_note"
        )

    async def _handle_search_notes(
        self, config: HubSpotSearchNotesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for notes."""
        return await self._search_objects(
            "notes",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_note_activities",
        )

    # =========================================================================
    # Task Operation Handlers
    # =========================================================================

    async def _handle_list_tasks(
        self, config: HubSpotListTasksConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all tasks."""
        return await self._list_objects(
            "tasks",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_tasks",
        )

    async def _handle_get_task(
        self, config: HubSpotGetTaskConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific task."""
        return await self._get_object(
            "tasks", config.task_id, config.properties, credentials, "get_task"
        )

    async def _handle_create_task(
        self, config: HubSpotCreateTaskConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new task."""
        properties: Dict[str, Any] = {"hs_task_subject": config.hs_task_subject}
        if config.hs_task_body:
            properties["hs_task_body"] = config.hs_task_body
        if config.hs_task_status:
            properties["hs_task_status"] = config.hs_task_status
        if config.hs_task_priority:
            properties["hs_task_priority"] = config.hs_task_priority
        if config.hs_timestamp:
            properties["hs_timestamp"] = config.hs_timestamp
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "tasks", properties, credentials, "create_task"
        )

    async def _handle_update_task(
        self, config: HubSpotUpdateTaskConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing task."""
        properties: Dict[str, Any] = {}
        if config.hs_task_subject is not None:
            properties["hs_task_subject"] = config.hs_task_subject
        if config.hs_task_body is not None:
            properties["hs_task_body"] = config.hs_task_body
        if config.hs_task_status is not None:
            properties["hs_task_status"] = config.hs_task_status
        if config.hs_task_priority is not None:
            properties["hs_task_priority"] = config.hs_task_priority
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "tasks", config.task_id, properties, credentials, "update_task"
        )

    async def _handle_delete_task(
        self, config: HubSpotDeleteTaskConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a task."""
        return await self._delete_object(
            "tasks", config.task_id, credentials, "delete_task"
        )

    async def _handle_search_tasks(
        self, config: HubSpotSearchTasksConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for tasks."""
        return await self._search_objects(
            "tasks",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_tasks",
        )

    # =========================================================================
    # Call Operation Handlers
    # =========================================================================

    async def _handle_list_calls(
        self, config: HubSpotListCallsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all calls."""
        return await self._list_objects(
            "calls",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_calls",
        )

    async def _handle_get_call(
        self, config: HubSpotGetCallConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific call."""
        return await self._get_object(
            "calls", config.call_id, config.properties, credentials, "get_call"
        )

    async def _handle_create_call(
        self, config: HubSpotCreateCallConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new call record."""
        properties: Dict[str, Any] = {}
        if config.hs_call_title:
            properties["hs_call_title"] = config.hs_call_title
        if config.hs_call_body:
            properties["hs_call_body"] = config.hs_call_body
        if config.hs_call_duration:
            properties["hs_call_duration"] = config.hs_call_duration
        if config.hs_call_status:
            properties["hs_call_status"] = config.hs_call_status
        if config.hs_timestamp:
            properties["hs_timestamp"] = config.hs_timestamp
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "calls", properties, credentials, "create_call_activity"
        )

    async def _handle_update_call(
        self, config: HubSpotUpdateCallConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing call record."""
        properties: Dict[str, Any] = {}
        if config.hs_call_title is not None:
            properties["hs_call_title"] = config.hs_call_title
        if config.hs_call_body is not None:
            properties["hs_call_body"] = config.hs_call_body
        if config.hs_call_duration is not None:
            properties["hs_call_duration"] = config.hs_call_duration
        if config.hs_call_status is not None:
            properties["hs_call_status"] = config.hs_call_status
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "calls", config.call_id, properties, credentials, "update_call_activity"
        )

    async def _handle_delete_call(
        self, config: HubSpotDeleteCallConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a call record."""
        return await self._delete_object(
            "calls", config.call_id, credentials, "delete_call_activity"
        )

    async def _handle_search_calls(
        self, config: HubSpotSearchCallsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for calls."""
        return await self._search_objects(
            "calls",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_call_activities",
        )

    # =========================================================================
    # Meeting Operation Handlers
    # =========================================================================

    async def _handle_list_meetings(
        self, config: HubSpotListMeetingsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all meetings."""
        return await self._list_objects(
            "meetings",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_meeting_activities",
        )

    async def _handle_get_meeting(
        self, config: HubSpotGetMeetingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific meeting."""
        return await self._get_object(
            "meetings",
            config.meeting_id,
            config.properties,
            credentials,
            "get_meeting_activity",
        )

    async def _handle_create_meeting(
        self, config: HubSpotCreateMeetingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new meeting record."""
        properties: Dict[str, Any] = {"hs_meeting_title": config.hs_meeting_title}
        if config.hs_meeting_body:
            properties["hs_meeting_body"] = config.hs_meeting_body
        if config.hs_meeting_start_time:
            properties["hs_meeting_start_time"] = config.hs_meeting_start_time
        if config.hs_meeting_end_time:
            properties["hs_meeting_end_time"] = config.hs_meeting_end_time
        if config.hs_meeting_outcome:
            properties["hs_meeting_outcome"] = config.hs_meeting_outcome
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "meetings", properties, credentials, "create_meeting_activity"
        )

    async def _handle_update_meeting(
        self, config: HubSpotUpdateMeetingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing meeting record."""
        properties: Dict[str, Any] = {}
        if config.hs_meeting_title is not None:
            properties["hs_meeting_title"] = config.hs_meeting_title
        if config.hs_meeting_body is not None:
            properties["hs_meeting_body"] = config.hs_meeting_body
        if config.hs_meeting_outcome is not None:
            properties["hs_meeting_outcome"] = config.hs_meeting_outcome
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "meetings",
            config.meeting_id,
            properties,
            credentials,
            "update_meeting_activity",
        )

    async def _handle_delete_meeting(
        self, config: HubSpotDeleteMeetingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a meeting record."""
        return await self._delete_object(
            "meetings", config.meeting_id, credentials, "delete_meeting_activity"
        )

    async def _handle_search_meetings(
        self, config: HubSpotSearchMeetingsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for meetings."""
        return await self._search_objects(
            "meetings",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_meeting_activities",
        )

    # =========================================================================
    # Email Operation Handlers
    # =========================================================================

    async def _handle_list_emails(
        self, config: HubSpotListEmailsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all email engagements."""
        return await self._list_objects(
            "emails",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_emails",
        )

    async def _handle_get_email(
        self, config: HubSpotGetEmailConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific email engagement."""
        return await self._get_object(
            "emails", config.email_id, config.properties, credentials, "get_email"
        )

    async def _handle_create_email(
        self, config: HubSpotCreateEmailConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new email engagement record."""
        properties: Dict[str, Any] = {"hs_email_subject": config.hs_email_subject}
        if config.hs_email_text:
            properties["hs_email_text"] = config.hs_email_text
        if config.hs_email_direction:
            properties["hs_email_direction"] = config.hs_email_direction
        if config.hs_email_status:
            properties["hs_email_status"] = config.hs_email_status
        if config.hs_timestamp:
            properties["hs_timestamp"] = config.hs_timestamp
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "emails", properties, credentials, "create_email_activity"
        )

    async def _handle_update_email(
        self, config: HubSpotUpdateEmailConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing email engagement record."""
        properties: Dict[str, Any] = {}
        if config.hs_email_subject is not None:
            properties["hs_email_subject"] = config.hs_email_subject
        if config.hs_email_text is not None:
            properties["hs_email_text"] = config.hs_email_text
        if config.hs_email_status is not None:
            properties["hs_email_status"] = config.hs_email_status
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "emails", config.email_id, properties, credentials, "update_email"
        )

    async def _handle_delete_email(
        self, config: HubSpotDeleteEmailConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete an email engagement record."""
        return await self._delete_object(
            "emails", config.email_id, credentials, "delete_email_activity"
        )

    async def _handle_search_emails(
        self, config: HubSpotSearchEmailsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for email engagements."""
        return await self._search_objects(
            "emails",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_email_activities",
        )

    # =========================================================================
    # Order Operation Handlers (Commerce)
    # =========================================================================

    async def _handle_list_orders(
        self, config: HubSpotListOrdersConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all orders."""
        return await self._list_objects(
            "orders",
            config.limit,
            config.after,
            config.properties,
            credentials,
            "list_orders",
        )

    async def _handle_get_order(
        self, config: HubSpotGetOrderConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific order."""
        return await self._get_object(
            "orders", config.order_id, config.properties, credentials, "get_order"
        )

    async def _handle_create_order(
        self, config: HubSpotCreateOrderConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new order."""
        properties: Dict[str, Any] = {}
        if config.hs_order_name:
            properties["hs_order_name"] = config.hs_order_name
        if config.hs_order_amount:
            properties["hs_order_amount"] = config.hs_order_amount
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._create_object(
            "orders", properties, credentials, "create_order"
        )

    async def _handle_update_order(
        self, config: HubSpotUpdateOrderConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing order."""
        properties: Dict[str, Any] = {}
        if config.hs_order_name is not None:
            properties["hs_order_name"] = config.hs_order_name
        if config.hs_order_amount is not None:
            properties["hs_order_amount"] = config.hs_order_amount
        properties.update(
            self._parse_additional_properties(config.additional_properties)
        )
        return await self._update_object(
            "orders", config.order_id, properties, credentials, "update_order"
        )

    async def _handle_delete_order(
        self, config: HubSpotDeleteOrderConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete an order."""
        return await self._delete_object(
            "orders", config.order_id, credentials, "delete_order"
        )

    async def _handle_search_orders(
        self, config: HubSpotSearchOrdersConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search for orders."""
        return await self._search_objects(
            "orders",
            config.query,
            config.filter_property,
            config.filter_operator,
            config.filter_value,
            config.limit,
            config.properties,
            credentials,
            "search_orders",
        )

    # =========================================================================
    # Owners API Handler (System)
    # =========================================================================

    async def _handle_list_owners(
        self, config: HubSpotListOwnersConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all owners (users) in the HubSpot account."""

        # Build request parameters
        params: Dict[str, Any] = {"limit": config.limit}
        if config.after:
            params["after"] = config.after

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/crm/v3/owners/",
            credentials,
            params=params,
            action_name="list_account_owners",
        )

        # Return standardized response
        return response_data

    # =========================================================================
    # Associations API Handlers (Cross-Object Operations)
    # =========================================================================

    async def _handle_create_association(
        self, config: HubSpotCreateAssociationConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create an association between two CRM objects."""

        # Build association request body
        request_body = [
            {
                "from": {"id": config.from_object_id},
                "to": {"id": config.to_object_id},
                "type": config.association_type_id,
            }
        ]

        # Make API request
        endpoint = f"/crm/v3/objects/{config.from_object_type}/{config.from_object_id}/associations/{config.to_object_type}/{config.to_object_id}/{config.association_type_id}"
        response_data = await self._make_request(
            "PUT", endpoint, credentials, action_name="create_record_association"
        )

        # Return standardized response
        return response_data

    async def _handle_delete_association(
        self, config: HubSpotDeleteAssociationConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete an association between two CRM objects."""

        # Make API request
        endpoint = f"/crm/v3/objects/{config.from_object_type}/{config.from_object_id}/associations/{config.to_object_type}/{config.to_object_id}/{config.association_type_id}"
        response_data = await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_record_association"
        )

        # Return standardized response
        return response_data

    async def _handle_list_associations(
        self, config: HubSpotListAssociationsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all associations for a specific object."""

        # Make API request
        endpoint = f"/crm/v3/objects/{config.object_type}/{config.object_id}/associations/{config.to_object_type}"
        response_data = await self._make_request(
            "GET", endpoint, credentials, action_name="list_record_associations"
        )

        # Return standardized response
        return response_data

    # =========================================================================
    # Properties API Handlers (System)
    # =========================================================================

    async def _handle_list_properties(
        self, config: HubSpotListPropertiesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all properties for a CRM object type."""

        # Build request parameters
        params: Dict[str, Any] = {}
        if config.data_sensitivity:
            params["dataSensitivity"] = config.data_sensitivity

        # Make API request
        endpoint = f"/crm/v3/properties/{config.object_type}"
        response_data = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params if params else None,
            action_name="list_custom_properties",
        )

        # Return standardized response
        return response_data

    async def _handle_get_property(
        self, config: HubSpotGetPropertyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific property by name."""

        # Make API request
        endpoint = f"/crm/v3/properties/{config.object_type}/{config.property_name}"
        response_data = await self._make_request(
            "GET", endpoint, credentials, action_name="get_custom_property"
        )

        # Return standardized response
        return response_data

    async def _handle_create_property(
        self, config: HubSpotCreatePropertyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new custom property for a CRM object."""

        # Build request body
        body: Dict[str, Any] = {
            "groupName": config.group_name,
            "name": config.name,
            "label": config.label,
            "type": config.type,
            "fieldType": config.field_type,
        }

        if config.description:
            body["description"] = config.description
        if config.has_unique_value is not None:
            body["hasUniqueValue"] = config.has_unique_value

        # Make API request
        endpoint = f"/crm/v3/properties/{config.object_type}"
        response_data = await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_custom_property",
        )

        # Return standardized response
        return response_data

    async def _handle_update_property(
        self, config: HubSpotUpdatePropertyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing property."""

        # Build request body
        body: Dict[str, Any] = {}
        if config.label is not None:
            body["label"] = config.label
        if config.description is not None:
            body["description"] = config.description
        if config.group_name is not None:
            body["groupName"] = config.group_name

        # Add additional fields if provided
        if config.additional_fields:
            additional = self._parse_additional_properties(config.additional_fields)
            body.update(additional)

        # Make API request
        endpoint = f"/crm/v3/properties/{config.object_type}/{config.property_name}"
        response_data = await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_custom_property",
        )

        # Return standardized response
        return response_data

    async def _handle_archive_property(
        self, config: HubSpotArchivePropertyConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Archive (delete) a property."""

        # Make API request
        endpoint = f"/crm/v3/properties/{config.object_type}/{config.property_name}"
        response_data = await self._make_request(
            "DELETE", endpoint, credentials, action_name="archive_custom_property"
        )

        # Return standardized response
        return response_data

    # =========================================================================
    # Pipelines API Handlers (System)
    # =========================================================================

    async def _handle_list_pipelines(
        self, config: HubSpotListPipelinesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all pipelines for an object type."""

        endpoint = f"/crm/v3/pipelines/{config.object_type}"
        response_data = await self._make_request(
            "GET", endpoint, credentials, action_name="list_pipelines"
        )

        return response_data

    async def _handle_get_pipeline(
        self, config: HubSpotGetPipelineConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific pipeline by ID."""

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}"
        response_data = await self._make_request(
            "GET", endpoint, credentials, action_name="get_pipeline"
        )

        return response_data

    async def _handle_create_pipeline(
        self, config: HubSpotCreatePipelineConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new pipeline."""

        body: Dict[str, Any] = {"label": config.label}
        if config.display_order is not None:
            body["displayOrder"] = config.display_order
        if config.stages:
            body["stages"] = json.loads(config.stages)

        endpoint = f"/crm/v3/pipelines/{config.object_type}"
        response_data = await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_pipeline"
        )

        return response_data

    async def _handle_update_pipeline(
        self, config: HubSpotUpdatePipelineConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing pipeline."""

        body: Dict[str, Any] = {}
        if config.label is not None:
            body["label"] = config.label
        if config.display_order is not None:
            body["displayOrder"] = config.display_order

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}"
        response_data = await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_pipeline",
        )

        return response_data

    async def _handle_replace_pipeline(
        self, config: HubSpotReplacePipelineConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Replace (overwrite) an existing pipeline."""

        body: Dict[str, Any] = {
            "label": config.label,
            "stages": json.loads(config.stages),
        }
        if config.display_order is not None:
            body["displayOrder"] = config.display_order

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}"
        response_data = await self._make_request(
            "PUT", endpoint, credentials, json_body=body, action_name="replace_pipeline"
        )

        return response_data

    async def _handle_delete_pipeline(
        self, config: HubSpotDeletePipelineConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a pipeline."""

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}"
        response_data = await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_pipeline"
        )

        return response_data

    # =========================================================================
    # Pipeline Stages API Handlers
    # =========================================================================

    async def _handle_list_pipeline_stages(
        self, config: HubSpotListPipelineStagesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all stages in a pipeline."""

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}/stages"
        response_data = await self._make_request(
            "GET", endpoint, credentials, action_name="list_pipeline_stages"
        )

        return response_data

    async def _handle_get_pipeline_stage(
        self, config: HubSpotGetPipelineStageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific pipeline stage by ID."""

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}/stages/{config.stage_id}"
        response_data = await self._make_request(
            "GET", endpoint, credentials, action_name="get_pipeline_stage"
        )

        return response_data

    async def _handle_create_pipeline_stage(
        self, config: HubSpotCreatePipelineStageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new pipeline stage."""

        body: Dict[str, Any] = {"label": config.label}
        if config.display_order is not None:
            body["displayOrder"] = config.display_order
        if config.metadata:
            body["metadata"] = json.loads(config.metadata)

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}/stages"
        response_data = await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_pipeline_stage",
        )

        return response_data

    async def _handle_update_pipeline_stage(
        self, config: HubSpotUpdatePipelineStageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing pipeline stage."""

        body: Dict[str, Any] = {}
        if config.label is not None:
            body["label"] = config.label
        if config.display_order is not None:
            body["displayOrder"] = config.display_order
        if config.metadata:
            body["metadata"] = json.loads(config.metadata)

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}/stages/{config.stage_id}"
        response_data = await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_pipeline_stage",
        )

        return response_data

    async def _handle_replace_pipeline_stage(
        self, config: HubSpotReplacePipelineStageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Replace (overwrite) an existing pipeline stage."""

        body: Dict[str, Any] = {
            "label": config.label,
            "metadata": json.loads(config.metadata),
        }
        if config.display_order is not None:
            body["displayOrder"] = config.display_order

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}/stages/{config.stage_id}"
        response_data = await self._make_request(
            "PUT",
            endpoint,
            credentials,
            json_body=body,
            action_name="replace_pipeline_stage",
        )

        return response_data

    async def _handle_delete_pipeline_stage(
        self, config: HubSpotDeletePipelineStageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a pipeline stage."""

        endpoint = f"/crm/v3/pipelines/{config.object_type}/{config.pipeline_id}/stages/{config.stage_id}"
        response_data = await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_pipeline_stage"
        )

        return response_data

    # =========================================================================
    # Batch Operations API Handlers
    # =========================================================================

    async def _handle_batch_create(
        self, config: HubSpotBatchCreateConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create multiple CRM objects in a single batch."""
        # Parse inputs JSON
        inputs = json.loads(config.inputs)

        # Build request body
        body = {"inputs": inputs}

        # Make API request
        endpoint = f"/crm/v3/objects/{config.object_type}/batch/create"
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="batch_create_records",
        )

    async def _handle_batch_read(
        self, config: HubSpotBatchReadConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Read multiple CRM objects by IDs in a single batch."""
        # Parse inputs JSON
        inputs = json.loads(config.inputs)

        # Build request body
        body = {"inputs": inputs}
        if config.properties:
            body["properties"] = config.properties.split(",")

        # Make API request
        endpoint = f"/crm/v3/objects/{config.object_type}/batch/read"
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="batch_read_records",
        )

    async def _handle_batch_update(
        self, config: HubSpotBatchUpdateConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update multiple CRM objects in a single batch."""
        # Parse inputs JSON
        inputs = json.loads(config.inputs)

        # Build request body
        body = {"inputs": inputs}

        # Make API request
        endpoint = f"/crm/v3/objects/{config.object_type}/batch/update"
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="batch_update_records",
        )

    async def _handle_batch_archive(
        self, config: HubSpotBatchArchiveConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Archive (delete) multiple CRM objects in a single batch."""
        # Parse inputs JSON
        inputs = json.loads(config.inputs)

        # Build request body
        body = {"inputs": inputs}

        # Make API request
        endpoint = f"/crm/v3/objects/{config.object_type}/batch/archive"
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="batch_archive_records",
        )

    async def _handle_batch_upsert(
        self, config: HubSpotBatchUpsertConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create or update multiple CRM objects by unique property in a single batch."""
        # Parse inputs JSON
        inputs = json.loads(config.inputs)

        # Build request body
        body = {"inputs": inputs}

        # Make API request
        endpoint = f"/crm/v3/objects/{config.object_type}/batch/upsert"
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="batch_upsert_records",
        )

    # ============================================================================
    # Custom Events API Handlers (Behavioral Tracking)
    # ============================================================================

    async def _handle_send_custom_event(
        self, config: HubSpotSendCustomEventConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Send a custom behavioral event."""

        # Build request body
        body: Dict[str, Any] = {"eventName": config.event_name}

        # Add optional fields
        if config.email:
            body["email"] = config.email
        if config.utk:
            body["utk"] = config.utk
        if config.object_id:
            body["objectId"] = config.object_id
        if config.properties:
            body["properties"] = json.loads(config.properties)
        if config.occurred_at:
            body["occurredAt"] = config.occurred_at

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/events/v3/send",
            credentials,
            json_body=body,
            action_name="send_custom_event",
        )

        return response_data

    async def _handle_list_event_definitions(
        self, config: HubSpotListEventDefinitionsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all custom event definitions."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/events/v3/event-definitions",
            credentials,
            action_name="list_custom_event_definitions",
        )

        return response_data

    async def _handle_create_event_definition(
        self, config: HubSpotCreateEventDefinitionConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new custom event definition."""

        # Build request body
        body: Dict[str, Any] = {"name": config.name, "label": config.label}

        # Add optional fields
        if config.description:
            body["description"] = config.description
        if config.property_definitions:
            body["propertyDefinitions"] = json.loads(config.property_definitions)

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/events/v3/event-definitions",
            credentials,
            json_body=body,
            action_name="create_custom_event_definition",
        )

        return response_data

    async def _handle_update_event_definition(
        self, config: HubSpotUpdateEventDefinitionConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing custom event definition."""

        # Build request body
        body: Dict[str, Any] = {}

        # Add optional fields
        if config.label:
            body["label"] = config.label
        if config.description:
            body["description"] = config.description
        if config.property_definitions:
            body["propertyDefinitions"] = json.loads(config.property_definitions)

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/events/v3/event-definitions/{config.event_name}",
            credentials,
            json_body=body,
            action_name="update_custom_event_definition",
        )

        return response_data

    # ============================================================================
    # Lists (Segments) API v3 Handlers
    # ============================================================================

    async def _handle_list_lists(
        self, config: HubSpotListListsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all lists/segments."""

        # Build query parameters
        params: Dict[str, Any] = {"limit": config.limit}
        if config.after:
            params["after"] = config.after

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/crm/v3/lists",
            credentials,
            params=params,
            action_name="list_contact_lists",
        )

        return response_data

    async def _handle_get_list(
        self, config: HubSpotGetListConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific list by ID."""

        # Build query parameters
        params: Dict[str, Any] = {}
        if config.include_filters is not None:
            params["includeFilters"] = str(config.include_filters).lower()

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/crm/v3/lists/{config.list_id}",
            credentials,
            params=params if params else None,
            action_name="get_contact_list",
        )

        return response_data

    async def _handle_create_list(
        self, config: HubSpotCreateListConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new list/segment."""

        # Build request body
        body: Dict[str, Any] = {
            "name": config.name,
            "objectTypeId": config.object_type_id,
            "processingType": config.processing_type,
        }

        # Add filter branch if provided
        if config.filter_branch:
            body["filterBranch"] = json.loads(config.filter_branch)

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/crm/v3/lists",
            credentials,
            json_body=body,
            action_name="create_contact_list",
        )

        return response_data

    async def _handle_update_list(
        self, config: HubSpotUpdateListConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing list."""

        # Build request body
        body: Dict[str, Any] = {}

        if config.name:
            body["name"] = config.name
        if config.processing_type:
            body["processingType"] = config.processing_type
        if config.filter_branch:
            body["filterBranch"] = json.loads(config.filter_branch)

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/crm/v3/lists/{config.list_id}",
            credentials,
            json_body=body,
            action_name="update_contact_list",
        )

        return response_data

    async def _handle_delete_list(
        self, config: HubSpotDeleteListConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a list."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/crm/v3/lists/{config.list_id}",
            credentials,
            action_name="delete_contact_list",
        )

        return {
            "status": "success",
            "action": "delete_contact_list",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_batch_add_list_members(
        self, config: HubSpotBatchAddListMembersConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Add members to a list in batch."""

        # Parse record IDs
        record_ids = json.loads(config.record_ids)

        # Build request body
        body = {"recordIds": record_ids}

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/crm/v3/lists/{config.list_id}/memberships/add",
            credentials,
            json_body=body,
            action_name="add_contacts_to_list_batch",
        )

        return response_data

    # ============================================================================
    # Schema API Handlers (Custom Object Schemas)
    # ============================================================================

    async def _handle_list_schemas(
        self, config: HubSpotListSchemasConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all custom object schemas."""

        # Build query parameters
        params: Dict[str, Any] = {}
        if config.include_standard:
            params["includeStandard"] = "true"

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/crm/v3/schemas",
            credentials,
            params=params if params else None,
            action_name="list_custom_object_schemas",
        )

        return response_data

    async def _handle_get_schema(
        self, config: HubSpotGetSchemaConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific custom object schema."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/crm/v3/schemas/{config.object_type}",
            credentials,
            action_name="get_custom_object_schema",
        )

        return response_data

    async def _handle_create_schema(
        self, config: HubSpotCreateSchemaConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new custom object schema."""

        # Build request body
        body: Dict[str, Any] = {
            "name": config.name,
            "labels": json.loads(config.labels),
            "primaryDisplayProperty": config.primary_display_property,
            "properties": json.loads(config.properties),
        }

        # Add associated objects if provided
        if config.associated_objects:
            body["associatedObjects"] = json.loads(config.associated_objects)

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/crm/v3/schemas",
            credentials,
            json_body=body,
            action_name="create_custom_object_schema",
        )

        return response_data

    async def _handle_update_schema(
        self, config: HubSpotUpdateSchemaConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing custom object schema."""

        # Build request body
        body: Dict[str, Any] = {}

        if config.labels:
            body["labels"] = json.loads(config.labels)
        if config.properties:
            body["properties"] = json.loads(config.properties)

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/crm/v3/schemas/{config.object_type}",
            credentials,
            json_body=body,
            action_name="update_custom_object_schema",
        )

        return response_data

    async def _handle_delete_schema(
        self, config: HubSpotDeleteSchemaConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a custom object schema."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/crm/v3/schemas/{config.object_type}",
            credentials,
            action_name="delete_custom_object_schema",
        )

        return {
            "status": "success",
            "action": "delete_custom_object_schema",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_purge_schema(
        self, config: HubSpotPurgeSchemaConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Purge all data for a custom object schema."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/crm/v3/schemas/{config.object_type}/purge",
            credentials,
            json_body={},
            action_name="purge_custom_object_schema",
        )

        return {
            "status": "success",
            "action": "purge_custom_object_schema",
            "data": response_data or {"purged": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    # ============================================================================
    # Marketing Events API Handlers (Webinars, Conferences)
    # ============================================================================

    async def _handle_list_marketing_events(
        self, config: HubSpotListMarketingEventsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all marketing events."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/marketing/v3/marketing-events",
            credentials,
            params={"limit": config.limit} if config.limit else None,
            action_name="list_marketing_events",
        )

        return response_data

    async def _handle_get_marketing_event(
        self, config: HubSpotGetMarketingEventConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific marketing event."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/marketing/v3/marketing-events/events/{config.external_event_id}",
            credentials,
            action_name="get_marketing_event",
        )

        return response_data

    async def _handle_create_marketing_event(
        self, config: HubSpotCreateMarketingEventConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new marketing event."""

        # Build request body
        body: Dict[str, Any] = {
            "eventName": config.event_name,
            "eventType": config.event_type,
            "startDateTime": config.start_date_time,
            "externalEventId": config.external_event_id,
        }

        # Add optional fields
        if config.end_date_time:
            body["endDateTime"] = config.end_date_time
        if config.event_url:
            body["eventUrl"] = config.event_url
        if config.event_description:
            body["eventDescription"] = config.event_description
        if config.custom_properties:
            body["customProperties"] = json.loads(config.custom_properties)

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/marketing/v3/marketing-events/events",
            credentials,
            json_body=body,
            action_name="create_marketing_event",
        )

        return response_data

    async def _handle_update_marketing_event(
        self, config: HubSpotUpdateMarketingEventConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing marketing event."""

        # Build request body
        body: Dict[str, Any] = {}

        if config.event_name:
            body["eventName"] = config.event_name
        if config.start_date_time:
            body["startDateTime"] = config.start_date_time
        if config.end_date_time:
            body["endDateTime"] = config.end_date_time
        if config.event_cancelled is not None:
            body["eventCancelled"] = config.event_cancelled

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/marketing/v3/marketing-events/events/{config.external_event_id}",
            credentials,
            json_body=body,
            action_name="update_marketing_event",
        )

        return response_data

    async def _handle_delete_marketing_event(
        self, config: HubSpotDeleteMarketingEventConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a marketing event."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/marketing/v3/marketing-events/events/{config.external_event_id}",
            credentials,
            action_name="delete_marketing_event",
        )

        return {
            "status": "success",
            "action": "delete_marketing_event",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_create_attendance(
        self, config: HubSpotCreateAttendanceConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create/update attendance records for an event."""

        # Parse inputs
        inputs = json.loads(config.inputs)

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/marketing/v3/marketing-events/events/{config.external_event_id}/attendance",
            credentials,
            json_body={"inputs": inputs},
            action_name="create_event_attendance",
        )

        return response_data

    async def _handle_get_attendance(
        self, config: HubSpotGetAttendanceConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get attendance records for an event."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/marketing/v3/marketing-events/events/{config.external_event_id}/attendance",
            credentials,
            action_name="get_event_attendance",
        )

        return response_data

    async def _handle_delete_attendance(
        self, config: HubSpotDeleteAttendanceConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete attendance record for a participant."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/marketing/v3/marketing-events/events/{config.external_event_id}/attendance/{config.subscriber_email}",
            credentials,
            action_name="delete_event_attendance",
        )

        return {
            "status": "success",
            "action": "delete_event_attendance",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    # ============================================================================
    # Campaigns API Handlers (Multi-channel Campaign Management)
    # ============================================================================

    async def _handle_list_campaigns(
        self, config: HubSpotListCampaignsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all campaigns."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/marketing/v3/campaigns",
            credentials,
            params={"limit": config.limit} if config.limit else None,
            action_name="list_marketing_campaigns",
        )

        return response_data

    async def _handle_get_campaign(
        self, config: HubSpotGetCampaignConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific campaign by ID."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/marketing/v3/campaigns/{config.campaign_id}",
            credentials,
            action_name="get_marketing_campaign",
        )

        return response_data

    async def _handle_create_campaign(
        self, config: HubSpotCreateCampaignConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new campaign."""

        # Build request body
        body = {"name": config.name}

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/marketing/v3/campaigns",
            credentials,
            json_body=body,
            action_name="create_marketing_campaign",
        )

        return response_data

    async def _handle_update_campaign(
        self, config: HubSpotUpdateCampaignConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing campaign."""

        # Build request body
        body: Dict[str, Any] = {}

        if config.name:
            body["name"] = config.name
        if config.hs_utm:
            body["hs_utm"] = json.loads(config.hs_utm)

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/marketing/v3/campaigns/{config.campaign_id}",
            credentials,
            json_body=body,
            action_name="update_marketing_campaign",
        )

        return response_data

    async def _handle_delete_campaign(
        self, config: HubSpotDeleteCampaignConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a campaign."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/marketing/v3/campaigns/{config.campaign_id}",
            credentials,
            action_name="delete_marketing_campaign",
        )

        return {
            "status": "success",
            "action": "delete_marketing_campaign",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_get_campaign_assets(
        self, config: HubSpotGetCampaignAssetsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get assets associated with a campaign."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/marketing/v3/campaigns/{config.campaign_id}/assets/{config.asset_type}",
            credentials,
            action_name="get_campaign_assets",
        )

        return response_data

    async def _handle_manage_campaign_budget(
        self, config: HubSpotManageCampaignBudgetConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Manage campaign budget items."""
        start_time = time.time()

        # Determine HTTP method and endpoint based on budget_operation
        if config.budget_operation == "create":
            method = "POST"
            endpoint = f"/marketing/v3/campaigns/{config.campaign_id}/budget"
            body = json.loads(config.budget_data) if config.budget_data else {}
        elif config.budget_operation == "update":
            method = "PATCH"
            endpoint = f"/marketing/v3/campaigns/{config.campaign_id}/budget"
            body = json.loads(config.budget_data) if config.budget_data else {}
        else:  # delete
            method = "DELETE"
            endpoint = f"/marketing/v3/campaigns/{config.campaign_id}/budget"
            body = None

        # Make API request
        response_data = await self._make_request(
            method,
            endpoint,
            credentials,
            json_body=body if body is not None else None,
            action_name="update_campaign_budget",
        )

        return {
            "status": "success",
            "action": "update_campaign_budget",
            "data": response_data
            or {"operation": config.budget_operation, "success": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    # ============================================================================
    # CMS HubDB API Handlers
    # ============================================================================

    async def _handle_list_hubdb_tables(
        self, config: HubSpotListHubDBTablesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all HubDB tables."""

        # Make API request
        response_data = await self._make_request(
            "GET", "/cms/v3/hubdb/tables", credentials, action_name="list_hubdb_tables"
        )

        return response_data

    async def _handle_get_hubdb_table(
        self, config: HubSpotGetHubDBTableConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific HubDB table."""

        # Determine if draft or published version
        path_suffix = "/draft" if config.draft else ""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/hubdb/tables/{config.table_id}{path_suffix}",
            credentials,
            action_name="get_hubdb_table",
        )

        return response_data

    async def _handle_create_hubdb_table(
        self, config: HubSpotCreateHubDBTableConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new HubDB table."""

        # Build request body
        body = {"name": config.name, "label": config.label}

        if config.columns:
            body["columns"] = json.loads(config.columns)

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/cms/v3/hubdb/tables",
            credentials,
            json_body=body,
            action_name="create_hubdb_table",
        )

        return response_data

    async def _handle_update_hubdb_table(
        self, config: HubSpotUpdateHubDBTableConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update a HubDB table (draft version)."""

        # Build request body
        body: Dict[str, Any] = {}
        if config.label:
            body["label"] = config.label

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/cms/v3/hubdb/tables/{config.table_id}/draft",
            credentials,
            json_body=body,
            action_name="update_hubdb_table",
        )

        return response_data

    async def _handle_publish_hubdb_table(
        self, config: HubSpotPublishHubDBTableConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Publish a HubDB table's draft version."""

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/cms/v3/hubdb/tables/{config.table_id}/draft/publish",
            credentials,
            action_name="publish_hubdb_table",
        )

        return response_data

    async def _handle_delete_hubdb_table(
        self, config: HubSpotDeleteHubDBTableConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a HubDB table."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/cms/v3/hubdb/tables/{config.table_id}",
            credentials,
            action_name="delete_hubdb_table",
        )

        return {
            "status": "success",
            "action": "delete_hubdb_table",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_list_hubdb_rows(
        self, config: HubSpotListHubDBRowsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List rows in a HubDB table."""

        # Determine if draft or published version
        path_suffix = "/draft" if config.draft else ""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/hubdb/tables/{config.table_id}{path_suffix}/rows",
            credentials,
            action_name="list_hubdb_rows",
        )

        return response_data

    async def _handle_get_hubdb_row(
        self, config: HubSpotGetHubDBRowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific row from a HubDB table."""

        # Determine if draft or published version
        path_suffix = "/draft" if config.draft else ""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/hubdb/tables/{config.table_id}{path_suffix}/rows/{config.row_id}",
            credentials,
            action_name="get_hubdb_row",
        )

        return response_data

    async def _handle_create_hubdb_row(
        self, config: HubSpotCreateHubDBRowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new row in a HubDB table."""

        # Build request body
        body = {"values": json.loads(config.values)}

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/cms/v3/hubdb/tables/{config.table_id}/rows",
            credentials,
            json_body=body,
            action_name="create_hubdb_row",
        )

        return response_data

    async def _handle_update_hubdb_row(
        self, config: HubSpotUpdateHubDBRowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update a row in a HubDB table (draft version)."""

        # Build request body
        body = {"values": json.loads(config.values)}

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/cms/v3/hubdb/tables/{config.table_id}/rows/{config.row_id}/draft",
            credentials,
            json_body=body,
            action_name="update_hubdb_row",
        )

        return response_data

    async def _handle_delete_hubdb_row(
        self, config: HubSpotDeleteHubDBRowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a row from a HubDB table."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/cms/v3/hubdb/tables/{config.table_id}/rows/{config.row_id}/draft",
            credentials,
            action_name="delete_hubdb_row",
        )

        return {
            "status": "success",
            "action": "delete_hubdb_row",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_clone_hubdb_table(
        self, config: HubSpotCloneHubDBTableConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Clone a HubDB table."""

        # Build request body
        body = {"newName": config.new_name}

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/cms/v3/hubdb/tables/{config.table_id}/draft/clone",
            credentials,
            json_body=body,
            action_name="clone_hubdb_table",
        )

        return response_data

    # ============================================================================
    # Communication Preferences API Handlers
    # ============================================================================

    async def _handle_get_subscription_status(
        self, config: HubSpotGetSubscriptionStatusConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get subscription status for an email address."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/communication-preferences/v3/status/email/{config.email}",
            credentials,
            action_name="get_contact_subscription_status",
        )

        return response_data

    async def _handle_subscribe_contact(
        self, config: HubSpotSubscribeContactConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Subscribe a contact to a subscription type."""

        # Build request body
        body = {"emailAddress": config.email, "subscriptionId": config.subscription_id}

        if config.legal_basis:
            body["legalBasis"] = config.legal_basis
        if config.legal_basis_explanation:
            body["legalBasisExplanation"] = config.legal_basis_explanation

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/communication-preferences/v3/subscribe",
            credentials,
            json_body=body,
            action_name="subscribe_contact_to_list",
        )

        return response_data

    async def _handle_unsubscribe_contact(
        self, config: HubSpotUnsubscribeContactConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Unsubscribe a contact from a subscription type."""

        # Build request body
        body = {"emailAddress": config.email, "subscriptionId": config.subscription_id}

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/communication-preferences/v3/unsubscribe",
            credentials,
            json_body=body,
            action_name="unsubscribe_contact_from_list",
        )

        return response_data

    async def _handle_list_subscription_types(
        self, config: HubSpotListSubscriptionTypesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all subscription types."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/communication-preferences/v3/definitions",
            credentials,
            action_name="list_subscription_types",
        )

        return response_data

    # ============================================================================
    # CMS Pages API Handlers
    # ============================================================================

    async def _handle_list_pages(
        self, config: HubSpotListPagesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all site pages."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            "/cms/v3/pages/site-pages",
            credentials,
            action_name="list_website_pages",
        )

        return response_data

    async def _handle_get_page(
        self, config: HubSpotGetPageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific page."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/pages/site-pages/{config.page_id}",
            credentials,
            action_name="get_website_page",
        )

        return response_data

    async def _handle_create_page(
        self, config: HubSpotCreatePageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new page."""

        # Build request body
        body = {k: v for k, v in {"name": config.name, "htmlTitle": config.html_title}.items() if v}

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/cms/v3/pages/site-pages",
            credentials,
            json_body=body,
            action_name="create_website_page",
        )

        return response_data

    async def _handle_update_page(
        self, config: HubSpotUpdatePageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing page."""

        # Build request body
        body = {k: v for k, v in {"name": config.name}.items() if v}

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/cms/v3/pages/site-pages/{config.page_id}",
            credentials,
            json_body=body,
            action_name="update_website_page",
        )

        return response_data

    async def _handle_delete_page(
        self, config: HubSpotDeletePageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a page."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/cms/v3/pages/site-pages/{config.page_id}",
            credentials,
            action_name="delete_website_page",
        )

        return {
            "status": "success",
            "action": "delete_website_page",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_publish_page(
        self, config: HubSpotPublishPageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Publish or schedule a page."""

        # Build request body
        body: Dict[str, Any] = {"action": config.operation}

        # Make API request
        response_data = await self._make_request(
            "POST",
            f"/cms/v3/pages/site-pages/{config.page_id}/schedule",
            credentials,
            json_body=body,
            action_name="publish_website_page",
        )

        return response_data

    # ============================================================================
    # CMS Blogs API Handlers
    # ============================================================================

    async def _handle_list_blog_posts(
        self, config: HubSpotListBlogPostsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all blog posts."""

        # Make API request
        response_data = await self._make_request(
            "GET", "/cms/v3/blogs/posts", credentials, action_name="list_blog_posts"
        )

        return response_data

    async def _handle_get_blog_post(
        self, config: HubSpotGetBlogPostConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific blog post."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/blogs/posts/{config.post_id}",
            credentials,
            action_name="get_blog_post",
        )

        return response_data

    async def _handle_create_blog_post(
        self, config: HubSpotCreateBlogPostConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new blog post."""

        # Build request body
        body = {k: v for k, v in {"name": config.name, "postBody": config.post_body}.items() if v}

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/cms/v3/blogs/posts",
            credentials,
            json_body=body,
            action_name="create_blog_post",
        )

        return response_data

    async def _handle_update_blog_post(
        self, config: HubSpotUpdateBlogPostConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update an existing blog post."""

        # Build request body
        body = {k: v for k, v in {"name": config.name}.items() if v}

        # Make API request
        response_data = await self._make_request(
            "PATCH",
            f"/cms/v3/blogs/posts/{config.post_id}",
            credentials,
            json_body=body,
            action_name="update_blog_post",
        )

        return response_data

    async def _handle_delete_blog_post(
        self, config: HubSpotDeleteBlogPostConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a blog post."""
        start_time = time.time()

        # Make API request
        response_data = await self._make_request(
            "DELETE",
            f"/cms/v3/blogs/posts/{config.post_id}",
            credentials,
            action_name="delete_blog_post",
        )

        return {
            "status": "success",
            "action": "delete_blog_post",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_list_blog_authors(
        self, config: HubSpotListBlogAuthorsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all blog authors."""

        # Make API request
        response_data = await self._make_request(
            "GET", "/cms/v3/blogs/authors", credentials, action_name="list_blog_authors"
        )

        return response_data

    async def _handle_get_blog_author(
        self, config: HubSpotGetBlogAuthorConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific blog author."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/blogs/authors/{config.author_id}",
            credentials,
            action_name="get_blog_author",
        )

        return response_data

    async def _handle_create_blog_author(
        self, config: HubSpotCreateBlogAuthorConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a new blog author."""

        # Build request body
        body = {"fullName": config.full_name, "email": config.email}

        # Make API request
        response_data = await self._make_request(
            "POST",
            "/cms/v3/blogs/authors",
            credentials,
            json_body=body,
            action_name="create_blog_author",
        )

        return response_data

    async def _handle_list_blog_topics(
        self, config: HubSpotListBlogTopicsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all blog topics (tags)."""

        # Make API request
        response_data = await self._make_request(
            "GET", "/cms/v3/blogs/tags", credentials, action_name="list_blog_topics"
        )

        return response_data

    async def _handle_get_blog_topic(
        self, config: HubSpotGetBlogTopicConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific blog topic."""

        # Make API request
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/blogs/tags/{config.topic_id}",
            credentials,
            action_name="get_blog_topic",
        )

        return response_data

    # ============================================================================
    # CMS Files API Handlers
    # ============================================================================

    async def _handle_list_files(
        self, config: HubSpotListFilesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all files."""
        response_data = await self._make_request(
            "GET", "/files/v3/files/search", credentials, action_name="list_files"
        )
        return response_data

    async def _handle_get_file(
        self, config: HubSpotGetFileConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific file."""
        response_data = await self._make_request(
            "GET",
            f"/files/v3/files/{config.file_id}",
            credentials,
            action_name="get_file",
        )
        return response_data

    async def _handle_upload_file(
        self, config: HubSpotUploadFileConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Upload a file by importing it from a URL. The direct upload endpoint
        is multipart-only; the URL-import endpoint takes JSON. `file_data` must
        contain at least `access` and `url` (+ optional folderPath/name)."""
        body = json.loads(config.file_data)
        response_data = await self._make_request(
            "POST",
            "/files/v3/files/import-from-url/async",
            credentials,
            json_body=body,
            action_name="upload_file",
        )
        return response_data

    async def _handle_update_file(
        self, config: HubSpotUpdateFileConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update file properties."""
        body = json.loads(config.file_data)
        response_data = await self._make_request(
            "PATCH",
            f"/files/v3/files/{config.file_id}",
            credentials,
            json_body=body,
            action_name="update_file",
        )
        return response_data

    async def _handle_delete_file(
        self, config: HubSpotDeleteFileConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a file."""
        start_time = time.time()
        response_data = await self._make_request(
            "DELETE",
            f"/files/v3/files/{config.file_id}",
            credentials,
            action_name="delete_file",
        )
        return {
            "status": "success",
            "action": "delete_file",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    # ============================================================================
    # CMS Domains API Handlers
    # ============================================================================

    async def _handle_list_domains(
        self, config: HubSpotListDomainsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all domains."""
        response_data = await self._make_request(
            "GET", "/cms/v3/domains", credentials, action_name="list_domains"
        )
        return response_data

    async def _handle_get_domain(
        self, config: HubSpotGetDomainConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific domain."""
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/domains/{config.domain_id}",
            credentials,
            action_name="get_domain",
        )
        return response_data

    # ============================================================================
    # CMS URL Mappings API Handlers
    # ============================================================================

    async def _handle_list_url_mappings(
        self, config: HubSpotListUrlMappingsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List all URL mappings."""
        response_data = await self._make_request(
            "GET",
            "/cms/v3/url-redirects",
            credentials,
            action_name="list_url_redirects",
        )
        return response_data

    async def _handle_get_url_mapping(
        self, config: HubSpotGetUrlMappingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a specific URL mapping."""
        response_data = await self._make_request(
            "GET",
            f"/cms/v3/url-redirects/{config.mapping_id}",
            credentials,
            action_name="get_url_redirect",
        )
        return response_data

    async def _handle_create_url_mapping(
        self, config: HubSpotCreateUrlMappingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a URL redirect."""
        body = {
            "routePrefix": config.route_prefix,
            "destination": config.destination,
            "redirectStyle": config.redirect_style,
        }
        response_data = await self._make_request(
            "POST",
            "/cms/v3/url-redirects",
            credentials,
            json_body=body,
            action_name="create_url_redirect",
        )
        return response_data

    async def _handle_update_url_mapping(
        self, config: HubSpotUpdateUrlMappingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update a URL mapping."""
        body = json.loads(config.mapping_data)
        response_data = await self._make_request(
            "PATCH",
            f"/cms/v3/url-redirects/{config.mapping_id}",
            credentials,
            json_body=body,
            action_name="update_url_redirect",
        )
        return response_data

    async def _handle_delete_url_mapping(
        self, config: HubSpotDeleteUrlMappingConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a URL mapping."""
        start_time = time.time()
        response_data = await self._make_request(
            "DELETE",
            f"/cms/v3/url-redirects/{config.mapping_id}",
            credentials,
            action_name="delete_url_redirect",
        )
        return {
            "status": "success",
            "action": "delete_url_redirect",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    # ============================================================================
    # CMS Site Search API Handlers
    # ============================================================================

    async def _handle_search_content(
        self, config: HubSpotSearchContentConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Search published site content via the portalId-keyed v2 endpoint
        (works on any tier; the v3 endpoint needs a scope this account can't get).
        Param is `term`, not `q`."""
        portal_id = await self._resolve_portal_id(credentials)
        params: Dict[str, Any] = {"term": config.query, "limit": config.limit}
        if portal_id:
            params["portalId"] = portal_id
        response_data = await self._make_request(
            "GET",
            "/contentsearch/v2/search",
            credentials,
            params=params,
            action_name="search_website_content",
        )
        return response_data

    # ============================================================================
    # Conversations API Handlers
    # ============================================================================

    async def _handle_list_conversation_threads(
        self,
        config: HubSpotListConversationThreadsConfig,
        credentials: HubSpotCredential,
    ) -> Dict[str, Any]:
        """List conversation threads."""
        response_data = await self._make_request(
            "GET",
            "/conversations/v3/conversations/threads",
            credentials,
            action_name="list_conversation_threads",
        )
        return response_data

    async def _handle_get_conversation_thread(
        self, config: HubSpotGetConversationThreadConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a conversation thread."""
        response_data = await self._make_request(
            "GET",
            f"/conversations/v3/conversations/threads/{config.thread_id}",
            credentials,
            action_name="get_conversation_thread",
        )
        return response_data

    async def _handle_list_messages(
        self, config: HubSpotListMessagesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List messages in a thread."""
        response_data = await self._make_request(
            "GET",
            f"/conversations/v3/conversations/threads/{config.thread_id}/messages",
            credentials,
            action_name="list_conversation_messages",
        )
        return response_data

    async def _handle_send_message(
        self, config: HubSpotSendMessageConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Send a message."""
        body: Dict[str, Any] = {"text": config.message}
        if config.sender_id:
            body["senderId"] = config.sender_id
        response_data = await self._make_request(
            "POST",
            f"/conversations/v3/conversations/threads/{config.thread_id}/messages",
            credentials,
            json_body=body,
            action_name="send_conversation_message",
        )
        return response_data

    async def _handle_list_channels(
        self, config: HubSpotListChannelsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List conversation channels."""
        response_data = await self._make_request(
            "GET",
            "/conversations/v3/conversations/channels",
            credentials,
            action_name="list_communication_channels",
        )
        return response_data

    async def _handle_get_channel(
        self, config: HubSpotGetChannelConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a conversation channel."""
        response_data = await self._make_request(
            "GET",
            f"/conversations/v3/conversations/channels/{config.channel_id}",
            credentials,
            action_name="get_communication_channel",
        )
        return response_data

    async def _handle_identify_visitor(
        self, config: HubSpotIdentifyVisitorConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Identify a visitor."""
        body = {"email": config.email, "token": config.token}
        response_data = await self._make_request(
            "POST",
            "/conversations/v3/visitor-identification/tokens/create",
            credentials,
            json_body=body,
            action_name="identify_website_visitor",
        )
        return response_data

    async def _handle_get_visitor(
        self, config: HubSpotGetVisitorConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get visitor information."""
        response_data = await self._make_request(
            "GET",
            f"/conversations/v3/visitor-identification/tokens/{config.visitor_id}",
            credentials,
            action_name="get_visitor",
        )
        return response_data

    async def _handle_update_conversation_status(
        self,
        config: HubSpotUpdateConversationStatusConfig,
        credentials: HubSpotCredential,
    ) -> Dict[str, Any]:
        """Update conversation status."""
        body = {"status": config.status}
        response_data = await self._make_request(
            "PATCH",
            f"/conversations/v3/conversations/threads/{config.thread_id}",
            credentials,
            json_body=body,
            action_name="update_conversation_status",
        )
        return response_data

    # ============================================================================
    # Automation & Workflows API Handlers
    # ============================================================================

    async def _handle_list_workflows(
        self, config: HubSpotListWorkflowsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List workflows. v4 flows API — the v3 list endpoint requires an
        internal scope public OAuth apps can't get; v4 uses `automation`."""
        response_data = await self._make_request(
            "GET", "/automation/v4/flows", credentials, action_name="list_workflows"
        )
        return response_data

    async def _handle_get_workflow(
        self, config: HubSpotGetWorkflowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a workflow (v4 flows API — v3 get needs a non-requestable scope)."""
        response_data = await self._make_request(
            "GET",
            f"/automation/v4/flows/{config.workflow_id}",
            credentials,
            action_name="get_workflow",
        )
        return response_data

    async def _handle_enroll_in_workflow(
        self, config: HubSpotEnrollInWorkflowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Enroll contact in workflow."""
        body = {"email": config.contact_email}
        response_data = await self._make_request(
            "POST",
            f"/automation/v3/workflows/{config.workflow_id}/enrollments",
            credentials,
            json_body=body,
            action_name="enroll_contact_in_workflow",
        )
        return response_data

    async def _handle_unenroll_from_workflow(
        self, config: HubSpotUnenrollFromWorkflowConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Unenroll contact from workflow."""
        body = {"email": config.contact_email}
        response_data = await self._make_request(
            "POST",
            f"/automation/v3/workflows/{config.workflow_id}/unenrollments",
            credentials,
            json_body=body,
            action_name="unenroll_contact_from_workflow",
        )
        return response_data

    async def _resolve_current_user_id(
        self, credentials: HubSpotCredential
    ) -> Optional[str]:
        """Resolve the connected HubSpot user id from the access token — needed
        by APIs (sequences v4, business units) that key on the acting user."""
        info = await self._make_request(
            "GET",
            f"/oauth/v1/access-tokens/{credentials.access_token}",
            credentials,
            action_name="resolve_user_id",
        )
        if isinstance(info, dict) and info.get("status") == "success":
            uid = (info.get("data") or {}).get("user_id")
            return str(uid) if uid is not None else None
        return None

    async def _resolve_portal_id(
        self, credentials: HubSpotCredential
    ) -> Optional[str]:
        """Resolve the connected account's portalId (hub_id) from the token —
        needed by the unauthenticated site-search endpoint."""
        info = await self._make_request(
            "GET",
            f"/oauth/v1/access-tokens/{credentials.access_token}",
            credentials,
            action_name="resolve_portal_id",
        )
        if isinstance(info, dict) and info.get("status") == "success":
            hub = (info.get("data") or {}).get("hub_id")
            return str(hub) if hub is not None else None
        return None

    async def _translate_scope_error(
        self, credentials: HubSpotCredential, error_data: Dict[str, Any]
    ) -> Optional[str]:
        """Turn HubSpot's generic "missing required scopes" 403 into an accurate
        message. HubSpot returns that error even when the scope IS granted but the
        account's plan doesn't include the feature. We ONLY call it a plan issue
        after VERIFYING (against the token's live granted scopes) that the required
        scope is actually present — otherwise we report a genuine missing scope.
        Returns None if the required scope can't be determined (leave original)."""
        import re
        required: List[str] = []
        for e in (error_data.get("errors") or []):
            ctx = e.get("context") or {}
            required += ctx.get("requiredGranularScopes") or []
            required += ctx.get("requiredScopes") or []
        if not required:
            msg = error_data.get("message", "")
            for grp in re.findall(r"requires (?:any|all) of \[([^\]]+)\]", msg):
                required += [s.strip() for s in grp.split(",")]
            required += re.findall(r"missing required '([^']+)' scope", msg)
        required = sorted({s for s in required if s})
        if not required:
            return None  # unrecognized 403 shape — keep HubSpot's original message

        # Verify against the token's ACTUAL granted scopes before claiming anything.
        granted: set = set()
        try:
            info = await self._make_request(
                "GET",
                f"/oauth/v1/access-tokens/{credentials.access_token}",
                credentials,
                action_name="scope_check",
            )
            if isinstance(info, dict) and info.get("status") == "success":
                granted = set((info.get("data") or {}).get("scopes") or [])
        except Exception:
            return None  # can't verify → don't assert a cause, keep original

        have = [s for s in required if s in granted]
        joined = ", ".join(required)
        if have:
            # Scope IS granted → the API refused for a non-scope reason: the
            # account's HubSpot plan/edition doesn't include this feature.
            return (
                f"Your HubSpot account is connected with the required permission "
                f"({', '.join(have)}), so this is NOT a missing-permission problem — "
                f"HubSpot refused the call because your plan/edition doesn't include "
                f"this feature. Check that your HubSpot subscription covers it "
                f"(these APIs usually require a Professional or Enterprise Hub)."
            )
        return (
            f"This operation needs the HubSpot permission(s) [{joined}], which your "
            f"connection doesn't have. Reconnect your HubSpot account and approve them "
            f"— note your HubSpot plan must also include the feature for it to work."
        )

    async def _handle_list_sequences(
        self, config: HubSpotListSequencesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List sequences (v4 public API — requires the acting userId)."""
        user_id = await self._resolve_current_user_id(credentials)
        if not user_id:
            return {
                "status": "error",
                "action": "list_sequences",
                "error": "Could not resolve the HubSpot user id required to list sequences.",
                "status_code": 400,
            }
        response_data = await self._make_request(
            "GET",
            "/automation/v4/sequences",
            credentials,
            params={"userId": user_id},
            action_name="list_sequences",
        )
        return response_data

    async def _handle_get_sequence(
        self, config: HubSpotGetSequenceConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a sequence."""
        response_data = await self._make_request(
            "GET",
            f"/automation/v4/sequences/{config.sequence_id}",
            credentials,
            action_name="get_sequence",
        )
        return response_data

    async def _handle_enroll_in_sequence(
        self, config: HubSpotEnrollInSequenceConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Enroll contact in sequence."""
        body = {"email": config.contact_email}
        response_data = await self._make_request(
            "POST",
            f"/automation/v3/sequences/{config.sequence_id}/enrollments",
            credentials,
            json_body=body,
            action_name="enroll_contact_in_sequence",
        )
        return response_data

    async def _handle_unenroll_from_sequence(
        self, config: HubSpotUnenrollFromSequenceConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Unenroll contact from sequence."""
        body = {"email": config.contact_email}
        response_data = await self._make_request(
            "POST",
            f"/automation/v3/sequences/{config.sequence_id}/unenrollments",
            credentials,
            json_body=body,
            action_name="unenroll_contact_from_sequence",
        )
        return response_data

    # ============================================================================
    # Settings & Account API Handlers
    # ============================================================================

    async def _handle_list_users(
        self, config: HubSpotListUsersConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List users."""
        response_data = await self._make_request(
            "GET", "/settings/v3/users", credentials, action_name="list_users"
        )
        return response_data

    async def _handle_get_user(
        self, config: HubSpotGetUserConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a user."""
        response_data = await self._make_request(
            "GET",
            f"/settings/v3/users/{config.user_id}",
            credentials,
            action_name="get_user",
        )
        return response_data

    async def _handle_create_user(
        self, config: HubSpotCreateUserConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a user."""
        body = json.loads(config.user_data)
        response_data = await self._make_request(
            "POST",
            "/settings/v3/users",
            credentials,
            json_body=body,
            action_name="create_user",
        )
        return response_data

    async def _handle_update_user(
        self, config: HubSpotUpdateUserConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Update a user."""
        body = json.loads(config.user_data)
        response_data = await self._make_request(
            "PATCH",
            f"/settings/v3/users/{config.user_id}",
            credentials,
            json_body=body,
            action_name="update_user",
        )
        return response_data

    async def _handle_delete_user(
        self, config: HubSpotDeleteUserConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Delete a user."""
        start_time = time.time()
        response_data = await self._make_request(
            "DELETE",
            f"/settings/v3/users/{config.user_id}",
            credentials,
            action_name="delete_user",
        )
        return {
            "status": "success",
            "action": "delete_user",
            "data": response_data or {"deleted": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_list_business_units(
        self, config: HubSpotListBusinessUnitsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List business units (keyed on the acting user)."""
        user_id = await self._resolve_current_user_id(credentials)
        if not user_id:
            return {
                "status": "error",
                "action": "list_business_units",
                "error": "Could not resolve the HubSpot user id required to list business units.",
                "status_code": 400,
            }
        response_data = await self._make_request(
            "GET",
            f"/business-units/v3/business-units/user/{user_id}",
            credentials,
            action_name="list_business_units",
        )
        return response_data

    async def _handle_get_business_unit(
        self, config: HubSpotGetBusinessUnitConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a business unit."""
        response_data = await self._make_request(
            "GET",
            f"/settings/v3/business-units/{config.business_unit_id}",
            credentials,
            action_name="get_business_unit",
        )
        return response_data

    async def _handle_get_account_info(
        self, config: HubSpotGetAccountInfoConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get account info."""
        response_data = await self._make_request(
            "GET", "/integrations/v1/me", credentials, action_name="get_account_info"
        )
        return response_data

    async def _handle_list_audit_logs(
        self, config: HubSpotListAuditLogsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List audit logs."""
        params = {}
        if config.after:
            params["after"] = config.after
        response_data = await self._make_request(
            "GET",
            "/account-info/v3/activity/audit-logs",
            credentials,
            params=params,
            action_name="list_audit_logs",
        )
        return response_data

    async def _handle_list_goals(
        self, config: HubSpotListGoalsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List goals."""
        response_data = await self._make_request(
            "GET", "/crm/v3/objects/goal_targets", credentials, action_name="list_goals"
        )
        return response_data

    async def _handle_get_goal(
        self, config: HubSpotGetGoalConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a goal."""
        response_data = await self._make_request(
            "GET",
            f"/goals/v1/goals/{config.goal_id}",
            credentials,
            action_name="get_goal",
        )
        return response_data

    async def _handle_list_teams(
        self, config: HubSpotListTeamsConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List teams."""
        response_data = await self._make_request(
            "GET", "/settings/v3/users/teams", credentials, action_name="list_teams"
        )
        return response_data

    async def _handle_get_team(
        self, config: HubSpotGetTeamConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a team."""
        response_data = await self._make_request(
            "GET",
            f"/settings/v3/users/teams/{config.team_id}",
            credentials,
            action_name="get_team",
        )
        return response_data

    async def _handle_list_roles(
        self, config: HubSpotListRolesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List roles."""
        response_data = await self._make_request(
            "GET", "/settings/v3/users/roles", credentials, action_name="list_roles"
        )
        return response_data

    async def _handle_get_role(
        self, config: HubSpotGetRoleConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get a role."""
        response_data = await self._make_request(
            "GET",
            f"/settings/v3/users/roles/{config.role_id}",
            credentials,
            action_name="get_role",
        )
        return response_data

    # ============================================================================
    # Data Management API Handlers
    # ============================================================================

    async def _handle_create_export(
        self, config: HubSpotCreateExportConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a data export."""
        body: Dict[str, Any] = {"exportType": config.export_type}
        if config.properties:
            body["properties"] = json.loads(config.properties)
        response_data = await self._make_request(
            "POST",
            "/crm/v3/exports/export/async",
            credentials,
            json_body=body,
            action_name="create_data_export",
        )
        return response_data

    async def _handle_get_export_status(
        self, config: HubSpotGetExportStatusConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get export status."""
        response_data = await self._make_request(
            "GET",
            f"/crm/v3/exports/export/async/tasks/{config.export_id}/status",
            credentials,
            action_name="get_export_status",
        )
        return response_data

    async def _handle_download_export(
        self, config: HubSpotDownloadExportConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Download export."""
        response_data = await self._make_request(
            "GET",
            f"/crm/v3/exports/export/async/tasks/{config.export_id}",
            credentials,
            action_name="download_data_export",
        )
        return response_data

    async def _handle_create_import(
        self, config: HubSpotCreateImportConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Create a data import. The Imports API is multipart/form-data only:
        an `importRequest` JSON part + a `files` CSV part. We fetch the CSV bytes
        from the provided URL and upload them."""
        async with guarded_async_client(timeout=30.0) as _c:
            _f = await _c.get(config.file_url)
        if _f.status_code >= 400:
            return {
                "status": "error", "action": "create_data_import",
                "error": f"Could not fetch file_url ({_f.status_code}).",
                "status_code": _f.status_code,
            }
        filename = config.file_url.rsplit("/", 1)[-1] or "import.csv"
        multipart = {
            "importRequest": (None, config.import_data, "application/json"),
            "files": (filename, _f.content, "text/csv"),
        }
        response_data = await self._make_request(
            "POST",
            "/crm/v3/imports",
            credentials,
            files=multipart,
            action_name="create_data_import",
        )
        return response_data

    async def _handle_get_import_status(
        self, config: HubSpotGetImportStatusConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get import status."""
        response_data = await self._make_request(
            "GET",
            f"/crm/v3/imports/{config.import_id}",
            credentials,
            action_name="get_import_status",
        )
        return response_data

    # ============================================================================
    # OAuth API Handlers
    # ============================================================================

    async def _handle_get_access_token_info(
        self, config: HubSpotGetAccessTokenInfoConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get access token info. The token being introspected goes in the
        PATH (possession of the token is the auth for this endpoint)."""
        response_data = await self._make_request(
            "GET",
            f"/oauth/v1/access-tokens/{credentials.access_token}",
            credentials,
            action_name="get_access_token_info",
        )
        return response_data

    async def _handle_revoke_access_token(
        self, config: HubSpotRevokeAccessTokenConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Revoke access token."""
        start_time = time.time()
        body = {"token": config.token}
        response_data = await self._make_request(
            "POST",
            "/oauth/v1/refresh-tokens",
            credentials,
            json_body=body,
            action_name="revoke_access_token",
        )
        return {
            "status": "success",
            "action": "revoke_access_token",
            "data": response_data or {"revoked": True},
            "timing_ms": {"operation": round((time.time() - start_time) * 1000, 2)},
        }

    async def _handle_list_scopes(
        self, config: HubSpotListScopesConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """List OAuth scopes."""
        response_data = await self._make_request(
            "GET",
            f"/oauth/v1/access-tokens/{credentials.access_token}",
            credentials,
            action_name="list_api_scopes",
        )
        return response_data

    async def _handle_validate_token(
        self, config: HubSpotValidateTokenConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Validate access token."""
        response_data = await self._make_request(
            "GET",
            f"/oauth/v1/access-tokens/{credentials.access_token}",
            credentials,
            action_name="validate_access_token",
        )
        return response_data

    # ============================================================================
    # Feedback Submissions API Handlers
    # ============================================================================

    async def _handle_list_feedback_submissions(
        self,
        config: HubSpotListFeedbackSubmissionsConfig,
        credentials: HubSpotCredential,
    ) -> Dict[str, Any]:
        """List feedback submissions."""
        response_data = await self._make_request(
            "GET",
            "/crm/v3/objects/feedback_submissions",
            credentials,
            action_name="list_feedback_submissions",
        )
        return response_data

    async def _handle_get_feedback_submission(
        self, config: HubSpotGetFeedbackSubmissionConfig, credentials: HubSpotCredential
    ) -> Dict[str, Any]:
        """Get feedback submission."""
        response_data = await self._make_request(
            "GET",
            f"/crm/v3/objects/feedback_submissions/{config.submission_id}",
            credentials,
            action_name="get_feedback_submission",
        )
        return response_data
