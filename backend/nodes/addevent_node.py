"""AddEvent Calendar and Event API v2.14.0.

One operation per published endpoint. API keys are sent only to the fixed API
origin. Searches return a single page with provider pagination; no link is
followed. RSVP and event writes can cause provider reminder/update emails.
Contract: https://docs.addevent.com/openapi/67a502770ad46a0037534f4c
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.addevent.com/calevent/v2"


class AddEventApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="AddEvent API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.addevent.com/account/settings",
            "x-credential-instructions": "Copy your AddEvent API key from account settings. Paste the key without the Bearer prefix.",
        },
    )
    credential_type: Literal["addevent_api_key"] = Field(
        "addevent_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value)
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", regex_engine="python-re")

    @field_validator(
        "event_id", "calendar_id", "attendee_id", "subscriber_id", check_fields=False
    )
    @classmethod
    def resource_id(cls, value):
        if value is not None and (
            value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Supply a resource ID without dot segments or controls")
        return value

    @model_validator(mode="after")
    def paired_filters(self):
        if (
            getattr(self, "sort_order", None) is not None
            and getattr(self, "sort_by", None) is None
        ):
            raise ValueError("Supply sort_by when using sort_order")
        if (getattr(self, "custom_data_key", None) is None) != (
            getattr(self, "custom_data_value", None) is None
        ):
            raise ValueError("Supply both custom_data_key and custom_data_value")
        if (
            getattr(self, "location", None) is not None
            and getattr(self, "location_id", None) is not None
        ):
            raise ValueError("Supply only location or location_id")
        if bool(getattr(self, "organizer_name", None)) != bool(
            getattr(self, "organizer_email", None)
        ):
            raise ValueError("Supply both organizer_name and organizer_email")
        return self


class CreateEventConfig(_Config):
    "Create an event"
    operation: Literal["create_event"] = Field(
        "create_event", title="Create an event", json_schema_extra={"ui:hidden": True}
    )
    title: str = Field(
        ...,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The event's title. It must be a non-empty, single-line string.",
        title="Title",
    )
    calendar_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the calendar that this event will be associated with. Defaults to the default calendar on the account if not provided.",
        title="Calendar Id",
    )
    datetime_start: str = Field(
        ...,
        pattern="^\\d{4}-\\d{2}-\\d{2}(\\s\\d{2}:\\d{2}(:\\d{2})?)?$",
        max_length=100000,
        description="The start date & time of the event. Accepts datetimes in the following formats:\n\n* `YYYY-MM-DD hh:mm:ss` e.g. 2023-11-28 10:00:00\n* `YYYY-MM-DD hh:mm` e.g. 2023-11-28 10:00\n* `YYYY-MM-DD` e.g. 2023-11-28\n",
        title="Datetime Start",
    )
    datetime_end: str | None = Field(
        None,
        pattern="^\\d{4}-\\d{2}-\\d{2}(\\s\\d{2}:\\d{2}(:\\d{2})?)?$",
        max_length=100000,
        description="The end date & time of the event. Accepts datetimes in the following formats:\n\n* `YYYY-MM-DD hh:mm:ss` e.g. 2023-11-28 10:00:00\n* `YYYY-MM-DD hh:mm` e.g. 2023-11-28 10:00\n* `YYYY-MM-DD` e.g. 2023-11-28\n\nDefaults to `datetime_start + 1 hour` if not set.\n",
        title="Datetime End",
    )
    all_day_event: bool | None = Field(
        None,
        description="Whether the event is an all day event. If `true` then the start and end time of the event are ignored, and only the date is used.",
        title="All Day Event",
    )
    timezone: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description='The event\'s timezone. This ensures that the event appears at the correct time for users regardless of their timezone.\n\nThe `List timezones` endpoint returns all of the timezone values that are supported, or you can use our <a href="https://www.addevent.com/c/documentation/tools/time-zone-lookup" target="_blank">Timezone Lookup Tool</a> to find a timezone. Defaults to the calendar\'s timezone if not provided.\n\nThis property also accepts the value `floating`, which means that the event will appear at the same time in each user\'s timezone. For example, the event will be at 2 pm local time for users in Paris and 2 pm for local time for users in San Francisco.\n',
        title="Timezone",
    )
    recurring_rule: str | None = Field(
        None,
        pattern='(?:(\\w+)=((?:(?:[^;,=]+,?)*[^;,=])|"(?:[^"]|"")*");?)+',
        max_length=100000,
        description='The event\'s recurring rule which must use the iCalendar Standard\'s format. See our <a href="https://www.addevent.com/c/documentation/tools/recurring-rule-generator" target="_blank">Recurring Rule Generator</a> for help with generating valid recurring rules.\n\nLeave this property empty to create an even that does not repeat.\n\n**Please note:**\n1. Recurring rules are advanced functionality and need to be tested before using them.\n2. `datetime_start` must match the recurring rule to work in strict calendar systems like Outlook (desktop) and Apple Calendar.\n3. Recurring rules are not supported by Yahoo Calendar.\n',
        title="Recurring Rule",
    )
    description: str | None = Field(
        None,
        max_length=100000,
        description="The event's description. This field accepts plain text or simplified HTML. Use `\\n` to create a new line. Simplified HTML is not supported by all calendar clients, in which case, the content will be automatically converted into readable text.\n\n**Please note:** We recommend keeping your description short and to the point, with a maximum of 500 characters. Some browsers (e.g., Microsoft Edge) limit the number of characters that can be transferred in a URL, so this limit ensures that your event is cross-browser compatible.\n",
        title="Description",
    )
    internal_name: str | None = Field(
        None,
        max_length=100000,
        description="An internal name for the event which will not be displayed publicly. This can be used internally to distinguish between events, to add additional information/context to an event, or to store an external ID that relates to another system.",
        title="Internal Name",
    )
    location: str | None = Field(
        None,
        max_length=100000,
        description="The event's location. This can be an address or a URL, for example, a meeting or webinar link. Only one of `location` and `location_id` can be provided.",
        title="Location",
    )
    location_id: int | None = Field(
        None,
        ge=0,
        description="The ID of the saved location to associate with the event. The value `0` means that a saved location is not being used. Only one of `location` and `location_id` can be provided.",
        title="Location Id",
    )
    organizer_name: str | None = Field(
        None,
        max_length=100000,
        description="The event organizer's name. If `organizer_name` is provided, then `organizer_email` must also be provided. The organizer information is displayed on the event landing page, and including an organizer means the event is considered a `meeting` by calendar clients such as Outlook (desktop) rather than an `appointment`.",
        title="Organizer Name",
    )
    organizer_email: str | None = Field(
        None,
        pattern="^$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
        max_length=100000,
        description="The event organizer's email address. If `organizer_email` is provided, then `organizer_name` must also be provided. The organizer information is displayed on the event landing page, and including an organizer means the event is considered a `meeting` by calendar clients such as Outlook (desktop) rather than an `appointment`.",
        title="Organizer Email",
    )
    reminder: int | None = Field(
        None,
        ge=0,
        le=10800,
        description="The number of minutes prior to the start of an event that a reminder notification will be sent to the user via their calendar app. Event reminders are currently only supported by:\n* Apple calendar\n* Outlook desktop\n* Office 365 and Outlook.com (when using the Microsoft Events API)\n",
        title="Reminder",
    )
    color: int | None = Field(
        None,
        ge=1,
        le=20,
        description="The event's color. This appears in the dashboard and on calendar landing pages or embeddable calendars. Accepts values between `1` and `20` that correspond to the colors on the calendar's palette.",
        title="Color",
    )
    free_busy: Literal["free", "busy", "default"] | None = Field(
        None,
        max_length=100000,
        description="Indicates whether the event appears as *free* or *busy* when the user adds it to their calendar. Accepts the following values:\n* `free`: the event appears as free and does not block the user's calendars\n* `busy`: the event appears as busy and blocks the user's calendar\n* `default`: the event uses the user's default free/busy setting\n",
        title="Free Busy",
    )
    landing_page_template_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom event landing page template to associate with the event. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom template, which can be retrieved with the `List event templates` endpoint.",
        title="Landing Page Template Id",
    )
    rsvp_enabled: bool | None = Field(
        None,
        description="Whether the event requires a user to respond and enter their information before adding the event to their calendar.",
        title="Rsvp Enabled",
    )
    rsvp_form_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom RSVP form to associate with the event. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom RSVP form, which can be retrieved with the `List RSVP forms` endpoint.",
        title="Rsvp Form Id",
    )
    custom_data: dict[str, object] | None = Field(
        None,
        description="Arbitary key-value pairs that can be attached to an event. Useful for storing additional structured data on an object, for example, storing external IDs to link an event to another system or linking to custom images for each event. `snake_case` should be used for custom data keys.",
        title="Custom Data",
    )


class SearchEventsConfig(_Config):
    "Search events"
    operation: Literal["search_events"] = Field(
        "search_events", title="Search events", json_schema_extra={"ui:hidden": True}
    )
    calendar_ids: list[str] | None = Field(
        None,
        description="Comma-separated list of calendar IDs. Limits search results to those specific calendars.",
        title="Calendar Ids",
    )
    event_ids: list[str] | None = Field(
        None,
        description="Comma-separated list of event IDs. Limits search results to those specific events.",
        title="Event Ids",
    )
    datetime_min: str | None = Field(
        None,
        pattern="^\\d{4}-\\d{2}-\\d{2}(\\s\\d{2}:\\d{2}(:\\d{2})?)?$",
        max_length=100000,
        description="Limits search results to events that *end after* this time, i.e. `datetime_end >= datetime_min`. Timezones are not considered when doing this comparison, it simply compares the naive datetimes. If `datetime_min` is provided, then the default sorting is changed to `datetime_start, asc`.\n\nAccepts datetimes in the following formats:\n\n* `YYYY-MM-DD hh:mm:ss` e.g. 2023-11-28 10:00:00\n* `YYYY-MM-DD hh:mm` e.g. 2023-11-28 10:00\n* `YYYY-MM-DD` e.g. 2023-11-28\n",
        title="Datetime Min",
    )
    datetime_max: str | None = Field(
        None,
        pattern="^\\d{4}-\\d{2}-\\d{2}(\\s\\d{2}:\\d{2}(:\\d{2})?)?$",
        max_length=100000,
        description="Limits search results to events that *start before* this time, i.e. `datetime_start =< datetime_max`. Timezones are not considered when doing this comparison, it simply compares the naive datetimes. If `datetime_max` is provided, then the default sorting is changed to `datetime_start, asc`.\n\nAccepts datetimes in the following formats:\n\n* `YYYY-MM-DD hh:mm:ss` e.g. 2023-11-28 10:00:00\n* `YYYY-MM-DD hh:mm` e.g. 2023-11-28 10:00\n* `YYYY-MM-DD` e.g. 2023-11-28\n",
        title="Datetime Max",
    )
    search: str | None = Field(
        None,
        max_length=100000,
        description="Search term that searches across an event's `title`, `internal_name`, `description`, and `location`. Searches are case-insensitive.",
        title="Search",
    )
    custom_data_key: str | None = Field(
        None,
        max_length=100000,
        description="Limits search results to objects with a given key-value pair in the `custom_data` field. If `custom_data_key` is provided, then `custom_data_value` must also be provided.",
        title="Custom Data Key",
    )
    custom_data_value: str | None = Field(
        None,
        max_length=100000,
        description="Limits search results to objects with a given key-value pair in the `custom_data` field. If `custom_data_value` is provided, then `custom_data_key` must also be provided.",
        title="Custom Data Value",
    )
    page: int | None = Field(
        None,
        ge=1,
        description="Page number of the search results. The first page of results is `page=1`.",
        title="Page",
    )
    page_size: int | None = Field(
        None,
        ge=1,
        le=20,
        description="A limit on the number of objects to be returned. `page_size` must be between 1 and 20, and the default is 10.",
        title="Page Size",
    )
    sort_by: Literal[
        "created", "title", "calendar_id", "datetime_start"
    ] | None = Field(
        None,
        max_length=100000,
        description="The event property to sort by. Allowed values are `created`, `title`, `calendar_id`, or `datetime_start`. If `sort_order` is provided, then `sort_by` must also be provided. The default sorting is `created, desc` *unless* `datetime_start` or `datetime_end` is provided, in which case the default sorting is `datetime_start, asc`.",
        title="Sort By",
    )
    sort_order: Literal["asc", "desc"] | None = Field(
        None,
        max_length=100000,
        description="The order of the returned search results, sorted by the property specified in `sort_by`. Allowed values are `asc` or `desc`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort Order",
    )


class RetrieveEventConfig(_Config):
    "Retrieve an event"
    operation: Literal["retrieve_event"] = Field(
        "retrieve_event",
        title="Retrieve an event",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the event.",
        title="Event Id",
    )


class UpdateEventConfig(_Config):
    "Update an event"
    operation: Literal["update_event"] = Field(
        "update_event", title="Update an event", json_schema_extra={"ui:hidden": True}
    )
    event_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the event.",
        title="Event Id",
    )
    title: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The event's title. It must be a non-empty, single-line string.",
        title="Title",
    )
    calendar_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the calendar the event is associated with.",
        title="Calendar Id",
    )
    datetime_start: str | None = Field(
        None,
        pattern="^\\d{4}-\\d{2}-\\d{2}(\\s\\d{2}:\\d{2}(:\\d{2})?)?$",
        max_length=100000,
        description="The start date & time of the event. Accepts datetimes in the following formats:\n\n* `YYYY-MM-DD hh:mm:ss` e.g. 2023-11-28 10:00:00\n* `YYYY-MM-DD hh:mm` e.g. 2023-11-28 10:00\n* `YYYY-MM-DD` e.g. 2023-11-28\n",
        title="Datetime Start",
    )
    datetime_end: str | None = Field(
        None,
        pattern="^\\d{4}-\\d{2}-\\d{2}(\\s\\d{2}:\\d{2}(:\\d{2})?)?$",
        max_length=100000,
        description="The end date & time of the event. Accepts datetimes in the following formats:\n\n* `YYYY-MM-DD hh:mm:ss` e.g. 2023-11-28 10:00:00\n* `YYYY-MM-DD hh:mm` e.g. 2023-11-28 10:00\n* `YYYY-MM-DD` e.g. 2023-11-28\n",
        title="Datetime End",
    )
    all_day_event: bool | None = Field(
        None,
        description="Whether the event is an all day event. If `true` then the start and end time of the event are ignored, and only the date is used.",
        title="All Day Event",
    )
    timezone: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description='The event\'s timezone. This ensures that the event appears at the correct time for users regardless of their timezone.\n\nThe `List timezones` endpoint returns all of the timezone values that are supported, or you can use our <a href="https://www.addevent.com/c/documentation/tools/time-zone-lookup" target="_blank">Timezone Lookup Tool</a> to find a timezone. Defaults to the calendar\'s timezone if not provided.\n\nThis property also accepts the value `floating`, which means that the event will appear at the same time in each user\'s timezone. For example, the event will be at 2 pm local time for users in Paris and 2 pm for local time for users in San Francisco.\n',
        title="Timezone",
    )
    recurring_rule: str | None = Field(
        None,
        pattern='(?:(\\w+)=((?:(?:[^;,=]+,?)*[^;,=])|"(?:[^"]|"")*");?)+',
        max_length=100000,
        description='The event\'s recurring rule which must use the iCalendar Standard\'s format. See our <a href="https://www.addevent.com/c/documentation/tools/recurring-rule-generator" target="_blank">Recurring Rule Generator</a> for help with generating valid recurring rules.\n\nLeave this property empty to create an even that does not repeat.\n\n**Please note:**\n1. Recurring rules are advanced functionality and need to be tested before using them.\n2. `datetime_start` must match the recurring rule to work in strict calendar systems like Outlook (desktop) and Apple Calendar.\n3. Recurring rules are not supported by Yahoo Calendar.\n',
        title="Recurring Rule",
    )
    description: str | None = Field(
        None,
        max_length=100000,
        description="The event's description. This field accepts plain text or simplified HTML. Use `\\n` to create a new line. Simplified HTML is not supported by all calendar clients, in which case, the content will be automatically converted into readable text.\n\n**Please note:** We recommend keeping your description short and to the point, with a maximum of 500 characters. Some browsers (e.g., Microsoft Edge) limit the number of characters that can be transferred in a URL, so this limit ensures that your event is cross-browser compatible.\n",
        title="Description",
    )
    internal_name: str | None = Field(
        None,
        max_length=100000,
        description="An internal name for the event which will not be displayed publicly. This can be used internally to distinguish between events, to add additional information/context to an event, or to store an external ID that relates to another system.",
        title="Internal Name",
    )
    location: str | None = Field(
        None,
        max_length=100000,
        description="The event's location. This can be an address or a URL, for example, a meeting or webinar link. Only one of `location` and `location_id` can be provided.",
        title="Location",
    )
    location_id: int | None = Field(
        None,
        ge=0,
        description="The ID of the saved location to associate with the event. The value `0` means that a saved location is not being used. Only one of `location` and `location_id` can be provided.",
        title="Location Id",
    )
    organizer_name: str | None = Field(
        None,
        max_length=100000,
        description="The event organizer's name. If `organizer_name` is provided, then `organizer_email` must also be provided. The organizer information is displayed on the event landing page, and including an organizer means the event is considered a `meeting` by calendar clients such as Outlook (desktop) rather than an `appointment`.",
        title="Organizer Name",
    )
    organizer_email: str | None = Field(
        None,
        pattern="^$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
        max_length=100000,
        description="The event organizer's email address. If `organizer_email` is provided, then `organizer_name` must also be provided. The organizer information is displayed on the event landing page, and including an organizer means the event is considered a `meeting` by calendar clients such as Outlook (desktop) rather than an `appointment`.",
        title="Organizer Email",
    )
    reminder: int | None = Field(
        None,
        ge=0,
        le=10800,
        description="The number of minutes prior to the start of an event that a reminder notification will be sent to the user via their calendar app. Event reminders are currently only supported by:\n* Apple calendar\n* Outlook desktop\n* Office 365 and Outlook.com (when using the Microsoft Events API)\n",
        title="Reminder",
    )
    color: int | None = Field(
        None,
        ge=1,
        le=20,
        description="The event's color. This appears in the dashboard and on calendar landing pages or embeddable calendars. Accepts values between `1` and `20` that correspond to the colors on the calendar's palette.",
        title="Color",
    )
    free_busy: Literal["free", "busy", "default"] | None = Field(
        None,
        max_length=100000,
        description="Indicates whether the event appears as *free* or *busy* when the user adds it to their calendar. Accepts the following values:\n* `free`: the event appears as free and does not block the user's calendars\n* `busy`: the event appears as busy and blocks the user's calendar\n* `default`: the event uses the user's default free/busy setting\n",
        title="Free Busy",
    )
    landing_page_template_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom event landing page template to associate with the event. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom template, which can be retrieved with the `List event templates` endpoint.",
        title="Landing Page Template Id",
    )
    rsvp_enabled: bool | None = Field(
        None,
        description="Whether the event requires a user to respond and enter their information before adding the event to their calendar.",
        title="Rsvp Enabled",
    )
    rsvp_form_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom RSVP form to associate with the event. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom RSVP form, which can be retrieved with the `List RSVP forms` endpoint.",
        title="Rsvp Form Id",
    )
    custom_data: dict[str, object] | None = Field(
        None,
        description="Arbitary key-value pairs that can be attached to an event. Useful for storing additional structured data on an object, for example, storing external IDs to link an event to another system or linking to custom images for each event. `snake_case` should be used for custom data keys.",
        title="Custom Data",
    )

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(
            getattr(self, k) is not None
            for k in (
                "title",
                "calendar_id",
                "datetime_start",
                "datetime_end",
                "all_day_event",
                "timezone",
                "recurring_rule",
                "description",
                "internal_name",
                "location",
                "location_id",
                "organizer_name",
                "organizer_email",
                "reminder",
                "color",
                "free_busy",
                "landing_page_template_id",
                "rsvp_enabled",
                "rsvp_form_id",
                "custom_data",
            )
        ):
            raise ValueError("Supply at least one field to update")
        return self


class DeleteEventConfig(_Config):
    "Delete an event"
    operation: Literal["delete_event"] = Field(
        "delete_event", title="Delete an event", json_schema_extra={"ui:hidden": True}
    )
    event_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the event.",
        title="Event Id",
    )


class CreateCalendarConfig(_Config):
    "Create a calendar"
    operation: Literal["create_calendar"] = Field(
        "create_calendar",
        title="Create a calendar",
        json_schema_extra={"ui:hidden": True},
    )
    title: str = Field(
        ...,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The calendar's title. It must be a non-empty, single-line string.",
        title="Title",
    )
    timezone: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description='The default timezone for events created on this calendar. The `List timezones` endpoint returns all of the timezone values that are supported, or you can use our <a href="https://www.addevent.com/c/documentation/tools/time-zone-lookup" target="_blank">Timezone Lookup Tool</a> to find a timezone. Defaults to `America/Los_Angeles`.\n',
        title="Timezone",
    )
    weekday_begin: Literal["sunday", "monday"] | None = Field(
        None,
        max_length=100000,
        description="The day of the week that the calendar starts on. Values are `sunday` or `monday`.",
        title="Weekday Begin",
    )
    description: str | None = Field(
        None,
        max_length=100000,
        description="The calendar's description. This appears on the calendar landing page and can be used to display additional information to users about the calendar. Accepts plain text and simplified HTML.",
        title="Description",
    )
    internal_name: str | None = Field(
        None,
        max_length=100000,
        description="An internal name for the calendar which will not be displayed publicly. This can be used internally to distinguish between calendars, to add additional information/context to a calendar, or to store an external ID that relates to another system.",
        title="Internal Name",
    )
    calendar_color: int | None = Field(
        None,
        ge=1,
        le=20,
        description="The color of the calendar. This appears in the dashboard. Accepts values between `1` and `20` that correspond to the colors on the calendar's palette.",
        title="Calendar Color",
    )
    landing_page_template_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom calendar landing page template to associate with the calendar. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom template, which can be retrieved with the `List calendar templates` endpoint.",
        title="Landing Page Template Id",
    )
    embeddable_calendar_template_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom embeddable calendar template to associate with the calendar. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom template, which can be retrieved with the `List calendar templates` endpoint.",
        title="Embeddable Calendar Template Id",
    )
    custom_data: dict[str, object] | None = Field(
        None,
        description="Arbitary key-value pairs that can be attached to a calendar. Useful for storing additional structured data on an object, for example, storing external IDs to link a calendar to another system or linking to custom images for each calendar.",
        title="Custom Data",
    )


class SearchCalendarsConfig(_Config):
    "Search calendars"
    operation: Literal["search_calendars"] = Field(
        "search_calendars",
        title="Search calendars",
        json_schema_extra={"ui:hidden": True},
    )
    calendar_ids: list[str] | None = Field(
        None,
        description="Comma-separated list of calendar IDs. Limits search results to those specific calendars.",
        title="Calendar Ids",
    )
    page: int | None = Field(
        None,
        ge=1,
        description="Page number of the search results. The first page of results is `page=1`.",
        title="Page",
    )
    page_size: int | None = Field(
        None,
        ge=1,
        le=20,
        description="A limit on the number of objects to be returned. `page_size` must be between 1 and 20, and the default is 10.",
        title="Page Size",
    )
    sort_by: Literal["created", "title"] | None = Field(
        None,
        max_length=100000,
        description="The calendar property to sort by. Allowed values are `created`, or `title`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort By",
    )
    sort_order: Literal["asc", "desc"] | None = Field(
        None,
        max_length=100000,
        description="The order of the returned search results, sorted by the property specified in `sort_by`. Allowed values are `asc` or `desc`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort Order",
    )


class RetrieveCalendarConfig(_Config):
    "Retrieve a calendar"
    operation: Literal["retrieve_calendar"] = Field(
        "retrieve_calendar",
        title="Retrieve a calendar",
        json_schema_extra={"ui:hidden": True},
    )
    calendar_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the calendar.",
        title="Calendar Id",
    )


class UpdateCalendarConfig(_Config):
    "Update a calendar"
    operation: Literal["update_calendar"] = Field(
        "update_calendar",
        title="Update a calendar",
        json_schema_extra={"ui:hidden": True},
    )
    calendar_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the calendar.",
        title="Calendar Id",
    )
    title: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The calendar's title. It must be a non-empty, single-line string.",
        title="Title",
    )
    timezone: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description='The default timezone for events created on this calendar. The `List timezones` endpoint returns all of the timezone values that are supported, or you can use our <a href="https://www.addevent.com/c/documentation/tools/time-zone-lookup" target="_blank">Timezone Lookup Tool</a> to find a timezone. Defaults to `America/Los_Angeles`.\n',
        title="Timezone",
    )
    weekday_begin: Literal["sunday", "monday"] | None = Field(
        None,
        max_length=100000,
        description="The day of the week that the calendar starts on. Values are `sunday` or `monday`.",
        title="Weekday Begin",
    )
    description: str | None = Field(
        None,
        max_length=100000,
        description="The calendar's description. This appears on the calendar landing page and can be used to display additional information to users about the calendar. Accepts plain text and simplified HTML.",
        title="Description",
    )
    internal_name: str | None = Field(
        None,
        max_length=100000,
        description="An internal name for the calendar which will not be displayed publicly. This can be used internally to distinguish between calendars, to add additional information/context to a calendar, or to store an external ID that relates to another system.",
        title="Internal Name",
    )
    calendar_color: int | None = Field(
        None,
        ge=1,
        le=20,
        description="The color of the calendar. This appears in the dashboard. Accepts values between `1` and `20` that correspond to the colors on the calendar's palette.",
        title="Calendar Color",
    )
    landing_page_template_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom calendar landing page template to associate with the calendar. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom template, which can be retrieved with the `List calendar templates` endpoint.",
        title="Landing Page Template Id",
    )
    embeddable_calendar_template_id: str | None = Field(
        None,
        pattern="^(?!\\s*$).+",
        max_length=100000,
        description="The ID of the custom embeddable calendar template to associate with the calendar. Accepts the value `default`, which uses the standard AddEvent template, or the ID of a custom template, which can be retrieved with the `List calendar templates` endpoint.",
        title="Embeddable Calendar Template Id",
    )
    custom_data: dict[str, object] | None = Field(
        None,
        description="Arbitary key-value pairs that can be attached to a calendar. Useful for storing additional structured data on an object, for example, storing external IDs to link a calendar to another system or linking to custom images for each calendar.",
        title="Custom Data",
    )

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(
            getattr(self, k) is not None
            for k in (
                "title",
                "timezone",
                "weekday_begin",
                "description",
                "internal_name",
                "calendar_color",
                "landing_page_template_id",
                "embeddable_calendar_template_id",
                "custom_data",
            )
        ):
            raise ValueError("Supply at least one field to update")
        return self


class DeleteCalendarConfig(_Config):
    "Delete a calendar"
    operation: Literal["delete_calendar"] = Field(
        "delete_calendar",
        title="Delete a calendar",
        json_schema_extra={"ui:hidden": True},
    )
    calendar_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the calendar.",
        title="Calendar Id",
    )


class CreateRsvpAttendeeConfig(_Config):
    "Create an RSVP attendee"
    operation: Literal["create_rsvp_attendee"] = Field(
        "create_rsvp_attendee",
        title="Create an RSVP attendee",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the event.",
        title="Event Id",
    )
    email: str = Field(
        ...,
        pattern="^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
        max_length=100000,
        description="Email address of the RSVP attendee. Update and reminder emails about the event will be sent to this email address. Email addresses must be unique for each attendee of a given event.",
        title="Email",
    )
    attending: Literal["going", "maybe", "not-going"] | None = Field(
        None,
        max_length=100000,
        description="The attendee's response to the event. The following responses are allowed: `going`, `maybe`, `not-going`.\n",
        title="Attending",
    )
    notify: Literal["active"] | None = Field(
        None,
        max_length=100000,
        description="By default, no attendee confirmation or organizer notification emails are sent when a new RSVP attendee is created via the API. If this parameter is set to `active` then when a new RSVP attendee is created via the API:\n\n* an attendee confirmation email is sent to the RSVP attendee's email address if confirmation emails are enabled for the event\n* an internal organizer notification email is sent to to the organizer notification email addresses listed under RSVP settings(`notify_emails`) if `notify_frequency` is set to `all` for an event.\n\nNote that attendee reminder and follow-up emails are not affected by this setting.\n",
        title="Notify",
    )
    rsvp_form_data: dict[str, object] | None = Field(
        None,
        description="The default RSVP form has one required input field (`name`: the user's name). **You must provide a value for this field when making the request.**\n\nCreate a custom RSVP forms to collect additional information about your RSVP attendees - https://dashboard.addevent.com/forms/rsvp\n",
        title="Rsvp Form Data",
    )

    @model_validator(mode="after")
    def form_name(self):
        if not self.rsvp_form_data:
            raise ValueError(
                "Supply rsvp_form_data with name for the default form, or the required fields for your custom form"
            )
        return self


class SearchRsvpAttendeesConfig(_Config):
    "Search RSVP attendees"
    operation: Literal["search_rsvp_attendees"] = Field(
        "search_rsvp_attendees",
        title="Search RSVP attendees",
        json_schema_extra={"ui:hidden": True},
    )
    calendar_ids: list[str] | None = Field(
        None,
        description="Comma-separated list of calendar IDs. Limits search results to those specific calendars.",
        title="Calendar Ids",
    )
    event_ids: list[str] | None = Field(
        None,
        description="Comma-separated list of event IDs. Limits search results to those specific events.",
        title="Event Ids",
    )
    attending: list[Literal["going", "maybe", "not-going"]] | None = Field(
        None,
        description="Only return attendees that RSVP'd with a specific response. Allowed values are `going`, `maybe`, `not-going`.",
        title="Attending",
    )
    page: int | None = Field(
        None,
        ge=1,
        description="Page number of the search results. The first page of results is `page=1`.",
        title="Page",
    )
    page_size: int | None = Field(
        None,
        ge=1,
        le=20,
        description="A limit on the number of objects to be returned. `page_size` must be between 1 and 20, and the default is 10.",
        title="Page Size",
    )
    sort_by: Literal["created", "event_id", "attending", "email"] | None = Field(
        None,
        max_length=100000,
        description="The RSVP attendee property to sort by. Allowed values are `created`, `email`, `event_id`, or `attending`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort By",
    )
    sort_order: Literal["asc", "desc"] | None = Field(
        None,
        max_length=100000,
        description="The order of the returned search results, sorted by the property specified in `sort_by`. Allowed values are `asc` or `desc`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort Order",
    )


class RetrieveRsvpAttendeeConfig(_Config):
    "Retrieve an RSVP attendee"
    operation: Literal["retrieve_rsvp_attendee"] = Field(
        "retrieve_rsvp_attendee",
        title="Retrieve an RSVP attendee",
        json_schema_extra={"ui:hidden": True},
    )
    attendee_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the RSVP attendee.",
        title="Attendee Id",
    )


class UpdateRsvpAttendeeConfig(_Config):
    "Update an RSVP attendee"
    operation: Literal["update_rsvp_attendee"] = Field(
        "update_rsvp_attendee",
        title="Update an RSVP attendee",
        json_schema_extra={"ui:hidden": True},
    )
    attendee_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the RSVP attendee.",
        title="Attendee Id",
    )
    email: str | None = Field(
        None,
        pattern="^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
        max_length=100000,
        description="Email address of the RSVP attendee. Update and reminder emails about the event will be sent to this email address. Email addresses must be unique for each attendee of a given event.",
        title="Email",
    )
    attending: Literal["going", "maybe", "not-going"] | None = Field(
        None,
        max_length=100000,
        description="The attendee's response to the event. The following responses are allowed: `going`, `maybe`, `not-going`.\n",
        title="Attending",
    )
    notify: Literal["active"] | None = Field(
        None,
        max_length=100000,
        description="By default, no attendee confirmation or organizer notification emails are sent when a new RSVP attendee is created via the API. If this parameter is set to `active` then when a new RSVP attendee is created via the API:\n\n* an attendee confirmation email is sent to the RSVP attendee's email address if confirmation emails are enabled for the event\n* an internal organizer notification email is sent to to the organizer notification email addresses listed under RSVP settings(`notify_emails`) if `notify_frequency` is set to `all` for an event.\n\nNote that attendee reminder and follow-up emails are not affected by this setting.\n",
        title="Notify",
    )
    rsvp_form_data: dict[str, object] | None = Field(
        None,
        description="The default RSVP form has one required input field (`name`: the user's name). **You must provide a value for this field when making the request.**\n\nCreate a custom RSVP forms to collect additional information about your RSVP attendees - https://dashboard.addevent.com/forms/rsvp\n",
        title="Rsvp Form Data",
    )

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(
            getattr(self, k) is not None
            for k in ("email", "attending", "notify", "rsvp_form_data")
        ):
            raise ValueError("Supply at least one field to update")
        return self


class DeleteRsvpAttendeeConfig(_Config):
    "Delete an RSVP attendee"
    operation: Literal["delete_rsvp_attendee"] = Field(
        "delete_rsvp_attendee",
        title="Delete an RSVP attendee",
        json_schema_extra={"ui:hidden": True},
    )
    attendee_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the RSVP attendee.",
        title="Attendee Id",
    )


class SearchCalendarSubscribersConfig(_Config):
    "Search calendar subscribers"
    operation: Literal["search_calendar_subscribers"] = Field(
        "search_calendar_subscribers",
        title="Search calendar subscribers",
        json_schema_extra={"ui:hidden": True},
    )
    calendar_ids: list[str] | None = Field(
        None,
        description="Comma-separated list of calendar IDs. Limits search results to those specific calendars.",
        title="Calendar Ids",
    )
    status: list[Literal["active", "inactive", "blocked"]] | None = Field(
        None,
        description="Only return subscribers with a specific status. Allowed values are:\n\n* `active`: The calendar subscriber's feed has synced in the last 30 days.\n* `inactive`: The calendar subscriber's feed has not synced in the last 30 days.\n* `blocked`: The calendar subscriber has been blocked by the calendar owner. The calendar subscriber's feed will not show any events.\n",
        title="Status",
    )
    page: int | None = Field(
        None,
        ge=1,
        description="Page number of the search results. The first page of results is `page=1`.",
        title="Page",
    )
    page_size: int | None = Field(
        None,
        ge=1,
        le=20,
        description="A limit on the number of objects to be returned. `page_size` must be between 1 and 20, and the default is 10.",
        title="Page Size",
    )
    sort_by: Literal["created", "synced", "calendar_id"] | None = Field(
        None,
        max_length=100000,
        description="The calendar subscriber property to sort by. Allowed values are `created`, `synced`, or `calendar_id`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort By",
    )
    sort_order: Literal["asc", "desc"] | None = Field(
        None,
        max_length=100000,
        description="The order of the returned search results, sorted by the property specified in `sort_by`. Allowed values are `asc` or `desc`. If `sort_order` is provided, then `sort_by` must also be provided.",
        title="Sort Order",
    )


class RetrieveCalendarSubscriberConfig(_Config):
    "Retrieve a calendar subscriber"
    operation: Literal["retrieve_calendar_subscriber"] = Field(
        "retrieve_calendar_subscriber",
        title="Retrieve a calendar subscriber",
        json_schema_extra={"ui:hidden": True},
    )
    subscriber_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the calendar subscriber.",
        title="Subscriber Id",
    )


class DeleteCalendarSubscriberConfig(_Config):
    "Delete a calendar subscriber"
    operation: Literal["delete_calendar_subscriber"] = Field(
        "delete_calendar_subscriber",
        title="Delete a calendar subscriber",
        json_schema_extra={"ui:hidden": True},
    )
    subscriber_id: str = Field(
        ...,
        pattern="^\\S+$",
        max_length=100000,
        description="Unique identifier for the calendar subscriber.",
        title="Subscriber Id",
    )


class ListRsvpFormsConfig(_Config):
    "List RSVP forms"
    operation: Literal["list_rsvp_forms"] = Field(
        "list_rsvp_forms",
        title="List RSVP forms",
        json_schema_extra={"ui:hidden": True},
    )


class ListEventTemplatesConfig(_Config):
    "List event templates"
    operation: Literal["list_event_templates"] = Field(
        "list_event_templates",
        title="List event templates",
        json_schema_extra={"ui:hidden": True},
    )
    type: Literal["event-landing"] | None = Field(
        None,
        max_length=100000,
        description="The type of event template to return. The only allowed value is `event-landing`.",
        title="Type",
    )


class ListCalendarTemplatesConfig(_Config):
    "List calendar templates"
    operation: Literal["list_calendar_templates"] = Field(
        "list_calendar_templates",
        title="List calendar templates",
        json_schema_extra={"ui:hidden": True},
    )
    type: Literal["calendar-landing", "calendar-embed"] | None = Field(
        None,
        max_length=100000,
        description="The type of calendar template to return. Allowed values are `calendar-landing` or `embeddable-calendar`.",
        title="Type",
    )


class ListTimezonesConfig(_Config):
    "List timezones"
    operation: Literal["list_timezones"] = Field(
        "list_timezones", title="List timezones", json_schema_extra={"ui:hidden": True}
    )


Operation = Annotated[
    Union[
        CreateEventConfig,
        SearchEventsConfig,
        RetrieveEventConfig,
        UpdateEventConfig,
        DeleteEventConfig,
        CreateCalendarConfig,
        SearchCalendarsConfig,
        RetrieveCalendarConfig,
        UpdateCalendarConfig,
        DeleteCalendarConfig,
        CreateRsvpAttendeeConfig,
        SearchRsvpAttendeesConfig,
        RetrieveRsvpAttendeeConfig,
        UpdateRsvpAttendeeConfig,
        DeleteRsvpAttendeeConfig,
        SearchCalendarSubscribersConfig,
        RetrieveCalendarSubscriberConfig,
        DeleteCalendarSubscriberConfig,
        ListRsvpFormsConfig,
        ListEventTemplatesConfig,
        ListCalendarTemplatesConfig,
        ListTimezonesConfig,
    ],
    Field(discriminator="operation"),
]


class AddEventFullConfig(NodeConfig[Operation, AddEventApiKeyCredential]):
    model_config = ConfigDict(title="AddEvent Node Configuration")


OPERATIONS = {
    "create_event": {
        "method": "POST",
        "path": "/events",
        "path_fields": [],
        "query": {},
        "body": [
            "title",
            "calendar_id",
            "datetime_start",
            "datetime_end",
            "all_day_event",
            "timezone",
            "recurring_rule",
            "description",
            "internal_name",
            "location",
            "location_id",
            "organizer_name",
            "organizer_email",
            "reminder",
            "color",
            "free_busy",
            "landing_page_template_id",
            "rsvp_enabled",
            "rsvp_form_id",
            "custom_data",
        ],
        "status": 201,
    },
    "search_events": {
        "method": "GET",
        "path": "/events",
        "path_fields": [],
        "query": {
            "calendar_ids": False,
            "event_ids": False,
            "datetime_min": True,
            "datetime_max": True,
            "search": True,
            "custom_data_key": True,
            "custom_data_value": True,
            "page": True,
            "page_size": True,
            "sort_by": True,
            "sort_order": True,
        },
        "body": [],
        "status": 200,
    },
    "retrieve_event": {
        "method": "GET",
        "path": "/events/{event_id}",
        "path_fields": ["event_id"],
        "query": {},
        "body": [],
        "status": 200,
    },
    "update_event": {
        "method": "PATCH",
        "path": "/events/{event_id}",
        "path_fields": ["event_id"],
        "query": {},
        "body": [
            "title",
            "calendar_id",
            "datetime_start",
            "datetime_end",
            "all_day_event",
            "timezone",
            "recurring_rule",
            "description",
            "internal_name",
            "location",
            "location_id",
            "organizer_name",
            "organizer_email",
            "reminder",
            "color",
            "free_busy",
            "landing_page_template_id",
            "rsvp_enabled",
            "rsvp_form_id",
            "custom_data",
        ],
        "status": 200,
    },
    "delete_event": {
        "method": "DELETE",
        "path": "/events/{event_id}",
        "path_fields": ["event_id"],
        "query": {},
        "body": [],
        "status": 204,
    },
    "create_calendar": {
        "method": "POST",
        "path": "/calendars",
        "path_fields": [],
        "query": {},
        "body": [
            "title",
            "timezone",
            "weekday_begin",
            "description",
            "internal_name",
            "calendar_color",
            "landing_page_template_id",
            "embeddable_calendar_template_id",
            "custom_data",
        ],
        "status": 201,
    },
    "search_calendars": {
        "method": "GET",
        "path": "/calendars",
        "path_fields": [],
        "query": {
            "calendar_ids": False,
            "page": True,
            "page_size": True,
            "sort_by": True,
            "sort_order": True,
        },
        "body": [],
        "status": 200,
    },
    "retrieve_calendar": {
        "method": "GET",
        "path": "/calendars/{calendar_id}",
        "path_fields": ["calendar_id"],
        "query": {},
        "body": [],
        "status": 200,
    },
    "update_calendar": {
        "method": "PATCH",
        "path": "/calendars/{calendar_id}",
        "path_fields": ["calendar_id"],
        "query": {},
        "body": [
            "title",
            "timezone",
            "weekday_begin",
            "description",
            "internal_name",
            "calendar_color",
            "landing_page_template_id",
            "embeddable_calendar_template_id",
            "custom_data",
        ],
        "status": 200,
    },
    "delete_calendar": {
        "method": "DELETE",
        "path": "/calendars/{calendar_id}",
        "path_fields": ["calendar_id"],
        "query": {},
        "body": [],
        "status": 204,
    },
    "create_rsvp_attendee": {
        "method": "POST",
        "path": "/events/{event_id}/rsvps",
        "path_fields": ["event_id"],
        "query": {},
        "body": ["email", "attending", "notify", "rsvp_form_data"],
        "status": 201,
    },
    "search_rsvp_attendees": {
        "method": "GET",
        "path": "/rsvps",
        "path_fields": [],
        "query": {
            "calendar_ids": False,
            "event_ids": False,
            "attending": True,
            "page": True,
            "page_size": True,
            "sort_by": True,
            "sort_order": True,
        },
        "body": [],
        "status": 200,
    },
    "retrieve_rsvp_attendee": {
        "method": "GET",
        "path": "/rsvps/{attendee_id}",
        "path_fields": ["attendee_id"],
        "query": {},
        "body": [],
        "status": 200,
    },
    "update_rsvp_attendee": {
        "method": "PATCH",
        "path": "/rsvps/{attendee_id}",
        "path_fields": ["attendee_id"],
        "query": {},
        "body": ["email", "attending", "notify", "rsvp_form_data"],
        "status": 200,
    },
    "delete_rsvp_attendee": {
        "method": "DELETE",
        "path": "/rsvps/{attendee_id}",
        "path_fields": ["attendee_id"],
        "query": {},
        "body": [],
        "status": 204,
    },
    "search_calendar_subscribers": {
        "method": "GET",
        "path": "/subscribers",
        "path_fields": [],
        "query": {
            "calendar_ids": False,
            "status": True,
            "page": True,
            "page_size": True,
            "sort_by": True,
            "sort_order": True,
        },
        "body": [],
        "status": 200,
    },
    "retrieve_calendar_subscriber": {
        "method": "GET",
        "path": "/subscribers/{subscriber_id}",
        "path_fields": ["subscriber_id"],
        "query": {},
        "body": [],
        "status": 200,
    },
    "delete_calendar_subscriber": {
        "method": "DELETE",
        "path": "/subscribers/{subscriber_id}",
        "path_fields": ["subscriber_id"],
        "query": {},
        "body": [],
        "status": 204,
    },
    "list_rsvp_forms": {
        "method": "GET",
        "path": "/events/rsvp-forms",
        "path_fields": [],
        "query": {},
        "body": [],
        "status": 200,
    },
    "list_event_templates": {
        "method": "GET",
        "path": "/events/templates",
        "path_fields": [],
        "query": {"type": True},
        "body": [],
        "status": 200,
    },
    "list_calendar_templates": {
        "method": "GET",
        "path": "/calendars/templates",
        "path_fields": [],
        "query": {"type": True},
        "body": [],
        "status": 200,
    },
    "list_timezones": {
        "method": "GET",
        "path": "/timezones",
        "path_fields": [],
        "query": {},
        "body": [],
        "status": 200,
    },
}


class AddEventNode(WorkflowNode):
    integration_type = "automation-addevent"
    credential_provider_labels = {"addevent": "AddEvent"}
    connection_evidence = ConnectionEvidence(
        noun="calendars", operation="search_calendars", label_keys=("title", "id")
    )

    @classmethod
    def get_config_model(cls):
        return AddEventFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an AddEvent API key")
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        for key in spec["path_fields"]:
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = []
        for key, explode in spec["query"].items():
            if key not in values:
                continue
            value = values[key]
            if isinstance(value, list):
                if explode:
                    params.extend((key, item) for item in value)
                else:
                    params.append((key, ",".join(value)))
            else:
                params.append((key, value))
        body = {key: values[key] for key in spec["body"] if key in values}
        headers = {
            "Authorization": "Bearer " + self.config.credentials.api_key,
            "Accept": "application/json",
        }
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                spec["method"],
                BASE + path,
                params=params,
                headers=headers,
                **({"json": body} if spec["body"] else {}),
            )
        if response.status_code != spec["status"]:
            # Keep provider rejection wording for the shared connect evidence seam.
            message = response.text[:1000].replace(
                self.config.credentials.api_key, "[redacted]"
            )
            raise ValueError(f"AddEvent HTTP {response.status_code}: {message}")
        if spec["status"] == 204:
            return {"status": "success", "deleted": True}
        if len(response.content) > 5_000_000:
            raise ValueError("AddEvent response exceeds the supported size")
        data = response.json()
        if config.operation.startswith("list_"):
            if not isinstance(data, list):
                raise ValueError("Expected an AddEvent list")
            return {"status": "success", "items": data}
        if not isinstance(data, dict):
            raise ValueError("Expected an AddEvent object")
        if config.operation.startswith("search_"):
            key = {
                "search_events": "events",
                "search_calendars": "calendars",
                "search_rsvp_attendees": "rsvps",
                "search_calendar_subscribers": "subscribers",
            }[config.operation]
            if not isinstance(data.get(key), list):
                raise ValueError("Expected AddEvent search results")
            return {
                "status": "success",
                "items": data[key],
                "pagination": data.get("pagination"),
                "links": data.get("links"),
            }
        return {"status": "success", "data": data}
