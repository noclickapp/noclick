"""The Odds API v4: the provider's eleven published read endpoints.

Reference: https://the-odds-api.com/liveapi/guides/v4/
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.the-odds-api.com"
CREDENTIAL_TYPE = "the_odds_api_key"


class TheOddsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="The Odds API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://the-odds-api.com/#get-access",
            "x-credential-instructions": "Paste your API key from The Odds API email or account dashboard. Sports-list access verifies that the key is accepted, not account identity. Historical endpoints require a paid plan; odds and scores may consume your request quota.",
        })
    credential_type: Literal["the_odds_api_key"] = Field("the_odds_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(ch.isspace() for ch in value):
            raise ValueError("Paste the API key without spaces or a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("date", "commence_time_from", "commence_time_to", check_fields=False)
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None or not value.endswith("Z"):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Use an ISO8601 UTC timestamp ending in Z") from None
        return value

    @model_validator(mode="after")
    def time_range(self):
        start, end = getattr(self, "commence_time_from", None), getattr(self, "commence_time_to", None)
        if start and end and datetime.fromisoformat(start.replace("Z", "+00:00")) > datetime.fromisoformat(end.replace("Z", "+00:00")):
            raise ValueError("Commence time from must not follow commence time to")
        return self


class ListSportsConfig(_Input):
    operation: Literal["list_sports"] = Field("list_sports", title="List Sports")
    all: bool | None = Field(None, title='All', description='When excluded, only recently updated (in-season) sports appear. Include this paramter to see all available sports')


class GetOddsConfig(_Input):
    operation: Literal["get_odds"] = Field("get_odds", title="Get Odds")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    regions: str = Field("us", pattern=r"^(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi)(?:,(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi))*$", max_length=256, title='Regions', description='Determines which bookmakers appear in the response. Multiple regions can be specified if comma delimited. Each region will count as 1 request against the usage quota for each market. Most use cases will only need to specify one region. For a list of bookmakers by region, see https://the-odds-api.com/sports-odds-data/bookmaker-apis.html')
    markets: str = Field("h2h", pattern=r"^[a-z0-9_]+(?:,[a-z0-9_]+)*$", max_length=4096, title='Markets', description='The odds market to return. Multiple markets can be specified if comma delimited. Defaults to h2h (head to head / moneyline). Outrights are only avaialable for select sports, such as golf. Comma-separated market keys; historical data availability and plan restrictions apply.')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    odds_format: Literal['decimal', 'american'] = Field('decimal', title='Odds format', description='Format of returned odds')
    event_ids: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Event ids', description='Comma-separated event ids. Filters the response to only return events for the specified ids, provided those events have not expired')
    bookmakers: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Bookmakers', description='Comma-separated list of bookmakers to be returned. If both `bookmakers` and `regions` are specified, `bookmakers` takes precendence. Bookmakers can be from any region. Every group of 10 bookmakers counts as 1 request. For example for a single market, specifying up to 10 bookmakers is the equivalent of 1 region. Specifying between 11 and 20 bookmakers is the equivalent of 2 regions')
    commence_time_from: str | None = Field(None, max_length=64, title='Commence time from', description='Filters the response to show events that commence on and after this parameter. Values are in ISO8601 format')
    commence_time_to: str | None = Field(None, max_length=64, title='Commence time to', description='Filters the response to show events that commence on and before this parameter. Values are in ISO8601 format')
    include_links: bool | None = Field(None, title='Include links', description='The response will include bookmaker links to events, markets, and betslips if available.')
    include_sids: bool | None = Field(None, title='Include sids', description='The response will include source ids (bookmaker ids) for events, markets, and outcomes if available.')
    include_bet_limits: bool | None = Field(None, title='Include bet limits', description='The response will include the bet limit of each betting option, mainly available for betting exchanges.')
    include_rotation_numbers: bool | None = Field(None, title='Include rotation numbers', description='The response will include home and away rotation numbers if available. For details, see https://the-odds-api.com/releases/rotation-numbers.html')


class GetScoresConfig(_Input):
    operation: Literal["get_scores"] = Field("get_scores", title="Get Scores")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds')
    days_from: int | None = Field(None, ge=1, le=3, title='Days from', description='The number of days in the past from which to return completed events. Valid values are integers from `1` to `3`. If this field is missing, only live and upcoming events are returned.')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    event_ids: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Event ids', description='Comma-separated event ids. Filters the response to only return events for the specified ids, provided those events have not expired')


class ListEventsConfig(_Input):
    operation: Literal["list_events"] = Field("list_events", title="List Events")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    event_ids: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Event ids', description='Comma-separated event ids. Filters the response to only return events for the specified ids, provided those events have not expired')
    commence_time_from: str | None = Field(None, max_length=64, title='Commence time from', description='Filters the response to show events that commence on and after this parameter. Values are in ISO8601 format')
    commence_time_to: str | None = Field(None, max_length=64, title='Commence time to', description='Filters the response to show events that commence on and before this parameter. Values are in ISO8601 format')
    include_rotation_numbers: bool | None = Field(None, title='Include rotation numbers', description='The response will include home and away rotation numbers if available. For details, see https://the-odds-api.com/releases/rotation-numbers.html')


class GetEventOddsConfig(_Input):
    operation: Literal["get_event_odds"] = Field("get_event_odds", title="Get Event Odds")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    event_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Event id', description='Event ids can be found in the `id` field in the response of the `/events` endpoint (see `/v4/sports/{sports}/events`). If the event has expired (not receiving updates due to completion or cancellation), a HTTP 404 status code will be returned.')
    regions: str = Field("us", pattern=r"^(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi)(?:,(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi))*$", max_length=256, title='Regions', description='Determines which bookmakers appear in the response. Multiple regions can be specified if comma delimited. Each region will count as 1 request against the usage quota for each market. Most use cases will only need to specify one region. See [the full list of bookmakers by region](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html)')
    markets: str = Field("h2h", pattern=r"^[a-z0-9_]+(?:,[a-z0-9_]+)*$", max_length=4096, title='Markets', description='The odds markets to return. Multiple markets can be specified if comma delimited. Defaults to h2h (head to head / moneyline). Outrights only avaialable for select sports. See [the full list of supported market keys](https://the-odds-api.com/sports-odds-data/betting-markets.html) Comma-separated market keys; historical data availability and plan restrictions apply.')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    odds_format: Literal['decimal', 'american'] = Field('decimal', title='Odds format', description='Format of returned odds')
    bookmakers: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Bookmakers', description='Comma-separated list of bookmakers to be returned. If both `bookmakers` and `regions` are specified, `bookmakers` takes precendence. Bookmakers can be from any region. Every group of 10 bookmakers counts as 1 request. For example for a single market, specifying up to 10 bookmakers counts as 1 request. Specifying between 11 and 20 bookmakers counts as 2 requests')
    include_links: bool | None = Field(None, title='Include links', description='The response will include bookmaker links to events, markets, and betslips if available.')
    include_sids: bool | None = Field(None, title='Include sids', description='The response will include source ids (bookmaker ids) for events, markets, and outcomes if available.')
    include_bet_limits: bool | None = Field(None, title='Include bet limits', description='The response will include the bet limit of each betting option, mainly available for betting exchanges.')
    include_multipliers: bool | None = Field(None, title='Include multipliers', description='Applicable to US DFS sites. When true, a "multiplier" field will be included with each bet selection in the response')
    include_rotation_numbers: bool | None = Field(None, title='Include rotation numbers', description='The response will include home and away rotation numbers if available. For details, see https://the-odds-api.com/releases/rotation-numbers.html')


class GetEventMarketsConfig(_Input):
    operation: Literal["get_event_markets"] = Field("get_event_markets", title="Get Event Markets")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    event_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Event id', description='Event ids can be found in the `id` field in the response of the `/events` endpoint (see `/v4/sports/{sports}/events`). If the event has expired (not receiving updates due to completion or cancellation), a HTTP 404 status code will be returned.')
    regions: str = Field("us", pattern=r"^(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi)(?:,(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi))*$", max_length=256, title='Regions', description='Determines which bookmakers appear in the response. Multiple regions can be specified if comma delimited. Each region will count as 1 request against the usage quota for each market. Most use cases will only need to specify one region. See [the full list of bookmakers by region](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html)')
    bookmakers: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Bookmakers', description='Comma-separated list of bookmakers to be returned. If both `bookmakers` and `regions` are specified, `bookmakers` takes precendence. Bookmakers can be from any region. Every group of 10 bookmakers counts as 1 request. For example for a single market, specifying up to 10 bookmakers counts as 1 request. Specifying between 11 and 20 bookmakers counts as 2 requests')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')


class ListParticipantsConfig(_Input):
    operation: Literal["list_participants"] = Field("list_participants", title="List Participants")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')


class GetHistoricalOddsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid plan"})
    operation: Literal["get_historical_odds"] = Field("get_historical_odds", title="Get Historical Odds")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    regions: str = Field("us", pattern=r"^(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi)(?:,(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi))*$", max_length=256, title='Regions', description='Determines which bookmakers appear in the response. Multiple regions can be specified if comma delimited. Most use cases will only need to specify one region. For a list of bookmakers by region, see https://the-odds-api.com/sports-odds-data/bookmaker-apis.html')
    markets: str = Field("h2h", pattern=r"^[a-z0-9_]+(?:,[a-z0-9_]+)*$", max_length=4096, title='Markets', description='The odds market to return. Multiple markets can be specified if comma delimited. Defaults to h2h (head to head / moneyline). Outrights are only avaialable for select sports, such as golf. Comma-separated market keys; historical data availability and plan restrictions apply.')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    odds_format: Literal['decimal', 'american'] = Field('decimal', title='Odds format', description='Format of returned odds')
    event_ids: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Event ids', description='Comma-separated event ids. Filters the response to only return events for the specified ids, provided those events have not expired')
    bookmakers: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Bookmakers', description='Comma-separated list of bookmakers to be returned. If both `bookmakers` and `regions` are specified, `bookmakers` takes precendence. Bookmakers can be from any region. Every group of 10 bookmakers counts as 1 request. For example for a single market, specifying up to 10 bookmakers counts as 1 request. Specifying between 11 and 20 bookmakers counts as 2 requests')
    commence_time_from: str | None = Field(None, max_length=64, title='Commence time from', description='Filters the response to show events that commence on and after this parameter. Values are in ISO8601 format')
    commence_time_to: str | None = Field(None, max_length=64, title='Commence time to', description='Filters the response to show events that commence on and before this parameter. Values are in ISO8601 format')
    date: str = Field(..., max_length=64, title='Date', description='The timestamp of the data snapshot to be returned, specified in ISO8601 format. The historical odds API will return the closest snapshot equal to or earlier than the provided date parameter')
    include_sids: bool | None = Field(None, title='Include sids', description='The response will include source ids (bookmaker ids) for events, markets, and outcomes if available.')
    include_bet_limits: bool | None = Field(None, title='Include bet limits', description='The response will include the bet limit of each betting option, mainly available for betting exchanges.')
    include_rotation_numbers: bool | None = Field(None, title='Include rotation numbers', description='The response will include home and away rotation numbers if available. For details, see https://the-odds-api.com/releases/rotation-numbers.html')


class ListHistoricalEventsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid plan"})
    operation: Literal["list_historical_events"] = Field("list_historical_events", title="List Historical Events")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    event_ids: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Event ids', description='Comma-separated event ids. Filters the response to only return events for the specified ids, provided those events have not expired')
    commence_time_from: str | None = Field(None, max_length=64, title='Commence time from', description='Filters the response to show events that commence on and after this parameter. Values are in ISO8601 format')
    commence_time_to: str | None = Field(None, max_length=64, title='Commence time to', description='Filters the response to show events that commence on and before this parameter. Values are in ISO8601 format')
    date: str = Field(..., max_length=64, title='Date', description='The timestamp of the data snapshot to be returned, specified in ISO8601 format. The API will return the closest snapshot equal to or earlier than the provided date parameter')
    include_rotation_numbers: bool | None = Field(None, title='Include rotation numbers', description='The response will include home and away rotation numbers if available. For details, see https://the-odds-api.com/releases/rotation-numbers.html')


class GetHistoricalEventOddsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid plan"})
    operation: Literal["get_historical_event_odds"] = Field("get_historical_event_odds", title="Get Historical Event Odds")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    event_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Event id', description='Event ids can be found in the `id` field in the response of the historical events endpoint (see `/v4/historical/sports/{sports}/events`). If the event had expired at the specified timestamp (not receiving updates due to completion or cancellation), a HTTP 404 status code will be returned.')
    regions: str = Field("us", pattern=r"^(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi)(?:,(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi))*$", max_length=256, title='Regions', description='Determines which bookmakers appear in the response. Multiple regions can be specified if comma delimited. Most use cases will only need to specify one region. See [the full list of bookmakers by region](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html)')
    markets: str = Field("h2h", pattern=r"^[a-z0-9_]+(?:,[a-z0-9_]+)*$", max_length=4096, title='Markets', description='The odds markets to return. Multiple markets can be specified if comma delimited. Defaults to h2h (head to head / moneyline). Outrights only avaialable for select sports. See [the full list of supported market keys](https://the-odds-api.com/sports-odds-data/betting-markets.html) Comma-separated market keys; historical data availability and plan restrictions apply.')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    odds_format: Literal['decimal', 'american'] = Field('decimal', title='Odds format', description='Format of returned odds')
    bookmakers: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Bookmakers', description='Comma-separated list of bookmakers to be returned. If both `bookmakers` and `regions` are specified, `bookmakers` takes precendence. Bookmakers can be from any region. Every group of 10 bookmakers counts as 1 request. For example for a single market, specifying up to 10 bookmakers counts as 1 request. Specifying between 11 and 20 bookmakers counts as 2 requests')
    date: str = Field(..., max_length=64, title='Date', description='The timestamp of the data snapshot to be returned, specified in ISO8601 format. The API will return the closest snapshot equal to or earlier than the provided date parameter')
    include_rotation_numbers: bool | None = Field(None, title='Include rotation numbers', description='The response will include home and away rotation numbers if available. For details, see https://the-odds-api.com/releases/rotation-numbers.html')
    include_multipliers: bool | None = Field(None, title='Include multipliers', description='Applicable to US DFS sites. When true, a "multiplier" field will be included with each bet selection in the response')
    include_sids: bool | None = Field(None, title='Include sids', description='The response will include source ids (bookmaker ids) for events, markets, and outcomes if available.')
    include_bet_limits: bool | None = Field(None, title='Include bet limits', description='The response will include the bet limit of each betting option, mainly available for betting exchanges.')


class GetHistoricalEventMarketsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid plan"})
    operation: Literal["get_historical_event_markets"] = Field("get_historical_event_markets", title="Get Historical Event Markets")
    sport: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Sport', description='sport key for which to return events and odds. This is obtained from the /sports endpoint')
    event_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title='Event id', description='Event ids can be found in the `id` field in the response of the historical events endpoint (see `/v4/historical/sports/{sports}/events`). If the event had expired at the specified timestamp (not receiving updates due to completion or cancellation), a HTTP 404 status code will be returned.')
    regions: str = Field("us", pattern=r"^(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi)(?:,(?:uk|us|us2|us_dfs|us_ex|eu|au|ca|fr|se|fi))*$", max_length=256, title='Regions', description='Determines which bookmakers appear in the response. Multiple regions can be specified if comma delimited. Each region will count as 1 request against the usage quota. Most use cases will only need to specify one region. See [the full list of bookmakers by region](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html)')
    bookmakers: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$", max_length=4096, title='Bookmakers', description='Comma-separated list of bookmakers to be returned. If both `bookmakers` and `regions` are specified, `bookmakers` takes precendence. Bookmakers can be from any region. Every group of 10 bookmakers counts as 1 request. For example, specifying up to 10 bookmakers counts as 1 request. Specifying between 11 and 20 bookmakers counts as 2 requests')
    date_format: Literal['iso', 'unix'] = Field('iso', title='Date format', description='Format of returned timestamps. Can be iso (ISO8601) or unix timestamp (seconds since epoch)')
    date: str = Field(..., max_length=64, title='Date', description='The timestamp of the data snapshot to be returned, specified in ISO8601 format. The API will return the closest snapshot equal to or earlier than the provided date parameter')


Operation = Annotated[Union[ListSportsConfig, GetOddsConfig, GetScoresConfig, ListEventsConfig, GetEventOddsConfig, GetEventMarketsConfig, ListParticipantsConfig, GetHistoricalOddsConfig, ListHistoricalEventsConfig, GetHistoricalEventOddsConfig, GetHistoricalEventMarketsConfig], Field(discriminator="operation")]


class TheOddsAPIConfig(NodeConfig[Operation, TheOddsAPIKeyCredential]):
    pass


ROUTES = {'list_sports': '/v4/sports', 'get_odds': '/v4/sports/{sport}/odds', 'get_scores': '/v4/sports/{sport}/scores', 'list_events': '/v4/sports/{sport}/events', 'get_event_odds': '/v4/sports/{sport}/events/{eventId}/odds', 'get_event_markets': '/v4/sports/{sport}/events/{eventId}/markets', 'list_participants': '/v4/sports/{sport}/participants', 'get_historical_odds': '/v4/historical/sports/{sport}/odds', 'list_historical_events': '/v4/historical/sports/{sport}/events', 'get_historical_event_odds': '/v4/historical/sports/{sport}/events/{eventId}/odds', 'get_historical_event_markets': '/v4/historical/sports/{sport}/events/{eventId}/markets'}
QUERY_NAMES = {'eventId': 'event_id', 'dateFormat': 'date_format', 'oddsFormat': 'odds_format', 'daysFrom': 'days_from', 'eventIds': 'event_ids', 'commenceTimeFrom': 'commence_time_from', 'commenceTimeTo': 'commence_time_to', 'includeLinks': 'include_links', 'includeSids': 'include_sids', 'includeBetLimits': 'include_bet_limits', 'includeRotationNumbers': 'include_rotation_numbers', 'includeMultipliers': 'include_multipliers'}


class TheOddsAPINode(WorkflowNode):
    integration_type = "automation-the-odds-api"
    connection_evidence = ConnectionEvidence(operation="list_sports", noun="sports",
        label_keys=("title", "key"), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return TheOddsAPIConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a The Odds API key")
        config, credential = self.config.config, self.config.credentials
        route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field, wire in (("sport", "sport"), ("event_id", "eventId")):
            if field in values:
                route = route.replace("{" + wire + "}", values.pop(field))
        wire_names = {value: key for key, value in QUERY_NAMES.items()}
        params = {wire_names.get(k, k): str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        params["apiKey"] = credential.api_key
        try:
            async with guarded_async_client(timeout=30.0,
                    follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE_URL + route, params=params)
            if response.status_code != 200:
                message = "The Odds API did not confirm this read"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(credential.api_key, "[redacted]")}
            body = response.json()
            historical = config.operation in {
                "get_historical_odds", "list_historical_events", "get_historical_event_odds", "get_historical_event_markets"}
            single = config.operation in {"get_event_odds", "get_event_markets", "get_historical_event_odds", "get_historical_event_markets"}
            data = body
            if historical:
                if not isinstance(body, dict) or "data" not in body or "timestamp" not in body:
                    raise ValueError("Missing historical snapshot metadata")
                data = body["data"]
            if single:
                if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                    raise ValueError("Missing event data")
            elif not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("Expected a list of records")
            usage = {name: response.headers["x-requests-" + name] for name in ("used", "remaining", "last")
                if "x-requests-" + name in response.headers}
            output = {"status": "success", "operation": config.operation, "data": body, "usage": usage}
            await self.emit(output)
            return output
        except (ValueError, SSRFError, httpx.HTTPError):
            return {"status": "error", "error": "The Odds API response could not be verified"}
