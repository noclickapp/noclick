"""ISN JSON API 1.1.0: account-scoped inspection operations.

Contract: https://json.inspectionsupport.net/openapi.json. Each action makes
one documented API request; mutation results are provider acknowledgments,
not independent readback verification. Lists use the provider's documented
response without inventing pagination parameters.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

CREDENTIAL_TYPE = "isn_api_key"


def _api_base_url(value):
    if not isinstance(value, str):
        raise ValueError("Paste your ISN HTTPS JSON API URL")
    value = value.strip()
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.hostname not in {"inspectionsupport.com", "goisn.net"}
                or parts.port is not None or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment
                or not re.fullmatch(r"/[A-Za-z0-9_-]+/json/?", parts.path)):
            raise ValueError()
    except ValueError:
        raise ValueError("Use https://goisn.net/your-company/json or https://inspectionsupport.com/your-company/json") from None
    return "https://" + parts.hostname + parts.path.rstrip("/")


class ISNAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="ISN API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://json.inspectionsupport.net/",
            "x-credential-instructions": "Paste your account's JSON API URL and the API access key and secret key used as the Basic-auth username and password. Use API keys with the permissions your workflow needs. The connection check reads the current user; it does not verify write permissions.",
        })
    credential_type: Literal["isn_api_key"] = Field("isn_api_key", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="ISN JSON API URL", description="Your account URL ending in /json, for example https://goisn.net/greenway/json")
    access_key: str = Field(..., min_length=1, max_length=4096, title="API access key", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, max_length=4096, title="API secret key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url", mode="before")
    @classmethod
    def base_url(cls, value):
        return _api_base_url(value)

    @field_validator("access_key", "secret_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key itself")
        value = clean_secret(value, field_name="API key", key=True)
        if any(ord(c) < 33 or ord(c) > 126 for c in value) or ":" in value:
            raise ValueError("Paste the API key without spaces, a colon, or the Basic prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Use a single ISN resource ID")
        return value


class _DateRange(_Input):
    start: str = Field(..., description="Start datetime in ISO 8601 format", json_schema_extra={"format": "date-time"})
    end: str = Field(..., description="End datetime in ISO 8601 format", json_schema_extra={"format": "date-time"})

    @field_validator("start", "end")
    @classmethod
    def iso_datetime(cls, value):
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value:
            raise ValueError("Use an ISO 8601 datetime including time")
        return value


class ISNClientInput(_Input):
    name: str = Field(..., min_length=1, max_length=500)
    email: str | None = Field(None, max_length=500)
    mobile: str | None = Field(None, max_length=100)


class ISNGetCurrentUserConfig(_Input):
    """Read the current user for this ISN account."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})

class ISNListOrdersConfig(_DateRange):
    """List inspection orders within the requested date range."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})
    criteria: Literal["date", "created", "scheduled", "updated", "created_scheduled", "date_created_scheduled"] | None = None
    mini: bool | None = None
    agent_id: str | None = None
    client_id: str | None = None

class ISNGetOrderConfig(_Input):
    """Read one inspection order."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: str
    all_controls: bool | None = None

class ISNCreateOrderConfig(_Input):
    """Create an inspection order; scheduling and configured account automations may run."""
    operation: Literal["create_order"] = Field("create_order", json_schema_extra={"ui:hidden": True})
    datetime: str = Field(..., description="Scheduled ISO 8601 datetime", json_schema_extra={"format": "date-time"})
    address: str = Field(..., min_length=1, max_length=1000)
    city: str = Field(..., min_length=1, max_length=200)
    state: str = Field(..., min_length=1, max_length=200)
    postal: str = Field(..., min_length=1, max_length=50)
    client: ISNClientInput
    clientid: int | None = None
    duration: int | None = Field(None, ge=0)
    orderType: int | None = None
    inspector_id: str | None = None
    agent: ISNClientInput | None = None
    buyersAgentId: int | None = None
    sellersAgentId: int | None = None
    notes: str | None = Field(None, max_length=100000)
    fee: float | None = Field(None, allow_inf_nan=False)
    area: str | None = None
    built: str | None = None

    @field_validator("datetime")
    @classmethod
    def scheduled_datetime(cls, value):
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if "T" not in value:
                raise ValueError("Use an ISO 8601 datetime including time")
        return value

class ISNUpdateOrderConfig(_Input):
    """Update selected order fields; omitted fields are not sent."""
    operation: Literal["update_order"] = Field("update_order", json_schema_extra={"ui:hidden": True})
    order_id: str
    datetime: str | None = Field(None, json_schema_extra={"format": "date-time"})
    duration: str | None = None
    city: str | None = None
    state: str | None = None
    postal: str | None = None

    @field_validator("datetime")
    @classmethod
    def scheduled_datetime(cls, value):
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if "T" not in value:
                raise ValueError("Use an ISO 8601 datetime including time")
        return value

    @model_validator(mode="after")
    def changed_fields(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "order_id", "service_id"}):
            raise ValueError("Provide at least one field to update")
        return self

class ISNCancelOrderConfig(_Input):
    """Cancel an inspection order; account cancellation automations may run."""
    operation: Literal["cancel_order"] = Field("cancel_order", json_schema_extra={"ui:hidden": True})
    order_id: str

class ISNListOrderNotesConfig(_Input):
    """List notes for an inspection order."""
    operation: Literal["list_order_notes"] = Field("list_order_notes", json_schema_extra={"ui:hidden": True})
    order_id: str
    note_id: str | None = None


class ISNListOrderTypesConfig(_Input):
    """List inspection types."""
    operation: Literal["list_order_types"] = Field("list_order_types", json_schema_extra={"ui:hidden": True})
    includedeleted: bool | None = None

class ISNListClientsConfig(_Input):
    """List account clients."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})

class ISNGetClientConfig(_Input):
    """Read a client."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: str

class ISNListAgentsConfig(_Input):
    """List real estate agents."""
    operation: Literal["list_agents"] = Field("list_agents", json_schema_extra={"ui:hidden": True})

class ISNGetAgentConfig(_Input):
    """Read a real estate agent."""
    operation: Literal["get_agent"] = Field("get_agent", json_schema_extra={"ui:hidden": True})
    agent_id: str

class ISNListContactsConfig(_Input):
    """List account contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})

class ISNGetContactConfig(_Input):
    """Read a contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str

class ISNListServicesConfig(_Input):
    """List inspection services."""
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"ui:hidden": True})
    alloffices: bool | None = None
    includedeleted: bool | None = None

class ISNGetServiceConfig(_Input):
    """Read an inspection service."""
    operation: Literal["get_service"] = Field("get_service", json_schema_extra={"ui:hidden": True})
    service_id: str

class ISNCreateServiceConfig(_Input):
    """Create an inspection service."""
    operation: Literal["create_service"] = Field("create_service", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    privatename: str | None = None
    description: str | None = Field(None, max_length=100000)
    label: bool | None = None
    ancillary: bool | None = None
    inspectiontypeid: str | None = None
    sequence: int | None = None

class ISNUpdateServiceConfig(_Input):
    """Update selected service fields."""
    operation: Literal["update_service"] = Field("update_service", json_schema_extra={"ui:hidden": True})
    service_id: str
    name: str | None = Field(None, min_length=1, max_length=500)
    privatename: str | None = None
    description: str | None = Field(None, max_length=100000)
    label: bool | None = None
    ancillary: bool | None = None
    inspectiontypeid: str | None = None
    sequence: int | None = None

    @model_validator(mode="after")
    def changed_fields(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "order_id", "service_id"}):
            raise ValueError("Provide at least one field to update")
        return self

class ISNDeleteServiceConfig(_Input):
    """Delete a service; provider acknowledgment does not independently verify absence."""
    operation: Literal["delete_service"] = Field("delete_service", json_schema_extra={"ui:hidden": True})
    service_id: str

class ISNListCalendarEventsConfig(_DateRange):
    """List calendar events within a date range."""
    operation: Literal["list_calendar_events"] = Field("list_calendar_events", json_schema_extra={"ui:hidden": True})
    owner_id: str | None = None

class ISNListUsersConfig(_Input):
    """List users in the office."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})

class ISNListPackagesConfig(_Input):
    """List service packages."""
    operation: Literal["list_packages"] = Field("list_packages", json_schema_extra={"ui:hidden": True})
    alloffices: bool | None = None
    includedeleted: bool | None = None
    view: Literal["slim"] | None = None

ISNOperation = Annotated[Union[
    ISNGetCurrentUserConfig,
    ISNListOrdersConfig,
    ISNGetOrderConfig,
    ISNCreateOrderConfig,
    ISNUpdateOrderConfig,
    ISNCancelOrderConfig,
    ISNListOrderNotesConfig,
    ISNListOrderTypesConfig,
    ISNListClientsConfig,
    ISNGetClientConfig,
    ISNListAgentsConfig,
    ISNGetAgentConfig,
    ISNListContactsConfig,
    ISNGetContactConfig,
    ISNListServicesConfig,
    ISNGetServiceConfig,
    ISNCreateServiceConfig,
    ISNUpdateServiceConfig,
    ISNDeleteServiceConfig,
    ISNListCalendarEventsConfig,
    ISNListUsersConfig,
    ISNListPackagesConfig,
], Field(discriminator="operation")]


class ISNFullConfig(NodeConfig[ISNOperation, ISNAPIKeyCredential]):
    pass


ROUTES = {
    "get_current_user": ("GET", "/me", False),
    "list_orders": ("GET", "/orders", True),
    "get_order": ("GET", "/order/{id}", False),
    "create_order": ("POST", "/order", False),
    "update_order": ("POST", "/order/{id}", False),
    "cancel_order": ("POST", "/order/{id}/cancel", False),
    "list_order_notes": ("GET", "/order_notes", True),
    "list_order_types": ("GET", "/order_types", True),
    "list_clients": ("GET", "/clients", True),
    "get_client": ("GET", "/client/{id}", False),
    "list_agents": ("GET", "/agents", True),
    "get_agent": ("GET", "/agent/{id}", False),
    "list_contacts": ("GET", "/contacts", True),
    "get_contact": ("GET", "/contact/{id}", False),
    "list_services": ("GET", "/services", True),
    "get_service": ("GET", "/service/{id}", False),
    "create_service": ("POST", "/service", False),
    "update_service": ("POST", "/service/{id}", False),
    "delete_service": ("DELETE", "/service/{id}", False),
    "list_calendar_events": ("GET", "/calendar_events", True),
    "list_users": ("GET", "/users", True),
    "list_packages": ("GET", "/packages", True),
}


class _ProviderError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def _redact(value, credential):
    secrets = (credential.access_key, credential.secret_key,
               base64.b64encode((credential.access_key + ":" + credential.secret_key).encode()).decode())
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    return value


class ISNNode(WorkflowNode):
    integration_type = "automation-isn"
    connection_evidence = ConnectionEvidence(
        noun="ISN account", identity_operation="get_current_user",
        identity_keys=("display", "email", "first", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return ISNFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an ISN API key")
        credential = self.config.credentials
        config = self.config.config
        operation = config.operation
        method, route, is_list = ROUTES[operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        identifier = next((values.pop(k) for k in ("order_id", "client_id", "agent_id", "contact_id", "service_id") if k in values), None) if "{" in route else None
        if identifier is not None:
            route = route.replace("{id}", identifier).replace("{oid}", identifier)
        params, body = {}, None
        if operation == "list_orders":
            params = { {"agent_id": "agentId", "client_id": "clientId"}.get(k, k): v for k, v in values.items() }
        elif operation == "list_order_notes":
            params = {"oid": values["order_id"]}
            if "note_id" in values:
                params["id"] = values["note_id"]
        elif method == "GET":
            params = values
        elif operation not in {"cancel_order", "delete_service"}:
            body = { {"inspector_id": "inspectorId"}.get(k, k): v for k, v in values.items() }
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        auth = "Basic " + base64.b64encode((credential.access_key + ":" + credential.secret_key).encode()).decode()
        output = {"operation": operation}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, credential.api_base_url + route,
                    headers={"Authorization": auth, "Accept": "application/json"}, params=params,
                    **({"json": body} if body is not None else {}))
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if len(response.content) > 10_000_000 or mime != "application/json":
                raise _ProviderError(response.status_code, "ISN returned an unexpected response; check your JSON API URL")
            data = response.json()
            error = isinstance(data, dict) and (data.get("error") or data.get("errors") or
                data.get("success") is False or str(data.get("status", "")).lower() in {"error", "failed", "failure", "unauthorized", "forbidden"})
            if not 200 <= response.status_code < 300 or error:
                message = next((data[k] for k in ("message", "description", "error") if isinstance(data.get(k), str) and data[k]), "ISN did not accept this request") if isinstance(data, dict) else "ISN did not accept this request"
                raise _ProviderError(response.status_code, message)
            if is_list:
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Expected an ISN record list")
            elif not isinstance(data, dict):
                raise ValueError("Expected an ISN record")
            if operation == "get_current_user":
                data = data.get("me")
                if not isinstance(data, dict) or not any(isinstance(data.get(k), str) and data[k] for k in ("id", "display", "email", "first")):
                    raise ValueError("ISN did not return a current user")
            output.update(status="success", data=data, http_status=response.status_code)
            if is_list:
                output["count"] = len(data)
            if method != "GET":
                output.update(write_acknowledged=True, readback_verified=False)
        except _ProviderError as exc:
            output.update(status="error", http_status=exc.status, error=exc.message)
            if method != "GET":
                output["write_outcome"] = "unverified"
        except (ValueError, SSRFError, httpx.HTTPError):
            output.update(status="error", error="ISN returned an invalid response or the request could not be completed")
            if method != "GET":
                output["write_outcome"] = "unverified"
        output = _redact(output, credential)
        await self.emit(output)
        return output
