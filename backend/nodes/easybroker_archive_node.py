"""EasyBroker API v1 operations and scheduled account-change triggers.

Contract: https://api.easybroker.com/docs, version 1.0. API keys belong to
account administrators. Writes are sent once; ambiguous failures are not retried.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit, parse_qs

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.easybroker.com/v1"
NODE_TYPE = "automation-easybroker-archive"
FAMILY = "easybroker_archive_api_key"


class EasyBrokerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="EasyBroker API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.easybroker.com/docs/api-de-easybroker",
            "x-credential-instructions": "As an account administrator, copy your API key from EasyBroker General Settings and paste it here. NoClick sends it in X-Authorization to api.easybroker.com. Connecting reads your account's contacts.",
        },
    )
    credential_type: Literal["easybroker_archive_api_key"] = Field(
        FAMILY, json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EasyBrokerListCollaborationsConfig(Input):
    "Returns a list of collaborations from your organization."
    operation: Literal["list_collaborations"] = Field(
        "list_collaborations",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all collaborations",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 50)", le=50, ge=1
    )


class EasyBrokerListContactRequestsConfig(Input):
    "Returns a list of the contact requests in a given period or for a specific property, if no parameters are provided all the contact requests will be returned"
    operation: Literal["list_contact_requests"] = Field(
        "list_contact_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all contact requests",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 50)", le=50, ge=1
    )
    happened_after: Optional[datetime] = Field(
        None, description="Contact requests created after the given date"
    )
    happened_before: Optional[datetime] = Field(
        None, description="Contact requests created before the given date"
    )
    property_id: Optional[str] = Field(
        None, description="The ID of a property to retrieve the contact requests for"
    )


class ContactRequestBody(Input):
    name: Optional[str] = Field(
        None, description="Required if the request does not provide a property_id"
    )
    phone: Optional[str] = Field(
        None,
        description="Required if the request does not provide neither a property id nor an email",
    )
    email: Optional[str] = Field(
        None,
        description="Required if the request does not provide neither a property id nor a phone number",
    )
    property_id: Optional[str] = Field(
        None,
        description="If the request provides this parameter, it should also provide a name, email or phone number",
    )
    message: Optional[str] = Field(
        None, description="Required if the request does not provide a property_id"
    )
    source: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def lead_details(self):
        if self.property_id:
            if not (self.name or self.phone or self.email):
                raise ValueError(
                    "A property contact request needs a name, email or phone"
                )
        elif not (self.name and self.message and (self.email or self.phone)):
            raise ValueError(
                "Without a property, provide name, message and email or phone"
            )
        return self


class EasyBrokerCreateContactRequestConfig(Input):
    "Creates or updates a new lead in EasyBroker that is interested in the provided property."
    operation: Literal["create_contact_request"] = Field(
        "create_contact_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create a contact request",
            "x-is-trigger": False,
            "x-method-kind": "write",
        },
    )
    body: ContactRequestBody = Field(
        ...,
        title="Request body",
        description="EasyBroker fields as documented; updates to image arrays replace existing images.",
    )


class EasyBrokerListContactsConfig(Input):
    "Returns a list of contacts from your organization."
    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all contacts",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 50)", le=50, ge=1
    )
    search_updated_after: Optional[datetime] = Field(
        None, description="Retrieve contacts updated after the given time."
    )
    search_updated_before: Optional[datetime] = Field(
        None, description="Retrieve contacts updated before the given time."
    )
    search_created_after: Optional[datetime] = Field(
        None, description="Retrieve contacts created after the given time."
    )
    search_created_before: Optional[datetime] = Field(
        None, description="Retrieve contacts created before the given time."
    )
    search_last_activity_after: Optional[datetime] = Field(
        None,
        description="Retrieve contacts whose last activity was after the given time.",
    )
    search_last_activity_before: Optional[datetime] = Field(
        None,
        description="Retrieve contacts whose last activity was before the given time. Contacts without activity are excluded.",
    )
    search_statuses: Optional[list[str]] = Field(
        None,
        description="This parameter allows you to filter contacts with the selected statuses. You must provide one of your account's status names exactly as they are shown on EasyBroker.",
    )
    search_probabilities: Optional[list[Literal["high", "medium", "low"]]] = Field(
        None,
        description="This parameter allows you to filter contacts with the selected probabilities",
    )
    search_tag: Optional[str] = Field(
        None,
        description="This parameter allows you to filter listings from one specific tag.",
    )
    search_email: Optional[str] = Field(
        None,
        description="This parameter allows you to filter contacts based on the assigned agent's email.",
    )
    search_offices: Optional[list[str]] = Field(
        None,
        description="This parameter allows you to filter contacts by office names.",
    )
    search_sources: Optional[list[str]] = Field(
        None, description="Retrieve contact listing from multiple sources."
    )


class EasyBrokerGetContactConfig(Input):
    "Returns the detailed information of a contact from your EasyBroker account."
    operation: Literal["get_contact"] = Field(
        "get_contact",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a contact",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    contact_id: int = Field(..., description="The ID of the specified contact")


class ContactEmailBody(Input):
    type: Optional[str] = Field(
        None, description="The contact email type (e.g. Home, Work, Other)."
    )
    email: Optional[str] = Field(None)


class ContactPhoneBody(Input):
    type: Optional[str] = Field(
        None,
        description="The contact phone type (e.g. Home, Work, Mobile, Pager, Home fax, Work fax).",
    )
    phone: Optional[str] = Field(None)


class ContactAddressBody(Input):
    type: Optional[str] = Field(
        None, description="The contact address type (e.g. Home, Work, Other)."
    )
    street: Optional[str] = Field(None)
    city: Optional[str] = Field(None)
    administrative_division: Optional[str] = Field(None)
    country: Optional[str] = Field(
        None, description="Country name (English or Spanish) or two-letter code."
    )
    postal_code: Optional[str] = Field(None)


class ContactBody(Input):
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    title: Optional[str] = Field(None)
    company: Optional[str] = Field(None)
    private_description: Optional[str] = Field(None)
    source: Optional[str] = Field(
        None,
        description="The contact origin name. A new source is created if one with this name doesn't exist.",
    )
    agent: Optional[str] = Field(
        None,
        description="The EasyBroker account email of the agent assigned to the contact.",
    )
    probability: Optional[Literal["low", "medium", "high"]] = Field(
        None, description="Lead probability level."
    )
    status: Optional[str] = Field(
        None,
        description="One of your account's contact status names, exactly as shown on EasyBroker. A name that matches none or several of them returns a 422 error.",
    )
    tags: Optional[list[str]] = Field(
        None, description="Replaces the contact's tag list with this exact set."
    )
    emails: Optional[list[ContactEmailBody]] = Field(
        None,
        description="Replaces the contact's emails with this exact list (existing entries with matching type and email are preserved; missing entries are removed).",
    )
    phones: Optional[list[ContactPhoneBody]] = Field(
        None,
        description="Replaces the contact's phone numbers with this exact list (matching is done by type and digits, ignoring formatting).",
    )
    addresses: Optional[list[ContactAddressBody]] = Field(
        None, description="Replaces the contact's addresses with this exact list."
    )


class EasyBrokerUpdateContactConfig(Input):
    "Updates an existing contact in your EasyBroker account. Only the fields you send are modified. For `emails`, `phones`, `addresses` and `tags`, the value you send fully replaces the current list — matching entries are preserved, missing entries are removed and new entries are appended (order is ignored)."
    operation: Literal["update_contact"] = Field(
        "update_contact",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update a contact",
            "x-is-trigger": False,
            "x-method-kind": "write",
        },
    )
    contact_id: int = Field(..., description="The ID of the specified contact")
    body: ContactBody = Field(
        ...,
        title="Contact changes",
        description="Only supplied fields change. Arrays replace the complete existing list.",
    )

    @model_validator(mode="after")
    def changes_present(self):
        if not self.body.model_fields_set:
            raise ValueError("Provide at least one contact field to update")
        return self


class EasyBrokerListFeaturesConfig(Input):
    "Returns a list of the property features available in your organization's country.\n                         You can also provide a `locale` parameter to define the language you want the name of the features to be in."
    operation: Literal["list_features"] = Field(
        "list_features",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all property features",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 100)", le=100, ge=1
    )
    locale: Optional[Literal["en", "es", "pt"]] = Field(
        None,
        description="The language you want the results to be in. If not provided it defaults to your organization's language.",
    )


class EasyBrokerListListingStatusesConfig(Input):
    "Returns a list of property listing statuses from your organization."
    operation: Literal["list_listing_statuses"] = Field(
        "list_listing_statuses",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all property listing statuses",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 100)", le=100, ge=1
    )
    search_updated_after: Optional[datetime] = Field(
        None,
        description="Retrieve listing statuses for properties updated after the given time.",
    )
    search_updated_before: Optional[datetime] = Field(
        None,
        description="Retrieve listing statuses for properties updated before the given time.",
    )
    search_statuses: Optional[
        list[
            Literal[
                "published",
                "not_published",
                "reserved",
                "sold",
                "rented",
                "suspended",
                "flagged",
                "disapproved",
            ]
        ]
    ] = Field(None)


class EasyBrokerGetLocationsConfig(Input):
    "Retrieve a location name and the children of a given location <neighborhood, city, state>. If no parameter provided, the states from the country registered in your account will be returned. Send `postal_code` instead of `query` to retrieve the city a postal code belongs to together with its neighborhoods mapped to that postal code."
    operation: Literal["get_locations"] = Field(
        "get_locations",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a location",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    query: Optional[str] = Field(None, description="Location to find")
    postal_code: Optional[str] = Field(
        None,
        description="Postal code to find. Returns the city it belongs to with the neighborhoods mapped to that postal code as its localities. Takes precedence over `query`. Some neighborhoods don't have a postal code mapped yet, so a 404 doesn't mean the location doesn't exist: search it by name with `query` instead.",
    )


class EasyBrokerListPropertiesConfig(Input):
    "Returns a list of properties from your organization."
    operation: Literal["list_properties"] = Field(
        "list_properties",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all properties",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 50)", le=50, ge=1
    )
    search_property_types: Optional[list[str]] = Field(
        None,
        description="Property type symbols from the `property_types` endpoint. Names remain accepted for backward compatibility.",
    )
    search_updated_after: Optional[datetime] = Field(None)
    search_updated_before: Optional[datetime] = Field(None)
    search_operation_type: Optional[
        Literal["sale", "rental", "temporary_rental"]
    ] = Field(None)
    search_min_price: Optional[int] = Field(
        None, description="operation_type is required"
    )
    search_max_price: Optional[int] = Field(
        None, description="operation_type is required"
    )
    search_min_bedrooms: Optional[int] = Field(None)
    search_min_bathrooms: Optional[int] = Field(None)
    search_min_parking_spaces: Optional[int] = Field(None)
    search_min_construction_size: Optional[int] = Field(
        None, description="construction size in square meters"
    )
    search_max_construction_size: Optional[int] = Field(
        None, description="construction size in square meters"
    )
    search_min_lot_size: Optional[int] = Field(
        None, description="lot size in square meters"
    )
    search_max_lot_size: Optional[int] = Field(
        None, description="lot size in square meters"
    )
    search_statuses: Optional[
        list[
            Literal[
                "published",
                "not_published",
                "reserved",
                "sold",
                "rented",
                "suspended",
                "flagged",
                "disapproved",
            ]
        ]
    ] = Field(None)
    search_sort_by: Optional[
        list[Literal["updated_at-asc", "updated_at-desc"]]
    ] = Field(None)


class PropertyCommissionBody(Input):
    type: Optional[Literal["amount", "percentage", "months"]] = Field(
        None, description="The month type is only available for rental commission."
    )
    value: Optional[float] = Field(
        None,
        description='Commission value corresponding to the specified type. For commission type "months", valid values are: 0.5, 1, 1.5, 2, 3, 4, 5.',
    )
    currency: Optional[str] = Field(
        None, description='Only applicable for the "amount" type.'
    )


class PropertyOperationSaleOrRentalBody(Input):
    type: Literal["sale", "rental"] = Field(...)
    active: StrictBool = Field(
        ..., description="Indicates whether this operation is active or not."
    )
    amount: float = Field(..., le=100000000000, gt=0)
    currency: str = Field(...)
    unit: Optional[Literal["total", "square_meter", "hectare"]] = Field(
        None, description='Indicates the property price unit. Defaults to "total"'
    )
    commission: Optional[PropertyCommissionBody] = Field(None)
    foreclosure: Optional[StrictBool] = Field(
        None,
        description="Indicates whether the property is up for auction. This option is available only to agencies in Mexico.",
    )
    adjudicated: Optional[StrictBool] = Field(
        None,
        description="Indicates whether the property has been legally awarded to a creditor. This option is available only to agencies in Mexico.",
    )


class TemporaryRentalRateBody(Input):
    type: Literal["daily", "weekly", "monthly"] = Field(...)
    amount: float = Field(..., le=100000000000, gt=0)


class PropertyOperationTemporaryRentalBody(Input):
    type: Literal["temporary_rental"] = Field("temporary_rental")
    active: StrictBool = Field(
        ..., description="Indicates whether this operation is active or not."
    )
    currency: str = Field(...)
    rates: list[TemporaryRentalRateBody] = Field(..., min_length=1)


class PropertyLocationBody(Input):
    name: Optional[str] = Field(
        None,
        description="A location string containing the neighborhood, city and the administrative division where the property is located. It must match a location found through the locations endpoint. The neighborhood is required to publish in Mexico but is not required in other countries or to create or update unpublished properties.",
    )
    street: Optional[str] = Field(
        None, description="The street where the property is located."
    )
    exterior_number: Optional[str] = Field(
        None, description="The property address exterior number."
    )
    interior_number: Optional[str] = Field(
        None, description="The property address interior number."
    )
    cross_street: Optional[str] = Field(
        None, description="The property address cross street."
    )
    postal_code: Optional[str] = Field(
        None, description="The property address postal code."
    )
    latitude: Optional[float] = Field(
        None, description="The latitude where the property is located."
    )
    longitude: Optional[float] = Field(
        None, description="The longitude where the property is located."
    )


class PropertyImageBody(Input):
    title: Optional[str] = Field(None, max_length=60)
    url: str = Field(...)


class PropertyBody(Input):
    property_type: str = Field(
        ...,
        description="The property type symbol returned by the `property_types` endpoint. Names remain accepted for backward compatibility.",
    )
    title: str = Field(..., description="The property listing title.")
    description: str = Field(..., description="The property listing description.")
    status: Literal[
        "published", "sold", "rented", "reserved", "suspended", "not_published"
    ] = Field(..., description="The property status")
    private_description: Optional[str] = Field(
        None, description="A private description visible only to your team."
    )
    operations: list[
        Union[PropertyOperationSaleOrRentalBody, PropertyOperationTemporaryRentalBody]
    ] = Field(...)
    agent: Optional[str] = Field(
        None,
        description="The EasyBroker account email of the agent assigned to the property.",
    )
    show_prices: Optional[StrictBool] = Field(
        None,
        description="An option that allows you to show or hide the EB listing prices.",
    )
    bedrooms: Optional[int] = Field(None, description="The number of bedrooms.")
    bathrooms: Optional[int] = Field(None, description="The number of bathrooms.")
    half_bathrooms: Optional[int] = Field(
        None, description="The number of half bathrooms."
    )
    parking_spaces: Optional[int] = Field(
        None, description="The number of parking spaces."
    )
    age: Optional[
        Union[Optional[int], Literal["under_construction", "new_construction"], str]
    ] = Field(
        None,
        description='One of "under_construction", "new_construction" or the year the property was built. The year may be sent as an integer or a four-digit string.',
    )
    conservation_state: Optional[
        Literal["new", "excellent", "good", "regular", "bad", "to_remodel"]
    ] = Field(
        None,
        description="The condition of the property. Send `null` to leave it unspecified. Not available for building, commercial or land property types; the value is ignored for those.",
    )
    floor: Optional[str] = Field(
        None,
        description="The floor number in which the property is located, useful for apartments. It can be set to a custom value such as 'Penthouse'",
    )
    floors: Optional[int] = Field(
        None, description="The number of floors in the building."
    )
    rental_maintenance_included: Optional[StrictBool] = Field(
        None,
        description="Indicates whether monthly maintenance is included in the rental price. Required when rental is active and maintenance_amount is provided; otherwise it is cleared to `null` when rental is inactive.",
    )
    maintenance_amount: Optional[int] = Field(
        None,
        description="Monthly maintenance amount. When rental is active, rental_maintenance_included must be specified; the amount is required when that field is `false`.",
        le=2147483647,
        ge=1,
    )
    maintenance_currency: Optional[str] = Field(
        None,
        description="Currency code for the maintenance amount. Defaults to the operation currency (rental, sale or temporary rental, in that order) when omitted.",
    )
    internal_id: Optional[str] = Field(
        None,
        description="A unique id used in your organization. It can only contain letters, numbers and a small set of special characters (- _ , . &  /)",
    )
    location: PropertyLocationBody = Field(...)
    tags: Optional[list[str]] = Field(
        None,
        description="An array of strings, each one is a tag that will be associated with the property.",
    )
    features: Optional[list[str]] = Field(
        None,
        description="An array with the names of all the features for this property. You can get the full list of features from the features endpoint.",
    )
    share_commission: Optional[StrictBool] = Field(
        None,
        description="An option to specify whether your agency is willing to share the commission with other agencies in the EasyBroker agency network.",
    )
    collaboration_notes: Optional[str] = Field(
        None, description="Notes on conditions or details for collaborations."
    )
    images: Optional[list[PropertyImageBody]] = Field(
        None,
        description="An array of objects, each one containing an image url and a title. Images are processed asynchronously and might take some time to appear in your listing. The API does not expose processing status; retrieve the property again and check its images array. For an existing listing, this array replaces the existing images. Image requirements: URL must be a valid HTTP/HTTPS URL with file extension (.jpg, .jpeg, .png, .gif, .heic, .webp), maximum 6MB per image, minimum 500px width or height, valid image MIME type, up to 50 images per listing.",
    )
    videos: Optional[list[str]] = Field(
        None,
        description="An array of strings, each one is a youtube video link that will be associated with the property.",
    )
    virtual_tour: Optional[str] = Field(
        None, description="A link to a virtual tour of the property."
    )
    show_exact_location: Optional[StrictBool] = Field(
        None,
        description="Set it to 'true' to show the exact address location and map location or 'false' to hide it.",
    )
    construction_size: Optional[float] = Field(None, description="In square meters")
    lot_size: Optional[float] = Field(None, description="In square meters")
    lot_length: Optional[float] = Field(None, description="In meters")
    lot_width: Optional[float] = Field(None, description="In meters")
    covered_space: Optional[float] = Field(
        None, description="In square meters. Not Available in Mexico."
    )
    uncovered_space: Optional[float] = Field(
        None, description="In square meters. Only available in Mexico and Argentina."
    )
    exclusive: Optional[StrictBool] = Field(
        None,
        description="Indicates whether the listing is exclusive. Set to `null` if not specified.",
    )
    shared_commission_percentage: Optional[float] = Field(
        None,
        description="Indicates the percentage of the agency fee that is shared. At the moment, it can only be set to 50% or `null` if not specified.",
    )


class EasyBrokerCreatePropertyConfig(Input):
    "Creates a new property in your EasyBroker account, which will be published to all your connected apps."
    operation: Literal["create_property"] = Field(
        "create_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create a property",
            "x-is-trigger": False,
            "x-method-kind": "write",
        },
    )
    body: PropertyBody = Field(
        ...,
        title="Request body",
        description="EasyBroker fields as documented; updates to image arrays replace existing images.",
    )


class EasyBrokerGetPropertyConfig(Input):
    "Returns the detailed information of a property from your EasyBroker account."
    operation: Literal["get_property"] = Field(
        "get_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a property",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    property_id: str = Field(
        ..., description="The public or internal ID of the specified property"
    )


class EasyBrokerUpdatePropertyConfig(Input):
    "Updates an existing property in your EasyBroker account."
    operation: Literal["update_property"] = Field(
        "update_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update a property",
            "x-is-trigger": False,
            "x-method-kind": "write",
        },
    )
    property_id: str = Field(
        ..., description="The public or internal ID of the specified property"
    )
    body: PropertyBody = Field(
        ...,
        title="Request body",
        description="EasyBroker fields as documented; updates to image arrays replace existing images.",
    )


class EasyBrokerListPropertyIntegrationsConfig(Input):
    "Returns, for every property in your organization connected to at least one portal, its publication status across all connected portals. Results are paginated by property, so `limit` counts properties rather than portal listings."
    operation: Literal["list_property_integrations"] = Field(
        "list_property_integrations",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List property integrations",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 50)", le=50, ge=1
    )
    search_updated_after: Optional[datetime] = Field(
        None,
        description="Only include properties whose most recently updated integration changed after this time.",
    )
    search_updated_before: Optional[datetime] = Field(
        None,
        description="Only include properties whose most recently updated integration changed before this time.",
    )
    search_integration_partner_symbol: Optional[str] = Field(
        None,
        description="Only include properties connected to this partner. Each property still lists all of its connected portals.",
    )


class EasyBrokerListPropertyTypesConfig(Input):
    "Returns a list of the property types from your organization's country.\n                         You can also provide a `locale` parameter to define the language you want the name of the property types to be in."
    operation: Literal["list_property_types"] = Field(
        "list_property_types",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all property types",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 100)", le=100, ge=1
    )
    locale: Optional[Literal["en", "es", "pt"]] = Field(
        None,
        description="The language you want the results to be in. If not provided it defaults to your organization's language.",
    )


class EasyBrokerListUsersConfig(Input):
    "Returns a list of active users from your organization."
    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all users",
            "x-is-trigger": False,
            "x-method-kind": "read",
        },
    )
    page: int = Field(1, description="Content's page", ge=1, le=1000000)
    limit: int = Field(
        20, description="Max results per page (Maximum: 50)", le=50, ge=1
    )


class EasyBrokerOnNewContactRequestConfig(PollTriggerConfigBase):
    operation: Literal["on_new_contact_request"] = Field(
        "on_new_contact_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "On New Contact Request",
            "x-category": "Triggers",
            "x-is-trigger": True,
        },
    )
    since: Optional[datetime] = Field(
        None,
        description="Optional lower time bound. First poll baselines existing records; subsequent polls emit newly seen IDs or versions. Polls read every page in this scope, at most 10000 records.",
    )
    property_id: Optional[str] = Field(
        None, description="Only monitor requests for this property."
    )


class EasyBrokerOnNewOrUpdatedContactConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_contact"] = Field(
        "on_new_or_updated_contact",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "On New Or Updated Contact",
            "x-category": "Triggers",
            "x-is-trigger": True,
        },
    )
    since: Optional[datetime] = Field(
        None,
        description="Optional lower time bound. First poll baselines existing records; subsequent polls emit newly seen IDs or versions. Polls read every page in this scope, at most 10000 records.",
    )


class EasyBrokerOnNewOrUpdatedPropertyConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_property"] = Field(
        "on_new_or_updated_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "On New Or Updated Property",
            "x-category": "Triggers",
            "x-is-trigger": True,
        },
    )
    since: Optional[datetime] = Field(
        None,
        description="Optional lower time bound. First poll baselines existing records; subsequent polls emit newly seen IDs or versions. Polls read every page in this scope, at most 10000 records.",
    )


OPERATIONS = {
    "list_collaborations": (
        "GET",
        "/collaborations",
        {"page": "page", "limit": "limit"},
    ),
    "list_contact_requests": (
        "GET",
        "/contact_requests",
        {
            "page": "page",
            "limit": "limit",
            "happened_after": "happened_after",
            "happened_before": "happened_before",
            "property_id": "property_id",
        },
    ),
    "create_contact_request": ("POST", "/contact_requests", {}),
    "list_contacts": (
        "GET",
        "/contacts",
        {
            "page": "page",
            "limit": "limit",
            "search_updated_after": "search[updated_after]",
            "search_updated_before": "search[updated_before]",
            "search_created_after": "search[created_after]",
            "search_created_before": "search[created_before]",
            "search_last_activity_after": "search[last_activity_after]",
            "search_last_activity_before": "search[last_activity_before]",
            "search_statuses": "search[statuses][]",
            "search_probabilities": "search[probabilities][]",
            "search_tag": "search[tag]",
            "search_email": "search[email]",
            "search_offices": "search[offices][]",
            "search_sources": "search[sources][]",
        },
    ),
    "get_contact": ("GET", "/contacts/{contact_id}", {}),
    "update_contact": ("PATCH", "/contacts/{contact_id}", {}),
    "list_features": (
        "GET",
        "/features",
        {"page": "page", "limit": "limit", "locale": "locale"},
    ),
    "list_listing_statuses": (
        "GET",
        "/listing_statuses",
        {
            "page": "page",
            "limit": "limit",
            "search_updated_after": "search[updated_after]",
            "search_updated_before": "search[updated_before]",
            "search_statuses": "search[statuses][]",
        },
    ),
    "get_locations": (
        "GET",
        "/locations",
        {"query": "query", "postal_code": "postal_code"},
    ),
    "list_properties": (
        "GET",
        "/properties",
        {
            "page": "page",
            "limit": "limit",
            "search_property_types": "search[property_types][]",
            "search_updated_after": "search[updated_after]",
            "search_updated_before": "search[updated_before]",
            "search_operation_type": "search[operation_type]",
            "search_min_price": "search[min_price]",
            "search_max_price": "search[max_price]",
            "search_min_bedrooms": "search[min_bedrooms]",
            "search_min_bathrooms": "search[min_bathrooms]",
            "search_min_parking_spaces": "search[min_parking_spaces]",
            "search_min_construction_size": "search[min_construction_size]",
            "search_max_construction_size": "search[max_construction_size]",
            "search_min_lot_size": "search[min_lot_size]",
            "search_max_lot_size": "search[max_lot_size]",
            "search_statuses": "search[statuses][]",
            "search_sort_by": "search[sort_by]",
        },
    ),
    "create_property": ("POST", "/properties", {}),
    "get_property": ("GET", "/properties/{property_id}", {}),
    "update_property": ("PATCH", "/properties/{property_id}", {}),
    "list_property_integrations": (
        "GET",
        "/property_integrations",
        {
            "page": "page",
            "limit": "limit",
            "search_updated_after": "search[updated_after]",
            "search_updated_before": "search[updated_before]",
            "search_integration_partner_symbol": "search[integration_partner_symbol]",
        },
    ),
    "list_property_types": (
        "GET",
        "/property_types",
        {"page": "page", "limit": "limit", "locale": "locale"},
    ),
    "list_users": ("GET", "/users", {"page": "page", "limit": "limit"}),
}

TRIGGERS = {
    "on_new_contact_request": "contact_requests",
    "on_new_or_updated_contact": "contacts",
    "on_new_or_updated_property": "properties",
}

EasyBrokerConfig = Annotated[
    Union[
        EasyBrokerListCollaborationsConfig,
        EasyBrokerListContactRequestsConfig,
        EasyBrokerCreateContactRequestConfig,
        EasyBrokerListContactsConfig,
        EasyBrokerGetContactConfig,
        EasyBrokerUpdateContactConfig,
        EasyBrokerListFeaturesConfig,
        EasyBrokerListListingStatusesConfig,
        EasyBrokerGetLocationsConfig,
        EasyBrokerListPropertiesConfig,
        EasyBrokerCreatePropertyConfig,
        EasyBrokerGetPropertyConfig,
        EasyBrokerUpdatePropertyConfig,
        EasyBrokerListPropertyIntegrationsConfig,
        EasyBrokerListPropertyTypesConfig,
        EasyBrokerListUsersConfig,
        EasyBrokerOnNewContactRequestConfig,
        EasyBrokerOnNewOrUpdatedContactConfig,
        EasyBrokerOnNewOrUpdatedPropertyConfig,
    ],
    Field(discriminator="operation"),
]


class EasyBrokerFullConfig(NodeConfig[EasyBrokerConfig, EasyBrokerAPIKeyCredential]):
    pass


class EasyBrokerNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-easybroker-archive"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return EasyBrokerFullConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None):
        # Fixed origin, no redirects and no automatic retries of writes.
        async with guarded_async_client(
            timeout=45, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                BASE + path,
                params=params,
                json=body,
                headers={"X-Authorization": key, "Accept": "application/json"},
            )
        if response.is_error or response.is_redirect:
            detail = "request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = str(error.get("error") or error.get("errors") or detail)
            except ValueError:
                pass
            detail = detail.replace(key, "[redacted]")[:1000]
            raise ValueError(f"EasyBroker API error {response.status_code}: {detail}")
        if len(response.content) > 10_000_000:
            raise ValueError("EasyBroker response exceeds 10 MB")
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Expected EasyBroker JSON object or array")
        if isinstance(payload, dict) and ("error" in payload or "errors" in payload):
            raise ValueError("EasyBroker returned an error envelope")
        return payload

    @staticmethod
    def _page(payload, path, params):
        if not isinstance(payload, dict) or not isinstance(
            payload.get("content"), list
        ):
            raise ValueError("EasyBroker list response is missing content")
        rows, pagination = payload["content"], payload.get("pagination")
        if any(not isinstance(row, dict) for row in rows) or not isinstance(
            pagination, dict
        ):
            raise ValueError("EasyBroker list response is malformed")
        page = params.get("page", 1)
        if pagination.get("page") != page or len(rows) > params.get("limit", 20):
            raise ValueError("EasyBroker returned an inconsistent page")
        link = pagination.get("next_page")
        following = None
        if link:
            if not isinstance(link, str) or not rows:
                raise ValueError("EasyBroker returned an invalid continuation")
            parsed = urlsplit(link)
            if (
                (parsed.scheme and parsed.scheme != "https")
                or (parsed.netloc and parsed.netloc != "api.easybroker.com")
                or parsed.fragment
            ):
                raise ValueError("EasyBroker continuation changed origin")
            if parsed.path != "/v1" + path:
                raise ValueError("EasyBroker continuation changed resource")
            query = parse_qs(parsed.query)
            if query.get("page") != [str(page + 1)]:
                raise ValueError("EasyBroker continuation did not advance one page")
            # Retain our own filters; never execute a provider-returned URL.
            for name, values in query.items():
                if name == "page":
                    continue
                expected = params.get(name)
                expected = expected if isinstance(expected, list) else [expected]
                if values != [str(value) for value in expected]:
                    raise ValueError("EasyBroker continuation changed filters")
            following = page + 1
        return rows, following

    async def _poll(self, key, config):
        resource = TRIGGERS[config.operation]
        path = "/" + resource
        params = {"page": 1, "limit": 50}
        if config.since is not None:
            params[
                "happened_after"
                if resource == "contact_requests"
                else "search[updated_after]"
            ] = config.since.isoformat()
        if resource == "contact_requests" and config.property_id:
            params["property_id"] = config.property_id
        rows = []
        for _ in range(200):
            payload = await self._request(key, "GET", path, params=params)
            batch, following = self._page(payload, path, params)
            rows.extend(batch)
            if following is None:
                break
            params["page"] = following
        else:
            raise ValueError(
                "EasyBroker poll exceeds 10000 records; choose a later since time"
            )

        def identity(row):
            identifier = (
                row.get("public_id") if resource == "properties" else row.get("id")
            )
            timestamp = row.get(
                "happened_at" if resource == "contact_requests" else "updated_at"
            )
            if (
                not isinstance(identifier, (str, int))
                or isinstance(identifier, bool)
                or not identifier
                or not isinstance(timestamp, str)
                or not timestamp
            ):
                raise ValueError(
                    "EasyBroker poll item lacks its documented ID or timestamp"
                )
            return str(identifier) + ":" + timestamp

        # Validate the complete snapshot before persisting any seen state.
        ids = [identity(row) for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("EasyBroker repeated a record across poll pages")
        fresh = await self._filter_unseen(rows, identity)
        return {
            "operation": config.operation,
            "items": fresh,
            "new_item_count": len(fresh),
        }

    @classmethod
    def should_propagate_output(cls, output, config):
        return (
            bool(output.get("new_item_count"))
            if config.get("operation") in TRIGGERS
            else True
        )

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in TRIGGERS:
            return super().resolve_agent_event(output)
        rows = output.get("items")
        if not isinstance(rows, list) or not rows:
            return None
        operation = output["operation"]
        lines = []
        for row in rows[:10]:
            if operation == "on_new_contact_request":
                lines.append(
                    f"{row.get('name') or 'Lead'} ({row.get('email') or row.get('phone') or 'no contact details'}): {row.get('message') or 'Contact request'}; property {row.get('property_id')}, request {row.get('id')}, contact {row.get('contact_id')}, source {row.get('source')}, at {row.get('happened_at')}"
                )
            elif operation == "on_new_or_updated_contact":
                lines.append(
                    f"{row.get('full_name') or 'Contact'} ({row.get('email') or row.get('phone') or 'no contact details'}); contact {row.get('id')}, agent {row.get('agent')}, status {row.get('status')}, updated {row.get('updated_at')}"
                )
            else:
                lines.append(
                    f"{row.get('title') or 'Property'} in {row.get('location')}; property {row.get('public_id')}, agent {row.get('agent')}, updated {row.get('updated_at')}"
                )
        return {
            "text": f"EasyBroker: {len(rows)} {operation.removeprefix('on_').replace('_', ' ')} event(s)\n"
            + "\n".join(lines),
            "conversation_key": None,
        }

    async def execute(self, inputs):
        if (
            not isinstance(self.config, EasyBrokerFullConfig)
            or self.config.credentials is None
        ):
            raise ValueError("Connect an EasyBroker API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if config.operation in TRIGGERS:
            return await self._poll(key, config)
        method, template, query_fields = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = template
        for field in ("property_id", "contact_id"):
            if "{" + field + "}" in path:
                value = str(values[field])
                if not value or value in {".", ".."} or any(ord(c) < 32 for c in value):
                    raise ValueError("Use a nonempty EasyBroker resource ID")
                path = path.replace("{" + field + "}", quote(value, safe=""))
        params = {
            wire: values[field]
            for field, wire in query_fields.items()
            if field in values
        }
        body = (
            config.body.model_dump(mode="json", exclude_unset=True)
            if hasattr(config, "body")
            else None
        )
        payload = await self._request(key, method, path, params=params, body=body)
        result = {"operation": config.operation, "data": payload}
        if config.operation.startswith("list_"):
            rows, following = self._page(payload, path, params)
            result.update(
                items=rows, next_page=following, has_more=following is not None
            )
        return result
