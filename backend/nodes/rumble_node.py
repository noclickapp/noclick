"""Rumble Network Discovery's frozen v2.15.0 organization API.

Contract: https://raw.githubusercontent.com/RumbleDiscovery/rumble-api/main/rumble-api.yml
Rumble is now runZero; this integration deliberately uses the deprecated API.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://console.rumble.run/api/v1.0"


class RumbleAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rumble Organization API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.runzero.com/docs/leveraging-the-api/",
            "x-credential-instructions": "Paste an organization API key for the deprecated Rumble v2.15.0 API. Export tokens do not authorize organization management. Asset polling requires the Splunk entitlement. Rumble Network Discovery is now runZero.",
        })
    credential_type: Literal["rumble_api_key"] = Field("rumble_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Organization API key", min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Organization API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class RumbleInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


# Each entry is exactly one published operation, with explicit wire fields.
# name: (method, path, query fields, JSON body fields)
OPERATIONS = {
    "get_organization": ("GET", "/org", (), ()),
    "list_sites": ("GET", "/org/sites", (), ()),
    "get_site": ("GET", "/org/sites/{site_id}", (), ()),
    "create_site": ("PUT", "/org/sites", (), ("name", "description", "scope", "excludes")),
    "update_site": ("PATCH", "/org/sites/{site_id}", (), ("name", "description", "scope", "excludes")),
    "delete_site": ("DELETE", "/org/sites/{site_id}", (), ()),
    "list_assets": ("GET", "/org/assets", ("search",), ()),
    "get_asset": ("GET", "/org/assets/{asset_id}", (), ()),
    "delete_asset": ("DELETE", "/org/assets/{asset_id}", (), ()),
    "update_asset_comments": ("PATCH", "/org/assets/{asset_id}/comments", (), ("comments",)),
    "update_asset_tags": ("PATCH", "/org/assets/{asset_id}/tags", (), ("tags",)),
    "list_services": ("GET", "/org/services", ("search",), ()),
    "get_service": ("GET", "/org/services/{service_id}", (), ()),
    "list_agents": ("GET", "/org/agents", (), ()),
    "get_agent": ("GET", "/org/agents/{agent_id}", (), ()),
    "create_scan": ("PUT", "/org/sites/{site_id}/scan", (), ("targets", "excludes", "scan-name", "scan-description", "scan-frequency", "scan-tags", "agent", "rate")),
    "stop_task": ("POST", "/org/tasks/{task_id}/stop", (), ()),
    "export_assets": ("GET", "/export/org/assets.json", ("search", "fields"), ()),
    "export_services": ("GET", "/export/org/services.json", ("search", "fields"), ()),
    "list_tasks": ("GET", "/org/tasks", ("status", "search"), ()),
    "get_task": ("GET", "/org/tasks/{task_id}", (), ()),
    "on_new_asset": ("GET", "/export/org/assets/sync/created/assets.json", ("since", "search"), ()),
    "on_updated_asset": ("GET", "/export/org/assets/sync/updated/assets.json", ("since", "search"), ()),
}


def _model(name, spec):
    method, path, query, body = spec
    trigger = name.startswith("on_")
    fields = {"operation": (Literal[name], Field(name, title=name.replace("_", " ").title(),
        json_schema_extra={"ui:hidden": True, **({"x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": name.replace("_", " ").title()} if trigger else {})}))}
    for part in path.split("/"):
        if part.startswith("{"):
            fields[part[1:-1]] = (UUID, Field(..., title=part[1:-1].replace("_", " ").title()))
    for field in query:
        fields[field] = (int, Field(0, ge=0, description="Unix timestamp lower bound. Requires Splunk entitlement.")) if field == "since" else (str | None, Field(None))
    for field in body:
        required = field in {"name", "comments", "tags", "targets"}
        field_type = str if required else str | None
        if field == "scan-frequency":
            field_type = Literal["once", "hourly", "daily", "weekly", "monthly", "continuous"] | None
        if field == "agent":
            field_type = UUID | None
        fields[field.replace("-", "_")] = (field_type, Field(... if required else None,
            serialization_alias=field,
            description="Tag expression, e.g. ThisTag=Value -OldTag" if field == "tags" else (
                "Use defaults for the site's configured targets, or specify scan targets." if field == "targets" else None)))
    return create_model("Rumble" + name.title().replace("_", "") + "Config",
        __base__=PollTriggerConfigBase if trigger else RumbleInput, **fields)


MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in MODELS.values()})
RumbleConfig = Annotated[Union[tuple(MODELS.values())], Field(discriminator="operation")]


class RumbleFullConfig(NodeConfig[RumbleConfig, RumbleAPIKeyCredential]):
    pass


class RumbleNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-rumble"
    connection_evidence = ConnectionEvidence(identity_operation="get_organization", noun="Rumble organization")

    @classmethod
    def get_config_model(cls):
        return RumbleFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Rumble organization API key")
        config = self.config.config
        method, path, query, body_fields = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, by_alias=True)
        for field, value in values.items():
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in query if key in values}
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        # The frozen spec says text/json for createScan. Provider's current
        # documented curl and OpenAPI both require application/json:
        # https://help.runzero.com/docs/leveraging-the-api/#scan-api-usage
        # httpx's json= sends that documented media type.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key,
                         "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {}))
        if response.status_code >= 400:
            # Keep provider rejection text for the manual-connect evidence seam.
            raise ValueError(f"Rumble HTTP {response.status_code}: " + response.text.replace(self.config.credentials.api_key, "[redacted]")[:1000])
        if response.status_code not in {200, 204}:
            raise ValueError(f"Unexpected Rumble HTTP {response.status_code}")
        data = None if response.status_code == 204 or (config.operation == "stop_task" and not response.content) else response.json()
        if config.operation == "get_organization":
            if not isinstance(data, dict) or not data.get("id") or not data.get("name"):
                raise ValueError("Rumble organization response is missing id or name")
            # The organization contract also contains download/export secrets.
            data = {key: data[key] for key in ("id", "name", "description") if key in data}
        if config.operation.startswith("on_"):
            if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
                raise ValueError("Rumble asset sync response must contain assets")
            timestamp = "created_at" if config.operation == "on_new_asset" else "updated_at"
            rows = data["assets"]
            if len(rows) > 10_000:
                raise ValueError("Rumble poll exceeds 10,000 assets; narrow search or since before arming")
            if any(not isinstance(row, dict) or not row.get("id") or type(row.get(timestamp)) is not int for row in rows):
                raise ValueError("Rumble poll requires asset ids and documented timestamps")
            fresh = await self._filter_unseen(rows, lambda row: str(row["id"]) + ":" + str(row[timestamp]))
            result = {"assets": fresh, "count": len(fresh)}
        else:
            result = {"data": data, "status": "success"}
        await self.emit(result)
        return result

    @classmethod
    def resolve_agent_event(cls, output):
        assets = output.get("assets", [])
        if not assets:
            return None
        details = "; ".join(
            f"{', '.join(row.get('names') or []) or row['id']} ({', '.join(row.get('addresses') or [])}; asset {row['id']})"
            for row in assets[:20]
        )
        return {"text": f"Rumble Network Discovery reported {len(assets)} new or updated network assets: {details}",
                "assets": assets}
