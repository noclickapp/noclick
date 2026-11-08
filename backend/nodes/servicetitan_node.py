"""ServiceTitan CRM v2 operations using a supplied short-lived access token.

Contract: https://developer.servicetitan.io/api/docs/apis/tenant-crm, version 1.0.
Tokens are minted outside NoClick with ServiceTitan's client-credentials grant.
"""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, AwareDatetime, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.servicetitan import SERVICETITAN_SCOPES
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class ServiceTitanTokenCredential(BaseModel):
    model_config = ConfigDict(title="ServiceTitan Access Token", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.servicetitan.io/api/docs/apis/tenant-crm",
        "x-credential-instructions": "Paste a ServiceTitan client-credentials access token, app key and tenant ID from your API administrator. Access tokens are short-lived: replace an expired token before the next run; NoClick does not renew it. Grant CRM Customers, Locations and Leads read/write access for the operations you use. Choose the matching production or integration environment."})
    credential_type: Literal["servicetitan_token"] = Field("servicetitan_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", json_schema_extra={"ui:widget": "password"})
    app_key: str = Field(..., title="App key", json_schema_extra={"ui:widget": "password"})
    tenant_id: str = Field(..., pattern=r"^[0-9]{1,19}$", title="Tenant ID")
    environment: Literal["production", "integration"] = "production"

    @field_validator("access_token", "app_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="ServiceTitan secret")
        if any(c.isspace() for c in value) or len(value)>8192:
            raise ValueError("Paste the secret without a header or whitespace")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class ListCustomersConfig(Input):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class GetCustomerConfig(Input):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")

class UpdateCustomerConfig(Input):
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    name: str = Field(..., min_length=1, max_length=10000)

class ListCustomerNotesConfig(Input):
    operation: Literal["list_customer_notes"] = Field("list_customer_notes", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class CreateCustomerNoteConfig(Input):
    operation: Literal["create_customer_note"] = Field("create_customer_note", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    text: str = Field(..., min_length=1, max_length=10000)
    pin_to_top: StrictBool = False

class ListCustomerContactsConfig(Input):
    operation: Literal["list_customer_contacts"] = Field("list_customer_contacts", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class ListLocationsConfig(Input):
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class GetLocationConfig(Input):
    operation: Literal["get_location"] = Field("get_location", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")

class UpdateLocationConfig(Input):
    operation: Literal["update_location"] = Field("update_location", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    name: str = Field(..., min_length=1, max_length=10000)

class ListLocationNotesConfig(Input):
    operation: Literal["list_location_notes"] = Field("list_location_notes", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class CreateLocationNoteConfig(Input):
    operation: Literal["create_location_note"] = Field("create_location_note", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    text: str = Field(..., min_length=1, max_length=10000)
    pin_to_top: StrictBool = False

class ListLocationContactsConfig(Input):
    operation: Literal["list_location_contacts"] = Field("list_location_contacts", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class ListLeadsConfig(Input):
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class GetLeadConfig(Input):
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")

class UpdateLeadConfig(Input):
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    summary: str = Field(..., min_length=1, max_length=10000)

class ListLeadNotesConfig(Input):
    operation: Literal["list_lead_notes"] = Field("list_lead_notes", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

class CreateLeadNoteConfig(Input):
    operation: Literal["create_lead_note"] = Field("create_lead_note", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    text: str = Field(..., min_length=1, max_length=10000)
    pin_to_top: StrictBool = False

class CreateLeadFollowUpConfig(Input):
    operation: Literal["create_lead_follow_up"] = Field("create_lead_follow_up", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    follow_up_date: AwareDatetime

class DismissLeadConfig(Input):
    operation: Literal["dismiss_lead"] = Field("dismiss_lead", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Resource ID")
    dismissing_reason_id: int = Field(..., ge=1)

ServiceTitanConfig = Annotated[Union[ListCustomersConfig, GetCustomerConfig, UpdateCustomerConfig, ListCustomerNotesConfig, CreateCustomerNoteConfig, ListCustomerContactsConfig, ListLocationsConfig, GetLocationConfig, UpdateLocationConfig, ListLocationNotesConfig, CreateLocationNoteConfig, ListLocationContactsConfig, ListLeadsConfig, GetLeadConfig, UpdateLeadConfig, ListLeadNotesConfig, CreateLeadNoteConfig, CreateLeadFollowUpConfig, DismissLeadConfig], Field(discriminator="operation")]

class ServiceTitanFullConfig(NodeConfig[ServiceTitanConfig, ServiceTitanTokenCredential]):
    pass

OPERATIONS = {'list_customers': ('GET', '/v2/tenant/{tenant}/customers', 'list'), 'get_customer': ('GET', '/v2/tenant/{tenant}/customers/{id}', 'get'), 'update_customer': ('PATCH', '/v2/tenant/{tenant}/customers/{id}', 'update'), 'list_customer_notes': ('GET', '/v2/tenant/{tenant}/customers/{id}/notes', 'list'), 'create_customer_note': ('POST', '/v2/tenant/{tenant}/customers/{id}/notes', 'note'), 'list_customer_contacts': ('GET', '/v2/tenant/{tenant}/customers/{id}/contacts', 'list'), 'list_locations': ('GET', '/v2/tenant/{tenant}/locations', 'list'), 'get_location': ('GET', '/v2/tenant/{tenant}/locations/{id}', 'get'), 'update_location': ('PATCH', '/v2/tenant/{tenant}/locations/{id}', 'update'), 'list_location_notes': ('GET', '/v2/tenant/{tenant}/locations/{id}/notes', 'list'), 'create_location_note': ('POST', '/v2/tenant/{tenant}/locations/{id}/notes', 'note'), 'list_location_contacts': ('GET', '/v2/tenant/{tenant}/locations/{id}/contacts', 'list'), 'list_leads': ('GET', '/v2/tenant/{tenant}/leads', 'list'), 'get_lead': ('GET', '/v2/tenant/{tenant}/leads/{id}', 'get'), 'update_lead': ('PATCH', '/v2/tenant/{tenant}/leads/{id}', 'update'), 'list_lead_notes': ('GET', '/v2/tenant/{tenant}/leads/{id}/notes', 'list'), 'create_lead_note': ('POST', '/v2/tenant/{tenant}/leads/{id}/notes', 'note'), 'create_lead_follow_up': ('POST', '/v2/tenant/{tenant}/leads/{id}/follow-up', 'followup'), 'dismiss_lead': ('POST', '/v2/tenant/{tenant}/leads/{id}/dismiss', 'dismiss')}

def redact(value, credential):
    if isinstance(value, dict): return {k: redact(v, credential) for k,v in value.items()}
    if isinstance(value, list): return [redact(v, credential) for v in value]
    if isinstance(value, str):
        for secret in (credential.access_token, credential.app_key):
            value = value.replace(secret, "[redacted]")
    return value

class ServiceTitanNode(WorkflowNode):
    integration_type = "automation-servicetitan"
    scope_registry = SERVICETITAN_SCOPES
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ServiceTitanFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a ServiceTitan access token and app key")
        credential, op = self.config.credentials, self.config.config
        method, template, kind = OPERATIONS[op.operation]
        host = "api.servicetitan.io" if credential.environment == "production" else "api-integration.servicetitan.io"
        route = template.format(tenant=credential.tenant_id, id=getattr(op, "id", ""))
        params, body = None, None
        if kind == "list": params = {"page": op.page, "pageSize": op.page_size, "includeTotal": True}
        elif kind == "update": body = {"summary": op.summary} if hasattr(op, "summary") else {"name": op.name}
        elif kind == "note": body = {"text": op.text, "pinToTop": op.pin_to_top}
        elif kind == "followup": body = {"followUpDate": op.follow_up_date.isoformat()}
        elif kind == "dismiss": body = {"dismissingReasonId": op.dismissing_reason_id}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://" + host + "/crm" + route,
                    headers={"Authorization": "Bearer " + credential.access_token, "ST-App-Key": credential.app_key,
                             "Accept": "application/json"}, params=params, json=body)
            if response.status_code >= 300:
                output = {"status": "error", "success": False, "http_status": response.status_code,
                          "message": response.text[:2000], "write_outcome": "unverified" if method != "GET" else None}
            else:
                data = response.json() if response.content else None
                if kind == "list":
                    if not isinstance(data, dict) or not isinstance(data.get("data"), list) or type(data.get("hasMore")) is not bool:
                        raise ValueError("Unexpected ServiceTitan page")
                    if type(data.get("page")) is not int or data["page"] != op.page:
                        raise ValueError("ServiceTitan returned a different page")
                    output = {"status": "success", "success": True, "data": data["data"],
                              "has_more": data["hasMore"], "next_page": op.page + 1 if data["hasMore"] else None,
                              "page": data["page"], "total_count": data.get("totalCount")}
                else:
                    if kind != "dismiss" and (not isinstance(data, dict) or type(data.get("id")) is not int):
                        raise ValueError("Unexpected ServiceTitan resource")
                    output = {"status": "success", "success": True, "data": data,
                              "write_acknowledged": method != "GET"}
        except (httpx.HTTPError, ValueError):
            output = {"status": "error" if method == "GET" else "unknown", "success": False,
                      "message": "ServiceTitan response could not be verified; inspect writes before retrying"}
        output = redact(output, credential)
        await self.emit(output)
        return output
