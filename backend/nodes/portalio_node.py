"""Portal.io public API: proposals, contacts and catalog with HMAC authentication.

Contract: https://docs.portal.io/openapi.json (1.0).
Signing: https://docs.portal.io/authentication/signing-requests
Keys are pasted after the provider's exchange; no password is stored or exchanged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from email.utils import formatdate
from typing import Annotated, Literal, Union
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


class PortalioApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Portal.io API Keys",
        json_schema_extra={
            "x-credential-url": "https://docs.portal.io/authentication/overview",
            "x-credential-instructions": "Get an application key and secret from your Portal.io representative. Exchange your Portal.io login for a User API Key using the provider's quickstart, then paste all three keys here. Sandbox and production keys are separate; production access requires Portal.io approval.",
        },
    )
    credential_type: Literal["portalio_api_key"] = Field(
        "portalio_api_key", json_schema_extra={"ui:hidden": True}
    )
    application_key: str = Field(
        ...,
        title="Application Key",
        min_length=1,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    secret_key: str = Field(
        ...,
        title="Secret Key",
        min_length=1,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    user_api_key: str = Field(
        ...,
        title="User API Key",
        min_length=1,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    environment: Literal["production", "sandbox"] = Field(
        "production", title="Environment"
    )

    @field_validator("application_key", "secret_key", "user_api_key")
    @classmethod
    def ascii_key(cls, value):
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortalioListProposalsConfig(_Input):
    """Returns the proposals for the current account. Supports filtering by status, contact, modified date, search text, and archive state, along with sorting and pagination."""

    operation: Literal["list_proposals"] = Field(
        "list_proposals", title="List Proposals", json_schema_extra={"ui:hidden": True}
    )
    search_text: str | None = Field(
        None,
        title="Search Text",
        description="Search proposal by this text",
        max_length=1000,
    )
    statuses: list[
        Literal[
            "Draft",
            "Submitted",
            "ViewedByClient",
            "Accepted",
            "Declined",
            "Delayed",
            "Completed",
            "EmailFailed",
            "Expired",
        ]
    ] | None = Field(None, title="Statuses")
    contact_id: int | None = Field(None, title="Contact Id")
    salesperson_id: int | None = Field(
        None,
        title="Salesperson Id",
        description="Filter proposals by salesperson user ID",
    )
    modified_after: datetime | None = Field(
        None, title="Modified After", description="Modified after timestamp in UTC"
    )
    sort_by: Literal[
        "CreatedDate",
        "ModifiedDate",
        "Number",
        "Name",
        "ClientName",
        "Status",
        "LastModifiedByMe",
    ] | None = Field(None, title="Sort By")
    is_archive: bool | None = Field(
        None,
        title="Is Archive",
        description="If true return only archived proposals otherwise return non archive proposals",
    )
    sort_direction: str | None = Field(None, title="Sort Direction", max_length=1000)
    page_number: int = Field(
        1, title="Page Number", description="Page number. Starting from 1", ge=1
    )
    page_size: int = Field(50, title="Page Size", description="Page Size", ge=1, le=100)


class PortalioCreateProposalConfig(_Input):
    """Creates a new proposal for the authenticated account. Supply a salesperson ID from the same account and, optionally, a proposal name. If no name is given, the system assigns a default name using the same logic as the Portal UI. The response includes the full proposal detail, including the new proposal ID, number, status, and financial summary."""

    operation: Literal["create_proposal"] = Field(
        "create_proposal",
        title="Create Proposal",
        json_schema_extra={"ui:hidden": True},
    )
    sales_person_id: int = Field(
        ...,
        title="Sales Person Id",
        description="ID of the salesperson (user) who will own the proposal. Must belong to the current account.",
    )
    name: str | None = Field(
        None,
        title="Name",
        description="Optional name of the proposal.  If omitted, the system will assign a default name.",
        max_length=100000,
    )


class PortalioGetProposalConfig(_Input):
    """Returns detailed information for the specified proposal. The HTTP response also sets the Last-Modified header from the response LastModifiedDate. Item costs are left out when costs are not available to your account, so a null cost does not mean the item has none. A recurring-service item is left out of its area option's total and counted in that option's totalRecurringService instead. When an item has total.isCombinedPrice true, its amount already includes the totals of the items nested under it, and those nested items still report their own amounts."""

    operation: Literal["get_proposal"] = Field(
        "get_proposal", title="Get Proposal", json_schema_extra={"ui:hidden": True}
    )
    proposal_id: int = Field(
        ..., title="Proposal Id", description="Proposal Id.", ge=1, le=2147483647
    )


class PortalioUpdateProposalConfig(_Input):
    """Performs a partial update on an existing proposal. You can update the proposal name, reassign the salesperson, or do both in one request. Both fields are optional, and omitted fields keep their current values. SalesPersonId must reference a user in the same account. The response includes the full updated proposal detail."""

    operation: Literal["update_proposal"] = Field(
        "update_proposal",
        title="Update Proposal",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(
        ...,
        title="Proposal Id",
        description="ID of the proposal to update.  Must belong to the current account.",
        ge=1,
        le=2147483647,
    )
    name: str | None = Field(
        None,
        title="Name",
        description="Optional new name for the proposal. If omitted, the current name is retained.",
        max_length=100000,
    )
    sales_person_id: int | None = Field(
        None,
        title="Sales Person Id",
        description="Optional ID of the new salesperson (user) to assign.  Must belong to the current account.  If omitted, the current salesperson is retained.",
    )


class PortalioUpdateDescriptionConfig(_Input):
    """Updates the client-facing project description of a proposal. This is the description shown on customer-facing proposal documents. The request body accepts a single description string. The response includes the full updated proposal detail."""

    operation: Literal["update_description"] = Field(
        "update_description",
        title="Update Description",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(
        ..., title="Proposal Id", description="Proposal Id.", ge=1, le=2147483647
    )
    description: str = Field(
        "", title="Description", description="Description.", max_length=100000
    )


class PortalioUpdateInternalNotesConfig(_Input):
    """Updates the internal installer notes (installer project description) of a proposal. These notes are visible only to the dealer's team and do not appear on client-facing documents. The request body accepts a single internal notes string. The response includes the full updated proposal detail."""

    operation: Literal["update_internal_notes"] = Field(
        "update_internal_notes",
        title="Update Internal Notes",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(..., title="Proposal Id", ge=1, le=2147483647)
    internal_notes: str = Field(
        "",
        title="Internal Notes",
        description="New internal notes (installer project description) to save on the proposal.",
        max_length=100000,
    )


class PortalioGetChangeOrderConfig(_Input):
    """Returns detailed information for the specified change order. The HTTP response also sets the Last-Modified header from the response LastModifiedDate. Item costs are left out when costs are not available to your account, so a null cost does not mean the item has none. A recurring-service item is left out of its area option's total and counted in that option's totalRecurringService instead. When an item has total.isCombinedPrice true, its amount already includes the totals of the items nested under it, and those nested items still report their own amounts."""

    operation: Literal["get_change_order"] = Field(
        "get_change_order",
        title="Get Change Order",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(
        ..., title="Proposal Id", description="Proposal Id.", ge=1, le=2147483647
    )
    change_order_id: int = Field(
        ...,
        title="Change Order Id",
        description="Change Order Id.",
        ge=1,
        le=2147483647,
    )


class PortalioListChangeOrdersConfig(_Input):
    """Returns the change orders for the specified proposal, including customer details, total, status, and created and modified dates."""

    operation: Literal["list_change_orders"] = Field(
        "list_change_orders",
        title="List Change Orders",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(
        ..., title="Proposal Id", description="Proposal Id.", ge=1, le=2147483647
    )


class PortalioAddAreaConfig(_Input):
    """Creates a new area (room) within a proposal. The area name must be unique within the proposal. The system automatically creates one default option in 'Draft' status under the new area. The response includes the full updated proposal detail, including the new area and its default option."""

    operation: Literal["add_area"] = Field(
        "add_area", title="Add Area", json_schema_extra={"ui:hidden": True}
    )
    proposal_id: int = Field(
        ...,
        title="Proposal Id",
        description="Unique ID of the proposal (not the proposal number).",
        ge=1,
        le=2147483647,
    )
    name: str = Field(
        ...,
        title="Name",
        description="Name of the area to create.",
        max_length=100000,
        min_length=1,
    )


class PortalioAddAreaOptionConfig(_Input):
    """Creates a new option within an existing area. Each area supports a maximum of three options. Client description and internal installer notes are optional at creation time. The new option is created with 'Draft' status. The response includes the full updated proposal detail."""

    operation: Literal["add_area_option"] = Field(
        "add_area_option",
        title="Add Area Option",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(
        ...,
        title="Proposal Id",
        description="Unique ID of the proposal (not the proposal number).",
        ge=1,
        le=2147483647,
    )
    area_id: int = Field(
        ...,
        title="Area Id",
        description="Unique ID of the area within the proposal where the option will be created. The area must exist for the given proposal.",
        ge=1,
        le=2147483647,
    )
    client_description: str | None = Field(
        None,
        title="Client Description",
        description="(Optional) Client‑facing description to show to customers. Keep concise and user-focused, e.g. 'Premium Installation Package'.",
        max_length=100000,
    )
    internal_notes: str | None = Field(
        None,
        title="Internal Notes",
        description="(Optional) Internal notes for installers or administrators (installer description). Not shown to clients; use for technical details, special instructions, or compatibility notes.",
        max_length=100000,
    )


class PortalioAssignContactConfig(_Input):
    """Assigns an existing contact (person/client) to a proposal. The proposal and contact must belong to the same account. If the contact has a single primary location, that location is automatically assigned to the proposal as well. Assigning a contact may trigger tax recalculations based on the contact's location."""

    operation: Literal["assign_contact"] = Field(
        "assign_contact", title="Assign Contact", json_schema_extra={"ui:hidden": True}
    )
    proposal_id: int = Field(
        ..., title="Proposal Id", description="Proposal Id.", ge=1, le=2147483647
    )
    contact_id: int = Field(
        ..., title="Contact Id", description="Contact Id.", ge=1, le=2147483647
    )


class PortalioAssignLocationConfig(_Input):
    """Assigns a location to a proposal that already has a contact assigned. The location must belong to the proposal's assigned contact and to the same account. Assigning a location triggers tax recalculations for the proposal. The response includes the full updated proposal detail."""

    operation: Literal["assign_location"] = Field(
        "assign_location",
        title="Assign Location",
        json_schema_extra={"ui:hidden": True},
    )
    proposal_id: int = Field(
        ...,
        title="Proposal Id",
        description="ID of the proposal to update.  Must belong to the current account.",
        ge=1,
        le=2147483647,
    )
    location_id: int = Field(
        ...,
        title="Location Id",
        description="ID of the location to assign to the proposal’s existing person.  Must belong to the current account.",
        ge=1,
        le=2147483647,
    )


class PortalioListContactsConfig(_Input):
    """Returns a paged list of contacts for the current account. Supports search, contact type filtering, sorting, and pagination. Pagination defaults to PageNumber 1 and PageSize 10 when values are missing or less than or equal to 0."""

    operation: Literal["list_contacts"] = Field(
        "list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True}
    )
    search_text: str | None = Field(
        None, title="Search Text", description="Search text", max_length=1000
    )
    contact_types: list[Literal["Person", "Company"]] | None = Field(
        None, title="Contact Types", description="Contact Types."
    )
    sort_by: Literal[
        "ModifiedDate",
        "CreatedDate",
        "FirstName",
        "LastName",
        "LastActive",
        "LastActiveByMe",
    ] | None = Field(None, title="Sort By")
    sort_direction: str | None = Field(None, title="Sort Direction", max_length=1000)
    page_number: int = Field(
        1, title="Page Number", description="Page number. Starting from 1", ge=1
    )
    page_size: int = Field(50, title="Page Size", description="Page Size", ge=1, le=100)


class PortalioCreateContactConfig(_Input):
    """Creates a contact in the current account. PartyType, ContactType, and FirstName are required. CompanyName is also required when PartyType is Company."""

    operation: Literal["create_contact"] = Field(
        "create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True}
    )
    party_type: Literal["Person", "Company"] = Field(..., title="Party Type")
    contact_type: Literal["Client", "Employee", "Contractor", "Other"] = Field(
        ..., title="Contact Type"
    )
    first_name: str = Field(
        ...,
        title="First Name",
        description="First Name (Maximum character length is 100)",
        max_length=100,
        min_length=1,
    )
    last_name: str | None = Field(
        None,
        title="Last Name",
        description="Last Name (Maximum character length is 50)",
        max_length=50,
    )
    company_name: str | None = Field(
        None,
        title="Company Name",
        description="Company Name (Maximum character length is 100)",
        max_length=100,
    )
    contact_email: str | None = Field(
        None,
        title="Contact Email",
        description="Email (Maximum character length is 256)",
        max_length=256,
    )
    contact_email_cc: str | None = Field(
        None,
        title="Contact Email Cc",
        description="Additioanl email(s) copied when a proposal is submitted",
        max_length=100000,
    )
    contact_phone: str | None = Field(
        None,
        title="Contact Phone",
        description="Contact Phone (Maximum character length is 30)",
        max_length=30,
    )
    notes: str | None = Field(None, title="Notes", max_length=100000)

    @model_validator(mode="after")
    def company_name_required(self):
        if self.party_type == "Company" and not self.company_name:
            raise ValueError("Company Name is required for a Company contact")
        return self


class PortalioGetContactConfig(_Input):
    """Returns the contact details for the specified person. PrimaryLocation and BillingLocation are included when available. When IncludeCounts is true, the response also includes proposal and payment counts for the contact."""

    operation: Literal["get_contact"] = Field(
        "get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True}
    )
    person_id: int = Field(
        ..., title="Person Id", description="Person Id.", ge=1, le=2147483647
    )
    include_counts: bool | None = Field(None, title="Include Counts")


class PortalioListContactLocationsConfig(_Input):
    """Returns the contact's locations. Results are ordered with the primary location first, then the billing location, then the most recently modified locations. Pagination defaults to PageNumber 1 and PageSize 10. When PageNumber is less than or equal to 0, all matching locations are returned."""

    operation: Literal["list_contact_locations"] = Field(
        "list_contact_locations",
        title="List Contact Locations",
        json_schema_extra={"ui:hidden": True},
    )
    contact_id: int = Field(..., title="Contact Id", ge=1, le=2147483647)
    page_number: int = Field(1, title="Page Number", ge=1)
    page_size: int = Field(50, title="Page Size", ge=1, le=100)


class PortalioCreateContactLocationConfig(_Input):
    """Adds a location to the specified contact. Street is required. When Country is provided, State is also required. Use IsPrimary to make the new location the primary location and IsBilling to make it the billing location."""

    operation: Literal["create_contact_location"] = Field(
        "create_contact_location",
        title="Create Contact Location",
        json_schema_extra={"ui:hidden": True},
    )
    contact_id: int = Field(..., title="Contact Id", ge=1, le=2147483647)
    contact_first_name: str | None = Field(
        None,
        title="Contact First Name",
        description="Contact First Name (Maximum character length is 50)",
        max_length=50,
    )
    contact_last_name: str | None = Field(
        None,
        title="Contact Last Name",
        description="Contact Last Name (Maximum character length is 50)",
        max_length=50,
    )
    contact_phone_number: str | None = Field(
        None,
        title="Contact Phone Number",
        description="Contact Phone Number (Maximum character length is 50)",
        max_length=50,
    )
    contact_email: str | None = Field(
        None,
        title="Contact Email",
        description="Contact Email (Maximum character length is 100)",
        max_length=100,
    )
    street: str = Field(
        ...,
        title="Street",
        description="Street (Maximum character length is 100)",
        max_length=100,
        min_length=1,
    )
    suite: str | None = Field(
        None,
        title="Suite",
        description="Suite (Maximum character length is 100)",
        max_length=100,
    )
    city: str | None = Field(
        None,
        title="City",
        description="City (Maximum character length is 50)",
        max_length=50,
    )
    postal_code: str | None = Field(
        None,
        title="Postal Code",
        description="Postal Code (Maximum character length is 20)",
        max_length=20,
    )
    state: str | None = Field(
        None,
        title="State",
        description="State (Maximum character length is 256)",
        max_length=256,
    )
    country: str | None = Field(
        None,
        title="Country",
        description="Country (Maximum character length is 256)",
        max_length=256,
    )
    is_primary: bool | None = Field(None, title="Is Primary")
    is_billing: bool | None = Field(None, title="Is Billing")

    @model_validator(mode="after")
    def country_needs_state(self):
        if self.country and not self.state:
            raise ValueError("State is required when Country is supplied")
        return self


class PortalioListUsersConfig(_Input):
    """Returns a list of all active users within the authenticated caller's account. The response includes basic, non-sensitive user details: user ID, first name, last name, email address, and the user's permission group. This is a read-only endpoint intended for integrations that need to look up user IDs before assigning them as salespersons on proposals or for syncing user data with external systems."""

    operation: Literal["list_users"] = Field(
        "list_users", title="List Users", json_schema_extra={"ui:hidden": True}
    )


class PortalioSearchCatalogConfig(_Input):
    """Searches the catalog using the provided category, brand, supplier, industry, stock, favorite, price, and item type filters. CategoryId and CategoryIds are mutually exclusive, and ParentCategoryId and ParentCategoryIds are mutually exclusive. If SearchText is omitted it is treated as an empty string. ItemType defaults to Part."""

    operation: Literal["search_catalog"] = Field(
        "search_catalog", title="Search Catalog", json_schema_extra={"ui:hidden": True}
    )
    search_text: str | None = Field(None, title="Search Text", max_length=1000)
    parent_category_id: int | None = Field(None, title="Parent Category Id")
    parent_category_ids: list[int] | None = Field(None, title="Parent Category Ids")
    category_id: int | None = Field(None, title="Category Id")
    category_ids: list[int] | None = Field(None, title="Category Ids")
    brands: list[str] | None = Field(None, title="Brands")
    suppliers: list[str] | None = Field(None, title="Suppliers")
    industries: list[int] | None = Field(None, title="Industries")
    is_in_stock: bool | None = Field(None, title="Is In Stock")
    is_favorite: bool | None = Field(None, title="Is Favorite")
    is_authorized: bool | None = Field(None, title="Is Authorized")
    is_discontinued: bool | None = Field(None, title="Is Discontinued")
    is_industrial_favorite: bool | None = Field(None, title="Is Industrial Favorite")
    min_msrp: float | None = Field(
        None,
        title="Min Msrp",
        description="Filter for products with an MSRP (of the users current country currency. If it doesn't exist then USD MSRP is used.) greater than this amount.",
    )
    max_msrp: float | None = Field(
        None,
        title="Max Msrp",
        description="Filter for products with an MSRP (of the users current country currency. If it doesn't exist then USD MSRP is used.) less than this amount.",
    )
    page_number: int = Field(0, title="Page Number", ge=0)
    page_size: int = Field(
        50, title="Page Size", description="Limit the number of results", ge=1, le=100
    )
    include_image_url: bool | None = Field(None, title="Include Image Url")
    item_type: str | None = Field(None, title="Item Type", max_length=1000)
    in_use_only: bool | None = Field(None, title="In Use Only")

    @model_validator(mode="after")
    def exclusive_category_filters(self):
        if self.category_id is not None and self.category_ids is not None:
            raise ValueError("Choose Category ID or Category IDs")
        if self.parent_category_id is not None and self.parent_category_ids is not None:
            raise ValueError("Choose Parent Category ID or Parent Category IDs")
        return self


class PortalioListCategoriesConfig(_Input):
    """Returns the catalog category hierarchy grouped by industry, including category image URLs when available."""

    operation: Literal["list_categories"] = Field(
        "list_categories",
        title="List Categories",
        json_schema_extra={"ui:hidden": True},
    )


class PortalioGetCatalogItemConfig(_Input):
    """Returns details for the requested catalog item. When ItemType is Labor or CustomItem, the item is returned from the current account's library; otherwise a standard catalog item is returned. ExtendedDetails adds extra information to standard catalog item responses."""

    operation: Literal["get_catalog_item"] = Field(
        "get_catalog_item",
        title="Get Catalog Item",
        json_schema_extra={"ui:hidden": True},
    )
    item_id: int = Field(
        ..., title="Item Id", description="Item Id", ge=1, le=2147483647
    )
    extended_details: bool | None = Field(
        None,
        title="Extended Details",
        description="Provides additional details like full description, specs, linked resources",
    )
    item_type: str | None = Field(None, title="Item Type", max_length=1000)


PortalioOperation = Annotated[
    Union[
        PortalioListProposalsConfig,
        PortalioCreateProposalConfig,
        PortalioGetProposalConfig,
        PortalioUpdateProposalConfig,
        PortalioUpdateDescriptionConfig,
        PortalioUpdateInternalNotesConfig,
        PortalioGetChangeOrderConfig,
        PortalioListChangeOrdersConfig,
        PortalioAddAreaConfig,
        PortalioAddAreaOptionConfig,
        PortalioAssignContactConfig,
        PortalioAssignLocationConfig,
        PortalioListContactsConfig,
        PortalioCreateContactConfig,
        PortalioGetContactConfig,
        PortalioListContactLocationsConfig,
        PortalioCreateContactLocationConfig,
        PortalioListUsersConfig,
        PortalioSearchCatalogConfig,
        PortalioListCategoriesConfig,
        PortalioGetCatalogItemConfig,
    ],
    Field(discriminator="operation"),
]


class PortalioConfig(NodeConfig[PortalioOperation, PortalioApiKeyCredential]):
    pass


ROUTES = {
    "list_proposals": (
        "GET",
        "/public/proposals",
        {
            "search_text": ("SearchText", "query"),
            "statuses": ("Statuses", "query"),
            "contact_id": ("ContactId", "query"),
            "salesperson_id": ("SalespersonId", "query"),
            "modified_after": ("ModifiedAfter", "query"),
            "sort_by": ("SortBy", "query"),
            "is_archive": ("IsArchive", "query"),
            "sort_direction": ("SortDirection", "query"),
            "page_number": ("PageNumber", "query"),
            "page_size": ("PageSize", "query"),
        },
        200,
    ),
    "create_proposal": (
        "POST",
        "/public/proposals",
        {"sales_person_id": ("SalesPersonId", "body"), "name": ("Name", "body")},
        200,
    ),
    "get_proposal": (
        "GET",
        "/public/proposals/{ProposalId}",
        {"proposal_id": ("ProposalId", "path")},
        200,
    ),
    "update_proposal": (
        "POST",
        "/public/proposals/{ProposalId}",
        {
            "proposal_id": ("ProposalId", "path"),
            "name": ("Name", "body"),
            "sales_person_id": ("SalesPersonId", "body"),
        },
        200,
    ),
    "update_description": (
        "POST",
        "/public/proposals/{ProposalId}/description",
        {"proposal_id": ("ProposalId", "path"), "description": ("Description", "body")},
        200,
    ),
    "update_internal_notes": (
        "POST",
        "/public/proposals/{ProposalId}/internalnotes",
        {
            "proposal_id": ("ProposalId", "path"),
            "internal_notes": ("InternalNotes", "body"),
        },
        200,
    ),
    "get_change_order": (
        "GET",
        "/public/proposals/{ProposalId}/changeorders/{ChangeOrderId}",
        {
            "proposal_id": ("ProposalId", "path"),
            "change_order_id": ("ChangeOrderId", "path"),
        },
        200,
    ),
    "list_change_orders": (
        "GET",
        "/public/proposals/{ProposalId}/changeorders",
        {"proposal_id": ("ProposalId", "path")},
        200,
    ),
    "add_area": (
        "POST",
        "/public/proposals/{ProposalId}/area",
        {"proposal_id": ("ProposalId", "path"), "name": ("Name", "body")},
        200,
    ),
    "add_area_option": (
        "POST",
        "/public/proposals/{ProposalId}/area/{AreaId}/option",
        {
            "proposal_id": ("ProposalId", "path"),
            "area_id": ("AreaId", "path"),
            "client_description": ("ClientDescription", "body"),
            "internal_notes": ("InternalNotes", "body"),
        },
        200,
    ),
    "assign_contact": (
        "POST",
        "/public/proposals/{ProposalId}/contact/{ContactId}",
        {"proposal_id": ("ProposalId", "path"), "contact_id": ("ContactId", "path")},
        204,
    ),
    "assign_location": (
        "POST",
        "/public/proposals/{ProposalId}/location/{LocationId}",
        {"proposal_id": ("ProposalId", "path"), "location_id": ("LocationId", "path")},
        200,
    ),
    "list_contacts": (
        "GET",
        "/public/people",
        {
            "search_text": ("SearchText", "query"),
            "contact_types": ("ContactTypes", "query"),
            "sort_by": ("SortBy", "query"),
            "sort_direction": ("SortDirection", "query"),
            "page_number": ("PageNumber", "query"),
            "page_size": ("PageSize", "query"),
        },
        200,
    ),
    "create_contact": (
        "POST",
        "/public/people",
        {
            "party_type": ("PartyType", "body"),
            "contact_type": ("ContactType", "body"),
            "first_name": ("FirstName", "body"),
            "last_name": ("LastName", "body"),
            "company_name": ("CompanyName", "body"),
            "contact_email": ("ContactEmail", "body"),
            "contact_email_cc": ("ContactEmailCC", "body"),
            "contact_phone": ("ContactPhone", "body"),
            "notes": ("Notes", "body"),
        },
        200,
    ),
    "get_contact": (
        "GET",
        "/public/people/{PersonId}",
        {
            "person_id": ("PersonId", "path"),
            "include_counts": ("IncludeCounts", "query"),
        },
        200,
    ),
    "list_contact_locations": (
        "GET",
        "/public/people/{ContactId}/location",
        {
            "contact_id": ("ContactId", "path"),
            "page_number": ("PageNumber", "query"),
            "page_size": ("PageSize", "query"),
        },
        200,
    ),
    "create_contact_location": (
        "POST",
        "/public/people/{ContactId}/location",
        {
            "contact_id": ("ContactId", "path"),
            "contact_first_name": ("ContactFirstName", "body"),
            "contact_last_name": ("ContactLastName", "body"),
            "contact_phone_number": ("ContactPhoneNumber", "body"),
            "contact_email": ("ContactEmail", "body"),
            "street": ("Street", "body"),
            "suite": ("Suite", "body"),
            "city": ("City", "body"),
            "postal_code": ("PostalCode", "body"),
            "state": ("State", "body"),
            "country": ("Country", "body"),
            "is_primary": ("IsPrimary", "body"),
            "is_billing": ("IsBilling", "body"),
        },
        200,
    ),
    "list_users": ("GET", "/public/users", {}, 200),
    "search_catalog": (
        "GET",
        "/public/catalog",
        {
            "search_text": ("SearchText", "query"),
            "parent_category_id": ("ParentCategoryId", "query"),
            "parent_category_ids": ("ParentCategoryIds", "query"),
            "category_id": ("CategoryId", "query"),
            "category_ids": ("CategoryIds", "query"),
            "brands": ("Brands", "query"),
            "suppliers": ("Suppliers", "query"),
            "industries": ("Industries", "query"),
            "is_in_stock": ("IsInStock", "query"),
            "is_favorite": ("IsFavorite", "query"),
            "is_authorized": ("IsAuthorized", "query"),
            "is_discontinued": ("IsDiscontinued", "query"),
            "is_industrial_favorite": ("IsIndustrialFavorite", "query"),
            "min_msrp": ("MinMsrp", "query"),
            "max_msrp": ("MaxMsrp", "query"),
            "page_number": ("PageNumber", "query"),
            "page_size": ("PageSize", "query"),
            "include_image_url": ("IncludeImageUrl", "query"),
            "item_type": ("ItemType", "query"),
            "in_use_only": ("InUseOnly", "query"),
        },
        200,
    ),
    "list_categories": ("GET", "/public/catalog/categories", {}, 200),
    "get_catalog_item": (
        "GET",
        "/public/catalog/{ItemId}",
        {
            "item_id": ("ItemId", "path"),
            "extended_details": ("ExtendedDetails", "query"),
            "item_type": ("ItemType", "query"),
        },
        200,
    ),
}


def signed_headers(method, url, credential, content_type=None, timestamp=None):
    """Provider's canonical string excludes query and body; secret stays raw ASCII."""
    timestamp = timestamp or formatdate(usegmt=True)
    canonical = (
        method
        + url
        + ((content_type or "") if method != "GET" else "")
        + timestamp
        + credential.user_api_key
    )
    signature = base64.b64encode(
        hmac.new(
            credential.secret_key.encode("ascii"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    headers = {
        "Accept": "application/json",
        "X-MSS-API-APPID": credential.application_key,
        "X-MSS-API-USERKEY": credential.user_api_key,
        "X-MSS-CUSTOM-DATE": timestamp,
        "X-MSS-SIGNATURE": signature,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _wire(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class PortalioNode(WorkflowNode):
    integration_type = "automation-portalio"
    connection_evidence = ConnectionEvidence(
        operation="list_users",
        noun="Portal.io users",
        label_keys=("email", "firstName", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return PortalioConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect Portal.io API keys")
        method, path, fields, expected = ROUTES[config.operation]
        query, body = [], []
        for field, value in config.model_dump(mode="json", exclude_none=True).items():
            if field == "operation":
                continue
            wire, location = fields[field]
            if location == "path":
                path = path.replace("{" + wire + "}", str(value))
            else:
                target = query if location == "query" else body
                target.extend(
                    (wire, _wire(item))
                    for item in (value if isinstance(value, list) else [value])
                )
        base = (
            "https://sandbox.api.portal.io"
            if credential.environment == "sandbox"
            else "https://api.portal.io"
        )
        url = base + path
        content_type = "application/x-www-form-urlencoded" if method != "GET" else None
        headers = signed_headers(method, url, credential, content_type)
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                url,
                params=query,
                headers=headers,
                content=urlencode(body).encode() if content_type else None,
            )
        if response.status_code != expected:
            message = response.text[:2000]
            for key in (
                credential.secret_key,
                credential.user_api_key,
                credential.application_key,
            ):
                message = message.replace(key, "[redacted]")
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message or "Portal.io rejected the request",
            }
        if expected == 204:
            return {"status": "success", "http_status": 204, "data": None}
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Expected Portal.io JSON object or list")
        if isinstance(payload, dict) and (
            (payload.get("responseStatus") or {}).get("errorCode")
            or payload.get("error")
        ):
            return {
                "status": "error",
                "error": (payload.get("responseStatus") or {}).get("message")
                or str(payload["error"]),
            }
        return {"status": "success", "data": payload}
