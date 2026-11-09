"""RAWG's published read-only video game catalog, using a manually supplied API key."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.rawg.io/api"


class RawgAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="RAWG API Key",
        json_schema_extra={
            "x-credential-url": "https://rawg.io/apidocs",
            "x-credential-instructions": "Paste your RAWG API key from the API documentation page. NoClick sends it as the key query parameter to api.rawg.io only. A public games read checks reachability, not account identity. Follow RAWG's usage limits and attribute RAWG with an active link wherever its data or images are displayed.",
        })
    credential_type: Literal["rawg_video_games_database_api_key"] = Field("rawg_video_games_database_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the RAWG API key without a URL or header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    page: int = Field(1, ge=1, description="One-based page number. Each execution returns one page; use next_page for the next execution.")
    page_size: int = Field(20, ge=1, le=40, description="Results per page, up to 40.")


class GameID(Input):
    id: str = Field(..., min_length=1, max_length=200, description="RAWG game ID or slug, for example 3498 or grand-theft-auto-v.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a game ID or slug without a path or URL")
        return value


class GamePage(Page):
    game_pk: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="RAWG game ID or slug.")


class ResourceID(Input):
    id: int = Field(..., ge=1, description="RAWG resource ID returned by its list operation.")


class ListGames(Page):
    """Get a list of games."""
    operation: Literal["list_games"] = Field("list_games", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description='Search query.')
    search_precise: StrictBool | None = Field(None, description='Disable fuzziness for the search query.')
    search_exact: StrictBool | None = Field(None, description='Mark the search query as exact.')
    parent_platforms: str | None = Field(None, description='Filter by parent platforms, for example: `1,2,3`.')
    platforms: str | None = Field(None, description='Filter by platforms, for example: `4,5`.')
    stores: str | None = Field(None, description='Filter by stores, for example: `5,6`.')
    developers: str | None = Field(None, description='Filter by developers, for example: `1612,18893` or `valve-software,feral-interactive`.')
    publishers: str | None = Field(None, description='Filter by publishers, for example: `354,20987` or `electronic-arts,microsoft-studios`.')
    genres: str | None = Field(None, description='Filter by genres, for example: `4,51` or `action,indie`.')
    tags: str | None = Field(None, description='Filter by tags, for example: `31,7` or `singleplayer,multiplayer`.')
    creators: str | None = Field(None, description='Filter by creators, for example: `78,28` or `cris-velasco,mike-morasky`.')
    dates: str | None = Field(None, description='Filter by a release date, for example: `2010-01-01,2018-12-31.1960-01-01,1969-12-31`.')
    updated: str | None = Field(None, description='Filter by an update date, for example: `2020-12-01,2020-12-31`.')
    platforms_count: int | None = Field(None, description='Filter by platforms count, for example: `1`.')
    metacritic: str | None = Field(None, description='Filter by a metacritic rating, for example: `80,100`.')
    exclude_collection: int | None = Field(None, description='Exclude games from a particular collection, for example: `123`.')
    exclude_additions: StrictBool | None = Field(None, description='Exclude additions.')
    exclude_parents: StrictBool | None = Field(None, description='Exclude games which have additions.')
    exclude_game_series: StrictBool | None = Field(None, description='Exclude games which included in a game series.')
    exclude_stores: str | None = Field(None, description='Exclude stores, for example: `5,6`.')
    ordering: str | None = Field(None, description='Available fields: `name`, `released`, `added`, `created`, `updated`, `rating`, `metacritic`. You can reverse the sort order adding a hyphen, for example: `-released`.')


class GetGame(GameID):
    """Get details of the game."""
    operation: Literal["get_game"] = Field("get_game", json_schema_extra={"ui:hidden": True})


class ListGameAdditions(GamePage):
    """Get a list of DLC's for the game, GOTY and other editions, companion apps, etc."""
    operation: Literal["list_game_additions"] = Field("list_game_additions", json_schema_extra={"ui:hidden": True})


class ListGameDevelopmentTeam(GamePage):
    """Get a list of individual creators that were part of the development team."""
    operation: Literal["list_game_development_team"] = Field("list_game_development_team", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class ListGameSeries(GamePage):
    """Get a list of games that are part of the same series."""
    operation: Literal["list_game_series"] = Field("list_game_series", json_schema_extra={"ui:hidden": True})


class ListGameParentGames(GamePage):
    """Get a list of parent games for DLC's and editions."""
    operation: Literal["list_game_parent_games"] = Field("list_game_parent_games", json_schema_extra={"ui:hidden": True})


class ListGameScreenshots(GamePage):
    """Get screenshots for the game."""
    operation: Literal["list_game_screenshots"] = Field("list_game_screenshots", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class ListGameStores(GamePage):
    """Get links to the stores that sell the game."""
    operation: Literal["list_game_stores"] = Field("list_game_stores", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class ListCreators(Page):
    """Get a list of game creators."""
    operation: Literal["list_creators"] = Field("list_creators", json_schema_extra={"ui:hidden": True})


class GetCreator(ResourceID):
    """Get details of the creator."""
    operation: Literal["get_creator"] = Field("get_creator", json_schema_extra={"ui:hidden": True})


class ListDevelopers(Page):
    """Get a list of game developers."""
    operation: Literal["list_developers"] = Field("list_developers", json_schema_extra={"ui:hidden": True})


class GetDeveloper(ResourceID):
    """Get details of the developer."""
    operation: Literal["get_developer"] = Field("get_developer", json_schema_extra={"ui:hidden": True})


class ListGenres(Page):
    """Get a list of video game genres."""
    operation: Literal["list_genres"] = Field("list_genres", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class GetGenre(ResourceID):
    """Get details of the genre."""
    operation: Literal["get_genre"] = Field("get_genre", json_schema_extra={"ui:hidden": True})


class ListPlatforms(Page):
    """Get a list of video game platforms."""
    operation: Literal["list_platforms"] = Field("list_platforms", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class GetPlatform(ResourceID):
    """Get details of the platform."""
    operation: Literal["get_platform"] = Field("get_platform", json_schema_extra={"ui:hidden": True})


class ListPublishers(Page):
    """Get a list of video game publishers."""
    operation: Literal["list_publishers"] = Field("list_publishers", json_schema_extra={"ui:hidden": True})


class GetPublisher(ResourceID):
    """Get details of the publisher."""
    operation: Literal["get_publisher"] = Field("get_publisher", json_schema_extra={"ui:hidden": True})


class ListStores(Page):
    """Get a list of video game storefronts."""
    operation: Literal["list_stores"] = Field("list_stores", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class GetStore(ResourceID):
    """Get details of the store."""
    operation: Literal["get_store"] = Field("get_store", json_schema_extra={"ui:hidden": True})


class ListTags(Page):
    """Get a list of tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class GetTag(ResourceID):
    """Get details of the tag."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})


class ListParentPlatforms(Page):
    """Get a list of parent platforms."""
    operation: Literal["list_parent_platforms"] = Field("list_parent_platforms", json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, description='Which field to use when ordering the results.')


class ListCreatorRoles(Page):
    """Get a list of creator positions (jobs)."""
    operation: Literal["list_creator_roles"] = Field("list_creator_roles", json_schema_extra={"ui:hidden": True})


RawgConfig = Annotated[Union[ListGames, GetGame, ListGameAdditions, ListGameDevelopmentTeam, ListGameSeries, ListGameParentGames, ListGameScreenshots, ListGameStores, ListCreators, GetCreator, ListDevelopers, GetDeveloper, ListGenres, GetGenre, ListPlatforms, GetPlatform, ListPublishers, GetPublisher, ListStores, GetStore, ListTags, GetTag, ListParentPlatforms, ListCreatorRoles], Field(discriminator="operation")]


class RawgFullConfig(NodeConfig[RawgConfig, RawgAPIKeyCredential]):
    pass


ROUTES = {
    "list_games": "/games",
    "get_game": "/games/{id}",
    "list_game_additions": "/games/{game_pk}/additions",
    "list_game_development_team": "/games/{game_pk}/development-team",
    "list_game_series": "/games/{game_pk}/game-series",
    "list_game_parent_games": "/games/{game_pk}/parent-games",
    "list_game_screenshots": "/games/{game_pk}/screenshots",
    "list_game_stores": "/games/{game_pk}/stores",
    "list_creators": "/creators",
    "get_creator": "/creators/{id}",
    "list_developers": "/developers",
    "get_developer": "/developers/{id}",
    "list_genres": "/genres",
    "get_genre": "/genres/{id}",
    "list_platforms": "/platforms",
    "get_platform": "/platforms/{id}",
    "list_publishers": "/publishers",
    "get_publisher": "/publishers/{id}",
    "list_stores": "/stores",
    "get_store": "/stores/{id}",
    "list_tags": "/tags",
    "get_tag": "/tags/{id}",
    "list_parent_platforms": "/platforms/lists/parents",
    "list_creator_roles": "/creator-roles"
}


def redact(value, token):
    if isinstance(value, dict):
        return {key: redact(item, token) for key, item in value.items() if key.lower() not in {"key", "api_key"}}
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]").replace(quote(token, safe=""), "[redacted]")
    return value


class RawgVideoGamesDatabaseNode(WorkflowNode):
    integration_type = "automation-rawg-video-games-database"
    connection_evidence = ConnectionEvidence(operation="list_games", noun="RAWG games", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return RawgFullConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type", "rawg_video_games_database_api_key") != "rawg_video_games_database_api_key"):
            raise ValueError("Attach a RAWG API key credential")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Supply a RAWG API key credential")
        config = self.config.config
        token = self.config.credentials.api_key
        path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("id", "game_pk"):
            if name in values:
                path = path.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
        params = {key: "true" if value is True else "false" if value is False else value for key, value in values.items()}
        params["key"] = token
        try:
            async with guarded_async_client(timeout=30.0, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", BASE + path, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("RAWG request could not be completed") from None
        try:
            data = redact(response.json(), token)
        except ValueError:
            raise ValueError("RAWG returned a non-JSON response") from None
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code, "error": data}
        if not isinstance(data, dict):
            raise ValueError("RAWG returned an unexpected response shape")
        if data.get("error") or data.get("detail"):
            return {"status": "error", "http_status": response.status_code, "error": data}
        output = {"status": "success", "operation": config.operation, "data": data}
        if isinstance(config, Page):
            if type(data.get("count")) is not int or data["count"] < 0 or not isinstance(data.get("results"), list):
                raise ValueError("RAWG returned an incomplete catalog page")
            if any(not isinstance(item, dict) for item in data["results"]):
                raise ValueError("RAWG returned an invalid catalog item")
            if data.get("next") is not None and not isinstance(data["next"], str):
                raise ValueError("RAWG returned an invalid next page")
            # Never return key-bearing pagination URLs or follow provider-supplied URLs.
            has_more = bool(data.get("next"))
            output.update(page=config.page, next_page=config.page + 1 if has_more else None, has_more=has_more)
            data.pop("next", None)
            data.pop("previous", None)
        await self.emit(output)
        return output
