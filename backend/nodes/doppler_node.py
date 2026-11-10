"""Doppler secrets management through the documented v3 REST API.

Only the explicit read operations return secret values. Mutation responses are
reduced to names/status so workflow history never copies a newly written value.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://api.doppler.com/v3"


class DopplerTokenCredential(BaseModel):
    """Personal, service-account, or config-scoped service token."""

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://dashboard.doppler.com/workplace/tokens",
    })
    token: str = Field(..., title="Doppler API token", json_schema_extra={"ui:widget": "password"},
                       description="Personal or service-account token for workspace actions; a service token is limited to its config.")


def _op(name: str, category: str, label: str):
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": label, "x-is-trigger": False,
    })


def _picker(name: str, label: str, depends_on: Optional[str] = None):
    options = {"field_name": name, "searchable": True, "allow_custom": True,
               "placeholder": f"Select {label.lower()}…", "custom_placeholder": f"Or enter {label.lower()}"}
    if depends_on:
        options["depends_on"] = depends_on
    return Field(..., title=label, json_schema_extra={"x-dynamic-options": options})


class GetTokenInfo(BaseModel):
    operation: Literal["get_token_info"] = _op("get_token_info", "Account", "Get Token Info")


class ListProjects(BaseModel):
    operation: Literal["list_projects"] = _op("list_projects", "Projects", "List Projects")
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


class GetProject(BaseModel):
    operation: Literal["get_project"] = _op("get_project", "Projects", "Get Project")
    project: str = _picker("project", "Project")


class CreateProject(BaseModel):
    operation: Literal["create_project"] = _op("create_project", "Projects", "Create Project")
    name: str = Field(..., description="Project slug, typically lowercase with dashes")
    description: Optional[str] = None


class ListEnvironments(BaseModel):
    operation: Literal["list_environments"] = _op("list_environments", "Environments", "List Environments")
    project: str = _picker("project", "Project")


class CreateEnvironment(BaseModel):
    operation: Literal["create_environment"] = _op("create_environment", "Environments", "Create Environment")
    project: str = _picker("project", "Project")
    name: str
    slug: str
    personal_configs: bool = False


class ListConfigs(BaseModel):
    operation: Literal["list_configs"] = _op("list_configs", "Configs", "List Configs")
    project: str = _picker("project", "Project")
    environment: Optional[str] = None
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


class GetConfig(BaseModel):
    operation: Literal["get_config"] = _op("get_config", "Configs", "Get Config")
    project: str = _picker("project", "Project")
    config: str = _picker("config", "Config", "project")


class CreateConfig(BaseModel):
    operation: Literal["create_config"] = _op("create_config", "Configs", "Create Branch Config")
    project: str = _picker("project", "Project")
    environment: str
    name: str


class ListSecretNames(BaseModel):
    operation: Literal["list_secret_names"] = _op("list_secret_names", "Secrets", "List Secret Names")
    project: str = Field(..., description="Project slug; service tokens can use their bound project")
    config: str = Field(..., description="Config slug; service tokens can use their bound config")


class ListSecrets(BaseModel):
    operation: Literal["list_secrets"] = _op("list_secrets", "Secrets", "List Secrets and Values")
    project: str
    config: str
    names: Optional[str] = Field(None, description="Optional comma-separated names; blank reads every secret")


class GetSecret(BaseModel):
    operation: Literal["get_secret"] = _op("get_secret", "Secrets", "Get Secret")
    project: str
    config: str
    name: str


class DownloadSecrets(BaseModel):
    operation: Literal["download_secrets"] = _op("download_secrets", "Secrets", "Download Secrets as JSON")
    project: Optional[str] = Field(None, description="Optional for a config-scoped service token")
    config: Optional[str] = Field(None, description="Optional for a config-scoped service token")
    names: Optional[str] = Field(None, description="Optional comma-separated secret names")


class SetSecrets(BaseModel):
    operation: Literal["set_secrets"] = _op("set_secrets", "Secrets", "Create or Update Secrets")
    project: str
    config: str
    secrets_json: str = Field(..., title="Secrets (JSON object)",
                              description='Example: {"API_KEY":"value"}. Values are stored in Doppler.',
                              json_schema_extra={"ui:widget": "textarea"})

    @field_validator("secrets_json")
    @classmethod
    def validate_secrets(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Secrets must be valid JSON") from exc
        if not isinstance(parsed, dict) or not parsed or not all(
            isinstance(k, str) and k and isinstance(v, str) for k, v in parsed.items()
        ):
            raise ValueError("Secrets must be a non-empty object of string names and values")
        return value


class DeleteSecret(BaseModel):
    operation: Literal["delete_secret"] = _op("delete_secret", "Secrets", "Delete Secret")
    project: str
    config: str
    name: str


DopplerOperation = Annotated[Union[
    GetTokenInfo, ListProjects, GetProject, CreateProject,
    ListEnvironments, CreateEnvironment, ListConfigs, GetConfig, CreateConfig,
    ListSecretNames, ListSecrets, GetSecret, DownloadSecrets, SetSecrets, DeleteSecret,
], Discriminator("operation")]


class DopplerNodeConfig(NodeConfig[DopplerOperation, DopplerTokenCredential]):
    pass


class DopplerNode(WorkflowNode):
    """Operate on Doppler projects, configs, environments and secrets."""
    integration_type = "automation-doppler"

    connection_evidence = ConnectionEvidence(
        identity_operation="get_token_info", noun="Doppler token", proves="reachability",
    )
    edit_examples = [
        "List secret names in my development config",
        "Get an API key from Doppler and pass it to the next node",
        "Update two secrets in a staging config",
    ]

    @classmethod
    def get_config_model(cls):
        return DopplerNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None):
        token = credential_data.get("token")
        if not token:
            return []
        if field_name == "project":
            result = await cls._request(token, "GET", "/projects", params={"per_page": 100}, action="list_projects")
            rows = result.get("data", {}).get("projects", []) if result["status"] == "success" else []
        elif field_name == "config" and (context or {}).get("project"):
            result = await cls._request(token, "GET", "/configs",
                                        params={"project": context["project"], "per_page": 100}, action="list_configs")
            rows = result.get("data", {}).get("configs", []) if result["status"] == "success" else []
        else:
            return []
        return [{"value": item["name"], "label": item["name"]}
                for item in rows if isinstance(item, dict) and item.get("name")]

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None, action: str,
                       redact_response: bool = False) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, f"{API_BASE}{path}",
                                                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                                                params={k: v for k, v in (params or {}).items() if v is not None and v != ""},
                                                json=body)
            elapsed = round((time.monotonic() - start) * 1000, 2)
            if response.status_code >= 400:
                # Doppler errors may echo submitted secret material. Do not persist them.
                return {"status": "error", "action": action, "status_code": response.status_code,
                        "error": f"Doppler returned HTTP {response.status_code}", "timing_ms": {"api_request": elapsed}}
            try:
                data = {"success": True} if not response.content else response.json()
            except ValueError:
                # An upstream HTML/text response can contain request details.
                return {"status": "error", "action": action, "status_code": response.status_code,
                        "error": "Doppler returned a non-JSON response", "timing_ms": {"api_request": elapsed}}
            if redact_response:
                data = {"success": True}
            return {"status": "success", "action": action, "status_code": response.status_code,
                    "data": data, "timing_ms": {"api_request": elapsed}}
        except httpx.RequestError:
            return {"status": "error", "action": action, "status_code": 503,
                    "error": "Doppler request failed", "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, DopplerNodeConfig) or not self.config.credentials:
            raise ValueError("Doppler token credential is required")
        cfg = self.config.config
        op = cfg.operation
        token = self.config.credentials.token
        if isinstance(cfg, GetTokenInfo):
            return await self._request(token, "GET", "/me", action=op)
        if isinstance(cfg, ListProjects):
            return await self._request(token, "GET", "/projects", params={"page": cfg.page, "per_page": cfg.per_page}, action=op)
        if isinstance(cfg, GetProject):
            return await self._request(token, "GET", "/projects/project", params={"project": cfg.project}, action=op)
        if isinstance(cfg, CreateProject):
            return await self._request(token, "POST", "/projects",
                                       body=cfg.model_dump(exclude={"operation"}, exclude_none=True), action=op)
        if isinstance(cfg, ListEnvironments):
            return await self._request(token, "GET", "/environments", params={"project": cfg.project}, action=op)
        if isinstance(cfg, CreateEnvironment):
            return await self._request(token, "POST", "/environments", params={"project": cfg.project},
                                       body={"name": cfg.name, "slug": cfg.slug, "personal_configs": cfg.personal_configs}, action=op)
        if isinstance(cfg, ListConfigs):
            return await self._request(token, "GET", "/configs", params=cfg.model_dump(exclude={"operation"}), action=op)
        if isinstance(cfg, GetConfig):
            return await self._request(token, "GET", "/configs/config", params={"project": cfg.project, "config": cfg.config}, action=op)
        if isinstance(cfg, CreateConfig):
            return await self._request(token, "POST", "/configs", body=cfg.model_dump(exclude={"operation"}), action=op)
        if isinstance(cfg, ListSecretNames):
            return await self._request(token, "GET", "/configs/config/secrets/names", params={"project": cfg.project, "config": cfg.config}, action=op)
        if isinstance(cfg, ListSecrets):
            return await self._request(token, "GET", "/configs/config/secrets", params={"project": cfg.project, "config": cfg.config, "secrets": cfg.names}, action=op)
        if isinstance(cfg, GetSecret):
            return await self._request(token, "GET", "/configs/config/secret", params={"project": cfg.project, "config": cfg.config, "name": cfg.name}, action=op)
        if isinstance(cfg, DownloadSecrets):
            return await self._request(token, "GET", "/configs/config/secrets/download",
                                       params={"project": cfg.project, "config": cfg.config, "format": "json", "secrets": cfg.names}, action=op)
        if isinstance(cfg, SetSecrets):
            names = list(json.loads(cfg.secrets_json))
            result = await self._request(token, "POST", "/configs/config/secrets",
                                         body={"project": cfg.project, "config": cfg.config, "secrets": json.loads(cfg.secrets_json)},
                                         action=op, redact_response=True)
            if result["status"] == "success":
                result["data"] = {"updated_names": names, "count": len(names)}
            return result
        if isinstance(cfg, DeleteSecret):
            result = await self._request(token, "DELETE", "/configs/config/secret",
                                         params={"project": cfg.project, "config": cfg.config, "name": cfg.name},
                                         action=op, redact_response=True)
            if result["status"] == "success":
                result["data"] = {"deleted_name": cfg.name}
            return result
        raise ValueError(f"Unsupported Doppler operation: {op}")
