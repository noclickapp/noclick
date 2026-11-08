"""Agiled v1 CRM, projects and tasks using a manually supplied API token.

Contract: https://my.agiled.app/docs/api-docs.json (1.0.0).
Requests always use the published API host; Brand is an account header only.
Agiled currently documents a limit of 180 requests per hour. No automatic retries.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

import httpx

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client

BASE_URL = "https://my.agiled.app/api/v1"


class AgiledAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Agiled API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://my.agiled.app/docs/",
            "x-credential-instructions": "In Agiled, open Settings > API Settings and copy your API token. Paste it here with your Agiled account URL. NoClick sends the token as api_token and the account URL as the Brand header to my.agiled.app. Agiled documents 180 requests per hour.",
        })
    credential_type: Literal["agiled_api_token"] = Field("agiled_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})
    brand_url: str = Field(..., title="Agiled account URL", description="Your account's HTTPS origin, for the Brand header.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without whitespace")
        return value

    @field_validator("brand_url", mode="before")
    @classmethod
    def brand(cls, value):
        origin = https_origin(value, field_name="Agiled account URL")
        if not origin.startswith("https://"):
            raise ValueError("Use your Agiled account HTTPS URL")
        return origin


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Contact(_Config):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=320)
    phone: Optional[str] = Field(None, max_length=100)
    job_title: Optional[str] = Field(None, max_length=255)
    role: Optional[Literal["Client", "Lead", "Prospect"]] = None
    account_id: Optional[str] = Field(None, pattern=r"^[1-9][0-9]*$")
    owner_id: Optional[int] = Field(None, gt=0)
    source_id: Optional[int] = Field(None, gt=0)
    status_id: Optional[int] = Field(None, gt=0)
    note: Optional[str] = Field(None, max_length=10000)
    tags: Optional[str] = Field(None, max_length=2000, description="Comma-separated tags.")


class _Account(_Config):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=10000)
    email: Optional[str] = Field(None, max_length=320)
    phone: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=2000)
    size: Optional[int] = Field(None, ge=0)
    owner_id: Optional[int] = Field(None, gt=0)
    note: Optional[str] = Field(None, max_length=10000)
    tags: Optional[str] = Field(None, max_length=2000, description="Comma-separated tags.")


class _Project(_Config):
    project_name: str = Field(..., min_length=1, max_length=255)
    start_date: date
    project_summary: Optional[str] = Field(None, max_length=10000)
    deadline: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=10000)
    client_id: Optional[int] = Field(None, gt=0)
    category_id: Optional[int] = Field(None, gt=0)
    completion_percent: Optional[int] = Field(None, ge=0, le=100)
    project_budget: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    currency_id: Optional[int] = Field(None, gt=0)


class _Task(_Config):
    heading: str = Field(..., min_length=1, max_length=255)
    start_date: date
    due_date: date
    priority: Literal["low", "medium", "high"]
    user_id: int = Field(..., gt=0)
    description: Optional[str] = Field(None, max_length=10000)
    project_id: Optional[int] = Field(None, gt=0)
    category_id: Optional[int] = Field(None, gt=0)
    milestone_id: Optional[int] = Field(None, gt=0)
    completed_on: Optional[date] = None
    billable: Optional[Literal[0, 1]] = None


class _Deal(_Config):
    deal_name: str = Field(..., min_length=1, max_length=255)
    pipeline_id: int = Field(..., gt=0)
    stage_id: int = Field(..., gt=0)
    deal_owner: Optional[int] = Field(None, gt=0)
    amount: Optional[str] = Field(None, pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    deal_type: Optional[str] = Field(None, max_length=255)
    close_date: Optional[date] = None


class AgiledListContactsConfig(_Config):
    """List contacts using GET /contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class AgiledListAccountsConfig(_Config):
    """List accounts using GET /accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class AgiledListProjectsConfig(_Config):
    """List projects using GET /projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class AgiledListTasksConfig(_Config):
    """List tasks using GET /tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})


class AgiledListDealsConfig(_Config):
    """List deals using GET /crm/deals."""
    operation: Literal["list_deals"] = Field("list_deals", json_schema_extra={"ui:hidden": True})


class AgiledListPipelinesConfig(_Config):
    """List pipelines using GET /crm/pipelines."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})


class AgiledListPipelineStagesConfig(_Config):
    """List pipeline stages using GET /crm/pipeline-stages."""
    operation: Literal["list_pipeline_stages"] = Field("list_pipeline_stages", json_schema_extra={"ui:hidden": True})


class AgiledListInvoicesConfig(_Config):
    """List invoices using GET /invoices."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class AgiledListProductsConfig(_Config):
    """List products using GET /products."""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})


class AgiledListCurrenciesConfig(_Config):
    """List currencies using GET /currencies."""
    operation: Literal["list_currencies"] = Field("list_currencies", json_schema_extra={"ui:hidden": True})


class AgiledListUsersConfig(_Config):
    """List users using GET /users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class AgiledCreateContactConfig(_Contact):
    """Create contact using POST /contacts."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})


class AgiledUpdateContactConfig(_Contact):
    """Update contact using PUT /contacts/{id}."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)


class AgiledCreateAccountConfig(_Account):
    """Create account using POST /accounts."""
    operation: Literal["create_account"] = Field("create_account", json_schema_extra={"ui:hidden": True})


class AgiledUpdateAccountConfig(_Account):
    """Update account using PUT /accounts/{id}."""
    operation: Literal["update_account"] = Field("update_account", json_schema_extra={"ui:hidden": True})
    account_id: int = Field(..., gt=0)


class AgiledCreateProjectConfig(_Project):
    """Create project using POST /projects."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    status: str = Field(..., min_length=1, max_length=100, description="Project status as configured in Agiled.")


class AgiledUpdateProjectConfig(_Project):
    """Update project using PUT /projects/{id}."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0)


class AgiledCreateTaskConfig(_Task):
    """Create task using POST /tasks."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})


class AgiledUpdateTaskConfig(_Task):
    """Update task using PUT /tasks/{id}."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)


class AgiledCreateDealConfig(_Deal):
    """Create deal using POST /crm/deals."""
    operation: Literal["create_deal"] = Field("create_deal", json_schema_extra={"ui:hidden": True})


class AgiledUpdateDealConfig(_Deal):
    """Update deal using PUT /crm/deals/{id}."""
    operation: Literal["update_deal"] = Field("update_deal", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., gt=0)


class AgiledGetProjectConfig(_Config):
    """Get project using GET /project/{id}."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0)


class AgiledGetTaskConfig(_Config):
    """Get task using GET /task/{id}."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)


AgiledConfig = Annotated[Union[
    AgiledListContactsConfig,
    AgiledListAccountsConfig,
    AgiledListProjectsConfig,
    AgiledListTasksConfig,
    AgiledListDealsConfig,
    AgiledListPipelinesConfig,
    AgiledListPipelineStagesConfig,
    AgiledListInvoicesConfig,
    AgiledListProductsConfig,
    AgiledListCurrenciesConfig,
    AgiledListUsersConfig,
    AgiledCreateContactConfig,
    AgiledUpdateContactConfig,
    AgiledCreateAccountConfig,
    AgiledUpdateAccountConfig,
    AgiledCreateProjectConfig,
    AgiledUpdateProjectConfig,
    AgiledCreateTaskConfig,
    AgiledUpdateTaskConfig,
    AgiledCreateDealConfig,
    AgiledUpdateDealConfig,
    AgiledGetProjectConfig,
    AgiledGetTaskConfig
], Field(discriminator="operation")]


class AgiledFullConfig(NodeConfig[AgiledConfig, AgiledAPITokenCredential]):
    pass


ROUTES = {'list_contacts': ('GET', '/contacts'),
 'list_accounts': ('GET', '/accounts'),
 'list_projects': ('GET', '/projects'),
 'list_tasks': ('GET', '/tasks'),
 'list_deals': ('GET', '/crm/deals'),
 'list_pipelines': ('GET', '/crm/pipelines'),
 'list_pipeline_stages': ('GET', '/crm/pipeline-stages'),
 'list_invoices': ('GET', '/invoices'),
 'list_products': ('GET', '/products'),
 'list_currencies': ('GET', '/currencies'),
 'list_users': ('GET', '/users'),
 'create_contact': ('POST', '/contacts'),
 'update_contact': ('PUT', '/contacts/{id}'),
 'create_account': ('POST', '/accounts'),
 'update_account': ('PUT', '/accounts/{id}'),
 'create_project': ('POST', '/projects'),
 'update_project': ('PUT', '/projects/{id}'),
 'create_task': ('POST', '/tasks'),
 'update_task': ('PUT', '/tasks/{id}'),
 'create_deal': ('POST', '/crm/deals'),
 'update_deal': ('PUT', '/crm/deals/{id}'),
 'get_project': ('GET', '/project/{id}'),
 'get_task': ('GET', '/task/{id}')}


class AgiledNode(WorkflowNode):
    integration_type = "automation-agiled"
    connection_evidence = ConnectionEvidence(noun="Agiled contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return AgiledFullConfig

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, AgiledFullConfig) or config.credentials is None:
            raise ValueError("Connect an Agiled API token")
        op = config.config
        credential = config.credentials
        method, path = ROUTES[op.operation]
        body = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            resource = op.operation.split("_", 1)[1]
            path = path.replace("{id}", str(body.pop(resource + "_id")))
        # The account URL is never used as an HTTP destination.
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    params={"api_token": credential.api_token},
                    headers={"Brand": credential.brand_url, "Accept": "application/json"},
                    **({"json": body} if method != "GET" else {}))
        except httpx.HTTPError:
            return {"status": "error", "error": "Agiled request could not be confirmed; inspect writes before retrying"}
        # Never expose a token-bearing request URL or an echoed secret in an error.
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": "Agiled request failed (HTTP " + str(response.status_code) + "). Check your token, account URL and permissions."}
        try:
            if len(response.content) > 10_000_000:
                raise ValueError()
            result = response.json()
            if not isinstance(result, (dict, list)):
                raise ValueError()
        except (ValueError, UnicodeError):
            return {"status": "error", "error": "Agiled returned an unexpected JSON response"}
        if isinstance(result, dict) and (result.get("error") or result.get("errors") or result.get("status") in ("error", "fail", "failed")):
            return {"status": "error", "error": "Agiled did not confirm the request"}
        # Preserve resource envelopes and pagination links without following them.
        return {"status": "success", "data": _redact(result, credential.api_token), "http_status": response.status_code}


def _redact(value, token):
    """Agiled's User schema contains api_token; it must never become node output."""
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
            if k.lower() not in {"api_token", "access_token", "password", "secret"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value
