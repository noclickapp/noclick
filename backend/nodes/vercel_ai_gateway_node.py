"""Vercel AI Gateway management API. Each operation sends exactly one request.

Lists return one page with the provider's original continuation. The caller
passes it back explicitly. Contract: https://openapi.vercel.sh/, version 0.0.1.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class VercelAiGatewayTokenCredential(BaseModel):
    model_config = ConfigDict(title="Vercel AI Gateway Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://vercel.com/account/settings/tokens",
        "x-credential-instructions": "Create a Vercel access token with access to the team whose AI Gateway you manage. Paste it here. Use Account Settings → Tokens. AI Gateway inference keys are separate. Optionally enter the team ID for a team-scoped connection."})
    credential_type: Literal["vercel_ai_gateway_token"] = Field("vercel_ai_gateway_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    team_id: str | None = Field(None, title="Team ID", min_length=1, max_length=256, description="Optional team ID from Vercel Team Settings. Leave empty to use the token's default account.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    teamId: str | None = Field(None, title="Team ID", min_length=1, max_length=256, description="Overrides the credential's default team for this request.")


class _Page(_Input):
    limit: int = Field(100, ge=1, le=200, title="Page Size")
    cursor: str | None = Field(None, max_length=8192, title="Cursor", description="Pass cursor or nextCursor from the previous response. Each run returns one page.")


class ListByokCredentials(_Input):
    operation: Literal["list_byok_credentials"] = Field("list_byok_credentials", title="List BYOK Credentials", json_schema_extra={"ui:hidden": True})
    providerSlug: str | None = Field(None, title="Provider Slug", max_length=256)
    includeDeleted: Literal["true", "false"] = "false"
    includeModelMappings: Literal["true", "false"] = "false"


class _CredentialId(_Input):
    credentialId: str = Field(..., title="BYOK Credential ID", min_length=1, max_length=256)


class GetByokCredential(_CredentialId):
    operation: Literal["get_byok_credential"] = Field("get_byok_credential", title="Get BYOK Credential", json_schema_extra={"ui:hidden": True})


class UpdateByokCredential(_CredentialId):
    operation: Literal["update_byok_credential"] = Field("update_byok_credential", title="Update BYOK Credential Settings", description="Change metadata and activation settings. Does not rotate the provider key.", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=100)
    active: bool | None = None
    zeroDataRetention: bool | None = Field(None, description="Attest whether this external credential has a zero data retention policy.")

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, key) is None for key in ("name", "active", "zeroDataRetention")):
            raise ValueError("Supply at least one credential setting to update")
        return self


class DeleteByokCredential(_CredentialId):
    operation: Literal["delete_byok_credential"] = Field("delete_byok_credential", title="Delete BYOK Credential", description="Soft-deletes the credential and its model mappings.", json_schema_extra={"ui:hidden": True})


class ListVirtualModelConfigs(_Page):
    operation: Literal["list_virtual_model_configs"] = Field("list_virtual_model_configs", title="List Virtual Model Configs", json_schema_extra={"ui:hidden": True})
    includeArchived: Literal["true", "false"] = "false"


class _VirtualModel(_Input):
    vmcSlug: str = Field(..., title="Virtual Model Slug", min_length=1, max_length=512)


class GetVirtualModelConfig(_VirtualModel):
    operation: Literal["get_virtual_model_config"] = Field("get_virtual_model_config", title="Get Virtual Model Config", json_schema_extra={"ui:hidden": True})


class DeleteVirtualModelConfig(_VirtualModel):
    operation: Literal["delete_virtual_model_config"] = Field("delete_virtual_model_config", title="Delete Virtual Model Config", json_schema_extra={"ui:hidden": True})


class ListRouters(_Input):
    operation: Literal["list_routers"] = Field("list_routers", title="List AI Gateway Routers", json_schema_extra={"ui:hidden": True})


class ListRules(_Page):
    operation: Literal["list_rules"] = Field("list_rules", title="List Routing Rules", json_schema_extra={"ui:hidden": True})
    includeDisabled: Literal["true", "false"] = "false"


class DeleteRule(_Input):
    operation: Literal["delete_rule"] = Field("delete_rule", title="Delete Routing Rule", json_schema_extra={"ui:hidden": True})
    ruleId: str = Field(..., title="Rule ID", min_length=1, max_length=256)


class ListBudgets(_Page):
    operation: Literal["list_budgets"] = Field("list_budgets", title="List AI Gateway Budgets", json_schema_extra={"ui:hidden": True})
    scopeType: Literal["team", "project", "user", "api-key"] | None = None
    includeDefaultCovered: Literal["true", "false"] = "true"


class _BudgetScope(_Input):
    scopeType: Literal["team", "project", "user"] = Field(..., title="Budget Scope")
    projectId: str | None = Field(None, min_length=1, max_length=256)
    userId: str | None = Field(None, min_length=1, max_length=256)
    justification: str | None = Field(None, max_length=500, description="Reason for the change, recorded in Vercel's activity and audit logs.")

    @model_validator(mode="after")
    def scoped_id(self):
        required = {"project": "projectId", "user": "userId"}.get(self.scopeType)
        if required and not getattr(self, required):
            raise ValueError(f"{required} is required for the selected budget scope")
        if self.projectId and self.scopeType != "project" or self.userId and self.scopeType != "user":
            raise ValueError("Supply only the ID for the selected budget scope")
        return self


class _BudgetSettings(BaseModel):
    limitAmount: float = Field(..., ge=1, allow_inf_nan=False, title="Limit in Dollars")
    refreshPeriod: Literal["daily", "weekly", "monthly", "none"] = "monthly"
    alertThresholds: list[Literal[50, 75, 100]] | None = None


class UpsertBudget(_BudgetScope, _BudgetSettings):
    operation: Literal["upsert_budget"] = Field("upsert_budget", title="Set AI Gateway Budget", json_schema_extra={"ui:hidden": True})
    includeByokInQuota: bool | None = None


class ArchiveBudget(_BudgetScope):
    operation: Literal["archive_budget"] = Field("archive_budget", title="Archive AI Gateway Budget", json_schema_extra={"ui:hidden": True})


class ListBudgetDefaults(_Input):
    operation: Literal["list_budget_defaults"] = Field("list_budget_defaults", title="List Budget Defaults", json_schema_extra={"ui:hidden": True})


class _DefaultScope(_Input):
    scopeType: Literal["team", "project", "api-key", "user"] = Field(..., title="Default Budget Scope")
    justification: str | None = Field(None, max_length=500)


class UpsertBudgetDefault(_DefaultScope, _BudgetSettings):
    operation: Literal["upsert_budget_default"] = Field("upsert_budget_default", title="Set Budget Default", json_schema_extra={"ui:hidden": True})


class ArchiveBudgetDefault(_DefaultScope):
    operation: Literal["archive_budget_default"] = Field("archive_budget_default", title="Archive Budget Default", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListByokCredentials, GetByokCredential, UpdateByokCredential, DeleteByokCredential,
    ListVirtualModelConfigs, GetVirtualModelConfig, DeleteVirtualModelConfig, ListRouters, ListRules, DeleteRule,
    ListBudgets, UpsertBudget, ArchiveBudget, ListBudgetDefaults, UpsertBudgetDefault, ArchiveBudgetDefault], Field(discriminator="operation")]


class VercelAiGatewayConfig(NodeConfig[Operation, VercelAiGatewayTokenCredential]):
    pass


ROUTES = {
    "list_byok_credentials": ("GET", "/ai-gateway/byok-credentials/list", 200),
    "get_byok_credential": ("GET", "/ai-gateway/byok-credentials/{credentialId}", 200),
    "update_byok_credential": ("PATCH", "/ai-gateway/byok-credentials/{credentialId}", 200),
    "delete_byok_credential": ("DELETE", "/ai-gateway/byok-credentials/{credentialId}", 204),
    "list_virtual_model_configs": ("GET", "/ai-gateway/virtual-model-configs/list", 200),
    "get_virtual_model_config": ("GET", "/ai-gateway/virtual-model-configs/{vmcSlug}", 200),
    "delete_virtual_model_config": ("DELETE", "/ai-gateway/virtual-model-configs/{vmcSlug}", 204),
    "list_routers": ("GET", "/v1/ai-gateway/routers", 200),
    "list_rules": ("GET", "/ai-gateway/rules", 200),
    "delete_rule": ("DELETE", "/ai-gateway/rules", 204),
    "list_budgets": ("GET", "/ai-gateway/budgets/list", 200),
    "upsert_budget": ("PUT", "/ai-gateway/budgets", 200),
    "archive_budget": ("DELETE", "/ai-gateway/budgets", 200),
    "list_budget_defaults": ("GET", "/ai-gateway/budgets/defaults/list", 200),
    "upsert_budget_default": ("PUT", "/ai-gateway/budgets/defaults", 200),
    "archive_budget_default": ("DELETE", "/ai-gateway/budgets/defaults", 204),
}


def _redact(value):
    """The BYOK list schema has a nullable credential; never emit its value."""
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items() if k not in {"credential", "access_token", "apiKey", "token"}}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class VercelAiGatewayNode(WorkflowNode):
    integration_type = "automation-vercel-ai-gateway"
    connection_evidence = ConnectionEvidence(operation="list_byok_credentials", noun="BYOK credentials")

    @classmethod
    def get_config_model(cls):
        return VercelAiGatewayConfig

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Attach a Vercel AI Gateway access token")
        method, path, expected = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        params = {}
        team_id = values.pop("teamId", None) or credential.team_id
        if team_id:
            params["teamId"] = team_id
        for key in ("credentialId", "vmcSlug"):
            if "{" + key + "}" in path:
                value = values.pop(key)
                if value in {".", ".."}:
                    raise ValueError("A resource ID cannot be a path traversal segment")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        kwargs = {}
        if method in {"PUT", "PATCH"}:
            kwargs["json"] = values
        else:
            params.update(values)
        headers = {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.vercel.com" + path, headers=headers, params=params, **kwargs)
        if response.status_code != expected:
            message = "Vercel AI Gateway rejected the request"
            try:
                error = response.json().get("error", {})
                candidate = error.get("message") if isinstance(error, dict) else error
                if isinstance(candidate, str):
                    message = candidate[:2000].replace(credential.access_token, "[redacted]")
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"Vercel AI Gateway HTTP {response.status_code}: {message}")
        if expected == 204:
            return {"success": True, "operation": config.operation, "http_status": 204}
        result = response.json()
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Vercel AI Gateway returned an invalid JSON envelope")
        collection = {
            "list_byok_credentials": "credentials", "list_virtual_model_configs": "virtualModelConfigs",
            "list_routers": "routers", "list_rules": "rules", "list_budgets": "budgets",
            "list_budget_defaults": "defaults",
        }.get(config.operation)
        if collection and not isinstance(result.get(collection), list):
            raise ValueError(f"Vercel AI Gateway response is missing the {collection} list")
        return _redact(result)
