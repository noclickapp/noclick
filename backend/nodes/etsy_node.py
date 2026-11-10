"""Etsy Open API v3: shop, listing/inventory and post-purchase order automation.

Contract: https://www.etsy.com/openapi/generated/oas/3.0.0.json (3.0.0).
Authentication: https://developers.etsy.com/documentation/essentials/authentication/
Paste the app keystring:shared_secret and an existing user OAuth access token.
Tokens expire after one hour; replace the pasted token when it expires. This
integration does not start an OAuth consent flow or silently refresh tokens.
Every operation maps to exactly one documented API call; lists return one page.
"""
from __future__ import annotations

import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.etsy import ETSY_SCOPES

ETSY_API_BASE = "https://openapi.etsy.com"


class EtsyTokenCredential(BaseModel):
    credential_type: Literal["etsy_token"] = Field(
        "etsy_token", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="App Keystring",
        min_length=1,
        description="Your Etsy application keystring from Your Apps.",
        json_schema_extra={"ui:widget": "password"},
    )
    shared_secret: str = Field(
        ...,
        title="Shared Secret",
        min_length=1,
        description="The shared secret for the same Etsy application; required on every request.",
        json_schema_extra={"ui:widget": "password"},
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        min_length=1,
        description="Paste an existing Etsy OAuth access token, including the numeric user ID prefix. Tokens expire after one hour; paste a replacement when it expires.",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("access_token")
    @classmethod
    def token_without_header(cls, value: str) -> str:
        value = value.strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the access token only, without whitespace.")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.etsy.com/developers/your-apps",
            "x-credential-instructions": "Copy keystring and shared secret from Etsy Your Apps into their separate fields. Generate an OAuth access token using Etsy's authorization-code/PKCE flow with the listed scopes, then paste it here. Tokens expire after one hour; replace expired tokens. Required scopes: listings_r, listings_w, listings_d, shops_r, shops_w, transactions_r, transactions_w.",
            "x-oauth-scopes": sorted(ETSY_SCOPES.declared_scopes()),
        }
    )


class EtsyUpdateListingInventoryConfigProductsItemPropertyValuesItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: int = Field(
        ...,
        title="Property Id",
        description="The unique ID of an Etsy [listing property](/documentation/reference#operation/getListingInventory).",
        ge=1,
    )
    value_ids: List[int] = Field(
        ...,
        title="Value Ids",
        description="An array of unique IDs of Etsy [listing property](/documentation/reference#operation/getListingInventory) values.",
    )
    scale_id: Optional[int] = Field(
        None,
        title="Scale Id",
        description="The numeric ID of a single Etsy.com measurement scale. For example, for shoe size, there are three `scale_id`s available - `UK`, `US/Canada`, and `EU`, where `US/Canada` has `scale_id` 19.",
        ge=1,
    )
    property_name: Optional[str] = Field(
        None,
        title="Property Name",
        description="The name of the property, in the requested locale language.",
    )
    values: List[str] = Field(
        ...,
        title="Values",
        description="A list of property value entries for this product. Note: parenthesis characters (`(` and `)`) are not allowed.",
    )


class EtsyUpdateListingInventoryConfigProductsItemOfferingsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: float = Field(..., title="Price", description="The price of the product.")
    quantity: int = Field(
        ..., title="Quantity", description="How many of this product are available?"
    )
    is_enabled: bool = Field(
        ..., title="Is Enabled", description="True if the offering is shown to buyers"
    )
    readiness_state_id: Optional[int] = Field(
        ...,
        title="Readiness State Id",
        description="The numeric ID of the [processing profile](/documentation/reference#operation/getShopReadinessStateDefinition) associated with the listing. Returned only when the listing is `active` and of type `physical`, and the endpoint is either shop-scoped (path contains `shop_id`) or a single-listing request such as `getListing`. For every other case this field can be null.",
        ge=1,
    )


class EtsyUpdateListingInventoryConfigProductsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Optional[str] = Field(
        None, title="Sku", description="The SKU string for the product"
    )
    property_values: Optional[
        List[EtsyUpdateListingInventoryConfigProductsItemPropertyValuesItem]
    ] = Field(
        None,
        title="Property Values",
        description="A list of property value entries for this product. Note: parenthesis characters (`(` and `)`) are not allowed.",
    )
    offerings: List[EtsyUpdateListingInventoryConfigProductsItemOfferingsItem] = Field(
        ...,
        title="Offerings",
        description="A list of product offering entries for this product.",
    )


class EtsyCreateShipmentConfigCustomsDataItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country_of_origin: Optional[str] = Field(
        ...,
        title="Country Of Origin",
        description="The country in which the goods originate from.",
    )
    declared_value: Optional[float] = Field(
        ..., title="Declared Value", description="The commercial value of the goods."
    )
    HS_code: Optional[str] = Field(
        ...,
        title="Hs Code",
        description="The standardized global system (Harmonized System) for classifying traded products.",
    )


class EtsyGetMeConfig(BaseModel):
    """getMe — GET /v3/application/users/me."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-display-name": "Get Me",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )


class EtsyGetShopConfig(BaseModel):
    """getShop — GET /v3/application/shops/{shop_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_shop"] = Field(
        "get_shop",
        json_schema_extra={
            "const": "get_shop",
            "ui:hidden": True,
            "x-display-name": "Get Shop",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )


class EtsyUpdateShopConfig(BaseModel):
    """updateShop — PUT /v3/application/shops/{shop_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["update_shop"] = Field(
        "update_shop",
        json_schema_extra={
            "const": "update_shop",
            "ui:hidden": True,
            "x-display-name": "Update Shop",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    title: Optional[str] = Field(
        None,
        title="Title",
        description="A brief heading string for the shop's main page.",
    )
    announcement: Optional[str] = Field(
        None,
        title="Announcement",
        description="An announcement string to buyers that displays on the shop's homepage.",
    )
    sale_message: Optional[str] = Field(
        None,
        title="Sale Message",
        description="A message string sent to users who complete a purchase from this shop.",
    )
    digital_sale_message: Optional[str] = Field(
        None,
        title="Digital Sale Message",
        description="A message string sent to users who purchase a digital item from this shop.",
    )
    policy_additional: Optional[str] = Field(
        None,
        title="Policy Additional",
        description="The shop's additional policies string (may be blank).",
    )


class EtsyListShopSectionsConfig(BaseModel):
    """getShopSections — GET /v3/application/shops/{shop_id}/sections."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_shop_sections"] = Field(
        "list_shop_sections",
        json_schema_extra={
            "const": "list_shop_sections",
            "ui:hidden": True,
            "x-display-name": "List Shop Sections",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )


class EtsyCreateShopSectionConfig(BaseModel):
    """createShopSection — POST /v3/application/shops/{shop_id}/sections."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["create_shop_section"] = Field(
        "create_shop_section",
        json_schema_extra={
            "const": "create_shop_section",
            "ui:hidden": True,
            "x-display-name": "Create Shop Section",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    title: str = Field(
        ..., title="Title", description="The title string for a shop section."
    )


class EtsyUpdateShopSectionConfig(BaseModel):
    """updateShopSection — PUT /v3/application/shops/{shop_id}/sections/{shop_section_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["update_shop_section"] = Field(
        "update_shop_section",
        json_schema_extra={
            "const": "update_shop_section",
            "ui:hidden": True,
            "x-display-name": "Update Shop Section",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    shop_section_id: int = Field(
        ...,
        title="Shop Section Id",
        description="The numeric ID of a section in a specific Etsy shop.",
        ge=1,
    )
    title: str = Field(
        ..., title="Title", description="The title string for a shop section."
    )


class EtsyListShippingProfilesConfig(BaseModel):
    """getShopShippingProfiles — GET /v3/application/shops/{shop_id}/shipping-profiles."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_shipping_profiles"] = Field(
        "list_shipping_profiles",
        json_schema_extra={
            "const": "list_shipping_profiles",
            "ui:hidden": True,
            "x-display-name": "List Shipping Profiles",
            "x-category": "Shop",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )


class EtsyListListingsConfig(BaseModel):
    """getListingsByShop — GET /v3/application/shops/{shop_id}/listings."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_listings"] = Field(
        "list_listings",
        json_schema_extra={
            "const": "list_listings",
            "ui:hidden": True,
            "x-display-name": "List Listings",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    state: Optional[
        Literal["active", "inactive", "sold_out", "draft", "removed", "expired"]
    ] = Field(
        "active",
        title="State",
        description="When _updating_ a listing, this value can be either `active` or `inactive`. Note: Setting a `draft` listing to `active` will also publish the listing on etsy.com and requires that the listing have an image set. Setting a `sold_out` listing to active will update the quantity to 1 and renew the listing on etsy.com.",
    )
    limit: Optional[int] = Field(
        25,
        title="Limit",
        description="The maximum number of results to return.",
        ge=1,
        le=100,
    )
    offset: Optional[int] = Field(
        0,
        title="Offset",
        description="The number of records to skip before selecting the first result.",
        ge=0,
    )
    sort_on: Optional[Literal["created", "price", "updated", "score"]] = Field(
        "created",
        title="Sort On",
        description="The value to sort a search result of listings on. NOTES: a) `sort_on` only works when combined with one of the search options (keywords, region, etc.). b) when using `score` the returned results will always be in _descending_ order, regardless of the `sort_order` parameter.",
    )
    sort_order: Optional[
        Literal["asc", "ascending", "desc", "descending", "up", "down"]
    ] = Field(
        "desc",
        title="Sort Order",
        description="The ascending(up) or descending(down) order to sort listings by. NOTE: sort_order only works when combined with one of the search options (keywords, region, etc.).",
    )
    includes: Optional[
        List[
            Literal[
                "Shipping",
                "Images",
                "Shop",
                "User",
                "Translations",
                "Inventory",
                "Videos",
                "Personalization",
                "BuyerPrice",
            ]
        ]
    ] = Field(
        None,
        title="Includes",
        description="An enumerated string that attaches a valid association. Acceptable inputs are 'Shipping', 'Shop', 'Images', 'User', 'Translations', 'Videos', 'Inventory' and 'Personalization'.",
    )


class EtsyGetListingConfig(BaseModel):
    """getListing — GET /v3/application/listings/{listing_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_listing"] = Field(
        "get_listing",
        json_schema_extra={
            "const": "get_listing",
            "ui:hidden": True,
            "x-display-name": "Get Listing",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    listing_id: int = Field(
        ...,
        title="Listing Id",
        description="The numeric ID for the [listing](/documentation/reference#tag/ShopListing) associated to this transaction.",
        ge=1,
    )
    includes: Optional[
        List[
            Literal[
                "Images",
                "Shop",
                "User",
                "Translations",
                "Videos",
                "Personalization",
                "BuyerPrice",
            ]
        ]
    ] = Field(
        None,
        title="Includes",
        description="An enumerated string that attaches a valid association. Acceptable inputs are 'Shop', 'Images', 'User', 'Translations', 'Videos', 'Personalization' and 'BuyerPrice'.",
    )
    language: Optional[str] = Field(
        None,
        title="Language",
        description="The IETF language tag for the language of this translation. Ex: `de`, `en`, `es`, `fr`, `it`, `ja`, `nl`, `pl`, `pt`.",
    )
    allow_suggested_title: Optional[bool] = Field(
        None,
        title="Allow Suggested Title",
        description="This parameter will include in the response a suggested title for the listing, if one is available. Since suggestions are only available to the listing's owner, client must submit an oauth_access_token scoped to the owner of the listing.",
    )


class EtsyCreateDraftListingConfig(BaseModel):
    """createDraftListing — POST /v3/application/shops/{shop_id}/listings."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["create_draft_listing"] = Field(
        "create_draft_listing",
        json_schema_extra={
            "const": "create_draft_listing",
            "ui:hidden": True,
            "x-display-name": "Create Draft Listing",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    quantity: int = Field(
        ...,
        title="Quantity",
        description="The positive non-zero number of products available for purchase in the listing. Note: The listing quantity is the sum of available offering quantities. You can request the quantities for individual offerings from the ListingInventory resource using the [getListingInventory](/documentation/reference#operation/getListingInventory) endpoint.",
    )
    title: str = Field(
        ...,
        title="Title",
        description="The listing's title string. When creating or updating a listing, valid title strings contain only letters, numbers, punctuation marks, mathematical symbols, whitespace characters, ™, ©, and ®. (regex: /[^\\p{L}\\p{Nd}\\p{P}\\p{Sm}\\p{Zs}™©®]/u) You can only use the %, :, & and + characters once each.",
    )
    description: str = Field(
        ...,
        title="Description",
        description="A description string of the product for sale in the listing.",
    )
    price: float = Field(
        ...,
        title="Price",
        description="The positive non-zero price of the product. (Sold product listings are private) Note: The price is the minimum possible price. The [`getListingInventory`](/documentation/reference/#operation/getListingInventory) method requests exact prices for available offerings.",
    )
    who_made: Literal["i_did", "someone_else", "collective"] = Field(
        ...,
        title="Who Made",
        description="An enumerated string indicating who made the product. Helps buyers locate the listing under the Handmade heading. Requires 'is_supply' and 'when_made'.",
    )
    when_made: Literal[
        "made_to_order",
        "2020_2026",
        "2010_2019",
        "2007_2009",
        "before_2007",
        "2000_2006",
        "1990s",
        "1980s",
        "1970s",
        "1960s",
        "1950s",
        "1940s",
        "1930s",
        "1920s",
        "1910s",
        "1900s",
        "1800s",
        "1700s",
        "before_1700",
    ] = Field(
        ...,
        title="When Made",
        description="An enumerated string for the era in which the maker made the product in this listing. Helps buyers locate the listing under the Vintage heading. Requires 'is_supply' and 'who_made'.",
    )
    taxonomy_id: int = Field(
        ...,
        title="Taxonomy Id",
        description="The numerical taxonomy ID of the listing. See [SellerTaxonomy](/documentation/reference#tag/SellerTaxonomy) and [BuyerTaxonomy](/documentation/reference#tag/BuyerTaxonomy) for more information.",
        ge=1,
    )
    shipping_profile_id: Optional[int] = Field(
        None,
        title="Shipping Profile Id",
        description="The numeric ID of the [shipping profile](/documentation/reference#operation/getShopShippingProfile) associated with the listing. Required when listing type is `physical`.",
        ge=1,
    )
    return_policy_id: Optional[int] = Field(
        None,
        title="Return Policy Id",
        description="The numeric ID of the [Return Policy](/documentation/reference#operation/getShopReturnPolicies).",
        ge=1,
    )
    materials: Optional[List[str]] = Field(
        None,
        title="Materials",
        description="A list of material strings for materials used in the product. Valid materials strings contain only letters, numbers, and whitespace characters. (regex: /[^\\p{L}\\p{Nd}\\p{Zs}]/u) Default value is null.",
    )
    shop_section_id: Optional[int] = Field(
        None,
        title="Shop Section Id",
        description="The numeric ID of the [shop section](/documentation/reference#tag/Shop-Section) for this listing. Default value is null.",
        ge=1,
    )
    processing_min: Optional[int] = Field(
        None,
        title="Processing Min",
        description="The minimum number of days required to process this listing. Default value is null.",
    )
    processing_max: Optional[int] = Field(
        None,
        title="Processing Max",
        description="The maximum number of days required to process this listing. Default value is null.",
    )
    readiness_state_id: Optional[int] = Field(
        None,
        title="Readiness State Id",
        description="The numeric ID of the [processing profile](/documentation/reference#operation/getShopReadinessStateDefinition) associated with the listing. Returned only when the listing is `active` and of type `physical`, and the endpoint is either shop-scoped (path contains `shop_id`) or a single-listing request such as `getListing`. For every other case this field can be null.",
        ge=1,
    )
    tags: Optional[List[str]] = Field(
        None,
        title="Tags",
        description="A comma-separated list of tag strings for the listing. When creating or updating a listing, valid tag strings contain only letters, numbers, whitespace characters, -, ', ™, ©, and ®. (regex: /[^\\p{L}\\p{Nd}\\p{Zs}\\-'™©®]/u) Default value is null.",
    )
    styles: Optional[List[str]] = Field(
        None,
        title="Styles",
        description='An array of style strings for this listing, each of which is free-form text string such as "Formal", or "Steampunk". When creating or updating a listing, the listing may have up to two styles. Valid style strings contain only letters, numbers, and whitespace characters. (regex: /[^\\p{L}\\p{Nd}\\p{Zs}]/u) Each style string is limited to 45 characters. Default value is null.',
    )
    item_weight: Optional[float] = Field(
        None,
        title="Item Weight",
        description="The numeric weight of the product measured in units set in 'item_weight_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_length: Optional[float] = Field(
        None,
        title="Item Length",
        description="The numeric length of the product measured in units set in 'item_dimensions_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_width: Optional[float] = Field(
        None,
        title="Item Width",
        description="The numeric width of the product measured in units set in 'item_dimensions_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_height: Optional[float] = Field(
        None,
        title="Item Height",
        description="The numeric height of the product measured in units set in 'item_dimensions_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_weight_unit: Optional[Literal["oz", "lb", "g", "kg"]] = Field(
        None,
        title="Item Weight Unit",
        description="A string defining the units used to measure the weight of the product. Default value is null.",
    )
    item_dimensions_unit: Optional[
        Literal["in", "ft", "mm", "cm", "m", "yd", "inches"]
    ] = Field(
        None,
        title="Item Dimensions Unit",
        description="A string defining the units used to measure the dimensions of the product. Default value is null.",
    )
    production_partner_ids: Optional[List[int]] = Field(
        None,
        title="Production Partner Ids",
        description="An array of unique IDs of production partner ids.",
    )
    image_ids: Optional[List[int]] = Field(
        None,
        title="Image Ids",
        description="An array of numeric image IDs of the images in a listing, which can include up to 20 images.",
    )
    ecgt_garan_brand: Optional[str] = Field(
        None,
        title="Ecgt Garan Brand",
        description="The brand or trademark name for the EU commercial guarantee (required under GPSR/ECGT for eligible EU traders). Maximum 25 characters. See the [Etsy Seller Handbook](https://help.etsy.com/hc/articles/43191692248343) for details. If any one of ecgt_garan_brand, ecgt_garan_model, ecgt_garan_years, or ecgt_garan_guarantee_details is provided and non-empty, all four are required. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_garan_years: Optional[int] = Field(
        None,
        title="Ecgt Garan Years",
        description="Duration of the EU commercial guarantee in whole years (minimum 3, maximum 99). Required together with ecgt_garan_brand, ecgt_garan_model, and ecgt_garan_guarantee_details. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_garan_model: Optional[str] = Field(
        None,
        title="Ecgt Garan Model",
        description="The product model or reference number for the EU commercial guarantee label. Maximum 20 characters. Required together with ecgt_garan_brand, ecgt_garan_years, and ecgt_garan_guarantee_details. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_garan_guarantee_details: Optional[str] = Field(
        None,
        title="Ecgt Garan Guarantee Details",
        description="Free-text description of the EU commercial guarantee terms and coverage. Maximum 255 characters. Required together with ecgt_garan_brand, ecgt_garan_model, and ecgt_garan_years. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_other_commercial_guarantee_details: Optional[str] = Field(
        None,
        title="Ecgt Other Commercial Guarantee Details",
        description="Free-text details of any additional commercial guarantee or warranty beyond the primary EU commercial guarantee. Maximum 255 characters. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_after_sales_service_info: Optional[str] = Field(
        None,
        title="Ecgt After Sales Service Info",
        description="After-sales service, repairability, or eco-friendly delivery information required under EU GPSR/ECGT regulations. Maximum 255 characters. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_software_update_details: Optional[str] = Field(
        None,
        title="Ecgt Software Update Details",
        description="Details of software update availability and the duration of such updates, as required under EU ECGT regulations for digital content. Maximum 255 characters. Silently ignored for physical listings and for sellers who are not eligible EU traders.",
    )
    gpsr_manufacturer_type: Optional[Literal["seller", "economic_operator"]] = Field(
        None,
        title="Gpsr Manufacturer Type",
        description="Who the manufacturer of this product is, for GPSR (EU General Product Safety Regulation) purposes. Either `seller` (your shop is the manufacturer) or `economic_operator` (a manufacturer record from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints, identified by `gpsr_manufacturer_id`). `seller` is rejected when `who_made` is `someone_else`; use `economic_operator` for items made by a third party. Send `null` to clear. Optional for now; it becomes required for listings from eligible traders that sell into the EU 60 days after these fields were announced. See the [GPSR Economic Operators Tutorial](/documentation/tutorials/gpsr-economic-operators) for eligibility and the full flow.",
    )
    gpsr_manufacturer_id: Optional[int] = Field(
        None,
        title="Gpsr Manufacturer Id",
        description="The `economic_operator_id` of the manufacturer, from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints. Required when `gpsr_manufacturer_type` is `economic_operator`, and rejected when the type is anything else. The operator must belong to this shop and not be deleted. The manufacturer may be located anywhere in the world. If you change `gpsr_manufacturer_type` to `seller` without sending this field, the stored id is cleared for you.",
    )
    gpsr_responsible_person_type: Optional[
        Literal["seller", "economic_operator"]
    ] = Field(
        None,
        title="Gpsr Responsible Person Type",
        description="Who the EU responsible person for this product is, for GPSR purposes. Either `seller` (your shop; only valid when the shop's legal address, or the address on file, is in the European Union) or `economic_operator` (a record from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints, identified by `gpsr_responsible_person_id`, which must have an address in the European Union). Send `null` to clear. Optional for now; it becomes required for listings from eligible traders that sell into the EU 60 days after these fields were announced. See the [GPSR Economic Operators Tutorial](/documentation/tutorials/gpsr-economic-operators) for eligibility and the full flow.",
    )
    gpsr_responsible_person_id: Optional[int] = Field(
        None,
        title="Gpsr Responsible Person Id",
        description="The `economic_operator_id` of the EU responsible person, from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints. Required when `gpsr_responsible_person_type` is `economic_operator`, and rejected when the type is anything else. The operator must belong to this shop and not be deleted, and its address must be in the European Union. If you change `gpsr_responsible_person_type` to `seller` without sending this field, the stored id is cleared for you.",
    )
    gpsr_serial_number: Optional[str] = Field(
        None,
        title="Gpsr Serial Number",
        description="An optional serial number, batch number, or lot identifier that lets the product be traced for GPSR purposes. Maximum 255 characters. Send `null` to clear.",
    )
    gpsr_safety_warnings: Optional[str] = Field(
        None,
        title="Gpsr Safety Warnings",
        description="Optional free-text safety warnings and safety information for the product regarding GPSR purposes, shown to buyers as product safety information on the listing page (for example age restrictions, choking hazards, or care and handling instructions). Maximum 102,400 characters. Send `null` to clear.",
    )
    is_supply: Optional[bool] = Field(
        None,
        title="Is Supply",
        description="When true, tags the listing as a supply product, else indicates that it's a finished product. Helps buyers locate the listing under the Supplies heading. Requires 'who_made' and 'when_made'.",
    )
    is_customizable: Optional[bool] = Field(
        None,
        title="Is Customizable",
        description="When true, a buyer may contact the seller for a customized order. The default value is true when a shop accepts custom orders. Does not apply to shops that do not accept custom orders.",
    )
    should_auto_renew: Optional[bool] = Field(
        None,
        title="Should Auto Renew",
        description="When true, renews a listing for four months upon expiration.",
    )
    is_taxable: Optional[bool] = Field(
        None,
        title="Is Taxable",
        description="When true, applicable [shop](/documentation/reference#tag/Shop) tax rates apply to this listing at checkout.",
    )
    type: Optional[Literal["physical", "download", "both"]] = Field(
        None,
        title="Type",
        description="An enumerated type string that indicates whether the listing is physical or a digital download.",
    )


class EtsyUpdateListingConfig(BaseModel):
    """updateListing — PATCH /v3/application/shops/{shop_id}/listings/{listing_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["update_listing"] = Field(
        "update_listing",
        json_schema_extra={
            "const": "update_listing",
            "ui:hidden": True,
            "x-display-name": "Update Listing",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    listing_id: int = Field(
        ...,
        title="Listing Id",
        description="The numeric ID for the [listing](/documentation/reference#tag/ShopListing) associated to this transaction.",
        ge=1,
    )
    image_ids: Optional[List[int]] = Field(
        None,
        title="Image Ids",
        description="An array of numeric image IDs of the images in a listing, which can include up to 20 images.",
    )
    title: Optional[str] = Field(
        None,
        title="Title",
        description="The listing's title string. When creating or updating a listing, valid title strings contain only letters, numbers, punctuation marks, mathematical symbols, whitespace characters, ™, ©, and ®. (regex: /[^\\p{L}\\p{Nd}\\p{P}\\p{Sm}\\p{Zs}™©®]/u) You can only use the %, :, & and + characters once each.",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="A description string of the product for sale in the listing.",
    )
    materials: Optional[List[str]] = Field(
        None,
        title="Materials",
        description="A list of material strings for materials used in the product. Valid materials strings contain only letters, numbers, and whitespace characters. (regex: /[^\\p{L}\\p{Nd}\\p{Zs}]/u) Default value is null.",
    )
    should_auto_renew: Optional[bool] = Field(
        None,
        title="Should Auto Renew",
        description="When true, renews a listing for four months upon expiration.",
    )
    shipping_profile_id: Optional[int] = Field(
        None,
        title="Shipping Profile Id",
        description="The numeric ID of the [shipping profile](/documentation/reference#operation/getShopShippingProfile) associated with the listing. Required when listing type is `physical`.",
        ge=1,
    )
    return_policy_id: Optional[int] = Field(
        None,
        title="Return Policy Id",
        description="The numeric ID of the [Return Policy](/documentation/reference#operation/getShopReturnPolicies). Required for active physical listings. This requirement does not apply to listings of EU-based shops.",
        ge=1,
    )
    shop_section_id: Optional[int] = Field(
        None,
        title="Shop Section Id",
        description="The numeric ID of the [shop section](/documentation/reference#tag/Shop-Section) for this listing. Default value is null.",
    )
    item_weight: Optional[float] = Field(
        None,
        title="Item Weight",
        description="The numeric weight of the product measured in units set in 'item_weight_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_length: Optional[float] = Field(
        None,
        title="Item Length",
        description="The numeric length of the product measured in units set in 'item_dimensions_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_width: Optional[float] = Field(
        None,
        title="Item Width",
        description="The numeric width of the product measured in units set in 'item_dimensions_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_height: Optional[float] = Field(
        None,
        title="Item Height",
        description="The numeric height of the product measured in units set in 'item_dimensions_unit'. Default value is null. If set, the value must be greater than 0.",
        ge=0,
        le=1.79769313486e308,
    )
    item_weight_unit: Optional[Literal["", "oz", "lb", "g", "kg"]] = Field(
        None,
        title="Item Weight Unit",
        description="A string defining the units used to measure the weight of the product. Default value is null.",
    )
    item_dimensions_unit: Optional[
        Literal["", "in", "ft", "mm", "cm", "m", "yd", "inches"]
    ] = Field(
        None,
        title="Item Dimensions Unit",
        description="A string defining the units used to measure the dimensions of the product. Default value is null.",
    )
    is_taxable: Optional[bool] = Field(
        None,
        title="Is Taxable",
        description="When true, applicable [shop](/documentation/reference#tag/Shop) tax rates apply to this listing at checkout.",
    )
    taxonomy_id: Optional[int] = Field(
        None,
        title="Taxonomy Id",
        description="The numerical taxonomy ID of the listing. See [SellerTaxonomy](/documentation/reference#tag/SellerTaxonomy) and [BuyerTaxonomy](/documentation/reference#tag/BuyerTaxonomy) for more information.",
        ge=1,
    )
    tags: Optional[List[str]] = Field(
        None,
        title="Tags",
        description="A comma-separated list of tag strings for the listing. When creating or updating a listing, valid tag strings contain only letters, numbers, whitespace characters, -, ', ™, ©, and ®. (regex: /[^\\p{L}\\p{Nd}\\p{Zs}\\-'™©®]/u) Default value is null.",
    )
    who_made: Optional[Literal["i_did", "someone_else", "collective"]] = Field(
        None,
        title="Who Made",
        description="An enumerated string indicating who made the product. Helps buyers locate the listing under the Handmade heading. Requires 'is_supply' and 'when_made'.",
    )
    when_made: Optional[
        Literal[
            "made_to_order",
            "2020_2026",
            "2010_2019",
            "2007_2009",
            "before_2007",
            "2000_2006",
            "1990s",
            "1980s",
            "1970s",
            "1960s",
            "1950s",
            "1940s",
            "1930s",
            "1920s",
            "1910s",
            "1900s",
            "1800s",
            "1700s",
            "before_1700",
        ]
    ] = Field(
        None,
        title="When Made",
        description="An enumerated string for the era in which the maker made the product in this listing. Helps buyers locate the listing under the Vintage heading. Requires 'is_supply' and 'who_made'.",
    )
    state: Optional[Literal["active", "inactive"]] = Field(
        None,
        title="State",
        description="When _updating_ a listing, this value can be either `active` or `inactive`. Note: Setting a `draft` listing to `active` will also publish the listing on etsy.com and requires that the listing have an image set. Setting a `sold_out` listing to active will update the quantity to 1 and renew the listing on etsy.com.",
    )
    is_supply: Optional[bool] = Field(
        None,
        title="Is Supply",
        description="When true, tags the listing as a supply product, else indicates that it's a finished product. Helps buyers locate the listing under the Supplies heading. Requires 'who_made' and 'when_made'.",
    )
    production_partner_ids: Optional[List[int]] = Field(
        None,
        title="Production Partner Ids",
        description="An array of unique IDs of production partner ids.",
    )
    type: Optional[Literal["physical", "download", "both"]] = Field(
        None,
        title="Type",
        description="An enumerated type string that indicates whether the listing is physical or a digital download.",
    )
    ecgt_garan_brand: Optional[str] = Field(
        None,
        title="Ecgt Garan Brand",
        description="The brand or trademark name for the EU commercial guarantee (required under GPSR/ECGT for eligible EU traders). Maximum 25 characters. See the [Etsy Seller Handbook](https://help.etsy.com/hc/articles/43191692248343) for details. If any one of ecgt_garan_brand, ecgt_garan_model, ecgt_garan_years, or ecgt_garan_guarantee_details is provided and non-empty, all four are required. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_garan_years: Optional[int] = Field(
        None,
        title="Ecgt Garan Years",
        description="Duration of the EU commercial guarantee in whole years (minimum 3, maximum 99). Required together with ecgt_garan_brand, ecgt_garan_model, and ecgt_garan_guarantee_details. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_garan_model: Optional[str] = Field(
        None,
        title="Ecgt Garan Model",
        description="The product model or reference number for the EU commercial guarantee label. Maximum 20 characters. Required together with ecgt_garan_brand, ecgt_garan_years, and ecgt_garan_guarantee_details. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_garan_guarantee_details: Optional[str] = Field(
        None,
        title="Ecgt Garan Guarantee Details",
        description="Free-text description of the EU commercial guarantee terms and coverage. Maximum 255 characters. Required together with ecgt_garan_brand, ecgt_garan_model, and ecgt_garan_years. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_other_commercial_guarantee_details: Optional[str] = Field(
        None,
        title="Ecgt Other Commercial Guarantee Details",
        description="Free-text details of any additional commercial guarantee or warranty beyond the primary EU commercial guarantee. Maximum 255 characters. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_after_sales_service_info: Optional[str] = Field(
        None,
        title="Ecgt After Sales Service Info",
        description="After-sales service, repairability, or eco-friendly delivery information required under EU GPSR/ECGT regulations. Maximum 255 characters. Silently ignored for digital listings and for sellers who are not eligible EU traders.",
    )
    ecgt_software_update_details: Optional[str] = Field(
        None,
        title="Ecgt Software Update Details",
        description="Details of software update availability and the duration of such updates, as required under EU ECGT regulations for digital content. Maximum 255 characters. Silently ignored for physical listings and for sellers who are not eligible EU traders.",
    )
    gpsr_manufacturer_type: Optional[Literal["seller", "economic_operator"]] = Field(
        None,
        title="Gpsr Manufacturer Type",
        description="Who the manufacturer of this product is, for GPSR (EU General Product Safety Regulation) purposes. Either `seller` (your shop is the manufacturer) or `economic_operator` (a manufacturer record from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints, identified by `gpsr_manufacturer_id`). `seller` is rejected when `who_made` is `someone_else`; use `economic_operator` for items made by a third party. Send `null` to clear. Optional for now; it becomes required for listings from eligible traders that sell into the EU 60 days after these fields were announced. See the [GPSR Economic Operators Tutorial](/documentation/tutorials/gpsr-economic-operators) for eligibility and the full flow.",
    )
    gpsr_manufacturer_id: Optional[int] = Field(
        None,
        title="Gpsr Manufacturer Id",
        description="The `economic_operator_id` of the manufacturer, from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints. Required when `gpsr_manufacturer_type` is `economic_operator`, and rejected when the type is anything else. The operator must belong to this shop and not be deleted. The manufacturer may be located anywhere in the world. If you change `gpsr_manufacturer_type` to `seller` without sending this field, the stored id is cleared for you.",
    )
    gpsr_responsible_person_type: Optional[
        Literal["seller", "economic_operator"]
    ] = Field(
        None,
        title="Gpsr Responsible Person Type",
        description="Who the EU responsible person for this product is, for GPSR purposes. Either `seller` (your shop; only valid when the shop's legal address, or the address on file, is in the European Union) or `economic_operator` (a record from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints, identified by `gpsr_responsible_person_id`, which must have an address in the European Union). Send `null` to clear. Optional for now; it becomes required for listings from eligible traders that sell into the EU 60 days after these fields were announced. See the [GPSR Economic Operators Tutorial](/documentation/tutorials/gpsr-economic-operators) for eligibility and the full flow.",
    )
    gpsr_responsible_person_id: Optional[int] = Field(
        None,
        title="Gpsr Responsible Person Id",
        description="The `economic_operator_id` of the EU responsible person, from the [Shop Economic Operators](/documentation/reference#tag/Shop-Economic-Operators) endpoints. Required when `gpsr_responsible_person_type` is `economic_operator`, and rejected when the type is anything else. The operator must belong to this shop and not be deleted, and its address must be in the European Union. If you change `gpsr_responsible_person_type` to `seller` without sending this field, the stored id is cleared for you.",
    )
    gpsr_serial_number: Optional[str] = Field(
        None,
        title="Gpsr Serial Number",
        description="An optional serial number, batch number, or lot identifier that lets the product be traced for GPSR purposes. Maximum 255 characters. Send `null` to clear.",
    )
    gpsr_safety_warnings: Optional[str] = Field(
        None,
        title="Gpsr Safety Warnings",
        description="Optional free-text safety warnings and safety information for the product regarding GPSR purposes, shown to buyers as product safety information on the listing page (for example age restrictions, choking hazards, or care and handling instructions). Maximum 102,400 characters. Send `null` to clear.",
    )


class EtsyDeleteListingConfig(BaseModel):
    """deleteListing — DELETE /v3/application/listings/{listing_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["delete_listing"] = Field(
        "delete_listing",
        json_schema_extra={
            "const": "delete_listing",
            "ui:hidden": True,
            "x-display-name": "Delete Listing",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    listing_id: int = Field(
        ...,
        title="Listing Id",
        description="The numeric ID for the [listing](/documentation/reference#tag/ShopListing) associated to this transaction.",
        ge=1,
    )


class EtsyGetListingInventoryConfig(BaseModel):
    """getListingInventory — GET /v3/application/listings/{listing_id}/inventory."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_listing_inventory"] = Field(
        "get_listing_inventory",
        json_schema_extra={
            "const": "get_listing_inventory",
            "ui:hidden": True,
            "x-display-name": "Get Listing Inventory",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    listing_id: int = Field(
        ...,
        title="Listing Id",
        description="The numeric ID for the [listing](/documentation/reference#tag/ShopListing) associated to this transaction.",
        ge=1,
    )
    show_deleted: Optional[bool] = Field(
        None,
        title="Show Deleted",
        description="A boolean value for inventory whether to include deleted products and their offerings. Default value is false.",
    )
    includes: Optional[Literal["Listing"]] = Field(
        None,
        title="Includes",
        description="An enumerated string that attaches a valid association. Default value is null.",
    )


class EtsyUpdateListingInventoryConfig(BaseModel):
    """updateListingInventory — PUT /v3/application/listings/{listing_id}/inventory."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["update_listing_inventory"] = Field(
        "update_listing_inventory",
        json_schema_extra={
            "const": "update_listing_inventory",
            "ui:hidden": True,
            "x-display-name": "Update Listing Inventory",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    listing_id: int = Field(
        ...,
        title="Listing Id",
        description="The numeric ID for the [listing](/documentation/reference#tag/ShopListing) associated to this transaction.",
        ge=1,
    )
    max_variations_supported: Optional[Literal["2", "3"]] = Field(
        None,
        title="Max Variations Supported",
        description="This parameter determines whether a third variation can be added to or updated for a listing. It accepts values of 2 or 3, where 3 enables third-variation support.",
    )
    enable_scale_validation: Optional[bool] = Field(
        None,
        title="Enable Scale Validation",
        description="This temporary parameter indicates whether scale validation should be enabled for the request. It will be removed in the near future, at which point scale validation will be mandatory for all requests.",
    )
    products: List[EtsyUpdateListingInventoryConfigProductsItem] = Field(
        ...,
        title="Products",
        description="A JSON array of products available in a listing, even if only one product. All field names in the JSON blobs are lowercase.",
    )
    price_on_property: Optional[List[int]] = Field(
        None,
        title="Price On Property",
        description="An array of unique [listing property](/documentation/reference#operation/getListingInventory) ID integers for the properties that change product prices, if any. For example, if you charge specific prices for different sized products in the same listing, then this array contains the property ID for size.",
    )
    quantity_on_property: Optional[List[int]] = Field(
        None,
        title="Quantity On Property",
        description="An array of unique [listing property](/documentation/reference#operation/getListingInventory) ID integers for the properties that change the quantity of the products, if any. For example, if you stock specific quantities of different colored products in the same listing, then this array contains the property ID for color.",
    )
    sku_on_property: Optional[List[int]] = Field(
        None,
        title="Sku On Property",
        description="An array of unique [listing property](/documentation/reference#operation/getListingInventory) ID integers for the properties that change the product SKU, if any. For example, if you use specific skus for different colored products in the same listing, then this array contains the property ID for color.",
    )
    readiness_state_on_property: Optional[List[int]] = Field(
        None,
        title="Readiness State On Property",
        description="An array of unique [listing property](/documentation/reference#operation/getListingInventory) ID integers for the properties that change processing profile, if any. For example, if you need specific processing profiles for different colored products in the same listing, then this array contains the property ID for color.",
    )


class EtsyListListingImagesConfig(BaseModel):
    """getListingImages — GET /v3/application/listings/{listing_id}/images."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_listing_images"] = Field(
        "list_listing_images",
        json_schema_extra={
            "const": "list_listing_images",
            "ui:hidden": True,
            "x-display-name": "List Listing Images",
            "x-category": "Listings",
            "x-is-trigger": False,
        },
    )
    listing_id: int = Field(
        ...,
        title="Listing Id",
        description="The numeric ID for the [listing](/documentation/reference#tag/ShopListing) associated to this transaction.",
        ge=1,
    )


class EtsyListOrdersConfig(BaseModel):
    """getShopReceipts — GET /v3/application/shops/{shop_id}/receipts."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_orders"] = Field(
        "list_orders",
        json_schema_extra={
            "const": "list_orders",
            "ui:hidden": True,
            "x-display-name": "List Orders",
            "x-category": "Orders",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    min_created: Optional[int] = Field(
        None,
        title="Min Created",
        description="The earliest unix timestamp for when a record was created.",
        ge=946684800,
    )
    max_created: Optional[int] = Field(
        None,
        title="Max Created",
        description="The latest unix timestamp for when a record was created.",
        ge=946684800,
    )
    min_last_modified: Optional[int] = Field(
        None,
        title="Min Last Modified",
        description="The earliest unix timestamp for when a record last changed.",
        ge=946684800,
    )
    max_last_modified: Optional[int] = Field(
        None,
        title="Max Last Modified",
        description="The latest unix timestamp for when a record last changed.",
        ge=946684800,
    )
    limit: Optional[int] = Field(
        25,
        title="Limit",
        description="The maximum number of results to return.",
        ge=1,
        le=100,
    )
    offset: Optional[int] = Field(
        0,
        title="Offset",
        description="The number of records to skip before selecting the first result.",
        ge=0,
    )
    sort_on: Optional[Literal["created", "updated", "receipt_id"]] = Field(
        "created",
        title="Sort On",
        description="The value to sort a search result of listings on.",
    )
    sort_order: Optional[
        Literal["asc", "ascending", "desc", "descending", "up", "down"]
    ] = Field(
        "desc",
        title="Sort Order",
        description="The ascending(up) or descending(down) order to sort receipts by.",
    )
    was_paid: Optional[bool] = Field(
        None,
        title="Was Paid",
        description="When `true`, returns receipts where the seller has received payment for the receipt. When `false`, returns receipts where payment has not been received.",
    )
    was_shipped: Optional[bool] = Field(
        None,
        title="Was Shipped",
        description="When `true`, returns receipts where the seller shipped the product(s) in this receipt. When `false`, returns receipts where shipment has not been set.",
    )
    was_delivered: Optional[bool] = Field(
        None,
        title="Was Delivered",
        description="When `true`, returns receipts that have been marked as delivered. When `false`, returns receipts where shipment has not been marked as delivered.",
    )
    was_canceled: Optional[bool] = Field(
        None,
        title="Was Canceled",
        description="When `true`, the endpoint will only return the canceled receipts. When `false`, the endpoint will only return non-canceled receipts.",
    )
    legacy: Optional[bool] = Field(
        None,
        title="Legacy",
        description="This parameter needed to enable new parameters and response values related to processing profiles.",
    )


class EtsyGetOrderConfig(BaseModel):
    """getShopReceipt — GET /v3/application/shops/{shop_id}/receipts/{receipt_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_order"] = Field(
        "get_order",
        json_schema_extra={
            "const": "get_order",
            "ui:hidden": True,
            "x-display-name": "Get Order",
            "x-category": "Orders",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    receipt_id: int = Field(
        ...,
        title="Receipt Id",
        description="The numeric ID for the [receipt](/documentation/reference#tag/Shop-Receipt) associated to this transaction.",
        ge=1,
    )
    legacy: Optional[bool] = Field(
        None,
        title="Legacy",
        description="This parameter needed to enable new parameters and response values related to processing profiles.",
    )


class EtsyUpdateOrderConfig(BaseModel):
    """updateShopReceipt — PUT /v3/application/shops/{shop_id}/receipts/{receipt_id}."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["update_order"] = Field(
        "update_order",
        json_schema_extra={
            "const": "update_order",
            "ui:hidden": True,
            "x-display-name": "Update Order",
            "x-category": "Orders",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    receipt_id: int = Field(
        ...,
        title="Receipt Id",
        description="The numeric ID for the [receipt](/documentation/reference#tag/Shop-Receipt) associated to this transaction.",
        ge=1,
    )
    legacy: Optional[bool] = Field(
        None,
        title="Legacy",
        description="This parameter needed to enable new parameters and response values related to processing profiles.",
    )
    was_shipped: Optional[bool] = Field(
        None,
        title="Was Shipped",
        description="When `true`, returns receipts where the seller shipped the product(s) in this receipt. When `false`, returns receipts where shipment has not been set.",
    )
    was_paid: Optional[bool] = Field(
        None,
        title="Was Paid",
        description="When `true`, returns receipts where the seller has received payment for the receipt. When `false`, returns receipts where payment has not been received.",
    )


class EtsyCreateShipmentConfig(BaseModel):
    """createReceiptShipment — POST /v3/application/shops/{shop_id}/receipts/{receipt_id}/tracking."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["create_shipment"] = Field(
        "create_shipment",
        json_schema_extra={
            "const": "create_shipment",
            "ui:hidden": True,
            "x-display-name": "Create Shipment",
            "x-category": "Orders",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    receipt_id: int = Field(
        ..., title="Receipt Id", description="The receipt to submit tracking for.", ge=1
    )
    legacy: Optional[bool] = Field(
        None,
        title="Legacy",
        description="This parameter needed to enable new parameters and response values related to processing profiles.",
    )
    tracking_code: Optional[str] = Field(
        None, title="Tracking Code", description="The tracking code for this receipt."
    )
    carrier_name: Optional[str] = Field(
        None, title="Carrier Name", description="The carrier name for this receipt."
    )
    send_bcc: Optional[bool] = Field(
        None,
        title="Send Bcc",
        description="If true, the shipping notification will be sent to the seller as well",
    )
    note_to_buyer: Optional[str] = Field(
        None,
        title="Note To Buyer",
        description="Message to include in notification to the buyer.",
    )
    mail_class: Optional[str] = Field(
        None,
        title="Mail Class",
        description="The service level of postal or carrier service selected for the shipment (e.g., First-Class, Priority, Ground, Express).",
    )
    weight: Optional[float] = Field(
        None, title="Weight", description="The total weight of the package."
    )
    weight_units: Optional[str] = Field(
        None,
        title="Weight Units",
        description="Unit of measurement used for package weight (oz, grams, etc.).",
    )
    length: Optional[float] = Field(
        None, title="Length", description="Longest side of the package."
    )
    width: Optional[float] = Field(
        None, title="Width", description="Second longest side of the package."
    )
    height: Optional[float] = Field(
        None, title="Height", description="Third longest side of the package."
    )
    dimension_units: Optional[str] = Field(
        None,
        title="Dimension Units",
        description="Unit of measurement used for package dimensions (in, cm...).",
    )
    shipping_label_cost: Optional[float] = Field(
        None,
        title="Shipping Label Cost",
        description="The purchase price the seller paid for the shipping label.",
    )
    shipping_label_currency: Optional[str] = Field(
        None,
        title="Shipping Label Currency",
        description="The currency in which the shipping label was purchased.",
    )
    revenue_eligibility: Optional[str] = Field(
        None,
        title="Revenue Eligibility",
        description="A flag indicating if the shipment is tied to a revenue share agreement between Etsy and the vendor.",
    )
    ship_from_country: Optional[str] = Field(
        None, title="Ship From Country", description="Where the package ships from."
    )
    ship_to_country: Optional[str] = Field(
        None, title="Ship To Country", description="Package destination."
    )
    incoterm: Optional[str] = Field(
        None,
        title="Incoterm",
        description="The specific incoterm (e.g., DDU, DDP) designated for the shipment.",
    )
    customs_data: Optional[List[EtsyCreateShipmentConfigCustomsDataItem]] = Field(
        None,
        title="Customs Data",
        description="Contains custom data like country of origin, declared value and HS code.",
    )
    duty_amount: Optional[float] = Field(
        None,
        title="Duty Amount",
        description="The estimated or actual amount of import duties and taxes assessed by customs for the shipment.",
    )
    duty_currency: Optional[str] = Field(
        None,
        title="Duty Currency",
        description="The currency in which the duty was paid.",
    )
    ship_date: Optional[str] = Field(
        None, title="Ship Date", description="The date package was shipped."
    )


class EtsyListOrderTransactionsConfig(BaseModel):
    """getShopReceiptTransactionsByReceipt — GET /v3/application/shops/{shop_id}/receipts/{receipt_id}/transactions."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_order_transactions"] = Field(
        "list_order_transactions",
        json_schema_extra={
            "const": "list_order_transactions",
            "ui:hidden": True,
            "x-display-name": "List Order Transactions",
            "x-category": "Orders",
            "x-is-trigger": False,
        },
    )
    shop_id: int = Field(
        ...,
        title="Shop Id",
        description="The unique positive non-zero numeric ID for an Etsy Shop.",
        ge=1,
    )
    receipt_id: int = Field(
        ...,
        title="Receipt Id",
        description="The numeric ID for the [receipt](/documentation/reference#tag/Shop-Receipt) associated to this transaction.",
        ge=1,
    )
    legacy: Optional[bool] = Field(
        None,
        title="Legacy",
        description="This parameter needed to enable new parameters and response values related to processing profiles.",
    )


EtsyConfig = Annotated[
    Union[
        EtsyGetMeConfig,
        EtsyGetShopConfig,
        EtsyUpdateShopConfig,
        EtsyListShopSectionsConfig,
        EtsyCreateShopSectionConfig,
        EtsyUpdateShopSectionConfig,
        EtsyListShippingProfilesConfig,
        EtsyListListingsConfig,
        EtsyGetListingConfig,
        EtsyCreateDraftListingConfig,
        EtsyUpdateListingConfig,
        EtsyDeleteListingConfig,
        EtsyGetListingInventoryConfig,
        EtsyUpdateListingInventoryConfig,
        EtsyListListingImagesConfig,
        EtsyListOrdersConfig,
        EtsyGetOrderConfig,
        EtsyUpdateOrderConfig,
        EtsyCreateShipmentConfig,
        EtsyListOrderTransactionsConfig,
    ],
    Discriminator("operation"),
]


class EtsyNodeConfig(NodeConfig[EtsyConfig, EtsyTokenCredential]):
    pass


# Explicit operation-to-request mapping, transcribed from the pinned official spec.
OPERATIONS = {
    "get_me": {
        "method": "GET",
        "path": "/v3/application/users/me",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [],
        "content_type": None,
    },
    "get_shop": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}",
        "path_fields": ["shop_id"],
        "query_fields": [],
        "body_fields": [],
        "content_type": None,
    },
    "update_shop": {
        "method": "PUT",
        "path": "/v3/application/shops/{shop_id}",
        "path_fields": ["shop_id"],
        "query_fields": [],
        "body_fields": [
            "title",
            "announcement",
            "sale_message",
            "digital_sale_message",
            "policy_additional",
        ],
        "content_type": "application/x-www-form-urlencoded",
    },
    "list_shop_sections": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}/sections",
        "path_fields": ["shop_id"],
        "query_fields": [],
        "body_fields": [],
        "content_type": None,
    },
    "create_shop_section": {
        "method": "POST",
        "path": "/v3/application/shops/{shop_id}/sections",
        "path_fields": ["shop_id"],
        "query_fields": [],
        "body_fields": ["title"],
        "content_type": "application/x-www-form-urlencoded",
    },
    "update_shop_section": {
        "method": "PUT",
        "path": "/v3/application/shops/{shop_id}/sections/{shop_section_id}",
        "path_fields": ["shop_id", "shop_section_id"],
        "query_fields": [],
        "body_fields": ["title"],
        "content_type": "application/x-www-form-urlencoded",
    },
    "list_shipping_profiles": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}/shipping-profiles",
        "path_fields": ["shop_id"],
        "query_fields": [],
        "body_fields": [],
        "content_type": None,
    },
    "list_listings": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}/listings",
        "path_fields": ["shop_id"],
        "query_fields": [
            "state",
            "limit",
            "offset",
            "sort_on",
            "sort_order",
            "includes",
        ],
        "body_fields": [],
        "content_type": None,
    },
    "get_listing": {
        "method": "GET",
        "path": "/v3/application/listings/{listing_id}",
        "path_fields": ["listing_id"],
        "query_fields": ["includes", "language", "allow_suggested_title"],
        "body_fields": [],
        "content_type": None,
    },
    "create_draft_listing": {
        "method": "POST",
        "path": "/v3/application/shops/{shop_id}/listings",
        "path_fields": ["shop_id"],
        "query_fields": [],
        "body_fields": [
            "quantity",
            "title",
            "description",
            "price",
            "who_made",
            "when_made",
            "taxonomy_id",
            "shipping_profile_id",
            "return_policy_id",
            "materials",
            "shop_section_id",
            "processing_min",
            "processing_max",
            "readiness_state_id",
            "tags",
            "styles",
            "item_weight",
            "item_length",
            "item_width",
            "item_height",
            "item_weight_unit",
            "item_dimensions_unit",
            "production_partner_ids",
            "image_ids",
            "ecgt_garan_brand",
            "ecgt_garan_years",
            "ecgt_garan_model",
            "ecgt_garan_guarantee_details",
            "ecgt_other_commercial_guarantee_details",
            "ecgt_after_sales_service_info",
            "ecgt_software_update_details",
            "gpsr_manufacturer_type",
            "gpsr_manufacturer_id",
            "gpsr_responsible_person_type",
            "gpsr_responsible_person_id",
            "gpsr_serial_number",
            "gpsr_safety_warnings",
            "is_supply",
            "is_customizable",
            "should_auto_renew",
            "is_taxable",
            "type",
        ],
        "content_type": "application/x-www-form-urlencoded",
    },
    "update_listing": {
        "method": "PATCH",
        "path": "/v3/application/shops/{shop_id}/listings/{listing_id}",
        "path_fields": ["shop_id", "listing_id"],
        "query_fields": [],
        "body_fields": [
            "image_ids",
            "title",
            "description",
            "materials",
            "should_auto_renew",
            "shipping_profile_id",
            "return_policy_id",
            "shop_section_id",
            "item_weight",
            "item_length",
            "item_width",
            "item_height",
            "item_weight_unit",
            "item_dimensions_unit",
            "is_taxable",
            "taxonomy_id",
            "tags",
            "who_made",
            "when_made",
            "state",
            "is_supply",
            "production_partner_ids",
            "type",
            "ecgt_garan_brand",
            "ecgt_garan_years",
            "ecgt_garan_model",
            "ecgt_garan_guarantee_details",
            "ecgt_other_commercial_guarantee_details",
            "ecgt_after_sales_service_info",
            "ecgt_software_update_details",
            "gpsr_manufacturer_type",
            "gpsr_manufacturer_id",
            "gpsr_responsible_person_type",
            "gpsr_responsible_person_id",
            "gpsr_serial_number",
            "gpsr_safety_warnings",
        ],
        "content_type": "application/x-www-form-urlencoded",
    },
    "delete_listing": {
        "method": "DELETE",
        "path": "/v3/application/listings/{listing_id}",
        "path_fields": ["listing_id"],
        "query_fields": [],
        "body_fields": [],
        "content_type": None,
    },
    "get_listing_inventory": {
        "method": "GET",
        "path": "/v3/application/listings/{listing_id}/inventory",
        "path_fields": ["listing_id"],
        "query_fields": ["show_deleted", "includes"],
        "body_fields": [],
        "content_type": None,
    },
    "update_listing_inventory": {
        "method": "PUT",
        "path": "/v3/application/listings/{listing_id}/inventory",
        "path_fields": ["listing_id"],
        "query_fields": ["max_variations_supported", "enable_scale_validation"],
        "body_fields": [
            "products",
            "price_on_property",
            "quantity_on_property",
            "sku_on_property",
            "readiness_state_on_property",
        ],
        "content_type": "application/json",
    },
    "list_listing_images": {
        "method": "GET",
        "path": "/v3/application/listings/{listing_id}/images",
        "path_fields": ["listing_id"],
        "query_fields": [],
        "body_fields": [],
        "content_type": None,
    },
    "list_orders": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}/receipts",
        "path_fields": ["shop_id"],
        "query_fields": [
            "min_created",
            "max_created",
            "min_last_modified",
            "max_last_modified",
            "limit",
            "offset",
            "sort_on",
            "sort_order",
            "was_paid",
            "was_shipped",
            "was_delivered",
            "was_canceled",
            "legacy",
        ],
        "body_fields": [],
        "content_type": None,
    },
    "get_order": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}/receipts/{receipt_id}",
        "path_fields": ["shop_id", "receipt_id"],
        "query_fields": ["legacy"],
        "body_fields": [],
        "content_type": None,
    },
    "update_order": {
        "method": "PUT",
        "path": "/v3/application/shops/{shop_id}/receipts/{receipt_id}",
        "path_fields": ["shop_id", "receipt_id"],
        "query_fields": ["legacy"],
        "body_fields": ["was_shipped", "was_paid"],
        "content_type": "application/x-www-form-urlencoded",
    },
    "create_shipment": {
        "method": "POST",
        "path": "/v3/application/shops/{shop_id}/receipts/{receipt_id}/tracking",
        "path_fields": ["shop_id", "receipt_id"],
        "query_fields": ["legacy"],
        "body_fields": [
            "tracking_code",
            "carrier_name",
            "send_bcc",
            "note_to_buyer",
            "mail_class",
            "weight",
            "weight_units",
            "length",
            "width",
            "height",
            "dimension_units",
            "shipping_label_cost",
            "shipping_label_currency",
            "revenue_eligibility",
            "ship_from_country",
            "ship_to_country",
            "incoterm",
            "customs_data",
            "duty_amount",
            "duty_currency",
            "ship_date",
        ],
        "content_type": "application/json",
    },
    "list_order_transactions": {
        "method": "GET",
        "path": "/v3/application/shops/{shop_id}/receipts/{receipt_id}/transactions",
        "path_fields": ["shop_id", "receipt_id"],
        "query_fields": ["legacy"],
        "body_fields": [],
        "content_type": None,
    },
}


def _wire(value: Any) -> str:
    """Lowercase scalar booleans and Etsy's documented CSV form arrays.

    Query arrays are kept as lists to use the spec's default exploded form
    style; CSV form bodies follow the official listings tutorial.
    https://developers.etsy.com/documentation/tutorials/listings/
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(_wire(item) for item in value)
    return str(value)


class EtsyNode(WorkflowNode):
    integration_type = "automation-etsy"
    credential_provider_labels = {"etsy": "Etsy Account"}
    scope_registry = ETSY_SCOPES
    connection_evidence = ConnectionEvidence(
        identity_operation="get_me",
        noun="Etsy account",
        identity_keys=("user_id", "shop_id"),
    )
    edit_examples = [
        "List paid unshipped orders from my Etsy shop",
        "Create a draft Etsy listing",
        "Update stock and prices for my listing variations",
        "Add shipment tracking to an Etsy order",
    ]

    @classmethod
    def get_config_model(cls):
        return EtsyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, EtsyNodeConfig):
            raise ValueError("Valid Etsy configuration is required")
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("Connect your Etsy app key and access token")
        config = self.config.config
        action = config.operation
        self.scope_registry.enforce_credential_type(action, credentials.credential_type)
        route = OPERATIONS[action]
        values = {
            key: value
            for key, value in config.model_dump(mode="json", exclude_unset=True).items()
            if value is not None
        }
        path = route["path"].format(
            **{key: values[key] for key in route["path_fields"]}
        )
        params = {
            key: (
                [_wire(item) for item in values[key]]
                if isinstance(values[key], list)
                else _wire(values[key])
            )
            for key in route["query_fields"]
            if key in values
        }
        body = {key: values[key] for key in route["body_fields"] if key in values}
        headers = {
            "x-api-key": f"{credentials.api_key}:{credentials.shared_secret}",
            "Authorization": f"Bearer {credentials.access_token}",
            "Accept": "application/json",
        }
        kwargs: Dict[str, Any] = {"params": params}
        if route["content_type"] == "application/json":
            kwargs["json"] = body
        elif route["content_type"] == "application/x-www-form-urlencoded":
            headers["Content-Type"] = route["content_type"]
            kwargs["content"] = urlencode(
                {key: _wire(value) for key, value in body.items()}
            )
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    route["method"], ETSY_API_BASE + path, headers=headers, **kwargs
                )
            timing = {"api_request": round((time.monotonic() - start) * 1000, 2)}
            if response.status_code >= 400:
                # Preserve the provider's exact error text (connection validation
                # uses definitive rejection, never a fabricated empty success).
                return {
                    "status": "error",
                    "action": action,
                    "status_code": response.status_code,
                    "error": response.text,
                    "timing_ms": timing,
                }
            if response.status_code == 204:
                return {
                    "status": "success",
                    "action": action,
                    "data": {"deleted": True},
                    "status_code": 204,
                    "timing_ms": timing,
                }
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(
                    "Etsy returned an unexpected response; expected a JSON object"
                )
            if "error" in payload:
                return {
                    "status": "error",
                    "action": action,
                    "error": payload["error"],
                    "status_code": response.status_code,
                    "timing_ms": timing,
                }
            if action == "get_me" and not isinstance(payload.get("user_id"), int):
                raise ValueError("Etsy account response is missing user_id")
            if action.startswith("list_") and not isinstance(
                payload.get("results"), list
            ):
                raise ValueError("Etsy list response is missing results")
            return {
                "status": "success",
                "action": action,
                "data": payload,
                "status_code": response.status_code,
                "timing_ms": timing,
            }
        except (httpx.RequestError, ValueError) as exc:
            return {
                "status": "error",
                "action": action,
                "error": str(exc),
                "timing_ms": {
                    "api_request": round((time.monotonic() - start) * 1000, 2)
                },
            }
