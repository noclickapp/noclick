"""Wodify Core v1: fixed client, lead, scheduling and membership endpoints.

Contract: https://docs.wodify.com/openapi/{client,lead,class,membership,program,customer,utils}-api.json.
Each operation sends one request. Lists return one page and the provider's pagination.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.wodify.com/v1"
CREDENTIAL_TYPE = "wodify_core_api_key"


def _picker(field):
    return {"x-dynamic-options": {"field_name": field, "allow_custom": True, "searchable": False}}


class WodifyCoreApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Wodify Core API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.wodify.com/reference/get_clients",
            "x-credential-instructions": "In Wodify, open Automations → Integrations and request an API key. Paste the key here. NoClick sends it to api.wodify.com as x-api-key."
        })
    credential_type: Literal["wodify_core_api_key"] = Field("wodify_core_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Wodify API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _LocationPage(_Input):
    page: int = Field(1, ge=1, le=2147483647, description="Page number; each execution returns one page.")
    page_size: int = Field(100, ge=1, le=100, title="Page Size")


class _Page(_LocationPage):
    sort: str | None = Field(None, max_length=200, description="Wodify sort expression, for example desc_updated_on.")


class _Search(_Page):
    q: str = Field(..., min_length=1, max_length=4096, title="Search Value",
        description="Search value sent as the endpoint's documented q parameter.")


class _Client(_Input):
    client_id: int = Field(..., ge=1, le=9223372036854775807, title="Client", json_schema_extra=_picker("client_id"))


class _Lead(_Input):
    lead_id: int = Field(..., ge=1, le=9223372036854775807, title="Lead", json_schema_extra=_picker("lead_id"))


class _Class(_Input):
    class_id: int = Field(..., ge=1, le=9223372036854775807, title="Class", json_schema_extra=_picker("class_id"))


class _Membership(_Input):
    membership_id: int = Field(..., ge=1, le=9223372036854775807, title="Membership", json_schema_extra=_picker("membership_id"))


class _ClientPage(_Page, _Client):
    pass


class _Contact(_Input):
    first_name: str | None = Field(None, max_length=500)
    last_name: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=1000)
    phone_number: str | None = Field(None, max_length=100)
    date_of_birth: date | None = None
    gender_id: int | None = Field(None, ge=0, le=2147483647, json_schema_extra=_picker("gender_id"))
    notes: str | None = Field(None, max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    location_id: int | None = Field(None, ge=1, le=9223372036854775807, json_schema_extra=_picker("location_id"))
    lead_source_id: int | None = Field(None, ge=1, le=9223372036854775807, json_schema_extra=_picker("lead_source_id"))


class _ClientContact(_Contact):
    gender_id: int | None = Field(None, ge=1, le=9223372036854775807, json_schema_extra=_picker("gender_id"))
    client_status_id: int | None = Field(None, ge=1, le=9223372036854775807)


class _LeadContact(_Contact):
    lead_status_id: int | None = Field(None, ge=1, le=9223372036854775807, json_schema_extra=_picker("lead_status_id"))


class _CreateClient(_ClientContact):
    first_name: str = Field(..., min_length=1, max_length=500)
    last_name: str = Field(..., min_length=1, max_length=500)
    email: str = Field(..., min_length=1, max_length=1000)
    date_of_birth: date
    gender_id: int = Field(..., ge=1, le=9223372036854775807, json_schema_extra=_picker("gender_id"))


class _CreateLead(_LeadContact):
    location_id: int = Field(..., ge=1, le=9223372036854775807, json_schema_extra=_picker("location_id"))


class _UpdateClient(_ClientContact, _Client):
    pass


class _UpdateLead(_LeadContact, _Lead):
    pass


class _Tags(_Input):
    tags: list[str] = Field(..., min_length=1, max_length=1000,
        description="Tag names as a JSON array, as required by the Wodify request schema.")


class _TagsClient(_Tags, _Client):
    pass


class _TagsLead(_Tags, _Lead):
    pass


class WodifyListClients(_Page):
    operation: Literal["list_clients"] = Field("list_clients", title="List Clients", json_schema_extra={"ui:hidden": True})


class WodifySearchClients(_Search):
    operation: Literal["search_clients"] = Field("search_clients", title="Search Clients", json_schema_extra={"ui:hidden": True})


class WodifyGetClient(_Client):
    operation: Literal["get_client"] = Field("get_client", title="Get Client", json_schema_extra={"ui:hidden": True})


class WodifyCreateClient(_CreateClient):
    operation: Literal["create_client"] = Field("create_client", title="Create Client", json_schema_extra={"ui:hidden": True})


class WodifyUpdateClient(_UpdateClient):
    operation: Literal["update_client"] = Field("update_client", title="Update Client", json_schema_extra={"ui:hidden": True})


class WodifyAddClientTags(_TagsClient):
    operation: Literal["add_client_tags"] = Field("add_client_tags", title="Add Client Tags", json_schema_extra={"ui:hidden": True})


class WodifyRemoveClientTags(_TagsClient):
    operation: Literal["remove_client_tags"] = Field("remove_client_tags", title="Remove Client Tags", json_schema_extra={"ui:hidden": True})


class WodifyListLeads(_Page):
    operation: Literal["list_leads"] = Field("list_leads", title="List Leads", json_schema_extra={"ui:hidden": True})


class WodifySearchLeads(_Search):
    operation: Literal["search_leads"] = Field("search_leads", title="Search Leads", json_schema_extra={"ui:hidden": True})


class WodifyGetLead(_Lead):
    operation: Literal["get_lead"] = Field("get_lead", title="Get Lead", json_schema_extra={"ui:hidden": True})


class WodifyCreateLead(_CreateLead):
    operation: Literal["create_lead"] = Field("create_lead", title="Create Lead", json_schema_extra={"ui:hidden": True})


class WodifyUpdateLead(_UpdateLead):
    operation: Literal["update_lead"] = Field("update_lead", title="Update Lead", json_schema_extra={"ui:hidden": True})


class WodifyAddLeadTags(_TagsLead):
    operation: Literal["add_lead_tags"] = Field("add_lead_tags", title="Add Lead Tags", json_schema_extra={"ui:hidden": True})


class WodifyRemoveLeadTags(_TagsLead):
    operation: Literal["remove_lead_tags"] = Field("remove_lead_tags", title="Remove Lead Tags", json_schema_extra={"ui:hidden": True})


class WodifyListClasses(_Page):
    operation: Literal["list_classes"] = Field("list_classes", title="List Classes", json_schema_extra={"ui:hidden": True})


class WodifyGetClass(_Class):
    operation: Literal["get_class"] = Field("get_class", title="Get Class", json_schema_extra={"ui:hidden": True})


class WodifyListMemberships(_Page):
    operation: Literal["list_memberships"] = Field("list_memberships", title="List Memberships", json_schema_extra={"ui:hidden": True})


class WodifyGetMembership(_Membership):
    operation: Literal["get_membership"] = Field("get_membership", title="Get Membership", json_schema_extra={"ui:hidden": True})


class WodifyListClientReservations(_ClientPage):
    operation: Literal["list_client_reservations"] = Field("list_client_reservations", title="List Client Reservations", json_schema_extra={"ui:hidden": True})


class WodifyListClientSignIns(_ClientPage):
    operation: Literal["list_client_sign_ins"] = Field("list_client_sign_ins", title="List Client Sign Ins", json_schema_extra={"ui:hidden": True})


class WodifyListPrograms(_Page):
    operation: Literal["list_programs"] = Field("list_programs", title="List Programs", json_schema_extra={"ui:hidden": True})


class WodifyListLeadSources(_Page):
    operation: Literal["list_lead_sources"] = Field("list_lead_sources", title="List Lead Sources", json_schema_extra={"ui:hidden": True})


class WodifyListLeadStatuses(_Page):
    operation: Literal["list_lead_statuses"] = Field("list_lead_statuses", title="List Lead Statuses", json_schema_extra={"ui:hidden": True})


class WodifyListLocations(_LocationPage):
    operation: Literal["list_locations"] = Field("list_locations", title="List Locations", json_schema_extra={"ui:hidden": True})


class WodifyListGenders(_Page):
    operation: Literal["list_genders"] = Field("list_genders", title="List Genders", json_schema_extra={"ui:hidden": True})


WodifyCoreConfig = Annotated[Union[
    WodifyListClients,
    WodifySearchClients,
    WodifyGetClient,
    WodifyCreateClient,
    WodifyUpdateClient,
    WodifyAddClientTags,
    WodifyRemoveClientTags,
    WodifyListLeads,
    WodifySearchLeads,
    WodifyGetLead,
    WodifyCreateLead,
    WodifyUpdateLead,
    WodifyAddLeadTags,
    WodifyRemoveLeadTags,
    WodifyListClasses,
    WodifyGetClass,
    WodifyListMemberships,
    WodifyGetMembership,
    WodifyListClientReservations,
    WodifyListClientSignIns,
    WodifyListPrograms,
    WodifyListLeadSources,
    WodifyListLeadStatuses,
    WodifyListLocations,
    WodifyListGenders
], Field(discriminator="operation")]


class WodifyCoreNodeConfig(NodeConfig[WodifyCoreConfig, WodifyCoreApiKeyCredential]):
    model_config = ConfigDict(title="Wodify Core Node Configuration")


ROUTES = {'list_clients': ('GET', '/clients'), 'search_clients': ('GET', '/clients/search'), 'get_client': ('GET', '/clients/{client_id}'), 'create_client': ('POST', '/clients'), 'update_client': ('PUT', '/clients/{client_id}'), 'add_client_tags': ('PUT', '/clients/{client_id}/tags'), 'remove_client_tags': ('DELETE', '/clients/{client_id}/tags'), 'list_leads': ('GET', '/leads'), 'search_leads': ('GET', '/leads/search'), 'get_lead': ('GET', '/leads/{lead_id}'), 'create_lead': ('POST', '/leads'), 'update_lead': ('PUT', '/leads/{lead_id}'), 'add_lead_tags': ('PUT', '/leads/{lead_id}/tags'), 'remove_lead_tags': ('DELETE', '/leads/{lead_id}/tags'), 'list_classes': ('GET', '/classes'), 'get_class': ('GET', '/classes/{class_id}'), 'list_memberships': ('GET', '/memberships'), 'get_membership': ('GET', '/memberships/{membership_id}'), 'list_client_reservations': ('GET', '/clients/{client_id}/classes/reservations'), 'list_client_sign_ins': ('GET', '/clients/{client_id}/classes/sign-ins'), 'list_programs': ('GET', '/programs'), 'list_lead_sources': ('GET', '/leads/sources'), 'list_lead_statuses': ('GET', '/leads/statuses'), 'list_locations': ('GET', '/customers/locations'), 'list_genders': ('GET', '/utilities/genders')}

# The wire response names are used by the same list request for dropdowns and proof.
PICKERS = {
    "client_id": ("list_clients", "clients", "client_id"),
    "lead_id": ("list_leads", "leads", "lead_id"),
    "class_id": ("list_classes", "classes", "class_id"),
    "membership_id": ("list_memberships", "memberships", "membership_id"),
    "location_id": ("list_locations", "locations", "location_id"),
    "gender_id": ("list_genders", "genders", "gender_id"),
    "lead_source_id": ("list_lead_sources", "sources", "id"),
    "lead_status_id": ("list_lead_statuses", "statuses", "id"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class WodifyCoreNode(WorkflowNode):
    integration_type = "automation-wodify-core"
    connection_evidence = ConnectionEvidence(field="location_id", noun="locations")

    @classmethod
    def get_config_model(cls):
        return WodifyCoreNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, *, config=None, credential_data=None,
                                 user_id=None, search=None, page_token=None, **kwargs):
        if field_name not in PICKERS:
            return {"options": []}
        operation, collection, id_key = PICKERS[field_name]
        page = int(page_token) if page_token else 1
        from nodes.core.run_op import run_node_operation
        result = await run_node_operation(node_type=cls.integration_type, operation=operation,
            arguments={"page": page}, credential_data=credential_data, user_id=user_id)
        body = result["data"]
        if not isinstance(body.get(collection), list):
            raise ValueError("Wodify did not return the requested resource list")
        options = []
        for row in body[collection]:
            if not isinstance(row, dict):
                raise ValueError("Wodify returned an invalid resource list")
            identifier = row.get(id_key, row.get("id"))
            if identifier is None:
                continue
            name = row.get("name") or row.get("location") or row.get("gender") or row.get("source") or row.get("status")
            name = name or " ".join(str(row.get(key) or "") for key in ("first_name", "last_name")).strip()
            options.append({"value": str(identifier), "label": str(name or identifier)})
        pagination = body.get("pagination", {})
        return {"options": options, "next_page_token": str(page + 1) if pagination.get("has_more") else None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wodify Core API key")
        cfg = self.config.config
        values = cfg.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        method, path = ROUTES[cfg.operation]
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        api_key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"x-api-key": api_key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"json": values}))
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Wodify HTTP {response.status_code}: " + _redact(response.text[:2000], api_key))
        if len(response.content) > 10_000_000:
            raise ValueError("Wodify response exceeds the JSON size limit")
        try:
            body = response.json() if response.content else {}
        except ValueError:
            raise ValueError("Wodify returned an invalid JSON response") from None
        if not isinstance(body, dict):
            raise ValueError("Wodify returned an unexpected JSON response")
        if body.get("wodify_validation_result") or body.get("is_success") is False:
            raise ValueError(_redact(str(body.get("wodify_validation_result") or "Wodify reported an unsuccessful action"), api_key))
        result = {"status": "success", "operation": cfg.operation, "data": _redact(body, api_key)}
        await self.emit(result)
        return result
