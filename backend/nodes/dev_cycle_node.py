"""DevCycle Management API operations, pinned to the provider's OpenAPI 1.0.0."""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.devcycle.com"
CREDENTIAL = "dev_cycle_access_token"


def _identifier(value: str) -> str:
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise ValueError("Use a DevCycle key or ID, without a URL or path")
    return value


Identifier = Annotated[str, AfterValidator(_identifier)]
Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-_.]+$")]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Description = Annotated[str, Field(max_length=1000)]
Color = Annotated[str, Field(max_length=9, pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")]
FeatureType = Literal["release", "experiment", "permission", "ops"]
VariableType = Literal["String", "Boolean", "Number", "JSON"]
EnvironmentType = Literal["development", "staging", "production", "disaster_recovery"]


class DevCycleAccessToken(BaseModel):
    model_config = ConfigDict(title="DevCycle Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.devcycle.com/management-api/",
        "x-credential-instructions": "Paste a DevCycle Management API access token without the Bearer prefix. Obtain it using the client credentials in Organization Settings and the documented token endpoint. SDK keys are not management tokens. NoClick does not refresh this token; replace it when it expires. Project access proves this token works, not every write permission.",
    })
    credential_type: Literal["dev_cycle_access_token"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=16384, repr=False,
                              json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Read one page; increment to continue.")
    perPage: int = Field(100, ge=1, le=1000, title="Per Page")
    sortBy: Literal["createdAt", "updatedAt", "name", "key", "propertyKey"] = Field("createdAt", title="Sort By")
    sortOrder: Literal["asc", "desc"] = Field("desc", title="Sort Order")
    search: str | None = Field(None, min_length=3, title="Search")


class _Project(_Input):
    project: Identifier = Field(..., title="Project Key or ID")


class _ProjectPage(_Page, _Project):
    pass


class _Environment(_Project):
    environment: Identifier = Field(..., title="Environment Key or ID")


class _Feature(_Project):
    feature: Identifier = Field(..., title="Feature Key or ID")


class _Variable(_Project):
    variable: Identifier = Field(..., title="Variable Key or ID")


class _Audience(_Project):
    audience: Identifier = Field(..., title="Audience Key or ID")


class ListProjects(_Page):
    operation: Literal["list_projects"] = "list_projects"
    createdBy: str | None = None


class GetProject(_Project):
    operation: Literal["get_project"] = "get_project"


class CreateProject(_Input):
    operation: Literal["create_project"] = "create_project"
    name: Name
    key: Key
    description: Description | None = None
    color: Color | None = None


class UpdateProject(_Project):
    operation: Literal["update_project"] = "update_project"
    name: Name | None = None
    key: Key | None = None
    description: Description | None = None
    color: Color | None = None


class DeleteProject(_Project):
    """Permanently delete the project and its resources."""
    operation: Literal["delete_project"] = "delete_project"


class ListEnvironments(_ProjectPage):
    operation: Literal["list_environments"] = "list_environments"
    createdBy: str | None = None


class GetEnvironment(_Environment):
    operation: Literal["get_environment"] = "get_environment"


class CreateEnvironment(_Project):
    operation: Literal["create_environment"] = "create_environment"
    name: Name
    key: Key
    type: EnvironmentType
    description: Description | None = None
    color: Color | None = None


class UpdateEnvironment(_Environment):
    operation: Literal["update_environment"] = "update_environment"
    name: Name | None = None
    key: Key | None = None
    type: EnvironmentType | None = None
    description: Description | None = None
    color: Color | None = None


class DeleteEnvironment(_Environment):
    """Permanently delete this environment."""
    operation: Literal["delete_environment"] = "delete_environment"


class ListFeatures(_ProjectPage):
    operation: Literal["list_features"] = "list_features"
    createdBy: str | None = None
    type: FeatureType | None = None
    status: Literal["active", "complete", "archived"] | None = None
    staleness: Literal["all", "unused", "released", "unmodified", "notStale"] | None = None
    includeLatestUpdate: bool | None = None


class GetFeature(_Feature):
    operation: Literal["get_feature"] = "get_feature"


class VariableDefinition(_Input):
    key: Key
    type: VariableType
    name: Name | None = None
    description: Description | None = None
    tags: list[str] | None = None


class VariationDefinition(_Input):
    key: Key
    name: Name
    variables: dict[str, JsonValue] | None = None

    @field_validator("variables")
    @classmethod
    def nonnull_values(cls, value):
        if value is not None and any(item is None for item in value.values()):
            raise ValueError("Variation values must be strings, numbers, booleans, arrays or objects")
        return value


class FeatureConfiguration(_Input):
    status: Literal["active", "inactive"]
    # Target rules are intentionally excluded; this node creates untargeted flags.
    targets: list[dict] = Field(default_factory=list, max_length=0)


class CreateFeature(_Project):
    """Create a feature with explicit environment states and no targeting rules."""
    operation: Literal["create_feature"] = "create_feature"
    key: Key
    name: Name
    configurations: dict[Identifier, FeatureConfiguration] = Field(..., min_length=1,
        description='Map environment keys to status and empty targets, e.g. {"development":{"status":"inactive","targets":[]}}.')
    description: Description | None = None
    type: FeatureType | None = None
    tags: list[str] | None = None
    variables: list[VariableDefinition] | None = None
    variations: list[VariationDefinition] | None = None
    controlVariation: Identifier | None = None


class UpdateFeature(_Feature):
    """Update feature metadata without changing targeting rules."""
    operation: Literal["update_feature"] = "update_feature"
    name: Name | None = None
    key: Key | None = None
    description: Description | None = None
    type: FeatureType | None = None
    tags: list[str] | None = None


class UpdateFeatureStatus(_Feature):
    """Change lifecycle status; complete serves the specified static variation."""
    operation: Literal["update_feature_status"] = "update_feature_status"
    status: Literal["active", "complete", "archived"]
    staticVariation: Identifier | None = None


class GetStaticConfiguration(_Feature):
    operation: Literal["get_static_configuration"] = "get_static_configuration"


class UpdateStaticConfiguration(_Feature):
    """Update static variable values and environment states."""
    operation: Literal["update_static_configuration"] = "update_static_configuration"
    variables: dict[str, JsonValue] | None = Field(None, description="Map variable keys to their static JSON values.")
    environments: dict[str, JsonValue] | None = Field(None, description="Environment configuration object as documented by DevCycle.")


class ListVariables(_ProjectPage):
    operation: Literal["list_variables"] = "list_variables"
    feature: Identifier | None = None
    type: VariableType | None = None
    status: Literal["active", "archived"] | None = None


class GetVariable(_Variable):
    operation: Literal["get_variable"] = "get_variable"


class CreateVariable(_Project, VariableDefinition):
    operation: Literal["create_variable"] = "create_variable"
    feature_id: Identifier | None = Field(None, description="Optional feature ID sent as _feature.")


class UpdateVariable(_Variable):
    operation: Literal["update_variable"] = "update_variable"
    key: Key | None = None
    name: Name | None = None
    description: Description | None = None
    type: VariableType | None = None
    persistent: bool | None = None
    tags: list[str] | None = None


class DeleteVariable(_Variable):
    """Permanently delete this variable."""
    operation: Literal["delete_variable"] = "delete_variable"


class UpdateVariableStatus(_Variable):
    operation: Literal["update_variable_status"] = "update_variable_status"
    status: Literal["active", "archived"]


class ListAudiences(_ProjectPage):
    operation: Literal["list_audiences"] = "list_audiences"
    createdBy: str | None = None
    includeUsage: bool | None = None


class GetAudience(_Audience):
    operation: Literal["get_audience"] = "get_audience"


# DevCycle's own MCP server: agents get its tools through a person's DevCycle sign-in.
DevCycleMcpCredential = mcp_credential("dev_cycle", "https://mcp.devcycle.com/mcp", app="DevCycle")
DevCycleCredential = Union[DevCycleAccessToken, DevCycleMcpCredential]


DevCycleOperation = Annotated[Union[
    ListProjects, GetProject, CreateProject, UpdateProject, DeleteProject,
    ListEnvironments, GetEnvironment, CreateEnvironment, UpdateEnvironment, DeleteEnvironment,
    ListFeatures, GetFeature, CreateFeature, UpdateFeature, UpdateFeatureStatus,
    GetStaticConfiguration, UpdateStaticConfiguration, ListVariables, GetVariable,
    CreateVariable, UpdateVariable, DeleteVariable, UpdateVariableStatus, ListAudiences, GetAudience,
], Field(discriminator="operation")]


class DevCycleConfig(NodeConfig[DevCycleOperation, DevCycleCredential]):
    pass


PAGE = ("page", "perPage", "sortBy", "sortOrder", "search")
# Each tuple names exactly one operation in the published contract.
ROUTES = {
    "list_projects": ("GET", "/v1/projects", PAGE + ("createdBy",)),
    "get_project": ("GET", "/v1/projects/{project}", ()),
    "create_project": ("POST", "/v1/projects", ()),
    "update_project": ("PATCH", "/v1/projects/{project}", ()),
    "delete_project": ("DELETE", "/v1/projects/{project}", ()),
    "list_environments": ("GET", "/v1/projects/{project}/environments", PAGE + ("createdBy",)),
    "get_environment": ("GET", "/v1/projects/{project}/environments/{environment}", ()),
    "create_environment": ("POST", "/v1/projects/{project}/environments", ()),
    "update_environment": ("PATCH", "/v1/projects/{project}/environments/{environment}", ()),
    "delete_environment": ("DELETE", "/v1/projects/{project}/environments/{environment}", ()),
    "list_features": ("GET", "/v2/projects/{project}/features", PAGE + ("createdBy", "type", "status", "staleness", "includeLatestUpdate")),
    "get_feature": ("GET", "/v2/projects/{project}/features/{feature}", ()),
    "create_feature": ("POST", "/v2/projects/{project}/features", ()),
    "update_feature": ("PATCH", "/v2/projects/{project}/features/{feature}", ()),
    "update_feature_status": ("PATCH", "/v2/projects/{project}/features/{feature}/status", ()),
    "get_static_configuration": ("GET", "/v2/projects/{project}/features/{feature}/static-configuration", ()),
    "update_static_configuration": ("PATCH", "/v2/projects/{project}/features/{feature}/static-configuration", ()),
    "list_variables": ("GET", "/v1/projects/{project}/variables", PAGE + ("feature", "type", "status")),
    "get_variable": ("GET", "/v1/projects/{project}/variables/{variable}", ()),
    "create_variable": ("POST", "/v1/projects/{project}/variables", ()),
    "update_variable": ("PATCH", "/v1/projects/{project}/variables/{variable}", ()),
    "delete_variable": ("DELETE", "/v1/projects/{project}/variables/{variable}", ()),
    "update_variable_status": ("PATCH", "/v1/projects/{project}/variables/{variable}/status", ()),
    "list_audiences": ("GET", "/v1/projects/{project}/audiences", PAGE + ("createdBy", "includeUsage")),
    "get_audience": ("GET", "/v1/projects/{project}/audiences/{audience}", ()),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class _ProviderError(ValueError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f"DevCycle HTTP {status}: {detail}")


class DevCycleNode(WorkflowNode):
    integration_type = "automation-dev-cycle"
    credential_provider_labels = {"dev_cycle": "DevCycle Account"}
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "key", "_id"))

    @classmethod
    def get_config_model(cls):
        return DevCycleConfig

    @classmethod
    async def _request(cls, credential, operation):
        method, route, query_fields = ROUTES[operation.operation]
        values = operation.model_dump(exclude_none=True, exclude={"operation"})
        path = route.format(**{name: quote(values.pop(name), safe="") for name in re.findall(r"{(\w+)}", route)})
        params = {name: values.pop(name) for name in query_fields if name in values}
        params = {name: str(value).lower() if isinstance(value, bool) else value for name, value in params.items()}
        if "feature_id" in values:
            values["_feature"] = values.pop("feature_id")
        if method == "PATCH" and not values:
            raise ValueError("Provide at least one field to update")
        kwargs = {"headers": {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, "params": params}
        if method in {"POST", "PATCH"}:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, **kwargs)
        except httpx.RequestError:
            raise ValueError("DevCycle request did not complete; inspect the account before retrying a write") from None
        if len(response.content) > 5_000_000:
            raise ValueError("DevCycle response exceeded the supported size")
        if not 200 <= response.status_code < 300:
            detail = _redact(response.text, credential.access_token)[:2000]
            raise _ProviderError(response.status_code, detail)
        if method == "DELETE":
            return {"deleted": True}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("DevCycle did not return JSON; inspect the account before retrying a write") from None
        if isinstance(payload, dict) and ("error" in payload or "errors" in payload):
            raise _ProviderError(response.status_code, _redact(json.dumps(payload), credential.access_token)[:2000])
        if operation.operation.startswith("list_"):
            if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                raise ValueError("DevCycle returned an unexpected resource list")
            return {"items": _redact(payload, credential.access_token), "page": operation.page, "per_page": operation.perPage}
        if not isinstance(payload, dict):
            raise ValueError("DevCycle returned an unexpected resource object")
        return {"data": _redact(payload, credential.access_token)}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = DevCycleAccessToken.model_validate(credential_data)
        try:
            await cls._request(credential, ListProjects())
        except _ProviderError as exc:
            return {"valid": False if exc.status in {401, 403} else None, "message": str(exc)}
        except (ValueError, httpx.HTTPError):
            return {"valid": None, "message": "DevCycle project access could not be verified"}
        return {"valid": True, "message": "DevCycle accepted the token for listing projects"}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a DevCycle Management API access token")
        result = await self._request(self.config.credentials, self.config.config)
        output = {"status": "success", "operation": self.config.config.operation, **result}
        await self.emit(output)
        return output
