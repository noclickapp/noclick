"""Vibe advertising automation, pinned to the official 2026-06-01 contract.

Each operation maps to one resource request. Lists expose a single offset page;
writes acknowledge the API response without claiming independent readback.
https://cdn.apps.vibe.co/open-api/public-api/2026-06-01/latest.yaml
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.vibe import VIBE_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.vibe.co"
REVISION = "2026-06-01"
FAMILY = "vibe_oauth"


class VibeOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Vibe OAuth", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "vibe",
            "x-oauth-scopes": VIBE_SCOPES.declared_scopes(),
            "x-credential-url": "https://vibe.co/dashboard/settings/my-applications",
            "x-credential-instructions": "Connect your Vibe account. The instance administrator must register a Vibe OAuth app and configure VIBE_CLIENT_ID, VIBE_CLIENT_SECRET and VIBE_REDIRECT_URI. Vibe approval is needed for other users to connect. For manual import, paste an OAuth access token; it expires in about 30 minutes unless a refresh token and expiry are also supplied. Legacy API keys are not supported.",
        })
    credential_type: Literal["vibe_oauth"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token expiry", description="ISO 8601 UTC expiry, when importing a refreshable OAuth token.")
    scope: str | None = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="OAuth token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class VibeOptimizationTarget(_Input):
    type: Literal['COST_PER_SESSION', 'COST_PER_LEAD', 'COST_PER_CALL', 'COST_PER_PURCHASE', 'ROAS', 'CPM', 'COST_PER_INSTALL', 'COST_PER_UNIQUE_HOUSEHOLD', 'COST_PER_UNIQUE_COMPANY'] = Field(...)
    value: float = Field(..., ge=1, description='Target value in USD (max 2 decimals)')


class VibeTargeting(_Input):
    geo: VibeGeoTargeting | None = Field(None)
    inventory: VibeInventoryTargeting | None = Field(None)
    age_ranges: list[Literal['RANGE_18_20', 'RANGE_21_24', 'RANGE_25_34', 'RANGE_35_44', 'RANGE_45_54', 'RANGE_55_64', 'RANGE_65_MORE']] | None = Field(None)
    genders: list[Literal['MALE', 'FEMALE']] | None = Field(None)
    devices: list[Literal['TV', 'TABLET', 'MOBILE']] | None = Field(None)
    interests: list[str] | None = Field(None)
    audiences: VibeAudienceTargeting | None = Field(None)
    dayparting: VibeDayparting | None = Field(None)


class VibeGeoTargeting(_Input):
    regions: VibeIncludeExcludeList | None = Field(None)
    cities: VibeIncludeExcludeList | None = Field(None)
    metro_codes: VibeIncludeExcludeList | None = Field(None)
    zip_codes: VibeIncludeExcludeList | None = Field(None)


class VibeIncludeExcludeList(_Input):
    include: list[str] | None = Field(None)
    exclude: list[str] | None = Field(None)


class VibeInventoryTargeting(_Input):
    type: Literal['APPS_AND_CHANNELS', 'LIVE_SPORTS'] | None = Field(None)
    include: list[str] | None = Field(None)
    exclude: list[str] | None = Field(None)


class VibeAudienceTargeting(_Input):
    upload: VibeIncludeExcludeUuid | None = Field(None)


class VibeIncludeExcludeUuid(_Input):
    include: list[UUID] | None = Field(None)
    exclude: list[UUID] | None = Field(None)


class VibeDayparting(_Input):
    preset: Literal['CUSTOM', 'ANY_TIME_ANY_DAY', 'PRIMETIME', 'AFTER_WORK', 'WORK_HOURS', 'SLEEPING_TIME', 'WEEKEND', 'WORK_DAYS'] | None = Field(None)
    custom_ranges: list[VibeDaypartingRange] | None = Field(None, description='Minutes from midnight Monday (0–10079). Only used when preset=CUSTOM.')


class VibeDaypartingRange(_Input):
    start: int = Field(..., ge=0, le=10079)
    end: int = Field(..., ge=0, le=10079)


class VibeReportFilter(_Input):
    dimension: Literal['event_source_id', 'campaign_id', 'strategy_id'] = Field(..., description='Dimension to filter on')
    values: list[str] | None = Field(None, min_length=1, description='Values to include')


class VibeListAccountsConfig(_Input):
    'List accounts.'
    operation: Literal['list_accounts'] = Field('list_accounts', title='List accounts')



class VibeListAdvertisersConfig(_Input):
    'List advertisers.'
    operation: Literal['list_advertisers'] = Field('list_advertisers', title='List advertisers')
    id: UUID | None = Field(None)
    name: str | None = Field(None)
    url: str | None = Field(None)
    limit: int = Field(20, ge=1)
    offset: int = Field(0, ge=0)
    account_id: int | None = Field(None)


class VibeCreateAdvertiserConfig(_Input):
    'Create an advertiser.'
    operation: Literal['create_advertiser'] = Field('create_advertiser', title='Create an advertiser')
    account_id: int | None = Field(None)
    name: str = Field(...)
    url: str = Field(..., description='The brand-owned website of the advertiser. Marketplace, app store and social media pages are rejected.', json_schema_extra={'format': 'uri'})
    industry: Literal['AUTOMOTIVE', 'EDUCATION', 'FINANCIAL_SERVICES', 'FOOD_DRINK', 'FOOD_DRINK_WINE', 'GAMING', 'GAMING_GAMBLING', 'HEALTH_FITNESS', 'HEALTH_FITNESS_ALTERNATIVE', 'HUNTING_SHOOTING', 'LAW_LEGAL_PRACTICE', 'MEDIA_ENTERTAINMENT', 'OTHER', 'POLITICS', 'PROFESSIONAL_SERVICES', 'REAL_ESTATE', 'RELIGION_SPIRITUALITY', 'RETAIL', 'TECHNOLOGY_TELECOMMUNICATIONS', 'TOBACCO_SMOKING', 'TRAVEL_HOSPITALITY'] = Field(...)


class VibeGetAdvertiserConfig(_Input):
    'Get an advertiser.'
    operation: Literal['get_advertiser'] = Field('get_advertiser', title='Get an advertiser')
    advertiser_id: UUID = Field(...)
    account_id: int | None = Field(None)


class VibeUpdateAdvertiserConfig(_Input):
    'Update an advertiser.'
    operation: Literal['update_advertiser'] = Field('update_advertiser', title='Update an advertiser')
    advertiser_id: UUID = Field(...)
    account_id: int | None = Field(None)
    name: str | None = Field(None)
    url: str | None = Field(None, description='The brand-owned website of the advertiser. Marketplace, app store and social media pages are rejected.', json_schema_extra={'format': 'uri'})
    industry: Literal['AUTOMOTIVE', 'EDUCATION', 'FINANCIAL_SERVICES', 'FOOD_DRINK', 'FOOD_DRINK_WINE', 'GAMING', 'GAMING_GAMBLING', 'HEALTH_FITNESS', 'HEALTH_FITNESS_ALTERNATIVE', 'HUNTING_SHOOTING', 'LAW_LEGAL_PRACTICE', 'MEDIA_ENTERTAINMENT', 'OTHER', 'POLITICS', 'PROFESSIONAL_SERVICES', 'REAL_ESTATE', 'RELIGION_SPIRITUALITY', 'RETAIL', 'TECHNOLOGY_TELECOMMUNICATIONS', 'TOBACCO_SMOKING', 'TRAVEL_HOSPITALITY'] | None = Field(None)


class VibeListAudiencesConfig(_Input):
    'List persistent audiences available for sync.'
    operation: Literal['list_audiences'] = Field('list_audiences', title='List persistent audiences available for sync')
    advertiser_id: str = Field(...)
    limit: int = Field(20, ge=1)
    offset: int = Field(0, ge=0)


class VibeGetAudienceConfig(_Input):
    'Get a persistent audience.'
    operation: Literal['get_audience'] = Field('get_audience', title='Get a persistent audience')
    audience_id: str = Field(...)


class VibeCreateAudienceConfig(_Input):
    'Create or upsert an audience under an advertiser.'
    operation: Literal['create_audience'] = Field('create_audience', title='Create or upsert an audience under an advertiser')
    advertiser_id: UUID = Field(...)
    name: str = Field(..., description='Display name for the audience')
    external_audience_key: str | None = Field(None, description='Caller-provided stable key')


class VibeListCampaignsConfig(_Input):
    'List campaigns.'
    operation: Literal['list_campaigns'] = Field('list_campaigns', title='List campaigns')
    id: UUID | None = Field(None)
    advertiser_id: UUID | None = Field(None)
    status: list[Literal['DRAFT', 'UPCOMING_OR_DELIVERING', 'PAUSED', 'ARCHIVED', 'COMPLETED', 'BLOCKED']] | None = Field(None)
    search: str | None = Field(None, min_length=2)
    limit: int = Field(20, ge=1)
    offset: int = Field(0, ge=0)
    account_id: int | None = Field(None)


class VibeCreateCampaignConfig(_Input):
    'Create a campaign.'
    operation: Literal['create_campaign'] = Field('create_campaign', title='Create a campaign')
    account_id: int | None = Field(None)
    advertiser_id: UUID = Field(...)
    name: str = Field(..., min_length=10, max_length=100)
    goal: Literal['AWARENESS', 'INSTALL', 'TRAFFIC', 'RETARGETING', 'SALES', 'LEADS', 'ABM'] = Field(...)
    optimization_goal: VibeOptimizationTarget = Field(...)
    active: StrictBool = Field(True)
    countries: list[str] = Field(..., description='ISO 3166-1 alpha-3 country codes the campaign targets. Must be the exact set: USA.')
    attribution_window: Literal['TWELVE_HOURS', 'ONE_DAY', 'FORTY_EIGHT_HOURS', 'SEVENTY_TWO_HOURS', 'SEVEN_DAYS', 'THIRTY_DAYS'] | None = Field(None)


class VibeGetCampaignConfig(_Input):
    'Get a campaign by id.'
    operation: Literal['get_campaign'] = Field('get_campaign', title='Get a campaign by id')
    campaign_id: UUID = Field(...)
    account_id: int | None = Field(None)


class VibeUpdateCampaignConfig(_Input):
    'Update a campaign.'
    operation: Literal['update_campaign'] = Field('update_campaign', title='Update a campaign')
    campaign_id: UUID = Field(...)
    account_id: int | None = Field(None)
    name: str | None = Field(None, min_length=10, max_length=100)
    goal: Literal['AWARENESS', 'INSTALL', 'TRAFFIC', 'RETARGETING', 'SALES', 'LEADS', 'ABM'] | None = Field(None)
    attribution_window: Literal['TWELVE_HOURS', 'ONE_DAY', 'FORTY_EIGHT_HOURS', 'SEVENTY_TWO_HOURS', 'SEVEN_DAYS', 'THIRTY_DAYS'] | None = Field(None)
    optimization_goal: VibeOptimizationTarget | None = Field(None)
    active: StrictBool | None = Field(None)


class VibeDeleteCampaignConfig(_Input):
    'Delete a draft campaign.'
    operation: Literal['delete_campaign'] = Field('delete_campaign', title='Delete a draft campaign')
    campaign_id: UUID = Field(...)
    account_id: int | None = Field(None)


class VibePerformCampaignActionConfig(_Input):
    'Perform a lifecycle action on a campaign.'
    operation: Literal['perform_campaign_action'] = Field('perform_campaign_action', title='Perform a lifecycle action on a campaign')
    campaign_id: UUID = Field(...)
    account_id: int | None = Field(None)
    action: Literal['PAUSE', 'ACTIVATE'] = Field(..., description='Lifecycle action to perform on the campaign')


class VibePublishCampaignConfig(_Input):
    'Publish a campaign.'
    operation: Literal['publish_campaign'] = Field('publish_campaign', title='Publish a campaign')
    campaign_id: UUID = Field(...)
    account_id: int | None = Field(None)


class VibeListCreativesConfig(_Input):
    'List creatives.'
    operation: Literal['list_creatives'] = Field('list_creatives', title='List creatives')
    advertiser_id: UUID | None = Field(None)
    limit: int = Field(20, ge=1)
    offset: int = Field(0, ge=0)
    account_id: int | None = Field(None)


class VibeListStrategiesConfig(_Input):
    'List strategies.'
    operation: Literal['list_strategies'] = Field('list_strategies', title='List strategies')
    limit: int = Field(20, ge=1)
    offset: int = Field(0, ge=0)
    campaign_id: UUID | None = Field(None)
    advertiser_id: UUID | None = Field(None)
    active: StrictBool | None = Field(None)
    starts_at: str | None = Field(None, json_schema_extra={'format': 'date-time'})
    ends_at: str | None = Field(None, json_schema_extra={'format': 'date-time'})
    account_id: int | None = Field(None)


class VibeCreateStrategyConfig(_Input):
    'Create a strategy.'
    operation: Literal['create_strategy'] = Field('create_strategy', title='Create a strategy')
    account_id: int | None = Field(None)
    campaign_id: UUID = Field(...)
    name: str = Field(..., min_length=3, max_length=100)
    budget: int = Field(..., ge=1, description='Budget in USD')
    budget_type: Literal['DAILY', 'GLOBAL'] = Field(...)
    starts_at: str = Field(..., json_schema_extra={'format': 'date-time'})
    ends_at: str | None = Field(None, json_schema_extra={'format': 'date-time'})
    active: StrictBool = Field(True)
    targeting: VibeTargeting | None = Field(None)
    creative_ids: list[UUID] | None = Field(None)


class VibeGetStrategyConfig(_Input):
    'Get a strategy by id.'
    operation: Literal['get_strategy'] = Field('get_strategy', title='Get a strategy by id')
    strategy_id: UUID = Field(...)
    account_id: int | None = Field(None)


class VibeUpdateStrategyConfig(_Input):
    'Update a strategy.'
    operation: Literal['update_strategy'] = Field('update_strategy', title='Update a strategy')
    strategy_id: UUID = Field(...)
    account_id: int | None = Field(None)
    name: str | None = Field(None, min_length=3, max_length=100)
    active: StrictBool | None = Field(None)
    budget: int | None = Field(None, ge=1, description='Budget in USD')
    budget_type: Literal['DAILY', 'GLOBAL'] | None = Field(None)
    starts_at: str | None = Field(None, json_schema_extra={'format': 'date-time'})
    ends_at: str | None = Field(None, json_schema_extra={'format': 'date-time'})
    targeting: VibeTargeting | None = Field(None)
    creative_ids: list[UUID] | None = Field(None)


class VibeDeleteStrategyConfig(_Input):
    'Delete a strategy.'
    operation: Literal['delete_strategy'] = Field('delete_strategy', title='Delete a strategy')
    strategy_id: UUID = Field(...)
    account_id: int | None = Field(None)


class VibeReplaceStrategyCreativesConfig(_Input):
    'Replace the creatives attached to a strategy.'
    operation: Literal['replace_strategy_creatives'] = Field('replace_strategy_creatives', title='Replace the creatives attached to a strategy')
    strategy_id: UUID = Field(...)
    account_id: int | None = Field(None)
    creative_ids: list[UUID] = Field(..., max_length=5000, description='Full list of creatives to attach. Replaces any current attachments.')


class VibePerformStrategyActionConfig(_Input):
    'Perform a lifecycle action on a strategy.'
    operation: Literal['perform_strategy_action'] = Field('perform_strategy_action', title='Perform a lifecycle action on a strategy')
    strategy_id: UUID = Field(...)
    account_id: int | None = Field(None)
    action: Literal['PAUSE', 'ACTIVATE'] = Field(..., description='Lifecycle action to perform on the strategy')


class VibeCreateReportConfig(_Input):
    'Create an async report.'
    operation: Literal['create_report'] = Field('create_report', title='Create an async report')
    start_date: str = Field(..., description='Minimum date (inclusive) for which to return data', json_schema_extra={'format': 'date'})
    end_date: str = Field(..., description='Maximum date (exclusive) for which to return data', json_schema_extra={'format': 'date'})
    timezone: Literal['UTC', 'Europe/Amsterdam', 'Europe/Berlin', 'Europe/Helsinki', 'Europe/Istanbul', 'Europe/London', 'Europe/Stockholm', 'Asia/Seoul', 'Asia/Shanghai', 'Asia/Tel_Aviv', 'America/Denver', 'America/Los_Angeles', 'America/New_York', 'America/Phoenix'] = Field('UTC', description='Timezone identifier for reported data')
    advertiser_ids: list[UUID] = Field(..., min_length=1, description='Advertisers to include. Must be owned by the tenant.')
    dimensions: list[Literal['advertiser_id', 'advertiser_name', 'campaign_id', 'campaign_name', 'strategy_id', 'strategy_name', 'creative_id', 'creative_name', 'event_source_id', 'event_source_platform', 'screen', 'channel_name', 'content_name', 'geo_region', 'geo_metro', 'geo_city', 'geo_zip', 'segment_ages', 'segment_career', 'segment_educations', 'segment_estimated_incomes', 'segment_estimated_net_worth', 'segment_ethnicity', 'segment_family_composition', 'segment_genders', 'segment_interests', 'segment_languages', 'segment_political_status', 'segment_retargeting', 'custom_audiences']] | None = Field(None, description='Dimensions to group rows by, in addition to the time period set by `granularity`')
    metrics: list[Literal['spend', 'impressions', 'households', 'frequency', 'cpm', 'completed_views', 'cost_per_completed_view', 'view_through_rate', 'number_of_page_views', 'cost_per_page_view', 'number_of_sessions', 'cost_per_session', 'number_of_leads', 'cost_per_lead', 'installs', 'cost_per_install', 'number_of_purchases', 'cost_per_purchase', 'amount_of_purchases', 'number_of_signups', 'cost_per_signup', 'number_of_custom_1', 'cost_per_custom_1', 'number_of_custom_2', 'cost_per_custom_2', 'number_of_custom_3', 'cost_per_custom_3', 'roas']] = Field(..., min_length=1, description='Metrics to compute')
    attribution_window: Literal['1h', '6h', '12h', '24h', '48h', '72h', '7 days', '30 days'] = Field('7 days')
    granularity: Literal['HOUR', 'DAY', 'WEEK', 'MONTH'] = Field('DAY', description='Time aggregation granularity for rows in the report. Every report is split by time: each row has an `impression_date` column (YYYY-MM-DD) holding the date its period starts on.')
    filters: list[VibeReportFilter] | None = Field(None, description='Optional filters, combined with AND')
    format: Literal['JSON', 'CSV'] = Field('JSON')


class VibeGetReportConfig(_Input):
    'Get the status of an async report.'
    operation: Literal['get_report'] = Field('get_report', title='Get the status of an async report')
    report_id: UUID = Field(...)


for _model in (VibeTargeting, VibeGeoTargeting, VibeAudienceTargeting, VibeDayparting):
    _model.model_rebuild()


VibeOperation = Annotated[Union[
    VibeListAccountsConfig,
    VibeListAdvertisersConfig,
    VibeCreateAdvertiserConfig,
    VibeGetAdvertiserConfig,
    VibeUpdateAdvertiserConfig,
    VibeListAudiencesConfig,
    VibeGetAudienceConfig,
    VibeCreateAudienceConfig,
    VibeListCampaignsConfig,
    VibeCreateCampaignConfig,
    VibeGetCampaignConfig,
    VibeUpdateCampaignConfig,
    VibeDeleteCampaignConfig,
    VibePerformCampaignActionConfig,
    VibePublishCampaignConfig,
    VibeListCreativesConfig,
    VibeListStrategiesConfig,
    VibeCreateStrategyConfig,
    VibeGetStrategyConfig,
    VibeUpdateStrategyConfig,
    VibeDeleteStrategyConfig,
    VibeReplaceStrategyCreativesConfig,
    VibePerformStrategyActionConfig,
    VibeCreateReportConfig,
    VibeGetReportConfig,
], Field(discriminator="operation")]


class VibeFullConfig(NodeConfig[VibeOperation, VibeOAuthCredential]):
    pass


# operation -> method, path, path fields, query fields, body fields, success codes.
ROUTES = {'list_accounts': ('GET', '/accounts', (), (), (), (200,)),
 'list_advertisers': ('GET',
                      '/advertisers',
                      (),
                      ('id', 'name', 'url', 'limit', 'offset', 'account_id'),
                      (),
                      (200,)),
 'create_advertiser': ('POST', '/advertisers', (), ('account_id',), ('name', 'url', 'industry'), (201,)),
 'get_advertiser': ('GET', '/advertisers/{advertiser_id}', ('advertiser_id',), ('account_id',), (), (200,)),
 'update_advertiser': ('PATCH',
                       '/advertisers/{advertiser_id}',
                       ('advertiser_id',),
                       ('account_id',),
                       ('name', 'url', 'industry'),
                       (200,)),
 'list_audiences': ('GET', '/audiences', (), ('advertiser_id', 'limit', 'offset'), (), (200,)),
 'get_audience': ('GET', '/audiences/{audience_id}', ('audience_id',), (), (), (200,)),
 'create_audience': ('POST',
                     '/advertisers/{advertiser_id}/audiences',
                     ('advertiser_id',),
                     (),
                     ('name', 'external_audience_key'),
                     (200, 201)),
 'list_campaigns': ('GET',
                    '/campaigns',
                    (),
                    ('id', 'advertiser_id', 'status', 'search', 'limit', 'offset', 'account_id'),
                    (),
                    (200,)),
 'create_campaign': ('POST',
                     '/campaigns',
                     (),
                     ('account_id',),
                     ('advertiser_id',
                      'name',
                      'goal',
                      'optimization_goal',
                      'active',
                      'countries',
                      'attribution_window'),
                     (201,)),
 'get_campaign': ('GET', '/campaigns/{campaign_id}', ('campaign_id',), ('account_id',), (), (200,)),
 'update_campaign': ('PATCH',
                     '/campaigns/{campaign_id}',
                     ('campaign_id',),
                     ('account_id',),
                     ('name', 'goal', 'attribution_window', 'optimization_goal', 'active'),
                     (200,)),
 'delete_campaign': ('DELETE', '/campaigns/{campaign_id}', ('campaign_id',), ('account_id',), (), (204,)),
 'perform_campaign_action': ('POST',
                             '/campaigns/{campaign_id}/actions',
                             ('campaign_id',),
                             ('account_id',),
                             ('action',),
                             (200,)),
 'publish_campaign': ('POST',
                      '/campaigns/{campaign_id}/publish',
                      ('campaign_id',),
                      ('account_id',),
                      (),
                      (200,)),
 'list_creatives': ('GET', '/creatives', (), ('advertiser_id', 'limit', 'offset', 'account_id'), (), (200,)),
 'list_strategies': ('GET',
                     '/strategies',
                     (),
                     ('limit',
                      'offset',
                      'campaign_id',
                      'advertiser_id',
                      'active',
                      'starts_at',
                      'ends_at',
                      'account_id'),
                     (),
                     (200,)),
 'create_strategy': ('POST',
                     '/strategies',
                     (),
                     ('account_id',),
                     ('campaign_id',
                      'name',
                      'budget',
                      'budget_type',
                      'starts_at',
                      'ends_at',
                      'active',
                      'targeting',
                      'creative_ids'),
                     (201,)),
 'get_strategy': ('GET', '/strategies/{strategy_id}', ('strategy_id',), ('account_id',), (), (200,)),
 'update_strategy': ('PATCH',
                     '/strategies/{strategy_id}',
                     ('strategy_id',),
                     ('account_id',),
                     ('name',
                      'active',
                      'budget',
                      'budget_type',
                      'starts_at',
                      'ends_at',
                      'targeting',
                      'creative_ids'),
                     (200,)),
 'delete_strategy': ('DELETE', '/strategies/{strategy_id}', ('strategy_id',), ('account_id',), (), (204,)),
 'replace_strategy_creatives': ('PUT',
                                '/strategies/{strategy_id}/creatives',
                                ('strategy_id',),
                                ('account_id',),
                                ('creative_ids',),
                                (200,)),
 'perform_strategy_action': ('POST',
                             '/strategies/{strategy_id}/actions',
                             ('strategy_id',),
                             ('account_id',),
                             ('action',),
                             (200,)),
 'create_report': ('POST',
                   '/reports',
                   (),
                   (),
                   ('start_date',
                    'end_date',
                    'timezone',
                    'advertiser_ids',
                    'dimensions',
                    'metrics',
                    'attribution_window',
                    'granularity',
                    'filters',
                    'format'),
                   (201,)),
 'get_report': ('GET', '/reports/{report_id}', ('report_id',), (), (), (200,))}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()
                if k.lower() not in {"access_token", "refresh_token", "authorization", "client_secret"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class VibeNode(WorkflowNode):
    integration_type = "automation-vibe"
    scope_registry = VIBE_SCOPES
    connection_evidence = ConnectionEvidence(noun="Vibe accounts", operation="list_accounts", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return VibeFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.vibe_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="vibe")

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Vibe account")
        credential = self.config.credentials
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.vibe_oauth import refresh_access_token
            data = credential.model_dump()
            await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=data, refresh=refresh_access_token,
                provider="vibe", caller_path="execute")
            for key in ("access_token", "refresh_token", "expires_at"):
                setattr(credential, key, data[key])
        token = credential.access_token
        secrets = (token, credential.refresh_token)
        op = self.config.config
        method, path, path_fields, query_fields, body_fields, success_codes = ROUTES[op.operation]
        fields = op.model_dump(mode="json", exclude_none=True)
        for name in path_fields:
            value = str(fields[name])
            if value in {".", ".."} or not value or len(value) > 256:
                raise ValueError("Use a Vibe resource ID")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = []
        for name in query_fields:
            if name not in fields:
                continue
            value = fields[name]
            for item in value if isinstance(value, list) else [value]:
                params.append((name, str(item).lower() if isinstance(item, bool) else str(item)))
        body = {name: fields[name] for name in body_fields if name in fields}
        # Only ends_at is nullable in these write schemas; an explicit null
        # clears the end date, while other absent optional values stay omitted.
        if "ends_at" in body_fields and "ends_at" in op.model_fields_set and op.ends_at is None:
            body["ends_at"] = None
        # A single request, including writes. No retry, hidden pagination or readback.
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "X-Vibe-Revision": REVISION, "Accept": "application/json"},
                    **({"json": body} if body_fields else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Vibe request could not be completed", "write_outcome": "unverified" if method != "GET" else None}
        if response.status_code not in success_codes:
            message = "Vibe request failed"
            try:
                error = response.json().get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "http_status": response.status_code,
                    "error": _redact(message, secrets)[:2000], "write_outcome": "unverified" if method != "GET" else None}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "acknowledged": True, "state_verified": False}
        try:
            result = response.json()
        except ValueError:
            return {"status": "error", "error": "Vibe returned invalid JSON"}
        if not isinstance(result, (dict, list)) or isinstance(result, dict) and ("error" in result or "errors" in result):
            return {"status": "error", "error": "Vibe returned an unexpected response"}
        result = _redact(result, secrets)
        output = {"status": "success", "http_status": response.status_code, "data": result}
        if op.operation == "list_accounts":
            if not isinstance(result, list) or any(not isinstance(row, dict) or "id" not in row or not isinstance(row.get("name"), str) for row in result):
                return {"status": "error", "error": "Vibe returned an invalid account list"}
            output.update(items=result, complete=True)
        elif op.operation.startswith("list_"):
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                return {"status": "error", "error": "Vibe returned an invalid list page"}
            output["items"] = result["data"]
            output["pagination"] = {key: result[key] for key in ("total", "limit", "offset") if key in result}
            # Preserve the provider page; caller explicitly requests the next offset.
        if method != "GET":
            output.update(acknowledged=True, state_verified=False)
        return output
