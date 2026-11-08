"""Fidel API v1: one published REST operation per automation action.

Contracts: https://fidel-oaas.readme.io/openapi/591c6a2c1fc800190041951d
https://fidel-oaas.readme.io/openapi/6696a8b4216d12003e4ae89f
https://fidel-oaas.readme.io/openapi/6a9fbe8dfd6e626eef16776d
Collections return a single page; provider count and last cursor remain intact.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.fidel.uk"


class FidelAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Fidel API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.fidel.uk/",
            "x-credential-instructions": "Copy a test or live secret API key from your Fidel Dashboard. Paste the key alone. NoClick sends it in the Fidel-Key header. Test keys access test data; live writes require a live key with the corresponding account permissions.",
        },
    )
    credential_type: Literal["fidel_api_key"] = Field(
        "fidel_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        repr=False,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FidelCreateBrandConfig(_Input):
    "Create Brand"
    operation: Literal["create_brand"] = Field(
        "create_brand", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        description="Name of the Brand. 2 - 50 characters. Must be unique for account.",
    )
    website_url: str | None = Field(None, description="URL for the Brand.")
    logo_url: str | None = Field(
        None, description="URL of the Brand logo in GIF, JPG, JPEG or PNG format."
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Metadata object with custom index and properties. Object size limited to 2kb.",
    )


class FidelListBrandsConfig(_Input):
    "List Brands"
    operation: Literal["list_brands"] = Field(
        "list_brands", json_schema_extra={"ui:hidden": True}
    )
    limit: str | None = Field(
        None, description="limit the number of responses from the API"
    )
    start: str | None = Field(
        None,
        description='Tells the API where the previous response left off. Use ${encodeURIComponent(JSON.stringify(last))}, where "last" is the parameter from the previous query.',
    )
    order: str | None = Field(
        None, description="possible values [asc, desc] of 'created' date."
    )
    name: str | None = Field(None, description="search by brand name")


class FidelGetBrandConfig(_Input):
    "Get Brand"
    operation: Literal["get_brand"] = Field(
        "get_brand", json_schema_extra={"ui:hidden": True}
    )
    brand_id: str = Field(
        ..., description="the brandId you are looking to obtain information on."
    )


class FidelUpdateBrandConfig(_Input):
    "Update Brand"
    operation: Literal["update_brand"] = Field(
        "update_brand", json_schema_extra={"ui:hidden": True}
    )
    brand_id: str = Field(..., description="Id for the Brand you want to update.")
    website_url: str | None = Field(None, description="URL for the Brand.")
    logo_url: str | None = Field(
        None, description="URL of the Brand logo in GIF, JPG, JPEG or PNG format."
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Metadata object with custom index and properties. Object size limited to 2kb.",
    )


class FidelDeleteBrandConfig(_Input):
    "Delete Brand"
    operation: Literal["delete_brand"] = Field(
        "delete_brand", json_schema_extra={"ui:hidden": True}
    )
    brand_id: str = Field(..., description="The BrandId to be deleted")


class FidelCreateProgramConfig(_Input):
    "Create Program"
    operation: Literal["create_program"] = Field(
        "create_program", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., description="Name of the Program. 4 - 50 characters.")
    icon: str | None = Field(
        None,
        description="Emoji to associate with the Program. Also used on the Fidel Dashboard. Uses the `:emoji-name:` format. Accepts between 4 and 200 characters.",
    )
    icon_background: str | None = Field(
        None,
        description='Background color for the program icon. Used on the Fidel Dashboard. Accepts a HEX CSS string, like "#333333".',
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Metadata object with custom index and properties. Object size limited to 2kb.",
    )


class FidelListProgramsConfig(_Input):
    "List Programs"
    operation: Literal["list_programs"] = Field(
        "list_programs", json_schema_extra={"ui:hidden": True}
    )
    limit: str | None = Field(None, description="Number of Programs to return.")
    start: str | None = Field(
        None,
        description='Tells the API where the previous response left off. Use ${encodeURIComponent(JSON.stringify(last))}, where "last" is the parameter from the previous query.',
    )
    order: str | None = Field(
        None, description="possible values [asc, desc] of 'created' date."
    )


class FidelGetProgramConfig(_Input):
    "Get Program"
    operation: Literal["get_program"] = Field(
        "get_program", json_schema_extra={"ui:hidden": True}
    )
    program_id: str = Field(..., description="The programId you wish to 'GET\"")


class FidelUpdateProgramConfig(_Input):
    "Update Program"
    operation: Literal["update_program"] = Field(
        "update_program", json_schema_extra={"ui:hidden": True}
    )
    program_id: str = Field(..., description="ProgramId to be edited")
    name: str | None = Field(
        None, description="Name for the Program. Can be 4 - 50 characters long."
    )
    icon: str | None = Field(
        None,
        description="Emoji to associate with the Program. Also used on the Fidel Dashboard. Uses the `:emoji-name:` format. Accepts between 4 and 200 characters.",
    )
    icon_background: str | None = Field(
        None,
        description='Background color for the program icon. Used on the Fidel Dashboard. Accepts a HEX CSS string, like "#333333".',
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Metadata object with custom properties. Object size limited to 2kb.",
    )
    status: str | None = Field(
        None,
        description="Program status. Used to sync all locations in a program. This only works with live programs, so make sure the programId you're using is from a live program. And you're using a live API key as well.",
    )


class FidelDeleteWebhookConfig(_Input):
    "Delete Webhook"
    operation: Literal["delete_webhook"] = Field(
        "delete_webhook", json_schema_extra={"ui:hidden": True}
    )
    hook_id: str = Field(...)


class FidelUpdateWebhookConfig(_Input):
    "Update Webhook"
    operation: Literal["update_webhook"] = Field(
        "update_webhook", json_schema_extra={"ui:hidden": True}
    )
    hook_id: str = Field(...)
    program_id: str | None = Field(None, description="Only on Program Level webhooks.")
    event: str | None = Field(None)
    url: str | None = Field(None)
    headers: dict[str, Any] | None = Field(
        None,
        description="A custom header key name that must be between 1 and 64 characters and only accepts roman alphabet, number, dash and underscore. And a value that must be between 1 and 1000 characters.",
    )


class FidelGetWebhookConfig(_Input):
    "Get Webhook"
    operation: Literal["get_webhook"] = Field(
        "get_webhook", json_schema_extra={"ui:hidden": True}
    )
    hook_id: str = Field(..., description="Webhook hookId")


class FidelListWebhooksConfig(_Input):
    "List Webhooks"
    operation: Literal["list_webhooks"] = Field(
        "list_webhooks", json_schema_extra={"ui:hidden": True}
    )
    limit: str | None = Field(None, description="Number of webhooks to return")
    event: str | None = Field(
        None, description="Use any event name to filter for that event."
    )
    program_id: str = Field(...)


class FidelCreateWebhookProgramConfig(_Input):
    "Create Webhook (Program)"
    operation: Literal["create_webhook_program"] = Field(
        "create_webhook_program", json_schema_extra={"ui:hidden": True}
    )
    program_id: str = Field(...)
    event: str | None = Field(
        None,
        description="The type of event. (values: marketplace.offer.live, marketplace.offer.updated)",
    )
    url: str | None = Field(None, description="URL destination of the event.")
    headers: dict[str, Any] | None = Field(
        None,
        description="A custom header key name that must be between 1 and 64 characters and only accepts roman alphabet, number, dash and underscore. And a value that must be between 1 and 1000 characters.",
    )


class FidelCreateWebhookBrandConfig(_Input):
    "Create Webhook (Brand)"
    operation: Literal["create_webhook_brand"] = Field(
        "create_webhook_brand", json_schema_extra={"ui:hidden": True}
    )
    event: str | None = Field(
        None, description="The type of event. (values: brand.consent)"
    )
    url: str | None = Field(None, description="URL destination of the event.")
    headers: dict[str, Any] | None = Field(
        None,
        description="A custom header key name that must be between 1 and 64 characters and only accepts roman alphabet, number, dash and underscore. And a value that must be between 1 and 1000 characters.",
    )


class FidelCreateOfferConfigType(_Input):
    name: str = Field(
        ...,
        description="The name property can have one of the following two values: [amount, discount]",
    )
    value: float = Field(
        ...,
        description="fixed amount of currency to be rewarded or the percentage value in case of a discount offer.",
    )
    max_reward_amount: float | None = Field(
        None,
        description="Maximum amount to be rewarded. Available for offers where the 'type.name' is 'discount'.",
    )


class FidelCreateOfferConfigFees(_Input):
    fidel_fee: float | None = Field(
        None, description="Percentage of reward for Fidel fee"
    )
    publisher_fee: float | None = Field(
        None, description="Percentage of reward for Publisher Fee"
    )
    uncapped_fidel_fee: bool | None = Field(
        None, description="Uncapped Fidel Fee only when offer with maxRewardAmount"
    )
    uncapped_publisher_fee: bool | None = Field(
        None, description="Uncapped Fidel Fee only when offer with maxRewardAmount"
    )


class FidelCreateOfferConfigMaxredemptions(_Input):
    transactions_limit: int | None = Field(None)
    period: int | None = Field(None)
    unit: Literal["day", "month", "year"] | None = Field(None)


class FidelCreateOfferConfigBudget(_Input):
    limit: int | None = Field(None)
    period: int | None = Field(None)
    unit: Literal["day", "month", "year"] | None = Field(None)


class FidelCreateOfferConfigTargeting(_Input):
    name: Literal["new", "lapsed", "existing"] | None = Field(
        None, description="The type of targeting"
    )
    from_: int | None = Field(
        None, description="number of days, required if lapsed or existing"
    )
    to: int | None = Field(
        None, description="number of days, required if lapsed or existing"
    )


class FidelCreateOfferConfig(_Input):
    "Create Offer"
    operation: Literal["create_offer"] = Field(
        "create_offer", json_schema_extra={"ui:hidden": True}
    )
    program_id: str = Field(...)
    brand_id: str = Field(..., description="Id of the Brand.")
    country_code: str = Field(
        ..., description="SO 3166-1 alpha-3 country code where the offer is active."
    )
    name: str = Field(..., description="Name of the offer, 2 - 50 characters long.")
    start_date: str = Field(
        ...,
        description="Starting date when offer starts qualifying transactions in the format YYYY-MM-DDThh:mm:ss",
    )
    type: FidelCreateOfferConfigType = Field(...)
    additional_terms: str | None = Field(None, description="Offer T&C")
    days_of_week: list[int] | None = Field(
        None,
        description="Array of numbers between 0 and 6 representing the days of the week. Starting on Sunday.",
    )
    end_date: str | None = Field(
        None,
        description="End date for the offer in the format YYYY-MM-DDThh:mm:ss. Can be at most 1 year from start date (default iIf not set/null)",
    )
    min_transaction_amount: str | None = Field(
        None, description="Minimum transaction amount to qualify for the offer."
    )
    schemes: list[str] | None = Field(
        None,
        description="Schemes where the offer will qualify. Possible values are [visa, mastercard, amex].",
    )
    channels: list[str] | None = Field(
        None, description="Type of offer, can be in-store and/or online"
    )
    short_description: str | None = Field(None, description="Short offer description")
    long_description: str | None = Field(None, description="Long offer description")
    requires_approval: bool | None = Field(
        None, description="As a content provider, if is an offer subject to approval"
    )
    fees: FidelCreateOfferConfigFees | None = Field(
        None, description="Commission percentages on top of the reward cashback"
    )
    max_redemptions: FidelCreateOfferConfigMaxredemptions | None = Field(
        None,
        description="Set a limit of transactions per card per unit (day/month/year)",
    )
    budget: FidelCreateOfferConfigBudget | None = Field(
        None, description="Set a budget limit per unit (day/month/year)"
    )
    metadata: dict[str, Any] | None = Field(None)
    targeting: FidelCreateOfferConfigTargeting | None = Field(
        None, description="Set a targeting type"
    )


class FidelUpdateOfferConfigType(_Input):
    name: str = Field(
        ...,
        description="The name property can have one of the following two values: [amount, discount]",
    )
    value: float = Field(
        ...,
        description="fixed amount of currency to be rewarded or the percentage value in case of a discount offer.",
    )
    max_reward_amount: float | None = Field(
        None,
        description="Maximum amount to be rewarded. Available for offers where the 'type.name' is 'discount'.",
    )


class FidelUpdateOfferConfig(_Input):
    "Update Offer"
    operation: Literal["update_offer"] = Field(
        "update_offer", json_schema_extra={"ui:hidden": True}
    )
    offer_id: str = Field(..., description="ID of the offer")
    end_date: str | None = Field(None)
    start_date: str | None = Field(None)
    channels: list[str] | None = Field(None)
    days_of_week: str | None = Field(None)
    short_description: str | None = Field(None)
    long_description: str | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    name: str | None = Field(None)
    schemes: str | None = Field(None)
    type: FidelUpdateOfferConfigType | None = Field(None)
    min_transaction_amount: int | None = Field(None)


class FidelDeleteOfferConfig(_Input):
    "Delete Offer"
    operation: Literal["delete_offer"] = Field(
        "delete_offer", json_schema_extra={"ui:hidden": True}
    )
    offer_id: str = Field(...)


class FidelListOffersConfig(_Input):
    "List Offers"
    operation: Literal["list_offers"] = Field(
        "list_offers", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, description="Max number of items per response")
    start: str | None = Field(
        None, description="Pagination token from last response 'last'"
    )
    select: Literal["count"] | None = Field(
        None, description="Select to only return count of items"
    )
    status: str | None = Field(
        None,
        description='current status for the offers you want to filter for. available values: "requests", "upcoming", "live", "expired"',
    )
    activation: bool | None = Field(
        None, description="filters if offer has activation enabled"
    )
    approval: bool | None = Field(
        None, description="filters if offer requires approval"
    )
    brand_id: str | None = Field(None, description="filter by brand ID")
    content_provider_id: str | None = Field(
        None, description="filter by Content Provider ID"
    )
    country_code: str | None = Field(
        None, description="filter by Country Code possible values"
    )
    network: str | None = Field(
        None, description="filter by network. possible values[amex, mastercard, visa]"
    )
    program_id: str | None = Field(None, description="filter by program ID")
    channel: str | None = Field(
        None,
        description="filter by Channel. possible values [in-store, online, not-specified]",
    )
    end_date: bool | None = Field(None, description="filter offers with end date set")
    expiring_in_days: int | None = Field(
        None,
        description="filter to include offers that will be expired in 'expiringInDays' days (0-366)",
    )


class FidelCreateOfferDescriptorConfig(_Input):
    "Create Offer Descriptor"
    operation: Literal["create_offer_descriptor"] = Field(
        "create_offer_descriptor", json_schema_extra={"ui:hidden": True}
    )
    offer_id: str = Field(..., description="ID of the offer")
    name: str = Field(..., description="Value of merchant descriptor")


class FidelListOfferDescriptorsConfig(_Input):
    "List Offer Descriptors"
    operation: Literal["list_offer_descriptors"] = Field(
        "list_offer_descriptors", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, description="Max number of items per response")
    start: str | None = Field(
        None, description="Pagination token from last response 'last'"
    )
    select: Literal["count"] | None = Field(
        None, description="Select to only return count of items"
    )
    offer_id: str = Field(...)


class FidelDeleteOfferDescriptorConfig(_Input):
    "Delete Offer Descriptor"
    operation: Literal["delete_offer_descriptor"] = Field(
        "delete_offer_descriptor", json_schema_extra={"ui:hidden": True}
    )
    offer_id: str = Field(...)
    descriptor_id: str = Field(...)


class FidelListOfferLocationsConfig(_Input):
    "List Offer Locations"
    operation: Literal["list_offer_locations"] = Field(
        "list_offer_locations", json_schema_extra={"ui:hidden": True}
    )
    offer_id: str = Field(...)
    limit: int | None = Field(None)
    start: str | None = Field(None)
    select: Literal["count"] | None = Field(None)


class FidelCreateOfferLocationConfig(_Input):
    "Create Offer Location"
    operation: Literal["create_offer_location"] = Field(
        "create_offer_location", json_schema_extra={"ui:hidden": True}
    )
    offer_id: str = Field(...)
    address: str = Field(...)
    city: str = Field(...)
    country: str = Field(...)
    zip_code: str = Field(...)
    latitude: float | None = Field(None)
    longitude: float | None = Field(None)
    state: str | None = Field(None)


class FidelListTransactionsByProgramConfig(_Input):
    "List transactions"
    operation: Literal["list_transactions_by_program"] = Field(
        "list_transactions_by_program", json_schema_extra={"ui:hidden": True}
    )
    program_id: str = Field(...)
    type: Literal["valid", "invalid"] | None = Field(
        None, description="Defaults to `valid`."
    )
    filename: str | None = Field(None, min_length=1, max_length=512)
    from_: str | None = Field(
        None,
        description="Inclusive start of the creation-time range. Must be within the last year.",
    )
    to: str | None = Field(
        None, description="Inclusive end of the creation-time range."
    )
    limit: int | None = Field(None, ge=1)
    order: Literal["asc", "desc"] | None = Field(None)
    start: str | None = Field(
        None, description="Cursor returned in the preceding response's `last` field."
    )
    select: Literal["count"] | None = Field(
        None, description="Set to `count` to omit transaction items."
    )


FidelOperation = Annotated[
    Union[
        FidelCreateBrandConfig,
        FidelListBrandsConfig,
        FidelGetBrandConfig,
        FidelUpdateBrandConfig,
        FidelDeleteBrandConfig,
        FidelCreateProgramConfig,
        FidelListProgramsConfig,
        FidelGetProgramConfig,
        FidelUpdateProgramConfig,
        FidelDeleteWebhookConfig,
        FidelUpdateWebhookConfig,
        FidelGetWebhookConfig,
        FidelListWebhooksConfig,
        FidelCreateWebhookProgramConfig,
        FidelCreateWebhookBrandConfig,
        FidelCreateOfferConfig,
        FidelUpdateOfferConfig,
        FidelDeleteOfferConfig,
        FidelListOffersConfig,
        FidelCreateOfferDescriptorConfig,
        FidelListOfferDescriptorsConfig,
        FidelDeleteOfferDescriptorConfig,
        FidelListOfferLocationsConfig,
        FidelCreateOfferLocationConfig,
        FidelListTransactionsByProgramConfig,
    ],
    Field(discriminator="operation"),
]


class FidelFullConfig(NodeConfig[FidelOperation, FidelAPIKeyCredential]):
    pass


# Each action maps to exactly one operation in the published contracts.
ROUTES = {
    "create_brand": {
        "method": "POST",
        "path": "/v1/brands",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "website_url": "websiteURL",
            "logo_url": "logoURL",
            "metadata": "metadata",
        },
        "success_codes": [201],
    },
    "list_brands": {
        "method": "GET",
        "path": "/v1/brands",
        "path_fields": {},
        "query_fields": {
            "limit": "limit",
            "start": "start",
            "order": "order",
            "name": "name",
        },
        "body_fields": {},
        "success_codes": [200],
    },
    "get_brand": {
        "method": "GET",
        "path": "/v1/brands/{brandId}",
        "path_fields": {"brand_id": "brandId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [200],
    },
    "update_brand": {
        "method": "PATCH",
        "path": "/v1/brands/{brandId}",
        "path_fields": {"brand_id": "brandId"},
        "query_fields": {},
        "body_fields": {
            "website_url": "websiteURL",
            "logo_url": "logoURL",
            "metadata": "metadata",
        },
        "success_codes": [200],
    },
    "delete_brand": {
        "method": "DELETE",
        "path": "/v1/brands/{brandId}",
        "path_fields": {"brand_id": "brandId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [204],
    },
    "create_program": {
        "method": "POST",
        "path": "/v1/programs",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "icon": "icon",
            "icon_background": "iconBackground",
            "metadata": "metadata",
        },
        "success_codes": [201],
    },
    "list_programs": {
        "method": "GET",
        "path": "/v1/programs",
        "path_fields": {},
        "query_fields": {"limit": "limit", "start": "start", "order": "order"},
        "body_fields": {},
        "success_codes": [200],
    },
    "get_program": {
        "method": "GET",
        "path": "/v1/programs/{programId}",
        "path_fields": {"program_id": "programId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [200],
    },
    "update_program": {
        "method": "PATCH",
        "path": "/v1/programs/{programId}",
        "path_fields": {"program_id": "programId"},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "icon": "icon",
            "icon_background": "iconBackground",
            "metadata": "metadata",
            "status": "status",
        },
        "success_codes": [200],
    },
    "delete_webhook": {
        "method": "DELETE",
        "path": "/v1/hooks/{hookId}",
        "path_fields": {"hook_id": "hookId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [204],
    },
    "update_webhook": {
        "method": "PATCH",
        "path": "/v1/hooks/{hookId}",
        "path_fields": {"hook_id": "hookId"},
        "query_fields": {},
        "body_fields": {
            "program_id": "programId",
            "event": "event",
            "url": "url",
            "headers": "headers",
        },
        "success_codes": [200],
    },
    "get_webhook": {
        "method": "GET",
        "path": "/v1/hooks/{hookId}",
        "path_fields": {"hook_id": "hookId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [200],
    },
    "list_webhooks": {
        "method": "GET",
        "path": "/v1/programs/{programId}/hooks",
        "path_fields": {"program_id": "programId"},
        "query_fields": {"limit": "limit", "event": "event"},
        "body_fields": {},
        "success_codes": [200],
    },
    "create_webhook_program": {
        "method": "POST",
        "path": "/v1/programs/{programId}/hooks",
        "path_fields": {"program_id": "programId"},
        "query_fields": {},
        "body_fields": {"event": "event", "url": "url", "headers": "headers"},
        "success_codes": [201],
    },
    "create_webhook_brand": {
        "method": "POST",
        "path": "/v1/hooks",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {"event": "event", "url": "url", "headers": "headers"},
        "success_codes": [201],
    },
    "create_offer": {
        "method": "POST",
        "path": "/v1/programs/{programId}/offers",
        "path_fields": {"program_id": "programId"},
        "query_fields": {},
        "body_fields": {
            "brand_id": "brandId",
            "country_code": "countryCode",
            "name": "name",
            "start_date": "startDate",
            "type": "type",
            "additional_terms": "additionalTerms",
            "days_of_week": "daysOfWeek",
            "end_date": "endDate",
            "min_transaction_amount": "minTransactionAmount",
            "schemes": "schemes",
            "channels": "channels",
            "short_description": "shortDescription",
            "long_description": "longDescription",
            "requires_approval": "requiresApproval",
            "fees": "fees",
            "max_redemptions": "maxRedemptions",
            "budget": "budget",
            "metadata": "metadata",
            "targeting": "targeting",
        },
        "success_codes": [201],
    },
    "update_offer": {
        "method": "PATCH",
        "path": "/v1/offers/{offerId}",
        "path_fields": {"offer_id": "offerId"},
        "query_fields": {},
        "body_fields": {
            "end_date": "endDate",
            "start_date": "startDate",
            "channels": "channels",
            "days_of_week": "daysOfWeek",
            "short_description": "shortDescription",
            "long_description": "longDescription",
            "metadata": "metadata",
            "name": "name",
            "schemes": "schemes",
            "type": "type",
            "min_transaction_amount": "minTransactionAmount",
        },
        "success_codes": [200],
    },
    "delete_offer": {
        "method": "DELETE",
        "path": "/v1/offers/{offerId}",
        "path_fields": {"offer_id": "offerId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [204],
    },
    "list_offers": {
        "method": "GET",
        "path": "/v1/offers",
        "path_fields": {},
        "query_fields": {
            "limit": "limit",
            "start": "start",
            "select": "select",
            "status": "status",
            "activation": "activation",
            "approval": "approval",
            "brand_id": "brandId",
            "content_provider_id": "contentProviderId",
            "country_code": "countryCode",
            "network": "network",
            "program_id": "programId",
            "channel": "channel",
            "end_date": "endDate",
            "expiring_in_days": "expiringInDays",
        },
        "body_fields": {},
        "success_codes": [200],
    },
    "create_offer_descriptor": {
        "method": "POST",
        "path": "/v1/offers/{offerId}/descriptors",
        "path_fields": {"offer_id": "offerId"},
        "query_fields": {},
        "body_fields": {"name": "name"},
        "success_codes": [201],
    },
    "list_offer_descriptors": {
        "method": "GET",
        "path": "/v1/offers/{offerId}/descriptors",
        "path_fields": {"offer_id": "offerId"},
        "query_fields": {"limit": "limit", "start": "start", "select": "select"},
        "body_fields": {},
        "success_codes": [200],
    },
    "delete_offer_descriptor": {
        "method": "DELETE",
        "path": "/v1/offers/{offerId}/descriptors/{descriptorId}",
        "path_fields": {"offer_id": "offerId", "descriptor_id": "descriptorId"},
        "query_fields": {},
        "body_fields": {},
        "success_codes": [204],
    },
    "list_offer_locations": {
        "method": "GET",
        "path": "/v1/offers/{offerId}/locations",
        "path_fields": {"offer_id": "offerId"},
        "query_fields": {"limit": "limit", "start": "start", "select": "select"},
        "body_fields": {},
        "success_codes": [200],
    },
    "create_offer_location": {
        "method": "POST",
        "path": "/v1/offers/{offerId}/location",
        "path_fields": {"offer_id": "offerId"},
        "query_fields": {},
        "body_fields": {
            "address": "address",
            "city": "city",
            "country": "country",
            "zip_code": "zipCode",
            "latitude": "latitude",
            "longitude": "longitude",
            "state": "state",
        },
        "success_codes": [201],
    },
    "list_transactions_by_program": {
        "method": "GET",
        "path": "/v1/programs/{programId}/transactions",
        "path_fields": {"program_id": "programId"},
        "query_fields": {
            "type": "type",
            "filename": "filename",
            "from_": "from",
            "to": "to",
            "limit": "limit",
            "order": "order",
            "start": "start",
            "select": "select",
        },
        "body_fields": {},
        "success_codes": [200],
    },
}

_BODY_NAMES = {
    "name": "name",
    "website_url": "websiteURL",
    "logo_url": "logoURL",
    "metadata": "metadata",
    "custom_key": "customKey",
    "icon": "icon",
    "icon_background": "iconBackground",
    "status": "status",
    "program_ids": "programIds",
    "program_id": "programId",
    "event": "event",
    "url": "url",
    "headers": "headers",
    "brand_id": "brandId",
    "country_code": "countryCode",
    "start_date": "startDate",
    "type": "type",
    "value": "value",
    "max_reward_amount": "maxRewardAmount",
    "additional_terms": "additionalTerms",
    "days_of_week": "daysOfWeek",
    "end_date": "endDate",
    "min_transaction_amount": "minTransactionAmount",
    "schemes": "schemes",
    "channels": "channels",
    "short_description": "shortDescription",
    "long_description": "longDescription",
    "requires_approval": "requiresApproval",
    "fees": "fees",
    "fidel_fee": "fidelFee",
    "publisher_fee": "publisherFee",
    "uncapped_fidel_fee": "uncappedFidelFee",
    "uncapped_publisher_fee": "uncappedPublisherFee",
    "max_redemptions": "maxRedemptions",
    "transactions_limit": "transactionsLimit",
    "period": "period",
    "unit": "unit",
    "budget": "budget",
    "limit": "limit",
    "targeting": "targeting",
    "from_": "from",
    "to": "to",
    "scheme": "scheme",
    "network_identifiers": "networkIdentifiers",
    "se_number": "seNumber",
    "vsid": "vsid",
    "vmid": "vmid",
    "caid": "caid",
    "bin": "bin",
    "merchant_id": "merchantId",
    "location_id": "locationId",
    "address": "address",
    "city": "city",
    "country": "country",
    "zip_code": "zipCode",
    "latitude": "latitude",
    "longitude": "longitude",
    "state": "state",
}


def _body_value(value):
    if isinstance(value, BaseModel):
        return {
            _BODY_NAMES.get(k, k): _body_value(v)
            for k in type(value).model_fields
            if (v := getattr(value, k)) is not None
        }
    if isinstance(value, list):
        return [_body_value(v) for v in value]
    # User metadata and custom headers must retain their exact keys.
    return value


class FidelAPINode(WorkflowNode):
    integration_type = "automation-fidel-api"
    connection_evidence = ConnectionEvidence(noun="brands", operation="list_brands")

    @classmethod
    def get_config_model(cls):
        return FidelFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not isinstance(credential, FidelAPIKeyCredential):
            raise ValueError("Attach a Fidel API key")
        route = ROUTES[config.operation]
        path = route["path"]
        for field, name in route["path_fields"].items():
            value = getattr(config, field)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
                raise ValueError("Use a single Fidel resource ID without a URL or path")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {}
        for field, name in route["query_fields"].items():
            value = getattr(config, field)
            if value is not None:
                params[name] = str(value).lower() if isinstance(value, bool) else value
        body = {
            name: _body_value(getattr(config, field))
            for field, name in route["body_fields"].items()
            if getattr(config, field) is not None
        }
        headers = {
            "Fidel-Key": credential.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                route["method"],
                BASE_URL + path,
                headers=headers,
                params=params,
                **({"json": body} if route["body_fields"] else {}),
            )
        if response.status_code not in route["success_codes"]:
            message = "Fidel API rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("error")
                    message = str(
                        error.get("message")
                        or (
                            detail.get("message")
                            if isinstance(detail, dict)
                            else detail
                        )
                        or message
                    )
            except ValueError:
                pass
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message.replace(credential.api_key, "[redacted]"),
            }
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Fidel API returned an invalid JSON response") from None
        if not isinstance(payload, dict):
            raise ValueError("Fidel API returned an unexpected response shape")
        if payload.get("error") or payload.get("errors"):
            return {"status": "error", "error": "Fidel API returned an error envelope"}
        # Keep provider pagination (count/last) and resources intact, without following links.
        return {
            "status": "success",
            "http_status": response.status_code,
            "data": payload,
        }
