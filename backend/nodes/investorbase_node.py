"""InvestorBase REST API 1.0.0: property research and enterprise user management.

Contract: https://www.investorbase.com/api-docs/openapi.json
Subscriber keys: Account → Integrations. Enterprise keys: issued by InvestorBase.
Every operation makes one request; no automatic retries of searches or writes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.investorbase.com"
CREDENTIAL_TYPE = "investorbase_api_key"


class InvestorBaseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="InvestorBase API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.investorbase.com/api-docs",
            "x-credential-instructions": "Copy your subscriber API key from Account → Integrations. For an enterprise key issued by InvestorBase, choose Enterprise and enter your registered end-user ID for property data requests. Enterprise account management needs an enterprise key. NoClick reads usage (subscriber) or account details (enterprise) to verify the connection.",
        })
    credential_type: Literal["investorbase_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    key_kind: Literal["subscriber", "enterprise"] = Field("subscriber", title="Key kind")
    enterprise_user_id: str | None = Field(None, min_length=1, max_length=500, title="Enterprise end-user ID", description="Your registered user_id. Required for property data calls with an enterprise key; omitted for subscriber keys and account management.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header or whitespace")
        return value

    @field_validator("enterprise_user_id")
    @classmethod
    def user_id(cls, value):
        if value is not None and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a nonempty end-user ID without control characters")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True, allow_inf_nan=False)


class SubjectPropertyDetails(_Input):
    bedrooms: float | None = Field(None, ge=0)
    bathrooms: float | None = Field(None, ge=0)
    square_feet: float | None = Field(None, ge=0)


class ResolveAddress(_Input):
    """Autocomplete a location."""
    operation: Literal['resolve_address'] = Field('resolve_address', title='Autocomplete a location', json_schema_extra={"ui:hidden": True})
    search_string: str = Field(..., min_length=3, description='The partial address or location to search for.')


class SearchBuyers(_Input):
    """Search for buyers."""
    operation: Literal['search_buyers'] = Field('search_buyers', title='Search for buyers', json_schema_extra={"ui:hidden": True})
    address: str | None = Field(None, description='Full street address of the subject property, in the same format `/v1/autocomplete` returns. Preferred over coordinates: we resolve it to the property, which keeps repeat detection and usage tracking accurate. When both are sent, the address wins, and the coordinates are used only if the address cannot be resolved.')
    latitude: float | None = Field(None, ge=-90, le=90, description='Latitude of the subject, in decimal degrees. Send it together with `longitude`. Required when no `address` is sent.')
    longitude: float | None = Field(None, ge=-180, le=180, description='Longitude of the subject, in decimal degrees. Send it together with `latitude`. Required when no `address` is sent.')
    property_types: list[Literal['SFR', 'MFR', 'LAND', 'CONDO', 'MOBILE', 'OTHER']] = Field(['SFR', 'CONDO', 'MOBILE', 'MFR'], description='Property types to include: `SFR` single family, `MFR` multifamily, `CONDO` condominium, `MOBILE` mobile or manufactured home, `LAND` vacant land, `OTHER` commercial and other properties. Omitted, null or empty means `SFR`, `CONDO`, `MOBILE` and `MFR`, as in the app.')
    buyer_types: list[Literal['flipper', 'landlord']] = Field(['flipper', 'landlord'], description='Buyer types to include. Omitted, null or empty means both.')
    radius_miles: float = Field(2, le=10, gt=0, description='How far from the subject to look, in miles, up to 10. Omitted or null means 2 miles.')
    lookback_years: float = Field(2, le=5, gt=0, description='How far back to look for purchases, in years, up to 5. Fractions work: `0.25` is 3 months. Omitted or null means 2 years.')
    min_bedrooms: int | None = Field(None, ge=0, le=100, description="Fewest bedrooms on the buyer's property. Omitted or null means no minimum.")
    max_bedrooms: int | None = Field(None, ge=0, le=100, description="Most bedrooms on the buyer's property. Omitted or null means no maximum.")
    min_bathrooms: float | None = Field(None, ge=0, le=100, description="Fewest bathrooms on the buyer's property. Omitted or null means no minimum.")
    max_bathrooms: float | None = Field(None, ge=0, le=100, description="Most bathrooms on the buyer's property. Omitted or null means no maximum.")
    min_purchase_price: int | None = Field(None, ge=0, le=9007199254740991, description='Lowest price, in dollars, the buyer paid for the property. Omitted or null means no minimum.')
    max_purchase_price: int | None = Field(None, ge=0, le=9007199254740991, description='Highest price, in dollars, the buyer paid for the property. Omitted or null means no maximum.')
    hide_non_arms_length: StrictBool = Field(True, description='Leaves out purchases that were not made on the open market, such as transfers between relatives. Omitted or null means `true`.')
    hide_hedge_fund: StrictBool = Field(True, description='Leaves out large institutional landlords. Omitted or null means `true`.')
    hide_no_phone: StrictBool = Field(False, description='Leaves out buyers without a phone number after skiptracing. Omitted or null means `false`.')
    min_portfolio_size: int | None = Field(None, ge=1, le=100000, description='Only buyers who still hold at least this many properties, as `portfolio_size` reports, so it also leaves out buyers with no portfolio on record and most flippers. A high minimum can return fewer buyers than `limit`. Omitted or null means no minimum.')
    limit: int | None = Field(None, ge=1, le=100, description='Most buyers to return, from 1 to 100: the nearest ones, ranked among themselves. The search may return fewer. A smaller limit comes back faster and still counts as one search.')
    create_deal: StrictBool = Field(True, description='Creates the deal for the searched property in your CRM and attaches the buyers found, the same as a search in the app. Searching the same address again reuses its deal. Only applies to a search by `address`. Omitted or null means `true`; send `false` to skip it.')
    async_search: StrictBool = Field(False, alias="async", description='When true, the request returns `202` with a `search_id` right away and the search runs in the background. Get the outcome from `GET /v1/buyer-search` or `webhook_url`.')
    webhook_url: str | None = Field(None, description='An https URL we POST the outcome to when the search completes or fails. Works in sync and async modes.')
    webhook_secret: str | None = Field(None, description='Sent back as the `x-webhook-secret` header on webhook calls, so you can verify they came from InvestorBase.')
    results_in_webhook: StrictBool = Field(False, description='When true, the completed webhook includes the full results array.')

    @model_validator(mode="after")
    def location(self):
        if not (self.address and self.address.strip()) and (self.latitude is None or self.longitude is None):
            raise ValueError("Send address or both latitude and longitude")
        for low, high in ((self.min_bedrooms, self.max_bedrooms), (self.min_bathrooms, self.max_bathrooms), (self.min_purchase_price, self.max_purchase_price)):
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")
        if self.webhook_url:
            from urllib.parse import urlsplit
            url = urlsplit(self.webhook_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Webhook URL must use HTTPS without user information")
        return self


class GetBuyerSearchResults(_Input):
    """Get async search results."""
    operation: Literal['get_buyer_search_results'] = Field('get_buyer_search_results', title='Get async search results', json_schema_extra={"ui:hidden": True})
    search_id: str = Field(..., min_length=1, description='The `search_id` an async `POST /v1/buyer-search` returned.')


class GetRetailComps(_Input):
    """Get retail comps for a property."""
    operation: Literal['get_retail_comps'] = Field('get_retail_comps', title='Get retail comps for a property', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., description='Full street address of the subject property, in the same format `/v1/autocomplete` returns. Required.')
    max_radius_miles: float | None = Field(None, ge=0, description='Maximum distance from the subject property, in miles.')
    max_days_back: float | None = Field(None, description='How many days back to look for sales, for example 90, 180 or 365.')
    living_square_feet_min: float | None = Field(None, description='Minimum interior living area, in square feet.')
    living_square_feet_max: float | None = Field(None, description='Maximum interior living area, in square feet.')
    bedrooms_min: float | None = Field(None, description='Minimum number of bedrooms.')
    bedrooms_max: float | None = Field(None, description='Maximum number of bedrooms. Must not be lower than `bedrooms_min`.')
    bathrooms_min: float | None = Field(None, description='Minimum number of bathrooms.')
    bathrooms_max: float | None = Field(None, description='Maximum number of bathrooms.')


class SearchInvestorActivity(_Input):
    """Search investor activity near a location."""
    operation: Literal['search_investor_activity'] = Field('search_investor_activity', title='Search investor activity near a location', json_schema_extra={"ui:hidden": True})
    latitude: float = Field(..., ge=-90, le=90, description='Latitude of the search center, in decimal degrees.')
    longitude: float = Field(..., ge=-180, le=180, description='Longitude of the search center, in decimal degrees.')
    property_types: list[Literal['SFR', 'MFR', 'LAND', 'CONDO', 'MOBILE', 'OTHER']] = Field(['SFR'], description='Property types to include: `SFR` single family, `MFR` multifamily, `CONDO` condominium, `MOBILE` mobile or manufactured home, `LAND` vacant land, `OTHER` commercial and other properties. Omitted, null or empty means `SFR`.')
    flipper_weight: float = Field(0.5, description='Target share of results that are flippers: `1` returns only flippers and `0` only landlords. Values outside 0 to 1 are clamped. Omitted or null means `0.5`.')


class GetMarketSummary(_Input):
    """Summarize the investor market near a location."""
    operation: Literal['get_market_summary'] = Field('get_market_summary', title='Summarize the investor market near a location', json_schema_extra={"ui:hidden": True})
    latitude: float = Field(..., ge=-90, le=90, description='Latitude of the search center, in decimal degrees.')
    longitude: float = Field(..., ge=-180, le=180, description='Longitude of the search center, in decimal degrees.')
    property_types: list[Literal['SFR', 'MFR', 'LAND', 'CONDO', 'MOBILE', 'OTHER']] = Field(['SFR'], description='Property types to include: `SFR` single family, `MFR` multifamily, `CONDO` condominium, `MOBILE` mobile or manufactured home, `LAND` vacant land, `OTHER` commercial and other properties. Omitted, null or empty means `SFR`.')
    lookback_months: int = Field(24, ge=1, le=60, description='Months of transaction history to include.')
    metrics_radius_mi: float = Field(2, le=10, gt=0, description='Radius in miles for `flipper_metrics` and `landlord_metrics`. Values below 0.1 are treated as 0.1. `radius_counts` always covers 1, 2, 5 and 10 miles.')


class GetInvestorComps(_Input):
    """Find investor comps."""
    operation: Literal['get_investor_comps'] = Field('get_investor_comps', title='Find investor comps', json_schema_extra={"ui:hidden": True})
    latitude: float = Field(..., ge=-90, le=90, description='Latitude of the subject property, in decimal degrees.')
    longitude: float = Field(..., ge=-180, le=180, description='Longitude of the subject property, in decimal degrees.')
    property_types: list[Literal['SFR', 'MFR', 'LAND', 'CONDO', 'MOBILE', 'OTHER']] = Field(['SFR'], description='Property types to include: `SFR` single family, `MFR` multifamily, `CONDO` condominium, `MOBILE` mobile or manufactured home, `LAND` vacant land, `OTHER` commercial and other properties. Omitted, null or empty means `SFR`.')
    subject_property_details: SubjectPropertyDetails | None = Field(None, description='Describe the subject property to get ranked comps. Every field is optional: send what you know, even `{}`. When this object is omitted, results are not ranked.')


class GetBuyerHistory(_Input):
    """Get a buyer's deal history."""
    operation: Literal['get_buyer_history'] = Field('get_buyer_history', title="Get a buyer's deal history", json_schema_extra={"ui:hidden": True})
    search_string: str | None = Field(None, min_length=1, description="The buyer's entity name, or their full mailing address as one string. For an address, pass the `address` value returned by `/v1/autocomplete` for the best match.")
    search_state: str | None = Field(None, description='Two-letter US state code of the entity. Required when `is_entity_name` is true or omitted, ignored for mailing address and property lookups.')
    is_entity_name: StrictBool = Field(True, description='`true` when `search_string` is an entity or owner name, `false` when it is a mailing address.')
    strict_matches_only: StrictBool = Field(True, description="`true` matches only on the dimension you searched. `false` also follows the buyer's other key (their mailing address for a name search, their name for an address search), which returns more deals with a higher risk of false positives.")
    property_address: str | None = Field(None, min_length=1, max_length=300, description='The address of a property the buyer bought, exactly as it came back: the `address` of a `/v1/buyer-search` result, or of a purchase on a CRM deal. Pass it with `buyer_type` instead of `search_string` to get exactly that buyer, with no name to match.')
    buyer_type: Literal['flipper', 'landlord'] | None = Field(None, description='The buyer type that came with `property_address`.')
    deal_type: Literal['flip', 'rental'] | None = Field(None, description="Only the buyer's flips, or only their rentals.")
    lookback_months: int | None = Field(None, ge=1, le=120, description='Only deals the buyer bought within this many months, from 1 to 120. A flip counts from its purchase, not its sale.')

    @model_validator(mode="after")
    def buyer(self):
        if self.property_address:
            if not self.buyer_type:
                raise ValueError("Property lookup requires buyer_type")
        elif not self.search_string or not self.search_string.strip():
            raise ValueError("Send property_address with buyer_type, or search_string")
        elif self.is_entity_name is not False and (not self.search_state or len(self.search_state) != 2):
            raise ValueError("Entity lookup requires a two-letter search_state")
        return self


class GetUsage(_Input):
    """Get your usage."""
    operation: Literal['get_usage'] = Field('get_usage', title='Get your usage', json_schema_extra={"ui:hidden": True})


class GetAccountDetails(_Input):
    """Get account details."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise key"})
    operation: Literal['get_account_details'] = Field('get_account_details', title='Get account details', json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    """Get a user and their usage."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise key"})
    operation: Literal['get_user'] = Field('get_user', title='Get a user and their usage', json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description='Your identifier for the end user.')


class CreateUser(_Input):
    """Create a user."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise key"})
    operation: Literal['create_user'] = Field('create_user', title='Create a user', json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description='Your own identifier for the end user. Send the same value as `x-user-id` on data requests.')


class UpdateUser(_Input):
    """Activate or deactivate a user."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise key"})
    operation: Literal['update_user'] = Field('update_user', title='Activate or deactivate a user', json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description='Your own identifier for the end user. Send the same value as `x-user-id` on data requests.')
    active: StrictBool = Field(..., description='`false` deactivates the user and every one of their subscriptions. `true` reactivates the user only; reactivate subscriptions through `PATCH /v1/api-user-subscriptions`.')


class CreateUserSubscription(_Input):
    """Assign a plan to a user."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise key"})
    operation: Literal['create_user_subscription'] = Field('create_user_subscription', title='Assign a plan to a user', json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description='Your identifier for an active end user.')
    plan_id: str = Field(..., min_length=1, description='The plan to assign, taken from `available_plans` in `GET /v1/api-credentials`.')


class UpdateUserSubscription(_Input):
    """Activate or deactivate a subscription."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise key"})
    operation: Literal['update_user_subscription'] = Field('update_user_subscription', title='Activate or deactivate a subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., min_length=1, description='The `id` returned when the subscription was created.')
    active: StrictBool = Field(..., description='`true` reactivates the subscription, `false` deactivates it.')


Operation = Annotated[Union[ResolveAddress, SearchBuyers, GetBuyerSearchResults, GetRetailComps, SearchInvestorActivity, GetMarketSummary, GetInvestorComps, GetBuyerHistory, GetUsage, GetAccountDetails, GetUser, CreateUser, UpdateUser, CreateUserSubscription, UpdateUserSubscription], Field(discriminator="operation")]


class InvestorBaseConfig(NodeConfig[Operation, InvestorBaseAPIKeyCredential]):
    pass


ROUTES = {'resolve_address': ('POST', '/v1/autocomplete', (200,)),
 'search_buyers': ('POST', '/v1/buyer-search', (200, 202)),
 'get_buyer_search_results': ('GET', '/v1/buyer-search', (200,)),
 'get_retail_comps': ('POST', '/v1/retail-comps', (200,)),
 'search_investor_activity': ('POST', '/v1/analytics-search', (200,)),
 'get_market_summary': ('POST', '/v1/analytics-summary', (200,)),
 'get_investor_comps': ('POST', '/v1/investor-comps', (200,)),
 'get_buyer_history': ('POST', '/v1/linked-deals', (200,)),
 'get_usage': ('GET', '/v1/usage', (200,)),
 'get_account_details': ('GET', '/v1/api-credentials', (200,)),
 'get_user': ('GET', '/v1/api-users', (200,)),
 'create_user': ('POST', '/v1/api-users', (201,)),
 'update_user': ('PATCH', '/v1/api-users', (200,)),
 'create_user_subscription': ('POST', '/v1/api-user-subscriptions', (201,)),
 'update_user_subscription': ('PATCH', '/v1/api-user-subscriptions', (200,))}


class InvestorBaseNode(WorkflowNode):
    integration_type = "automation-investorbase"
    connection_evidence = ConnectionEvidence(field="account", noun="InvestorBase account usage")

    @classmethod
    def get_config_model(cls):
        return InvestorBaseConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an InvestorBase API key")
        credential = self.config.credentials
        config = self.config.config
        method, path, statuses = ROUTES[config.operation]
        enterprise_only = path.startswith("/v1/api-")
        if enterprise_only and credential.key_kind != "enterprise":
            raise ValueError("This operation needs an enterprise API key issued by InvestorBase")
        if config.operation == "get_usage" and credential.key_kind != "subscriber":
            raise ValueError("Usage is available for subscriber keys; use account details or get user with an enterprise key")
        headers = {"x-api-key": credential.api_key, "Accept": "application/json"}
        if not enterprise_only and config.operation != "get_usage" and credential.key_kind == "enterprise":
            if not credential.enterprise_user_id:
                raise ValueError("Enter the registered enterprise end-user ID in your credential for property data calls")
            headers["x-user-id"] = credential.enterprise_user_id
        payload = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        kwargs = {"params": payload} if method == "GET" else {"json": payload}
        if method != "GET":
            headers["Content-Type"] = "application/json"
        # Buyer searches can take time. Do not retry: they may create a CRM deal,
        # consume an allowance or have already completed after a lost response.
        async with guarded_async_client(timeout=120, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        if response.status_code not in statuses:
            message = "InvestorBase did not confirm this request"
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("error"), str):
                    message = body["error"]
            except ValueError:
                if response.status_code == 429:
                    message = "InvestorBase rate limit reached; wait before retrying"
            # Keys must never be returned through a provider's diagnostic echo.
            message = message.replace(credential.api_key, "[redacted]")
            if getattr(config, "webhook_secret", None):
                message = message.replace(config.webhook_secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message[:2000]}
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if mime != "application/json":
            raise ValueError("InvestorBase returned an unexpected response format")
        data = response.json()
        if isinstance(data, dict) and (data.get("error") or data.get("success") is False):
            raise ValueError("InvestorBase returned an error in a successful HTTP response")
        if response.status_code == 202:
            if not isinstance(data, dict) or not isinstance(data.get("search_id"), str) or not data["search_id"]:
                raise ValueError("InvestorBase did not return the async search ID")
            return {"status": "pending", "http_status": 202, "search_id": data["search_id"], "data": data}
        if config.operation == "get_buyer_search_results" and data is None:
            return {"status": "pending", "http_status": 200, "search_id": config.search_id, "data": None}
        array_ops = {"resolve_address", "search_buyers", "get_buyer_search_results", "search_investor_activity", "get_investor_comps"}
        if config.operation in array_ops:
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("InvestorBase returned an unexpected result list")
        elif not isinstance(data, dict) or not data:
            raise ValueError("InvestorBase returned an unexpected result object")
        return {"status": "success", "http_status": response.status_code, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        """Credential-only evidence, using the same reads and transport as execution."""
        if field_name != "account":
            raise ValueError("Unknown InvestorBase option field")
        credential = InvestorBaseAPIKeyCredential.model_validate(credential_data)
        from nodes.core.registry import NodeFactory
        operation = "get_usage" if credential.key_kind == "subscriber" else "get_account_details"
        node = NodeFactory.create_node(node_id="investorbase-evidence", node_type=cls.integration_type,
            node_data={"config": {"operation": operation}, "credentials": credential.model_dump()})
        result = await node.execute({})
        if result["status"] != "success":
            # The evidence seam reads the error envelope and HTTP status itself.
            return result
        data = result["data"]
        if credential.key_kind == "enterprise":
            label = data.get("account_name")
            if not isinstance(label, str) or not label:
                raise ValueError("InvestorBase account response omitted the account name")
        else:
            period, company = data.get("period"), data.get("company")
            if not isinstance(period, dict) or not isinstance(company, dict) or not isinstance(data.get("plan"), str):
                raise ValueError("InvestorBase usage response omitted account usage")
            used = company.get("buyer_search", {}).get("used")
            if not isinstance(period.get("resets_at"), str) or type(used) is not int:
                raise ValueError("InvestorBase usage response omitted the period or buyer search count")
            label = f"{data['plan']} · {used} buyer searches · resets {period['resets_at']}"
        return {"options": [{"value": "account", "label": label}], "next_page_token": None}
