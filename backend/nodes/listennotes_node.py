"""Listen Notes v2: podcast discovery, metadata and API-admin playlists.

Contract: https://listen-api.listennotes.com/api/v2/openapi.yaml (2.0).
Each operation makes one request. Pagination values remain provider values;
no automatic pagination, downloads, retries or mutation readbacks are performed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://listen-api.listennotes.com/api/v2"


class ListenNotesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Listen Notes API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.listennotes.com/api/dashboard/",
            "x-credential-instructions": "Paste your Listen API key from the API dashboard. Team keys act as the API admin. Playlist reads show that admin's active memberships; writes require ownership. Plan limits apply to search and insights."
        })
    credential_type: Literal["listennotes_api_key"] = Field("listennotes_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_api_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_path_fields(cls, value, info):
        if info.field_name in {"id", "item_id"} and isinstance(value, str):
            if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
                raise ValueError("Use the resource ID, not a URL or path")
        if info.field_name == "name" and value is not None:
            value = value.strip()
            if not value or value.lower() == "rss":
                raise ValueError("Use a nonblank playlist name other than rss")
        return value


class SearchConfig(_Input):
    """Full-text search."""
    operation: Literal["search"] = Field("search", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description='Search term, e.g., person, place, topic... You can use double quotes to do verbatim match, e.g., "game of thrones". Otherwise, it\'s fuzzy search.')
    sort_by_date: Optional[Literal[0, 1]] = Field(None, ge=0, description='Sort by date or not? If 0, then sort by relevance. If 1, then sort by date.')
    type: Optional[Literal['episode', 'podcast', 'curated']] = Field(None, description='What type of contents do you want to search for?')
    offset: Optional[int] = Field(None, ge=0, description="Offset for search results, for pagination. You'll use **next_offset** from response for this parameter.")
    len_min: Optional[int] = Field(None, ge=0, description="Minimum audio length in minutes. Applicable only when **type** parameter is **episode** or **podcast**.\nIf **type** parameter is **episode**, it's for audio length of an episode.\nIf **type** parameter is **podcast**, it's for average audio length of all episodes in a podcast.")
    len_max: Optional[int] = Field(None, ge=0, description="Maximum audio length in minutes. Applicable only when **type** parameter is **episode** or **podcast**.\nIf **type** parameter is **episode**, it's for audio length of an episode.\nIf **type** parameter is **podcast**, it's for average audio length of all episodes in a podcast.")
    episode_count_min: Optional[int] = Field(None, ge=0, description='Minimum number of episodes. Applicable only when type parameter is **podcast**.')
    episode_count_max: Optional[int] = Field(None, ge=0, description='Maximum number of episodes. Applicable only when type parameter is **podcast**.')
    update_freq_min: Optional[int] = Field(None, ge=0, description='Minimum update frequency in hours (how frequently does a podcast release a new episode). For example, if you want to find "weekly" podcasts, then you can set **update_freq_min**=144 hours (or 6 days) and **update_freq_max**=192 hours (or 8 days). Applicable only when type parameter is **podcast**.')
    update_freq_max: Optional[int] = Field(None, ge=0, description='Maximum update frequency in hours (how frequently does a podcast release a new episode). For example, if you want to find "weekly" podcasts, then you can set **update_freq_min**=144 hours (or 6 days) and **update_freq_max**=192 hours (or 8 days). Applicable only when type parameter is **podcast**.')
    genre_ids: Optional[str] = Field(None, description='A comma-delimited string of a list of genre ids. If not specified, then all genres are included. You can find the id and the name of all genres from `GET /genres`. It works only when **type** is *episode* or *podcast*.')
    published_before: Optional[int] = Field(None, ge=0, description='Only show episodes/podcasts/curated lists published before this Epoch Unix timestamp (in milliseconds). \nIf **published_before** & **published_after** are used at the same time, **published_before** should be bigger than **published_after**.')
    published_after: Optional[int] = Field(None, ge=0, description='Only show episodes/podcasts/curated lists published after this Epoch Unix timestamp (in milliseconds). \nIf **published_before** & **published_after** are used at the same time, **published_before** should be bigger than **published_after**.')
    only_in: Optional[str] = Field(None, description='A comma-delimited string to search only in specific fields. Allowed values are title, description, author, and audio. If not specified, then search every fields.')
    language: Optional[str] = Field(None, description="Limit search results to a specific language. If not specified, it'll be any language. You can get a list of supported languages from `GET /languages`. It works only when **type** is *episode* or *podcast*.")
    region: Optional[str] = Field(None, description="Limit search results to a specific region (e.g., us, gb, in...). If not specified, it'll be any region. You can get the supported country codes from `GET /regions`. It works only when **type** is *episode* or *podcast*.")
    ocid: Optional[str] = Field(None, description='A comma-delimited string of podcast ids (up to 5 podcasts) - you can get a podcast id from the **podcast_id** field in response. This parameter is to limit search results from only a few specific podcasts. It works only when **type** is *episode*.')
    ncid: Optional[str] = Field(None, description='A comma-delimited string of podcast ids (up to 5 podcasts) - you can get a podcast id from the **podcast_id** field in response. This parameter is to exclude search results of a few specific podcasts. It works only when **type** is *episode*.')
    safe_mode: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to exclude podcasts/episodes with explicit language. 1 is yes and 0 is no. It works only when **type** is *episode* or *podcast*.')
    unique_podcasts: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to keep only one episode per podcast in search results. 1 is yes and 0 is no. It works only when **type** is *episode*.')
    interviews_only: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to keep only podcasts that have guest interviews in search results. 1 is yes and 0 is no. It works only when **type** is *podcast*. \nThis parameter is available only in the PRO/ENTERPRISE plan.')
    sponsored_only: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to keep only podcasts that have sponsors in search results. 1 is yes and 0 is no. It works only when **type** is *podcast*.\nThis parameter is available only in the PRO/ENTERPRISE plan.')
    page_size: Optional[int] = Field(None, ge=1, le=10, description='The maximum number of search results per page. A valid value should be an integer between 1 and 10 (inclusive).')


class TypeaheadConfig(_Input):
    """Typeahead search."""
    operation: Literal["typeahead"] = Field("typeahead", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description='Search term, e.g., person, place, topic... You can use double quotes to do verbatim match, e.g., "game of thrones". Otherwise, it\'s fuzzy search.')
    show_podcasts: Optional[Literal[0, 1]] = Field(None, ge=0, description="Autosuggest podcasts. This only searches podcast title and publisher and returns very limited info of 5 podcasts. 1 is yes, 0 is no. It's a bit slow to autosuggest podcasts, so we turn it off by default. If show_podcasts=1, you can also pass iTunes id (e.g., 474722933) to the q parameter to fetch podcast meta data.")
    show_genres: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to autosuggest genres. 1 is yes, 0 is no.')
    safe_mode: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to exclude podcasts/episodes with explicit language. 1 is yes and 0 is no. It works only when **show_podcasts** is *1*.')


class SearchEpisodeTitlesConfig(_Input):
    """Find individual episodes by searching for their titles."""
    operation: Literal["search_episode_titles"] = Field("search_episode_titles", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description='An episode\'s title, e.g., Jerusalem Demsas on The Dispossessed. You can use double quotes to do verbatim match, e.g., "Jerusalem Demsas on The Dispossessed". Otherwise, it\'s fuzzy search.')
    podcast_id: Optional[str] = Field(None, description="Refine search results by specifying a podcast through its unique ID.\nThe format of the podcast ID is governed by the podcast_id_type parameter. \nFor listennotes_id, the podcast ID will look like 'cda18f20f1be4ac7b3cce7d0eb168fff'. \nFor itunes_id, it will be a numerical value like '983795625'. \nFor spotify_id, expect a format like '0Z1234tGXD2hVhjFrrhJ7g'. \nFor rss, the podcast ID will be the RSS URL, e.g., 'https://cowenconvos.libsyn.com/rss'.")
    podcast_id_type: Optional[Literal['listennotes_id', 'itunes_id', 'spotify_id', 'rss']] = Field(None, description='The type of podcast id. Valid values are **listennotes_id**, **itunes_id**, **spotify_id**, and **rss**.\nNote: **itunes_id** is for Apple Podcasts.')


class GetTrendingSearchesConfig(_Input):
    """Fetch trending search terms."""
    operation: Literal["get_trending_searches"] = Field("get_trending_searches", json_schema_extra={"ui:hidden": True})


class GetRelatedSearchesConfig(_Input):
    """Fetch related search terms."""
    operation: Literal["get_related_searches"] = Field("get_related_searches", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description='Search term, e.g., person, place, topic...')


class SpellcheckConfig(_Input):
    """Spell check on a search term."""
    operation: Literal["spellcheck"] = Field("spellcheck", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description='Search term, e.g., person, place, topic...')


class GetBestPodcastsConfig(_Input):
    """Fetch a list of best podcasts by genre."""
    operation: Literal["get_best_podcasts"] = Field("get_best_podcasts", json_schema_extra={"ui:hidden": True})
    genre_id: Optional[str] = Field(None, description="You can get the id from `GET /genres`. If not specified, it'll be the overall best podcasts, which can be considered as a special genre.")
    page: Optional[int] = Field(None, ge=1, description='Page number of those podcasts in this genre.')
    region: Optional[str] = Field(None, description='Filter best podcasts by country/region.\nPlease note that podcasts that are "best" in a country/region may not be produced in that country/region.\nFor example, a podcast from the US may be very popular in Canada.\nYou can get the supported country codes (e.g., us, jp, gb...) from `GET /regions`.\nIf not specified, you\'ll get "best podcasts" in United States.')
    publisher_region: Optional[str] = Field(None, description='Filter best podcasts by the publisher\'s country/region.\nThis is to narrow down the results to include "best podcasts" produced in a specific country/region.\nYou can get the supported country codes (e.g., us, jp, gb...) from `GET /regions`.\nIf not specified, you\'ll get "best podcasts" produced in any country/region.\nIf you want to get a country/region\'s "best podcasts" that are also produced in that country/region,\nthen you need to specify both **region** and **publisher_region**,\ne.g., `region=jp` and `publisher_region=jp`.')
    language: Optional[str] = Field(None, description='Filter best podcasts by language.\nYou can get a list of supported languages (e.g., English, Chinese, Japanese...) from `GET /languages`.\nIf not specified, you\'ll get "best podcasts" in any language.')
    sort: Optional[Literal['recent_added_first', 'oldest_added_first', 'recent_published_first', 'oldest_published_first', 'listen_score']] = Field(None, description="How do you want to sort these podcasts?\nIf you'd like to sort by popularity, please use **listen_score**.")
    safe_mode: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to exclude podcasts with explicit language. 1 is yes, and 0 is no.')


class GetPodcastConfig(_Input):
    """Fetch detailed meta data and episodes for a podcast by id."""
    operation: Literal["get_podcast"] = Field("get_podcast", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Podcast id. You can get podcast id from using other endpoints, e.g., `GET /search`, `GET /best_podcasts`...')
    next_episode_pub_date: Optional[int] = Field(None, ge=0, description="For episodes pagination. It's the value of **next_episode_pub_date** from the response of last request. If not specified, just return latest 10 episodes or oldest 10 episodes, depending on the value of the **sort** parameter.\nIt is an Epoch Unix timestamp in milliseconds.\nDuring pagination with **next_episode_pub_date**, an empty **episodes** array in the response signals that no more episodes are available.")
    sort: Optional[Literal['recent_first', 'oldest_first']] = Field(None, description='How do you want to sort the episodes of this podcast?')


class GetEpisodeConfig(_Input):
    """Fetch detailed meta data for an episode by id."""
    operation: Literal["get_episode"] = Field("get_episode", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='id for a specific episode. You can get episode id from using other endpoints, e.g., `GET /search`...')
    show_transcript: Optional[int] = Field(None, ge=0, description="To include the transcript of this episode or not? If it is 1, then include the transcript in the **transcript** field. The default value is 0 - we don't include transcript by default, because 1) it would make the response data very big, thus slow response time; 2) less than 1% of episodes have transcripts. The transcript field is available only in the PRO/ENTERPRISE plan.")


class GetEpisodesConfig(_Input):
    """Batch fetch basic meta data for episodes."""
    operation: Literal["get_episodes"] = Field("get_episodes", json_schema_extra={"ui:hidden": True})
    ids: str = Field(..., min_length=1, description='Comma-separated list of episode ids.')


class GetPodcastsConfig(_Input):
    """Batch fetch basic meta data for podcasts."""
    operation: Literal["get_podcasts"] = Field("get_podcasts", json_schema_extra={"ui:hidden": True})
    ids: str = Field(..., min_length=1, description='Comma-separated list of podcast ids.')
    show_latest_episodes: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to fetch up to 15 latest episodes from these podcasts, sorted by pub_date. 1 is yes, and 0 is no.')
    next_episode_pub_date: Optional[int] = Field(None, ge=0, description="For latest episodes pagination. It's the value of **next_episode_pub_date** from the response of last request. If not specified, just return latest 15 episodes.\nIt is an Epoch Unix timestamp in milliseconds.")


class GetCuratedListConfig(_Input):
    """Fetch a curated list of podcasts by id."""
    operation: Literal["get_curated_list"] = Field("get_curated_list", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='id for a specific curated list of podcasts. You can get the id from the response of `GET /search?type=curated` or `GET /curated_podcasts`.')


class ListCuratedListsConfig(_Input):
    """Fetch curated lists of podcasts."""
    operation: Literal["list_curated_lists"] = Field("list_curated_lists", json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(None, ge=1, description='Page number of curated lists.')


class GetGenresConfig(_Input):
    """Fetch a list of podcast genres."""
    operation: Literal["get_genres"] = Field("get_genres", json_schema_extra={"ui:hidden": True})
    top_level_only: Optional[Literal[0, 1]] = Field(None, ge=0, description='Just show top level genres? If 1, yes, just show top level genres. If 0, no, show all genres.')


class GetPodcastRecommendationsConfig(_Input):
    """Fetch recommendations for a podcast."""
    operation: Literal["get_podcast_recommendations"] = Field("get_podcast_recommendations", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Podcast id.')
    safe_mode: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to exclude podcasts with explicit language. 1 is yes, and 0 is no.')


class GetEpisodeRecommendationsConfig(_Input):
    """Fetch recommendations for an episode."""
    operation: Literal["get_episode_recommendations"] = Field("get_episode_recommendations", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Episode id.')
    safe_mode: Optional[Literal[0, 1]] = Field(None, ge=0, description='Whether or not to exclude podcasts with explicit language. 1 is yes, and 0 is no.')


class SubmitPodcastConfig(_Input):
    """Submit a podcast to Listen Notes database."""
    operation: Literal["submit_podcast"] = Field("submit_podcast", json_schema_extra={"ui:hidden": True})
    rss: str = Field(..., min_length=1, description='A valid podcast rss url.')
    email: Optional[str] = Field(None, description="A valid email address. If **email** is specified, then we'll notify this email address once the podcast is accepted.")


class RefreshPodcastRssConfig(_Input):
    """Refresh RSS feed of a podcast."""
    operation: Literal["refresh_podcast_rss"] = Field("refresh_podcast_rss", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Podcast id. You can get podcast id from using other endpoints, e.g., `GET /search`, `GET /best_podcasts`...')


class ListPlaylistsConfig(_Input):
    """Fetch a list of your playlists."""
    operation: Literal["list_playlists"] = Field("list_playlists", json_schema_extra={"ui:hidden": True})
    sort: Optional[Literal['recent_added_first', 'oldest_added_first', 'name_a_to_z', 'name_z_to_a']] = Field(None, description='How do you want to sort playlists?')
    page: Optional[int] = Field(None, ge=1, description='Page number of playlists.')


class GetPlaylistConfig(_Input):
    """Fetch a playlist's info and items (i.e., episodes or podcasts)."""
    operation: Literal["get_playlist"] = Field("get_playlist", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Playlist id (always 11 characters, e.g., m1pe7z60bsw).\nYou can get the podcast id from the url of a playlist, e.g.,\nm1pe7z60bsw is the playlist id of listennotes.com/listen/podcasts-about-podcasting-m1pe7z60bsw')
    type: Optional[Literal['episode_list', 'podcast_list']] = Field(None, description="Select **episode_list** or **podcast_list** to fetch that view.\nIf omitted, use the playlist's saved default type. This query parameter does not change the saved default.")
    last_timestamp_ms: Optional[int] = Field(None, ge=0, description="For playlist items pagination.\nIt's the value of **last_timestamp_ms** from the response of last request.\nIf it's 0 or not specified, just return the latest or the oldest 20 items,\ndepending on the value of the **sort** parameter.\nIt is an Epoch Unix timestamp in milliseconds.")
    sort: Optional[Literal['recent_added_first', 'oldest_added_first', 'recent_published_first', 'oldest_published_first']] = Field(None, description='How do you want to sort playlist items?')


class CreatePlaylistConfig(_Input):
    """Create a playlist."""
    operation: Literal["create_playlist"] = Field("create_playlist", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=4096, description='Nonblank playlist name. Leading/trailing whitespace is trimmed; rss is reserved (case insensitive).')
    description: Optional[str] = Field(None, min_length=0, max_length=4096, description='Playlist description. An empty string clears it.')
    visibility: Optional[Literal['public', 'unlisted', 'private']] = Field(None, description='Who can view the playlist. Creation defaults to public.')
    type: Optional[Literal['episode_list', 'podcast_list']] = Field(None, description='The saved default view. Changing it preserves all episodes and podcasts in the playlist.')
    clear_description: bool = Field(False, description="Send an empty description to clear it.")


class UpdatePlaylistConfig(_Input):
    """Update playlist metadata."""
    operation: Literal["update_playlist"] = Field("update_playlist", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=11, max_length=11, description='11-character playlist ID returned by the playlist endpoints.')
    name: Optional[str] = Field(None, min_length=1, max_length=4096, description='Nonblank playlist name. Leading/trailing whitespace is trimmed; rss is reserved (case insensitive).')
    description: Optional[str] = Field(None, min_length=0, max_length=4096, description='Playlist description. An empty string clears it.')
    visibility: Optional[Literal['public', 'unlisted', 'private']] = Field(None, description='Who can view the playlist. Creation defaults to public.')
    type: Optional[Literal['episode_list', 'podcast_list']] = Field(None, description='The saved default view. Changing it preserves all episodes and podcasts in the playlist.')
    clear_description: bool = Field(False, description="Send an empty description to clear it.")

    @model_validator(mode="after")
    def required_changes(self):
        if all(getattr(self, k) is None for k in ("name", "description", "visibility", "type")) and not self.clear_description:
            raise ValueError("Provide at least one playlist field to update")
        return self


class AddPlaylistItemConfig(_Input):
    """Add an episode or podcast to a playlist."""
    operation: Literal["add_playlist_item"] = Field("add_playlist_item", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=11, max_length=11, description='11-character playlist ID returned by the playlist endpoints.')
    episode_id: Optional[str] = Field(None, pattern='^([0-9a-fA-F]{32})?$', description='Episode UUID. Supply this or podcast_id. An empty unused field is ignored.')
    podcast_id: Optional[str] = Field(None, pattern='^([0-9a-fA-F]{32})?$', description='Podcast UUID. Supply this or episode_id. An empty unused field is ignored.')
    notes: Optional[str] = Field(None, min_length=0, max_length=1024, description='Plain-text notes. An empty string clears existing notes.')
    clear_notes: bool = Field(False, description="Send empty notes to clear existing notes.")

    @model_validator(mode="after")
    def required_changes(self):
        if bool(self.episode_id) == bool(self.podcast_id):
            raise ValueError("Provide exactly one episode ID or podcast ID")
        return self


class UpdatePlaylistItemConfig(_Input):
    """Update notes for a playlist item."""
    operation: Literal["update_playlist_item"] = Field("update_playlist_item", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=11, max_length=11, description='11-character playlist ID returned by the playlist endpoints.')
    item_id: int = Field(..., ge=1, description='Integer playlist-item ID returned by GET /playlists/{id} or the add-item endpoint, not a podcast or episode UUID.')
    notes: Optional[str] = Field(None, min_length=0, max_length=1024, description='Plain-text notes. An empty string clears existing notes.')
    clear_notes: bool = Field(False, description="Send empty notes to clear existing notes.")

    @model_validator(mode="after")
    def required_changes(self):
        if self.notes is None and not self.clear_notes:
            raise ValueError("Provide notes or choose Clear notes")
        return self


class DeletePlaylistItemConfig(_Input):
    """Remove an item from a playlist."""
    operation: Literal["delete_playlist_item"] = Field("delete_playlist_item", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=11, max_length=11, description='11-character playlist ID returned by the playlist endpoints.')
    item_id: int = Field(..., ge=1, description='Integer playlist-item ID returned by GET /playlists/{id} or the add-item endpoint, not a podcast or episode UUID.')


ListenNotesConfig = Annotated[Union[
    SearchConfig,
    TypeaheadConfig,
    SearchEpisodeTitlesConfig,
    GetTrendingSearchesConfig,
    GetRelatedSearchesConfig,
    SpellcheckConfig,
    GetBestPodcastsConfig,
    GetPodcastConfig,
    GetEpisodeConfig,
    GetEpisodesConfig,
    GetPodcastsConfig,
    GetCuratedListConfig,
    ListCuratedListsConfig,
    GetGenresConfig,
    GetPodcastRecommendationsConfig,
    GetEpisodeRecommendationsConfig,
    SubmitPodcastConfig,
    RefreshPodcastRssConfig,
    ListPlaylistsConfig,
    GetPlaylistConfig,
    CreatePlaylistConfig,
    UpdatePlaylistConfig,
    AddPlaylistItemConfig,
    UpdatePlaylistItemConfig,
    DeletePlaylistItemConfig
], Field(discriminator="operation")]


RESPONSE_FIELDS = {
    'search': {'results': list},
    'typeahead': {'terms': list},
    'search_episode_titles': {'results': list},
    'get_trending_searches': {'terms': list},
    'get_related_searches': {'terms': list},
    'spellcheck': {'tokens': list},
    'get_best_podcasts': {'podcasts': list},
    'get_podcast': {'episodes': list, 'id': str},
    'get_episode': {'id': str},
    'get_episodes': {'episodes': list},
    'get_podcasts': {'podcasts': list},
    'get_curated_list': {'podcasts': list, 'id': str},
    'list_curated_lists': {'curated_lists': list},
    'get_genres': {'genres': list},
    'get_podcast_recommendations': {'recommendations': list},
    'get_episode_recommendations': {'recommendations': list},
    'submit_podcast': {'status': str},
    'refresh_podcast_rss': {'status': str},
    'list_playlists': {'playlists': list},
    'get_playlist': {'items': list, 'id': str},
    'create_playlist': {'id': str},
    'update_playlist': {'id': str},
    'add_playlist_item': {'id': int, 'data': dict},
    'update_playlist_item': {'id': int, 'data': dict},
    'delete_playlist_item': {'id': int, 'deleted': bool},
}


class ListenNotesNodeConfig(NodeConfig[ListenNotesConfig, ListenNotesAPIKeyCredential]):
    pass


ROUTES = {
    'search': ('GET', '/search', []),
    'typeahead': ('GET', '/typeahead', []),
    'search_episode_titles': ('GET', '/search_episode_titles', []),
    'get_trending_searches': ('GET', '/trending_searches', []),
    'get_related_searches': ('GET', '/related_searches', []),
    'spellcheck': ('GET', '/spellcheck', []),
    'get_best_podcasts': ('GET', '/best_podcasts', []),
    'get_podcast': ('GET', '/podcasts/{id}', []),
    'get_episode': ('GET', '/episodes/{id}', []),
    'get_episodes': ('POST', '/episodes', ['ids']),
    'get_podcasts': ('POST', '/podcasts', ['ids', 'show_latest_episodes', 'next_episode_pub_date']),
    'get_curated_list': ('GET', '/curated_podcasts/{id}', []),
    'list_curated_lists': ('GET', '/curated_podcasts', []),
    'get_genres': ('GET', '/genres', []),
    'get_podcast_recommendations': ('GET', '/podcasts/{id}/recommendations', []),
    'get_episode_recommendations': ('GET', '/episodes/{id}/recommendations', []),
    'submit_podcast': ('POST', '/podcasts/submit', ['rss', 'email']),
    'refresh_podcast_rss': ('POST', '/podcasts/{id}/rss', []),
    'list_playlists': ('GET', '/playlists', []),
    'get_playlist': ('GET', '/playlists/{id}', []),
    'create_playlist': ('POST', '/playlists', ['name', 'description', 'visibility', 'type']),
    'update_playlist': ('PUT', '/playlists/{id}', ['name', 'description', 'visibility', 'type']),
    'add_playlist_item': ('POST', '/playlists/{id}/items', ['episode_id', 'podcast_id', 'notes']),
    'update_playlist_item': ('PUT', '/playlists/{id}/items/{item_id}', ['notes']),
    'delete_playlist_item': ('DELETE', '/playlists/{id}/items/{item_id}', []),
}


class ListenNotesNode(WorkflowNode):
    integration_type = "automation-listennotes"
    connection_evidence = ConnectionEvidence(noun="playlists", operation="list_playlists", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ListenNotesNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Listen Notes API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation", "clear_description", "clear_notes"})
        for field in ("id", "item_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        body = {k: values.pop(k) for k in body_fields if k in values}
        if getattr(config, "clear_description", False):
            body["description"] = ""
        if getattr(config, "clear_notes", False):
            body["notes"] = ""
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"X-ListenAPI-Key": key, "Accept": "application/json"},
                    params=values or None, data=body if body_fields else None)
        except httpx.RequestError:
            raise ValueError("Listen Notes request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider refusal text for the connect seam, while removing the secret.
            message = response.text.replace(key, "[redacted]")[:500]
            output = {"status": "error", "success": False, "status_code": response.status_code,
                "error": message or "Listen Notes rejected the request"}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Listen Notes returned a non-JSON response; outcome is unverified") from None
            if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
                raise ValueError("Listen Notes returned an unexpected response; outcome is unverified")
            if any(type(payload.get(k)) is not kind for k, kind in RESPONSE_FIELDS[config.operation].items()):
                raise ValueError("Listen Notes returned an unexpected response; outcome is unverified")
            if config.operation == "delete_playlist_item" and payload["deleted"] is not True:
                raise ValueError("Listen Notes did not acknowledge item deletion")
            # Keep the provider envelope and its cursors, counts and acknowledgement semantics.
            # An accepted submission/refresh is not proof that indexing has completed.
            output = {"status": "success", "success": True, "status_code": response.status_code,
                "data": payload}
        output = self._redact(output, key)
        await self.emit(output)
        return output

    @staticmethod
    def _redact(value, secret):
        if isinstance(value, str):
            return value.replace(secret, "[redacted]")
        if isinstance(value, list):
            return [ListenNotesNode._redact(v, secret) for v in value]
        if isinstance(value, dict):
            return {k: ListenNotesNode._redact(v, secret) for k, v in value.items()}
        return value
