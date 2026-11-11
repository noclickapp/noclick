"""SmartHR employee and organization automation using a tenant access token.

Each operation makes one request from the published SmartHR v1 contract.
List operations expose page navigation without downloading all employee data.
"""
from __future__ import annotations

import re
import hmac
import json
import secrets
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.agent_events import prune_empty
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SmartHRAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="SmartHR Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.smarthr.jp/api/about_api",
            "x-credential-instructions": "Ask a SmartHR administrator to issue an access token in the admin screen. Enter your tenant subdomain and paste the token. The token must permit the operations you use; NoClick checks access by reading your company records.",
        })
    credential_type: Literal["smarthr_access_token"] = Field("smarthr_access_token", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Tenant subdomain", description="The part before .smarthr.jp in your SmartHR address, for example acme.")
    access_token: str = Field(..., title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain")
    @classmethod
    def tenant(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter only your SmartHR tenant subdomain")
        return value

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if not value or len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class SmartHRListEmployeesConfig(_Input):
    """GET /v1/crews: getV1Crews."""
    operation: Literal["list_employees"] = Field("list_employees", json_schema_extra={"ui:hidden": True})
    emp_code: str | None = Field(None, description='Employee code.')
    employment_type_id: str | None = Field(None, description='Employment type id.')
    emp_status: Literal['incoming', 'employed', 'absent', 'retired'] | None = Field(None, description='Emp status.')
    gender: Literal['male', 'female'] | None = Field(None, description='Gender.')
    sort: str | None = Field(None, description='Sort.')
    entered_at_from: date | None = Field(None, description='Entered at from.')
    entered_at_to: date | None = Field(None, description='Entered at to.')
    resigned_at_from: date | None = Field(None, description='Resigned at from.')
    resigned_at_to: date | None = Field(None, description='Resigned at to.')
    user_id: str | None = Field(None, description='User id.')
    department_id: str | None = Field(None, description='Department id.')
    position_id: str | None = Field(None, description='Position id.')
    q: str | None = Field(None, description='Search employee, business name, department or position.')
    prefer_business_name: bool | None = Field(None, description='Prefer business name.')
    id: str | None = Field(None, description='SmartHR resource ID.')
    fields: str | None = Field(None, description='Comma-separated response field names.')
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')


class SmartHRGetEmployeeConfig(_Input):
    """GET /v1/crews/{id}: getV1CrewsId."""
    operation: Literal["get_employee"] = Field("get_employee", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')
    fields: str | None = Field(None, description='Comma-separated response field names.')


class SmartHRCreateEmployeeConfig(_Input):
    """POST /v1/crews: postV1Crews."""
    operation: Literal["create_employee"] = Field("create_employee", json_schema_extra={"ui:hidden": True})
    emp_status: Literal['incoming', 'employed', 'absent', 'retired'] = Field(..., description='Emp status.')
    emp_code: str | None = Field(None, description='Employee code.')
    last_name: str = Field(..., description='Family name.')
    first_name: str = Field(..., description='Given name.')
    last_name_yomi: str = Field(..., description='Family name in Katakana.')
    first_name_yomi: str = Field(..., description='Given name in Katakana.')
    gender: Literal['male', 'female'] = Field(..., description='Gender.')
    email: str | None = Field(None, description='Email.')
    position: str | None = Field(None, description='Position.')
    entered_at: date | None = Field(None, description='Entered at.')
    resigned_at: date | None = Field(None, description='Resigned at.')
    employment_type_id: str | None = Field(None, description='Employment type id.')
    department_ids: list[str] | None = Field(None, description='Department IDs.')


class SmartHRUpdateEmployeeConfig(_Input):
    """PATCH /v1/crews/{id}: patchV1CrewsId."""
    operation: Literal["update_employee"] = Field("update_employee", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')
    emp_status: Literal['incoming', 'employed', 'absent', 'retired'] = Field(..., description='Emp status.')
    emp_code: str | None = Field(None, description='Employee code.')
    last_name: str = Field(..., description='Family name.')
    first_name: str = Field(..., description='Given name.')
    last_name_yomi: str = Field(..., description='Family name in Katakana.')
    first_name_yomi: str = Field(..., description='Given name in Katakana.')
    gender: Literal['male', 'female'] = Field(..., description='Gender.')
    email: str | None = Field(None, description='Email.')
    position: str | None = Field(None, description='Position.')
    entered_at: date | None = Field(None, description='Entered at.')
    resigned_at: date | None = Field(None, description='Resigned at.')
    employment_type_id: str | None = Field(None, description='Employment type id.')
    department_ids: list[str] | None = Field(None, description='Department IDs.')


class SmartHRDeleteEmployeeConfig(_Input):
    """DELETE /v1/crews/{id}: deleteV1CrewsId."""
    operation: Literal["delete_employee"] = Field("delete_employee", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


class SmartHRListDepartmentsConfig(_Input):
    """GET /v1/departments: getV1Departments."""
    operation: Literal["list_departments"] = Field("list_departments", json_schema_extra={"ui:hidden": True})
    code: str | None = Field(None, description='Code.')
    sort: str | None = Field(None, description='Sort.')
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')


class SmartHRGetDepartmentConfig(_Input):
    """GET /v1/departments/{id}: getV1DepartmentsId."""
    operation: Literal["get_department"] = Field("get_department", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


class SmartHRCreateDepartmentConfig(_Input):
    """POST /v1/departments: postV1Departments."""
    operation: Literal["create_department"] = Field("create_department", json_schema_extra={"ui:hidden": True})
    company_id: str | None = Field(None, description='Company id.')
    name: str = Field(..., min_length=1, max_length=500, description='Name.')
    position: int | None = Field(None, description='Position.')
    code: str | None = Field(None, description='Code.')
    parent_id: str | None = Field(None, description='Parent department ID.')

    @field_validator("name")
    @classmethod
    def department_name(cls, value):
        if "/" in value:
            raise ValueError("SmartHR department names cannot contain a slash")
        return value


class SmartHRUpdateDepartmentConfig(_Input):
    """PATCH /v1/departments/{id}: patchV1DepartmentsId."""
    operation: Literal["update_department"] = Field("update_department", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')
    name: str = Field(..., min_length=1, max_length=500, description='Name.')
    position: int | None = Field(None, description='Position.')
    code: str | None = Field(None, description='Code.')
    company_id: str | None = Field(None, description='Company id.')
    parent_id: str | None = Field(None, description='Parent department ID.')

    @field_validator("name")
    @classmethod
    def department_name(cls, value):
        if "/" in value:
            raise ValueError("SmartHR department names cannot contain a slash")
        return value


class SmartHRListEmploymentTypesConfig(_Input):
    """GET /v1/employment_types: getV1EmploymentTypes."""
    operation: Literal["list_employment_types"] = Field("list_employment_types", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')


class SmartHRGetEmploymentTypeConfig(_Input):
    """GET /v1/employment_types/{id}: getV1EmploymentTypesId."""
    operation: Literal["get_employment_type"] = Field("get_employment_type", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


class SmartHRCreateEmploymentTypeConfig(_Input):
    """POST /v1/employment_types: postV1EmploymentTypes."""
    operation: Literal["create_employment_type"] = Field("create_employment_type", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500, description='Name.')
    code: str | None = Field(None, description='Code.')


class SmartHRUpdateEmploymentTypeConfig(_Input):
    """PATCH /v1/employment_types/{id}: patchV1EmploymentTypesId."""
    operation: Literal["update_employment_type"] = Field("update_employment_type", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')
    name: str = Field(..., min_length=1, max_length=500, description='Name.')
    code: str | None = Field(None, description='Code.')


class SmartHRDeleteEmploymentTypeConfig(_Input):
    """DELETE /v1/employment_types/{id}: deleteV1EmploymentTypesId."""
    operation: Literal["delete_employment_type"] = Field("delete_employment_type", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


class SmartHRListUsersConfig(_Input):
    """GET /v1/users: getV1Users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    sort: str | None = Field(None, description='Sort.')
    embed: Literal['crew', 'biz_establishment', 'biz_establishment_company', 'department_company'] | None = Field(None, description='Embed.')
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')


class SmartHRGetUserConfig(_Input):
    """GET /v1/users/{id}: getV1UsersId."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')
    embed: Literal['crew', 'biz_establishment', 'biz_establishment_company', 'department_company'] | None = Field(None, description='Embed.')


class SmartHRListCompaniesConfig(_Input):
    """GET /v1/companies: getV1Companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')
    embed: Literal['owner'] | None = Field(None, description='Embed.')


class SmartHRListBusinessEstablishmentsConfig(_Input):
    """GET /v1/biz_establishments: getV1BizEstablishments."""
    operation: Literal["list_business_establishments"] = Field("list_business_establishments", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')
    embed: Literal['soc_ins_owner', 'lab_ins_owner', 'company'] | None = Field(None, description='Embed.')


class SmartHRListJobTitlesConfig(_Input):
    """GET /v1/job_titles: getV1JobTitles."""
    operation: Literal["list_job_titles"] = Field("list_job_titles", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')
    sort: str | None = Field(None, description='Sort.')


class SmartHRGetJobTitleConfig(_Input):
    """GET /v1/job_titles/{id}: getV1JobTitlesId."""
    operation: Literal["get_job_title"] = Field("get_job_title", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


class SmartHRCreateJobTitleConfig(_Input):
    """POST /v1/job_titles: postV1JobTitles."""
    operation: Literal["create_job_title"] = Field("create_job_title", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=500, description='Name.')
    rank: int | None = Field(None, description='Rank.')
    code: str | None = Field(None, description='Code.')


class SmartHRUpdateJobTitleConfig(_Input):
    """PATCH /v1/job_titles/{id}: patchV1JobTitlesId."""
    operation: Literal["update_job_title"] = Field("update_job_title", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')
    name: str | None = Field(None, min_length=1, max_length=500, description='Name.')
    rank: int | None = Field(None, description='Rank.')
    code: str | None = Field(None, description='Code.')


class SmartHRDeleteJobTitleConfig(_Input):
    """DELETE /v1/job_titles/{id}: deleteV1JobTitlesId."""
    operation: Literal["delete_job_title"] = Field("delete_job_title", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


class SmartHRListDependentsConfig(_Input):
    """GET /v1/crews/{crew_id}/dependents: getV1CrewsCrewIdDependents."""
    operation: Literal["list_dependents"] = Field("list_dependents", json_schema_extra={"ui:hidden": True})
    crew_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='Parent employee ID.')
    page: int = Field(1, ge=1, description='Page number, starting at 1.')
    per_page: int = Field(10, ge=1, le=100, description='Records per page, at most 100.')


class SmartHRGetDependentConfig(_Input):
    """GET /v1/crews/{crew_id}/dependents/{id}: getV1CrewsCrewIdDependentsId."""
    operation: Literal["get_dependent"] = Field("get_dependent", json_schema_extra={"ui:hidden": True})
    crew_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='Parent employee ID.')
    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description='SmartHR resource ID.')


SMARTHR_WEBHOOK_EVENTS = (
    "crew_created", "crew_updated", "crew_deleted", "crew_imported",
    "dependent_created", "dependent_updated", "dependent_deleted", "dependent_imported",
)


class SmartHROnEventConfig(WebhookTriggerConfigBase):
    """API-registered events from developer.smarthr.jp/api/about_webhook."""
    operation: Literal["on_event"] = Field("on_event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Employee or Dependent Event",
        "x-category": "Triggers",
    })
    event_type: Literal[*SMARTHR_WEBHOOK_EVENTS] = Field(
        "crew_created", title="Event", description="Start when an employee or dependent is created, updated, deleted or imported.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with SmartHR automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


SmartHRConfig = Annotated[Union[
    SmartHROnEventConfig,
    SmartHRListEmployeesConfig,
    SmartHRGetEmployeeConfig,
    SmartHRCreateEmployeeConfig,
    SmartHRUpdateEmployeeConfig,
    SmartHRDeleteEmployeeConfig,
    SmartHRListDepartmentsConfig,
    SmartHRGetDepartmentConfig,
    SmartHRCreateDepartmentConfig,
    SmartHRUpdateDepartmentConfig,
    SmartHRListEmploymentTypesConfig,
    SmartHRGetEmploymentTypeConfig,
    SmartHRCreateEmploymentTypeConfig,
    SmartHRUpdateEmploymentTypeConfig,
    SmartHRDeleteEmploymentTypeConfig,
    SmartHRListUsersConfig,
    SmartHRGetUserConfig,
    SmartHRListCompaniesConfig,
    SmartHRListBusinessEstablishmentsConfig,
    SmartHRListJobTitlesConfig,
    SmartHRGetJobTitleConfig,
    SmartHRCreateJobTitleConfig,
    SmartHRUpdateJobTitleConfig,
    SmartHRDeleteJobTitleConfig,
    SmartHRListDependentsConfig,
    SmartHRGetDependentConfig
], Field(discriminator="operation")]


class SmartHRFullConfig(NodeConfig[SmartHRConfig, SmartHRAccessTokenCredential]):
    pass


ROUTES = {'list_employees': ('GET', '/v1/crews'),
 'get_employee': ('GET', '/v1/crews/{id}'),
 'create_employee': ('POST', '/v1/crews'),
 'update_employee': ('PATCH', '/v1/crews/{id}'),
 'delete_employee': ('DELETE', '/v1/crews/{id}'),
 'list_departments': ('GET', '/v1/departments'),
 'get_department': ('GET', '/v1/departments/{id}'),
 'create_department': ('POST', '/v1/departments'),
 'update_department': ('PATCH', '/v1/departments/{id}'),
 'list_employment_types': ('GET', '/v1/employment_types'),
 'get_employment_type': ('GET', '/v1/employment_types/{id}'),
 'create_employment_type': ('POST', '/v1/employment_types'),
 'update_employment_type': ('PATCH', '/v1/employment_types/{id}'),
 'delete_employment_type': ('DELETE', '/v1/employment_types/{id}'),
 'list_users': ('GET', '/v1/users'),
 'get_user': ('GET', '/v1/users/{id}'),
 'list_companies': ('GET', '/v1/companies'),
 'list_business_establishments': ('GET', '/v1/biz_establishments'),
 'list_job_titles': ('GET', '/v1/job_titles'),
 'get_job_title': ('GET', '/v1/job_titles/{id}'),
 'create_job_title': ('POST', '/v1/job_titles'),
 'update_job_title': ('PATCH', '/v1/job_titles/{id}'),
 'delete_job_title': ('DELETE', '/v1/job_titles/{id}'),
 'list_dependents': ('GET', '/v1/crews/{crew_id}/dependents'),
 'get_dependent': ('GET', '/v1/crews/{crew_id}/dependents/{id}')}

QUERY_FIELDS = {'list_employees': ['emp_code',
                    'employment_type_id',
                    'emp_status',
                    'gender',
                    'sort',
                    'entered_at_from',
                    'entered_at_to',
                    'resigned_at_from',
                    'resigned_at_to',
                    'user_id',
                    'department_id',
                    'position_id',
                    'q',
                    'prefer_business_name',
                    'id',
                    'fields',
                    'page',
                    'per_page'],
 'get_employee': ['fields'],
 'create_employee': [],
 'update_employee': [],
 'delete_employee': [],
 'list_departments': ['code', 'sort', 'page', 'per_page'],
 'get_department': [],
 'create_department': [],
 'update_department': [],
 'list_employment_types': ['page', 'per_page'],
 'get_employment_type': [],
 'create_employment_type': [],
 'update_employment_type': [],
 'delete_employment_type': [],
 'list_users': ['sort', 'embed', 'page', 'per_page'],
 'get_user': ['embed'],
 'list_companies': ['page', 'per_page', 'embed'],
 'list_business_establishments': ['page', 'per_page', 'embed'],
 'list_job_titles': ['page', 'per_page', 'sort'],
 'get_job_title': [],
 'create_job_title': [],
 'update_job_title': [],
 'delete_job_title': [],
 'list_dependents': ['page', 'per_page'],
 'get_dependent': []}


class SmartHRNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-smarthr"
    connection_evidence = ConnectionEvidence(noun="companies", operation="list_companies")

    @classmethod
    def get_config_model(cls):
        return SmartHRFullConfig

    @classmethod
    async def _request(cls, credential, method, path, *, query=None, body=None):
        credential = SmartHRAccessTokenCredential.model_validate(credential)
        url = f"https://{credential.subdomain}.smarthr.jp/api" + path
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, params=query,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("message", "SmartHR request failed")
            except (ValueError, AttributeError):
                message = "SmartHR request failed"
            message = str(message).replace(credential.access_token, "[redacted]")[:2000]
            raise ValueError(f"SmartHR HTTP {response.status_code}: {message}")
        return response

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = SmartHROnEventConfig.model_validate(config).event_type
        secret = secrets.token_urlsafe(32)
        response = await cls._request(credential, "POST", "/v1/webhooks", body={
            "url": webhook_url, "secret_token": secret, "expose_only_id": False,
            **{name: name == event for name in SMARTHR_WEBHOOK_EVENTS},
        })
        endpoint_id = response.json().get("id")
        if not isinstance(endpoint_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", endpoint_id):
            raise ValueError("SmartHR did not return a valid webhook ID")
        return {"external_webhook_id": endpoint_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get("external_webhook_id")
        if not endpoint_id:
            raise ValueError("SmartHR webhook ID is required for removal")
        endpoint_id = SmartHRGetEmployeeConfig(id=str(endpoint_id)).id
        await cls._request(credential, "DELETE", f"/v1/webhooks/{endpoint_id}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": SmartHROnEventConfig.model_validate(config).event_type}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # SmartHR sends the configured secret verbatim, not a body HMAC.
        secret = config.get("signing_secret")
        token = next((value for key, value in headers.items() if key.lower() == "x-smarthr-token"), "")
        return bool(isinstance(secret, str) and secret and isinstance(token, str)
                    and hmac.compare_digest(secret.encode(), token.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event") == SmartHROnEventConfig.model_validate(config).event_type

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("event")
        if event not in SMARTHR_WEBHOOK_EVENTS:
            return super().resolve_agent_event(output)
        noun, action = event.split("_", 1)
        label = "employee" if noun == "crew" else "dependent"
        sender = output.get("sender") or {}
        actor = " ".join(str(sender.get(k) or "") for k in ("last_name", "first_name")).strip()
        lines = [f"SmartHR {label} {action}"]
        if actor:
            lines.append(f"By: {actor} (employee ID {sender.get('id')})")
        if output.get("triggered_at"):
            lines.append(f"At: {output['triggered_at']}")
        if action == "imported":
            result = output.get(f"{noun}_import_result") or {}
            created = result.get(f"created_{noun}s") or []
            updated = result.get(f"updated_{noun}s") or []
            records = created + updated
            lines.append(f"Imported: {len(created)} created, {len(updated)} updated")
        else:
            record = output.get(noun) or {}
            records = [record]
        for record in records:
            name = " ".join(str(record.get(k) or "") for k in ("last_name", "first_name")).strip()
            lines.append(f"{label.title()}: {name} (ID {record.get('id')})")
            if noun == "dependent":
                lines.append(f"Employee ID: {record.get('crew_id')}")
            lines.append(json.dumps(prune_empty(record, max_str=1000), ensure_ascii=False)[:4000])
        lines.append("Use get_employee id=<employee ID> or get_dependent crew_id=<employee ID> id=<dependent ID> for current details; deleted records are no longer available.")
        return {"text": "\n".join(lines)[:12000], "title": f"SmartHR {label} {action}"}

    async def execute(self, inputs):
        if isinstance(self.config.config, SmartHROnEventConfig):
            return self.no_event_output("on_event")

        if not self.config.credentials:
            raise ValueError("Connect a SmartHR access token")
        credential = self.config.credentials
        config = self.config.config.model_dump(mode="json", exclude_none=True)
        operation = config.pop("operation")
        method, path = ROUTES[operation]
        for field in ("crew_id", "id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", config.pop(field))
        query = {key: config.pop(key) for key in QUERY_FIELDS[operation] if key in config}
        # httpx serializes booleans as lowercase JSON-compatible query values.
        url = f"https://{credential.subdomain}.smarthr.jp/api" + path
        response = await self._request(credential.model_dump(), method, path, query=query,
                                       body=config if method in {"POST", "PATCH"} else None)
        if response.status_code == 204:
            return {"status": "success", "operation": operation, "acknowledged": True}
        payload = response.json()
        if isinstance(payload, dict) and ("error" in payload or "errors" in payload or payload.get("type") in {"unauthorized_token", "forbidden"}):
            raise ValueError("SmartHR returned an error response")
        if operation.startswith("list_"):
            if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                raise ValueError("Expected a SmartHR resource list")
            next_page = None
            next_url = response.links.get("next", {}).get("url")
            if next_url:
                parsed = urlsplit(next_url)
                current = urlsplit(url)
                if parsed.scheme != current.scheme or parsed.netloc != current.netloc or parsed.path != current.path:
                    raise ValueError("SmartHR returned an unexpected pagination URL")
                values = parse_qs(parsed.query).get("page", [])
                if len(values) != 1 or not values[0].isdigit() or int(values[0]) <= query.get("page", 1):
                    raise ValueError("SmartHR pagination did not advance")
                next_page = int(values[0])
            return {"status": "success", "items": payload, "page": query.get("page", 1), "next_page": next_page}
        if not isinstance(payload, dict):
            raise ValueError("Expected a SmartHR resource object")
        return {"status": "success", "data": payload}
