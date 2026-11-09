"""Yelp Places API operations, pinned to Yelp's published OpenAPI 1.0 contracts.

Requests use a manually supplied API key. Partner-only endpoints still require
Yelp to enable access for that key. Responses preserve the provider JSON.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class YelpAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Yelp API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.yelp.com/developers/v3/manage_app",
            "x-credential-instructions": "Paste your Yelp Places API key from Manage API Access. Yelp must enable partner endpoints such as engagement for your key. NoClick sends it only to api.yelp.com. Connecting checks key reachability using the public category catalog; it does not verify business ownership.",
        })
    credential_type: Literal["yelp_api_key"] = Field("yelp_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key without a Bearer prefix")
        return value


class YelpInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def supported_values(self):
        for name in ("business_id_or_alias", "event_id", "alias"):
            value = getattr(self, name, None)
            if value is not None and (not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value)):
                raise ValueError("Use a single Yelp resource ID or alias")
        for name in ("categories", "excluded_events", "attributes", "business_ids"):
            values = getattr(self, name, None)
            if values is not None and (not values or len(values) != len(set(values)) or any(not v.strip() or "," in v for v in values)):
                raise ValueError("Use distinct nonempty values without commas")
        price = getattr(self, "price", None)
        if price is not None and (not price or len(price) != len(set(price))):
            raise ValueError("Use distinct price levels")
        if hasattr(self, "latitude"):
            latitude, longitude = getattr(self, "latitude", None), getattr(self, "longitude", None)
            if (latitude is None) != (longitude is None):
                raise ValueError("Provide both latitude and longitude")
            if self.operation in {"search_businesses", "search_delivery", "get_featured_event"} and not getattr(self, "location", None) and latitude is None:
                raise ValueError("Provide a location or latitude and longitude")
        if getattr(self, "open_now", None) is True and getattr(self, "open_at", None) is not None:
            raise ValueError("Choose open_now or open_at")
        for start, end in (("start_date", "end_date"), ("date_range_start", "date_range_end")):
            a, b = getattr(self, start, None), getattr(self, end, None)
            if a is not None and b is not None and a > b:
                raise ValueError("End must be on or after start")
        return self


class ChatLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)


class ChatRequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skip_text_generation: StrictBool = False


class YelpChatConfig(YelpInput):
    """Yelp AI API (Search & Chat). https://docs.developer.yelp.com/reference/v2_ai_chat"""
    operation: Literal['chat'] = Field('chat', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=1000)
    chat_id: str | None = None
    user_context: ChatLocation | None = None
    request_context: ChatRequestContext | None = None

class YelpSearchBusinessesConfig(YelpInput):
    """Search. https://docs.developer.yelp.com/reference/v3_business_search"""
    operation: Literal['search_businesses'] = Field('search_businesses', json_schema_extra={"ui:hidden": True})
    location: str | None = Field(None, min_length=1, max_length=250)
    latitude: float | None = Field(None, allow_inf_nan=False, ge=-90, le=90)
    longitude: float | None = Field(None, allow_inf_nan=False, ge=-180, le=180)
    term: str | None = Field(None, max_length=300)
    radius: int | None = Field(None, ge=0, le=40000)
    categories: list[str] | None = Field(None)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')
    price: list[Annotated[int, Field(ge=1, le=4)]] | None = Field(None, max_length=4)
    open_now: StrictBool | None = Field(None)
    open_at: int | None = Field(None)
    attributes: list[str] | None = Field(None)
    sort_by: Literal['best_match', 'rating', 'review_count', 'distance'] = Field('best_match')
    device_platform: Literal['android', 'ios', 'mobile-generic'] | None = Field(None)
    reservation_date: str | None = Field(None)
    reservation_time: str | None = Field(None)
    reservation_covers: int | None = Field(None, ge=1, le=10)
    matches_party_size_param: StrictBool | None = Field(None)
    job_alias: str | None = Field(None)
    limit: int = Field(20, ge=0, le=50)
    offset: int | None = Field(None, ge=0, le=1000)

class YelpSearchBusinessesByPhoneConfig(YelpInput):
    """Phone Search. https://docs.developer.yelp.com/reference/v3_business_phone_search"""
    operation: Literal['search_businesses_by_phone'] = Field('search_businesses_by_phone', json_schema_extra={"ui:hidden": True})
    phone: str = Field(..., min_length=1, max_length=32, pattern='^[0-9 +()-.x/]+$')
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')

class YelpMatchBusinessesConfig(YelpInput):
    """Business Match. https://docs.developer.yelp.com/reference/v3_business_match"""
    operation: Literal['match_businesses'] = Field('match_businesses', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=64)
    address1: str = Field(..., max_length=64)
    address2: str | None = Field(None, max_length=64)
    address3: str | None = Field(None, max_length=64)
    city: str = Field(..., min_length=1, max_length=64)
    state: str = Field(..., min_length=1, max_length=3)
    country: str = Field(..., min_length=2, max_length=2, pattern='[A-Z]{2}')
    postal_code: str | None = Field(None, max_length=12)
    latitude: float | None = Field(None, allow_inf_nan=False, ge=-90, le=90)
    longitude: float | None = Field(None, allow_inf_nan=False, ge=-180, le=180)
    phone: str | None = Field(None, min_length=1, max_length=32, pattern='^[0-9 +()-.x/]+$')
    yelp_business_id: str | None = Field(None, min_length=22, max_length=22)
    limit: int = Field(3, ge=1, le=10)
    match_threshold: Literal['none', 'default', 'strict'] = Field('default')

class YelpGetBusinessConfig(YelpInput):
    """Business Details. https://docs.developer.yelp.com/reference/v3_business_info"""
    operation: Literal['get_business'] = Field('get_business', json_schema_extra={"ui:hidden": True})
    business_id_or_alias: str = Field(..., min_length=1, max_length=250)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')
    device_platform: Literal['android', 'ios', 'mobile-generic'] | None = Field(None)

class YelpSearchDeliveryConfig(YelpInput):
    """Food Delivery Search. https://docs.developer.yelp.com/reference/v3_transaction_search"""
    operation: Literal['search_delivery'] = Field('search_delivery', json_schema_extra={"ui:hidden": True})
    transaction_type: Literal['delivery'] = Field('delivery')
    latitude: float | None = Field(None, allow_inf_nan=False, ge=-90, le=90)
    longitude: float | None = Field(None, allow_inf_nan=False, ge=-180, le=180)
    location: str | None = Field(None, min_length=1, max_length=250)
    term: str | None = Field(None, max_length=300)
    categories: list[str] | None = Field(None)
    price: list[Annotated[int, Field(ge=1, le=4)]] | None = Field(None, max_length=4)

class YelpGetBusinessEngagementConfig(YelpInput):
    """Engagement Metrics. https://docs.developer.yelp.com/reference/v3_get_businesses_engagement"""
    operation: Literal['get_business_engagement'] = Field('get_business_engagement', json_schema_extra={"ui:hidden": True})
    business_ids: list[str] = Field(..., max_length=20)
    date_range_start: date | None = Field(None)
    date_range_end: date | None = Field(None)

class YelpGetServiceOfferingsConfig(YelpInput):
    """Service Offerings. https://docs.developer.yelp.com/reference/v3_business_service_offerings"""
    operation: Literal['get_service_offerings'] = Field('get_service_offerings', json_schema_extra={"ui:hidden": True})
    business_id_or_alias: str = Field(..., min_length=1, max_length=250)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')

class YelpListCategoriesConfig(YelpInput):
    """All Categories. https://docs.developer.yelp.com/reference/v3_all_categories"""
    operation: Literal['list_categories'] = Field('list_categories', json_schema_extra={"ui:hidden": True})
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')

class YelpGetCategoryConfig(YelpInput):
    """Category Details. https://docs.developer.yelp.com/reference/v3_categories"""
    operation: Literal['get_category'] = Field('get_category', json_schema_extra={"ui:hidden": True})
    alias: str = Field(..., min_length=1, max_length=250)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')

class YelpSearchEventsConfig(YelpInput):
    """Event Search. https://docs.developer.yelp.com/reference/v3_events_search"""
    operation: Literal['search_events'] = Field('search_events', json_schema_extra={"ui:hidden": True})
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')
    offset: int | None = Field(None, ge=0, le=1000)
    limit: int = Field(3, ge=0, le=50)
    sort_by: Literal['asc', 'desc'] = Field('desc')
    sort_on: Literal['popularity', 'time_start'] = Field('popularity')
    start_date: int | None = Field(None, ge=-2208960000, le=221845420800)
    end_date: int | None = Field(None, ge=-2208960000, le=221845420800)
    categories: list[str] | None = Field(None)
    is_free: StrictBool | None = Field(None)
    excluded_events: list[str] | None = Field(None)
    location: str | None = Field(None, min_length=1, max_length=250)
    latitude: float | None = Field(None, allow_inf_nan=False, ge=-90, le=90)
    longitude: float | None = Field(None, allow_inf_nan=False, ge=-180, le=180)
    radius: int | None = Field(None, ge=0, le=40000)

class YelpGetEventConfig(YelpInput):
    """Event Details. https://docs.developer.yelp.com/reference/v3_event"""
    operation: Literal['get_event'] = Field('get_event', json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=250)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')

class YelpGetFeaturedEventConfig(YelpInput):
    """Featured Event. https://docs.developer.yelp.com/reference/v3_featured_event"""
    operation: Literal['get_featured_event'] = Field('get_featured_event', json_schema_extra={"ui:hidden": True})
    location: str | None = Field(None, min_length=1, max_length=250)
    latitude: float | None = Field(None, allow_inf_nan=False, ge=-90, le=90)
    longitude: float | None = Field(None, allow_inf_nan=False, ge=-180, le=180)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')

class YelpAutocompleteConfig(YelpInput):
    """Autocomplete. https://docs.developer.yelp.com/reference/v3_autocomplete"""
    operation: Literal['autocomplete'] = Field('autocomplete', json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')
    latitude: float | None = Field(None, allow_inf_nan=False, ge=-90, le=90)
    longitude: float | None = Field(None, allow_inf_nan=False, ge=-180, le=180)

class YelpGetReviewsConfig(YelpInput):
    """Reviews. https://docs.developer.yelp.com/reference/v3_business_reviews"""
    operation: Literal['get_reviews'] = Field('get_reviews', json_schema_extra={"ui:hidden": True})
    business_id_or_alias: str = Field(..., min_length=1, max_length=250)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')
    offset: int | None = Field(None, ge=0, le=1000)
    limit: int = Field(20, ge=0, le=50)
    sort_by: Literal['yelp_sort'] = Field('yelp_sort')

class YelpGetReviewHighlightsConfig(YelpInput):
    """Review Highlights. https://docs.developer.yelp.com/reference/v3_business_review_highlights"""
    operation: Literal['get_review_highlights'] = Field('get_review_highlights', json_schema_extra={"ui:hidden": True})
    business_id_or_alias: str = Field(..., min_length=1, max_length=250)
    count: int = Field(3)
    locale: str | None = Field(None, pattern='^[a-z]{2,3}_[A-Z]{2}$')


YelpConfig = Annotated[Union[
    YelpChatConfig,
    YelpSearchBusinessesConfig,
    YelpSearchBusinessesByPhoneConfig,
    YelpMatchBusinessesConfig,
    YelpGetBusinessConfig,
    YelpSearchDeliveryConfig,
    YelpGetBusinessEngagementConfig,
    YelpGetServiceOfferingsConfig,
    YelpListCategoriesConfig,
    YelpGetCategoryConfig,
    YelpSearchEventsConfig,
    YelpGetEventConfig,
    YelpGetFeaturedEventConfig,
    YelpAutocompleteConfig,
    YelpGetReviewsConfig,
    YelpGetReviewHighlightsConfig
], Field(discriminator="operation")]


class YelpFullConfig(NodeConfig[YelpConfig, YelpAPIKeyCredential]):
    pass


ROUTES = {'chat': ('POST', '/ai/chat/v2', ()),
 'search_businesses': ('GET', '/v3/businesses/search', ()),
 'search_businesses_by_phone': ('GET', '/v3/businesses/search/phone', ()),
 'match_businesses': ('GET', '/v3/businesses/matches', ()),
 'get_business': ('GET', '/v3/businesses/{business_id_or_alias}', ('business_id_or_alias',)),
 'search_delivery': ('GET', '/v3/transactions/{transaction_type}/search', ('transaction_type',)),
 'get_business_engagement': ('GET', '/v3/businesses/engagement', ()),
 'get_service_offerings': ('GET',
                           '/v3/businesses/{business_id_or_alias}/service_offerings',
                           ('business_id_or_alias',)),
 'list_categories': ('GET', '/v3/categories', ()),
 'get_category': ('GET', '/v3/categories/{alias}', ('alias',)),
 'search_events': ('GET', '/v3/events', ()),
 'get_event': ('GET', '/v3/events/{event_id}', ('event_id',)),
 'get_featured_event': ('GET', '/v3/events/featured', ()),
 'autocomplete': ('GET', '/v3/autocomplete', ()),
 'get_reviews': ('GET', '/v3/businesses/{business_id_or_alias}/reviews', ('business_id_or_alias',)),
 'get_review_highlights': ('GET',
                           '/v3/businesses/{business_id_or_alias}/review_highlights',
                           ('business_id_or_alias',))}


class YelpNode(WorkflowNode):
    integration_type = "automation-yelp"
    connection_evidence = ConnectionEvidence(
        noun="Yelp category catalog", operation="list_categories", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return YelpFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Yelp API key")
        config = self.config.config
        method, path, path_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        params = None
        body = None
        if method == "GET":
            params = {key: ",".join(str(x) for x in value) if isinstance(value, list)
                      else str(value).lower() if isinstance(value, bool) else value
                      for key, value in values.items()}
        else:
            body = values
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.yelp.com" + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            # Preserve provider rejection words so the shared connect seam can judge
            # a rejected key. Never leak the supplied secret through error echoes.
            message = response.text[:4000].replace(key, "[redacted]")
            raise ValueError(f"Yelp HTTP {response.status_code}: {message}")
        if len(response.content) > 10_000_000:
            raise ValueError("Yelp response exceeded the JSON size limit")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "application/json":
            raise ValueError("Expected a JSON response from Yelp")
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Yelp returned an invalid JSON response")
        return {"status": "success", "data": data}
