"""SoundCloud account, playlists, track metadata and social automation.

Each operation calls exactly one endpoint in the pinned public API 1.0.0.
Lists return one page (with the provider's next_href when supplied), never
claim a complete collection. Writes return acknowledgements, not readback
verification. Uploading audio and downloading/streaming media are excluded.
Docs: https://developers.soundcloud.com/docs/api/guide
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.soundcloud import SOUNDCLOUD_SCOPES
from nodes.soundcloud_operations import SOUNDCLOUD_OPERATIONS
from utils.ssrf import guarded_async_client

ID = Annotated[int, Field(gt=0)]


class SoundcloudOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="SoundCloud OAuth",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "soundcloud",
            "x-oauth-scopes": SOUNDCLOUD_SCOPES.declared_scopes(),
            "x-credential-url": "https://soundcloud.com/you/apps",
            "x-credential-instructions": "Connect your SoundCloud account. The instance administrator must register a SoundCloud app and configure its client ID, client secret and callback URL. SoundCloud requires PKCE; access tokens expire after about one hour and refresh tokens are single-use. You can also paste an existing user access token; reconnect when it expires if no refresh token is supplied.",
        },
    )
    credential_type: Literal["soundcloud_oauth"] = Field(
        "soundcloud_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        min_length=1,
        repr=False,
        title="Access token",
        json_schema_extra={"ui:widget": "password"},
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
        description="ISO 8601 expiry, when supplied by the OAuth flow.",
    )
    scope: str | None = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return None
        value = clean_secret(value, field_name="Token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste a token without a header or whitespace")
        return value


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Fields):
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="Maximum items in this single page, not a complete collection.",
    )


class LinkedPage(Page):
    linked_partitioning: Literal[True] = Field(
        True, json_schema_extra={"ui:hidden": True}
    )


class OffsetPage(Page):
    offset: int = Field(
        0,
        ge=0,
        description="First result offset; increase explicitly for the next page.",
    )


class UserID(Fields):
    user_id: ID


class TrackID(Fields):
    track_id: ID


class PlaylistID(Fields):
    playlist_id: ID


class PlaylistContent(Fields):
    title: str = Field(..., min_length=1)
    description: str | None = None
    sharing: Literal["public", "private"] | None = None
    track_ids: list[ID] | None = Field(
        None,
        max_length=500,
        description="Ordered track IDs. On update this replaces the playlist tracks; an empty list clears them. Omit to leave existing tracks unchanged.",
    )


class UpdatePlaylistFields(PlaylistContent, PlaylistID):
    pass


class TrackContent(TrackID):
    title: str = Field(..., min_length=1)
    description: str | None = None
    genre: str | None = None
    tag_list: str | None = Field(
        None, description="Space-separated tags; quote multiword tags in double quotes."
    )
    sharing: Literal["public", "private"] | None = None
    downloadable: bool | None = None
    streamable: bool | None = None
    commentable: bool | None = None


class GetCurrentUserConfig(Fields):
    operation: Literal["get_current_user"] = Field(
        "get_current_user", json_schema_extra={"ui:hidden": True}
    )


class ListMyTracksConfig(LinkedPage):
    operation: Literal["list_my_tracks"] = Field(
        "list_my_tracks", json_schema_extra={"ui:hidden": True}
    )


class ListMyPlaylistsConfig(Page):
    operation: Literal["list_my_playlists"] = Field(
        "list_my_playlists", json_schema_extra={"ui:hidden": True}
    )


class ListMyLikedTracksConfig(LinkedPage):
    operation: Literal["list_my_liked_tracks"] = Field(
        "list_my_liked_tracks", json_schema_extra={"ui:hidden": True}
    )


class ListMyFollowersConfig(Page):
    operation: Literal["list_my_followers"] = Field(
        "list_my_followers", json_schema_extra={"ui:hidden": True}
    )


class ListMyFollowingsConfig(OffsetPage):
    operation: Literal["list_my_followings"] = Field(
        "list_my_followings", json_schema_extra={"ui:hidden": True}
    )


class ListFollowingTracksConfig(OffsetPage):
    operation: Literal["list_following_tracks"] = Field(
        "list_following_tracks", json_schema_extra={"ui:hidden": True}
    )


class FollowUserConfig(UserID):
    operation: Literal["follow_user"] = Field(
        "follow_user", json_schema_extra={"ui:hidden": True}
    )


class UnfollowUserConfig(UserID):
    operation: Literal["unfollow_user"] = Field(
        "unfollow_user", json_schema_extra={"ui:hidden": True}
    )


class CreatePlaylistConfig(PlaylistContent):
    operation: Literal["create_playlist"] = Field(
        "create_playlist", json_schema_extra={"ui:hidden": True}
    )


class UpdatePlaylistConfig(UpdatePlaylistFields):
    operation: Literal["update_playlist"] = Field(
        "update_playlist", json_schema_extra={"ui:hidden": True}
    )


class UpdateTrackConfig(TrackContent):
    operation: Literal["update_track"] = Field(
        "update_track", json_schema_extra={"ui:hidden": True}
    )


class DeleteTrackConfig(TrackID):
    operation: Literal["delete_track"] = Field(
        "delete_track", json_schema_extra={"ui:hidden": True}
    )


class LikeTrackConfig(TrackID):
    operation: Literal["like_track"] = Field(
        "like_track", json_schema_extra={"ui:hidden": True}
    )


class UnlikeTrackConfig(TrackID):
    operation: Literal["unlike_track"] = Field(
        "unlike_track", json_schema_extra={"ui:hidden": True}
    )


class RepostTrackConfig(TrackID):
    operation: Literal["repost_track"] = Field(
        "repost_track", json_schema_extra={"ui:hidden": True}
    )


class UnrepostTrackConfig(TrackID):
    operation: Literal["unrepost_track"] = Field(
        "unrepost_track", json_schema_extra={"ui:hidden": True}
    )


class LikePlaylistConfig(PlaylistID):
    operation: Literal["like_playlist"] = Field(
        "like_playlist", json_schema_extra={"ui:hidden": True}
    )


class UnlikePlaylistConfig(PlaylistID):
    operation: Literal["unlike_playlist"] = Field(
        "unlike_playlist", json_schema_extra={"ui:hidden": True}
    )


class RepostPlaylistConfig(PlaylistID):
    operation: Literal["repost_playlist"] = Field(
        "repost_playlist", json_schema_extra={"ui:hidden": True}
    )


class UnrepostPlaylistConfig(PlaylistID):
    operation: Literal["unrepost_playlist"] = Field(
        "unrepost_playlist", json_schema_extra={"ui:hidden": True}
    )


SoundcloudConfig = Annotated[
    Union[
        GetCurrentUserConfig,
        ListMyTracksConfig,
        ListMyPlaylistsConfig,
        ListMyLikedTracksConfig,
        ListMyFollowersConfig,
        ListMyFollowingsConfig,
        ListFollowingTracksConfig,
        FollowUserConfig,
        UnfollowUserConfig,
        CreatePlaylistConfig,
        UpdatePlaylistConfig,
        UpdateTrackConfig,
        DeleteTrackConfig,
        LikeTrackConfig,
        UnlikeTrackConfig,
        RepostTrackConfig,
        UnrepostTrackConfig,
        LikePlaylistConfig,
        UnlikePlaylistConfig,
        RepostPlaylistConfig,
        UnrepostPlaylistConfig,
    ],
    Field(discriminator="operation"),
]


class SoundcloudFullConfig(NodeConfig[SoundcloudConfig, SoundcloudOAuthCredential]):
    pass


def _check_credential(data):
    credential = data.get("credentials")
    if (
        isinstance(credential, dict)
        and credential.get("credential_type", "soundcloud_oauth") != "soundcloud_oauth"
    ):
        raise ValueError("Attach a SoundCloud OAuth credential")


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    return value


class SoundcloudNode(WorkflowNode):
    integration_type = "automation-soundcloud"
    scope_registry = SOUNDCLOUD_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="SoundCloud tracks",
        operation="list_my_tracks",
        identity_operation="get_current_user",
        identity_keys=("username", "full_name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return SoundcloudFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _check_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.soundcloud_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="soundcloud",
        )

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a SoundCloud account")
        # The shared seam owns locking, persistence and rotating-token adoption.
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.soundcloud_oauth import refresh_access_token

        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            pool=None,
            user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"),
            credential=data,
            refresh=refresh_access_token,
            provider="soundcloud",
            caller_path="execute",
        )
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in data:
                setattr(credential, key, data[key])
        config = self.config.config
        spec = SOUNDCLOUD_OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        params = {key: values.pop(key) for key in spec["query"] if key in values}
        body = None
        if config.operation in {"create_playlist", "update_playlist"}:
            if "track_ids" in values:
                values["tracks"] = [
                    {"id": str(item)} for item in values.pop("track_ids")
                ]
            body = {"playlist": values}
        elif config.operation == "update_track":
            body = {"track": values}
        secrets = (credential.access_token, credential.refresh_token)
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream(
                spec["method"],
                "https://api.soundcloud.com" + path,
                headers={
                    "Authorization": "OAuth " + credential.access_token,
                    "Accept": "application/json; charset=utf-8",
                },
                params=params,
                **({"json": body} if body is not None else {}),
            ) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("SoundCloud response exceeds 8 MiB")
                status = response.status_code
                if not 200 <= status < 300:
                    message = _redact(
                        bytes(raw).decode("utf-8", errors="replace"), secrets
                    )[:2000]
                    raise ValueError(f"SoundCloud HTTP {status}: {message}")
                result = None
                if raw:
                    if (
                        "application/json"
                        not in response.headers.get("content-type", "").lower()
                    ):
                        raise ValueError("SoundCloud did not return JSON")
                    try:
                        result = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("SoundCloud returned invalid JSON") from None
                if isinstance(result, dict) and (
                    "errors" in result or "error" in result
                ):
                    raise ValueError(
                        "SoundCloud returned an error: "
                        + str(_redact(result, secrets))[:2000]
                    )
                if config.operation.startswith("list_"):
                    rows = (
                        result.get("collection") if isinstance(result, dict) else result
                    )
                    if not isinstance(rows, list):
                        raise ValueError("SoundCloud returned no collection")
                elif config.operation == "get_current_user":
                    if (
                        not isinstance(result, dict)
                        or not result.get("id")
                        or not result.get("username")
                    ):
                        raise ValueError("SoundCloud returned no account identity")
        return {
            "status": "success",
            "data": _redact(result, secrets),
            "http_status": status,
        }
