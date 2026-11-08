"""Givebutter v1 donor CRM and fundraising operations.

Each operation makes one request to the published API contract. List operations
return the first page and its pagination metadata; links are never followed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.givebutter.com"


class GivebutterAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Givebutter API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.givebutter.com/en/articles/5489015-how-to-access-the-givebutter-public-api-key",
            "x-credential-instructions": "In Givebutter, open Settings → Developers → API and copy your API key. Paste the key without the Bearer prefix. NoClick sends it only to api.givebutter.com. Access to your campaigns is checked when connecting.",
        })
    credential_type: Literal["givebutter_api_key"] = Field("givebutter_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


ID = Annotated[int, Field(gt=0)]
Name = Annotated[str, Field(min_length=1, max_length=255)]
Tag = Annotated[str, Field(min_length=1, max_length=64)]


class _Input(BaseModel):
    # Saved workflows carry editor metadata such as credentialIds beside inputs.
    # Pydantic retains declared fields only, so metadata never reaches the API.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class ListCampaigns(_Input):
    """List the first page of account campaigns, with pagination metadata."""
    operation: Literal["list_campaigns"] = "list_campaigns"
    scope: str | None = None


class GetCampaign(_Input):
    """Read a campaign by its Givebutter ID."""
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: ID


class CreateCampaign(_Input):
    """Create a fundraising campaign."""
    operation: Literal["create_campaign"] = "create_campaign"
    type: Literal["general", "collect", "fundraise", "event"]
    title: str = Field(..., min_length=1, max_length=150)
    subtitle: Name | None = None
    description: str | None = None
    goal: int | None = Field(None, ge=0)
    slug: Name | None = None
    end_at: AwareDatetime | None = None
    timezone: Name | None = None


class UpdateCampaign(_Input):
    """Update campaign details; only supplied fields are sent."""
    operation: Literal["update_campaign"] = "update_campaign"
    campaign_id: ID
    title: str | None = Field(None, min_length=1, max_length=150)
    subtitle: Name | None = None
    description: str | None = None
    goal: int | None = Field(None, ge=0)
    end_at: AwareDatetime | None = None


class ListContacts(_Input):
    """Find donors by email or name; returns one page and pagination metadata."""
    operation: Literal["list_contacts"] = "list_contacts"
    email: str | None = None
    firstName: str | None = Field(None, max_length=1000)
    lastName: str | None = Field(None, max_length=1000)
    type: Literal["individual", "company"] | None = None
    tags: str | None = None
    updatedAfter: AwareDatetime | None = None
    createdAfter: AwareDatetime | None = None


class GetContact(_Input):
    """Read one contact."""
    operation: Literal["get_contact"] = "get_contact"
    contact_id: ID


class CreateContact(_Input):
    """Create an individual donor contact without forcing a duplicate."""
    operation: Literal["create_contact"] = "create_contact"
    first_name: Name
    last_name: Name
    primary_email: str | None = None
    primary_phone: str | None = None
    external_id: Name | None = None
    note: str | None = None
    tags: list[Tag] | None = None


class UpdateContact(_Input):
    """Update supplied donor profile fields."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: ID
    first_name: Name | None = None
    last_name: Name | None = None
    preferred_name: Name | None = None
    external_id: Name | None = None
    note: str | None = None


class RestoreContact(_Input):
    """Restore an archived contact."""
    operation: Literal["restore_contact"] = "restore_contact"
    contact_id: ID


class AddContactTags(_Input):
    """Add tags while retaining the contact's existing tags."""
    operation: Literal["add_contact_tags"] = "add_contact_tags"
    contact_id: ID
    tags: list[Tag] = Field(..., min_length=1)


class RemoveContactTags(_Input):
    """Remove the named tags from a contact."""
    operation: Literal["remove_contact_tags"] = "remove_contact_tags"
    contact_id: ID
    tags: list[Tag] = Field(..., min_length=1)


class ListContactActivities(_Input):
    """Read the first page of a contact's activity timeline."""
    operation: Literal["list_contact_activities"] = "list_contact_activities"
    contact_id: ID


class CreateContactActivity(_Input):
    """Record a donor interaction or volunteer activity."""
    operation: Literal["create_contact_activity"] = "create_contact_activity"
    contact_id: ID
    type: Literal["email", "meeting", "note", "phone_call", "sms", "completed_task", "volunteer_activity"]
    subject: Name | None = None
    note: str | None = None
    occurred_at: AwareDatetime | None = None
    timezone: Name | None = None


class ListFunds(_Input):
    """List the first page of designation funds."""
    operation: Literal["list_funds"] = "list_funds"


class GetFund(_Input):
    """Read one designation fund."""
    operation: Literal["get_fund"] = "get_fund"
    fund_id: ID


class CreateFund(_Input):
    """Create a designation fund."""
    operation: Literal["create_fund"] = "create_fund"
    name: Name
    code: Name | None = None


class UpdateFund(_Input):
    """Update a designation fund's name and optional code."""
    operation: Literal["update_fund"] = "update_fund"
    fund_id: ID
    name: Name
    code: Name | None = None


class ListTransactions(_Input):
    """List the first page of donations, optionally filtered by dates or contacts."""
    operation: Literal["list_transactions"] = "list_transactions"
    transactedAfter: AwareDatetime | None = None
    transactedBefore: AwareDatetime | None = None
    updatedAfter: AwareDatetime | None = None
    contacts: str | None = None
    method: str | None = None
    scope: Literal["all", "benefiting", "chapters"] | None = None


class GetTransaction(_Input):
    """Read one donation transaction."""
    operation: Literal["get_transaction"] = "get_transaction"
    transaction_id: ID


class ListPlans(_Input):
    """List the first page of recurring donation plans."""
    operation: Literal["list_plans"] = "list_plans"


class GetPlan(_Input):
    """Read one recurring donation plan."""
    operation: Literal["get_plan"] = "get_plan"
    plan_id: ID


GivebutterOperation = Annotated[Union[
    ListCampaigns, GetCampaign, CreateCampaign, UpdateCampaign,
    ListContacts, GetContact, CreateContact, UpdateContact, RestoreContact,
    AddContactTags, RemoveContactTags, ListContactActivities, CreateContactActivity,
    ListFunds, GetFund, CreateFund, UpdateFund, ListTransactions, GetTransaction,
    ListPlans, GetPlan,
], Field(discriminator="operation")]


class GivebutterConfig(NodeConfig[GivebutterOperation, GivebutterAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Exact method/path pairs from https://givebutter.com/docs/api.json (v1.0.0).
ROUTES = {
    "list_campaigns": ("GET", "/v1/campaigns"),
    "get_campaign": ("GET", "/v1/campaigns/{campaign_id}"),
    "create_campaign": ("POST", "/v1/campaigns"),
    "update_campaign": ("PUT", "/v1/campaigns/{campaign_id}"),
    "list_contacts": ("GET", "/v1/contacts"),
    "get_contact": ("GET", "/v1/contacts/{contact_id}"),
    "create_contact": ("POST", "/v1/contacts"),
    "update_contact": ("PUT", "/v1/contacts/{contact_id}"),
    "restore_contact": ("PATCH", "/v1/contacts/{contact_id}/restore"),
    "add_contact_tags": ("POST", "/v1/contacts/{contact_id}/tags/add"),
    "remove_contact_tags": ("POST", "/v1/contacts/{contact_id}/tags/remove"),
    "list_contact_activities": ("GET", "/v1/contacts/{contact_id}/activities"),
    "create_contact_activity": ("POST", "/v1/contacts/{contact_id}/activities"),
    "list_funds": ("GET", "/v1/funds"),
    "get_fund": ("GET", "/v1/funds/{fund_id}"),
    "create_fund": ("POST", "/v1/funds"),
    "update_fund": ("PUT", "/v1/funds/{fund_id}"),
    "list_transactions": ("GET", "/v1/transactions"),
    "get_transaction": ("GET", "/v1/transactions/{transaction_id}"),
    "list_plans": ("GET", "/v1/plans"),
    "get_plan": ("GET", "/v1/plans/{plan_id}"),
}


class GivebutterNode(WorkflowNode):
    integration_type = "automation-givebutter"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return GivebutterConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Givebutter API key")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        if config.operation in {"update_contact", "update_campaign"} and not values:
            raise ValueError("Supply at least one field to update")
        key = self.config.credentials.api_key
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Givebutter could not be reached; inspect write outcomes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Retain provider rejection text for the connection seam; never emit the credential.
            try:
                payload = response.json()
                message = payload.get("message") if isinstance(payload, dict) else None
            except ValueError:
                message = None
            message = message if isinstance(message, str) else "Givebutter request failed"
            result = {"status": "error", "http_status": response.status_code, "message": message[:2000].replace(key, "[redacted]")}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Givebutter response exceeds the supported size")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Givebutter returned an unexpected non-JSON response") from None
            if not isinstance(payload, (dict, list)) or isinstance(payload, dict) and ("errors" in payload or payload.get("success") is False):
                raise ValueError("Givebutter returned an unexpected response")
            if config.operation.startswith("list_") and (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)):
                raise ValueError("Givebutter list response is missing its data array")
            result = {"status": "success", "operation": config.operation, "http_status": response.status_code,
                **({"data": payload["data"], "links": payload.get("links"), "meta": payload.get("meta")} if config.operation.startswith("list_") else {"data": payload})}
        await self.emit(result)
        return result
