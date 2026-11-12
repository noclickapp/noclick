"""Ezekia v4 recruiting records, pinned to the provider's OpenAPI 2.1.1.

Each operation makes one documented request. Lists return one page; pagination
metadata is preserved without following provider-supplied URLs. Writes are never
retried automatically, including when their outcome cannot be confirmed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://ezekia.com/api/v4"
CREDENTIAL_TYPE = "ezekia_api_token"


class EzekiaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Ezekia API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://ezekia.com/docs",
            "x-credential-instructions": "Paste your Ezekia API bearer token. NoClick sends it only to ezekia.com and reads the authenticated user to verify your account. Your token must have access to the records you use.",
        })
    credential_type: Literal["ezekia_api_token"] = Field("ezekia_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page to read; this operation returns one page only.")
    count: int = Field(50, ge=1, le=100, description="Records per page.")
    query: str | None = Field(None, max_length=1000, description="Search text matched by Ezekia.")


class _PersonFields(_Input):
    firstName: str = Field(..., min_length=1, max_length=500, title="First name")
    lastName: str = Field(..., min_length=1, max_length=500, title="Last name")
    companyName: str = Field(..., min_length=1, max_length=500, title="Company name", description="Free-text employer name; this does not link an existing company record.")
    headline: str | None = Field(None, max_length=5000)
    title: str | None = Field(None, max_length=500, title="Job title")
    department: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=500, description="Work email for the new person.")
    phone: str | None = Field(None, max_length=100, description="Work phone for the new person.")


class _CompanyFields(_Input):
    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=20000)
    email: str | None = Field(None, max_length=500)
    phone: str | None = Field(None, max_length=100)
    division: str | None = Field(None, max_length=500)
    size: str | None = Field(None, max_length=500)
    specialities: str | None = Field(None, max_length=5000)


class _ProjectFields(_Input):
    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=20000)
    projectId: str | None = Field(None, max_length=200, title="Project reference", description="Your external project reference, distinct from the numeric record ID.")
    companyId: str | None = Field(None, max_length=30, pattern=r"^[1-9][0-9]*$", title="Company ID")
    leadId: int | None = Field(None, ge=1, title="Contact person ID")
    probability: int | None = Field(None, ge=0, le=100)


class EzekiaGetMe(_Input):
    """Read the authenticated Ezekia user."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class EzekiaListPeople(_Page):
    """List people."""
    operation: Literal["list_people"] = Field("list_people", json_schema_extra={"ui:hidden": True})


class EzekiaGetPerson(_Input):
    """Get person."""
    operation: Literal["get_person"] = Field("get_person", json_schema_extra={"ui:hidden": True})
    person_id: int = Field(..., ge=1, title="Person record ID")


class EzekiaCreatePerson(_PersonFields):
    """Create person."""
    operation: Literal["create_person"] = Field("create_person", json_schema_extra={"ui:hidden": True})


class EzekiaListCompanies(_Page):
    """List companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class EzekiaGetCompany(_Input):
    """Get company."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, title="Company record ID")


class EzekiaCreateCompany(_CompanyFields):
    """Create company."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})


class EzekiaUpdateCompany(_CompanyFields):
    """Update company."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, title="Company record ID")


class EzekiaListProjects(_Page):
    """List projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class EzekiaGetProject(_Input):
    """Get project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., ge=1, title="Project record ID")


class EzekiaCreateProject(_ProjectFields):
    """Create project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    label: Literal["assignment", "opportunity", "list"] = Field(..., title="Project kind")


class EzekiaUpdateProject(_ProjectFields):
    """Update project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., ge=1, title="Project record ID")


class EzekiaListTasks(_Input):
    """List tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000)
    done: StrictBool | None = None
    overdue: StrictBool | None = None
    order: Literal["asc", "desc"] = Field("asc")
    sort: Literal["start_date_utc", "created_at", "updated_at", "title"] = Field("start_date_utc")


class EzekiaGetTask(_Input):
    """Get task."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1)


class EzekiaSetTaskDone(_Input):
    """Set task done."""
    operation: Literal["set_task_done"] = Field("set_task_done", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1)
    done: StrictBool = Field(..., description="Whether this task is complete.")


class EzekiaSetTaskPinned(_Input):
    """Set task pinned."""
    operation: Literal["set_task_pinned"] = Field("set_task_pinned", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1)
    pinned: StrictBool = Field(..., description="Whether this task is pinned.")


class EzekiaDeleteTask(_Input):
    """Delete task."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1)


# Ezekia's own MCP server: agents get its tools through a person's Ezekia sign-in.
EzekiaMcpCredential = mcp_credential("ezekia", "https://mcp.ezekia.com", app="Ezekia")
EzekiaCredential = Union[EzekiaAPITokenCredential, EzekiaMcpCredential]


EzekiaConfig = Annotated[Union[
    EzekiaGetMe,
    EzekiaListPeople,
    EzekiaGetPerson,
    EzekiaCreatePerson,
    EzekiaListCompanies,
    EzekiaGetCompany,
    EzekiaCreateCompany,
    EzekiaUpdateCompany,
    EzekiaListProjects,
    EzekiaGetProject,
    EzekiaCreateProject,
    EzekiaUpdateProject,
    EzekiaListTasks,
    EzekiaGetTask,
    EzekiaSetTaskDone,
    EzekiaSetTaskPinned,
    EzekiaDeleteTask
], Field(discriminator="operation")]


class EzekiaFullConfig(NodeConfig[EzekiaConfig, EzekiaCredential]):
    pass


OPERATIONS = {'get_me': ('GET', '/me'),
 'list_people': ('GET', '/people'),
 'get_person': ('GET', '/people/{person_id}'),
 'create_person': ('POST', '/people'),
 'list_companies': ('GET', '/companies'),
 'get_company': ('GET', '/companies/{company_id}'),
 'create_company': ('POST', '/companies'),
 'update_company': ('PUT', '/companies/{company_id}'),
 'list_projects': ('GET', '/projects'),
 'get_project': ('GET', '/projects/{project_id}'),
 'create_project': ('POST', '/projects'),
 'update_project': ('PUT', '/projects/{project_id}'),
 'list_tasks': ('GET', '/tasks'),
 'get_task': ('GET', '/tasks/{task_id}'),
 'set_task_done': ('PUT', '/tasks/{task_id}/done'),
 'set_task_pinned': ('PUT', '/tasks/{task_id}/pinned'),
 'delete_task': ('DELETE', '/tasks/{task_id}')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class EzekiaNode(WorkflowNode):
    integration_type = "automation-ezekia"
    credential_provider_labels = {"ezekia": "Ezekia Account"}
    connection_evidence = ConnectionEvidence(noun="Ezekia account", identity_operation="get_me", identity_keys=("fullName", "email"))

    @classmethod
    def get_config_model(cls):
        return EzekiaFullConfig

    @classmethod
    def _check_credential_type(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Attach an Ezekia API token credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential_type(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential_type(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Ezekia API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for field in ("person_id", "company_id", "project_id", "task_id"):
            if field in values:
                path = path.replace("{" + field + "}", str(values.pop(field)))
        if config.operation in {"create_company", "update_company", "create_project", "update_project"}:
            values["_type"] = "info"
        if config.operation == "create_person":
            for field, collection, key in (("email", "emails", "address"), ("phone", "phones", "number")):
                if field in values:
                    values[collection] = [{key: values.pop(field), "label": "work", "isDefault": True}]
        kwargs = {"params": values} if method == "GET" else ({"json": values} if method != "DELETE" else {})
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
            code = response.status_code
            if code != 200:
                message = "Ezekia request was not confirmed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"][:2000]
                except ValueError:
                    pass
                result = {"status": "error", "success": False, "http_status": code, "error": message,
                    "write_outcome": "unverified" if method != "GET" and (code < 400 or code >= 500) else None}
            else:
                if len(response.content) > 8_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Expected a bounded JSON response from Ezekia")
                body = response.json()
                if not isinstance(body, dict) or body.get("error") or body.get("errors") or body.get("success") is False:
                    raise ValueError("Ezekia returned an unconfirmed response")
                if config.operation == "get_me":
                    if type(body.get("id")) is not int or not all(isinstance(body.get(k), str) and body[k] for k in ("email", "fullName")):
                        raise ValueError("Ezekia user identity could not be verified")
                    result = {"status": "success", "success": True, **{k: body[k] for k in ("id", "email", "fullName")}}
                elif method == "DELETE":
                    if body.get("success") is not True:
                        raise ValueError("Ezekia did not confirm deletion")
                    result = {"status": "success", "success": True, "deleted": True}
                else:
                    if "data" not in body or not isinstance(body["data"], (dict, list)):
                        raise ValueError("Ezekia response has no record data")
                    if config.operation.startswith("list_") and not isinstance(body["data"], list):
                        raise ValueError("Ezekia list response is invalid")
                    result = {"status": "success", "success": True, "data": body.get("data", body)}
                    for key in ("links", "meta"):
                        if key in body:
                            result[key] = body[key]
        except (httpx.HTTPError, OSError, SSRFError):
            result = {"status": "error", "success": False, "error": "Ezekia request did not complete",
                "write_outcome": "unverified" if method != "GET" else None}
        except (ValueError, TypeError):
            result = {"status": "error", "success": False, "error": "Ezekia response could not be verified",
                "write_outcome": "unverified" if method != "GET" else None}
        result = _redact(result, token)
        await self.emit(result)
        return result
