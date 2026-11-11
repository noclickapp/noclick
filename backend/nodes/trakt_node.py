"""Trakt account automation against the published API v2 contract.

Lists return a single explicit page. Polls inspect at most 2,000 recent items;
choose a start_at boundary for busy histories. Writes return Trakt's acknowledgement,
including not_found, rather than claiming every submitted item changed.
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.trakt import TRAKT_SCOPES
from nodes.trakt_operations import TRAKT_OPERATIONS
from utils.ssrf import guarded_async_client


class TraktOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Trakt OAuth",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "trakt",
            "x-oauth-scopes": TRAKT_SCOPES.declared_scopes(),
            "x-credential-url": "https://app.trakt.tv/settings/apps",
            "x-credential-instructions": "Sign in to Trakt. The instance administrator registers an app and configures TRAKT_CLIENT_ID and TRAKT_REDIRECT_URI. Trakt uses PKCE and rotating refresh tokens. To connect by hand, paste an existing user access token and its application's client ID. Without a refresh token, reconnect when the access token expires.",
        },
    )
    credential_type: Literal["trakt_oauth"] = Field(
        "trakt_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        repr=False,
        title="Access token",
        json_schema_extra={"ui:widget": "password"},
    )
    client_id: str | None = Field(
        None,
        title="Client ID",
        description="Application client ID for a pasted token; defaults to the instance's TRAKT_CLIENT_ID.",
    )
    refresh_token: str | None = Field(
        None,
        repr=False,
        title="Refresh token",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: str | None = Field(
        None,
        title="Token expiry",
        description="ISO 8601 expiry from OAuth, when available.",
    )
    scope: str | None = None

    @field_validator("access_token", "refresh_token", "client_id", mode="before")
    @classmethod
    def clean(cls, value):
        if value is None:
            return None
        value = clean_secret(value, field_name="Trakt token or client ID")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the value without headers or whitespace")
        return value


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Fields):
    page: int = Field(
        1,
        ge=1,
        le=1000000,
        description="Explicit page number; lists return only this page.",
    )
    limit: int = Field(100, ge=1, le=100, description="Results per page.")


class History(Page):
    user_id: str = Field(
        "me",
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        description="Trakt username, user slug or me for the signed-in account.",
    )
    start_at: str | None = Field(
        None,
        description="Inclusive UTC ISO 8601 watched timestamp.",
        json_schema_extra={"format": "date-time"},
    )
    end_at: str | None = Field(
        None,
        description="Exclusive UTC ISO 8601 watched timestamp.",
        json_schema_extra={"format": "date-time"},
    )

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.utcoffset() is None:
                raise ValueError("Include a UTC offset in timestamps")
        return value


class Watchlist(Page):
    type: Literal["movies", "shows", "seasons", "episodes"] = "movies"
    sort_by: Literal[
        "rank", "added", "title", "released", "runtime", "popularity", "random"
    ] = "added"
    sort_how: Literal["asc", "desc"] = "desc"


class Item(Fields):
    media_type: Literal["movies", "shows", "seasons", "episodes"] = Field(
        "movies",
        description="A show/season history or collection write can affect its episodes, as Trakt documents.",
    )
    item_id: int = Field(
        ...,
        gt=0,
        description="Trakt numeric ID, not the history entry or list item ID.",
    )


class TimedItem(Item):
    watched_at: str | None = Field(
        None,
        description="UTC ISO 8601 watched time; omit to use Trakt's current time.",
        json_schema_extra={"format": "date-time"},
    )
    _timestamp = field_validator("watched_at")(History.timestamp.__func__)


class RatingItem(Item):
    rating: int = Field(..., ge=1, le=10, description="Rating from 1 to 10.")


class CollectionPage(Page):
    type: Literal["movies", "shows"] = "movies"


class UserPage(Page):
    user_id: str = Field("me", max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class CreateList(Fields):
    user_id: str = Field("me", max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=10000)
    privacy: Literal["private", "link", "friends", "public"] = Field(
        "private", description="Public and link lists can be read by other people."
    )


class ListItem(Item):
    user_id: str = Field("me", max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    list_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        description="Personal list slug or Trakt list ID.",
    )


class MediaID(Fields):
    id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        description="Trakt ID or slug.",
    )


class Search(Page):
    type: Literal["movie", "show", "episode", "person", "list"] = "movie"
    query: str = Field(..., min_length=1, max_length=500)


class HistoryPoll(PollTriggerConfigBase):
    user_id: str = Field("me", max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    start_at: str | None = Field(
        None,
        description="Optional UTC ISO 8601 boundary; polls at most 2,000 entries and baselines existing watches on activation.",
        json_schema_extra={"format": "date-time"},
    )
    _timestamp = field_validator("start_at")(History.timestamp.__func__)


class WatchlistPoll(PollTriggerConfigBase):
    type: Literal["movies", "shows", "seasons", "episodes"] = "movies"


BASES = {
    "search": Search,
    "get_movie": MediaID,
    "get_show": MediaID,
    "list_trending_movies": Page,
    "list_movie_history": History,
    "list_episode_history": History,
    "list_watchlist": Watchlist,
    "list_collection": CollectionPage,
    "list_lists": UserPage,
    "create_list": CreateList,
    "add_list_item": ListItem,
    "remove_list_item": ListItem,
    "add_to_history": TimedItem,
    "rate_item": RatingItem,
    "on_movie_watched": HistoryPoll,
    "on_episode_watched": HistoryPoll,
    "on_watchlist_item_added": WatchlistPoll,
}
ITEM_WRITES = {
    "add_to_watchlist",
    "remove_from_watchlist",
    "add_to_history",
    "remove_from_history",
    "rate_item",
    "remove_rating",
    "add_to_collection",
    "remove_from_collection",
    "add_list_item",
    "remove_list_item",
}
CONFIGS = {}
for _name in TRAKT_OPERATIONS:
    _trigger = _name.startswith("on_")
    _base = BASES.get(_name, Item if _name in ITEM_WRITES else Fields)
    _label = _name.replace("_", " ").title()
    _model = create_model(
        "Trakt" + _label.replace(" ", "") + "Config",
        __base__=_base,
        __module__=__name__,
        operation=(
            Literal[_name],
            Field(
                _name,
                title=_label,
                json_schema_extra={
                    "const": _name,
                    "ui:hidden": True,
                    "x-display-name": _label,
                    "x-is-trigger": _trigger,
                    "x-category": "Triggers" if _trigger else "Trakt",
                },
            ),
        ),
    )
    CONFIGS[_name] = _model
    globals()[_model.__name__] = _model

TraktConfig = Annotated[
    Union[tuple(CONFIGS.values())], Field(discriminator="operation")
]


class TraktNodeConfig(NodeConfig[TraktConfig, TraktOAuthCredential]):
    pass


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.access_token, credential.refresh_token):
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, credential) for key, item in value.items()}
    return value


class TraktNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-trakt"
    scope_registry = TRAKT_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="Trakt account",
        identity_operation="get_settings",
        identity_keys=("username", "name", "email"),
    )

    @classmethod
    def get_config_model(cls):
        return TraktNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.trakt_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="trakt",
        )

    async def _request(self, credential, method, path, params=None, body=None):
        client_id = credential.client_id or os.environ.get("TRAKT_CLIENT_ID")
        if not client_id:
            raise ValueError(
                "Enter the Trakt application's client ID or configure TRAKT_CLIENT_ID"
            )
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                "https://api.trakt.tv" + path,
                headers={
                    "Authorization": "Bearer " + credential.access_token,
                    "trakt-api-key": client_id,
                    "trakt-api-version": "2",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "NoClick/1.0",
                },
                params=params,
                **({"json": body} if body is not None else {}),
            )
        if not 200 <= response.status_code < 300:
            message = _redact(response.text, credential)[:2000]
            raise ValueError(f"Trakt HTTP {response.status_code}: {message}")
        if len(response.content) > 8 * 1024 * 1024:
            raise ValueError("Trakt response exceeds 8 MiB")
        result = response.json() if response.content else None
        if (
            response.content
            and "application/json"
            not in response.headers.get("content-type", "").lower()
        ):
            raise ValueError("Trakt returned a non-JSON response")
        if not isinstance(result, (dict, list, type(None))):
            raise ValueError("Trakt returned an unexpected response")
        pages = response.headers.get("X-Pagination-Page-Count")
        page = int(params.get("page", 1)) if params else 1
        next_page = page + 1 if pages is not None and page < int(pages) else None
        return {
            "data": result,
            "http_status": response.status_code,
            "next_page": next_page,
            "pagination_page_count": int(pages) if pages is not None else None,
        }

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Trakt account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.trakt_oauth import refresh_access_token

        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=data,
            refresh=refresh_access_token,
            provider="trakt",
            caller_path="execute",
        )
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in data:
                setattr(credential, key, data[key])
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        spec = TRAKT_OPERATIONS[name]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        trigger = name.startswith("on_")
        if trigger:
            values.update(page=1, limit=100)
            if name == "on_watchlist_item_added":
                values.update(sort_by="added", sort_how="desc")
        path = spec["path"]
        for key, value in values.items():
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in spec["query"] if key in values}
        body = None
        if name in ITEM_WRITES:
            item = {"ids": {"trakt": op.item_id}}
            if name == "rate_item":
                item["rating"] = op.rating
            if name == "add_to_history" and op.watched_at is not None:
                item["watched_at"] = op.watched_at
            body = {op.media_type: [item]}
        elif name == "create_list":
            body = {
                key: values[key]
                for key in ("name", "description", "privacy")
                if key in values
            }
        if not trigger:
            result = await self._request(credential, spec["method"], path, params, body)
            expected = list if name.startswith("list_") or name == "search" else dict
            if not isinstance(result["data"], expected):
                raise ValueError("Trakt returned an unexpected operation response")
            return _redact(result, credential)
        rows = []
        for page in range(1, 21):
            params["page"] = page
            result = await self._request(credential, "GET", path, params)
            batch = result["data"]
            if not isinstance(batch, list):
                raise ValueError("Trakt poll expected an array")
            # Both history entries and watchlist items document a distinct id.
            if any(
                not isinstance(row, dict) or not isinstance(row.get("id"), int)
                for row in batch
            ):
                raise ValueError("Trakt poll response has no numeric entry ID")
            rows.extend(batch)
            if result["pagination_page_count"] is not None:
                if result["next_page"] is None:
                    break
            elif len(batch) < 100:
                break
        else:
            raise ValueError(
                "Trakt poll exceeds 2,000 entries; narrow the history start_at boundary"
            )
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError(
                "Trakt repeated entry IDs across poll pages; retry the next poll"
            )
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
        return _redact(
            {
                "events": fresh,
                "event_count": len(fresh),
                "event_type": name,
                "account": values.get("user_id", "signed-in account"),
            },
            credential,
        )

    @classmethod
    def resolve_agent_event(cls, output):
        events = output.get("events") if isinstance(output, dict) else None
        if not isinstance(events, list):
            return super().resolve_agent_event(output)
        # Preserve provider entry ids, timestamps and media content for an agent to act on.
        return {
            "text": f"Trakt account {output.get('account', 'signed-in account')}: {len(events)} new entries ({output.get('event_type')}).\n"
            + json.dumps(events, ensure_ascii=False),
            "events": events,
            "conversation_key": "trakt:" + str(output.get("event_type")),
        }
