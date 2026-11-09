"""Tomba contact discovery and lead management using a pasted key and secret.

Wire contract: https://docs.tomba.io/openapi.md and /authentication.
The older api-specification contract has obsolete paths and header names.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.tomba.io/v1"


class TombaApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tomba API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.tomba.io/api",
        "x-credential-instructions": "Copy your API key and account secret from Tomba’s API keys page. Both are required. NoClick sends them as X-Tomba-Key and X-Tomba-Secret headers to api.tomba.io. Connecting reads your leads without changing them.",
    })
    credential_type: Literal["tomba_api_key"] = Field("tomba_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="Account secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Tomba key or secret")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key or secret without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Domain(_Input):
    domain: str = Field(..., min_length=3, max_length=253, title="Company domain", description="A bare domain, for example stripe.com.")

    @field_validator("domain")
    @classmethod
    def bare_domain(cls, value):
        import re
        if not re.fullmatch(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value):
            raise ValueError("Enter a bare company domain such as stripe.com")
        return value.lower()


class DomainSearch(_Domain):
    operation: Literal["domain_search"] = Field("domain_search", title="Search Domain")
    page: int = Field(1, ge=1)
    limit: int = Field(10, ge=1, le=100, description="Email addresses per page. Each page is one request.")


class EmailFinder(_Domain):
    operation: Literal["email_finder"] = Field("email_finder", title="Find Email")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)


class EmailVerifier(_Input):
    operation: Literal["email_verifier"] = Field("email_verifier", title="Verify Email")
    email: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class DomainSuggestions(_Input):
    operation: Literal["domain_suggestions"] = Field("domain_suggestions", title="Suggest Domains")
    query: str = Field(..., min_length=1, max_length=255, title="Company name")


class Technology(_Domain):
    operation: Literal["technology"] = Field("technology", title="Get Domain Technologies")


def _picker(field):
    return {"x-dynamic-options": {"field_name": field, "allow_custom": True, "searchable": False}}


class _LeadId(_Input):
    lead_id: int = Field(..., ge=1, title="Lead", json_schema_extra=_picker("lead_id"))


class _ListId(_Input):
    list_id: int = Field(..., ge=1, title="Lead list", json_schema_extra=_picker("list_id"))


class ListLeads(_Input):
    operation: Literal["list_leads"] = Field("list_leads", title="List Leads")
    page: int = Field(1, ge=1)
    limit: int = Field(10, ge=1, le=200)
    list_id: int | None = Field(None, ge=1, title="Filter by lead list", json_schema_extra=_picker("list_id"))


class GetLead(_LeadId):
    operation: Literal["get_lead"] = Field("get_lead", title="Get Lead")


class _LeadFields(_Input):
    email: str | None = Field(None, max_length=320)
    first_name: str | None = Field(None, min_length=1, max_length=25)
    last_name: str | None = Field(None, min_length=1, max_length=25)
    company: str | None = Field(None, max_length=55)
    position: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=55)
    phone_number: str | None = Field(None, max_length=100)
    website_url: str | None = Field(None, max_length=253)
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    list_id: int | None = Field(None, ge=1, title="Lead list", json_schema_extra=_picker("list_id"))
    score: int | None = Field(None, ge=0, le=100)


class CreateLead(_LeadFields):
    """Create a lead; duplicate emails create additional leads. May invoke a configured Tomba lead webhook."""
    operation: Literal["create_lead"] = Field("create_lead", title="Create Lead")


class UpdateLead(_LeadFields, _LeadId):
    operation: Literal["update_lead"] = Field("update_lead", title="Update Lead")
    first_name: str | None = Field(None, min_length=2, max_length=25)
    last_name: str | None = Field(None, min_length=2, max_length=25)
    position: str | None = Field(None, max_length=25)

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_dump(exclude_none=True).keys() - {"operation", "lead_id"}:
            raise ValueError("Supply at least one lead field to update")
        return self


class DeleteLead(_LeadId):
    operation: Literal["delete_lead"] = Field("delete_lead", title="Delete Lead")


class ListLeadLists(_Input):
    operation: Literal["list_lead_lists"] = Field("list_lead_lists", title="List Lead Lists")


class GetLeadList(_ListId):
    operation: Literal["get_lead_list"] = Field("get_lead_list", title="Get Lead List")


class CreateLeadList(_Input):
    operation: Literal["create_lead_list"] = Field("create_lead_list", title="Create Lead List")
    name: str = Field(..., min_length=2, max_length=40, description="A unique list name.")
    favorite: bool = False


class UpdateLeadList(_ListId):
    operation: Literal["update_lead_list"] = Field("update_lead_list", title="Update Lead List")
    name: str | None = Field(None, min_length=2, max_length=40, description="Omit when changing only favorite; Tomba rejects the existing name.")
    favorite: bool = Field(..., description="Choose explicitly: Tomba always overwrites this flag.")


class DeleteLeadList(_ListId):
    """Delete a lead list; the leads in it are retained by Tomba."""
    operation: Literal["delete_lead_list"] = Field("delete_lead_list", title="Delete Lead List")


TombaConfig = Annotated[Union[DomainSearch, EmailFinder, EmailVerifier, DomainSuggestions, Technology,
    ListLeads, GetLead, CreateLead, UpdateLead, DeleteLead, ListLeadLists, GetLeadList,
    CreateLeadList, UpdateLeadList, DeleteLeadList], Field(discriminator="operation")]


class TombaFullConfig(NodeConfig[TombaConfig, TombaApiKeyCredential]):
    pass


ROUTES = {
    "domain_search": ("GET", "/domain-search"), "email_finder": ("GET", "/email-finder"),
    "email_verifier": ("GET", "/email-verifier"), "domain_suggestions": ("GET", "/domain-suggestions"),
    "technology": ("GET", "/technology"), "list_leads": ("GET", "/leads"),
    "get_lead": ("GET", "/leads/{lead_id}"), "create_lead": ("POST", "/leads"),
    "update_lead": ("PUT", "/leads/{lead_id}"), "delete_lead": ("DELETE", "/leads/{lead_id}"),
    "list_lead_lists": ("GET", "/leads_lists"), "get_lead_list": ("GET", "/leads_lists/{list_id}"),
    "create_lead_list": ("POST", "/leads_lists"), "update_lead_list": ("PUT", "/leads_lists/{list_id}"),
    "delete_lead_list": ("DELETE", "/leads_lists/{list_id}"),
}


def _redact(value, credential):
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items() if k.lower() not in {"secret_token", "api_key", "api_secret", "secret", "token"}}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
    return value


async def _request(credential, method, path, *, params=None, body=None):
    async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
        response = await client.request(method, BASE + path, params=params, json=body, headers={
            "X-Tomba-Key": credential.api_key, "X-Tomba-Secret": credential.api_secret, "Accept": "application/json",
        })
    try:
        data = response.json()
    except ValueError:
        raise ValueError(f"Tomba returned a non-JSON response (HTTP {response.status_code})") from None
    if not isinstance(data, dict):
        raise ValueError("Tomba returned an invalid response envelope")
    if not response.is_success or data.get("errors"):
        error = data.get("errors", {})
        message = error.get("message") if isinstance(error, dict) else None
        raise ValueError(_redact(message or f"Tomba request failed (HTTP {response.status_code})", credential))
    if isinstance(data.get("data"), dict) and data["data"].get("status") is False:
        raise ValueError(_redact(data["data"].get("message") or "Tomba did not confirm the change", credential))
    if "data" not in data:
        raise ValueError("Tomba response is missing data")
    return _redact(data, credential)


class TombaNode(WorkflowNode):
    integration_type = "automation-tomba"
    connection_evidence = ConnectionEvidence(operation="list_leads", noun="Tomba leads")

    @classmethod
    def get_config_model(cls):
        return TombaFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Tomba API key and account secret")
        op = self.config.config
        method, path = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("lead_id", "list_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(fields.pop(key)), safe=""))
        if op.operation == "list_leads" and "list_id" in fields:
            fields["list"] = fields.pop("list_id")
        result = await _request(self.config.credentials, method, path,
            params=fields if method == "GET" else None,
            body=fields if method in {"POST", "PUT"} else None)
        if op.operation == "list_leads" and (not isinstance(result["data"], dict) or not isinstance(result["data"].get("leads"), list)):
            raise ValueError("Tomba response is missing the leads array")
        return {"status": "success", "operation": op.operation, **result}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, *, page_token=None, search=None):
        if field_name not in {"lead_id", "list_id"}:
            return []
        credential = TombaApiKeyCredential.model_validate(credential_data)
        if field_name == "list_id":
            result = await _request(credential, "GET", "/leads_lists")
            rows = result["data"]["list_leads"]
            return [{"value": str(row["id"]), "label": row["name"]} for row in rows]
        page = int(page_token) if page_token is not None else 1
        if page < 1:
            raise ValueError("Invalid lead page")
        result = await _request(credential, "GET", "/leads", params={"page": page, "limit": 200})
        rows = result["data"]["leads"]
        total = result.get("meta", {}).get("total")
        if rows and not isinstance(total, int):
            raise ValueError("Tomba lead page is missing its total")
        has_more = bool(rows) and page * 200 < total
        return {"options": [{"value": str(row["id"]), "label": row.get("email") or str(row["id"])} for row in rows],
            "next_page_token": str(page + 1) if has_more else None}
