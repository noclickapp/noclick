"""Zeno Podcast Bot, pinned to Aggregators API Service 1.2-86f57be.

Routes: https://api.zeno.fm/v3/api-docs
API-key header: https://api.zeno.fm/v3/api-docs/podcast-bot
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://api.zeno.fm"
PODCAST = "/podcast-bot/podcasts/{podcast_key}"
EPISODE = PODCAST + "/episodes/{episode_key}"


class ZenoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zeno API Key", json_schema_extra={
        "x-credential-url": "https://zeno.fm/mcp/",
        "x-credential-instructions": "Paste your Zeno Podcast Bot API key. NoClick sends it to api.zeno.fm in the x-api-key header and lists your podcasts to check the connection.",
    })
    credential_type: Literal["zeno_api_key"] = Field("zeno_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = value.strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or spaces")
        return value


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    paged: bool = False
    text: bool = False


OPERATIONS = {
    "list_podcasts": Operation("List Podcasts", "GET", "/podcast-bot/podcasts/list", True),
    "get_podcast": Operation("Get Podcast", "GET", PODCAST),
    "update_podcast": Operation("Update Podcast", "PUT", PODCAST),
    "delete_podcast": Operation("Delete Podcast", "DELETE", PODCAST),
    "list_episodes": Operation("List Episodes", "GET", PODCAST + "/episodes", True),
    "get_episode": Operation("Get Episode", "GET", EPISODE),
    "delete_episode": Operation("Delete Episode", "DELETE", EPISODE),
    "publish_episode": Operation("Publish Episode", "PUT", EPISODE + "/publish"),
    "unpublish_episode": Operation("Unpublish Episode", "PUT", EPISODE + "/unpublish"),
    "reprocess_episode": Operation("Reprocess Episode", "POST", EPISODE + "/reprocess"),
    "create_episode_video": Operation("Create Episode Video Using Stored Configuration", "POST", EPISODE + "/createVideo"),
    "create_episode_clips": Operation("Create Episode Clips Using Stored Configuration", "POST", EPISODE + "/autoClips"),
    "get_transcript": Operation("Get Episode Transcript", "GET", EPISODE + "/transcript", text=True),
    "get_timed_transcript": Operation("Get Episode Timed Transcript", "GET", EPISODE + "/timedTranscript", text=True),
    "get_episode_metadata": Operation("Get Episode Metadata", "GET", EPISODE + "/metadata"),
    "list_episode_clips": Operation("List Episode Clips", "GET", EPISODE + "/clips"),
    "list_episode_chapters": Operation("List Episode Chapters", "GET", EPISODE + "/chapters"),
    "get_episode_ad_markers": Operation("Get Episode Ad Markers", "GET", EPISODE + "/adsMarkers"),
    "list_podcast_videos": Operation("List Podcast Videos", "GET", PODCAST + "/videos", True),
    "list_episode_videos": Operation("List Episode Videos", "GET", EPISODE + "/videos"),
    "get_job": Operation("Get Processing Job", "GET", "/podcast-bot/jobs/{job_id}"),
    "list_episode_jobs": Operation("List Episode Processing Jobs", "GET", "/podcast-bot/jobs/podcasts/{podcast_key}/episodes/{episode_key}"),
}


class ZenoInput(BaseModel):
    @field_validator("podcast_key", "episode_key", "job_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if not value.strip() or value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Enter the Zeno resource key")
        return value


def _config(name, spec):
    fields: dict[str, Any] = {"operation": (Literal[name], Field(name, title=spec.label, json_schema_extra={
        "ui:hidden": True, "x-display-name": spec.label, "x-is-trigger": False,
        "x-category": "Podcasts" if "episode" not in name else "Episodes",
    }))}
    for key, title in (("podcast_key", "Podcast Key"), ("episode_key", "Episode Key"), ("job_id", "Job ID")):
        if "{" + key + "}" in spec.path:
            fields[key] = (str, Field(..., min_length=1, title=title))
    if spec.paged:
        fields["limit"] = (int, Field(50, ge=1, le=500, description="Page size. Use offset to retrieve another page."))
        fields["offset"] = (int, Field(0, ge=0, description="Number of records to skip."))
    if name == "update_podcast":
        for key, title in (("title", "Title"), ("description", "Description"), ("language", "Language"), ("ownerName", "Owner Name"), ("ownerEmail", "Owner Email")):
            fields[key] = (str, Field(..., title=title))
        fields["categories"] = (list[str], Field(..., title="Categories"))
        for key in ("author", "coverArtUrl", "link"):
            fields[key] = (Optional[str], Field(None))
        fields["explicit"] = (Optional[bool], Field(None))
    return create_model("Zeno" + "".join(s.title() for s in name.split("_")) + "Config", __base__=ZenoInput, **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ZenoOnNewVideoConfig(PollTriggerConfigBase):
    operation: Literal["on_new_video"] = Field("on_new_video", title="On New Podcast Video", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Podcast Video", "x-category": "Triggers",
    })
    podcast_key: str = Field(..., min_length=1, title="Podcast Key")


ZenoConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ZenoOnNewVideoConfig,)], Field(discriminator="operation")]


class ZenoNodeConfig(NodeConfig[ZenoConfig, ZenoAPIKeyCredential]):
    pass


class ZenoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zeno"
    connection_evidence = ConnectionEvidence(operation="list_podcasts", noun="podcasts")

    @classmethod
    def get_config_model(cls):
        return ZenoNodeConfig

    @classmethod
    def resolve_agent_event(cls, output):
        videos = output.get("videos")
        if not isinstance(videos, list):
            return super().resolve_agent_event(output)
        if not videos:
            return None
        podcast = output.get("podcast_key", "")
        lines = [f"New Zeno podcast video(s) in podcast {podcast}:"]
        for video in videos[:20]:
            lines.append(f"- {video.get('name') or 'Video'}: video ID {video.get('id')}, episode key {video.get('episodeKey')}, aspect ratio {video.get('aspectRatio')}; {video.get('fileUrl') or ''}")
        lines.append(f"Use get_episode with podcast_key={podcast} and the episode key to inspect an episode.")
        return {"text": "\n".join(lines), "conversation_key": f"zeno:{podcast}", "title": "New Zeno podcast videos"}

    async def _request(self, method, path, *, params=None, body=None, text=False):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Zeno API key")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"x-api-key": credential.api_key, "Accept": "application/json, text/plain"},
                **({"json": body} if body is not None else {}))
        if not response.is_success:
            # Preserve provider rejection text for connection evidence; redact the supplied key.
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Zeno API {response.status_code}: {detail}")
        if not response.content:
            return None
        if text:
            if "json" in response.headers.get("content-type", ""):
                return response.json()
            return response.text
        return response.json()

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, ZenoOnNewVideoConfig):
            # The contract explicitly orders this endpoint newest episode first.
            # Retrieve all pages before advancing the seen set; never baseline a partial scan.
            rows = []
            for offset in range(0, 10000, 500):
                page = await self._request("GET", PODCAST.replace("{podcast_key}", quote(config.podcast_key, safe="")) + "/videos",
                    params={"limit": "500", "offset": str(offset)})
                if not isinstance(page, dict) or not isinstance(page.get("data"), list) or not isinstance(page.get("total"), int):
                    raise ValueError("Zeno video page must contain data and total")
                rows.extend(page["data"])
                if offset + len(page["data"]) >= page["total"]:
                    break
                if not page["data"]:
                    raise ValueError("Zeno returned an incomplete video page")
            else:
                raise ValueError("This podcast exceeds the 10,000-video polling limit")
            if any(not isinstance(row, dict) or row.get("id") is None for row in rows):
                raise ValueError("Zeno video is missing its ID")
            fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
            return {"videos": fresh, "new_video_count": len(fresh), "podcast_key": config.podcast_key}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {key: str(values.pop(key)) for key in ("limit", "offset") if key in values}
        data = await self._request(spec.method, path, params=params or None,
            body=values if config.operation == "update_podcast" else None, text=spec.text)
        # Empty successful responses acknowledge the API call, not completion of asynchronous jobs.
        return {"data": data, "request_accepted": True}
