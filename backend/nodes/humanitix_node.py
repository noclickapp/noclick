"""Humanitix Public API v1.30.1: account events, orders, tickets and tags.

Contract: https://api.humanitix.com/v1/documentation/json
Actions return one page; poll triggers traverse all pages before deduplication.
Global reads require Humanitix's special permission.
Check-in/out send exactly one POST without a body and are never retried.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from nodes.scopes.humanitix import HUMANITIX_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.humanitix.com"
ID = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{24}$")]


class HumanitixAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Humanitix API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.humanitix.com/",
            "x-credential-instructions": "In the Humanitix console, open API keys and create a key with events:read for connection verification, orders:read for orders, tickets:read for tickets and check-in counts, and tickets:checkin for check-in and check-out. Paste the key here. Global reads also need global:read and special permission from Humanitix. Keys access your account's events; legacy keys may also access shared events."
        })
    credential_type: Literal["humanitix_api_key"] = Field("humanitix_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ch.isspace() for ch in value) or not value.isascii():
            raise ValueError("Paste only the API key, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_since(cls, value, info):
        if info.field_name == "since" and value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 date-time with a timezone") from None
        return value


class ListEventsConfig(_Input):
    """Returns an array of events."""
    operation: Literal["list_events"] = Field("list_events", title="Get Events", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number you wish to fetch.')
    pageSize: int = Field(100, ge=1, le=100, description='Page size of the results you wish to fetch.')
    inFutureOnly: Optional[StrictBool] = Field(None, description='If true, return only events that have an endDate in the future.')
    since: Optional[str] = Field(None, json_schema_extra={"format": "date-time"}, description='Results since this date-time (ISO 8601).')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class GetEventConfig(_Input):
    """Returns an event for the given eventId."""
    operation: Literal["get_event"] = Field("get_event", title="Get Event", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class GetEventCheckInCountConfig(_Input):
    """Returns a check in count object for a given eventId and eventDateId for all tickets that have had sales (this endpoint is in Beta and is subject to change)."""
    operation: Literal["get_event_check_in_count"] = Field("get_event_check_in_count", title="Get Event check in count (BETA)", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    eventDateId: ID = Field(..., description='ID of the event on a specific date.')


class ListOrdersConfig(_Input):
    """Returns all orders for a given event and eventDateId."""
    operation: Literal["list_orders"] = Field("list_orders", title="Get Orders", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    eventDateId: Optional[ID] = Field(None, description='ID of the event on a specific date.')
    page: int = Field(1, ge=1, description='Page number you wish to fetch.')
    pageSize: int = Field(100, ge=1, le=100, description='Page size of the results you wish to fetch.')
    since: Optional[str] = Field(None, json_schema_extra={"format": "date-time"}, description='Results since this date-time (ISO 8601).')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class GetOrderConfig(_Input):
    """Returns an order for the given eventId."""
    operation: Literal["get_order"] = Field("get_order", title="Get Order", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    orderId: ID = Field(..., description='ID of the order.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class ListTicketsConfig(_Input):
    """Returns all tickets for an event."""
    operation: Literal["list_tickets"] = Field("list_tickets", title="Get Tickets", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    eventDateId: Optional[ID] = Field(None, description='ID of the event on a specific date.')
    page: int = Field(1, ge=1, description='Page number you wish to fetch.')
    pageSize: int = Field(100, ge=1, le=100, description='Page size of the results you wish to fetch.')
    status: Optional[Literal['complete', 'cancelled']] = Field(None, description='Ticket status you wish to fetch.')
    since: Optional[str] = Field(None, json_schema_extra={"format": "date-time"}, description='Results since this date-time (ISO 8601).')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class GetTicketConfig(_Input):
    """Returns a ticket for the given eventId and ticketId."""
    operation: Literal["get_ticket"] = Field("get_ticket", title="Get Ticket", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    ticketId: ID = Field(..., description='ID of the ticket.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class CheckInTicketConfig(_Input):
    """Update the ticket to check it in"""
    operation: Literal["check_in_ticket"] = Field("check_in_ticket", title="Check in", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    ticketId: ID = Field(..., description='ID of the ticket.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class CheckOutTicketConfig(_Input):
    """Update the ticket to check it out"""
    operation: Literal["check_out_ticket"] = Field("check_out_ticket", title="Check out", json_schema_extra={"ui:hidden": True})
    eventId: ID = Field(..., description='ID of the event.')
    ticketId: ID = Field(..., description='ID of the ticket.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')


class ListTagsConfig(_Input):
    """Returns all tags for a user."""
    operation: Literal["list_tags"] = Field("list_tags", title="Get Tags", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number you wish to fetch.')
    pageSize: int = Field(100, ge=1, le=100, description='Page size of the results you wish to fetch.')


class GetTagConfig(_Input):
    """Returns a tag for the given tagId."""
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True})
    tagId: ID = Field(..., description='ID of the tag.')


class ListGlobalEventsConfig(_Input):
    """Returns an array of events from across the platform. Requires special user permission to use this endpoint, activated by Humanitix."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-tier": "humanitix_global", "x-tier-label": "Humanitix global permission"})
    operation: Literal["list_global_events"] = Field("list_global_events", title="Get Events global", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number you wish to fetch.')
    pageSize: int = Field(100, ge=1, le=100, description='Page size of the results you wish to fetch.')
    type: Optional[Literal['appearanceOrSigning', 'attraction', 'campTripOrRetreat', 'classTrainingOrWorkshop', 'concertOrPerformance', 'conference', 'convention', 'dinnerOrGala', 'festivalOrFair', 'gameOrCompetition', 'meetingOrNetworkingEvent', 'partyOrSocialGathering', 'raceOrEnduranceEvent', 'rally', 'screening', 'seminarOrTalk', 'tour', 'tournament', 'tradeShowConsumerShowOrExpo', 'other']] = Field(None, description='Filter events where "event.classification.type" matches this field.')
    category: Optional[Literal['autoBoatAndAir', 'businessAndProfessional', 'charityAndCauses', 'communityAndCulture', 'familyAndEducation', 'fashionAndBeauty', 'filmMediaAndEntertainment', 'foodAndDrink', 'governmentAndPolitics', 'healthAndWellness', 'hobbiesAndSpecialInterest', 'homeAndLifestyle', 'music', 'performingAndVisualArts', 'religionAndSpirituality', 'schoolActivities', 'scienceAndTechnology', 'seasonalAndHoliday', 'sportsAndFitness', 'travelAndOutdoor', 'other']] = Field(None, description='Filter events where "event.classification.category" matches this field.')
    subcategory: Optional[Literal['air', 'auto', 'boat', 'motorcycle', 'other', 'career', 'design', 'educators', 'environmentAndSustainability', 'finance', 'investment', 'media', 'nonProfitNGO', 'realEstate', 'salesAndMarketing', 'startupsAndBusiness', 'animalWelfare', 'disasterRelief', 'education', 'environment', 'healthcare', 'humanRights', 'internationalAid', 'poverty', 'cityTown', 'county', 'heritage', 'historic', 'lgbt', 'language', 'medieval', 'nationality', 'renaissance', 'state', 'alumni', 'baby', 'childrenAndYouth', 'parenting', 'parentsAssociation', 'reunion', 'seniorCitizen', 'accessories', 'beauty', 'bridal', 'fashion', 'adult', 'anime', 'comedy', 'comics', 'film', 'gaming', 'tv', 'beer', 'food', 'spirits', 'wine', 'countyMunicipalGovernment', 'democraticParty', 'federalGovernment', 'internationalAffairs', 'military', 'nationalSecurity', 'nonPartisan', 'otherParty', 'republicanParty', 'stateGovernment', 'medical', 'mentalHealth', 'personalHealth', 'spa', 'yoga', 'animeComics', 'books', 'diy', 'drawingAndPainting', 'knitting', 'photography', 'dating', 'homeAndGarden', 'petsAndAnimals', 'acoustic', 'alternative', 'americana', 'bluegrass', 'blues', 'bluesAndJazz', 'classical', 'country', 'cultural', 'djDance', 'edm', 'edmElectronic', 'electronic', 'experimental', 'folk', 'hipHopRap', 'indie', 'jazz', 'latin', 'metal', 'opera', 'pop', 'psychedelic', 'punkHardcore', 'rAndB', 'reggae', 'religiousSpiritual', 'rock', 'singerSongwriter', 'top40', 'world', 'ballet', 'craft', 'fineArt', 'jewelry', 'literaryArts', 'musical', 'orchestra', 'painting', 'sculpture', 'theatre', 'agnosticism', 'atheism', 'buddhism', 'christianity', 'easternReligion', 'folkReligions', 'hinduism', 'islam', 'judaism', 'mormonism', 'mysticismAndOccult', 'newAge', 'shintoism', 'sikhism', 'unaffiliated', 'afterSchoolCare', 'dinner', 'fundRaiser', 'parking', 'publicSpeaker', 'raffle', 'biotech', 'highTech', 'medicine', 'mobile', 'robotics', 'science', 'socialMedia', 'autumnEvents', 'christmas', 'easter', 'halloweenHaunt', 'hanukkah', 'independenceDay', 'newYearsEve', 'stPatricksDay', 'thanksgiving', 'americanFootball', 'baseball', 'basketball', 'camps', 'cheer', 'cycling', 'exercise', 'fightingMartialArts', 'football', 'golf', 'hockey', 'lacrosse', 'motorsports', 'mountainBiking', 'obstacles', 'rugby', 'running', 'snowSports', 'softball', 'swimmingWaterSports', 'tennis', 'trackField', 'volleyball', 'walking', 'weightlifting', 'wrestling', 'canoeing', 'climbing', 'hiking', 'kayaking', 'rafting', 'travel']] = Field(None, description='Filter events where "event.classification.subcategory" matches this field. If this parameter is provided, then "#/components/parameters/Category" must also be provided.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')
    withArtistsOnly: Optional[StrictBool] = Field(None, description='If true, return only events that have artists.')

    @model_validator(mode="after")
    def category_required(self):
        if self.subcategory is not None and self.category is None:
            raise ValueError("Provide category when filtering by subcategory")
        return self


class ListGlobalEventDatesConfig(_Input):
    """Returns an array of individual event dates from across the platform, with public offer status annotated on every ticket type and packaged ticket. Each event date appears as a separate root-level object (events with multiple dates produce multiple rows). Requires special user permission to use this endpoint, activated by Humanitix."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-tier": "humanitix_global", "x-tier-label": "Humanitix global permission"})
    operation: Literal["list_global_event_dates"] = Field("list_global_event_dates", title="Get Event Dates global", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number you wish to fetch.')
    pageSize: int = Field(100, ge=1, le=100, description='Page size of the results you wish to fetch.')
    type: Optional[Literal['appearanceOrSigning', 'attraction', 'campTripOrRetreat', 'classTrainingOrWorkshop', 'concertOrPerformance', 'conference', 'convention', 'dinnerOrGala', 'festivalOrFair', 'gameOrCompetition', 'meetingOrNetworkingEvent', 'partyOrSocialGathering', 'raceOrEnduranceEvent', 'rally', 'screening', 'seminarOrTalk', 'tour', 'tournament', 'tradeShowConsumerShowOrExpo', 'other']] = Field(None, description='Filter events where "event.classification.type" matches this field.')
    category: Optional[Literal['autoBoatAndAir', 'businessAndProfessional', 'charityAndCauses', 'communityAndCulture', 'familyAndEducation', 'fashionAndBeauty', 'filmMediaAndEntertainment', 'foodAndDrink', 'governmentAndPolitics', 'healthAndWellness', 'hobbiesAndSpecialInterest', 'homeAndLifestyle', 'music', 'performingAndVisualArts', 'religionAndSpirituality', 'schoolActivities', 'scienceAndTechnology', 'seasonalAndHoliday', 'sportsAndFitness', 'travelAndOutdoor', 'other']] = Field(None, description='Filter events where "event.classification.category" matches this field.')
    subcategory: Optional[Literal['air', 'auto', 'boat', 'motorcycle', 'other', 'career', 'design', 'educators', 'environmentAndSustainability', 'finance', 'investment', 'media', 'nonProfitNGO', 'realEstate', 'salesAndMarketing', 'startupsAndBusiness', 'animalWelfare', 'disasterRelief', 'education', 'environment', 'healthcare', 'humanRights', 'internationalAid', 'poverty', 'cityTown', 'county', 'heritage', 'historic', 'lgbt', 'language', 'medieval', 'nationality', 'renaissance', 'state', 'alumni', 'baby', 'childrenAndYouth', 'parenting', 'parentsAssociation', 'reunion', 'seniorCitizen', 'accessories', 'beauty', 'bridal', 'fashion', 'adult', 'anime', 'comedy', 'comics', 'film', 'gaming', 'tv', 'beer', 'food', 'spirits', 'wine', 'countyMunicipalGovernment', 'democraticParty', 'federalGovernment', 'internationalAffairs', 'military', 'nationalSecurity', 'nonPartisan', 'otherParty', 'republicanParty', 'stateGovernment', 'medical', 'mentalHealth', 'personalHealth', 'spa', 'yoga', 'animeComics', 'books', 'diy', 'drawingAndPainting', 'knitting', 'photography', 'dating', 'homeAndGarden', 'petsAndAnimals', 'acoustic', 'alternative', 'americana', 'bluegrass', 'blues', 'bluesAndJazz', 'classical', 'country', 'cultural', 'djDance', 'edm', 'edmElectronic', 'electronic', 'experimental', 'folk', 'hipHopRap', 'indie', 'jazz', 'latin', 'metal', 'opera', 'pop', 'psychedelic', 'punkHardcore', 'rAndB', 'reggae', 'religiousSpiritual', 'rock', 'singerSongwriter', 'top40', 'world', 'ballet', 'craft', 'fineArt', 'jewelry', 'literaryArts', 'musical', 'orchestra', 'painting', 'sculpture', 'theatre', 'agnosticism', 'atheism', 'buddhism', 'christianity', 'easternReligion', 'folkReligions', 'hinduism', 'islam', 'judaism', 'mormonism', 'mysticismAndOccult', 'newAge', 'shintoism', 'sikhism', 'unaffiliated', 'afterSchoolCare', 'dinner', 'fundRaiser', 'parking', 'publicSpeaker', 'raffle', 'biotech', 'highTech', 'medicine', 'mobile', 'robotics', 'science', 'socialMedia', 'autumnEvents', 'christmas', 'easter', 'halloweenHaunt', 'hanukkah', 'independenceDay', 'newYearsEve', 'stPatricksDay', 'thanksgiving', 'americanFootball', 'baseball', 'basketball', 'camps', 'cheer', 'cycling', 'exercise', 'fightingMartialArts', 'football', 'golf', 'hockey', 'lacrosse', 'motorsports', 'mountainBiking', 'obstacles', 'rugby', 'running', 'snowSports', 'softball', 'swimmingWaterSports', 'tennis', 'trackField', 'volleyball', 'walking', 'weightlifting', 'wrestling', 'canoeing', 'climbing', 'hiking', 'kayaking', 'rafting', 'travel']] = Field(None, description='Filter events where "event.classification.subcategory" matches this field. If this parameter is provided, then "#/components/parameters/Category" must also be provided.')
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2, description='The Humanitix market to look up data in: an ISO 3166-1 alpha-2 country code, with DE for the EU market. By default, the API uses the market of the account that owns the API key. Not the venue; see eventLocation.')
    withArtistsOnly: Optional[StrictBool] = Field(None, description='If true, return only events that have artists.')

    @model_validator(mode="after")
    def category_required(self):
        if self.subcategory is not None and self.category is None:
            raise ValueError("Provide category when filtering by subcategory")
        return self


class _HumanitixPollConfig(PollTriggerConfigBase, _Input):
    """Baseline existing records, then emit new ids or changed updatedAt versions."""
    # Canvas metadata must not invalidate the parsed polling scope.
    model_config = ConfigDict(extra="ignore")
    since: Optional[str] = Field(None, title="Since", json_schema_extra={"format": "date-time"},
        description="Only monitor results since this ISO 8601 date-time. Narrow this scope if it exceeds 10,000 records. Existing records form a baseline when armed.")
    overrideLocation: Optional[str] = Field(None, min_length=2, max_length=2,
        description="Humanitix account market (two-letter country code; DE for the EU).")


class OnNewOrUpdatedEventConfig(_HumanitixPollConfig):
    operation: Literal["on_new_or_updated_event"] = Field("on_new_or_updated_event", title="On New or Updated Event",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On New or Updated Event"})


class OnNewOrUpdatedOrderConfig(_HumanitixPollConfig):
    operation: Literal["on_new_or_updated_order"] = Field("on_new_or_updated_order", title="On New or Updated Order",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On New or Updated Order"})
    eventId: ID = Field(..., title="Event ID", description="ID of the event to monitor.")
    eventDateId: Optional[ID] = Field(None, title="Event Date ID", description="Optionally monitor one event date.")


class OnNewOrUpdatedTicketConfig(_HumanitixPollConfig):
    operation: Literal["on_new_or_updated_ticket"] = Field("on_new_or_updated_ticket", title="On New or Updated Ticket",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On New or Updated Ticket"})
    eventId: ID = Field(..., title="Event ID", description="ID of the event to monitor.")
    eventDateId: Optional[ID] = Field(None, title="Event Date ID", description="Optionally monitor one event date.")
    status: Optional[Literal["complete", "cancelled"]] = Field(None, description="Optionally monitor tickets of this status.")


HumanitixConfig = Annotated[Union[ListEventsConfig, GetEventConfig, GetEventCheckInCountConfig, ListOrdersConfig, GetOrderConfig, ListTicketsConfig, GetTicketConfig, CheckInTicketConfig, CheckOutTicketConfig, ListTagsConfig, GetTagConfig, ListGlobalEventsConfig, ListGlobalEventDatesConfig, OnNewOrUpdatedEventConfig, OnNewOrUpdatedOrderConfig, OnNewOrUpdatedTicketConfig], Field(discriminator="operation")]


class HumanitixNodeConfig(NodeConfig[HumanitixConfig, HumanitixAPIKeyCredential]):
    pass


ROUTES = {'list_events': ('GET', '/v1/events'), 'get_event': ('GET', '/v1/events/{eventId}'), 'get_event_check_in_count': ('GET', '/v1/events/{eventId}/check-in-count'), 'list_orders': ('GET', '/v1/events/{eventId}/orders'), 'get_order': ('GET', '/v1/events/{eventId}/orders/{orderId}'), 'list_tickets': ('GET', '/v1/events/{eventId}/tickets'), 'get_ticket': ('GET', '/v1/events/{eventId}/tickets/{ticketId}'), 'check_in_ticket': ('POST', '/v1/events/{eventId}/tickets/{ticketId}/check-in'), 'check_out_ticket': ('POST', '/v1/events/{eventId}/tickets/{ticketId}/check-out'), 'list_tags': ('GET', '/v1/tags'), 'get_tag': ('GET', '/v1/tags/{tagId}'), 'list_global_events': ('GET', '/v1/global/events'), 'list_global_event_dates': ('GET', '/v1/global/event-dates')}


POLL_OPERATIONS = {
    "on_new_or_updated_event": (ListEventsConfig, "events"),
    "on_new_or_updated_order": (ListOrdersConfig, "orders"),
    "on_new_or_updated_ticket": (ListTicketsConfig, "tickets"),
}


class HumanitixNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-humanitix"
    scope_registry = HUMANITIX_SCOPES
    connection_evidence = ConnectionEvidence(noun="events", operation="list_events", label_keys=("name", "_id"))

    @classmethod
    def get_config_model(cls):
        return HumanitixNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in POLL_OPERATIONS:
            return bool(output.get("new_item_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in POLL_OPERATIONS:
            return super().resolve_agent_event(output)
        items = output.get("items", [])
        if not items:
            return None
        resource = output["resource"]
        lines = []
        for item in items[:10]:
            who = " ".join(filter(None, [item.get("firstName"), item.get("lastName")])) if resource != "events" else ""
            label = item.get("name") if resource == "events" else who or resource[:-1]
            details = [f"id {item['_id']}", f"updated {item['updatedAt']}"]
            for field in ("eventId", "orderId", "status") if resource != "events" else ():
                if item.get(field):
                    details.append(f"{field} {item[field]}")
            if output.get("event_id"):
                details.append(f"watched event {output['event_id']}")
            lines.append(f"- {label} ({'; '.join(details)})")
        if len(items) > 10:
            lines.append(f"- … and {len(items) - 10} more")
        return {"text": f"Humanitix: {len(items)} new or updated {resource}:\n" + "\n".join(lines),
            "conversation_key": output.get("event_id")}

    async def _poll(self, config):
        model, resource = POLL_OPERATIONS[config.operation]
        values = config.model_dump(exclude=set(PollTriggerConfigBase.model_fields) | {"operation"}, exclude_none=True)
        items = []
        for page in range(1, 101):
            result = await self._execute_operation(model.model_validate({**values, "page": page, "pageSize": 100}))
            if result["page"] != page or result["page_size"] != 100:
                raise ValueError("Humanitix returned a different poll page than requested")
            items.extend(result["items"])
            # Reject partial snapshots before changing the baseline or consuming new records.
            if result["total"] > 10_000 or len(items) > 10_000:
                raise ValueError("Humanitix poll exceeds 10,000 records; narrow Since or event date")
            if result["next_page"] is None:
                break
        else:
            raise ValueError("Humanitix poll did not finish pagination; narrow Since or event date")
        if any(not isinstance(item.get("_id"), str) or not item["_id"]
               or not isinstance(item.get("updatedAt"), str) or not item["updatedAt"] for item in items):
            raise ValueError("Humanitix poll record is missing its id or update time")
        fresh = await self._filter_unseen(items, lambda item: item["_id"] + ":" + item["updatedAt"])
        return {"status": "success", "operation": config.operation, "resource": resource,
            "event_id": getattr(config, "eventId", None), "items": fresh, "new_item_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Humanitix API key")
        config = self.config.config
        output = await self._poll(config) if config.operation in POLL_OPERATIONS else await self._execute_operation(config)
        await self.emit(output)
        return output

    async def _execute_operation(self, config):
        key = self.config.credentials.api_key
        method, route = ROUTES[config.operation]
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        for name in tuple(params):
            if "{" + name + "}" in route:
                route = route.replace("{" + name + "}", params.pop(name))
        params = {name: str(value).lower() if isinstance(value, bool) else value for name, value in params.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"x-api-key": key, "Accept": "application/json"}, params=params)
        except httpx.TransportError:
            raise ValueError("Humanitix request did not complete" + ("; check the ticket before retrying" if method == "POST" else "")) from None
        if response.status_code != 200:
            # Preserve the provider's rejection text for the connect seam, while
            # never echoing a key that a server or proxy might reflect.
            text = response.text.replace(key, "[redacted]")[:500]
            raise ValueError(f"Humanitix HTTP {response.status_code}: {text}")
        if len(response.content) > 10_000_000 or "application/json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Expected bounded JSON from Humanitix")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Humanitix returned invalid JSON") from None
        if not isinstance(body, dict) or "error" in body or "errors" in body:
            raise ValueError("Humanitix returned an unexpected response")
        output = {"status": "success", "data": body}
        if config.operation.startswith("list_"):
            collection = {"list_global_event_dates": "eventDates"}.get(config.operation, config.operation.removeprefix("list_global_").removeprefix("list_"))
            rows = body.get(collection)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Humanitix returned an invalid list")
            if any(type(body.get(field)) is not int for field in ("page", "pageSize", "total")):
                raise ValueError("Humanitix pagination is missing")
            if body["page"] < 1 or not 1 <= body["pageSize"] <= 100 or body["total"] < 0:
                raise ValueError("Humanitix pagination is invalid")
            output.update(items=rows, page=body["page"], page_size=body["pageSize"], total=body["total"],
                next_page=body["page"] + 1 if body["page"] * body["pageSize"] < body["total"] else None)
        elif method == "POST":
            messages = body.get("scanningMessages")
            if not isinstance(messages, list) or any(not isinstance(row, dict) or not isinstance(row.get("header"), str) or not isinstance(row.get("message"), str) for row in messages):
                raise ValueError("Humanitix did not confirm the scan response; inspect the ticket before retrying")
        # Provider fields stay intact for workflow expressions, with credential
        # reflection removed recursively from both keys and values.
        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]")
            if isinstance(value, dict):
                return {redact(k): redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        output = redact(output)
        return output
