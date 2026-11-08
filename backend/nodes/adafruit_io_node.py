"""Adafruit IO v2 feed, data and group automation using a pasted account key.

Each action makes one documented request; list results represent one API page.
The current-user read supplies account-specific connection evidence.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://io.adafruit.com/api/v2"
FAMILY = "adafruit_io_api_key"


class AdafruitIOAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Adafruit IO API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://io.adafruit.com/",
            "x-credential-instructions": "In Adafruit IO, click the gold key icon or View Adafruit IO Key. Paste your username and active account key. NoClick sends the key in the X-AIO-Key header to io.adafruit.com. Connection checks show the account returned by the key.",
        })
    credential_type: Literal["adafruit_io_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Adafruit IO username")
    api_key: str = Field(..., min_length=1, max_length=4096, title="Adafruit IO key", repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Adafruit IO key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCurrentUser(_Input):
    """Get the identity belonging to the supplied account key."""
    operation: Literal["get_current_user"] = "get_current_user"


class GetThrottle(_Input):
    """Get the account's data rate limit and current usage."""
    operation: Literal["get_throttle"] = "get_throttle"


class ListFeeds(_Input):
    """List one API page of feeds and their latest values."""
    operation: Literal["list_feeds"] = "list_feeds"


class _FeedInput(_Input):
    feed_key: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$",
                          description="Feed key, including its group prefix when present.")


class GetFeed(_FeedInput):
    """Read feed settings and its latest value."""
    operation: Literal["get_feed"] = "get_feed"


class GetFeedDetails(_FeedInput):
    """Read feed settings, sharing and stored-data details."""
    operation: Literal["get_feed_details"] = "get_feed_details"


class _FeedFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=10000)
    license: str | None = Field(None, max_length=255)


class CreateFeed(_FeedFields):
    """Create a feed, optionally in a selected group."""
    operation: Literal["create_feed"] = "create_feed"
    name: str = Field(..., min_length=1, max_length=128)
    group_key: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class UpdateFeed(_FeedFields, _FeedInput):
    """Update selected feed properties without replacing its data."""
    operation: Literal["update_feed"] = "update_feed"

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, f) is None for f in ("name", "description", "license")):
            raise ValueError("Supply a feed property to update")
        return self


class DeleteFeed(_FeedInput):
    """Permanently delete a feed and its stored data."""
    operation: Literal["delete_feed"] = "delete_feed"


class ListData(_FeedInput):
    """Read one page of data; use next_end_time for an older page."""
    operation: Literal["list_data"] = "list_data"
    limit: int = Field(100, ge=1, le=1000)
    start_time: str | None = Field(None, json_schema_extra={"format": "date-time"})
    end_time: str | None = Field(None, json_schema_extra={"format": "date-time"})

    @field_validator("start_time", "end_time")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Use an ISO 8601 timestamp with a time zone")
        return value

    @model_validator(mode="after")
    def time_order(self):
        if self.start_time and self.end_time and datetime.fromisoformat(self.start_time.replace("Z", "+00:00")) >= datetime.fromisoformat(self.end_time.replace("Z", "+00:00")):
            raise ValueError("end_time must be after start_time")
        return self


class _DataInput(_FeedInput):
    data_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$",
                         description="ID of the data point in this feed.")

    @field_validator("data_id")
    @classmethod
    def point_id(cls, value):
        if value in {"last", "first", "next", "previous", "retain", "chart", "batch"}:
            raise ValueError("Supply a data point ID, not a data endpoint name")
        return value


class GetData(_DataInput):
    """Read a selected data point."""
    operation: Literal["get_data"] = "get_data"


class _DataFields(_FeedInput):
    value: str = Field(..., min_length=1, max_length=102400,
                       description="Value to store. History-enabled feeds accept at most 1 KB; feeds without history accept at most 100 KB.")
    lat: str | None = Field(None, description="Latitude as a decimal string.")
    lon: str | None = Field(None, description="Longitude as a decimal string.")
    ele: str | None = Field(None, description="Elevation as a decimal string.")

    @field_validator("lat", "lon", "ele")
    @classmethod
    def coordinate(cls, value, info):
        if value is not None:
            if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) or len(value) > 32:
                raise ValueError("Use a finite decimal location value")
            bound = {"lat": 90, "lon": 180}.get(info.field_name)
            if bound is not None and abs(float(value)) > bound:
                raise ValueError("Location is outside its valid range")
        return value

    @field_validator("value")
    @classmethod
    def byte_limit(cls, value):
        if len(value.encode("utf-8")) > 102400:
            raise ValueError("Data value exceeds 100 KB")
        return value


class CreateData(_DataFields):
    """Append a data point to a feed; this can activate feed automations."""
    operation: Literal["create_data"] = "create_data"


class UpdateData(_DataFields, _DataInput):
    """Update the value and optional location of a stored data point."""
    operation: Literal["update_data"] = "update_data"


class DeleteData(_DataInput):
    """Permanently delete a selected data point."""
    operation: Literal["delete_data"] = "delete_data"


class GetLastData(_FeedInput):
    """Read the newest point and move the API queue pointer to the end."""
    operation: Literal["get_last_data"] = "get_last_data"


class GetFirstData(_FeedInput):
    """Read the oldest point and move the API queue pointer to the beginning."""
    operation: Literal["get_first_data"] = "get_first_data"


class ListGroups(_Input):
    """List one API page of groups with their feeds."""
    operation: Literal["list_groups"] = "list_groups"


class _GroupInput(_Input):
    group_key: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class GetGroup(_GroupInput):
    """Read a group and its feeds."""
    operation: Literal["get_group"] = "get_group"


class CreateGroup(_Input):
    """Create a named group for organizing feeds."""
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(None, max_length=10000)


class UpdateGroup(_GroupInput):
    """Update a group's name or description."""
    operation: Literal["update_group"] = "update_group"
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.description is None:
            raise ValueError("Supply a group property to update")
        return self


class ListGroupFeeds(_GroupInput):
    """List one API page of feeds belonging to a group."""
    operation: Literal["list_group_feeds"] = "list_group_feeds"


AdafruitIOConfig = Annotated[Union[
    GetCurrentUser, GetThrottle, ListFeeds, GetFeed, GetFeedDetails, CreateFeed,
    UpdateFeed, DeleteFeed, ListData, GetData, CreateData, UpdateData, DeleteData,
    GetLastData, GetFirstData, ListGroups, GetGroup, CreateGroup, UpdateGroup,
    ListGroupFeeds,
], Field(discriminator="operation")]


class AdafruitIOFullConfig(NodeConfig[AdafruitIOConfig, AdafruitIOAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "get_current_user": ("GET", "/user"),
    "get_throttle": ("GET", "/{username}/throttle"),
    "list_feeds": ("GET", "/{username}/feeds"),
    "get_feed": ("GET", "/{username}/feeds/{feed_key}"),
    "get_feed_details": ("GET", "/{username}/feeds/{feed_key}/details"),
    "create_feed": ("POST", "/{username}/feeds"),
    "update_feed": ("PATCH", "/{username}/feeds/{feed_key}"),
    "delete_feed": ("DELETE", "/{username}/feeds/{feed_key}"),
    "list_data": ("GET", "/{username}/feeds/{feed_key}/data"),
    "get_data": ("GET", "/{username}/feeds/{feed_key}/data/{data_id}"),
    "create_data": ("POST", "/{username}/feeds/{feed_key}/data"),
    "update_data": ("PATCH", "/{username}/feeds/{feed_key}/data/{data_id}"),
    "delete_data": ("DELETE", "/{username}/feeds/{feed_key}/data/{data_id}"),
    "get_last_data": ("GET", "/{username}/feeds/{feed_key}/data/last"),
    "get_first_data": ("GET", "/{username}/feeds/{feed_key}/data/first"),
    "list_groups": ("GET", "/{username}/groups"),
    "get_group": ("GET", "/{username}/groups/{group_key}"),
    "create_group": ("POST", "/{username}/groups"),
    "update_group": ("PATCH", "/{username}/groups/{group_key}"),
    "list_group_feeds": ("GET", "/{username}/groups/{group_key}/feeds"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()
                if k.lower() not in {"api_key", "aio_key", "password", "token", "x-aio-key"}}
    return value


class AdafruitIONode(WorkflowNode):
    integration_type = "automation-adafruit-io"
    connection_evidence = ConnectionEvidence(noun="Adafruit IO account",
        identity_operation="get_current_user", identity_keys=("username", "name"))

    @classmethod
    def get_config_model(cls):
        return AdafruitIOFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Supply an Adafruit IO API key credential")
        credential = self.config.credentials
        config = self.config.config
        operation = config.operation
        method, template = ROUTES[operation]
        fields = config.model_dump(exclude_none=True, exclude={"operation"})
        path = template.format(**{k: quote(str(v), safe="") for k, v in
                                  {**fields, "username": credential.username}.items()})
        params, body = {}, None
        if isinstance(config, ListData):
            params = {k: fields[k] for k in ("limit", "start_time", "end_time") if k in fields}
        elif isinstance(config, (CreateFeed, UpdateFeed)):
            body = {"feed": {k: fields[k] for k in ("name", "description", "license") if k in fields}}
            if isinstance(config, CreateFeed) and config.group_key:
                params["group_key"] = config.group_key
        elif isinstance(config, (CreateGroup, UpdateGroup)):
            body = {k: fields[k] for k in ("name", "description") if k in fields}
        elif isinstance(config, (CreateData, UpdateData)):
            body = {k: fields[k] for k in ("value", "lat", "lon", "ele") if k in fields}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"X-AIO-Key": credential.api_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                # Keep the provider's rejection text for the shared connect verdict.
                message = response.text[:2000] or "Adafruit IO request failed"
                return {"status": "error", "http_status": response.status_code,
                        "error": _redact(message, credential.api_key), "operation": operation}
            if method == "DELETE":
                return {"status": "success", "operation": operation,
                        "http_status": response.status_code, "deletion_acknowledged": True}
            data = response.json()
            listing = operation in {"list_feeds", "list_groups", "list_group_feeds", "list_data"}
            if listing:
                if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                    raise ValueError("Expected a list of records")
            elif not isinstance(data, dict):
                raise ValueError("Expected a record")
            records = data if listing else [data]
            if any("error" in row or "errors" in row for row in records):
                raise ValueError("Provider returned an error envelope")
            if operation == "get_current_user" and not data.get("username"):
                raise ValueError("Current-user response has no username")
            result = {"status": "success", "operation": operation, "data": _redact(data, credential.api_key)}
            if listing:
                result["count"] = len(data)
                result["page_only"] = True
            if operation == "list_data":
                result["next_end_time"] = response.headers.get("X-Pagination-Start") if len(data) >= config.limit else None
            return result
        except (ValueError, httpx.HTTPError, SSRFError):
            return {"status": "error", "operation": operation,
                    "error": "Adafruit IO did not return a confirmed response; inspect writes before retrying"}
