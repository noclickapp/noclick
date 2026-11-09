"""EMnify v1 endpoint, SIM, SMS and quota operations.

Contract: https://cdn.emnify.net/api/doc/apis/enterprise.yaml (v1.3).
Application tokens are exchanged for a short-lived JWT, never sent as bearer tokens.
Each execution performs one business operation; writes report acknowledgement only.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://cdn.emnify.net/api/v1"


class EMnifyApplicationTokenCredential(BaseModel):
    model_config = ConfigDict(title="Emnify Application Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://portal.emnify.com/integrations#application-tokens",
            "x-credential-instructions": "In the EMnify Portal, open Integrations → Application tokens, create a token and copy it here. NoClick exchanges it for an authentication token before each operation. The token needs permission for the selected operation. Connection verification reads your organisation.",
        })
    credential_type: Literal["emnify_application_token"] = Field("emnify_application_token", json_schema_extra={"ui:hidden": True})
    application_token: str = Field(..., title="Application token", min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("application_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Application token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the application token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Endpoint(_Input):
    endpoint_id: int = Field(..., gt=0, description="Numeric EMnify endpoint ID")


class _SIM(_Input):
    sim_id: int = Field(..., gt=0, description="Numeric EMnify SIM ID")


class _SMS(_Endpoint):
    sms_id: int = Field(..., gt=0, description="Numeric EMnify SMS ID")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; returns one page only")
    per_page: int = Field(100, ge=1, le=1000)


class _UpdateEndpoint(_Endpoint):
    name: str = Field(..., min_length=1)
    tags: str = Field(..., description="Comma-separated endpoint tags")
    imei: str = Field(..., description="Device IMEI")
    imei_lock: bool = Field(...)
    ip_address: str = Field(...)
    service_profile_id: int = Field(..., gt=0)
    tariff_profile_id: int = Field(..., gt=0)
    status_id: Literal[0, 1] = Field(..., description="0 enabled; 1 disabled")
    ip_address_space_id: int = Field(..., gt=0)
    sim_id: int = Field(..., gt=0)
    sim_status_id: int = Field(..., ge=0)


class _ResetConnectivity(_Endpoint):
    reset: Literal["all", "network", "data"] = Field("all", description="Reset network location, data session, or both; may interrupt connectivity")


class _SendSMS(_Endpoint):
    source_address: str = Field(..., min_length=1, description="Sender number")
    payload: str = Field(..., min_length=1, description="SMS text to send to the endpoint; provider charges may apply")


class _DataQuota(_Endpoint):
    volume: float = Field(..., ge=0, allow_inf_nan=False, description="Data quota volume in MB")
    expiry_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", description="UTC expiry: YYYY-MM-DD HH:MM:SS")
    status_id: Literal[1, 2, 3] = Field(1)
    auto_refill: Literal[0, 1] = Field(0)
    threshold_percentage: float = Field(15, ge=0, le=100)

    @field_validator("expiry_date")
    @classmethod
    def expiry(cls, value):
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value


class _SMSQuota(_Endpoint):
    volume: int = Field(..., ge=0, description="Number of SMS messages")
    expiry_date: str = Field(..., description="UTC expiry as an ISO 8601 date-time")
    status_id: Literal[1, 2, 3] = Field(1)
    auto_refill: bool = Field(False)
    threshold_percentage: float = Field(20, ge=0, le=100)

    @field_validator("expiry_date")
    @classmethod
    def expiry(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Include a UTC offset in the expiry date")
        return value


class _UpdateSIM(_SIM):
    issuer_org_id: int = Field(..., gt=0)
    reseller_org_id: int = Field(..., gt=0)
    customer_org_id: int = Field(..., gt=0)
    status_id: int = Field(..., ge=0)


class _DailyUsage(_Endpoint):
    start_date: str | None = Field(None, description="YYYY-MM-DD")
    end_date: str | None = Field(None, description="YYYY-MM-DD")

    @field_validator("start_date", "end_date")
    @classmethod
    def dates(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class EMnifyGetOrganisationConfig(_Input):
    operation: Literal["get_organisation"] = Field("get_organisation", title="Get Organisation", json_schema_extra={"ui:hidden": True})


class EMnifyListEndpointsConfig(_Page):
    operation: Literal["list_endpoints"] = Field("list_endpoints", title="List Endpoints", json_schema_extra={"ui:hidden": True})


class EMnifyGetEndpointConfig(_Endpoint):
    operation: Literal["get_endpoint"] = Field("get_endpoint", title="Get Endpoint", json_schema_extra={"ui:hidden": True})


class EMnifyUpdateEndpointConfig(_UpdateEndpoint):
    operation: Literal["update_endpoint"] = Field("update_endpoint", title="Update Endpoint", json_schema_extra={"ui:hidden": True})


class EMnifyDeleteEndpointConfig(_Endpoint):
    operation: Literal["delete_endpoint"] = Field("delete_endpoint", title="Delete Endpoint", json_schema_extra={"ui:hidden": True})


class EMnifyGetConnectivityConfig(_Endpoint):
    operation: Literal["get_connectivity"] = Field("get_connectivity", title="Get Connectivity", json_schema_extra={"ui:hidden": True})


class EMnifyResetConnectivityConfig(_ResetConnectivity):
    operation: Literal["reset_connectivity"] = Field("reset_connectivity", title="Reset Connectivity", json_schema_extra={"ui:hidden": True})


class EMnifyListSmsConfig(_Endpoint):
    operation: Literal["list_sms"] = Field("list_sms", title="List Sms", json_schema_extra={"ui:hidden": True})


class EMnifySendSmsConfig(_SendSMS):
    operation: Literal["send_sms"] = Field("send_sms", title="Send Sms", json_schema_extra={"ui:hidden": True})


class EMnifyGetSmsConfig(_SMS):
    operation: Literal["get_sms"] = Field("get_sms", title="Get Sms", json_schema_extra={"ui:hidden": True})


class EMnifyCancelSmsConfig(_SMS):
    operation: Literal["cancel_sms"] = Field("cancel_sms", title="Cancel Sms", json_schema_extra={"ui:hidden": True})


class EMnifyGetDataQuotaConfig(_Endpoint):
    operation: Literal["get_data_quota"] = Field("get_data_quota", title="Get Data Quota", json_schema_extra={"ui:hidden": True})


class EMnifySetDataQuotaConfig(_DataQuota):
    operation: Literal["set_data_quota"] = Field("set_data_quota", title="Set Data Quota", json_schema_extra={"ui:hidden": True})


class EMnifyRemoveDataQuotaConfig(_Endpoint):
    operation: Literal["remove_data_quota"] = Field("remove_data_quota", title="Remove Data Quota", json_schema_extra={"ui:hidden": True})


class EMnifyGetSmsQuotaConfig(_Endpoint):
    operation: Literal["get_sms_quota"] = Field("get_sms_quota", title="Get Sms Quota", json_schema_extra={"ui:hidden": True})


class EMnifySetSmsQuotaConfig(_SMSQuota):
    operation: Literal["set_sms_quota"] = Field("set_sms_quota", title="Set Sms Quota", json_schema_extra={"ui:hidden": True})


class EMnifyRemoveSmsQuotaConfig(_Endpoint):
    operation: Literal["remove_sms_quota"] = Field("remove_sms_quota", title="Remove Sms Quota", json_schema_extra={"ui:hidden": True})


class EMnifyListSimsConfig(_Page):
    operation: Literal["list_sims"] = Field("list_sims", title="List Sims", json_schema_extra={"ui:hidden": True})


class EMnifyGetSimConfig(_SIM):
    operation: Literal["get_sim"] = Field("get_sim", title="Get Sim", json_schema_extra={"ui:hidden": True})


class EMnifyUpdateSimConfig(_UpdateSIM):
    operation: Literal["update_sim"] = Field("update_sim", title="Update Sim", json_schema_extra={"ui:hidden": True})


class EMnifyGetDailyUsageConfig(_DailyUsage):
    operation: Literal["get_daily_usage"] = Field("get_daily_usage", title="Get Daily Usage", json_schema_extra={"ui:hidden": True})


EMnifyConfig = Annotated[Union[
    EMnifyGetOrganisationConfig,
    EMnifyListEndpointsConfig,
    EMnifyGetEndpointConfig,
    EMnifyUpdateEndpointConfig,
    EMnifyDeleteEndpointConfig,
    EMnifyGetConnectivityConfig,
    EMnifyResetConnectivityConfig,
    EMnifyListSmsConfig,
    EMnifySendSmsConfig,
    EMnifyGetSmsConfig,
    EMnifyCancelSmsConfig,
    EMnifyGetDataQuotaConfig,
    EMnifySetDataQuotaConfig,
    EMnifyRemoveDataQuotaConfig,
    EMnifyGetSmsQuotaConfig,
    EMnifySetSmsQuotaConfig,
    EMnifyRemoveSmsQuotaConfig,
    EMnifyListSimsConfig,
    EMnifyGetSimConfig,
    EMnifyUpdateSimConfig,
    EMnifyGetDailyUsageConfig], Field(discriminator="operation")]


class EMnifyFullConfig(NodeConfig[EMnifyConfig, EMnifyApplicationTokenCredential]):
    pass


OPERATIONS = {
    'get_organisation': ('GET', '/organisation/my'),
    'list_endpoints': ('GET', '/endpoint'),
    'get_endpoint': ('GET', '/endpoint/{endpoint_id}'),
    'update_endpoint': ('PATCH', '/endpoint/{endpoint_id}'),
    'delete_endpoint': ('DELETE', '/endpoint/{endpoint_id}'),
    'get_connectivity': ('GET', '/endpoint/{endpoint_id}/connectivity'),
    'reset_connectivity': ('PATCH', '/endpoint/{endpoint_id}/connectivity'),
    'list_sms': ('GET', '/endpoint/{endpoint_id}/sms'),
    'send_sms': ('POST', '/endpoint/{endpoint_id}/sms'),
    'get_sms': ('GET', '/endpoint/{endpoint_id}/sms/{sms_id}'),
    'cancel_sms': ('DELETE', '/endpoint/{endpoint_id}/sms/{sms_id}'),
    'get_data_quota': ('GET', '/endpoint/{endpoint_id}/quota/data'),
    'set_data_quota': ('POST', '/endpoint/{endpoint_id}/quota/data'),
    'remove_data_quota': ('DELETE', '/endpoint/{endpoint_id}/quota/data'),
    'get_sms_quota': ('GET', '/endpoint/{endpoint_id}/quota/sms'),
    'set_sms_quota': ('POST', '/endpoint/{endpoint_id}/quota/sms'),
    'remove_sms_quota': ('DELETE', '/endpoint/{endpoint_id}/quota/sms'),
    'list_sims': ('GET', '/sim'),
    'get_sim': ('GET', '/sim/{sim_id}'),
    'update_sim': ('PATCH', '/sim/{sim_id}'),
    'get_daily_usage': ('GET', '/endpoint/{endpoint_id}/stats/daily'),
}


class EMnifyNode(WorkflowNode):
    integration_type = "automation-emnify"
    connection_evidence = ConnectionEvidence(noun="EMnify organisation", identity_operation="get_organisation")

    @classmethod
    def get_config_model(cls):
        return EMnifyFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an EMnify application token")
        config = self.config.config
        method, path = OPERATIONS[config.operation]
        path = path.format(**config.model_dump())
        params = {}
        body = None
        if isinstance(config, _Page):
            params = {"page": config.page, "per_page": config.per_page}
        if isinstance(config, _DailyUsage):
            params = {k: getattr(config, k) for k in ("start_date", "end_date") if getattr(config, k) is not None}
        if isinstance(config, _UpdateEndpoint):
            body = {k: getattr(config, k) for k in ("name", "tags", "imei", "imei_lock", "ip_address")}
            body.update({k: {"id": getattr(config, k + "_id")} for k in ("service_profile", "tariff_profile", "status", "ip_address_space")})
            body["sim"] = {"id": config.sim_id, "status": {"id": config.sim_status_id}}
        elif isinstance(config, _ResetConnectivity):
            body = {}
            if config.reset in {"all", "network"}:
                body["location"] = None
            if config.reset in {"all", "data"}:
                body["pdp_context"] = None
        elif isinstance(config, _SendSMS):
            body = {"source_address": config.source_address, "payload": config.payload}
        elif isinstance(config, (_DataQuota, _SMSQuota)):
            body = {k: getattr(config, k) for k in ("volume", "expiry_date", "auto_refill", "threshold_percentage")}
            body.update(status={"id": config.status_id}, action_on_exhaustion={"id": 1})
        elif isinstance(config, _UpdateSIM):
            body = {k: {"id": getattr(config, k + "_id")} for k in ("issuer_org", "reseller_org", "customer_org", "status")}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            auth = await client.post(BASE + "/authenticate", json={"application_token": credential.application_token}, headers={"Accept": "application/json"})
            self._check(auth, credential.application_token)
            token = auth.json().get("auth_token")
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError("EMnify did not return an authentication token")
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
            self._check(response, credential.application_token, token)
        data = response.json() if response.content else None
        if isinstance(data, dict) and ("error_code" in data or "error_token" in data):
            raise ValueError("EMnify returned an error response")
        out = {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": data}
        if method == "GET":
            out["read_completed"] = True
        else:
            out["acknowledged"] = True
            out["effect_verified"] = False
        if isinstance(config, _Page):
            out["page"] = config.page
            out["per_page"] = config.per_page
            total = response.headers.get("X-Total-Pages")
            out["total_pages"] = int(total) if total and total.isdigit() else None
            out["next_page"] = config.page + 1 if total and total.isdigit() and config.page < int(total) else None
            out["pagination_known"] = bool(total and total.isdigit())
        return out

    @staticmethod
    def _check(response, *secrets):
        if 200 <= response.status_code < 300:
            return
        message = "EMnify HTTP " + str(response.status_code)
        try:
            detail = response.json().get("message")
            if isinstance(detail, str):
                message += ": " + detail[:1000]
        except (ValueError, AttributeError):
            pass
        for secret in secrets:
            message = message.replace(secret, "[redacted]")
        raise ValueError(message)
