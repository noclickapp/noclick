"""Unleash Admin API: feature flags, rollout strategies and reusable segments.

Contract: https://docs.getunleash.io/openapi/admin-api.yaml (1.0.0).
Each operation performs exactly one request; writes are never retried.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    @field_validator("*")
    @classmethod
    def path_component(cls, value, info):
        if info.field_name in {"project_id", "feature_name", "environment", "strategy_id"}:
            if not isinstance(value, str) or value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a single resource name without dot traversal or control characters")
        return value


class UnleashTokenCredential(BaseModel):
    model_config = ConfigDict(title="Unleash Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.getunleash.io/concepts/api-tokens-and-client-keys",
            "x-credential-instructions": "In Unleash, open Profile > View profile settings > Personal API tokens and create a token. Paste it with your instance base URL. Service account tokens also work. Permissions follow the token's user or service account; allow project reads to verify the connection, and the write permissions needed by your workflow. Backend and frontend SDK tokens cannot manage flags."})
    credential_type: Literal["unleash_token"] = Field("unleash_token", json_schema_extra={"ui:hidden": True})
    instance_url: str = Field(..., title="Instance URL", description="Public HTTPS base URL before /api, e.g. https://example.app.unleash-hosted.com. A self-hosted path prefix is supported.")
    api_token: str = Field(..., title="Access token", min_length=1, max_length=4096, repr=False,
        description="Paste the complete personal access or service account token, without a Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("instance_url", mode="before")
    @classmethod
    def base_url(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter the public HTTPS instance base URL")
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or "." not in parts.hostname
                or parts.username is not None or parts.password is not None or parts.port not in (None, 443)
                or parts.query or parts.fragment or not value.isascii() or any(c.isspace() for c in value)
                or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", parts.path)
                or parts.path.endswith("/api")):
            raise ValueError("Use a public HTTPS base URL before /api, without query or fragment")
        return value

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the complete token without a header prefix or whitespace")
        return value


def _picker(name, parents=None):
    return {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True,
        **({"depends_on": parents} if parents else {})}}


class _Project(_Input):
    project_id: str = Field(..., min_length=1, max_length=255, title="Project", json_schema_extra=_picker("project_id"))


class _Feature(_Project):
    feature_name: str = Field(..., min_length=1, max_length=255, title="Feature flag", json_schema_extra=_picker("feature_name", ["project_id"]))


class _FeatureEnvironment(_Feature):
    environment: str = Field(..., min_length=1, max_length=255, title="Environment", json_schema_extra=_picker("environment"))


class _Strategy(_FeatureEnvironment):
    strategy_id: str = Field(..., min_length=1, max_length=255, title="Strategy ID", description="ID of an existing strategy configuration, not its strategy type name.")


class _Segment(_Input):
    segment_id: int = Field(..., ge=1, title="Segment", json_schema_extra=_picker("segment_id"))


FeatureType = Literal["experiment", "kill-switch", "release", "operational", "permission", "sunset"]


class UnleashConstraint(_Input):
    context_name: str = Field(..., alias="contextName", min_length=1)
    operator: Literal["NOT_IN", "IN", "STR_ENDS_WITH", "STR_STARTS_WITH", "STR_CONTAINS", "NUM_EQ", "NUM_GT", "NUM_GTE", "NUM_LT", "NUM_LTE", "DATE_AFTER", "DATE_BEFORE", "SEMVER_EQ", "SEMVER_GT", "SEMVER_LT", "SEMVER_GTE", "SEMVER_LTE", "REGEX", "IN_CIDR"]
    values: list[str] | None = None
    value: str | None = Field(None, min_length=1)
    case_insensitive: StrictBool | None = Field(None, alias="caseInsensitive")
    inverted: StrictBool | None = None


class _StrategyFields(_Input):
    title: str | None = None
    disabled: StrictBool | None = None
    parameters: dict[str, str] | None = Field(None, description='Strategy parameters, e.g. {"rollout":"50","stickiness":"default","groupId":"checkout"} for flexibleRollout.')
    constraints: list[UnleashConstraint] | None = None
    segments: list[int] | None = None


class _SegmentFields(_Input):
    name: str = Field(..., min_length=1, max_length=255)
    constraints: list[UnleashConstraint] = Field(..., description="Complete constraint list; an empty list matches all contexts.")
    description: str | None = None
    project: str | None = Field(None, description="Project ID, or omit for a global segment.")


class UnleashListProjectsConfig(_Input):
    """List projects visible to this token."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    archived: StrictBool | None = None


class UnleashGetProjectConfig(_Project):
    """Get a project overview."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class UnleashListFeaturesConfig(_Project):
    """List feature flags in a project."""
    operation: Literal["list_features"] = Field("list_features", json_schema_extra={"ui:hidden": True})


class UnleashGetFeatureConfig(_Feature):
    """Get a flag and its configuration."""
    operation: Literal["get_feature"] = Field("get_feature", json_schema_extra={"ui:hidden": True})


class UnleashCreateFeatureConfig(_Project):
    """Create a feature flag in a project."""
    operation: Literal["create_feature"] = Field("create_feature", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    feature_type: FeatureType | None = Field(None, alias="type")
    description: str | None = None
    impression_data: StrictBool | None = Field(None, alias="impressionData")


class UnleashUpdateFeatureConfig(_Feature):
    """Update supplied flag metadata fields."""
    operation: Literal["update_feature"] = Field("update_feature", json_schema_extra={"ui:hidden": True})
    description: str | None = None
    feature_type: FeatureType | None = Field(None, alias="type")
    stale: StrictBool | None = None
    impression_data: StrictBool | None = Field(None, alias="impressionData")


class UnleashArchiveFeatureConfig(_Feature):
    """Archive a feature flag; this removes it from SDK evaluation."""
    operation: Literal["archive_feature"] = Field("archive_feature", json_schema_extra={"ui:hidden": True})


class UnleashGetFeatureEnvironmentConfig(_FeatureEnvironment):
    """Get flag configuration for an environment."""
    operation: Literal["get_feature_environment"] = Field("get_feature_environment", json_schema_extra={"ui:hidden": True})


class UnleashEnableFeatureConfig(_FeatureEnvironment):
    """Enable a flag in the selected environment."""
    operation: Literal["enable_feature"] = Field("enable_feature", json_schema_extra={"ui:hidden": True})


class UnleashDisableFeatureConfig(_FeatureEnvironment):
    """Disable a flag in the selected environment."""
    operation: Literal["disable_feature"] = Field("disable_feature", json_schema_extra={"ui:hidden": True})


class UnleashListStrategiesConfig(_FeatureEnvironment):
    """List activation strategies for a flag environment."""
    operation: Literal["list_strategies"] = Field("list_strategies", json_schema_extra={"ui:hidden": True})


class UnleashGetStrategyConfig(_Strategy):
    """Read one activation strategy configuration."""
    operation: Literal["get_strategy"] = Field("get_strategy", json_schema_extra={"ui:hidden": True})


class UnleashCreateStrategyConfig(_FeatureEnvironment, _StrategyFields):
    """Add an activation strategy to a flag environment."""
    operation: Literal["create_strategy"] = Field("create_strategy", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description="Strategy type, e.g. flexibleRollout.")


class UnleashUpdateStrategyConfig(_Strategy, _StrategyFields):
    """Update supplied strategy configuration fields."""
    operation: Literal["update_strategy"] = Field("update_strategy", json_schema_extra={"ui:hidden": True})


class UnleashDeleteStrategyConfig(_Strategy):
    """Remove an activation strategy from a flag environment."""
    operation: Literal["delete_strategy"] = Field("delete_strategy", json_schema_extra={"ui:hidden": True})


class UnleashListVariantsConfig(_FeatureEnvironment):
    """Read flag variants for an environment."""
    operation: Literal["list_variants"] = Field("list_variants", json_schema_extra={"ui:hidden": True})


class UnleashListEnvironmentsConfig(_Input):
    """List configured environments."""
    operation: Literal["list_environments"] = Field("list_environments", json_schema_extra={"ui:hidden": True})


class UnleashGetEnvironmentConfig(_Input):
    """Read an environment by name."""
    operation: Literal["get_environment"] = Field("get_environment", json_schema_extra={"ui:hidden": True})
    environment: str = Field(..., min_length=1, max_length=255, json_schema_extra=_picker("environment"))


class UnleashListSegmentsConfig(_Input):
    """List reusable targeting segments."""
    operation: Literal["list_segments"] = Field("list_segments", json_schema_extra={"ui:hidden": True})


class UnleashGetSegmentConfig(_Segment):
    """Read a reusable targeting segment."""
    operation: Literal["get_segment"] = Field("get_segment", json_schema_extra={"ui:hidden": True})


class UnleashCreateSegmentConfig(_SegmentFields):
    """Create a reusable targeting segment."""
    operation: Literal["create_segment"] = Field("create_segment", json_schema_extra={"ui:hidden": True})


class UnleashUpdateSegmentConfig(_Segment, _SegmentFields):
    """Replace a segment name and constraints."""
    operation: Literal["update_segment"] = Field("update_segment", json_schema_extra={"ui:hidden": True})


class UnleashDeleteSegmentConfig(_Segment):
    """Delete a targeting segment; fails if still referenced."""
    operation: Literal["delete_segment"] = Field("delete_segment", json_schema_extra={"ui:hidden": True})


UnleashConfig = Annotated[Union[
    UnleashListProjectsConfig,
    UnleashGetProjectConfig,
    UnleashListFeaturesConfig,
    UnleashGetFeatureConfig,
    UnleashCreateFeatureConfig,
    UnleashUpdateFeatureConfig,
    UnleashArchiveFeatureConfig,
    UnleashGetFeatureEnvironmentConfig,
    UnleashEnableFeatureConfig,
    UnleashDisableFeatureConfig,
    UnleashListStrategiesConfig,
    UnleashGetStrategyConfig,
    UnleashCreateStrategyConfig,
    UnleashUpdateStrategyConfig,
    UnleashDeleteStrategyConfig,
    UnleashListVariantsConfig,
    UnleashListEnvironmentsConfig,
    UnleashGetEnvironmentConfig,
    UnleashListSegmentsConfig,
    UnleashGetSegmentConfig,
    UnleashCreateSegmentConfig,
    UnleashUpdateSegmentConfig,
    UnleashDeleteSegmentConfig
], Field(discriminator="operation")]


class UnleashFullConfig(NodeConfig[UnleashConfig, UnleashTokenCredential]):
    pass


ROUTES = {
    "list_projects": ("GET", "/api/admin/projects"),
    "get_project": ("GET", "/api/admin/projects/{project_id}/overview"),
    "list_features": ("GET", "/api/admin/projects/{project_id}/features"),
    "get_feature": ("GET", "/api/admin/projects/{project_id}/features/{feature_name}"),
    "create_feature": ("POST", "/api/admin/projects/{project_id}/features"),
    "update_feature": ("PUT", "/api/admin/projects/{project_id}/features/{feature_name}"),
    "archive_feature": ("DELETE", "/api/admin/projects/{project_id}/features/{feature_name}"),
    "get_feature_environment": ("GET", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}"),
    "enable_feature": ("POST", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/on"),
    "disable_feature": ("POST", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/off"),
    "list_strategies": ("GET", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/strategies"),
    "get_strategy": ("GET", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/strategies/{strategy_id}"),
    "create_strategy": ("POST", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/strategies"),
    "update_strategy": ("PUT", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/strategies/{strategy_id}"),
    "delete_strategy": ("DELETE", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/strategies/{strategy_id}"),
    "list_variants": ("GET", "/api/admin/projects/{project_id}/features/{feature_name}/environments/{environment}/variants"),
    "list_environments": ("GET", "/api/admin/environments"),
    "get_environment": ("GET", "/api/admin/environments/{environment}"),
    "list_segments": ("GET", "/api/admin/segments"),
    "get_segment": ("GET", "/api/admin/segments/{segment_id}"),
    "create_segment": ("POST", "/api/admin/segments"),
    "update_segment": ("PUT", "/api/admin/segments/{segment_id}"),
    "delete_segment": ("DELETE", "/api/admin/segments/{segment_id}"),
}

PATH_FIELDS = {"project_id", "feature_name", "environment", "strategy_id", "segment_id"}


class UnleashNode(WorkflowNode):
    integration_type = "automation-unleash"
    connection_evidence = ConnectionEvidence(field="project_id", operation="list_projects", noun="Unleash projects")

    @classmethod
    def get_config_model(cls):
        return UnleashFullConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        from nodes.core.registry import NodeFactory
        if page_token is not None:
            raise ValueError("These Unleash endpoints do not paginate")
        context = context or {}
        choices = {
            "project_id": ("list_projects", {}, "projects", "id"),
            "feature_name": ("list_features", {"project_id": context.get("project_id")}, "features", "name"),
            "environment": ("list_environments", {}, "environments", "name"),
            "segment_id": ("list_segments", {}, "segments", "id"),
        }
        if field_name not in choices:
            raise ValueError("Unknown Unleash choice field")
        operation, arguments, key, identifier = choices[field_name]
        node = NodeFactory.create_node(node_id="unleash-options", node_type=cls.integration_type,
            node_data={"config": {"operation": operation, **arguments}, "credentials": credential_data})
        result = await node.execute({})
        if result["status"] != "success":
            raise ValueError(result["error"])
        body = result["data"]
        if not isinstance(body, dict) or not isinstance(body.get(key), list):
            raise ValueError("Unleash returned an invalid choice list")
        options = []
        for item in body[key]:
            if not isinstance(item, dict) or not isinstance(item.get(identifier), (str, int)):
                raise ValueError("Unleash returned an invalid choice")
            label = item.get("name") or str(item[identifier])
            if not isinstance(label, str):
                raise ValueError("Unleash returned an invalid choice name")
            if not search or search.casefold() in label.casefold():
                options.append({"value": str(item[identifier]), "label": label})
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        if not isinstance(self.config, UnleashFullConfig) or not self.config.credentials:
            raise ValueError("Connect an Unleash access token")
        config, credential = self.config.config, self.config.credentials
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, by_alias=False)
        # Each path component is encoded independently; no input can add a route or query.
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items() if k in PATH_FIELDS})
        params = {}
        body = None
        if config.operation == "list_projects" and config.archived is not None:
            params["archived"] = "true" if config.archived else "false"
        if config.operation in {"create_feature", "update_feature", "create_strategy", "update_strategy", "create_segment", "update_segment"}:
            body = config.model_dump(exclude_none=True, by_alias=True, exclude=PATH_FIELDS | {"operation"})
            if not body:
                raise ValueError("Supply at least one field to update")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.instance_url + path,
                headers={"Authorization": credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for connection evidence, without reflecting the token.
            error = response.text.replace(credential.api_token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": error or "Unleash rejected the request"}
        data = response.json() if response.content else None
        return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": data}
