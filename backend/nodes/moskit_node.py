"""Moskit (now Ollow) CRM v2 operations using a manually supplied API key.

Routes, required write fields and pagination follow the pinned public v2 contract.
Each operation makes exactly one request, and writes are never retried.
"""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.ms.prod.ollow.services/v2"



class MoskitAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Moskit API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.moskitcrm.com/",
        "x-credential-instructions": "Paste your Moskit (now Ollow) v2 API key. NoClick sends it in the apikey header and reads contacts to check the connection.",
    })
    credential_type: Literal["moskit_api_key"] = Field("moskit_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    quantity: int = Field(50, ge=1, le=100, description="Maximum records in this page; no automatic pagination.")
    start: int | None = Field(None, ge=0)
    next_page_token: str | None = Field(None, min_length=1, max_length=4096, description="Token returned by the previous page.")
    sort: str | None = None
    order: Literal["asc", "desc"] | None = None

    @model_validator(mode="after")
    def pagination(self):
        if self.start is not None and self.next_page_token is not None:
            raise ValueError("Use start or next page token, not both")
        return self


class _OwnedWrite(_Input):
    created_by_id: int = Field(..., gt=0, description="Creating user's Moskit ID; required by the v2 contract, including updates.")
    responsible_id: int = Field(..., gt=0, description="Responsible user's Moskit ID.")


class _PersonWrite(_OwnedWrite):
    name: str = Field(..., min_length=1)
    email: str | None = Field(None, min_length=1, description="Email address; when updating, replaces the email collection with this address.")
    phone: str | None = Field(None, min_length=1, description="Phone number; when updating, replaces the phone collection with this number.")
    notes: str | None = None


class _DealWrite(_OwnedWrite):
    name: str = Field(..., min_length=1)
    status: Literal["OPEN", "WON", "LOST"] = Field(...)
    stage_id: int = Field(..., gt=0)
    price: int | None = Field(None, ge=0, description="Price in centavos: 1000 means R$10.00.")
    prevision_close_date: str | None = None
    close_date: str | None = None
    lost_reason_id: int | None = Field(None, gt=0)
    contact_ids: list[int] | None = None
    company_ids: list[int] | None = None


class _ActivityWrite(_OwnedWrite):
    title: str = Field(..., min_length=1)
    due_date: str = Field(..., min_length=1, description="Activity date/time in the provider's date format.")
    type_id: int = Field(..., gt=0)
    duration: int | None = Field(None, ge=0, description="Minutes")
    notes: str | None = None
    done_date: str | None = None
    done_notes: str | None = None
    contact_ids: list[int] | None = None
    company_ids: list[int] | None = None
    deal_ids: list[int] | None = None



class MoskitListContacts(_Page):
    """List contacts using the Moskit v2 endpoint."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class MoskitGetContact(_Input):
    """Get contact using the Moskit v2 endpoint."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)


class MoskitCreateContact(_PersonWrite):
    """Create contact using the Moskit v2 endpoint."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    cpf: str | None = None


class MoskitUpdateContact(_PersonWrite):
    """Update contact using the Moskit v2 endpoint."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)
    cpf: str | None = None


class MoskitDeleteContact(_Input):
    """Delete contact using the Moskit v2 endpoint."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)


class MoskitListCompanies(_Page):
    """List companies using the Moskit v2 endpoint."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class MoskitGetCompany(_Input):
    """Get company using the Moskit v2 endpoint."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0)


class MoskitCreateCompany(_PersonWrite):
    """Create company using the Moskit v2 endpoint."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    domain: str | None = None
    cnpj: str | None = None


class MoskitUpdateCompany(_PersonWrite):
    """Update company using the Moskit v2 endpoint."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0)
    domain: str | None = None
    cnpj: str | None = None


class MoskitDeleteCompany(_Input):
    """Delete company using the Moskit v2 endpoint."""
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0)


class MoskitListDeals(_Page):
    """List deals using the Moskit v2 endpoint."""
    operation: Literal["list_deals"] = Field("list_deals", json_schema_extra={"ui:hidden": True})


class MoskitGetDeal(_Input):
    """Get deal using the Moskit v2 endpoint."""
    operation: Literal["get_deal"] = Field("get_deal", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., gt=0)


class MoskitCreateDeal(_DealWrite):
    """Create deal using the Moskit v2 endpoint."""
    operation: Literal["create_deal"] = Field("create_deal", json_schema_extra={"ui:hidden": True})


class MoskitUpdateDeal(_DealWrite):
    """Update deal using the Moskit v2 endpoint."""
    operation: Literal["update_deal"] = Field("update_deal", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., gt=0)


class MoskitDeleteDeal(_Input):
    """Delete deal using the Moskit v2 endpoint."""
    operation: Literal["delete_deal"] = Field("delete_deal", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., gt=0)


class MoskitListActivities(_Page):
    """List activities using the Moskit v2 endpoint."""
    operation: Literal["list_activities"] = Field("list_activities", json_schema_extra={"ui:hidden": True})


class MoskitGetActivity(_Input):
    """Get activity using the Moskit v2 endpoint."""
    operation: Literal["get_activity"] = Field("get_activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., gt=0)


class MoskitCreateActivity(_ActivityWrite):
    """Create activity using the Moskit v2 endpoint."""
    operation: Literal["create_activity"] = Field("create_activity", json_schema_extra={"ui:hidden": True})


class MoskitUpdateActivity(_ActivityWrite):
    """Update activity using the Moskit v2 endpoint."""
    operation: Literal["update_activity"] = Field("update_activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., gt=0)


class MoskitListPipelines(_Page):
    """List pipelines using the Moskit v2 endpoint."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})


class MoskitListStages(_Page):
    """List stages using the Moskit v2 endpoint."""
    operation: Literal["list_stages"] = Field("list_stages", json_schema_extra={"ui:hidden": True})


class MoskitListUsers(_Page):
    """List users using the Moskit v2 endpoint."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class MoskitCreateContactNote(_Input):
    """Add a note to an existing contact."""
    operation: Literal["create_contact_note"] = Field("create_contact_note", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)
    description: str = Field(..., min_length=1)
    user_id: int | None = Field(None, gt=0)


class MoskitCreateDealNote(_Input):
    """Add a note to an existing deal."""
    operation: Literal["create_deal_note"] = Field("create_deal_note", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., gt=0)
    description: str = Field(..., min_length=1)
    user_id: int | None = Field(None, gt=0)

MoskitConfig = Annotated[Union[MoskitListContacts, MoskitGetContact, MoskitCreateContact, MoskitUpdateContact, MoskitDeleteContact, MoskitListCompanies, MoskitGetCompany, MoskitCreateCompany, MoskitUpdateCompany, MoskitDeleteCompany, MoskitListDeals, MoskitGetDeal, MoskitCreateDeal, MoskitUpdateDeal, MoskitDeleteDeal, MoskitListActivities, MoskitGetActivity, MoskitCreateActivity, MoskitUpdateActivity, MoskitListPipelines, MoskitListStages, MoskitListUsers, MoskitCreateContactNote, MoskitCreateDealNote], Field(discriminator="operation")]



class MoskitFullConfig(NodeConfig[MoskitConfig, MoskitAPIKeyCredential]):
    pass


ROUTES = {
    'list_contacts': ('GET', '/contacts'),
    'get_contact': ('GET', '/contacts/{contact_id}'),
    'create_contact': ('POST', '/contacts'),
    'update_contact': ('PUT', '/contacts/{contact_id}'),
    'delete_contact': ('DELETE', '/contacts/{contact_id}'),
    'list_companies': ('GET', '/companies'),
    'get_company': ('GET', '/companies/{company_id}'),
    'create_company': ('POST', '/companies'),
    'update_company': ('PUT', '/companies/{company_id}'),
    'delete_company': ('DELETE', '/companies/{company_id}'),
    'list_deals': ('GET', '/deals'),
    'get_deal': ('GET', '/deals/{deal_id}'),
    'create_deal': ('POST', '/deals'),
    'update_deal': ('PUT', '/deals/{deal_id}'),
    'delete_deal': ('DELETE', '/deals/{deal_id}'),
    'list_activities': ('GET', '/activities'),
    'get_activity': ('GET', '/activities/{activity_id}'),
    'create_activity': ('POST', '/activities'),
    'update_activity': ('PUT', '/activities/{activity_id}'),
    'list_pipelines': ('GET', '/pipelines'),
    'list_stages': ('GET', '/stages'),
    'list_users': ('GET', '/users'),
    'create_contact_note': ('POST', '/contacts/{contact_id}/notes'),
    'create_deal_note': ('POST', '/deals/{deal_id}/notes'),
}

# These are provider field names, not arbitrary user-supplied body keys.
BODY_FIELDS = {
    "name": "name", "notes": "notes", "domain": "domain", "cnpj": "cnpj", "cpf": "cpf",
    "title": "title", "status": "status", "price": "price", "description": "description",
    "due_date": "dueDate", "done_date": "doneDate", "done_notes": "doneNotes", "duration": "duration",
    "prevision_close_date": "previsionCloseDate", "close_date": "closeDate",
}
REFERENCES = {"created_by_id": "createdBy", "responsible_id": "responsible", "stage_id": "stage", "type_id": "type", "lost_reason_id": "lostReason", "user_id": "user"}
COLLECTIONS = {"contact_ids": "contacts", "company_ids": "companies", "deal_ids": "deals"}


def request_parts(config):
    values = config.model_dump(exclude_none=True)
    method, route = ROUTES[config.operation]
    route = route.format(**values)
    if config.operation.startswith("list_"):
        query = {("nextPageToken" if k == "next_page_token" else k): v for k, v in values.items() if k != "operation"}
        return method, route, query, None
    if method in {"GET", "DELETE"}:
        return method, route, {}, None
    body = {target: values[k] for k, target in BODY_FIELDS.items() if k in values}
    body.update({target: {"id": values[k]} for k, target in REFERENCES.items() if k in values})
    body.update({target: [{"id": v} for v in values[k]] for k, target in COLLECTIONS.items() if k in values})
    if "email" in values:
        body["emails"] = [{"address": values["email"]}]
    if "phone" in values:
        body["phones"] = [{"number": values["phone"]}]
    return method, route, {}, body



class MoskitNode(WorkflowNode):
    integration_type = "automation-moskit"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return MoskitFullConfig

    @staticmethod
    def _check_credential(data):
        credential = data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type", "moskit_api_key") != "moskit_api_key":
            raise ValueError("Attach a Moskit API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            return {"status": "error", "error": "Connect a Moskit API key"}
        method, route, params, body = request_parts(config)
        headers = {"apikey": credential.api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, params=params, **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                return {"status": "error", "http_status": response.status_code, "error": response.text[:2000].replace(credential.api_key, "[redacted]") or "Moskit rejected the request"}
            if method == "DELETE":
                if response.status_code != 204:
                    raise ValueError("Unexpected deletion response")
                return {"status": "success", "deleted": True, "http_status": 204}
            payload = response.json()
            listing = config.operation.startswith("list_")
            if (listing and (not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload))) or (not listing and not isinstance(payload, dict)):
                raise ValueError("Unexpected Moskit response shape")
            if isinstance(payload, dict) and any(k in payload for k in ("error", "errors")):
                raise ValueError("Moskit returned an error envelope")
            result = {"status": "success", "data": payload, "http_status": response.status_code}
            if listing:
                result["next_page_token"] = response.headers.get("X-Ollow-Listing-Next-Page-Token")
                result["has_more"] = bool(result["next_page_token"])
            return result
        except httpx.RequestError:
            return {"status": "error", "error": "Moskit request could not be confirmed; inspect writes before retrying"}
        except ValueError:
            return {"status": "error", "error": "Moskit returned an unexpected response; inspect writes before retrying"}
