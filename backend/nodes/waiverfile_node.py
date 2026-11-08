"""WaiverFile v1 waiver, event, form and subscriber operations.

Routes and authentication placements follow the pinned provider Swagger contract.
JSON converted from XML is preserved, including singleton collections and strings.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.waiverfile.com"
CREDENTIAL_TYPE = "waiverfile_api_key"
DOCS = "https://api.waiverfile.com/swagger/docs/v1"


class WaiverfileAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Waiverfile API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.waiverfile.com/",
            "x-credential-instructions": "In your WaiverFile admin, open Settings > API Keys. Paste the API key and its site ID (GUID). The key must belong to that site."})
    credential_type: Literal["waiverfile_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    site_id: UUID = Field(..., title="Site ID", description="Site GUID belonging to this API key.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def dates_and_references(self):
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end and _date(start) > _date(end):
            raise ValueError("End date must be on or after start date")
        if getattr(self, "operation", None) == "get_waivers_by_reference_id" and not any(
            getattr(self, key) for key in ("ref_id1", "ref_id2", "ref_id3", "ref_id_any")
        ):
            raise ValueError("Supply at least one reference ID")
        return self


def _date(value):
    # WaiverFile query dates are UTC without an offset. Treat naive inputs as UTC.
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat()


class WaiverfileGetSiteDetailsConfig(_Operation):
    """Get the details of your WaiverFile site."""
    operation: Literal["get_site_details"] = Field("get_site_details", title="Get Site Details", json_schema_extra={"ui:hidden": True})


class WaiverfileGetWaiverConfig(_Operation):
    """Get a single signed waiver with all of its related data."""
    operation: Literal["get_waiver"] = Field("get_waiver", title="Get Waiver", json_schema_extra={"ui:hidden": True})
    waiver_id: UUID


class WaiverfileGetWaiverLiteConfig(_Operation):
    """Get a single signed waiver with only the collected form data (no agreement text, event details or signatures)."""
    operation: Literal["get_waiver_lite"] = Field("get_waiver_lite", title="Get Waiver Lite", json_schema_extra={"ui:hidden": True})
    waiver_id: UUID


class WaiverfileSearchWaiversConfig(_Operation):
    """Search all of your waivers by name (or by your configured quick-search fields)."""
    operation: Literal["search_waivers"] = Field("search_waivers", title="Search Waivers", json_schema_extra={"ui:hidden": True})
    terms: str = Field(..., min_length=1, max_length=1000)


class WaiverfileGetWaiversByReferenceIdConfig(_Operation):
    """Get waivers that match one or more reference IDs."""
    operation: Literal["get_waivers_by_reference_id"] = Field("get_waivers_by_reference_id", title="Get Waivers By Reference Id", json_schema_extra={"ui:hidden": True})
    ref_id1: str | None = None
    ref_id2: str | None = None
    ref_id3: str | None = None
    ref_id_any: str | None = None


class WaiverfileCountWaiversConfig(_Operation):
    """Get the number of waivers signed in a date range, to plan paging through GetAllWaiversByDateRange."""
    operation: Literal["count_waivers"] = Field("count_waivers", title="Count Waivers", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime


class WaiverfileListWaiversConfig(_Operation):
    """Get a page of full waiver records signed within a date range."""
    operation: Literal["list_waivers"] = Field("list_waivers", title="List Waivers", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime
    page_index: int = Field(0, ge=0, le=2147483647, description="Zero-based waiver page.")
    page_size: int = Field(100, ge=10, le=500)


class WaiverfileListWaiversLiteConfig(_Operation):
    """Get a page of waivers signed within a date range, with only the collected form data (no agreement text, event details or signatures)."""
    operation: Literal["list_waivers_lite"] = Field("list_waivers_lite", title="List Waivers Lite", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime
    page_index: int = Field(0, ge=0, le=2147483647, description="Zero-based waiver page.")
    page_size: int = Field(100, ge=10, le=500)


class WaiverfileGetWaiverDataConfig(_Operation):
    """Get a page of waiver data as flat, report-style rows (one row per participant)."""
    operation: Literal["get_waiver_data"] = Field("get_waiver_data", title="Get Waiver Data", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime
    include_custom_columns: bool = False
    consolidate_participants: bool = Field(False, description="Reserved by WaiverFile; results remain one row per participant.")
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based report page.")
    page_size: int = Field(100, ge=10, le=500)


class WaiverfileCountWaiverDataConfig(_Operation):
    """Get the number of rows GetWaiverData will return for a date range."""
    operation: Literal["count_waiver_data"] = Field("count_waiver_data", title="Count Waiver Data", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime


class WaiverfileListActiveWaiverFormsConfig(_Operation):
    """Get the waiver forms that are currently active on your site."""
    operation: Literal["list_active_waiver_forms"] = Field("list_active_waiver_forms", title="List Active Waiver Forms", json_schema_extra={"ui:hidden": True})


class WaiverfileListAllWaiverFormsConfig(_Operation):
    """Get all waiver forms on your site, including disabled and deleted forms."""
    operation: Literal["list_all_waiver_forms"] = Field("list_all_waiver_forms", title="List All Waiver Forms", json_schema_extra={"ui:hidden": True})


class WaiverfileListEventsConfig(_Operation):
    """Get events (in any category) that fall within a date range. Dates are in UTC."""
    operation: Literal["list_events"] = Field("list_events", title="List Events", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime


class WaiverfileListEventsByCategoryConfig(_Operation):
    """Get events in a specific event category that fall within a date range. Dates are in UTC."""
    operation: Literal["list_events_by_category"] = Field("list_events_by_category", title="List Events By Category", json_schema_extra={"ui:hidden": True})
    event_category_id: UUID
    start_date: datetime
    end_date: datetime


class WaiverfileListUpcomingEventsConfig(_Operation):
    """Get events (in any category) within a date range, up to 3,000 events. Dates are in UTC."""
    operation: Literal["list_upcoming_events"] = Field("list_upcoming_events", title="List Upcoming Events", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime


class WaiverfileListEventWaiversConfig(_Operation):
    """Get the waivers signed for an event."""
    operation: Literal["list_event_waivers"] = Field("list_event_waivers", title="List Event Waivers", json_schema_extra={"ui:hidden": True})
    event_id: UUID


class WaiverfileListEventCategoriesConfig(_Operation):
    """Get your site's event categories."""
    operation: Literal["list_event_categories"] = Field("list_event_categories", title="List Event Categories", json_schema_extra={"ui:hidden": True})
    include_disabled_categories: bool = False


class WaiverfileCreateEventConfig(_Operation):
    """Create an event with dates, category, location, forms, capacity and signing cutoff."""
    operation: Literal["create_event"] = Field("create_event", title="Create Event", json_schema_extra={"ui:hidden": True})
    event_name: str = Field(..., min_length=1, max_length=1000)
    start_date: datetime
    end_date: datetime
    is_all_day: bool = False
    event_category_id: UUID
    event_location: str | None = Field(None, max_length=2000)
    max_participants: int = Field(0, ge=-1, le=2147483647)
    waiver_form_id_list: str = Field("", description="Comma-separated waiver form GUIDs. Empty attaches all active forms.")
    signing_cutoff: datetime

    @field_validator("waiver_form_id_list")
    @classmethod
    def form_ids(cls, value):
        for item in value.replace(",", " ").split():
            UUID(item)
        return value


class WaiverfileUpdateEventConfig(_Operation):
    """Update an existing event's name, dates, all-day flag, category and attached waiver forms."""
    operation: Literal["update_event"] = Field("update_event", title="Update Event", json_schema_extra={"ui:hidden": True})
    event_id: UUID
    event_name: str = Field(..., min_length=1, max_length=1000)
    start_date: datetime
    end_date: datetime
    is_all_day: bool = False
    event_category_id: UUID
    waiver_form_ids: list[UUID] = Field(..., description="Replaces attached forms. Empty attaches all active forms.")


class WaiverfileDeleteEventConfig(_Operation):
    """Delete an event."""
    operation: Literal["delete_event"] = Field("delete_event", title="Delete Event", json_schema_extra={"ui:hidden": True})
    event_id: UUID


class WaiverfileCreateEventCategoryConfig(_Operation):
    """Create a new event category."""
    operation: Literal["create_event_category"] = Field("create_event_category", title="Create Event Category", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    active: bool = True


class WaiverfileUpdateEventCategoryConfig(_Operation):
    """Rename an event category and set whether it is active."""
    operation: Literal["update_event_category"] = Field("update_event_category", title="Update Event Category", json_schema_extra={"ui:hidden": True})
    event_category_id: UUID
    name: str = Field(..., min_length=1, max_length=1000)
    active: bool = True


class WaiverfileDeleteEventCategoryConfig(_Operation):
    """Delete an event category."""
    operation: Literal["delete_event_category"] = Field("delete_event_category", title="Delete Event Category", json_schema_extra={"ui:hidden": True})
    event_category_id: UUID


class WaiverfileListSubscribersConfig(_Operation):
    """Get SMS subscribers who were added within a date range. Dates are in UTC."""
    operation: Literal["list_subscribers"] = Field("list_subscribers", title="List Subscribers", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime


class WaiverfileListOptedOutSubscribersConfig(_Operation):
    """Get SMS subscribers who opted out within a date range. Dates are in UTC."""
    operation: Literal["list_opted_out_subscribers"] = Field("list_opted_out_subscribers", title="List Opted Out Subscribers", json_schema_extra={"ui:hidden": True})
    start_date: datetime
    end_date: datetime


Operation = Annotated[Union[WaiverfileGetSiteDetailsConfig, WaiverfileGetWaiverConfig, WaiverfileGetWaiverLiteConfig, WaiverfileSearchWaiversConfig, WaiverfileGetWaiversByReferenceIdConfig, WaiverfileCountWaiversConfig, WaiverfileListWaiversConfig, WaiverfileListWaiversLiteConfig, WaiverfileGetWaiverDataConfig, WaiverfileCountWaiverDataConfig, WaiverfileListActiveWaiverFormsConfig, WaiverfileListAllWaiverFormsConfig, WaiverfileListEventsConfig, WaiverfileListEventsByCategoryConfig, WaiverfileListUpcomingEventsConfig, WaiverfileListEventWaiversConfig, WaiverfileListEventCategoriesConfig, WaiverfileCreateEventConfig, WaiverfileUpdateEventConfig, WaiverfileDeleteEventConfig, WaiverfileCreateEventCategoryConfig, WaiverfileUpdateEventCategoryConfig, WaiverfileDeleteEventCategoryConfig, WaiverfileListSubscribersConfig, WaiverfileListOptedOutSubscribersConfig], Field(discriminator="operation")]


class WaiverfileFullConfig(NodeConfig[Operation, WaiverfileAPIKeyCredential]):
    pass


ROUTES = {'get_site_details': ['GET', '/api/v1/GetSiteDetails', {}],
 'get_waiver': ['GET', '/api/v1/GetWaiver', {'waiver_id': 'waiverID'}],
 'get_waiver_lite': ['GET', '/api/v1/GetWaiverLite', {'waiver_id': 'waiverID'}],
 'search_waivers': ['GET', '/api/v1/SearchWaivers', {'terms': 'terms'}],
 'get_waivers_by_reference_id': ['GET',
                                 '/api/v1/GetWaiversByReferenceID',
                                 {'ref_id1': 'refID1',
                                  'ref_id2': 'refID2',
                                  'ref_id3': 'refID3',
                                  'ref_id_any': 'refIDAny'}],
 'count_waivers': ['GET',
                   '/api/v1/GetAllWaiversByDateRangePageCount',
                   {'start_date': 'startDate', 'end_date': 'endDate'}],
 'list_waivers': ['GET',
                  '/api/v1/GetAllWaiversByDateRange',
                  {'start_date': 'startDate',
                   'end_date': 'endDate',
                   'page_index': 'pageIndex',
                   'page_size': 'pageSize'}],
 'list_waivers_lite': ['GET',
                       '/api/v1/GetAllWaiversByDateRangeLite',
                       {'start_date': 'startDate',
                        'end_date': 'endDate',
                        'page_index': 'pageIndex',
                        'page_size': 'pageSize'}],
 'get_waiver_data': ['GET',
                     '/api/v1/GetWaiverData',
                     {'start_date': 'startDate',
                      'end_date': 'endDate',
                      'include_custom_columns': 'includeCustomColumns',
                      'consolidate_participants': 'consolidateParticipants',
                      'page_index': 'pageIndex',
                      'page_size': 'pageSize'}],
 'count_waiver_data': ['GET',
                       '/api/v1/GetWaiverDataCount',
                       {'start_date': 'startDate', 'end_date': 'endDate'}],
 'list_active_waiver_forms': ['GET', '/api/v1/GetActiveWaiverForms', {}],
 'list_all_waiver_forms': ['GET', '/api/v1/GetAllWaiverForms', {}],
 'list_events': ['GET',
                 '/api/v1/GetEventsByDateRange',
                 {'start_date': 'startDateUTC', 'end_date': 'endDateUTC'}],
 'list_events_by_category': ['GET',
                             '/api/v1/GetEventsByCategory',
                             {'event_category_id': 'eventCategoryID',
                              'start_date': 'startDateUTC',
                              'end_date': 'endDateUTC'}],
 'list_upcoming_events': ['GET',
                          '/api/v1/GetUpcomingEvents',
                          {'start_date': 'startDateUTC', 'end_date': 'endDateUTC'}],
 'list_event_waivers': ['GET', '/api/v1/GetWaiversForEvent', {'event_id': 'waiverEventID'}],
 'list_event_categories': ['GET',
                           '/api/v1/GetEventCategories',
                           {'include_disabled_categories': 'includeDisabledCategories'}],
 'create_event': ['POST',
                  '/api/v1/InsertEvent',
                  {'event_name': 'EventName',
                   'start_date': 'DateStart',
                   'end_date': 'DateEnd',
                   'is_all_day': 'IsAllDay',
                   'event_category_id': 'EventCategoryID',
                   'event_location': 'EventLocation',
                   'max_participants': 'MaxParticipants',
                   'waiver_form_id_list': 'WaiverFormIDList',
                   'signing_cutoff': 'SigningCutoff'}],
 'update_event': ['POST',
                  '/api/v1/UpdateEvent',
                  {'event_id': 'eventID',
                   'event_name': 'eventName',
                   'start_date': 'dateStart',
                   'end_date': 'dateEnd',
                   'is_all_day': 'isAllDay',
                   'event_category_id': 'eventCategoryID',
                   'waiver_form_ids': 'waiverFormIDs'}],
 'delete_event': ['GET', '/api/v1/DeleteEvent', {'event_id': 'eventID'}],
 'create_event_category': ['POST',
                           '/api/v1/InsertEventCategory',
                           {'name': 'name', 'active': 'active'}],
 'update_event_category': ['POST',
                           '/api/v1/UpdateEventCategory',
                           {'event_category_id': 'eventCategoryID',
                            'name': 'name',
                            'active': 'active'}],
 'delete_event_category': ['POST',
                           '/api/v1/DeleteEventCategory',
                           {'event_category_id': 'eventCategoryID'}],
 'list_subscribers': ['GET',
                      '/api/v1/GetSubscribersByDate',
                      {'start_date': 'startDateUTC', 'end_date': 'endDateUTC'}],
 'list_opted_out_subscribers': ['GET',
                                '/api/v1/GetOptedOutSubscribersByOptOutDate',
                                {'start_date': 'startDateUTC', 'end_date': 'endDateUTC'}]}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


def _wire(value):
    if isinstance(value, datetime):
        return _date(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_wire(item) for item in value]
    return value


class WaiverfileNode(WorkflowNode):
    integration_type = "automation-waiverfile"
    connection_evidence = ConnectionEvidence(operation="get_site_details", noun="WaiverFile site", label_keys=("Name", "Url", "ID"))

    @classmethod
    def get_config_model(cls):
        return WaiverfileFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a WaiverFile API key and site ID")
        credential, config = self.config.credentials, self.config.config
        method, path, fields = ROUTES[config.operation]
        values = {wire: _wire(getattr(config, name)) for name, wire in fields.items() if getattr(config, name) is not None}
        body = None
        params = {"apiKey": credential.api_key, "siteID": str(credential.site_id)}
        if config.operation == "create_event":
            # InsertEvent explicitly requires UTC or offset-qualified body dates.
            for field in ("DateStart", "DateEnd", "SigningCutoff"):
                values[field] += "Z"
            body = {"APIKey": credential.api_key, "SiteID": str(credential.site_id), **values}
            params = {}
        else:
            if config.operation == "update_event":
                body = values.pop("waiverFormIDs")
                values["dateStart"] += "Z"
                values["dateEnd"] += "Z"
            params.update(values)
        params = {k: "true" if v is True else "false" if v is False else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, BASE + path, params=params, headers={"Accept": "application/json"},
                        **({"json": body} if body is not None else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 20_000_000:
                            raise ValueError("WaiverFile response exceeds 20 MB; reduce the date range or page size")
                    if response.status_code != 200:
                        return {"status": "error", "http_status": response.status_code,
                            "error": _redact(raw.decode("utf-8", errors="replace")[:2000], credential.api_key),
                            "write_outcome": "unverified" if config.operation.startswith(("create_", "update_", "delete_")) else None}
                    try:
                        data = json.loads(raw)
                        if config.operation == "list_upcoming_events" and isinstance(data, str):
                            data = json.loads(data)
                    except (ValueError, UnicodeError):
                        raise ValueError("WaiverFile returned a non-JSON response") from None
            if not isinstance(data, (dict, list, int)) or isinstance(data, bool):
                raise ValueError("WaiverFile returned an unexpected response shape")
            if isinstance(data, dict) and (data.get("error") or data.get("Error") or data.get("success") is False):
                raise ValueError("WaiverFile returned an error envelope")
            if config.operation == "get_site_details" and (not isinstance(data, dict) or not data.get("Name") or str(data.get("ID", "")).lower() != str(credential.site_id)):
                raise ValueError("WaiverFile did not return the selected site's identity")
            if config.operation in {"count_waivers", "count_waiver_data"} and (type(data) is not int or data < 0):
                raise ValueError("WaiverFile did not return a nonnegative count")
            output = {"status": "success", "operation": config.operation, "data": _redact(data, credential.api_key)}
            if config.operation in {"list_waivers", "list_waivers_lite", "get_waiver_data"}:
                # One API operation returns one page. Do not silently combine separate API calls.
                output.update(page_index=config.page_index, page_size=config.page_size)
            await self.emit(output)
            return output
        except httpx.HTTPError:
            raise ValueError("WaiverFile request did not complete; inspect before retrying a write") from None
