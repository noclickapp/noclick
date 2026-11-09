"""Simplicate v3 RPC operations using the user's API key and secret.

Contract: https://developer.simplicate.com/docs/api/v3/reference/
The v3 API is intentionally smaller than v2; every operation here is one RPC.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SimplicateAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Simplicate API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.simplicate.com/docs/api/v3/getting_started/#authentication",
            "x-credential-instructions": "In Simplicate, open General settings → API and create a token for a user with the required permissions. Paste its key and secret separately, and enter your Simplicate subdomain. The token inherits that user's rights.",
        })
    credential_type: Literal["simplicate_api_key"] = Field("simplicate_api_key", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Subdomain", description="The company part of https://company.simplicate.app; enter only company.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API Secret", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def domain(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter only your lowercase Simplicate subdomain")
        return value

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key or secret")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value) or ":" in value:
            raise ValueError("Paste the key or secret without a header, colon or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, strict=True, description="Page number, starting at 1. This operation returns one page.")
    items_per_page: int = Field(30, ge=1, le=30, strict=True, title="Items Per Page")


class _ByID(_Input):
    id: str = Field(..., min_length=1, max_length=512, title="Resource ID", description="Opaque Simplicate identifier, such as project:1234abcd.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Resource IDs cannot contain control characters")
        return value


class ListCostTypesConfig(_Page):
    """List CostTypes."""
    operation: Literal["list_cost_types"] = Field("list_cost_types", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=191, description="Documented partial name or description filter.")


class ListHourTypesConfig(_Page):
    """List HourTypes."""
    operation: Literal["list_hour_types"] = Field("list_hour_types", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=191, description="Documented partial name or description filter.")


class ListDefaultServicesConfig(_Page):
    """List all available default services."""
    operation: Literal["list_default_services"] = Field("list_default_services", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=100, description="Documented partial name or description filter.")


class ListVatCodesConfig(_Page):
    """List VAT codes."""
    operation: Literal["list_vat_codes"] = Field("list_vat_codes", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=100, description="Documented partial name or description filter.")


class ListRevenueGroupsConfig(_Page):
    """List revenue groups."""
    operation: Literal["list_revenue_groups"] = Field("list_revenue_groups", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=100, description="Documented partial name or description filter.")


class ListRelationTypesConfig(_Page):
    """List all available relation types, sorted alphabetically by localized name."""
    operation: Literal["list_relation_types"] = Field("list_relation_types", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=191, description="Documented partial name or description filter.")


class ListInvoiceMethodsConfig(_Input):
    """List available invoice methods for services.."""
    operation: Literal["list_invoice_methods"] = Field("list_invoice_methods", json_schema_extra={"ui:hidden": True})


class ListSubscriptionCyclesConfig(_Input):
    """List available subscription cycle options for services.."""
    operation: Literal["list_subscription_cycles"] = Field("list_subscription_cycles", json_schema_extra={"ui:hidden": True})


class GetProjectConfig(_ByID):
    """Get project by id."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class GetProjectServiceConfig(_ByID):
    """Get project service by id."""
    operation: Literal["get_project_service"] = Field("get_project_service", json_schema_extra={"ui:hidden": True})


class GetInvoiceDraftRequestConfig(_ByID):
    """Get the status of an invoice draft request."""
    operation: Literal["get_invoice_draft_request"] = Field("get_invoice_draft_request", json_schema_extra={"ui:hidden": True})


class GetCostTypeConfig(_ByID):
    """Get CostType."""
    operation: Literal["get_cost_type"] = Field("get_cost_type", json_schema_extra={"ui:hidden": True})


class GetHourTypeConfig(_ByID):
    """Get HourType."""
    operation: Literal["get_hour_type"] = Field("get_hour_type", json_schema_extra={"ui:hidden": True})


class GetDefaultServiceConfig(_ByID):
    """Get a single default service by id."""
    operation: Literal["get_default_service"] = Field("get_default_service", json_schema_extra={"ui:hidden": True})


class GetVatCodeConfig(_ByID):
    """Get VAT code."""
    operation: Literal["get_vat_code"] = Field("get_vat_code", json_schema_extra={"ui:hidden": True})


class GetRevenueGroupConfig(_ByID):
    """Get revenue group."""
    operation: Literal["get_revenue_group"] = Field("get_revenue_group", json_schema_extra={"ui:hidden": True})


class CreateRelationTypeConfig(_Input):
    """Create a relation type."""
    operation: Literal["create_relation_type"] = Field("create_relation_type", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=191, min_length=1, title='Name')
    color: str = Field(..., min_length=1, max_length=512, pattern=r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$", title='Color')


class UpdateRelationTypeConfig(_Input):
    """Update a relation type by id."""
    operation: Literal["update_relation_type"] = Field("update_relation_type", json_schema_extra={"ui:hidden": True})
    relationTypeId: str = Field(..., min_length=1, max_length=512, title='Relation Type Id')
    name: str | None = Field(None, min_length=1, max_length=191, title='Name')
    color: str | None = Field(None, pattern=r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$", title='Color')


class DeleteRelationTypeConfig(_Input):
    """Delete a user-defined relation type by id."""
    operation: Literal["delete_relation_type"] = Field("delete_relation_type", json_schema_extra={"ui:hidden": True})
    relationTypeId: str = Field(..., min_length=1, max_length=512, title='Relation Type Id')


class SetDefaultRelationTypeConfig(_Input):
    """Set or clear the default relation type."""
    operation: Literal["set_default_relation_type"] = Field("set_default_relation_type", json_schema_extra={"ui:hidden": True})
    relationTypeId: str | None = Field(None, title='Relation Type Id', description="Existing relation type ID, or leave empty to clear the default.")


class CreateSaleServiceGroupConfig(_Input):
    """Add a new service group."""
    operation: Literal["create_sale_service_group"] = Field("create_sale_service_group", json_schema_extra={"ui:hidden": True})
    saleId: str = Field(..., min_length=1, max_length=512, title='Sale Id')
    name: str = Field(..., min_length=1, max_length=255, title='Name')
    description: str | None = Field(None, max_length=65535, title='Description')
    type: Literal['all_included', 'multiple_optional', 'single_required', 'single_optional'] = Field(..., title='Type')


class UpdateSaleServiceGroupConfig(_Input):
    """Update a service group."""
    operation: Literal["update_sale_service_group"] = Field("update_sale_service_group", json_schema_extra={"ui:hidden": True})
    serviceGroupId: str = Field(..., min_length=1, max_length=512, title='Service Group Id')
    name: str = Field(..., min_length=1, max_length=255, title='Name')
    description: str | None = Field(None, max_length=65535, title='Description')
    type: Literal['all_included', 'multiple_optional', 'single_required', 'single_optional'] = Field(..., title='Type')


class DeleteSaleServiceGroupConfig(_Input):
    """Delete a service group from the sale."""
    operation: Literal["delete_sale_service_group"] = Field("delete_sale_service_group", json_schema_extra={"ui:hidden": True})
    serviceGroupId: str = Field(..., min_length=1, max_length=512, title='Service Group Id')
    shouldDeleteServices: bool = Field(False, strict=True, title='Should Delete Services', description="Also delete the services in the group. Defaults to false; review before enabling.")


SimplicateConfig = Annotated[Union[
    ListCostTypesConfig,
    ListHourTypesConfig,
    ListDefaultServicesConfig,
    ListVatCodesConfig,
    ListRevenueGroupsConfig,
    ListRelationTypesConfig,
    ListInvoiceMethodsConfig,
    ListSubscriptionCyclesConfig,
    GetProjectConfig,
    GetProjectServiceConfig,
    GetInvoiceDraftRequestConfig,
    GetCostTypeConfig,
    GetHourTypeConfig,
    GetDefaultServiceConfig,
    GetVatCodeConfig,
    GetRevenueGroupConfig,
    CreateRelationTypeConfig,
    UpdateRelationTypeConfig,
    DeleteRelationTypeConfig,
    SetDefaultRelationTypeConfig,
    CreateSaleServiceGroupConfig,
    UpdateSaleServiceGroupConfig,
    DeleteSaleServiceGroupConfig], Field(discriminator="operation")]


class SimplicateFullConfig(NodeConfig[SimplicateConfig, SimplicateAPIKeyCredential]):
    pass


OPERATIONS = {'list_cost_types': ('GET', '/costType.list', 'page', 200),
 'list_hour_types': ('GET', '/hourType.list', 'page', 200),
 'list_default_services': ('GET', '/defaultService.list', 'page', 200),
 'list_vat_codes': ('GET', '/vatCode.list', 'page', 200),
 'list_revenue_groups': ('GET', '/revenueGroup.list', 'page', 200),
 'list_relation_types': ('GET', '/relation.relationtype.list', 'page', 200),
 'list_invoice_methods': ('GET', '/invoiceMethod.list', 'empty', 200),
 'list_subscription_cycles': ('GET', '/subscriptionCycle.list', 'empty', 200),
 'get_project': ('GET', '/project.get/{id}', 'id', 200),
 'get_project_service': ('GET', '/projectService.get/{id}', 'id', 200),
 'get_invoice_draft_request': ('GET', '/invoiceDraftRequest.get/{id}', 'id', 200),
 'get_cost_type': ('GET', '/costType.get/{id}', 'id', 200),
 'get_hour_type': ('GET', '/hourType.get/{id}', 'id', 200),
 'get_default_service': ('GET', '/defaultService.get/{id}', 'id', 200),
 'get_vat_code': ('GET', '/vatCode.get/{id}', 'id', 200),
 'get_revenue_group': ('GET', '/revenueGroup.get/{id}', 'id', 200),
 'create_relation_type': ('POST', '/relation.relationtype.create', 'body', 201),
 'update_relation_type': ('POST', '/relation.relationtype.update', 'body', 200),
 'delete_relation_type': ('POST', '/relation.relationtype.delete', 'body', 204),
 'set_default_relation_type': ('POST', '/relation.relationtype.setDefault', 'body', 204),
 'create_sale_service_group': ('POST', '/saleService.group.create', 'body', 201),
 'update_sale_service_group': ('POST', '/saleService.group.update', 'body', 201),
 'delete_sale_service_group': ('POST', '/saleService.group.delete', 'body', 201)}


class SimplicateNode(WorkflowNode):
    integration_type = "automation-simplicate"
    connection_evidence = ConnectionEvidence(noun="relation types", operation="list_relation_types")

    @classmethod
    def get_config_model(cls):
        return SimplicateFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Simplicate API key first")
        config = self.config.config
        method, path, kind, expected_status = OPERATIONS[config.operation]
        params, body = None, None
        if kind == "id":
            path = path.replace("{id}", quote(config.id, safe=""))
        elif kind == "page":
            params = {"page": config.page, "itemsPerPage": config.items_per_page}
            if getattr(config, "search", None) is not None:
                params["search"] = config.search
        elif kind == "body":
            body = config.model_dump(exclude={"operation"}, exclude_none=True)
            # Null explicitly clears the default relation type.
            if config.operation == "set_default_relation_type":
                body["relationTypeId"] = config.relationTypeId
        headers = {"Authorization": "Bearer " + credential.api_key + ":" + credential.api_secret,
                   "Accept": "application/json"}
        url = "https://" + credential.subdomain + ".simplicate.app/api/v3" + path
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, params=params,
                                            **({"json": body} if body is not None else {}))
        if response.status_code != expected_status:
            detail = "Simplicate returned an unexpected response"
            if response.headers.get("Content-Type", "").split(";", 1)[0] in {"application/json", "application/problem+json"}:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("detail"), str):
                    detail = error["detail"][:1000]
            for secret in (credential.api_key, credential.api_secret):
                detail = detail.replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": detail}
        if expected_status == 204:
            return {"status": "success", "http_status": 204}
        if len(response.content) > 5_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Expected bounded JSON from Simplicate")
        data = response.json()
        if not isinstance(data, dict) or "error" in data or "violations" in data:
            raise ValueError("Simplicate response was not a successful resource")
        output = {"status": "success", "http_status": expected_status, "data": data}
        if kind == "page":
            rows = data.get("data")
            pagination = data.get("metadata", {}).get("pagination")
            if not isinstance(rows, list) or not isinstance(pagination, dict):
                raise ValueError("Simplicate collection is missing data or pagination")
            output["data"] = rows
            output["pagination"] = pagination
            current, last = pagination.get("currentPage"), pagination.get("lastPage")
            if type(current) is not int or type(last) is not int or current < 1 or last < 0:
                raise ValueError("Simplicate pagination is invalid")
            output["next_page"] = current + 1 if current < last else None
        return output
