"""Statsig Console API operations pinned to the published 20240601 contract.

A Console API key is distinct from client/server SDK keys. Each operation makes
one request; list operations return one page and preserve provider pagination.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://statsigapi.net/console/v1"
CREDENTIAL_TYPE = "statsig_api_key"


class StatsigAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Statsig Console API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.statsig.com/api_keys",
            "x-credential-instructions": "Create a Console API key in Statsig Project Settings > API Keys. Paste the key here, without a header prefix. Client and server SDK keys do not work with the Console API. Grant read/write access to the resources your workflow uses.",
        })
    credential_type: Literal["statsig_api_key"] = Field("statsig_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Console API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="Console API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the Console API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class _List(_Input):
    limit: int = Field(100, ge=1, le=100, title="Results Per Page")
    page: int = Field(1, ge=1, title="Page Number", description="Read one page. Increment to fetch subsequent pages; provider pagination is returned unchanged.")


# Statsig's own MCP server: agents get its tools through a person's Statsig sign-in.
StatsigMcpCredential = mcp_credential("statsig", "https://api.statsig.com/v3/mcp", app="Statsig")
StatsigCredential = Union[StatsigAPIKeyCredential, StatsigMcpCredential]


def _picker(field):
    return {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True}}


class _Resource(_Input):
    @field_validator("gate_id", "config_id", "experiment_id", "segment_id", "tag_id", mode="before", check_fields=False)
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id"):
            if not isinstance(value, str) or not value or len(value) > 256 or value in {".", ".."} or re.search(r"[/\\?#\x00-\x20\x7f]", value):
                raise ValueError("Use a single Statsig resource ID")
        return value


class _Gate(_Resource):
    gate_id: str = Field(..., title="Gate", json_schema_extra=_picker("gate_id"))


class _Config(_Resource):
    config_id: str = Field(..., title="Dynamic Config", json_schema_extra=_picker("config_id"))


class _Experiment(_Resource):
    experiment_id: str = Field(..., title="Experiment", json_schema_extra=_picker("experiment_id"))


class _Segment(_Resource):
    segment_id: str = Field(..., title="Segment", json_schema_extra=_picker("segment_id"))


class _Tag(_Resource):
    tag_id: str = Field(..., title="Tag", json_schema_extra=_picker("tag_id"))


class Condition(_Input):
    type: Literal['app_version', 'browser_name', 'browser_version', 'country', 'custom_field', 'email', 'environment_tier', 'fails_gate', 'fails_segment', 'ip_address', 'locale', 'os_name', 'os_version', 'passes_gate', 'passes_segment', 'public', 'time', 'unit_id', 'user_id', 'user_agent', 'url', 'javascript', 'device_model', 'target_app', 'experiment_group']
    operator: Literal['any', 'none', 'any_case_sensitive', 'none_case_sensitive', 'str_contains_any', 'str_contains_none', 'gt', 'lt', 'lte', 'gte', 'version_gt', 'version_lt', 'version_gte', 'version_lte', 'version_eq', 'after', 'before', 'on', 'is_null', 'is_not_null', 'str_matches', 'encoded_any', 'array_contains_any', 'array_contains_none', 'array_contains_all', 'not_array_contains_all'] | None = None
    targetValue: list[str] | list[float] | str | float | None = None
    field: str | None = None
    customID: str | None = None


class GateRule(_Input):
    name: str
    passPercentage: float = Field(..., ge=0, le=100, multiple_of=0.01)
    conditions: list[Condition]
    environments: list[str] | None = None
    id: str | None = None


class ConfigRule(GateRule):
    returnValue: dict[str, Any] = Field(..., title="Return Value")


class _GateFields(_Input):
    name: str | None = Field(None, min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_\-. ]*$")
    description: str | None = Field(None, max_length=1000)
    is_enabled: bool | None = Field(None, alias="isEnabled", title="Enabled")
    rules: list[GateRule] | None = Field(None, title="Rules", description="When supplied, replaces the complete rules array. An empty array removes all rules.")
    tags: list[str] | None = None
    id_type: str | None = Field(None, alias="idType", title="ID Type")


class _ConfigFields(_Input):
    name: str | None = Field(None, min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_\-. ]*$")
    description: str | None = Field(None, max_length=1000)
    is_enabled: bool | None = Field(None, alias="isEnabled", title="Enabled")
    default_value: dict[str, Any] | None = Field(None, alias="defaultValue", title="Default Value")
    rules: list[ConfigRule] | None = Field(None, title="Rules", description="When supplied, replaces the complete rules array.")
    tags: list[str] | None = None
    id_type: str | None = Field(None, alias="idType", title="ID Type")


class _TagFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)
    is_core: bool | None = Field(None, alias="isCore", title="Core Tag")


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})


class ListGates(_List):
    operation: Literal["list_gates"] = Field("list_gates", title="List Gates", json_schema_extra={"ui:hidden": True})


class GetGate(_Gate):
    operation: Literal["get_gate"] = Field("get_gate", title="Get Gate", json_schema_extra={"ui:hidden": True})


class CreateGate(_GateFields):
    operation: Literal["create_gate"] = Field("create_gate", title="Create Gate", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_\-. ]*$")


class UpdateGate(_Gate, _GateFields):
    operation: Literal["update_gate"] = Field("update_gate", title="Update Gate", description='Partially update a gate. Supplied rules replace all rules; enabled changes affect evaluations.', json_schema_extra={"ui:hidden": True})


class DeleteGate(_Gate):
    operation: Literal["delete_gate"] = Field("delete_gate", title="Delete Gate", description='Permanently delete this gate.', json_schema_extra={"ui:hidden": True})


class EnableGate(_Gate):
    operation: Literal["enable_gate"] = Field("enable_gate", title="Enable Gate", description='Enable this gate for SDK evaluations.', json_schema_extra={"ui:hidden": True})


class DisableGate(_Gate):
    operation: Literal["disable_gate"] = Field("disable_gate", title="Disable Gate", description='Disable this gate for SDK evaluations.', json_schema_extra={"ui:hidden": True})


class GetGateRules(_Gate):
    operation: Literal["get_gate_rules"] = Field("get_gate_rules", title="Get Gate Rules", json_schema_extra={"ui:hidden": True})


class ListDynamicConfigs(_List):
    operation: Literal["list_dynamic_configs"] = Field("list_dynamic_configs", title="List Dynamic Configs", json_schema_extra={"ui:hidden": True})


class GetDynamicConfig(_Config):
    operation: Literal["get_dynamic_config"] = Field("get_dynamic_config", title="Get Dynamic Config", json_schema_extra={"ui:hidden": True})


class CreateDynamicConfig(_ConfigFields):
    operation: Literal["create_dynamic_config"] = Field("create_dynamic_config", title="Create Dynamic Config", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_\-. ]*$")


class UpdateDynamicConfig(_Config, _ConfigFields):
    operation: Literal["update_dynamic_config"] = Field("update_dynamic_config", title="Update Dynamic Config", description='Partially update this config. Supplied defaultValue and rules affect SDK evaluations.', json_schema_extra={"ui:hidden": True})


class DeleteDynamicConfig(_Config):
    operation: Literal["delete_dynamic_config"] = Field("delete_dynamic_config", title="Delete Dynamic Config", description='Permanently delete this dynamic config.', json_schema_extra={"ui:hidden": True})


class ListExperiments(_List):
    operation: Literal["list_experiments"] = Field("list_experiments", title="List Experiments", json_schema_extra={"ui:hidden": True})


class GetExperiment(_Experiment):
    operation: Literal["get_experiment"] = Field("get_experiment", title="Get Experiment", json_schema_extra={"ui:hidden": True})


class ListSegments(_List):
    operation: Literal["list_segments"] = Field("list_segments", title="List Segments", json_schema_extra={"ui:hidden": True})


class GetSegment(_Segment):
    operation: Literal["get_segment"] = Field("get_segment", title="Get Segment", json_schema_extra={"ui:hidden": True})


class ListTags(_List):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})


class GetTag(_Tag):
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True})


class CreateTag(_TagFields):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., max_length=1000)


class UpdateTag(_Tag, _TagFields):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True})


class DeleteTag(_Tag):
    operation: Literal["delete_tag"] = Field("delete_tag", title="Delete Tag", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetProject, ListGates, GetGate, CreateGate, UpdateGate, DeleteGate, EnableGate, DisableGate, GetGateRules, ListDynamicConfigs, GetDynamicConfig, CreateDynamicConfig, UpdateDynamicConfig, DeleteDynamicConfig, ListExperiments, GetExperiment, ListSegments, GetSegment, ListTags, GetTag, CreateTag, UpdateTag, DeleteTag], Field(discriminator="operation")]


class StatsigNodeConfig(NodeConfig[Operation, StatsigCredential]):
    pass


# Each operation maps to exactly one method and published Console API route.
ROUTES = {
    "get_project": ("GET", "/project", None),
    "list_gates": ('GET', '/gates', None),
    "get_gate": ('GET', '/gates/{id}', 'gate_id'),
    "create_gate": ('POST', '/gates', None),
    "update_gate": ('PATCH', '/gates/{id}', 'gate_id'),
    "delete_gate": ('DELETE', '/gates/{id}', 'gate_id'),
    "list_dynamic_configs": ('GET', '/dynamic_configs', None),
    "get_dynamic_config": ('GET', '/dynamic_configs/{id}', 'config_id'),
    "create_dynamic_config": ('POST', '/dynamic_configs', None),
    "update_dynamic_config": ('PATCH', '/dynamic_configs/{id}', 'config_id'),
    "delete_dynamic_config": ('DELETE', '/dynamic_configs/{id}', 'config_id'),
    "list_experiments": ('GET', '/experiments', None),
    "get_experiment": ('GET', '/experiments/{id}', 'experiment_id'),
    "list_segments": ('GET', '/segments', None),
    "get_segment": ('GET', '/segments/{id}', 'segment_id'),
    "list_tags": ('GET', '/tags', None),
    "get_tag": ('GET', '/tags/{id}', 'tag_id'),
    "create_tag": ('POST', '/tags', None),
    "update_tag": ('PATCH', '/tags/{id}', 'tag_id'),
    "delete_tag": ('DELETE', '/tags/{id}', 'tag_id'),
    "enable_gate": ('PUT', '/gates/{id}/enable', 'gate_id'),
    "disable_gate": ('PUT', '/gates/{id}/disable', 'gate_id'),
    "get_gate_rules": ('GET', '/gates/{id}/rules', 'gate_id'),
}
PICKERS = {"gate_id": "gates", "config_id": "dynamic_configs", "experiment_id": "experiments", "segment_id": "segments", "tag_id": "tags"}


class StatsigNode(WorkflowNode):
    integration_type = "automation-statsig"
    credential_provider_labels = {"statsig": "Statsig Account"}
    connection_evidence = ConnectionEvidence(noun="Statsig gates", field="gate_id", identity_operation="get_project")

    @classmethod
    def get_config_model(cls):
        return StatsigNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in PICKERS:
            raise ValueError("Unknown Statsig resource field")
        page = int(page_token) if page_token is not None else 1
        if page < 1:
            raise ValueError("Use a positive page number")
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="statsig-options", node_type=cls.integration_type,
            node_data={"config": {"operation": "list_" + PICKERS[field_name], "page": page, "limit": 100},
                "credentials": credential_data})
        result = await node.execute({})
        rows = result["data"]
        options = [{"value": row["id"], "label": row.get("name") or row["id"]} for row in rows]
        if search:
            options = [x for x in options if search.casefold() in x["label"].casefold() or search.casefold() in x["value"].casefold()]
        # Pagination links are data only; never follow a provider-supplied URL.
        pagination = result.get("pagination") or {}
        more = bool(pagination.get("nextPage"))
        return {"options": options, "next_page_token": str(page + 1) if more else None}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("A Statsig Console API key is required")
        config = self.config.config
        method, route, field = ROUTES[config.operation]
        if field:
            route = route.replace("{id}", quote(getattr(config, field), safe=""))
        params = {"limit": config.limit, "page": config.page} if isinstance(config, _List) else None
        body = None
        if method in {"POST", "PATCH"}:
            body = config.model_dump(by_alias=True, exclude_none=True, exclude={"operation", field} if field else {"operation"})
            if not body:
                raise ValueError("Supply at least one field to update")
        # No retries: a failed write may already have reached Statsig.
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, params=params, json=body,
                    headers={"STATSIG-API-KEY": self.config.credentials.api_key,
                        "STATSIG-API-VERSION": "20240601", "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Statsig request did not complete; check the resource before retrying a write") from None
        if response.status_code >= 300:
            # Provider errors can echo the supplied key. Redact it before surfacing.
            try:
                message = response.json().get("message", "Statsig rejected the request")
            except (ValueError, AttributeError):
                message = "Statsig rejected the request"
            message = str(message).replace(self.config.credentials.api_key, "[redacted]")[:1000]
            raise ValueError(f"Statsig HTTP {response.status_code}: {message}")
        if not response.content and method == "DELETE":
            return {"status": "success", "operation": config.operation}
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Statsig returned a non-JSON response") from None
        if not isinstance(result, dict):
            raise ValueError("Statsig returned an invalid response object")
        if method != "DELETE":
            data = result.get("data")
            # The gate-rules schema says array, while the published example
            # wraps rules in an object. Preserve both documented shapes.
            expected = (dict, list) if config.operation == "get_gate_rules" else list if isinstance(config, _List) else dict
            if not isinstance(data, expected):
                raise ValueError("Statsig returned an invalid data envelope")
            if isinstance(config, _List) and any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data):
                raise ValueError("Statsig returned invalid resource rows")
            if config.operation == "get_project" and not isinstance(data.get("id"), str):
                raise ValueError("Statsig returned an invalid project identity")
        return {**result, "status": "success", "operation": config.operation}
