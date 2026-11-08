"""Pingdom API 3.1 uptime checks, maintenance, alerts and reports.

Contract: https://docs.pingdom.com/API_3.1.yaml
Each operation issues one documented request; writes return acknowledgement,
not an assertion of downstream alert delivery or a verified state change.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.pingdom.com/api/3.1"

class PingdomAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Pingdom API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://my.pingdom.com/", "x-credential-instructions":
            "In My Pingdom, generate an API token. Paste the token here. Read access supports reports and lists; Read/Write access is required to create, modify or delete checks and maintenance windows. NoClick sends it as a Bearer token to api.pingdom.com."})
    credential_type: Literal["pingdom_api_token"] = Field("pingdom_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste only the API token")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

class Page(Input):
    limit: int = Field(100, ge=1, le=1000, description="One page only. Increase offset by limit for the next page.")
    offset: int = Field(0, ge=0)

class Period(Input):
    from_time: int | None = Field(None, ge=0, description="Inclusive start, Unix seconds. Omit for provider default.")
    to_time: int | None = Field(None, ge=0, description="End, Unix seconds. Omit for provider default.")
    @model_validator(mode="after")
    def period(self):
        if self.from_time is not None and self.to_time is not None and self.to_time <= self.from_time:
            raise ValueError("End must follow start")
        return self

class Check(Input):
    check_id: int = Field(..., gt=0, description="Pingdom uptime check ID")

class Maintenance(Input):
    maintenance_id: int = Field(..., gt=0)

class ListChecks(Page):
    operation: Literal["list_checks"] = "list_checks"
    tags: str | None = Field(None, description="Comma separated check tags")
    include_tags: bool = True
    include_severity: bool = False

class GetCheck(Check):
    operation: Literal["get_check"] = "get_check"
    include_teams: bool = False

class CreateCheck(Input):
    operation: Literal["create_check"] = "create_check"
    name: str = Field(..., min_length=1)
    host: str = Field(..., min_length=1, description="Target hostname, without scheme or path")
    url: str = Field("/", description="HTTP path on the target host")
    encryption: bool = True
    paused: bool = False
    resolution: Literal[1, 5, 15, 30, 60] = 5
    @field_validator("host")
    @classmethod
    def host_name(cls, value):
        if any(c.isspace() for c in value) or any(c in value for c in "/?#@"):
            raise ValueError("Use a hostname without scheme or path")
        return value
    @field_validator("url")
    @classmethod
    def path(cls, value):
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("Use an HTTP path beginning with one slash")
        return value

class UpdateCheck(Check):
    operation: Literal["update_check"] = "update_check"
    name: str | None = Field(None, min_length=1)
    paused: bool | None = None
    resolution: Literal[1, 5, 15, 30, 60] | None = None
    tags: list[str] | None = None
    custom_message: str | None = None
    @model_validator(mode="after")
    def changed(self):
        if not any(getattr(self, k) is not None for k in ("name", "paused", "resolution", "tags", "custom_message")):
            raise ValueError("Provide at least one setting to update")
        return self

class DeleteCheck(Check):
    operation: Literal["delete_check"] = "delete_check"

class ListMaintenance(Page):
    operation: Literal["list_maintenance"] = "list_maintenance"
    orderby: Literal["description", "from", "to", "effectiveto"] = "from"
    order: Literal["asc", "desc"] = "asc"

class GetMaintenance(Maintenance):
    operation: Literal["get_maintenance"] = "get_maintenance"

class MaintenanceWrite(Input):
    description: str = Field(..., min_length=1)
    from_time: int = Field(..., ge=1, description="Future start in Unix seconds; 1 means now")
    to_time: int = Field(..., ge=1, description="Future end in Unix seconds")
    uptimeids: list[int] | None = None
    tmsids: list[int] | None = None
    @model_validator(mode="after")
    def window(self):
        if self.to_time <= self.from_time:
            raise ValueError("End must follow start")
        if any(type(x) is not int or x <= 0 for x in (self.uptimeids or []) + (self.tmsids or [])):
            raise ValueError("Use positive check IDs")
        return self

class CreateMaintenance(MaintenanceWrite):
    operation: Literal["create_maintenance"] = "create_maintenance"

class UpdateMaintenance(MaintenanceWrite, Maintenance):
    operation: Literal["update_maintenance"] = "update_maintenance"

class DeleteMaintenance(Maintenance):
    operation: Literal["delete_maintenance"] = "delete_maintenance"

class ListResults(Check, Page, Period):
    operation: Literal["list_results"] = "list_results"
    includeanalysis: bool = False

class GetAverage(Check, Period):
    operation: Literal["get_average"] = "get_average"
    includeuptime: bool = True

class GetOutages(Check, Period):
    operation: Literal["get_outages"] = "get_outages"
    order: Literal["asc", "desc"] = "asc"

class GetPerformance(Check, Period):
    operation: Literal["get_performance"] = "get_performance"
    resolution: Literal["hour", "day", "week"] = "hour"
    includeuptime: bool = True
    order: Literal["asc", "desc"] = "asc"

class ListActions(Page, Period):
    operation: Literal["list_actions"] = "list_actions"
    checkids: str | None = Field(None, description="Comma separated check IDs")
    status: Literal["sent", "delivered", "error", "notdelivered", "nocredits"] | None = None
    via: Literal["email", "sms", "twitter", "apns", "agcm"] | None = None

class ListAnalyses(Check, Page, Period):
    operation: Literal["list_analyses"] = "list_analyses"

class ListContacts(Input):
    operation: Literal["list_contacts"] = "list_contacts"

class GetContact(Input):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: int = Field(..., gt=0)

class ListTeams(Input):
    operation: Literal["list_teams"] = "list_teams"

class GetCredits(Input):
    operation: Literal["get_credits"] = "get_credits"

PingdomConfig = Annotated[Union[ListChecks, GetCheck, CreateCheck, UpdateCheck, DeleteCheck,
    ListMaintenance, GetMaintenance, CreateMaintenance, UpdateMaintenance, DeleteMaintenance,
    ListResults, GetAverage, GetOutages, GetPerformance, ListActions, ListAnalyses,
    ListContacts, GetContact, ListTeams, GetCredits], Field(discriminator="operation")]

class PingdomFullConfig(NodeConfig[PingdomConfig, PingdomAPITokenCredential]):
    pass

# Each operation maps to exactly one published API operation.
ROUTES = {
    "list_checks": ("GET", "/checks", "checks"),
    "get_check": ("GET", "/checks/{check_id}", "check"),
    "create_check": ("POST", "/checks", "check"),
    "update_check": ("PUT", "/checks/{check_id}", "message"),
    "delete_check": ("DELETE", "/checks/{check_id}", "message"),
    "list_maintenance": ("GET", "/maintenance", "maintenance"),
    "get_maintenance": ("GET", "/maintenance/{maintenance_id}", "maintenance"),
    "create_maintenance": ("POST", "/maintenance", "maintenance"),
    "update_maintenance": ("PUT", "/maintenance/{maintenance_id}", "message"),
    "delete_maintenance": ("DELETE", "/maintenance/{maintenance_id}", "message"),
    "list_results": ("GET", "/results/{check_id}", "results"),
    "get_average": ("GET", "/summary.average/{check_id}", "summary"),
    "get_outages": ("GET", "/summary.outage/{check_id}", "summary"),
    "get_performance": ("GET", "/summary.performance/{check_id}", "summary"),
    "list_actions": ("GET", "/actions", "actions"),
    "list_analyses": ("GET", "/analysis/{check_id}", "analysis"),
    "list_contacts": ("GET", "/alerting/contacts", "contacts"),
    "get_contact": ("GET", "/alerting/contacts/{contact_id}", "contact"),
    "list_teams": ("GET", "/alerting/teams", "teams"),
    "get_credits": ("GET", "/credits", "credits"),
}

def request_for(config):
    method, path, key = ROUTES[config.operation]
    values = config.model_dump(exclude_none=True, exclude={"operation"})
    for field in ("check_id", "maintenance_id", "contact_id"):
        if field in values:
            path = path.replace("{" + field + "}", str(values.pop(field)))
    for source, target in (("from_time", "from"), ("to_time", "to")):
        if source in values:
            values[target] = values.pop(source)
    if config.operation == "create_check":
        values["type"] = "http"
    if method == "GET":
        values = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
    return method, path, key, values


def redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {redact(k, token): redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, token) for v in value]
    return value

class PingdomNode(WorkflowNode):
    integration_type = "automation-pingdom"
    connection_evidence = ConnectionEvidence(noun="uptime checks", operation="list_checks")

    @classmethod
    def get_config_model(cls):
        return PingdomFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Pingdom API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path, key, values = request_for(config)
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values} if values else {}))
        except httpx.RequestError:
            raise ValueError("Pingdom request could not be confirmed; inspect writes before retrying") from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Pingdom returned an unexpected response; inspect writes before retrying") from None
        if not isinstance(body, dict):
            raise ValueError("Pingdom returned an unexpected response")
        if response.status_code != 200 or "error" in body:
            error = body.get("error")
            message = error.get("errormessage") if isinstance(error, dict) else None
            result = {"status": "error", "success": False, "http_status": response.status_code,
                "message": message if isinstance(message, str) else "Pingdom request was not confirmed"}
        else:
            # API docs explicitly permit absent response attributes; retain the envelope.
            result = {"status": "success", "success": True, "http_status": response.status_code, "data": body}
            if isinstance(body.get(key), list):
                result["items"] = body[key]
            if method != "GET":
                result["acknowledged"] = True
                result["state_verified"] = False
        result = redact(result, token)
        await self.emit(result)
        return result
