"""SolarWinds Service Desk v2.1, pinned against published OpenAPI 0.2.20.

Each operation makes one documented resource request. Tokens are supplied by
people; the selected region fixes the destination to a provider API host.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit, parse_qs

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

AUTH_DOC = "https://documentation.solarwinds.com/en/success_center/swsd/content/completeguidetoswsd/token-authentication-for-api-integration.htm"
HOSTS = {"us": "https://api.samanage.com", "eu": "https://apieu.samanage.com", "apj": "https://apiau.samanage.com"}


class SamanageTokenCredential(BaseModel):
    model_config = ConfigDict(title="SolarWinds Service Desk API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOC,
            "x-credential-instructions": "In SolarWinds Service Desk, open Setup > Users & Groups > Users, select your user, and copy an API token. An administrator can generate a token. Paste only the token and select your account's region. Your user's permissions apply to every operation."})
    credential_type: Literal["samanage_api_token"] = Field("samanage_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu", "apj"] = Field("us", title="Account region", description="US, Europe, or Asia Pacific / Japan.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("incident_id", "user_id", "solution_id", "problem_id", "change_id", "state_id", "assignee_id", "site_id", "department_id", mode="before", check_fields=False)
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if isinstance(value, int) and not isinstance(value, bool): value = str(value)
            if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
                raise ValueError("Use a positive numeric SolarWinds resource ID")
        return value


class _List(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number; request next_page from the previous result.")
    per_page: int = Field(50, ge=1, le=100, description="Maximum records on this page. One request per execution.")


class _Write(_Input):
    @model_validator(mode="after")
    def nonempty_update(self):
        if getattr(self, "operation", "").startswith("update_"):
            fields = self.model_dump(exclude_none=True)
            if not any(k not in {"operation", self.operation.removeprefix("update_") + "_id"} for k in fields):
                raise ValueError("Supply at least one field to update")
        return self


class SamanageListIncidentConfig(_List):
    """List incidents in SolarWinds Service Desk."""
    operation: Literal["list_incidents"] = Field("list_incidents", json_schema_extra={"ui:hidden": True})


class SamanageGetIncidentConfig(_Input):
    """Get incident in SolarWinds Service Desk."""
    operation: Literal["get_incident"] = Field("get_incident", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")


class SamanageCreateIncidentConfig(_Write):
    """Create incident in SolarWinds Service Desk."""
    operation: Literal["create_incident"] = Field("create_incident", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = None
    state_id: Optional[str] = None
    assignee_id: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    site_id: Optional[str] = None
    department_id: Optional[str] = None
    tag_list: Optional[str] = None


class SamanageUpdateIncidentConfig(_Write):
    """Update incident in SolarWinds Service Desk."""
    operation: Literal["update_incident"] = Field("update_incident", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = None
    state_id: Optional[str] = None
    assignee_id: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    site_id: Optional[str] = None
    department_id: Optional[str] = None
    tag_list: Optional[str] = None


class SamanageListUserConfig(_List):
    """List users in SolarWinds Service Desk."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class SamanageGetUserConfig(_Input):
    """Get user in SolarWinds Service Desk."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., title="User ID")


class SamanageCreateUserConfig(_Write):
    """Create user in SolarWinds Service Desk."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr = Field(...)
    title: Optional[str] = None
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    disabled: Optional[StrictBool] = None


class SamanageUpdateUserConfig(_Write):
    """Update user in SolarWinds Service Desk."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., title="User ID")
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    disabled: Optional[StrictBool] = None


class SamanageListSolutionConfig(_List):
    """List solutions in SolarWinds Service Desk."""
    operation: Literal["list_solutions"] = Field("list_solutions", json_schema_extra={"ui:hidden": True})


class SamanageGetSolutionConfig(_Input):
    """Get solution in SolarWinds Service Desk."""
    operation: Literal["get_solution"] = Field("get_solution", json_schema_extra={"ui:hidden": True})
    solution_id: str = Field(..., title="Solution ID")


class SamanageCreateSolutionConfig(_Write):
    """Create solution in SolarWinds Service Desk."""
    operation: Literal["create_solution"] = Field("create_solution", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    state: Optional[str] = None
    tag_list: Optional[str] = None


class SamanageUpdateSolutionConfig(_Write):
    """Update solution in SolarWinds Service Desk."""
    operation: Literal["update_solution"] = Field("update_solution", json_schema_extra={"ui:hidden": True})
    solution_id: str = Field(..., title="Solution ID")
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    state: Optional[str] = None
    tag_list: Optional[str] = None


class SamanageListProblemConfig(_List):
    """List problems in SolarWinds Service Desk."""
    operation: Literal["list_problems"] = Field("list_problems", json_schema_extra={"ui:hidden": True})


class SamanageGetProblemConfig(_Input):
    """Get problem in SolarWinds Service Desk."""
    operation: Literal["get_problem"] = Field("get_problem", json_schema_extra={"ui:hidden": True})
    problem_id: str = Field(..., title="Problem ID")


class SamanageCreateProblemConfig(_Write):
    """Create problem in SolarWinds Service Desk."""
    operation: Literal["create_problem"] = Field("create_problem", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    state: Optional[str] = None
    priority: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    assignee_email: Optional[EmailStr] = None
    root_cause: Optional[str] = None
    symptoms: Optional[str] = None
    workaround: Optional[str] = None


class SamanageUpdateProblemConfig(_Write):
    """Update problem in SolarWinds Service Desk."""
    operation: Literal["update_problem"] = Field("update_problem", json_schema_extra={"ui:hidden": True})
    problem_id: str = Field(..., title="Problem ID")
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    state: Optional[str] = None
    priority: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    assignee_email: Optional[EmailStr] = None
    root_cause: Optional[str] = None
    symptoms: Optional[str] = None
    workaround: Optional[str] = None


class SamanageListChangeConfig(_List):
    """List changes in SolarWinds Service Desk."""
    operation: Literal["list_changes"] = Field("list_changes", json_schema_extra={"ui:hidden": True})


class SamanageGetChangeConfig(_Input):
    """Get change in SolarWinds Service Desk."""
    operation: Literal["get_change"] = Field("get_change", json_schema_extra={"ui:hidden": True})
    change_id: str = Field(..., title="Change ID")


class SamanageCreateChangeConfig(_Write):
    """Create change in SolarWinds Service Desk."""
    operation: Literal["create_change"] = Field("create_change", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    change_type: int = Field(...)
    description: Optional[str] = None
    state: Optional[str] = None
    priority: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    assignee_email: Optional[EmailStr] = None
    change_plan: Optional[str] = None
    rollback_plan: Optional[str] = None
    test_plan: Optional[str] = None
    planned_start_at: Optional[str] = None
    planned_end_at: Optional[str] = None


class SamanageUpdateChangeConfig(_Write):
    """Update change in SolarWinds Service Desk."""
    operation: Literal["update_change"] = Field("update_change", json_schema_extra={"ui:hidden": True})
    change_id: str = Field(..., title="Change ID")
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    change_type: Optional[int] = None
    description: Optional[str] = None
    state: Optional[str] = None
    priority: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    assignee_email: Optional[EmailStr] = None
    change_plan: Optional[str] = None
    rollback_plan: Optional[str] = None
    test_plan: Optional[str] = None
    planned_start_at: Optional[str] = None
    planned_end_at: Optional[str] = None


SamanageConfig = Annotated[Union[
    SamanageListIncidentConfig,
    SamanageGetIncidentConfig,
    SamanageCreateIncidentConfig,
    SamanageUpdateIncidentConfig,
    SamanageListUserConfig,
    SamanageGetUserConfig,
    SamanageCreateUserConfig,
    SamanageUpdateUserConfig,
    SamanageListSolutionConfig,
    SamanageGetSolutionConfig,
    SamanageCreateSolutionConfig,
    SamanageUpdateSolutionConfig,
    SamanageListProblemConfig,
    SamanageGetProblemConfig,
    SamanageCreateProblemConfig,
    SamanageUpdateProblemConfig,
    SamanageListChangeConfig,
    SamanageGetChangeConfig,
    SamanageCreateChangeConfig,
    SamanageUpdateChangeConfig
], Field(discriminator="operation")]


class SamanageFullConfig(NodeConfig[SamanageConfig, SamanageTokenCredential]):
    pass


ROUTES = {'list_incidents': ['GET', 'incidents', None], 'get_incident': ['GET', 'incidents', 'incident_id'], 'create_incident': ['POST', 'incidents', None], 'update_incident': ['PUT', 'incidents', 'incident_id'], 'list_users': ['GET', 'users', None], 'get_user': ['GET', 'users', 'user_id'], 'create_user': ['POST', 'users', None], 'update_user': ['PUT', 'users', 'user_id'], 'list_solutions': ['GET', 'solutions', None], 'get_solution': ['GET', 'solutions', 'solution_id'], 'create_solution': ['POST', 'solutions', None], 'update_solution': ['PUT', 'solutions', 'solution_id'], 'list_problems': ['GET', 'problems', None], 'get_problem': ['GET', 'problems', 'problem_id'], 'create_problem': ['POST', 'problems', None], 'update_problem': ['PUT', 'problems', 'problem_id'], 'list_changes': ['GET', 'changes', None], 'get_change': ['GET', 'changes', 'change_id'], 'create_change': ['POST', 'changes', None], 'update_change': ['PUT', 'changes', 'change_id']}


class SamanageNode(WorkflowNode):
    integration_type = "automation-samanage"
    connection_evidence = ConnectionEvidence(noun="incidents", operation="list_incidents")

    @classmethod
    def get_config_model(cls):
        return SamanageFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SolarWinds Service Desk API token")
        method, resource, id_field = ROUTES[config.operation]
        path = "/" + resource
        if id_field:
            path += "/" + getattr(config, id_field)
        # Use the contract paths; the versioned Accept header selects JSON.
        origin = HOSTS[credential.region]
        headers = {"X-Samanage-Authorization": "Bearer " + credential.api_token,
            "Accept": "application/vnd.samanage.v2.1+json"}
        kwargs = {}
        if config.operation.startswith("list_"):
            kwargs["params"] = {"page": config.page, "per_page": config.per_page}
        if method in {"POST", "PUT"}:
            body = config.model_dump(exclude_none=True, exclude={"operation", id_field} if id_field else {"operation"})
            for person in ("requester", "assignee"):
                email = body.pop(person + "_email", None)
                if email is not None: body[person] = {"email": email}
            kwargs["json"] = {resource[:-1]: body}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, origin + path, headers=headers, **kwargs)
        if response.status_code != 200:
            # Preserve provider rejection text for the connect verdict, redacting
            # an echoed credential before returning it to any surface.
            message = response.text[:2000].replace(credential.api_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code,
                "error": message or "SolarWinds Service Desk refused the request"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "error": "SolarWinds Service Desk returned a non-JSON response"}
        if isinstance(payload, dict) and any(payload.get(k) for k in ("error", "errors")):
            return {"status": "error", "error": str(payload)[:2000].replace(credential.api_token, "[redacted]")}
        if config.operation.startswith("list_"):
            if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                raise ValueError("Expected a SolarWinds resource array")
            next_page = None
            link = response.links.get("next", {}).get("url")
            if link:
                parts = urlsplit(link)
                if (parts.scheme, parts.netloc) != ("https", urlsplit(origin).netloc) or parts.path not in {path, path + ".json", path + ".xml"}:
                    raise ValueError("Pagination link changed the selected resource or region")
                values = parse_qs(parts.query).get("page", [])
                if len(values) != 1 or not values[0].isdigit() or int(values[0]) <= config.page:
                    raise ValueError("Pagination did not advance")
                next_page = int(values[0])
            elif response.headers.get("X-Total-Pages"):
                if int(response.headers["X-Total-Pages"]) > config.page: next_page = config.page + 1
            return {"status": "success", "items": payload, "page": config.page,
                "next_page": next_page, "has_more": next_page is not None}
        if not isinstance(payload, dict):
            raise ValueError("Expected a SolarWinds resource object")
        # Incident responses are flat; the other resources use a singular wrapper.
        item = payload.get(resource[:-1], payload)
        if not isinstance(item, dict): raise ValueError("Expected a SolarWinds resource object")
        return {"status": "success", "item": item}
