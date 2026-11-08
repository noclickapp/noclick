"""Appcircle build and testing-distribution actions against its published API.

A manually supplied generated access token is sent only to api.appcircle.io.
Each operation performs one request; paged reads return the provider page unchanged.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class AppcircleAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Appcircle Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.appcircle.io/appcircle-api-and-cli/api-authentication",
            "x-credential-instructions": "Paste the generated access token, without Bearer. Exchange your Personal Access Key at Appcircle's Auth API first; the key itself is not an access token. Access tokens expire: replace this credential when it expires. The token must allow the selected build or testing-distribution actions."
        })
    credential_type: Literal["appcircle_access_token"] = Field("appcircle_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=16384, title="Access token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the generated access token")
        value = clean_secret(value, field_name="Access token")
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or not value.isascii():
            raise ValueError("Paste only the generated access token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Paged(_Input):
    page: int = Field(1, ge=1, description="Page number; each execution fetches one page.")
    size: int = Field(50, ge=1, le=200, description="Requested page size. Increment page to fetch more results.")


class AppcircleListOrganizationsConfig(_Input):
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(200, ge=1)
    search: str | None = None


class AppcircleListBuildProfilesConfig(_Paged):
    operation: Literal["list_build_profiles"] = Field("list_build_profiles", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class AppcircleGetBuildProfileConfig(_Input):
    operation: Literal["get_build_profile"] = Field("get_build_profile", json_schema_extra={"ui:hidden": True})
    profile_id: UUID


class AppcircleDeleteBuildProfileConfig(_Input):
    operation: Literal["delete_build_profile"] = Field("delete_build_profile", json_schema_extra={"ui:hidden": True})
    profile_id: UUID


class AppcircleListCommitsConfig(_Paged):
    operation: Literal["list_commits"] = Field("list_commits", json_schema_extra={"ui:hidden": True})
    profile_id: UUID
    branch_id: UUID


class AppcircleGetBuildStatusConfig(_Input):
    operation: Literal["get_build_status"] = Field("get_build_status", json_schema_extra={"ui:hidden": True})
    commit_id: UUID
    build_id: UUID


class AppcircleStartBuildConfig(_Input):
    operation: Literal["start_build"] = Field("start_build", json_schema_extra={"ui:hidden": True})
    commit_id: UUID
    configuration_id: UUID | None = None


class AppcircleStartWorkflowBuildConfig(_Input):
    operation: Literal["start_workflow_build"] = Field("start_workflow_build", json_schema_extra={"ui:hidden": True})
    commit_id: UUID
    workflow_id: UUID
    configuration_id: UUID | None = None


class AppcircleListBuildConfigurationsConfig(_Input):
    operation: Literal["list_build_configurations"] = Field("list_build_configurations", json_schema_extra={"ui:hidden": True})
    profile_id: UUID
    branch_id: UUID | None = None


class AppcircleListBuildWorkflowsConfig(_Input):
    operation: Literal["list_build_workflows"] = Field("list_build_workflows", json_schema_extra={"ui:hidden": True})
    profile_id: UUID


class AppcircleGetBuildQueueConfig(_Input):
    operation: Literal["get_build_queue"] = Field("get_build_queue", json_schema_extra={"ui:hidden": True})
    task_id: UUID


class AppcircleCancelBuildConfig(_Input):
    operation: Literal["cancel_build"] = Field("cancel_build", json_schema_extra={"ui:hidden": True})
    task_id: UUID


class AppcircleListVariableGroupsConfig(_Paged):
    operation: Literal["list_variable_groups"] = Field("list_variable_groups", json_schema_extra={"ui:hidden": True})


class AppcircleCreateVariableGroupConfig(_Input):
    operation: Literal["create_variable_group"] = Field("create_variable_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    organization_id: UUID


class AppcircleDeleteVariableGroupConfig(_Input):
    operation: Literal["delete_variable_group"] = Field("delete_variable_group", json_schema_extra={"ui:hidden": True})
    variable_group_id: UUID


class AppcircleRenameVariableGroupConfig(_Input):
    operation: Literal["rename_variable_group"] = Field("rename_variable_group", json_schema_extra={"ui:hidden": True})
    variable_group_id: UUID
    name: str = Field(..., min_length=1, max_length=500)


class AppcircleListDistributionProfilesConfig(_Paged):
    operation: Literal["list_distribution_profiles"] = Field("list_distribution_profiles", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class AppcircleListAppVersionsConfig(_Paged):
    operation: Literal["list_app_versions"] = Field("list_app_versions", json_schema_extra={"ui:hidden": True})
    profile_id: UUID
    search: str | None = None


class AppcircleListTestingGroupsConfig(_Paged):
    operation: Literal["list_testing_groups"] = Field("list_testing_groups", json_schema_extra={"ui:hidden": True})


class AppcircleCreateTestingGroupConfig(_Input):
    operation: Literal["create_testing_group"] = Field("create_testing_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    organization_id: UUID


class AppcircleGetTestingGroupConfig(_Input):
    operation: Literal["get_testing_group"] = Field("get_testing_group", json_schema_extra={"ui:hidden": True})
    group_id: UUID


class AppcircleDeleteTestingGroupConfig(_Input):
    operation: Literal["delete_testing_group"] = Field("delete_testing_group", json_schema_extra={"ui:hidden": True})
    group_id: UUID


class AppcircleAddTestersConfig(_Input):
    operation: Literal["add_testers"] = Field("add_testers", json_schema_extra={"ui:hidden": True})
    group_id: UUID
    emails: list[Annotated[str, Field(json_schema_extra={"format": "email"})]] = Field(..., min_length=1, max_length=100, description="Tester email addresses. Adding testers can send invitations.")

    @field_validator("emails")
    @classmethod
    def addresses(cls, values):
        if any("@" not in v or any(c.isspace() for c in v) for v in values):
            raise ValueError("Supply tester email addresses")
        return values


class AppcircleGetTaskStatusConfig(_Input):
    operation: Literal["get_task_status"] = Field("get_task_status", json_schema_extra={"ui:hidden": True})
    task_id: UUID


AppcircleOperation = Annotated[Union[
    AppcircleListOrganizationsConfig,
    AppcircleListBuildProfilesConfig,
    AppcircleGetBuildProfileConfig,
    AppcircleDeleteBuildProfileConfig,
    AppcircleListCommitsConfig,
    AppcircleGetBuildStatusConfig,
    AppcircleStartBuildConfig,
    AppcircleStartWorkflowBuildConfig,
    AppcircleListBuildConfigurationsConfig,
    AppcircleListBuildWorkflowsConfig,
    AppcircleGetBuildQueueConfig,
    AppcircleCancelBuildConfig,
    AppcircleListVariableGroupsConfig,
    AppcircleCreateVariableGroupConfig,
    AppcircleDeleteVariableGroupConfig,
    AppcircleRenameVariableGroupConfig,
    AppcircleListDistributionProfilesConfig,
    AppcircleListAppVersionsConfig,
    AppcircleListTestingGroupsConfig,
    AppcircleCreateTestingGroupConfig,
    AppcircleGetTestingGroupConfig,
    AppcircleDeleteTestingGroupConfig,
    AppcircleAddTestersConfig,
    AppcircleGetTaskStatusConfig,
], Field(discriminator="operation")]


class AppcircleFullConfig(NodeConfig[AppcircleOperation, AppcircleAccessTokenCredential]):
    pass


# One published HTTP operation per user action. Query names retain provider casing.
ROUTES = {
    "list_organizations": ('identity', 'GET', '/v1/organizations', {'page': 'page', 'per_page': 'perPage', 'search': 'search'}),
    "list_build_profiles": ('build', 'GET', '/v2/profiles', {'page': 'Page', 'size': 'Size', 'search': 'search'}),
    "get_build_profile": ('build', 'GET', '/v2/profiles/{profile_id}', {}),
    "delete_build_profile": ('build', 'DELETE', '/v2/profiles/{profile_id}', {}),
    "list_commits": ('build', 'GET', '/v2/commits', {'profile_id': 'profileId', 'branch_id': 'branchId', 'page': 'Page', 'size': 'Size'}),
    "get_build_status": ('build', 'GET', '/v2/commits/{commit_id}/builds/{build_id}/status', {}),
    "start_build": ('build', 'POST', '/v3/commits/{commit_id}/build', {'configuration_id': 'configurationId'}),
    "start_workflow_build": ('build', 'POST', '/v3/commits/{commit_id}/build/by-workflow', {'workflow_id': 'workflowId', 'configuration_id': 'configurationId'}),
    "list_build_configurations": ('build', 'GET', '/v2/profiles/{profile_id}/configurations', {'branch_id': 'branchId'}),
    "list_build_workflows": ('build', 'GET', '/v2/profiles/{profile_id}/workflows', {}),
    "get_build_queue": ('build', 'GET', '/v3/queue/{task_id}', {}),
    "cancel_build": ('build', 'POST', '/v3/queue/{task_id}/cancel', {}),
    "list_variable_groups": ('build', 'GET', '/v2/variable-groups', {'page': 'Page', 'size': 'Size'}),
    "create_variable_group": ('build', 'POST', '/v2/variable-groups', {}),
    "delete_variable_group": ('build', 'DELETE', '/v2/variable-groups/{variable_group_id}', {}),
    "rename_variable_group": ('build', 'PATCH', '/v2/variable-groups/{variable_group_id}', {'name': 'name'}),
    "list_distribution_profiles": ('distribution', 'GET', '/v2/profiles', {'page': 'Page', 'size': 'Size', 'search': 'search'}),
    "list_app_versions": ('distribution', 'GET', '/v2/profiles/{profile_id}/app-versions', {'page': 'Page', 'size': 'Size', 'search': 'searchTerm'}),
    "list_testing_groups": ('distribution', 'GET', '/v2/testing-groups', {'page': 'Page', 'size': 'Size'}),
    "create_testing_group": ('distribution', 'POST', '/v2/testing-groups', {}),
    "get_testing_group": ('distribution', 'GET', '/v2/testing-groups/{group_id}', {}),
    "delete_testing_group": ('distribution', 'DELETE', '/v2/testing-groups/{group_id}', {}),
    "add_testers": ('distribution', 'POST', '/v3/testing-groups/{group_id}/testers', {}),
    "get_task_status": ('task', 'GET', '/v1/tasks/{task_id}', {}),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class AppcircleNode(WorkflowNode):
    integration_type = "automation-appcircle"
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")

    @classmethod
    def get_config_model(cls):
        return AppcircleFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Appcircle access token")
        config = self.config.config
        token = self.config.credentials.access_token
        values = config.model_dump(mode="json", exclude_none=True)
        module, method, template, query = ROUTES[config.operation]
        url = "https://api.appcircle.io/" + module + template.format(**values)
        params = {target: values[source] for source, target in query.items() if source in values}
        kwargs = {"params": params}
        if config.operation in {"create_variable_group", "create_testing_group"}:
            kwargs["json"] = {"name": config.name, "organizationId": str(config.organization_id)}
        elif config.operation == "add_testers":
            kwargs["json"] = config.emails
        # No automatic retries: a timed-out build or invitation may have succeeded.
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(response.text[:2000], token) or "Appcircle rejected the request"}
        if not response.content:
            data = None
        else:
            data = response.json()
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(str(data), token)}
        # Preserve API arrays, objects and scalar acknowledgements without claiming
        # that a queued build has finished or that this page is the whole collection.
        return {"status": "success", "http_status": response.status_code,
            "data": _redact(data, token),
            **({"page": config.page, "size": config.size} if hasattr(config, "size") else {})}
