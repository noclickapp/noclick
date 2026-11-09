"""The Events Calendar v1 operations on a person's WordPress site.

Contract: https://docs.theeventscalendar.com/tec-events-v1-doc.json (1.0.0).
Authentication: WordPress Application Passwords via HTTPS Basic authentication.
Only individual-resource writes present in the pinned contract are exposed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client



class TheEventsCalendarCredential(BaseModel):
    model_config = ConfigDict(title="The Events Calendar Application Password", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/",
            "x-credential-instructions": "Enter your WordPress site URL and username, then paste an application password from Users → Profile → Application Passwords (WordPress 5.6+ over HTTPS). Use an account allowed to edit the events, venues, organizers and terms you automate. The connection read shows public site events; it establishes reachability, not account identity or write permissions."
        })
    credential_type: Literal["the_events_calendar_application_password"] = Field("the_events_calendar_application_password", json_schema_extra={"ui:hidden": True})
    site_url: str = Field(..., title="WordPress site URL", description="HTTPS WordPress installation URL, e.g. https://example.com or https://example.com/blog; omit /wp-admin and /wp-json.")
    username: str = Field(..., min_length=1, max_length=255, title="WordPress username")
    application_password: str = Field(..., min_length=1, max_length=4096, title="Application password", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("site_url", mode="before")
    @classmethod
    def site(cls, value):
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise ValueError("Enter the HTTPS WordPress installation URL")
        try:
            parts = urlsplit(value)
            if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None or parts.port not in (None, 443) or parts.query or parts.fragment:
                raise ValueError()
            if not re.fullmatch(r"[A-Za-z0-9.-]+", parts.hostname) or "." not in parts.hostname:
                raise ValueError()
            path = parts.path.rstrip("/")
            if not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", path) or any(x in {".", "..", "wp-admin", "wp-json"} for x in path.split("/")):
                raise ValueError()
        except ValueError:
            raise ValueError("Use an HTTPS site URL without credentials, query, fragment or API/admin path") from None
        return "https://" + parts.hostname.lower() + path

    @field_validator("username")
    @classmethod
    def user(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter a WordPress username without a colon or control characters")
        return value

    @field_validator("application_password")
    @classmethod
    def password(cls, value):
        value = clean_secret(value, field_name="Application password")
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the application password without control characters")
        return value



class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")



class _Page(_Input):
    page: int = Field(1, ge=1, description="Archive page to fetch. Increment for subsequent pages.")
    per_page: int = Field(20, ge=1, le=100, description="Results per page; one page is returned per run.")
    search: str | None = Field(None, max_length=1000)



class _Resource(_Input):
    id: int = Field(..., ge=1, title="Resource ID", description="Existing event, venue, organizer, category or tag ID on this site.")



class _Update(_Resource):
    @model_validator(mode="after")
    def changed(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self



class ListEvents(_Page):
    """List events on the connected site."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    start_date: str | None = Field(None, max_length=100000, description='Start Date')
    end_date: str | None = Field(None, max_length=100000, description='End Date')
    status: str | None = Field(None, max_length=100000, description='Status')
    featured: bool | None = Field(None, description='Featured')
    venue: list[int] | None = Field(None, description='Venue')
    organizer: list[int] | None = Field(None, description='Organizer')


class GetEvent(_Resource):
    """Get event on the connected site."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})


class UpdateEvent(_Update):
    """Update event on the connected site."""
    operation: Literal["update_event"] = Field("update_event", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, max_length=100000, description='The event title')
    description: str | None = Field(None, max_length=100000, description='The event description')
    slug: str | None = Field(None, max_length=100000, description='The event slug')
    excerpt: str | None = Field(None, max_length=100000, description='The event excerpt')
    status: str | None = Field(None, max_length=100000, description='The event post status')
    timezone: str | None = Field(None, max_length=100000, description='The event time zone')
    all_day: bool | None = Field(None, description='Whether the event lasts the whole day or not')
    start_date: str | None = Field(None, max_length=100000, description='The event start date and time')
    end_date: str | None = Field(None, max_length=100000, description='The event end date and time')
    cost: str | None = Field(None, max_length=100000, description='The event cost')
    website: str | None = Field(None, max_length=100000, description='The event website URL')
    show_map: bool | None = Field(None, description='Whether the event should show a map or not')
    show_map_link: bool | None = Field(None, description='Whether the event should show a map link or not')
    hide_from_listings: bool | None = Field(None, description='Whether events should be hidden in the calendar view or not')
    sticky: bool | None = Field(None, description='Whether the event should be sticky in the calendar view or not')
    featured: bool | None = Field(None, description='Whether the event should be featured on the site or not')
    categories: list[int] | None = Field(None, description='The event category ID or name')
    tags: list[int] | None = Field(None, description='The event tag ID or name')
    venue: list[int] | None = Field(None, description='The event venue IDs or data')
    organizer: list[int] | None = Field(None, description='The event organizer IDs or data')


class DeleteEvent(_Resource):
    """Delete event on the connected site."""
    operation: Literal["delete_event"] = Field("delete_event", json_schema_extra={"ui:hidden": True})


class ListVenues(_Page):
    """List venues on the connected site."""
    operation: Literal["list_venues"] = Field("list_venues", json_schema_extra={"ui:hidden": True})
    event: int | None = Field(None, ge=1, description='Event')
    has_events: bool | None = Field(None, description='Has Events')
    only_with_upcoming: bool | None = Field(None, description='Only With Upcoming')
    status: str | None = Field(None, max_length=100000, description='Status')


class GetVenue(_Resource):
    """Get venue on the connected site."""
    operation: Literal["get_venue"] = Field("get_venue", json_schema_extra={"ui:hidden": True})


class UpdateVenue(_Update):
    """Update venue on the connected site."""
    operation: Literal["update_venue"] = Field("update_venue", json_schema_extra={"ui:hidden": True})
    venue: str | None = Field(None, max_length=100000, description='The venue name')
    description: str | None = Field(None, max_length=100000, description='The venue description')
    status: str | None = Field(None, max_length=100000, description='The venue post status')
    show_map: str | None = Field(None, max_length=100000, description='Whether events linked to the venue should show a map or not')
    show_map_link: str | None = Field(None, max_length=100000, description='Whether events linked to the venue should show a map link or not')
    address: str | None = Field(None, max_length=100000, description='The venue address')
    city: str | None = Field(None, max_length=100000, description='The venue city')
    country: str | None = Field(None, max_length=100000, description='The venue country')
    province: str | None = Field(None, max_length=100000, description='The venue province')
    state: str | None = Field(None, max_length=100000, description='The venue state')
    zip: str | None = Field(None, max_length=100000, description='The venue ZIP code')
    phone: str | None = Field(None, max_length=100000, description='The venue phone number')
    stateprovince: str | None = Field(None, max_length=100000, description='The venue state and province')
    website: str | None = Field(None, max_length=100000, description='The venue website URL')


class DeleteVenue(_Resource):
    """Delete venue on the connected site."""
    operation: Literal["delete_venue"] = Field("delete_venue", json_schema_extra={"ui:hidden": True})


class ListOrganizers(_Page):
    """List organizers on the connected site."""
    operation: Literal["list_organizers"] = Field("list_organizers", json_schema_extra={"ui:hidden": True})
    event: int | None = Field(None, ge=1, description='Event')
    has_events: bool | None = Field(None, description='Has Events')
    only_with_upcoming: bool | None = Field(None, description='Only With Upcoming')
    status: str | None = Field(None, max_length=100000, description='Status')


class GetOrganizer(_Resource):
    """Get organizer on the connected site."""
    operation: Literal["get_organizer"] = Field("get_organizer", json_schema_extra={"ui:hidden": True})


class UpdateOrganizer(_Update):
    """Update organizer on the connected site."""
    operation: Literal["update_organizer"] = Field("update_organizer", json_schema_extra={"ui:hidden": True})
    organizer: str | None = Field(None, max_length=100000, description='The organizer name')
    description: str | None = Field(None, max_length=100000, description='The organizer description')
    status: str | None = Field(None, max_length=100000, description='The organizer post status')
    phone: str | None = Field(None, max_length=100000, description='The organizer phone number')
    website: str | None = Field(None, max_length=100000, description='The organizer website')
    email: str | None = Field(None, max_length=100000, description='The organizer e-mail address')


class DeleteOrganizer(_Resource):
    """Delete organizer on the connected site."""
    operation: Literal["delete_organizer"] = Field("delete_organizer", json_schema_extra={"ui:hidden": True})


class ListCategories(_Page):
    """List categories on the connected site."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})
    slug: str | None = Field(None, max_length=100000, description='Slug')
    parent: int | None = Field(None, ge=0, description='Parent')
    hide_empty: bool | None = Field(None, description='Hide Empty')


class GetCategory(_Resource):
    """Get category on the connected site."""
    operation: Literal["get_category"] = Field("get_category", json_schema_extra={"ui:hidden": True})


class UpdateCategory(_Update):
    """Update category on the connected site."""
    operation: Literal["update_category"] = Field("update_category", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=100000, description='The event category name')
    description: str | None = Field(None, max_length=100000, description='The event category description')
    slug: str | None = Field(None, max_length=100000, description='The event category slug')
    parent: int | None = Field(None, ge=0, description='The event category slug')


class DeleteCategory(_Resource):
    """Delete category on the connected site."""
    operation: Literal["delete_category"] = Field("delete_category", json_schema_extra={"ui:hidden": True})


class ListTags(_Page):
    """List tags on the connected site."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    slug: str | None = Field(None, max_length=100000, description='Slug')
    hide_empty: bool | None = Field(None, description='Hide Empty')


class GetTag(_Resource):
    """Get tag on the connected site."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})


class UpdateTag(_Update):
    """Update tag on the connected site."""
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=100000, description='The event tag name')
    description: str | None = Field(None, max_length=100000, description='The event tag description')
    slug: str | None = Field(None, max_length=100000, description='The event tag slug')


class DeleteTag(_Resource):
    """Delete tag on the connected site."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})


TheEventsCalendarOperation = Annotated[Union[
    ListEvents,
    GetEvent,
    UpdateEvent,
    DeleteEvent,
    ListVenues,
    GetVenue,
    UpdateVenue,
    DeleteVenue,
    ListOrganizers,
    GetOrganizer,
    UpdateOrganizer,
    DeleteOrganizer,
    ListCategories,
    GetCategory,
    UpdateCategory,
    DeleteCategory,
    ListTags,
    GetTag,
    UpdateTag,
    DeleteTag
], Field(discriminator="operation")]



class TheEventsCalendarConfig(NodeConfig[TheEventsCalendarOperation, TheEventsCalendarCredential]):
    pass


ROUTES = {
    'list_events': ('GET', '/events', 'events'),
    'get_event': ('GET', '/events/{id}', 'events'),
    'update_event': ('POST', '/events/{id}', 'events'),
    'delete_event': ('DELETE', '/events/{id}', 'events'),
    'list_venues': ('GET', '/venues', 'venues'),
    'get_venue': ('GET', '/venues/{id}', 'venues'),
    'update_venue': ('POST', '/venues/{id}', 'venues'),
    'delete_venue': ('DELETE', '/venues/{id}', 'venues'),
    'list_organizers': ('GET', '/organizers', 'organizers'),
    'get_organizer': ('GET', '/organizers/{id}', 'organizers'),
    'update_organizer': ('POST', '/organizers/{id}', 'organizers'),
    'delete_organizer': ('DELETE', '/organizers/{id}', 'organizers'),
    'list_categories': ('GET', '/categories', 'categories'),
    'get_category': ('GET', '/categories/{id}', 'categories'),
    'update_category': ('POST', '/categories/{id}', 'categories'),
    'delete_category': ('DELETE', '/categories/{id}', 'categories'),
    'list_tags': ('GET', '/tags', 'tags'),
    'get_tag': ('GET', '/tags/{id}', 'tags'),
    'update_tag': ('POST', '/tags/{id}', 'tags'),
    'delete_tag': ('DELETE', '/tags/{id}', 'tags'),
}



class TheEventsCalendarNode(WorkflowNode):
    integration_type = "automation-the-events-calendar"
    connection_evidence = ConnectionEvidence(operation="list_events", noun="site events", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return TheEventsCalendarConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a The Events Calendar application password")
        config = self.config.config
        method, route, kind = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation", "id"})
        path = route.format(id=getattr(config, "id", ""))
        # PHP form arrays use bracketed keys; keep false and empty arrays rather
        # than treating them as omitted updates.
        wire = {}
        for key, value in values.items():
            if isinstance(value, list):
                if method == "GET":
                    wire[key] = ",".join(str(item) for item in value)
                elif value:
                    for index, item in enumerate(value):
                        wire[f"{key}[{index}]"] = str(item)
                else:
                    wire[key] = ""
            else:
                wire[key] = "true" if value is True else "false" if value is False else str(value)
        auth = httpx.BasicAuth(credential.username, credential.application_password)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.site_url + "/wp-json/tribe/events/v1" + path,
                auth=auth, headers={"Accept": "application/json"},
                **({"params": wire} if method == "GET" else {"data": wire} if method == "POST" else {}))
        if response.status_code not in {200, 201}:
            # Preserve the provider rejection for the shared connect verdict;
            # never include the request, which contains credentials.
            try:
                error = response.json().get("message", "The Events Calendar request failed")
            except (ValueError, AttributeError):
                error = "The Events Calendar returned a non-JSON error; check the site URL"
            raise ValueError(f"The Events Calendar HTTP {response.status_code}: {error}")
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected a JSON response from the WordPress site")
        body = response.json()
        if isinstance(body, dict) and "code" in body and "message" in body:
            raise ValueError(str(body["message"]))
        if method == "GET" and config.operation.startswith("list_"):
            # Events archives are envelopes. Venue/organizer/term archives vary
            # across releases between a bare array and a resource envelope.
            items = body.get(kind) if isinstance(body, dict) else body
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("The Events Calendar returned an invalid archive")
            return {"items": items, "page": config.page, "per_page": config.per_page,
                "total": body.get("total") if isinstance(body, dict) else response.headers.get("X-WP-Total"),
                "total_pages": body.get("total_pages") if isinstance(body, dict) else response.headers.get("X-WP-TotalPages")}
        if not isinstance(body, dict) or type(body.get("id")) is not int or body["id"] != config.id:
            raise ValueError("The Events Calendar returned an invalid or mismatched resource")
        return {"data": body}
