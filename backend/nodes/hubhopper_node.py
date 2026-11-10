"""Hubhopper Partner v5: the complete read-only catalog and newest-content polls.

Contract: https://docs.hubhopper.com/api/integrations/partner/swagger.yaml
The partner contract offers no writes, account identity or webhook registration.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://apis.hubhopper.com/partner"
DOCS_URL = "https://docs.hubhopper.com/api/integrations/partner/"


class HubhopperAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hubhopper Partner API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste the API key and partner ID supplied by Hubhopper for the production Partner Integration API. These are sent as x-api-key and hhPartnerId. The connection check confirms access to the partner catalog; this API does not identify your account."})
    credential_type: Literal["hubhopper_api_key"] = Field("hubhopper_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    partner_id: str = Field(..., title="Partner ID", min_length=1, repr=False, description="The hhPartnerId supplied with your partner API access.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "partner_id", mode="before")
    @classmethod
    def header_value(cls, value):
        value = clean_secret(value, field_name="Hubhopper credential")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value) or len(value) > 4096:
            raise ValueError("Paste the supplied value without a header prefix or whitespace")
        return value


def operation_field(name, label, category, trigger=False):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True,
        "x-display-name": label, "x-category": category, "x-is-trigger": trigger})


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(100, ge=1, le=100, title="Page Size", description="Number of items per request; advance Page to read more.")


class _ContentPage(_Page):
    order: Literal["newest", "random"] = Field("newest", title="Order")
    filters_json: str | None = Field("{}", title="Filters JSON", description='Documented language filter, for example {"lang":["en","hi"]}.')

    @field_validator("filters_json")
    @classmethod
    def filters(cls, value):
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            raise ValueError("Filters must be a JSON object, for example {\"lang\":[\"en\"]}") from None
        if not isinstance(parsed, dict):
            raise ValueError("Filters must be a JSON object")
        return json.dumps(parsed, separators=(",", ":"))


class _Category(_Input):
    category_id: str = Field(..., min_length=1, max_length=256, title="Category ID", pattern=r"^[A-Za-z0-9_-]+$")


class _Podcast(_Input):
    podcast_id: str = Field(..., min_length=1, max_length=256, title="Podcast ID", pattern=r"^[A-Za-z0-9_-]+$")


class HubhopperListCategories(_Page):
    operation: Literal["list_categories"] = operation_field("list_categories", "List Categories", "Categories")


class HubhopperGetCategory(_Category):
    operation: Literal["get_category"] = operation_field("get_category", "Get Category", "Categories")


class HubhopperListCategoryPodcasts(_ContentPage, _Category):
    operation: Literal["list_category_podcasts"] = operation_field("list_category_podcasts", "List Category Podcasts", "Podcasts")


class HubhopperListPodcasts(_ContentPage):
    operation: Literal["list_podcasts"] = operation_field("list_podcasts", "List Podcasts", "Podcasts")


class HubhopperGetPodcast(_Podcast):
    operation: Literal["get_podcast"] = operation_field("get_podcast", "Get Podcast", "Podcasts")


class HubhopperListEpisodes(_ContentPage, _Podcast):
    operation: Literal["list_episodes"] = operation_field("list_episodes", "List Podcast Episodes", "Episodes")


class HubhopperListLanguages(_Page):
    operation: Literal["list_languages"] = operation_field("list_languages", "List Languages", "Languages")


class HubhopperOnNewPodcast(PollTriggerConfigBase):
    """Monitor the newest 100 podcasts; shorten the schedule for busy catalogs."""
    operation: Literal["on_new_podcast"] = operation_field("on_new_podcast", "On New Podcast", "Triggers", True)


class HubhopperOnNewCategoryPodcast(PollTriggerConfigBase, _Category):
    """Monitor the newest 100 podcasts in this category between polls."""
    operation: Literal["on_new_category_podcast"] = operation_field("on_new_category_podcast", "On New Category Podcast", "Triggers", True)


class HubhopperOnNewEpisode(PollTriggerConfigBase, _Podcast):
    """Monitor the newest 100 episodes in this podcast between polls."""
    operation: Literal["on_new_episode"] = operation_field("on_new_episode", "On New Podcast Episode", "Triggers", True)


HubhopperOperation = Annotated[Union[HubhopperListCategories, HubhopperGetCategory,
    HubhopperListCategoryPodcasts, HubhopperListPodcasts, HubhopperGetPodcast,
    HubhopperListEpisodes, HubhopperListLanguages, HubhopperOnNewPodcast,
    HubhopperOnNewCategoryPodcast, HubhopperOnNewEpisode], Field(discriminator="operation")]


class HubhopperNodeConfig(NodeConfig[HubhopperOperation, HubhopperAPIKeyCredential]):
    pass


ROUTES = {
    "list_categories": ("/categories", "categories"),
    "get_category": ("/categories/{category_id}", "category"),
    "list_category_podcasts": ("/categories/{category_id}/podcasts", "podcasts"),
    "list_podcasts": ("/podcasts", "podcasts"),
    "get_podcast": ("/podcasts/{podcast_id}", "podcast"),
    "list_episodes": ("/podcasts/{podcast_id}/episodes", "episodes"),
    "list_languages": ("/util/languages", "languages"),
}
POLL_READS = {"on_new_podcast": "list_podcasts",
    "on_new_category_podcast": "list_category_podcasts", "on_new_episode": "list_episodes"}


class HubhopperNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-hubhopper"
    connection_evidence = ConnectionEvidence(operation="list_categories", noun="Hubhopper partner catalog categories",
        label_keys=("name", "id"), proves="reachability")
    edit_examples = ["List the newest Hubhopper podcasts", "Read episodes from a Hubhopper podcast",
        "Run when a new Hubhopper podcast episode appears"]

    @classmethod
    def get_config_model(cls):
        return HubhopperNodeConfig

    async def _request(self, path: str, params: dict[str, str] | None = None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Hubhopper Partner API key and partner ID")
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request("GET", BASE_URL + path, params=params,
                headers={"x-api-key": credential.api_key, "hhPartnerId": credential.partner_id,
                    "Accept": "application/json"})
        if response.status_code == 204 and path == "/util/languages":
            return {"languages": []}
        if response.is_error or response.is_redirect:
            message = response.text[:1000]
            for secret in (credential.api_key, credential.partner_id):
                message = message.replace(secret, "[redacted]")
            raise ValueError(f"Hubhopper HTTP {response.status_code}: {message}")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object from Hubhopper")
        return body

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self.config.config
        name = config.operation
        read = POLL_READS.get(name, name)
        path, key = ROUTES[read]
        for field in ("category_id", "podcast_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(getattr(config, field), safe=""))
        if name in POLL_READS:
            # The contract can sort newest but cannot filter by a time cursor.
            # Monitor the latest 100 per interval; the shared poll family baselines
            # on arming and resets that baseline when the declared scope changes.
            body = await self._request(path, {"page": "1", "pageSize": "100", "order": "newest"})
            items = body.get(key)
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                raise ValueError(f"Hubhopper response is missing {key}")
            id_field = "episodeId" if key == "episodes" else "podcastId"
            fresh = await self._filter_unseen(items, lambda row: str(row[id_field]) if row.get(id_field) is not None else None)
            return {key: fresh, "new_item_count": len(fresh)}
        params = None
        if isinstance(config, _Page):
            params = {"page": str(config.page), "pageSize": str(config.page_size)}
        if isinstance(config, _ContentPage):
            params["order"] = config.order
            if config.filters_json not in (None, "{}"):
                params["filters"] = config.filters_json
        return await self._request(path, params)

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_item_count")) if config.get("operation") in POLL_READS else True

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("episodes", output.get("podcasts"))
        if not isinstance(rows, list) or not rows:
            return None
        episode = "episodes" in output
        lines = []
        for row in rows[:10]:
            identifier = row.get("episodeId" if episode else "podcastId")
            url = row.get("episodeUrl" if episode else "url") or ""
            parent = f"; podcast {row.get('podcastId')}" if episode else ""
            lines.append(f"- {row.get('title') or 'Untitled'} by {row.get('author') or 'Unknown author'} (ID {identifier}{parent}) {url}\n  {row.get('description') or ''}")
        kind = "episode(s)" if episode else "podcast(s)"
        return {"text": f"Hubhopper: {len(rows)} new {kind}\n" + "\n".join(lines), "conversation_key": None}
