"""Read artist profiles and tour dates through Bandsintown PublicAPI 3.0.1.

The published API has three GET routes and no account-identity or mutation API.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://rest.bandsintown.com"


def _artist_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("Enter the canonical Bandsintown artist name")
    value = value.strip()
    if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter an artist name without control characters")
    return value


def _artist_segment(value):
    # PublicAPI documents double encoding for /, ? and *, and %27C for ".
    return (quote(_artist_name(value), safe="")
            .replace("%2F", "%252F").replace("%3F", "%253F")
            .replace("%2A", "%252A").replace("%22", "%27C"))


class BandsintownAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Bandsintown API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.artists.bandsintown.com/support/api-installation",
            "x-credential-instructions": "In Bandsintown for Artists, open your artist's Settings, then General, and copy the API Key. Paste it as the application ID and enter that artist's canonical name. Keys are artist-specific unless Bandsintown approves broader access. These reads verify reachability, not account identity or ownership.",
        },
    )
    credential_type: Literal["bandsintown_api_key"] = Field(
        "bandsintown_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="Application ID (API key)",
                        json_schema_extra={"ui:widget": "password"})
    artist_name: str = Field(..., min_length=1, max_length=500, title="Artist name",
                            description="Canonical name of the artist this key can access; also used for the connection check.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Bandsintown application ID")
        value = clean_secret(value, field_name="Application ID", key=True)
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the application ID without whitespace")
        return value

    @field_validator("artist_name", mode="before")
    @classmethod
    def artist(cls, value):
        return _artist_name(value)


class _ArtistInput(BaseModel):
    artist_name: str | None = Field(None, min_length=1, max_length=500,
                                  description="Artist name; leave empty to use the credential's artist.")

    @field_validator("artist_name", mode="before")
    @classmethod
    def artist(cls, value):
        return None if value is None else _artist_name(value)


class GetArtistConfig(_ArtistInput):
    """Get the artist's profile, follower count, images and upcoming-event count."""
    operation: Literal["get_artist"] = Field("get_artist", json_schema_extra={"ui:hidden": True})


class GetArtistByIDConfig(BaseModel):
    """Get an artist profile using its confirmed Bandsintown ID."""
    operation: Literal["get_artist_by_id"] = Field("get_artist_by_id", json_schema_extra={"ui:hidden": True})
    artist_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[0-9]+$",
                           description="Artist ID from the Bandsintown artist page URL.")


class ListArtistEventsConfig(_ArtistInput):
    """List tour dates with venues, ticket offers, lineups and descriptions."""
    operation: Literal["list_artist_events"] = Field("list_artist_events", json_schema_extra={"ui:hidden": True})
    date: str = Field("upcoming", title="Event date filter",
                      description='Use upcoming, past, all, or an inclusive YYYY-MM-DD,YYYY-MM-DD range.',
                      json_schema_extra={"examples": ["upcoming", "past", "all", "2015-05-05,2017-05-05"]})

    @field_validator("date")
    @classmethod
    def dates(cls, value):
        if value in {"upcoming", "past", "all"}:
            return value
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2},[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Use upcoming, past, all, or YYYY-MM-DD,YYYY-MM-DD")
        start, end = (date.fromisoformat(v) for v in value.split(","))
        if end < start:
            raise ValueError("The event date range must end on or after its start")
        return value


BandsintownConfig = Annotated[Union[GetArtistConfig, ListArtistEventsConfig, GetArtistByIDConfig], Field(discriminator="operation")]


class BandsintownFullConfig(NodeConfig[BandsintownConfig, BandsintownAPIKeyCredential]):
    model_config = ConfigDict(title="Bandsintown Node Configuration", hide_input_in_errors=True)


def _redact(value, app_id):
    if isinstance(value, str):
        for token in {app_id, quote(app_id, safe="")}:
            value = value.replace(token, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, app_id) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, app_id) for key, item in value.items()}
    return value


class BandsintownNode(WorkflowNode):
    integration_type = "automation-bandsintown"
    connection_evidence = ConnectionEvidence(
        noun="Bandsintown artist profile", operation="get_artist", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BandsintownFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Bandsintown API key")
        config = self.config.config
        params = {"app_id": credential.api_key}
        if isinstance(config, GetArtistByIDConfig):
            path = "/artists/id_" + config.artist_id
        else:
            path = "/artists/" + _artist_segment(config.artist_name or credential.artist_name)
            if isinstance(config, ListArtistEventsConfig):
                path += "/events"
                params["date"] = config.date
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE_URL + path, params=params, headers={"Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Bandsintown could not be reached; try again later") from None
        if response.status_code != 200:
            message = _redact(response.text, credential.api_key)[:1000]
            raise ValueError(f"Bandsintown (HTTP {response.status_code}): {message}")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Bandsintown returned an unreadable JSON response") from None
        if isinstance(body, dict) and ("error" in body or "errors" in body):
            raise ValueError("Bandsintown: " + str(_redact(body, credential.api_key)))
        if isinstance(config, ListArtistEventsConfig):
            if not isinstance(body, list) or any(not isinstance(item, dict) or "id" not in item for item in body):
                raise ValueError("Bandsintown returned an unexpected events response")
            output = {"status": "success", "events": body, "count": len(body)}
        else:
            if not isinstance(body, dict) or not isinstance(body.get("name"), str) or not body["name"]:
                raise ValueError("Bandsintown returned an unexpected artist response")
            output = {"status": "success", "data": body}
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output
