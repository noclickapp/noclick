"""Luxury Presence CMS and CRM operations using a manually supplied API key.

Each operation makes one request to the provider's fixed public API host.
The published v1.0 contract defines the routes; the getting-started guide defines x-api-key authentication.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.luxurypresence.com"
CREDENTIAL_TYPE = "luxury_presence_api_key"


class LuxuryPresenceApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Luxury Presence API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.luxurypresence.com/",
            "x-credential-instructions": "An account admin can generate an API key in Settings → API Keys → Generate Key. Paste the key here. NoClick sends it as x-api-key to api.luxurypresence.com. Connection verification reads your agents.",
        })
    credential_type: Literal["luxury_presence_api_key"] = Field("luxury_presence_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    offset: int = Field(0, ge=0, title="Offset", description="Number of records to skip; request another page explicitly.")
    limit: int = Field(100, ge=1, le=100, title="Page Size")


class _SearchPage(_Page):
    search: str | None = Field(None, title="Search")
    external_source: str | None = Field(None, title="External Source")
    external_ids: list[str] | None = Field(None, title="External IDs")


class _Resource(_Input):
    resource_id: str = Field(..., min_length=1, title="Resource ID", pattern=r"^[A-Za-z0-9_-]+$", description="The existing agent, office, team, media or webhook ID for this operation.")


class _AgentFields(_Input):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    position: str | None = None
    bio_short_description: str | None = None
    website_url: str | None = None
    tags: list[str] | None = None
    offices: list[str] | None = None
    do_not_allow_duplicates: bool = Field(True, title="Reject Duplicate Emails")


class _OfficeFields(_Input):
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    short_description: str | None = None
    full_description: str | None = None
    media_url: str | None = None
    slug: str | None = None


class _TeamFields(_Input):
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    bio_short_description: str | None = None
    website_url: str | None = None
    tags: list[str] | None = None
    do_not_allow_duplicates: bool = Field(True, title="Reject Duplicate Emails")


class _Members(_Resource):
    agent_ids: list[UUID] = Field(..., min_length=1, title="Agent IDs")


class ListAgents(_SearchPage):
    operation: Literal["list_agents"] = Field("list_agents", title="List Agents", json_schema_extra={"ui:hidden": True})
    tags: list[str] | None = None
    tags_mode: Literal["ANY", "ALL", "NOT", "NOT_ALL"] | None = None
    emails: list[str] | None = None


class GetAgent(_Resource):
    operation: Literal["get_agent"] = Field("get_agent", title="Get Agent", json_schema_extra={"ui:hidden": True})


class CreateAgent(_AgentFields):
    operation: Literal["create_agent"] = Field("create_agent", title="Create Agent", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    external_source: str | None = None
    external_id: str | None = None


class UpdateAgent(_Resource, _AgentFields):
    operation: Literal["update_agent"] = Field("update_agent", title="Update Agent", json_schema_extra={"ui:hidden": True})


class DeleteAgent(_Resource):
    operation: Literal["delete_agent"] = Field("delete_agent", title="Delete Agent", json_schema_extra={"ui:hidden": True})
    action: Literal["archive", "unassign"] | None = Field(None, description="Controls handling of the agent listings.")


class ListOffices(_SearchPage):
    operation: Literal["list_offices"] = Field("list_offices", title="List Offices", json_schema_extra={"ui:hidden": True})


class GetOffice(_Resource):
    operation: Literal["get_office"] = Field("get_office", title="Get Office", json_schema_extra={"ui:hidden": True})


class CreateOffice(_OfficeFields):
    operation: Literal["create_office"] = Field("create_office", title="Create Office", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    external_source: str | None = None
    external_id: str | None = None


class UpdateOffice(_Resource, _OfficeFields):
    operation: Literal["update_office"] = Field("update_office", title="Update Office", json_schema_extra={"ui:hidden": True})


class DeleteOffice(_Resource):
    operation: Literal["delete_office"] = Field("delete_office", title="Delete Office", json_schema_extra={"ui:hidden": True})


class ListTeams(_SearchPage):
    operation: Literal["list_teams"] = Field("list_teams", title="List Teams", json_schema_extra={"ui:hidden": True})


class GetTeam(_Resource):
    operation: Literal["get_team"] = Field("get_team", title="Get Team", json_schema_extra={"ui:hidden": True})


class CreateTeam(_TeamFields):
    operation: Literal["create_team"] = Field("create_team", title="Create Team", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    external_source: str | None = None
    external_id: str | None = None


class UpdateTeam(_Resource, _TeamFields):
    operation: Literal["update_team"] = Field("update_team", title="Update Team", json_schema_extra={"ui:hidden": True})


class DeleteTeam(_Resource):
    operation: Literal["delete_team"] = Field("delete_team", title="Delete Team", json_schema_extra={"ui:hidden": True})


class ListOfficeAgents(_Resource, _Page):
    operation: Literal["list_office_agents"] = Field("list_office_agents", title="List Office Agents", json_schema_extra={"ui:hidden": True})


class AddOfficeAgents(_Members):
    operation: Literal["add_office_agents"] = Field("add_office_agents", title="Add Office Agents", json_schema_extra={"ui:hidden": True})


class RemoveOfficeAgents(_Members):
    operation: Literal["remove_office_agents"] = Field("remove_office_agents", title="Remove Office Agents", json_schema_extra={"ui:hidden": True})


class ListTeamAgents(_Resource, _Page):
    operation: Literal["list_team_agents"] = Field("list_team_agents", title="List Team Agents", json_schema_extra={"ui:hidden": True})


class AddTeamAgents(_Members):
    operation: Literal["add_team_agents"] = Field("add_team_agents", title="Add Team Agents", json_schema_extra={"ui:hidden": True})


class RemoveTeamAgents(_Members):
    operation: Literal["remove_team_agents"] = Field("remove_team_agents", title="Remove Team Agents", json_schema_extra={"ui:hidden": True})


class GetMedia(_Resource):
    operation: Literal["get_media"] = Field("get_media", title="Get Media", json_schema_extra={"ui:hidden": True})


class ListWebhooks(_Input):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})


class CreateWebhook(_Input):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Webhook Name")
    url: str = Field(..., pattern=r"^https://[^\s]+$", title="Webhook URL")
    secret: str | None = Field(None, title="Signing Secret", repr=False, json_schema_extra={"ui:widget": "password"}, description="Set a secret to enable HMAC-SHA256 delivery signatures. Without it, deliveries are unsigned.")
    is_active: bool = Field(True, title="Active")


class DeleteWebhook(_Resource):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})


LuxuryPresenceConfig = Annotated[Union[
    ListAgents,
    GetAgent,
    CreateAgent,
    UpdateAgent,
    DeleteAgent,
    ListOffices,
    GetOffice,
    CreateOffice,
    UpdateOffice,
    DeleteOffice,
    ListTeams,
    GetTeam,
    CreateTeam,
    UpdateTeam,
    DeleteTeam,
    ListOfficeAgents,
    AddOfficeAgents,
    RemoveOfficeAgents,
    ListTeamAgents,
    AddTeamAgents,
    RemoveTeamAgents,
    GetMedia,
    ListWebhooks,
    CreateWebhook,
    DeleteWebhook
], Field(discriminator="operation")]


class LuxuryPresenceFullConfig(NodeConfig[LuxuryPresenceConfig, LuxuryPresenceApiKeyCredential]):
    pass


# One public-contract endpoint for each operation; no generic URL or method input.
ROUTES = {
    "list_agents": ("GET", "/cms/v1/agents"),
    "get_agent": ("GET", "/cms/v1/agents/{id}"),
    "create_agent": ("POST", "/cms/v1/agents"),
    "update_agent": ("PATCH", "/cms/v1/agents/{id}"),
    "delete_agent": ("DELETE", "/cms/v1/agents/{id}"),
    "list_offices": ("GET", "/cms/v1/offices"),
    "get_office": ("GET", "/cms/v1/offices/{id}"),
    "create_office": ("POST", "/cms/v1/offices"),
    "update_office": ("PATCH", "/cms/v1/offices/{id}"),
    "delete_office": ("DELETE", "/cms/v1/offices/{id}"),
    "list_teams": ("GET", "/cms/v1/teams"),
    "get_team": ("GET", "/cms/v1/teams/{id}"),
    "create_team": ("POST", "/cms/v1/teams"),
    "update_team": ("PATCH", "/cms/v1/teams/{id}"),
    "delete_team": ("DELETE", "/cms/v1/teams/{id}"),
    "list_office_agents": ("GET", "/cms/v1/offices/{id}/agents"),
    "add_office_agents": ("POST", "/cms/v1/offices/{id}/agents"),
    "remove_office_agents": ("DELETE", "/cms/v1/offices/{id}/agents"),
    "list_team_agents": ("GET", "/cms/v1/teams/{id}/agents"),
    "add_team_agents": ("POST", "/cms/v1/teams/{id}/agents"),
    "remove_team_agents": ("DELETE", "/cms/v1/teams/{id}/agents"),
    "get_media": ("GET", "/cms/v1/media/{id}"),
    "list_webhooks": ("GET", "/crm/v1/webhooks"),
    "create_webhook": ("POST", "/crm/v1/webhooks"),
    "delete_webhook": ("DELETE", "/crm/v1/webhooks/{id}"),
}
WIRE_NAMES = {
    "external_ids": "externalIds", "external_id": "externalId", "external_source": "externalSource",
    "first_name": "firstName", "last_name": "lastName", "phone_number": "phoneNumber",
    "bio_short_description": "bioShortDescription", "website_url": "websiteUrl",
    "short_description": "shortDescription", "full_description": "fullDescription",
    "media_url": "mediaUrl", "tags_mode": "tagsMode", "agent_ids": "agentIds", "is_active": "isActive",
}


def _redact_secrets(body):
    # The webhook API may echo its signing secret; keep it out of workflow outputs.
    if isinstance(body, dict):
        return {k: _redact_secrets(v) for k, v in body.items() if k not in {"secret", "headers"}}
    if isinstance(body, list):
        return [_redact_secrets(v) for v in body]
    return body


class LuxuryPresenceNode(WorkflowNode):
    integration_type = "automation-luxury-presence"
    connection_evidence = ConnectionEvidence(operation="list_agents", noun="agents", label_keys=("email", "firstName", "lastName", "agentId"))

    @classmethod
    def get_config_model(cls):
        return LuxuryPresenceFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Luxury Presence API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "resource_id" in values:
            path = path.replace("{id}", quote(values.pop("resource_id"), safe=""))
        params = {}
        if "do_not_allow_duplicates" in values:
            params["doNotAllowDuplicates"] = str(values.pop("do_not_allow_duplicates")).lower()
        body = None
        if method == "GET" or config.operation == "delete_agent":
            params.update({WIRE_NAMES.get(k, k): v for k, v in values.items()})
        elif method in {"POST", "PATCH"} or config.operation.startswith("remove_"):
            body = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
            if config.operation == "create_webhook":
                # The provider supports only 'leads'; activity filtering belongs in the receiver.
                body["events"] = ["leads"]
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"x-api-key": self.config.credentials.api_key, "Accept": "application/json"})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            message = response.text[:3000]
            for secret in (self.config.credentials.api_key, getattr(config, "secret", None)):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"Luxury Presence API error {response.status_code}: {message}") from None
        if response.status_code == 204 or not response.content:
            return {"status": "success", "operation": config.operation, "data": None}
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Luxury Presence returned an unexpected response shape")
        if isinstance(data, dict) and (data.get("error") or data.get("statusCode", 200) >= 400):
            raise ValueError(str(data.get("message") or data.get("error")))
        data = _redact_secrets(data) if "webhook" in config.operation else data
        result = {"status": "success", "operation": config.operation, "data": data}
        if config.operation.startswith("list_"):
            items = data.get("items") if isinstance(data, dict) else data
            if not isinstance(items, list):
                if config.operation in {"list_office_agents", "list_team_agents"}:
                    # These routes publish no response schema. Preserve raw JSON.
                    return result
                raise ValueError("Luxury Presence list response has no items array")
            result["items"] = items
            if isinstance(config, _Page):
                result["offset"] = config.offset
                result["limit"] = config.limit
                result["next_offset"] = config.offset + len(items) if len(items) == config.limit else None
        return result
