"""
Affinity CRM automation node.

Provides workflow integration with Affinity CRM for operations across:
- System: Authentication verification, rate limit checking
- Persons: CRUD operations on person records
- Organizations: CRUD operations on organization records
- Opportunities: CRUD operations on opportunity records
- Lists: Managing list collections
- List Entries: Managing entries within lists
- Fields: Custom field management
- Field Values: Managing field data for entities
- Notes: Attach notes to entities
- Reminders: Task/follow-up scheduling
- Relationship Strengths: AI-computed connection strength metrics
- Webhooks: Event subscription management
- Files: File upload/download
- v2 Companies: Enhanced company data (Affinity API v2)
- v2 List Entry Fields: Batch field management (Affinity API v2)

Authentication: API Key only (no OAuth available)
  - v1 API: HTTP Basic Auth (empty username, API key as password)
  - v2 API: Bearer token with same API key

API Base URL: https://api.affinity.co
Rate Limit: 900 requests/user/minute
Documentation: https://api-docs.affinity.co/ (v1), https://developer.affinity.co/ (v2)
"""

import base64
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode

logger = logging.getLogger(__name__)

AFFINITY_API_BASE = "https://api.affinity.co"


# ============================================================================
# Credential Schema
# ============================================================================


class AffinityAPIKeyCredential(BaseModel):
    """
    API Key credential for Affinity CRM.

    Generate your API key from Settings → API in your Affinity account.
    API access requires Premium, Scale, Advanced, or Enterprise tier.
    """

    credential_type: Literal["affinity_api_key"] = Field(
        "affinity_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Affinity API key from Settings → API",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://support.affinity.co/s/article/Getting-started-with-the-Affinity-API-FAQs",
        "x-credential-instructions": (
            "Generate your API key from Settings → API in your Affinity account. "
            "API access requires Premium, Scale, Advanced, or Enterprise tier."
        ),
    })


# ============================================================================
# System Operation Configs
# ============================================================================


class AffinityGetWhoamiConfig(BaseModel):
    model_config = ConfigDict(title="Get Current User")

    operation: Literal["get_authenticated_user_info"] = Field(
        "get_authenticated_user_info",
        json_schema_extra={
            "const": "get_authenticated_user_info",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User Info",
        },
        title="Get Authenticated User Info",
    )


class AffinityGetRateLimitConfig(BaseModel):
    model_config = ConfigDict(title="Get Rate Limit")

    operation: Literal["get_rate_limit_info"] = Field(
        "get_rate_limit_info",
        json_schema_extra={
            "const": "get_rate_limit_info",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Rate Limit Info",
        },
        title="Get Rate Limit Info",
    )


# ============================================================================
# Persons Operation Configs
# ============================================================================


class AffinityListPersonsConfig(BaseModel):
    model_config = ConfigDict(title="List Persons")

    operation: Literal["list_persons"] = Field(
        "list_persons",
        json_schema_extra={
            "const": "list_persons",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "List Persons",
        },
        title="List Persons",
    )
    term: Optional[str] = Field(
        None, title="Search Term", description="Filter persons by name or email"
    )
    with_interaction_dates: Optional[str] = Field(
        None,
        title="With Interaction Dates",
        description="Include interaction dates in response",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    page_size: Optional[int] = Field(
        None, title="Page Size", description="Results per page (max 500)", ge=1, le=500
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Pagination token from previous response"
    )


class AffinityGetPersonConfig(BaseModel):
    model_config = ConfigDict(title="Get Person")

    operation: Literal["get_person_by_id"] = Field(
        "get_person_by_id",
        json_schema_extra={
            "const": "get_person_by_id",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Get Person by Id",
        },
        title="Get Person by Id",
    )
    person_id: int = Field(..., title="Person ID")
    with_interaction_dates: Optional[str] = Field(
        None,
        title="With Interaction Dates",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AffinityCreatePersonConfig(BaseModel):
    model_config = ConfigDict(title="Create Person")

    operation: Literal["create_person"] = Field(
        "create_person",
        json_schema_extra={
            "const": "create_person",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Create Person",
        },
        title="Create Person",
    )
    first_name: str = Field(..., title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    emails: Optional[str] = Field(
        None,
        title="Emails",
        description="Comma-separated email addresses",
    )
    organization_ids: Optional[str] = Field(
        None,
        title="Organization IDs",
        description="Comma-separated organization IDs to associate",
    )


class AffinityUpdatePersonConfig(BaseModel):
    model_config = ConfigDict(title="Update Person")

    operation: Literal["update_person"] = Field(
        "update_person",
        json_schema_extra={
            "const": "update_person",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Update Person",
        },
        title="Update Person",
    )
    person_id: int = Field(..., title="Person ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    emails: Optional[str] = Field(
        None,
        title="Emails",
        description="Comma-separated email addresses (replaces existing)",
    )


class AffinityDeletePersonConfig(BaseModel):
    model_config = ConfigDict(title="Delete Person")

    operation: Literal["delete_person"] = Field(
        "delete_person",
        json_schema_extra={
            "const": "delete_person",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Delete Person",
        },
        title="Delete Person",
    )
    person_id: int = Field(..., title="Person ID")


class AffinityGetPersonFieldsConfig(BaseModel):
    model_config = ConfigDict(title="Get Person Fields")

    operation: Literal["get_person_fields"] = Field(
        "get_person_fields",
        json_schema_extra={
            "const": "get_person_fields",
            "ui:hidden": True,
            "x-category": "Person",
            "x-is-trigger": False,
            "x-display-name": "Get Person Fields",
        },
        title="Get Person Fields",
    )


# ============================================================================
# Organizations Operation Configs
# ============================================================================


class AffinityListOrganizationsConfig(BaseModel):
    model_config = ConfigDict(title="List Organizations")

    operation: Literal["list_organizations"] = Field(
        "list_organizations",
        json_schema_extra={
            "const": "list_organizations",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Organizations",
        },
        title="List Organizations",
    )
    term: Optional[str] = Field(None, title="Search Term", description="Filter by name")
    with_interaction_dates: Optional[str] = Field(
        None,
        title="With Interaction Dates",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    page_size: Optional[int] = Field(None, title="Page Size", ge=1, le=500)
    page_token: Optional[str] = Field(None, title="Page Token")


class AffinityGetOrganizationConfig(BaseModel):
    model_config = ConfigDict(title="Get Organization")

    operation: Literal["get_organization_by_id"] = Field(
        "get_organization_by_id",
        json_schema_extra={
            "const": "get_organization_by_id",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Organization by Id",
        },
        title="Get Organization by Id",
    )
    organization_id: int = Field(..., title="Organization ID")
    with_interaction_dates: Optional[str] = Field(
        None,
        title="With Interaction Dates",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AffinityCreateOrganizationConfig(BaseModel):
    model_config = ConfigDict(title="Create Organization")

    operation: Literal["create_organization"] = Field(
        "create_organization",
        json_schema_extra={
            "const": "create_organization",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Create Organization",
        },
        title="Create Organization",
    )
    name: str = Field(..., title="Name", description="Organization name")
    domain: Optional[str] = Field(
        None, title="Domain", description="Website domain (e.g., affinity.co)"
    )
    person_ids: Optional[str] = Field(
        None,
        title="Person IDs",
        description="Comma-separated person IDs to associate",
    )


class AffinityUpdateOrganizationConfig(BaseModel):
    model_config = ConfigDict(title="Update Organization")

    operation: Literal["update_organization"] = Field(
        "update_organization",
        json_schema_extra={
            "const": "update_organization",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Update Organization",
        },
        title="Update Organization",
    )
    organization_id: int = Field(..., title="Organization ID")
    name: Optional[str] = Field(None, title="Name")
    domain: Optional[str] = Field(None, title="Domain")


class AffinityDeleteOrganizationConfig(BaseModel):
    model_config = ConfigDict(title="Delete Organization")

    operation: Literal["delete_organization"] = Field(
        "delete_organization",
        json_schema_extra={
            "const": "delete_organization",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Delete Organization",
        },
        title="Delete Organization",
    )
    organization_id: int = Field(..., title="Organization ID")


class AffinityGetOrganizationFieldsConfig(BaseModel):
    model_config = ConfigDict(title="Get Organization Fields")

    operation: Literal["get_organization_fields"] = Field(
        "get_organization_fields",
        json_schema_extra={
            "const": "get_organization_fields",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Fields",
        },
        title="Get Organization Fields",
    )


# ============================================================================
# Opportunities Operation Configs
# ============================================================================


class AffinityListOpportunitiesConfig(BaseModel):
    model_config = ConfigDict(title="List Opportunities")

    operation: Literal["list_opportunities"] = Field(
        "list_opportunities",
        json_schema_extra={
            "const": "list_opportunities",
            "ui:hidden": True,
            "x-category": "Opportunity",
            "x-is-trigger": False,
            "x-display-name": "List Opportunities",
        },
        title="List Opportunities",
    )
    term: Optional[str] = Field(None, title="Search Term", description="Filter by name")
    page_size: Optional[int] = Field(None, title="Page Size", ge=1, le=500)
    page_token: Optional[str] = Field(None, title="Page Token")


class AffinityGetOpportunityConfig(BaseModel):
    model_config = ConfigDict(title="Get Opportunity")

    operation: Literal["get_opportunity_by_id"] = Field(
        "get_opportunity_by_id",
        json_schema_extra={
            "const": "get_opportunity_by_id",
            "ui:hidden": True,
            "x-category": "Opportunity",
            "x-is-trigger": False,
            "x-display-name": "Get Opportunity by Id",
        },
        title="Get Opportunity by Id",
    )
    opportunity_id: int = Field(..., title="Opportunity ID")


class AffinityCreateOpportunityConfig(BaseModel):
    model_config = ConfigDict(title="Create Opportunity")

    operation: Literal["create_opportunity"] = Field(
        "create_opportunity",
        json_schema_extra={
            "const": "create_opportunity",
            "ui:hidden": True,
            "x-category": "Opportunity",
            "x-is-trigger": False,
            "x-display-name": "Create Opportunity",
        },
        title="Create Opportunity",
    )
    name: str = Field(..., title="Name")
    list_id: int = Field(
        ..., title="List ID", description="Opportunity list to create in"
    )
    person_ids: Optional[str] = Field(
        None, title="Person IDs", description="Comma-separated person IDs"
    )
    organization_ids: Optional[str] = Field(
        None, title="Organization IDs", description="Comma-separated organization IDs"
    )


class AffinityUpdateOpportunityConfig(BaseModel):
    model_config = ConfigDict(title="Update Opportunity")

    operation: Literal["update_opportunity"] = Field(
        "update_opportunity",
        json_schema_extra={
            "const": "update_opportunity",
            "ui:hidden": True,
            "x-category": "Opportunity",
            "x-is-trigger": False,
            "x-display-name": "Update Opportunity",
        },
        title="Update Opportunity",
    )
    opportunity_id: int = Field(..., title="Opportunity ID")
    name: Optional[str] = Field(None, title="Name")


class AffinityDeleteOpportunityConfig(BaseModel):
    model_config = ConfigDict(title="Delete Opportunity")

    operation: Literal["delete_opportunity"] = Field(
        "delete_opportunity",
        json_schema_extra={
            "const": "delete_opportunity",
            "ui:hidden": True,
            "x-category": "Opportunity",
            "x-is-trigger": False,
            "x-display-name": "Delete Opportunity",
        },
        title="Delete Opportunity",
    )
    opportunity_id: int = Field(..., title="Opportunity ID")


# ============================================================================
# Lists Operation Configs
# ============================================================================


class AffinityListListsConfig(BaseModel):
    model_config = ConfigDict(title="List Lists")

    operation: Literal["list_lists"] = Field(
        "list_lists",
        json_schema_extra={
            "const": "list_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List Lists",
        },
        title="List Lists",
    )


class AffinityGetListConfig(BaseModel):
    model_config = ConfigDict(title="Get List")

    operation: Literal["get_list_by_id"] = Field(
        "get_list_by_id",
        json_schema_extra={
            "const": "get_list_by_id",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get List by Id",
        },
        title="Get List by Id",
    )
    list_id: int = Field(..., title="List ID")


class AffinityCreateListConfig(BaseModel):
    model_config = ConfigDict(title="Create List")

    operation: Literal["create_list"] = Field(
        "create_list",
        json_schema_extra={
            "const": "create_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Create List",
        },
        title="Create List",
    )
    name: str = Field(..., title="Name", description="Name for the new list")
    type: str = Field(
        ...,
        title="List Type",
        json_schema_extra={
            "enum": ["0", "1", "8"],
            "enumNames": ["Person", "Organization", "Opportunity"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# List Entries Operation Configs
# ============================================================================


class AffinityListListEntriesConfig(BaseModel):
    model_config = ConfigDict(title="List List Entries")

    operation: Literal["list_list_entries"] = Field(
        "list_list_entries",
        json_schema_extra={
            "const": "list_list_entries",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "List List Entries",
        },
        title="List List Entries",
    )
    list_id: int = Field(..., title="List ID")
    page_size: Optional[int] = Field(None, title="Page Size", ge=1, le=500)
    page_token: Optional[str] = Field(None, title="Page Token")


class AffinityGetListEntryConfig(BaseModel):
    model_config = ConfigDict(title="Get List Entry")

    operation: Literal["get_list_entry"] = Field(
        "get_list_entry",
        json_schema_extra={
            "const": "get_list_entry",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "Get List Entry",
        },
        title="Get List Entry",
    )
    list_id: int = Field(..., title="List ID")
    entry_id: int = Field(..., title="Entry ID")


class AffinityCreateListEntryConfig(BaseModel):
    model_config = ConfigDict(title="Create List Entry")

    operation: Literal["create_list_entry"] = Field(
        "create_list_entry",
        json_schema_extra={
            "const": "create_list_entry",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "Create List Entry",
        },
        title="Create List Entry",
    )
    list_id: int = Field(..., title="List ID")
    entity_id: int = Field(
        ..., title="Entity ID", description="ID of person, organization, or opportunity"
    )


class AffinityDeleteListEntryConfig(BaseModel):
    model_config = ConfigDict(title="Delete List Entry")

    operation: Literal["delete_list_entry"] = Field(
        "delete_list_entry",
        json_schema_extra={
            "const": "delete_list_entry",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "Delete List Entry",
        },
        title="Delete List Entry",
    )
    list_id: int = Field(..., title="List ID")
    entry_id: int = Field(..., title="Entry ID")


# ============================================================================
# Fields Operation Configs
# ============================================================================


class AffinityListFieldsConfig(BaseModel):
    model_config = ConfigDict(title="List Fields")

    operation: Literal["list_custom_fields"] = Field(
        "list_custom_fields",
        json_schema_extra={
            "const": "list_custom_fields",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "List Custom Fields",
        },
        title="List Custom Fields",
    )
    list_id: Optional[int] = Field(None, title="List ID", description="Filter by list")
    value_type: Optional[int] = Field(
        None, title="Value Type", description="Filter by field value type"
    )


class AffinityCreateFieldConfig(BaseModel):
    model_config = ConfigDict(title="Create Field")

    operation: Literal["create_custom_field"] = Field(
        "create_custom_field",
        json_schema_extra={
            "const": "create_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    name: str = Field(..., title="Field Name")
    entity_type: str = Field(
        ...,
        title="Entity Type",
        json_schema_extra={
            "enum": ["0", "1", "2"],
            "enumNames": ["Person", "Organization", "Opportunity"],
            "x-enum-searchable": True,
        },
    )
    value_type: str = Field(
        ...,
        title="Value Type",
        json_schema_extra={
            "enum": ["0", "1", "2", "3", "4", "5", "6", "7", "8"],
            "enumNames": [
                "Person",
                "Organization",
                "Dropdown",
                "Number",
                "Date",
                "Location",
                "Text",
                "Ranked Dropdown",
                "Formula",
            ],
            "x-enum-searchable": True,
        },
    )
    list_id: Optional[int] = Field(
        None, title="List ID", description="If set, field is list-specific"
    )
    allows_multiple: Optional[str] = Field(
        None,
        title="Allows Multiple",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AffinityDeleteFieldConfig(BaseModel):
    model_config = ConfigDict(title="Delete Field")

    operation: Literal["delete_custom_field"] = Field(
        "delete_custom_field",
        json_schema_extra={
            "const": "delete_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Field",
        },
        title="Delete Custom Field",
    )
    field_id: int = Field(..., title="Field ID")


# ============================================================================
# Field Values Operation Configs
# ============================================================================


class AffinityListFieldValuesConfig(BaseModel):
    model_config = ConfigDict(title="List Field Values")

    operation: Literal["list_field_values"] = Field(
        "list_field_values",
        json_schema_extra={
            "const": "list_field_values",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "List Field Values",
        },
        title="List Field Values",
    )
    person_id: Optional[int] = Field(
        None, title="Person ID", description="Get field values for this person"
    )
    organization_id: Optional[int] = Field(
        None,
        title="Organization ID",
        description="Get field values for this organization",
    )
    opportunity_id: Optional[int] = Field(
        None,
        title="Opportunity ID",
        description="Get field values for this opportunity",
    )
    list_entry_id: Optional[int] = Field(
        None, title="List Entry ID", description="Get field values for this list entry"
    )


class AffinityCreateFieldValueConfig(BaseModel):
    model_config = ConfigDict(title="Create Field Value")

    operation: Literal["create_field_value"] = Field(
        "create_field_value",
        json_schema_extra={
            "const": "create_field_value",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "Create Field Value",
        },
        title="Create Field Value",
    )
    field_id: int = Field(..., title="Field ID")
    entity_id: int = Field(
        ..., title="Entity ID", description="Person, organization, or opportunity ID"
    )
    value: str = Field(
        ..., title="Value", description="Value to set (use JSON for complex values)"
    )
    list_entry_id: Optional[int] = Field(
        None, title="List Entry ID", description="Required for list-specific fields"
    )


class AffinityUpdateFieldValueConfig(BaseModel):
    model_config = ConfigDict(title="Update Field Value")

    operation: Literal["update_field_value"] = Field(
        "update_field_value",
        json_schema_extra={
            "const": "update_field_value",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "Update Field Value",
        },
        title="Update Field Value",
    )
    field_value_id: int = Field(..., title="Field Value ID")
    value: str = Field(
        ..., title="Value", description="New value (use JSON for complex values)"
    )


class AffinityDeleteFieldValueConfig(BaseModel):
    model_config = ConfigDict(title="Delete Field Value")

    operation: Literal["delete_field_value"] = Field(
        "delete_field_value",
        json_schema_extra={
            "const": "delete_field_value",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "Delete Field Value",
        },
        title="Delete Field Value",
    )
    field_value_id: int = Field(..., title="Field Value ID")


class AffinityListFieldValueChangesConfig(BaseModel):
    model_config = ConfigDict(title="List Field Value Changes")

    operation: Literal["list_field_value_changes"] = Field(
        "list_field_value_changes",
        json_schema_extra={
            "const": "list_field_value_changes",
            "ui:hidden": True,
            "x-category": "Custom Field",
            "x-is-trigger": False,
            "x-display-name": "List Field Value Changes",
        },
        title="List Field Value Changes",
    )
    field_id: Optional[int] = Field(
        None, title="Field ID", description="Filter by field"
    )
    entity_id: Optional[int] = Field(
        None, title="Entity ID", description="Filter by entity"
    )
    list_entry_id: Optional[int] = Field(None, title="List Entry ID")
    page_size: Optional[int] = Field(None, title="Page Size", ge=1, le=500)
    page_token: Optional[str] = Field(None, title="Page Token")


# ============================================================================
# Notes Operation Configs
# ============================================================================


class AffinityListNotesConfig(BaseModel):
    model_config = ConfigDict(title="List Notes")

    operation: Literal["list_notes"] = Field(
        "list_notes",
        json_schema_extra={
            "const": "list_notes",
            "ui:hidden": True,
            "x-category": "Note",
            "x-is-trigger": False,
            "x-display-name": "List Notes",
        },
        title="List Notes",
    )
    person_id: Optional[int] = Field(
        None, title="Person ID", description="Filter notes for this person"
    )
    organization_id: Optional[int] = Field(
        None, title="Organization ID", description="Filter notes for this organization"
    )
    opportunity_id: Optional[int] = Field(
        None, title="Opportunity ID", description="Filter notes for this opportunity"
    )


class AffinityGetNoteConfig(BaseModel):
    model_config = ConfigDict(title="Get Note")

    operation: Literal["get_note_by_id"] = Field(
        "get_note_by_id",
        json_schema_extra={
            "const": "get_note_by_id",
            "ui:hidden": True,
            "x-category": "Note",
            "x-is-trigger": False,
            "x-display-name": "Get Note by Id",
        },
        title="Get Note by Id",
    )
    note_id: int = Field(..., title="Note ID")


class AffinityCreateNoteConfig(BaseModel):
    model_config = ConfigDict(title="Create Note")

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": "Note",
            "x-is-trigger": False,
            "x-display-name": "Create Note",
        },
        title="Create Note",
    )
    content: str = Field(
        ...,
        title="Content",
        description="Text content of the note",
        json_schema_extra={"ui:widget": "textarea"},
    )
    person_ids: Optional[str] = Field(
        None, title="Person IDs", description="Comma-separated person IDs"
    )
    organization_ids: Optional[str] = Field(
        None, title="Organization IDs", description="Comma-separated organization IDs"
    )
    opportunity_ids: Optional[str] = Field(
        None, title="Opportunity IDs", description="Comma-separated opportunity IDs"
    )
    gmail_address: Optional[str] = Field(
        None, title="Gmail Address", description="Associate with a Gmail address"
    )


class AffinityUpdateNoteConfig(BaseModel):
    model_config = ConfigDict(title="Update Note")

    operation: Literal["update_note"] = Field(
        "update_note",
        json_schema_extra={
            "const": "update_note",
            "ui:hidden": True,
            "x-category": "Note",
            "x-is-trigger": False,
            "x-display-name": "Update Note",
        },
        title="Update Note",
    )
    note_id: int = Field(..., title="Note ID")
    content: str = Field(
        ...,
        title="Content",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AffinityDeleteNoteConfig(BaseModel):
    model_config = ConfigDict(title="Delete Note")

    operation: Literal["delete_note"] = Field(
        "delete_note",
        json_schema_extra={
            "const": "delete_note",
            "ui:hidden": True,
            "x-category": "Note",
            "x-is-trigger": False,
            "x-display-name": "Delete Note",
        },
        title="Delete Note",
    )
    note_id: int = Field(..., title="Note ID")


# ============================================================================
# Reminders Operation Configs
# ============================================================================


class AffinityListRemindersConfig(BaseModel):
    model_config = ConfigDict(title="List Reminders")

    operation: Literal["list_reminders"] = Field(
        "list_reminders",
        json_schema_extra={
            "const": "list_reminders",
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "List Reminders",
        },
        title="List Reminders",
    )
    person_id: Optional[int] = Field(
        None, title="Person ID", description="Filter reminders for this person"
    )
    organization_id: Optional[int] = Field(
        None,
        title="Organization ID",
        description="Filter reminders for this organization",
    )
    opportunity_id: Optional[int] = Field(
        None,
        title="Opportunity ID",
        description="Filter reminders for this opportunity",
    )
    owner_id: Optional[int] = Field(
        None, title="Owner ID", description="Filter by owner"
    )


class AffinityGetReminderConfig(BaseModel):
    model_config = ConfigDict(title="Get Reminder")

    operation: Literal["get_reminder_by_id"] = Field(
        "get_reminder_by_id",
        json_schema_extra={
            "const": "get_reminder_by_id",
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Get Reminder by Id",
        },
        title="Get Reminder by Id",
    )
    reminder_id: int = Field(..., title="Reminder ID")


class AffinityCreateReminderConfig(BaseModel):
    model_config = ConfigDict(title="Create Reminder")

    operation: Literal["create_reminder"] = Field(
        "create_reminder",
        json_schema_extra={
            "const": "create_reminder",
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Create Reminder",
        },
        title="Create Reminder",
    )
    content: str = Field(
        ..., title="Content", description="Text content of the reminder"
    )
    due_date: str = Field(
        ...,
        title="Due Date",
        description="ISO 8601 format (e.g., 2024-12-31T12:00:00Z)",
    )
    person_ids: Optional[str] = Field(
        None, title="Person IDs", description="Comma-separated person IDs"
    )
    organization_ids: Optional[str] = Field(
        None, title="Organization IDs", description="Comma-separated organization IDs"
    )
    opportunity_ids: Optional[str] = Field(
        None, title="Opportunity IDs", description="Comma-separated opportunity IDs"
    )
    owner_id: Optional[int] = Field(
        None, title="Owner ID", description="User who owns this reminder"
    )


class AffinityUpdateReminderConfig(BaseModel):
    model_config = ConfigDict(title="Update Reminder")

    operation: Literal["update_reminder"] = Field(
        "update_reminder",
        json_schema_extra={
            "const": "update_reminder",
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Update Reminder",
        },
        title="Update Reminder",
    )
    reminder_id: int = Field(..., title="Reminder ID")
    content: Optional[str] = Field(None, title="Content")
    due_date: Optional[str] = Field(None, title="Due Date", description="ISO 8601 date")
    completed_at: Optional[str] = Field(
        None,
        title="Completed At",
        description="ISO 8601 timestamp when completed",
    )


class AffinityDeleteReminderConfig(BaseModel):
    model_config = ConfigDict(title="Delete Reminder")

    operation: Literal["delete_reminder"] = Field(
        "delete_reminder",
        json_schema_extra={
            "const": "delete_reminder",
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Delete Reminder",
        },
        title="Delete Reminder",
    )
    reminder_id: int = Field(..., title="Reminder ID")


# ============================================================================
# Relationship Strengths Operation Config
# ============================================================================


class AffinityGetRelationshipStrengthsConfig(BaseModel):
    model_config = ConfigDict(title="Get Relationship Strengths")

    operation: Literal["get_relationship_strengths"] = Field(
        "get_relationship_strengths",
        json_schema_extra={
            "const": "get_relationship_strengths",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Relationship Strengths",
        },
        title="Get Relationship Strengths",
    )
    internal_id: Optional[int] = Field(
        None,
        title="Internal User ID",
        description="Filter for a specific internal team member",
    )
    external_id: Optional[int] = Field(
        None,
        title="External Person/Org ID",
        description="Filter for a specific external contact or organization",
    )


# ============================================================================
# Webhooks Operation Configs
# ============================================================================


class AffinityListWebhooksConfig(BaseModel):
    model_config = ConfigDict(title="List Webhooks")

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )


class AffinityGetWebhookConfig(BaseModel):
    model_config = ConfigDict(title="Get Webhook")

    operation: Literal["get_webhook_by_id"] = Field(
        "get_webhook_by_id",
        json_schema_extra={
            "const": "get_webhook_by_id",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook by Id",
        },
        title="Get Webhook by Id",
    )
    webhook_id: int = Field(..., title="Webhook ID")


class AffinityCreateWebhookConfig(BaseModel):
    model_config = ConfigDict(title="Create Webhook")

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    webhook_url: str = Field(
        ..., title="Webhook URL", description="URL to receive webhook notifications"
    )
    subscriptions: str = Field(
        ...,
        title="Subscriptions",
        description='JSON array of subscription objects, e.g. [{"type": 0, "triggers": [1]}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class AffinityUpdateWebhookConfig(BaseModel):
    model_config = ConfigDict(title="Update Webhook")

    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={
            "const": "update_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook",
        },
        title="Update Webhook",
    )
    webhook_id: int = Field(..., title="Webhook ID")
    webhook_url: Optional[str] = Field(None, title="Webhook URL")
    subscriptions: Optional[str] = Field(
        None,
        title="Subscriptions",
        description="JSON array of subscription objects",
    )


class AffinityDeleteWebhookConfig(BaseModel):
    model_config = ConfigDict(title="Delete Webhook")

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "const": "delete_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    webhook_id: int = Field(..., title="Webhook ID")


# ============================================================================
# Files Operation Configs
# ============================================================================


class AffinityListFilesConfig(BaseModel):
    model_config = ConfigDict(title="List Files")

    operation: Literal["list_files"] = Field(
        "list_files",
        json_schema_extra={
            "const": "list_files",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Files",
        },
        title="List Files",
    )
    person_id: Optional[int] = Field(
        None, title="Person ID", description="Filter files for this person"
    )
    organization_id: Optional[int] = Field(
        None, title="Organization ID", description="Filter files for this organization"
    )
    opportunity_id: Optional[int] = Field(
        None, title="Opportunity ID", description="Filter files for this opportunity"
    )


class AffinityGetFileConfig(BaseModel):
    model_config = ConfigDict(title="Get File")

    operation: Literal["get_file_by_id"] = Field(
        "get_file_by_id",
        json_schema_extra={
            "const": "get_file_by_id",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File by Id",
        },
        title="Get File by Id",
    )
    file_id: int = Field(..., title="File ID")


class AffinityDownloadFileConfig(BaseModel):
    model_config = ConfigDict(title="Download File")

    operation: Literal["download_file"] = Field(
        "download_file",
        json_schema_extra={
            "const": "download_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Download File",
        },
        title="Download File",
    )
    file_id: int = Field(..., title="File ID")


class AffinityUploadFileConfig(BaseModel):
    model_config = ConfigDict(title="Upload File")

    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={
            "const": "upload_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File",
        },
        title="Upload File",
    )
    file_url: str = Field(
        ...,
        title="File URL",
        description=(
            "The file to upload — upload a file, paste a URL, or reference an "
            "upstream file (e.g. {{http-1.response.url}})."
        ),
        json_schema_extra={"ui:widget": "media_upload"},
    )
    file_name: str = Field(
        ..., title="File Name", description="Name for the uploaded file"
    )
    person_id: Optional[int] = Field(
        None, title="Person ID", description="Attach file to this person"
    )
    organization_id: Optional[int] = Field(
        None, title="Organization ID", description="Attach file to this organization"
    )
    opportunity_id: Optional[int] = Field(
        None, title="Opportunity ID", description="Attach file to this opportunity"
    )


# ============================================================================
# v2 Companies Operation Configs
# ============================================================================


class AffinityListCompaniesV2Config(BaseModel):
    model_config = ConfigDict(title="List Companies (v2)")

    operation: Literal["list_companies"] = Field(
        "list_companies",
        json_schema_extra={
            "const": "list_companies",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Companies",
        },
        title="List Companies",
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor from previous response"
    )
    limit: Optional[int] = Field(
        None, title="Limit", description="Max results to return", ge=1, le=100
    )


class AffinityGetCompanyV2Config(BaseModel):
    model_config = ConfigDict(title="Get Company (v2)")

    operation: Literal["get_company_by_id"] = Field(
        "get_company_by_id",
        json_schema_extra={
            "const": "get_company_by_id",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Company by Id",
        },
        title="Get Company by Id",
    )
    company_id: int = Field(..., title="Company ID")


class AffinityListCompanyFieldsV2Config(BaseModel):
    model_config = ConfigDict(title="List Company Fields (v2)")

    operation: Literal["list_company_fields"] = Field(
        "list_company_fields",
        json_schema_extra={
            "const": "list_company_fields",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Company Fields",
        },
        title="List Company Fields",
    )
    company_id: int = Field(..., title="Company ID")


# ============================================================================
# v2 List Entry Fields Operation Configs
# ============================================================================


class AffinityListListFieldsV2Config(BaseModel):
    model_config = ConfigDict(title="List List Fields (v2)")

    operation: Literal["list_list_fields"] = Field(
        "list_list_fields",
        json_schema_extra={
            "const": "list_list_fields",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "List List Fields",
        },
        title="List List Fields",
    )
    list_id: int = Field(..., title="List ID")


class AffinityGetListEntryFieldsV2Config(BaseModel):
    model_config = ConfigDict(title="Get List Entry Fields (v2)")

    operation: Literal["get_list_entry_fields"] = Field(
        "get_list_entry_fields",
        json_schema_extra={
            "const": "get_list_entry_fields",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "Get List Entry Fields",
        },
        title="Get List Entry Fields",
    )
    list_id: int = Field(..., title="List ID")
    entry_id: int = Field(..., title="Entry ID")


class AffinityUpdateListEntryFieldsV2Config(BaseModel):
    model_config = ConfigDict(title="Update List Entry Fields (v2)")

    operation: Literal["update_list_entry_fields"] = Field(
        "update_list_entry_fields",
        json_schema_extra={
            "const": "update_list_entry_fields",
            "ui:hidden": True,
            "x-category": "List Entry",
            "x-is-trigger": False,
            "x-display-name": "Update List Entry Fields",
        },
        title="Update List Entry Fields",
    )
    list_id: int = Field(..., title="List ID")
    entry_id: int = Field(..., title="Entry ID")
    fields: str = Field(
        ...,
        title="Fields",
        description='JSON array of field updates, e.g. [{"id": 123, "value": "new_value"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Union of all configs + Node Config
# ============================================================================

AffinityConfig = Annotated[
    Union[
        # System
        AffinityGetWhoamiConfig,
        AffinityGetRateLimitConfig,
        # Persons
        AffinityListPersonsConfig,
        AffinityGetPersonConfig,
        AffinityCreatePersonConfig,
        AffinityUpdatePersonConfig,
        AffinityDeletePersonConfig,
        AffinityGetPersonFieldsConfig,
        # Organizations
        AffinityListOrganizationsConfig,
        AffinityGetOrganizationConfig,
        AffinityCreateOrganizationConfig,
        AffinityUpdateOrganizationConfig,
        AffinityDeleteOrganizationConfig,
        AffinityGetOrganizationFieldsConfig,
        # Opportunities
        AffinityListOpportunitiesConfig,
        AffinityGetOpportunityConfig,
        AffinityCreateOpportunityConfig,
        AffinityUpdateOpportunityConfig,
        AffinityDeleteOpportunityConfig,
        # Lists
        AffinityListListsConfig,
        AffinityGetListConfig,
        AffinityCreateListConfig,
        # List Entries
        AffinityListListEntriesConfig,
        AffinityGetListEntryConfig,
        AffinityCreateListEntryConfig,
        AffinityDeleteListEntryConfig,
        # Fields
        AffinityListFieldsConfig,
        AffinityCreateFieldConfig,
        AffinityDeleteFieldConfig,
        # Field Values
        AffinityListFieldValuesConfig,
        AffinityCreateFieldValueConfig,
        AffinityUpdateFieldValueConfig,
        AffinityDeleteFieldValueConfig,
        AffinityListFieldValueChangesConfig,
        # Notes
        AffinityListNotesConfig,
        AffinityGetNoteConfig,
        AffinityCreateNoteConfig,
        AffinityUpdateNoteConfig,
        AffinityDeleteNoteConfig,
        # Reminders
        AffinityListRemindersConfig,
        AffinityGetReminderConfig,
        AffinityCreateReminderConfig,
        AffinityUpdateReminderConfig,
        AffinityDeleteReminderConfig,
        # Relationship Strengths
        AffinityGetRelationshipStrengthsConfig,
        # Webhooks
        AffinityListWebhooksConfig,
        AffinityGetWebhookConfig,
        AffinityCreateWebhookConfig,
        AffinityUpdateWebhookConfig,
        AffinityDeleteWebhookConfig,
        # Files
        AffinityListFilesConfig,
        AffinityGetFileConfig,
        AffinityDownloadFileConfig,
        AffinityUploadFileConfig,
        # v2 Companies
        AffinityListCompaniesV2Config,
        AffinityGetCompanyV2Config,
        AffinityListCompanyFieldsV2Config,
        # v2 List Entry Fields
        AffinityListListFieldsV2Config,
        AffinityGetListEntryFieldsV2Config,
        AffinityUpdateListEntryFieldsV2Config,
    ],
    Discriminator("operation"),
]


class AffinityNodeConfig(NodeConfig[AffinityConfig, AffinityAPIKeyCredential]):
    """Full configuration for Affinity CRM node including credentials."""

    credentials: AffinityAPIKeyCredential = Field(
        ..., description="Affinity API key credentials"
    )


# ============================================================================
# Affinity Node Implementation
# ============================================================================


class AffinityNode(WorkflowNode):
    """
    Affinity CRM automation node.

    Executes Affinity CRM API operations for workflow automation.
    Supports 60 operations across all Affinity API resource types:
    - System: Authentication verification, rate limit checking (2 ops)
    - Persons: Full CRUD + fields (6 ops)
    - Organizations: Full CRUD + fields (6 ops)
    - Opportunities: Full CRUD (5 ops)
    - Lists: List management (3 ops)
    - List Entries: Entry management (4 ops)
    - Fields: Custom field management (3 ops)
    - Field Values: Field data management (5 ops)
    - Notes: Note attachment to entities (5 ops)
    - Reminders: Task/follow-up scheduling (5 ops)
    - Relationship Strengths: AI-computed connection metrics (1 op)
    - Webhooks: Event subscription management (5 ops)
    - Files: File upload and download (4 ops)
    - v2 Companies: Enhanced company data (3 ops)
    - v2 List Entry Fields: Batch field management (3 ops)

    Authentication: API Key only (no OAuth available)
    Rate Limit: 900 requests/user/minute
    """

    edit_examples = [
        "Create a person record for jane@acme.com with title VP Sales",
        "Find the organization Acme Corp and pull its full profile",
        "Add a note to the OpenAI opportunity summarizing today's call",
        "Schedule a follow-up reminder for the Stripe deal next Friday",
        "Add a contact to the Q4 Outreach list with custom field values",
        "Search opportunities where stage is 'Closed Won' this quarter",
        "Subscribe a webhook for new list entries on the Targets list",
    ]

    @classmethod
    def get_config_model(cls):
        return AffinityNodeConfig

    def _get_auth_header(self, api_key: str, endpoint: str) -> str:
        """Return correct Authorization header for v1 (Basic) or v2 (Bearer) endpoints."""
        if endpoint.startswith("/v2"):
            return f"Bearer {api_key}"
        encoded = base64.b64encode(f":{api_key}".encode()).decode()
        return f"Basic {encoded}"

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        api_key: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make an authenticated HTTP request to the Affinity API."""
        url = f"{AFFINITY_API_BASE}{endpoint}"
        headers = {
            "Authorization": self._get_auth_header(api_key, endpoint),
            "Content-Type": "application/json",
        }
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params if params else None,
                    json=json_body,
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get("message", str(error_data))
                    except Exception:
                        error_message = error_text
                    logger.error(
                        f"[AffinityNode] API error {response.status_code}: {error_message}"
                    )
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                if response.status_code == 204:
                    data: Dict[str, Any] = {"success": True}
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
                logger.exception(f"[AffinityNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, AffinityNodeConfig):
            raise ValueError("Valid AffinityNodeConfig is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Affinity API key credentials are required")

        op_config = config.config

        handlers = {
            # System
            "get_authenticated_user_info": self._handle_get_whoami,
            "get_rate_limit_info": self._handle_get_rate_limit,
            # Persons
            "list_persons": self._handle_list_persons,
            "get_person_by_id": self._handle_get_person,
            "create_person": self._handle_create_person,
            "update_person": self._handle_update_person,
            "delete_person": self._handle_delete_person,
            "get_person_fields": self._handle_get_person_fields,
            # Organizations
            "list_organizations": self._handle_list_organizations,
            "get_organization_by_id": self._handle_get_organization,
            "create_organization": self._handle_create_organization,
            "update_organization": self._handle_update_organization,
            "delete_organization": self._handle_delete_organization,
            "get_organization_fields": self._handle_get_organization_fields,
            # Opportunities
            "list_opportunities": self._handle_list_opportunities,
            "get_opportunity_by_id": self._handle_get_opportunity,
            "create_opportunity": self._handle_create_opportunity,
            "update_opportunity": self._handle_update_opportunity,
            "delete_opportunity": self._handle_delete_opportunity,
            # Lists
            "list_lists": self._handle_list_lists,
            "get_list_by_id": self._handle_get_list,
            "create_list": self._handle_create_list,
            # List Entries
            "list_list_entries": self._handle_list_list_entries,
            "get_list_entry": self._handle_get_list_entry,
            "create_list_entry": self._handle_create_list_entry,
            "delete_list_entry": self._handle_delete_list_entry,
            # Fields
            "list_custom_fields": self._handle_list_fields,
            "create_custom_field": self._handle_create_field,
            "delete_custom_field": self._handle_delete_field,
            # Field Values
            "list_field_values": self._handle_list_field_values,
            "create_field_value": self._handle_create_field_value,
            "update_field_value": self._handle_update_field_value,
            "delete_field_value": self._handle_delete_field_value,
            "list_field_value_changes": self._handle_list_field_value_changes,
            # Notes
            "list_notes": self._handle_list_notes,
            "get_note_by_id": self._handle_get_note,
            "create_note": self._handle_create_note,
            "update_note": self._handle_update_note,
            "delete_note": self._handle_delete_note,
            # Reminders
            "list_reminders": self._handle_list_reminders,
            "get_reminder_by_id": self._handle_get_reminder,
            "create_reminder": self._handle_create_reminder,
            "update_reminder": self._handle_update_reminder,
            "delete_reminder": self._handle_delete_reminder,
            # Relationship Strengths
            "get_relationship_strengths": self._handle_get_relationship_strengths,
            # Webhooks
            "list_webhooks": self._handle_list_webhooks,
            "get_webhook_by_id": self._handle_get_webhook,
            "create_webhook": self._handle_create_webhook,
            "update_webhook": self._handle_update_webhook,
            "delete_webhook": self._handle_delete_webhook,
            # Files
            "list_files": self._handle_list_files,
            "get_file_by_id": self._handle_get_file,
            "download_file": self._handle_download_file,
            "upload_file": self._handle_upload_file,
            # v2 Companies
            "list_companies": self._handle_list_companies_v2,
            "get_company_by_id": self._handle_get_company_v2,
            "list_company_fields": self._handle_list_company_fields_v2,
            # v2 List Entry Fields
            "list_list_fields": self._handle_list_list_fields_v2,
            "get_list_entry_fields": self._handle_get_list_entry_fields_v2,
            "update_list_entry_fields": self._handle_update_list_entry_fields_v2,
        }

        action = op_config.operation
        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown Affinity action: {action}")

        result = await handler(op_config, credentials)
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }
        return result

    # -------------------------------------------------------------------------
    # System Handlers
    # -------------------------------------------------------------------------

    async def _handle_get_whoami(self, config, credentials):
        return await self._make_request(
            "GET",
            "/auth/whoami",
            credentials.api_key,
            action_name="get_authenticated_user_info",
        )

    async def _handle_get_rate_limit(self, config, credentials):
        return await self._make_request(
            "GET",
            "/rate-limit",
            credentials.api_key,
            action_name="get_rate_limit_info",
        )

    # -------------------------------------------------------------------------
    # Persons Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_persons(
        self, config: AffinityListPersonsConfig, credentials
    ):
        params = {
            "term": config.term,
            "with_interaction_dates": config.with_interaction_dates,
            "page_size": config.page_size,
            "page_token": config.page_token,
        }
        return await self._make_request(
            "GET",
            "/persons",
            credentials.api_key,
            params=params,
            action_name="list_persons",
        )

    async def _handle_get_person(self, config: AffinityGetPersonConfig, credentials):
        params = {"with_interaction_dates": config.with_interaction_dates}
        return await self._make_request(
            "GET",
            f"/persons/{config.person_id}",
            credentials.api_key,
            params=params,
            action_name="get_person_by_id",
        )

    async def _handle_create_person(
        self, config: AffinityCreatePersonConfig, credentials
    ):
        body: Dict[str, Any] = {"first_name": config.first_name}
        if config.last_name:
            body["last_name"] = config.last_name
        if config.emails:
            body["emails"] = [e.strip() for e in config.emails.split(",") if e.strip()]
        if config.organization_ids:
            body["organization_ids"] = [
                int(x.strip()) for x in config.organization_ids.split(",") if x.strip()
            ]
        return await self._make_request(
            "POST",
            "/persons",
            credentials.api_key,
            json_body=body,
            action_name="create_person",
        )

    async def _handle_update_person(
        self, config: AffinityUpdatePersonConfig, credentials
    ):
        body: Dict[str, Any] = {}
        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name
        if config.emails:
            body["emails"] = [e.strip() for e in config.emails.split(",") if e.strip()]
        return await self._make_request(
            "PUT",
            f"/persons/{config.person_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_person",
        )

    async def _handle_delete_person(
        self, config: AffinityDeletePersonConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/persons/{config.person_id}",
            credentials.api_key,
            action_name="delete_person",
        )

    async def _handle_get_person_fields(self, config, credentials):
        return await self._make_request(
            "GET",
            "/persons/fields",
            credentials.api_key,
            action_name="get_person_fields",
        )

    # -------------------------------------------------------------------------
    # Organizations Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_organizations(
        self, config: AffinityListOrganizationsConfig, credentials
    ):
        params = {
            "term": config.term,
            "with_interaction_dates": config.with_interaction_dates,
            "page_size": config.page_size,
            "page_token": config.page_token,
        }
        return await self._make_request(
            "GET",
            "/organizations",
            credentials.api_key,
            params=params,
            action_name="list_organizations",
        )

    async def _handle_get_organization(
        self, config: AffinityGetOrganizationConfig, credentials
    ):
        params = {"with_interaction_dates": config.with_interaction_dates}
        return await self._make_request(
            "GET",
            f"/organizations/{config.organization_id}",
            credentials.api_key,
            params=params,
            action_name="get_organization_by_id",
        )

    async def _handle_create_organization(
        self, config: AffinityCreateOrganizationConfig, credentials
    ):
        body: Dict[str, Any] = {"name": config.name}
        if config.domain:
            body["domain"] = config.domain
        if config.person_ids:
            body["person_ids"] = [
                int(x.strip()) for x in config.person_ids.split(",") if x.strip()
            ]
        return await self._make_request(
            "POST",
            "/organizations",
            credentials.api_key,
            json_body=body,
            action_name="create_organization",
        )

    async def _handle_update_organization(
        self, config: AffinityUpdateOrganizationConfig, credentials
    ):
        body: Dict[str, Any] = {}
        if config.name:
            body["name"] = config.name
        if config.domain:
            body["domain"] = config.domain
        return await self._make_request(
            "PUT",
            f"/organizations/{config.organization_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_organization",
        )

    async def _handle_delete_organization(
        self, config: AffinityDeleteOrganizationConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/organizations/{config.organization_id}",
            credentials.api_key,
            action_name="delete_organization",
        )

    async def _handle_get_organization_fields(self, config, credentials):
        return await self._make_request(
            "GET",
            "/organizations/fields",
            credentials.api_key,
            action_name="get_organization_fields",
        )

    # -------------------------------------------------------------------------
    # Opportunities Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_opportunities(
        self, config: AffinityListOpportunitiesConfig, credentials
    ):
        params = {
            "term": config.term,
            "page_size": config.page_size,
            "page_token": config.page_token,
        }
        return await self._make_request(
            "GET",
            "/opportunities",
            credentials.api_key,
            params=params,
            action_name="list_opportunities",
        )

    async def _handle_get_opportunity(
        self, config: AffinityGetOpportunityConfig, credentials
    ):
        return await self._make_request(
            "GET",
            f"/opportunities/{config.opportunity_id}",
            credentials.api_key,
            action_name="get_opportunity_by_id",
        )

    async def _handle_create_opportunity(
        self, config: AffinityCreateOpportunityConfig, credentials
    ):
        body: Dict[str, Any] = {"name": config.name, "list_id": config.list_id}
        if config.person_ids:
            body["person_ids"] = [
                int(x.strip()) for x in config.person_ids.split(",") if x.strip()
            ]
        if config.organization_ids:
            body["organization_ids"] = [
                int(x.strip()) for x in config.organization_ids.split(",") if x.strip()
            ]
        return await self._make_request(
            "POST",
            "/opportunities",
            credentials.api_key,
            json_body=body,
            action_name="create_opportunity",
        )

    async def _handle_update_opportunity(
        self, config: AffinityUpdateOpportunityConfig, credentials
    ):
        body: Dict[str, Any] = {}
        if config.name:
            body["name"] = config.name
        return await self._make_request(
            "PUT",
            f"/opportunities/{config.opportunity_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_opportunity",
        )

    async def _handle_delete_opportunity(
        self, config: AffinityDeleteOpportunityConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/opportunities/{config.opportunity_id}",
            credentials.api_key,
            action_name="delete_opportunity",
        )

    # -------------------------------------------------------------------------
    # Lists Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_lists(self, config, credentials):
        return await self._make_request(
            "GET", "/lists", credentials.api_key, action_name="list_lists"
        )

    async def _handle_get_list(self, config: AffinityGetListConfig, credentials):
        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}",
            credentials.api_key,
            action_name="get_list_by_id",
        )

    async def _handle_create_list(self, config: AffinityCreateListConfig, credentials):
        body: Dict[str, Any] = {"name": config.name, "type": int(config.type)}
        return await self._make_request(
            "POST",
            "/lists",
            credentials.api_key,
            json_body=body,
            action_name="create_list",
        )

    # -------------------------------------------------------------------------
    # List Entries Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_list_entries(
        self, config: AffinityListListEntriesConfig, credentials
    ):
        params = {
            "page_size": config.page_size,
            "page_token": config.page_token,
        }
        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}/list-entries",
            credentials.api_key,
            params=params,
            action_name="list_list_entries",
        )

    async def _handle_get_list_entry(
        self, config: AffinityGetListEntryConfig, credentials
    ):
        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}/list-entries/{config.entry_id}",
            credentials.api_key,
            action_name="get_list_entry",
        )

    async def _handle_create_list_entry(
        self, config: AffinityCreateListEntryConfig, credentials
    ):
        body: Dict[str, Any] = {"entity_id": config.entity_id}
        return await self._make_request(
            "POST",
            f"/lists/{config.list_id}/list-entries",
            credentials.api_key,
            json_body=body,
            action_name="create_list_entry",
        )

    async def _handle_delete_list_entry(
        self, config: AffinityDeleteListEntryConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/lists/{config.list_id}/list-entries/{config.entry_id}",
            credentials.api_key,
            action_name="delete_list_entry",
        )

    # -------------------------------------------------------------------------
    # Fields Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_fields(self, config: AffinityListFieldsConfig, credentials):
        params = {
            "list_id": config.list_id,
            "value_type": config.value_type,
        }
        return await self._make_request(
            "GET",
            "/fields",
            credentials.api_key,
            params=params,
            action_name="list_custom_fields",
        )

    async def _handle_create_field(
        self, config: AffinityCreateFieldConfig, credentials
    ):
        body: Dict[str, Any] = {
            "name": config.name,
            "entity_type": int(config.entity_type),
            "value_type": int(config.value_type),
        }
        if config.list_id is not None:
            body["list_id"] = config.list_id
        if config.allows_multiple is not None:
            body["allows_multiple"] = config.allows_multiple == "true"
        return await self._make_request(
            "POST",
            "/fields",
            credentials.api_key,
            json_body=body,
            action_name="create_custom_field",
        )

    async def _handle_delete_field(
        self, config: AffinityDeleteFieldConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/fields/{config.field_id}",
            credentials.api_key,
            action_name="delete_custom_field",
        )

    # -------------------------------------------------------------------------
    # Field Values Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_field_values(
        self, config: AffinityListFieldValuesConfig, credentials
    ):
        params = {
            "person_id": config.person_id,
            "organization_id": config.organization_id,
            "opportunity_id": config.opportunity_id,
            "list_entry_id": config.list_entry_id,
        }
        return await self._make_request(
            "GET",
            "/field-values",
            credentials.api_key,
            params=params,
            action_name="list_field_values",
        )

    async def _handle_create_field_value(
        self, config: AffinityCreateFieldValueConfig, credentials
    ):
        import json as json_mod

        try:
            value = json_mod.loads(config.value)
        except (json_mod.JSONDecodeError, TypeError):
            value = config.value
        body: Dict[str, Any] = {
            "field_id": config.field_id,
            "entity_id": config.entity_id,
            "value": value,
        }
        if config.list_entry_id is not None:
            body["list_entry_id"] = config.list_entry_id
        return await self._make_request(
            "POST",
            "/field-values",
            credentials.api_key,
            json_body=body,
            action_name="create_field_value",
        )

    async def _handle_update_field_value(
        self, config: AffinityUpdateFieldValueConfig, credentials
    ):
        import json as json_mod

        try:
            value = json_mod.loads(config.value)
        except (json_mod.JSONDecodeError, TypeError):
            value = config.value
        body: Dict[str, Any] = {"value": value}
        return await self._make_request(
            "PUT",
            f"/field-values/{config.field_value_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_field_value",
        )

    async def _handle_delete_field_value(
        self, config: AffinityDeleteFieldValueConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/field-values/{config.field_value_id}",
            credentials.api_key,
            action_name="delete_field_value",
        )

    async def _handle_list_field_value_changes(
        self, config: AffinityListFieldValueChangesConfig, credentials
    ):
        params = {
            "field_id": config.field_id,
            "entity_id": config.entity_id,
            "list_entry_id": config.list_entry_id,
            "page_size": config.page_size,
            "page_token": config.page_token,
        }
        return await self._make_request(
            "GET",
            "/field-value-changes",
            credentials.api_key,
            params=params,
            action_name="list_field_value_changes",
        )

    # -------------------------------------------------------------------------
    # Notes Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_notes(self, config: AffinityListNotesConfig, credentials):
        params = {
            "person_id": config.person_id,
            "organization_id": config.organization_id,
            "opportunity_id": config.opportunity_id,
        }
        return await self._make_request(
            "GET",
            "/notes",
            credentials.api_key,
            params=params,
            action_name="list_notes",
        )

    async def _handle_get_note(self, config: AffinityGetNoteConfig, credentials):
        return await self._make_request(
            "GET",
            f"/notes/{config.note_id}",
            credentials.api_key,
            action_name="get_note_by_id",
        )

    async def _handle_create_note(self, config: AffinityCreateNoteConfig, credentials):
        body: Dict[str, Any] = {"content": config.content}
        if config.person_ids:
            body["person_ids"] = [
                int(x.strip()) for x in config.person_ids.split(",") if x.strip()
            ]
        if config.organization_ids:
            body["organization_ids"] = [
                int(x.strip()) for x in config.organization_ids.split(",") if x.strip()
            ]
        if config.opportunity_ids:
            body["opportunity_ids"] = [
                int(x.strip()) for x in config.opportunity_ids.split(",") if x.strip()
            ]
        if config.gmail_address:
            body["gmail_address"] = config.gmail_address
        return await self._make_request(
            "POST",
            "/notes",
            credentials.api_key,
            json_body=body,
            action_name="create_note",
        )

    async def _handle_update_note(self, config: AffinityUpdateNoteConfig, credentials):
        body: Dict[str, Any] = {"content": config.content}
        return await self._make_request(
            "PUT",
            f"/notes/{config.note_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_note",
        )

    async def _handle_delete_note(self, config: AffinityDeleteNoteConfig, credentials):
        return await self._make_request(
            "DELETE",
            f"/notes/{config.note_id}",
            credentials.api_key,
            action_name="delete_note",
        )

    # -------------------------------------------------------------------------
    # Reminders Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_reminders(
        self, config: AffinityListRemindersConfig, credentials
    ):
        params = {
            "person_id": config.person_id,
            "organization_id": config.organization_id,
            "opportunity_id": config.opportunity_id,
            "owner_id": config.owner_id,
        }
        return await self._make_request(
            "GET",
            "/reminders",
            credentials.api_key,
            params=params,
            action_name="list_reminders",
        )

    async def _handle_get_reminder(
        self, config: AffinityGetReminderConfig, credentials
    ):
        return await self._make_request(
            "GET",
            f"/reminders/{config.reminder_id}",
            credentials.api_key,
            action_name="get_reminder_by_id",
        )

    async def _handle_create_reminder(
        self, config: AffinityCreateReminderConfig, credentials
    ):
        body: Dict[str, Any] = {"content": config.content, "due_date": config.due_date}
        if config.person_ids:
            body["person_ids"] = [
                int(x.strip()) for x in config.person_ids.split(",") if x.strip()
            ]
        if config.organization_ids:
            body["organization_ids"] = [
                int(x.strip()) for x in config.organization_ids.split(",") if x.strip()
            ]
        if config.opportunity_ids:
            body["opportunity_ids"] = [
                int(x.strip()) for x in config.opportunity_ids.split(",") if x.strip()
            ]
        if config.owner_id is not None:
            body["owner_id"] = config.owner_id
        return await self._make_request(
            "POST",
            "/reminders",
            credentials.api_key,
            json_body=body,
            action_name="create_reminder",
        )

    async def _handle_update_reminder(
        self, config: AffinityUpdateReminderConfig, credentials
    ):
        body: Dict[str, Any] = {}
        if config.content:
            body["content"] = config.content
        if config.due_date:
            body["due_date"] = config.due_date
        if config.completed_at:
            body["completed_at"] = config.completed_at
        return await self._make_request(
            "PUT",
            f"/reminders/{config.reminder_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_reminder",
        )

    async def _handle_delete_reminder(
        self, config: AffinityDeleteReminderConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/reminders/{config.reminder_id}",
            credentials.api_key,
            action_name="delete_reminder",
        )

    # -------------------------------------------------------------------------
    # Relationship Strengths Handler
    # -------------------------------------------------------------------------

    async def _handle_get_relationship_strengths(
        self, config: AffinityGetRelationshipStrengthsConfig, credentials
    ):
        params = {
            "internal_id": config.internal_id,
            "external_id": config.external_id,
        }
        return await self._make_request(
            "GET",
            "/relationships-strengths",
            credentials.api_key,
            params=params,
            action_name="get_relationship_strengths",
        )

    # -------------------------------------------------------------------------
    # Webhooks Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_webhooks(self, config, credentials):
        return await self._make_request(
            "GET",
            "/webhook-subscriptions",
            credentials.api_key,
            action_name="list_webhooks",
        )

    async def _handle_get_webhook(self, config: AffinityGetWebhookConfig, credentials):
        return await self._make_request(
            "GET",
            f"/webhook-subscriptions/{config.webhook_id}",
            credentials.api_key,
            action_name="get_webhook_by_id",
        )

    async def _handle_create_webhook(
        self, config: AffinityCreateWebhookConfig, credentials
    ):
        import json as json_mod

        try:
            subscriptions = json_mod.loads(config.subscriptions)
        except (json_mod.JSONDecodeError, TypeError):
            subscriptions = config.subscriptions
        body: Dict[str, Any] = {
            "webhook_url": config.webhook_url,
            "subscriptions": subscriptions,
        }
        return await self._make_request(
            "POST",
            "/webhook-subscriptions",
            credentials.api_key,
            json_body=body,
            action_name="create_webhook",
        )

    async def _handle_update_webhook(
        self, config: AffinityUpdateWebhookConfig, credentials
    ):
        import json as json_mod

        body: Dict[str, Any] = {}
        if config.webhook_url:
            body["webhook_url"] = config.webhook_url
        if config.subscriptions:
            try:
                body["subscriptions"] = json_mod.loads(config.subscriptions)
            except (json_mod.JSONDecodeError, TypeError):
                body["subscriptions"] = config.subscriptions
        return await self._make_request(
            "PUT",
            f"/webhook-subscriptions/{config.webhook_id}",
            credentials.api_key,
            json_body=body,
            action_name="update_webhook",
        )

    async def _handle_delete_webhook(
        self, config: AffinityDeleteWebhookConfig, credentials
    ):
        return await self._make_request(
            "DELETE",
            f"/webhook-subscriptions/{config.webhook_id}",
            credentials.api_key,
            action_name="delete_webhook",
        )

    # -------------------------------------------------------------------------
    # Files Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_files(self, config: AffinityListFilesConfig, credentials):
        params = {
            "person_id": config.person_id,
            "organization_id": config.organization_id,
            "opportunity_id": config.opportunity_id,
        }
        return await self._make_request(
            "GET",
            "/files",
            credentials.api_key,
            params=params,
            action_name="list_files",
        )

    async def _handle_get_file(self, config: AffinityGetFileConfig, credentials):
        return await self._make_request(
            "GET",
            f"/files/{config.file_id}",
            credentials.api_key,
            action_name="get_file_by_id",
        )

    async def _handle_download_file(
        self, config: AffinityDownloadFileConfig, credentials
    ):
        return await self._make_request(
            "GET",
            f"/files/{config.file_id}/download",
            credentials.api_key,
            action_name="download_file",
        )

    async def _handle_upload_file(self, config: AffinityUploadFileConfig, credentials):
        """Resolve the file input to bytes then POST as multipart."""
        from nodes.core.media_resolver import resolve_media_input

        start_time = time.time()
        encoded = base64.b64encode(f":{credentials.api_key}".encode()).decode()
        headers_auth = {"Authorization": f"Basic {encoded}"}

        resolved = await resolve_media_input(
            config.file_url, default_mime="application/octet-stream"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                files_payload = {
                    "file": (config.file_name, resolved.data, resolved.mime_type)
                }
                data_payload: Dict[str, Any] = {}
                if config.person_id is not None:
                    data_payload["person_id"] = config.person_id
                if config.organization_id is not None:
                    data_payload["organization_id"] = config.organization_id
                if config.opportunity_id is not None:
                    data_payload["opportunity_id"] = config.opportunity_id

                response = await client.post(
                    f"{AFFINITY_API_BASE}/files",
                    headers=headers_auth,
                    files=files_payload,
                    data=data_payload,
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    return {
                        "status": "error",
                        "action": "upload_file",
                        "error": response.text,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                try:
                    data: Dict[str, Any] = response.json()
                except Exception:
                    data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": "upload_file",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": "upload_file",
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[AffinityNode] upload_file failed: {e}")
                return {
                    "status": "error",
                    "action": "upload_file",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # -------------------------------------------------------------------------
    # v2 Companies Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_companies_v2(
        self, config: AffinityListCompaniesV2Config, credentials
    ):
        params = {"cursor": config.cursor, "limit": config.limit}
        return await self._make_request(
            "GET",
            "/v2/companies",
            credentials.api_key,
            params=params,
            action_name="list_companies",
        )

    async def _handle_get_company_v2(
        self, config: AffinityGetCompanyV2Config, credentials
    ):
        return await self._make_request(
            "GET",
            f"/v2/companies/{config.company_id}",
            credentials.api_key,
            action_name="get_company_by_id",
        )

    async def _handle_list_company_fields_v2(
        self, config: AffinityListCompanyFieldsV2Config, credentials
    ):
        return await self._make_request(
            "GET",
            f"/v2/companies/{config.company_id}/fields",
            credentials.api_key,
            action_name="list_company_fields",
        )

    # -------------------------------------------------------------------------
    # v2 List Entry Fields Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_list_fields_v2(
        self, config: AffinityListListFieldsV2Config, credentials
    ):
        return await self._make_request(
            "GET",
            f"/v2/lists/{config.list_id}/fields",
            credentials.api_key,
            action_name="list_list_fields",
        )

    async def _handle_get_list_entry_fields_v2(
        self, config: AffinityGetListEntryFieldsV2Config, credentials
    ):
        return await self._make_request(
            "GET",
            f"/v2/lists/{config.list_id}/list-entries/{config.entry_id}/fields",
            credentials.api_key,
            action_name="get_list_entry_fields",
        )

    async def _handle_update_list_entry_fields_v2(
        self, config: AffinityUpdateListEntryFieldsV2Config, credentials
    ):
        import json as json_mod

        try:
            fields = json_mod.loads(config.fields)
        except (json_mod.JSONDecodeError, TypeError):
            fields = config.fields
        body: Dict[str, Any] = {"fields": fields}
        return await self._make_request(
            "PATCH",
            f"/v2/lists/{config.list_id}/list-entries/{config.entry_id}/fields",
            credentials.api_key,
            json_body=body,
            action_name="update_list_entry_fields",
        )
