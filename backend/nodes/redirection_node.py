"""redirection.io public API v2: organization, rules, drafts and infrastructure.

Contract: https://api.redirection.io/docs.json (2.0.0).
Writes create draft changes; publish_project explicitly applies the ruleset.
Lists return one page, with search_after_id continuation where documented.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.redirection.io"
DOCS = "https://redirection.io/documentation/developer-documentation/public-api"


class RedirectionTokenCredential(BaseModel):
    model_config = ConfigDict(title="redirection.io API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://redirection.io/manager",
            "x-credential-instructions": "In your organization's Settings → API tokens, create a token and paste it here. The API requires at least one Starter or Pro project. Tokens grant full control over the organization."})
    credential_type: Literal["redirection_api_token"] = Field("redirection_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceId = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class _Project(_Input):
    project_id: ResourceId = Field(..., title="Project ID")


class _Page(_Project):
    search_after_id: ResourceId | None = Field(None, description="Last ID of the previous page. Each page contains up to 100 items.")


class _RulePage(_Page):
    tags: list[str] | None = None
    enabled: bool | None = None
    trigger_url: str | None = Field(None, description="Exact source URL to search for.")


class RuleTrigger(_Input):
    source: str = Field(..., min_length=1, description="Source URL or path, such as /old-url.")
    methods: list[str] | None = None
    responseStatusCodes: list[int] | None = None
    excludeMethods: bool | None = None
    excludeResponseStatusCodes: bool | None = None
    sampling: int | None = Field(None, ge=0, le=100)


class RedirectAction(_Input):
    type: Literal["redirection"] = "redirection"
    location: str = Field(..., min_length=1)
    statusCode: Literal[301, 302, 307, 308] = 301


class HeaderAction(_Input):
    type: Literal["header"] = "header"
    name: str = Field(..., min_length=1)
    value: str
    mode: Literal["override", "default", "replace", "append", "add"] = "override"


class StatusAction(_Input):
    type: Literal["customStatus"] = "customStatus"
    statusCode: int = Field(..., ge=200, le=511)


class HtmlAction(_Input):
    type: Literal["customHtml"] = "customHtml"
    value: str
    cssSelector: str
    action: Literal["append_child", "prepend_child", "replace"]


Action = Annotated[Union[RedirectAction, HeaderAction, StatusAction, HtmlAction], Field(discriminator="type")]


class _RuleWrite(_Project):
    trigger: RuleTrigger
    actions: list[Action] = Field(..., min_length=1)
    description: str | None = None
    enabled: bool = True
    priority: int = 0
    tags: list[str] | None = None
    metadata: dict[str, str | None] | None = None


class RedirectionGetOrganizationConfig(_Input):
    """Read the organization associated with the API token."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})


class RedirectionListProjectsConfig(_Input):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class RedirectionGetProjectConfig(_Project):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class RedirectionCreateProjectConfig(_Input):
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    metadata: dict[str, str | None] | None = None


class RedirectionDeleteProjectConfig(_Project):
    """Permanently delete the selected project."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})


class RedirectionListRulesConfig(_RulePage):
    """List published rules; saved drafts are excluded."""
    operation: Literal["list_rules"] = Field("list_rules", json_schema_extra={"ui:hidden": True})


class RedirectionGetRuleConfig(_Input):
    operation: Literal["get_rule"] = Field("get_rule", json_schema_extra={"ui:hidden": True})
    rule_id: ResourceId


class RedirectionCreateRedirectionConfig(_Project):
    """Create a simple redirect as a draft; publish separately to apply it."""
    operation: Literal["create_redirection"] = Field("create_redirection", json_schema_extra={"ui:hidden": True})
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    status_code: Literal[301, 302, 307, 308] = 301
    description: str | None = None
    enabled: bool = True
    priority: int = 0
    tags: list[str] | None = None


class RedirectionCreateRuleConfig(_RuleWrite):
    """Create a draft rule with redirect, header, status or HTML actions."""
    operation: Literal["create_rule"] = Field("create_rule", json_schema_extra={"ui:hidden": True})


class RedirectionUpdateRuleConfig(_RuleWrite):
    """Replace the rule with these fields as a draft; publish separately."""
    operation: Literal["update_rule"] = Field("update_rule", json_schema_extra={"ui:hidden": True})
    rule_id: ResourceId


class RedirectionDeleteRuleConfig(_Input):
    """Stage deletion of a rule; publish separately to apply it."""
    operation: Literal["delete_rule"] = Field("delete_rule", json_schema_extra={"ui:hidden": True})
    rule_id: ResourceId


class RedirectionGetRuleStatisticsConfig(_Input):
    operation: Literal["get_rule_statistics"] = Field("get_rule_statistics", json_schema_extra={"ui:hidden": True})
    rule_id: ResourceId
    start: str | None = Field(None, description="Statistics start time, as accepted by the provider.")
    end: str | None = Field(None, description="Statistics end time, as accepted by the provider.")


class RedirectionListDraftsConfig(_RulePage):
    operation: Literal["list_drafts"] = Field("list_drafts", json_schema_extra={"ui:hidden": True})


class RedirectionGetDraftConfig(_Input):
    operation: Literal["get_draft"] = Field("get_draft", json_schema_extra={"ui:hidden": True})
    draft_id: ResourceId


class RedirectionDeleteDraftConfig(_Input):
    """Discard a pending draft change."""
    operation: Literal["delete_draft"] = Field("delete_draft", json_schema_extra={"ui:hidden": True})
    draft_id: ResourceId


class RedirectionPublishProjectConfig(_Project):
    """Publish all pending draft changes in this project. Limited to 20 calls per day."""
    operation: Literal["publish_project"] = Field("publish_project", json_schema_extra={"ui:hidden": True})


class RedirectionListDomainsConfig(_Page):
    operation: Literal["list_domains"] = Field("list_domains", json_schema_extra={"ui:hidden": True})


class RedirectionGetDomainConfig(_Input):
    operation: Literal["get_domain"] = Field("get_domain", json_schema_extra={"ui:hidden": True})
    domain_id: ResourceId


class RedirectionCreateDomainConfig(_Project):
    operation: Literal["create_domain"] = Field("create_domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1)
    backend_address: str | None = None
    backend_enabled: bool = False
    backend_use_ssl: bool = True
    backend_allow_invalid_certificate: bool = True
    ssl_automatic: bool = True
    ssl_enabled: bool = True


class RedirectionDeleteDomainConfig(_Input):
    """Permanently delete a managed domain."""
    operation: Literal["delete_domain"] = Field("delete_domain", json_schema_extra={"ui:hidden": True})
    domain_id: ResourceId


class RedirectionListInstancesConfig(_Page):
    operation: Literal["list_instances"] = Field("list_instances", json_schema_extra={"ui:hidden": True})
    name: str | None = None


class RedirectionGetInstanceConfig(_Input):
    operation: Literal["get_instance"] = Field("get_instance", json_schema_extra={"ui:hidden": True})
    instance_id: ResourceId


class RedirectionDeleteInstanceConfig(_Input):
    operation: Literal["delete_instance"] = Field("delete_instance", json_schema_extra={"ui:hidden": True})
    instance_id: ResourceId


class RedirectionListIpsConfig(_Input):
    """Read the redirection.io service IP addresses."""
    operation: Literal["list_ips"] = Field("list_ips", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[
    RedirectionGetOrganizationConfig,
    RedirectionListProjectsConfig,
    RedirectionGetProjectConfig,
    RedirectionCreateProjectConfig,
    RedirectionDeleteProjectConfig,
    RedirectionListRulesConfig,
    RedirectionGetRuleConfig,
    RedirectionCreateRedirectionConfig,
    RedirectionCreateRuleConfig,
    RedirectionUpdateRuleConfig,
    RedirectionDeleteRuleConfig,
    RedirectionGetRuleStatisticsConfig,
    RedirectionListDraftsConfig,
    RedirectionGetDraftConfig,
    RedirectionDeleteDraftConfig,
    RedirectionPublishProjectConfig,
    RedirectionListDomainsConfig,
    RedirectionGetDomainConfig,
    RedirectionCreateDomainConfig,
    RedirectionDeleteDomainConfig,
    RedirectionListInstancesConfig,
    RedirectionGetInstanceConfig,
    RedirectionDeleteInstanceConfig,
    RedirectionListIpsConfig
], Field(discriminator="operation")]


class RedirectionConfig(NodeConfig[Operation, RedirectionTokenCredential]):
    pass


ROUTES = {'get_organization': ('GET', '/organization'), 'list_ips': ('GET', '/ips'), 'create_redirection': ('POST', '/redirections'), 'publish_project': ('POST', '/projects/{project_id}/publish'), 'get_rule_statistics': ('GET', '/rules/{rule_id}/statistics'), 'list_projects': ('GET', '/projects'), 'get_project': ('GET', '/projects/{project_id}'), 'create_project': ('POST', '/projects'), 'delete_project': ('DELETE', '/projects/{project_id}'), 'list_rules': ('GET', '/rules'), 'get_rule': ('GET', '/rules/{rule_id}'), 'create_rule': ('POST', '/rules'), 'update_rule': ('PUT', '/rules/{rule_id}'), 'delete_rule': ('DELETE', '/rules/{rule_id}'), 'list_drafts': ('GET', '/drafts'), 'get_draft': ('GET', '/drafts/{draft_id}'), 'delete_draft': ('DELETE', '/drafts/{draft_id}'), 'list_domains': ('GET', '/domains'), 'get_domain': ('GET', '/domains/{domain_id}'), 'create_domain': ('POST', '/domains'), 'delete_domain': ('DELETE', '/domains/{domain_id}'), 'list_instances': ('GET', '/instances'), 'get_instance': ('GET', '/instances/{instance_id}'), 'delete_instance': ('DELETE', '/instances/{instance_id}')}

# Only these documented fields are translated to provider query/body names.
QUERY_NAMES = {"project_id": "projectId", "search_after_id": "searchAfterId",
    "trigger_url": "triggerUrl", "tags": "tags", "enabled": "enabled", "name": "name",
    "start": "start", "end": "end"}
BODY_NAMES = {"status_code": "statusCode", "backend_address": "backendAddress",
    "backend_enabled": "backendEnabled", "backend_use_ssl": "backendUseSsl",
    "backend_allow_invalid_certificate": "backendAllowInvalidCertificate",
    "ssl_automatic": "sslAutomatic", "ssl_enabled": "sslEnabled"}
PAGED = {"list_rules", "list_drafts", "list_domains", "list_instances"}


class RedirectionNode(WorkflowNode):
    integration_type = "automation-redirection"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", identity_operation="get_organization")

    @classmethod
    def get_config_model(cls):
        return RedirectionConfig

    async def execute(self, inputs):
        if not isinstance(self.config, RedirectionConfig) or not self.config.credentials:
            raise ValueError("Connect a redirection.io API token")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        operation = values.pop("operation")
        method, path = ROUTES[operation]
        for key in list(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params, body = {}, None
        if method == "GET":
            params = {QUERY_NAMES[k]: v for k, v in values.items() if k in QUERY_NAMES}
        elif method in {"POST", "PUT"} and operation != "publish_project":
            body = {BODY_NAMES.get(k, k): v for k, v in values.items()}
            if "project_id" in body:
                body["project"] = "/projects/" + body.pop("project_id")
        token = self.config.credentials.api_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params,
                **({"json": body} if body is not None else {}))
        expected = 204 if (method == "DELETE" and operation != "delete_rule") or operation == "publish_project" else 201 if method == "POST" else 200
        if response.status_code != expected:
            message = response.text[:2000].replace(token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message or "redirection.io did not confirm the operation",
                **({"retry_after": response.headers["Retry-After"]} if "Retry-After" in response.headers else {})}
        if expected == 204:
            return {"status": "success", "http_status": 204}
        data = response.json()
        if operation.startswith("list_") or operation == "get_rule_statistics":
            if not isinstance(data, list):
                raise ValueError("Expected a redirection.io JSON array")
        elif not isinstance(data, (dict, list)):
            # The documentation shows an array of drafts for create_redirection.
            raise ValueError("Expected a redirection.io JSON resource")
        result = {"status": "success", "http_status": expected, "data": data}
        if operation in PAGED:
            has_more = len(data) == 100
            next_id = data[-1].get("id") if has_more and isinstance(data[-1], dict) else None
            if has_more and (not next_id or next_id == getattr(config, "search_after_id", None)):
                raise ValueError("redirection.io returned a non-advancing page")
            result.update(has_more=has_more, next_search_after_id=next_id)
        return result
