"""Spotify playlists, library, catalog and playback, plus played-track polling.

Contract: https://developer.spotify.com/reference/web-api/open-api-schema.yaml
Playback controls require Spotify Premium and an available Spotify device.
The poll watches the latest 50 plays; poll often enough to retain that window.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.spotify_oauth import refresh_access_token
from nodes.scopes.spotify import SPOTIFY_SCOPES
from nodes.spotify_operations import OPERATIONS

BASE_URL = "https://api.spotify.com/v1"


class SpotifyOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Spotify OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "spotify",
        "x-oauth-scopes": SPOTIFY_SCOPES.declared_scopes(),
        "x-credential-url": "https://developer.spotify.com/dashboard",
        "x-credential-instructions": "Connect your Spotify account. Playback controls require Spotify Premium and an available device.",
    })
    credential_type: Literal["spotify_oauth"] = Field("spotify_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without whitespace or a Bearer prefix")
        return value


def _uris(value: str, *, allowed: set[str], maximum: int) -> list[str]:
    items = [item.strip() for item in value.split(",")]
    if not 1 <= len(items) <= maximum:
        raise ValueError(f"Provide between 1 and {maximum} comma-separated Spotify URIs")
    for item in items:
        match = re.fullmatch(r"spotify:([a-z]+):([A-Za-z0-9]+)", item)
        if not match or match[1] not in allowed:
            raise ValueError("Use Spotify URIs of the supported content types")
    return items


class _OperationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def validate_inputs(self):
        values = self.model_dump(exclude_none=True)
        name = values["operation"]
        for key in ("track_id", "artist_id", "playlist_id", "device_id"):
            value = values.get(key)
            if value is not None and not re.fullmatch(r"[A-Za-z0-9]{1,128}", value):
                raise ValueError(f"{key} must be a Spotify ID, without a URL or URI")
        if "type" in values:
            kinds = values["type"].split(",")
            if not kinds or any(k not in {"album", "artist", "playlist", "track", "show", "episode", "audiobook"} for k in kinds):
                raise ValueError("Choose comma-separated catalog types")
        if "uris" in values:
            if name in {"save_library_items", "remove_library_items", "check_library_items"}:
                allowed = {"track", "album", "episode", "show", "audiobook", "user", "playlist"}
                if name == "check_library_items":
                    allowed.add("artist")
                _uris(values["uris"], allowed=allowed, maximum=40)
            else:
                _uris(values["uris"], allowed={"track"} if name == "start_playback" else {"track", "episode"}, maximum=100)
        if "uri" in values:
            _uris(values["uri"], allowed={"track", "episode"}, maximum=1)
        if values.get("context_uri"):
            _uris(values["context_uri"], allowed={"album", "artist", "playlist"}, maximum=1)
            if values.get("uris"):
                raise ValueError("Choose either a context URI or track URIs")
        if values.get("after") is not None and values.get("before") is not None:
            raise ValueError("Choose either after or before, not both")
        if name in {"create_playlist", "update_playlist"}:
            if values.get("collaborative") and values.get("public") is not False:
                raise ValueError("A collaborative playlist must explicitly be private (public=false)")
            if name == "update_playlist" and not any(k in values for k in ("name", "description", "public", "collaborative")):
                raise ValueError("Provide at least one playlist detail to update")
        return self


_TITLES = {"q": "Search Query", "type": "Item Types", "uris": "Spotify URIs", "uri": "Spotify URI"}
_INTEGER_FIELDS = {"limit", "offset", "position", "position_ms", "after", "before"}
_BOOLEAN_FIELDS = {"public", "collaborative"}


def _field(name: str, required: bool, operation: str):
    kind = int if name in _INTEGER_FIELDS else bool if name in _BOOLEAN_FIELDS else str
    options: dict[str, Any] = {"title": _TITLES.get(name, name.replace("_", " ").title())}
    if kind is int:
        options["ge"] = 1 if name == "limit" else 0
        if name == "limit":
            options["le"] = 10 if operation == "search" else 50
        if name == "offset":
            options["le"] = 1000 if operation == "search" else 100000
    if kind is str:
        options["max_length"] = 20000 if name == "uris" else 4096
        if required or name in {"name", "q"}:
            options["min_length"] = 1
        if name == "market":
            options["pattern"] = "^[A-Z]{2}$"
        if name == "uris":
            options["description"] = "Comma-separated Spotify URIs. Up to 40 for library actions; up to 100 for playlist actions."
    if name == "playlist_id":
        options["json_schema_extra"] = {"x-dynamic-options": {
            "field_name": "playlist_id", "searchable": True, "allow_custom": True,
            "placeholder": "Select a playlist", "custom_placeholder": "Or paste a Spotify playlist ID",
        }}
    default = ... if required else 20 if name == "limit" and operation != "search" else 5 if name == "limit" else 0 if name == "offset" else None
    return (kind if required else Optional[kind], Field(default, **options))


CONFIG_MODELS = {}
for _name, _spec in OPERATIONS.items():
    _fields = {"operation": (Literal[_name], Field(_name, title=_name.replace("_", " ").title(), json_schema_extra={
        "const": _name, "ui:hidden": True, "x-category": _spec.category,
        "x-display-name": _name.replace("_", " ").title(), "x-is-trigger": False,
    }))}
    for _key in dict.fromkeys((*_spec.required, *_spec.query, *_spec.body)):
        _fields[_key] = _field(_key, _key in _spec.required, _name)
    CONFIG_MODELS[_name] = create_model("Spotify" + _name.title().replace("_", "") + "Config", __base__=_OperationConfig, **_fields)


class SpotifyOnTrackPlayedConfig(PollTriggerConfigBase):
    """Watch the latest 50 plays. Frequent polling avoids gaps during heavy use."""
    operation: Literal["on_track_played"] = Field("on_track_played", title="On Track Played", json_schema_extra={
        "const": "on_track_played", "ui:hidden": True, "x-category": "Triggers",
        "x-display-name": "On Track Played", "x-is-trigger": True,
    })


SpotifyConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (SpotifyOnTrackPlayedConfig,)], Field(discriminator="operation")]


class SpotifyNodeConfig(NodeConfig[SpotifyConfig, SpotifyOAuthCredential]):
    pass


class SpotifyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-spotify"
    scope_registry = SPOTIFY_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_playlists", noun="playlists", label_keys=("name", "id"),
        identity_operation="get_profile", identity_keys=("display_name", "account_id", "id"),
    )
    edit_examples = ["Add this song to my Spotify playlist", "Create a private playlist",
                     "Pause Spotify playback", "When I play a track, log it"]

    @classmethod
    def get_config_model(cls):
        return SpotifyNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="spotify")

    async def _access_token(self):
        credential = self.config.credentials
        if credential.refresh_token:
            data = credential.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=data, refresh=refresh_access_token, provider="spotify", caller_path="execute")
            for key in ("access_token", "refresh_token", "expires_at"):
                if data.get(key) is not None:
                    setattr(credential, key, data[key])
            return token
        return credential.access_token

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        # Fixed provider origin; never follow a response's next URL or redirects with the token.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, json=body)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error", {})
                message = error.get("message") if isinstance(error, dict) else error
            except (ValueError, AttributeError):
                message = None
            detail = str(message or "request failed").replace(token, "[redacted]")[:500]
            raise ValueError(f"Spotify API {response.status_code}: {detail}")
        return response.json() if response.content else None

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "playlist_id":
            return {"options": []}
        token = SpotifyOAuthCredential.model_validate(credential_data).access_token
        try:
            offset = int(page_token) if page_token is not None else 0
        except (ValueError, TypeError):
            raise ValueError("Invalid Spotify playlist offset") from None
        if not 0 <= offset <= 100000:
            raise ValueError("Spotify playlist offset must be between 0 and 100000")
        data = await cls._request(token, "GET", "/me/playlists", params={"limit": 50, "offset": offset})
        rows = data["items"]
        options = [{"value": row["id"], "label": row.get("name") or row["id"]}
                   for row in rows if row and row.get("id")
                   and (not search or search.casefold() in (row.get("name") or "").casefold())]
        return {"options": options, "next_page_token": str(offset + len(rows)) if data.get("next") and rows else None}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("play_count")) if config.get("operation") == "on_track_played" else True

    @classmethod
    def resolve_agent_event(cls, output):
        plays = output.get("plays") if isinstance(output, dict) else None
        if not isinstance(plays, list):
            return super().resolve_agent_event(output)
        if not plays:
            return None
        lines = []
        for play in plays[:10]:
            track = play["track"]
            artists = ", ".join(artist["name"] for artist in track["artists"])
            lines.append(f"- You played {track['name']} by {artists} at {play['played_at']} on Spotify "
                         f"(track {track['id']}; {track['uri']}).")
        return {"text": "Spotify listening activity:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Spotify account")
        config = self.config.config
        name = config.operation
        self.scope_registry.require(name)
        token = await self._access_token()
        if name == "on_track_played":
            data = await self._request(token, "GET", "/me/player/recently-played", params={"limit": 50})
            # A repeat of the same track at another time is a separate play.
            plays = await self._filter_unseen(data["items"], lambda item: item["track"]["uri"] + "@" + item["played_at"])
            return {"plays": plays, "play_count": len(plays), "window_limit": 50}
        spec = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values}
        if "uris" in body:
            body["uris"] = [uri.strip() for uri in body["uris"].split(",")]
        if name == "remove_playlist_items":
            body["items"] = [{"uri": uri} for uri in body.pop("uris")]
        data = await self._request(token, spec.method, path, params=params or None, body=body or None)
        # Preserve Spotify's pagination, snapshots and nullable playback response.
        return {"status": "success", "operation": name, "data": data}
