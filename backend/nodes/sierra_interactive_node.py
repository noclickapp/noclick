"""Sierra Interactive Zapier API v1: fixed operations from the published contract.

The contract leaves response objects unstructured; preserve their JSON without
inventing IDs, pagination, delivery guarantees or write readback verification.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://api.sierrainteractivedev.com:1444"
CREDENTIAL_TYPE = "sierra_interactive_api_key"


class SierraInteractiveAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Sierra Interactive API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.sierrainteractivedev.com/swagger/ui/index",
            "x-credential-instructions": "Paste your Sierra Interactive user API key. NoClick sends it in the Sierra-User-ApiKey header to Sierra's API. The connection check reads your account's sites; it does not verify write permissions.",
        })
    credential_type: Literal["sierra_interactive_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Sierra Interactive API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste an API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class AgentResolveAttributes(_Input):
    agentUserId: int | None = None
    agentUserEmail: str | None = None
    agentUserPhone: str | None = None
    agentUserFirstName: str | None = None
    agentUserLastName: str | None = None
    agentSiteId: int | None = None

class LeadApiSaveReqModel(_Input):
    firstName: str | None = None
    lastName: str | None = None
    leadStatus: str | None = None
    lenderStatus: str | None = None
    listingAgentStatus: str | None = None
    email: str | None = None
    emailStatus: str | None = None
    phone: str | None = None
    phoneStatus: str | None = None
    birthDate: str | None = None
    referralFee: bool | None = None
    sendRegistrationEmail: bool | None = None
    assignTo: AgentResolveAttributes | None = None
    lender: AgentResolveAttributes | None = None
    listingAgent: AgentResolveAttributes | None = None
    sourceType: str | None = None
    note: str | None = None
    siteId: int | None = None
    leadType: str | None = None
    source: str | None = None
    tags: list[str] | None = None
    removeTags: list[str] | None = None
    partnerLink: str | None = None
    streetAddress: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    shortSummary: str | None = None
    homeAnniversaryDate: str | None = None

class ZapierTaskReqModel(_Input):
    description: str | None = None
    dueDate: str | None = None
    type: str | None = None

class NoteApiModel(_Input):
    message: str | None = None
    shouldNotify: str | None = None

class ListingApiSaveReqModel(_Input):
    leadIdOrEmail: str | None = None
    mlsNumber: str | None = None
    mlsRegion: str | None = None

class ListingApiLeadRequestModel(_Input):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    mlsNumber: str | None = None
    mlsRegion: str | None = None
    assignTo: AgentResolveAttributes | None = None
    leadId: int | None = None
    contactPreference: str | None = None
    preferredTimeToContact: str | None = None
    preferredAppointmentDay: str | None = None
    preferredAppointmentTime: str | None = None
    comments: str | None = None
    sendAutoResponder: bool | None = None

class ActionPlanApplyModel(_Input):
    actionPlanId: int | None = None
    note: str | None = None
    leadIdOrEmailOrPhone: str | None = None
    startNextDayIfAppliedAfter: str | None = None

class ActionPlanStopModel(_Input):
    actionPlanId: int | None = None
    note: str | None = None
    leadIdOrEmailOrPhone: str | None = None

class ActionPlanStopModel_v2(_Input):
    actionPlanId: int | None = None
    note: str | None = None
    leadIdOrEmailOrPhone: str | None = None
    actionPlanStatus: str | None = None


class CheckConnectionConfig(_Input):
    """GET /zapier/validateAPIKey."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class CreateLeadConfig(LeadApiSaveReqModel):
    """POST /zapier/leads."""
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})
    firstName: str = Field(..., min_length=1)
    lastName: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)


class UpdateLeadConfig(LeadApiSaveReqModel):
    """PUT /zapier/leads/{leadIdOrEmailOrPhone}."""
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    leadIdOrEmailOrPhone: str = Field(..., min_length=1, max_length=320, description="Exact lead ID or contact identifier; sent as one encoded path segment.")


class FindLeadConfig(_Input):
    """PUT /zapier/findLead/{leadIdOrEmail}."""
    operation: Literal["find_lead"] = Field("find_lead", json_schema_extra={"ui:hidden": True})
    leadIdOrEmail: str = Field(..., min_length=1, max_length=320, description="Exact lead ID or contact identifier; sent as one encoded path segment.")


class CreateTaskConfig(ZapierTaskReqModel):
    """POST /zapier/leads/{leadIdOrEmail}/createTask."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    leadIdOrEmail: str = Field(..., min_length=1, max_length=320, description="Exact lead ID or contact identifier; sent as one encoded path segment.")
    description: str = Field(..., min_length=1)
    dueDate: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)


class AddNoteConfig(NoteApiModel):
    """POST /zapier/leads/{leadIdOrEmail}/note."""
    operation: Literal["add_note"] = Field("add_note", json_schema_extra={"ui:hidden": True})
    leadIdOrEmail: str = Field(..., min_length=1, max_length=320, description="Exact lead ID or contact identifier; sent as one encoded path segment.")
    message: str = Field(..., min_length=1)


class SaveListingConfig(ListingApiSaveReqModel):
    """POST /zapier/savedListings."""
    operation: Literal["save_listing"] = Field("save_listing", json_schema_extra={"ui:hidden": True})
    leadIdOrEmail: str = Field(..., min_length=1)
    mlsNumber: str = Field(..., min_length=1)
    mlsRegion: str = Field(..., min_length=1)


class RequestInformationConfig(ListingApiLeadRequestModel):
    """POST /zapier/requestInfo."""
    operation: Literal["request_information"] = Field("request_information", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    mlsNumber: str = Field(..., min_length=1)
    mlsRegion: str = Field(..., min_length=1)


class ScheduleShowingConfig(ListingApiLeadRequestModel):
    """POST /zapier/scheduleShowing."""
    operation: Literal["schedule_showing"] = Field("schedule_showing", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    mlsNumber: str = Field(..., min_length=1)
    mlsRegion: str = Field(..., min_length=1)


class ApplyTraditionalActionPlanConfig(ActionPlanApplyModel):
    """PUT /zapier/applyTraditionalActionPlan."""
    operation: Literal["apply_traditional_action_plan"] = Field("apply_traditional_action_plan", json_schema_extra={"ui:hidden": True})
    actionPlanId: int = Field(..., ge=1)
    leadIdOrEmailOrPhone: str = Field(..., min_length=1)


class ApplyAutomatedActionPlanConfig(ActionPlanApplyModel):
    """PUT /zapier/applyFullyAutomatedActionPlan."""
    operation: Literal["apply_automated_action_plan"] = Field("apply_automated_action_plan", json_schema_extra={"ui:hidden": True})
    actionPlanId: int = Field(..., ge=1)
    leadIdOrEmailOrPhone: str = Field(..., min_length=1)


class StopTraditionalActionPlanConfig(ActionPlanStopModel):
    """PUT /zapier/stopTraditionalActionPlan."""
    operation: Literal["stop_traditional_action_plan"] = Field("stop_traditional_action_plan", json_schema_extra={"ui:hidden": True})
    actionPlanId: int = Field(..., ge=1)
    leadIdOrEmailOrPhone: str = Field(..., min_length=1)


class StopAutomatedActionPlanConfig(ActionPlanStopModel_v2):
    """PUT /zapier/v2/stopFullyAutomatedActionPlan."""
    operation: Literal["stop_automated_action_plan"] = Field("stop_automated_action_plan", json_schema_extra={"ui:hidden": True})
    actionPlanId: int = Field(..., ge=1)
    leadIdOrEmailOrPhone: str = Field(..., min_length=1)


class ListAgentsConfig(_Input):
    """GET /zapier/agents."""
    operation: Literal["list_agents"] = Field("list_agents", json_schema_extra={"ui:hidden": True})


class ListSitesConfig(_Input):
    """GET /zapier/sites."""
    operation: Literal["list_sites"] = Field("list_sites", json_schema_extra={"ui:hidden": True})


class ListLeadSourcesConfig(_Input):
    """GET /zapier/leadSource."""
    operation: Literal["list_lead_sources"] = Field("list_lead_sources", json_schema_extra={"ui:hidden": True})


class ListLeadStatusesConfig(_Input):
    """GET /zapier/leadStatus."""
    operation: Literal["list_lead_statuses"] = Field("list_lead_statuses", json_schema_extra={"ui:hidden": True})


class ListEmailStatusesConfig(_Input):
    """GET /zapier/emailStatus."""
    operation: Literal["list_email_statuses"] = Field("list_email_statuses", json_schema_extra={"ui:hidden": True})


class ListPhoneStatusesConfig(_Input):
    """GET /zapier/phoneStatus."""
    operation: Literal["list_phone_statuses"] = Field("list_phone_statuses", json_schema_extra={"ui:hidden": True})


class ListTaskTypesConfig(_Input):
    """GET /zapier/taskType."""
    operation: Literal["list_task_types"] = Field("list_task_types", json_schema_extra={"ui:hidden": True})


class ListMlsRegionsConfig(_Input):
    """GET /zapier/mlsRegion."""
    operation: Literal["list_mls_regions"] = Field("list_mls_regions", json_schema_extra={"ui:hidden": True})


class ListLeadTypesConfig(_Input):
    """GET /zapier/leadTypes."""
    operation: Literal["list_lead_types"] = Field("list_lead_types", json_schema_extra={"ui:hidden": True})


class ListTagsConfig(_Input):
    """GET /zapier/tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class ListTraditionalActionPlansConfig(_Input):
    """GET /zapier/traditionalActionPlans."""
    operation: Literal["list_traditional_action_plans"] = Field("list_traditional_action_plans", json_schema_extra={"ui:hidden": True})


class ListAutomatedActionPlansConfig(_Input):
    """GET /zapier/fullyAutomatedActionPlans."""
    operation: Literal["list_automated_action_plans"] = Field("list_automated_action_plans", json_schema_extra={"ui:hidden": True})


SierraInteractiveConfig = Annotated[Union[
    CheckConnectionConfig,
    CreateLeadConfig,
    UpdateLeadConfig,
    FindLeadConfig,
    CreateTaskConfig,
    AddNoteConfig,
    SaveListingConfig,
    RequestInformationConfig,
    ScheduleShowingConfig,
    ApplyTraditionalActionPlanConfig,
    ApplyAutomatedActionPlanConfig,
    StopTraditionalActionPlanConfig,
    StopAutomatedActionPlanConfig,
    ListAgentsConfig,
    ListSitesConfig,
    ListLeadSourcesConfig,
    ListLeadStatusesConfig,
    ListEmailStatusesConfig,
    ListPhoneStatusesConfig,
    ListTaskTypesConfig,
    ListMlsRegionsConfig,
    ListLeadTypesConfig,
    ListTagsConfig,
    ListTraditionalActionPlansConfig,
    ListAutomatedActionPlansConfig
], Field(discriminator="operation")]


class SierraInteractiveNodeConfig(NodeConfig[SierraInteractiveConfig, SierraInteractiveAPIKeyCredential]):
    pass


ROUTES = {
    "check_connection": ("GET", "/zapier/validateAPIKey"),
    "create_lead": ("POST", "/zapier/leads"),
    "update_lead": ("PUT", "/zapier/leads/{leadIdOrEmailOrPhone}"),
    "find_lead": ("PUT", "/zapier/findLead/{leadIdOrEmail}"),
    "create_task": ("POST", "/zapier/leads/{leadIdOrEmail}/createTask"),
    "add_note": ("POST", "/zapier/leads/{leadIdOrEmail}/note"),
    "save_listing": ("POST", "/zapier/savedListings"),
    "request_information": ("POST", "/zapier/requestInfo"),
    "schedule_showing": ("POST", "/zapier/scheduleShowing"),
    "apply_traditional_action_plan": ("PUT", "/zapier/applyTraditionalActionPlan"),
    "apply_automated_action_plan": ("PUT", "/zapier/applyFullyAutomatedActionPlan"),
    "stop_traditional_action_plan": ("PUT", "/zapier/stopTraditionalActionPlan"),
    "stop_automated_action_plan": ("PUT", "/zapier/v2/stopFullyAutomatedActionPlan"),
    "list_agents": ("GET", "/zapier/agents"),
    "list_sites": ("GET", "/zapier/sites"),
    "list_lead_sources": ("GET", "/zapier/leadSource"),
    "list_lead_statuses": ("GET", "/zapier/leadStatus"),
    "list_email_statuses": ("GET", "/zapier/emailStatus"),
    "list_phone_statuses": ("GET", "/zapier/phoneStatus"),
    "list_task_types": ("GET", "/zapier/taskType"),
    "list_mls_regions": ("GET", "/zapier/mlsRegion"),
    "list_lead_types": ("GET", "/zapier/leadTypes"),
    "list_tags": ("GET", "/zapier/tags"),
    "list_traditional_action_plans": ("GET", "/zapier/traditionalActionPlans"),
    "list_automated_action_plans": ("GET", "/zapier/fullyAutomatedActionPlans"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class SierraInteractiveNode(WorkflowNode):
    integration_type = "automation-sierra-interactive"
    connection_evidence = ConnectionEvidence(
        noun="sites", operation="list_sites", label_keys=("name", "siteName", "url", "id", "text", "Text", "label"))

    @classmethod
    def get_config_model(cls):
        return SierraInteractiveNodeConfig

    @staticmethod
    def _check_credential_family(config_data):
        data = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(data, dict) and data.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Attach a Sierra Interactive API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Sierra Interactive API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        for field in ("leadIdOrEmail", "leadIdOrEmailOrPhone"):
            if "{" + field + "}" in path:
                identifier = body.pop(field)
                if identifier in {".", ".."} or any(ord(c) < 32 for c in identifier):
                    raise ValueError("Use an exact lead identifier without control characters")
                path = path.replace("{" + field + "}", quote(identifier, safe=""))
        write = method != "GET" and op.operation != "find_lead"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Sierra-User-ApiKey": key, "Accept": "application/json"},
                    **({"json": body} if write else {}))
        except (httpx.RequestError, SSRFError):
            # Never retry a mutation whose outcome is unknown.
            raise ValueError("Sierra Interactive request was not confirmed; inspect writes before retrying") from None
        if response.status_code != 200:
            message = "Request was not confirmed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    candidate = error.get("message") or error.get("Message") or error.get("error")
                    if isinstance(candidate, str):
                        message = candidate[:1000]
            except (ValueError, UnicodeError):
                pass
            raise ValueError(_redact(f"Sierra Interactive HTTP {response.status_code}: {message}", key))
        try:
            if len(response.content) > 5_000_000:
                raise ValueError()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError("Sierra Interactive returned an unexpected JSON object; inspect writes before retrying") from None
        if payload.get("success") is False or payload.get("Success") is False or payload.get("error") or payload.get("errors") or payload.get("status") in ("error", "failed"):
            message = payload.get("message") or payload.get("Message") or payload.get("error")
            detail = ": " + message[:1000] if isinstance(message, str) else ""
            raise ValueError(_redact("Sierra Interactive did not confirm the request" + detail, key))
        output = {"status": "success", "operation": op.operation, "data": _redact(payload, key),
                  "http_status": response.status_code}
        if write:
            output["write_acknowledged"] = True
            output["readback_verified"] = False
        await self.emit(output)
        return output
