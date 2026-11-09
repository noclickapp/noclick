"""GoFundMe Pro v2 fundraising and donor CRM operations.

Each operation maps to one published method/path. Lists return one page and the
provider's pagination metadata without following response URLs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://pro.gofundme.com/api/2.0"
ID = Annotated[int, Field(gt=0)]


class GoFundMeProAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="GoFundMe Pro Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.gofundme.com/pro/overview/authentication",
            "x-credential-instructions": "Paste an existing GoFundMe Pro bearer access token and your organization ID. Use a token authorized for that organization's resources and the reads or writes you need. API credentials are created in the organization admin dashboard; the documented client-credentials exchange issues app access tokens. Tokens expire (the documentation example lasts 3600 seconds); replace an expired token here. NoClick checks campaigns when connecting.",
        })
    credential_type: Literal["gofundme_pro_access_token"] = Field("gofundme_pro_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})
    organization_id: ID = Field(..., title="Organization ID", description="Numeric ID of the organization whose resources to list or create.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without spaces or the Bearer prefix")
        return value


class _Input(BaseModel):
    # Saved editor metadata must never be forwarded to the provider.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; each run reads one page.")
    per_page: int = Field(20, ge=1, le=100, description="Results per page (maximum 100).")


class ListCampaigns(_Page):
    """List one page of organization campaigns."""
    operation: Literal["list_campaigns"] = "list_campaigns"


class GetCampaign(_Input):
    """Read one campaign."""
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: ID


class ListSupporters(_Page):
    """List one page of organization supporters."""
    operation: Literal["list_supporters"] = "list_supporters"


class GetSupporter(_Input):
    """Read one supporter."""
    operation: Literal["get_supporter"] = "get_supporter"
    supporter_id: ID


class ListTransactions(_Page):
    """List one page of organization transactions."""
    operation: Literal["list_transactions"] = "list_transactions"


class GetTransaction(_Input):
    """Read one transaction."""
    operation: Literal["get_transaction"] = "get_transaction"
    transaction_id: ID


class ListDesignations(_Page):
    """List one page of organization designations."""
    operation: Literal["list_designations"] = "list_designations"


class GetDesignation(_Input):
    """Read one designation."""
    operation: Literal["get_designation"] = "get_designation"
    designation_id: ID


class ListRecurringDonationPlans(_Page):
    """List one page of organization recurring-donation-plans."""
    operation: Literal["list_recurring_donation_plans"] = "list_recurring_donation_plans"


class GetRecurringDonationPlan(_Input):
    """Read one recurring-donation-plan."""
    operation: Literal["get_recurring_donation_plan"] = "get_recurring_donation_plan"
    recurring_donation_plan_id: ID


class ListFundraisingPages(_Page):
    """List one page of organization fundraising-pages."""
    operation: Literal["list_fundraising_pages"] = "list_fundraising_pages"


class GetFundraisingPage(_Input):
    """Read one fundraising-page."""
    operation: Literal["get_fundraising_page"] = "get_fundraising_page"
    fundraising_page_id: ID


class ListFundraisingTeams(_Page):
    """List one page of organization fundraising-teams."""
    operation: Literal["list_fundraising_teams"] = "list_fundraising_teams"


class GetFundraisingTeam(_Input):
    """Read one fundraising-team."""
    operation: Literal["get_fundraising_team"] = "get_fundraising_team"
    fundraising_team_id: ID


class _SupporterFields(_Input):
    email_address: EmailStr | None = None
    first_name: str | None = Field(None, max_length=32)
    last_name: str | None = Field(None, max_length=32)
    nickname: str | None = Field(None, max_length=32)
    phone: str | None = Field(None, max_length=16)
    cell_phone: str | None = Field(None, max_length=32)
    address1: str | None = Field(None, max_length=512)
    address2: str | None = Field(None, max_length=45)
    city: str | None = Field(None, max_length=45)
    state: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=50)
    country: str | None = Field(None, min_length=2, max_length=2)


class CreateSupporter(_SupporterFields):
    """Create an organization supporter from supplied profile fields."""
    operation: Literal["create_supporter"] = "create_supporter"


class UpdateSupporter(_SupporterFields):
    """Update only supplied supporter profile fields."""
    operation: Literal["update_supporter"] = "update_supporter"
    supporter_id: ID


class _DesignationFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=127)
    description: str | None = None
    external_reference_id: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    is_complete: bool | None = None
    is_default: bool | None = None
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, min_length=2, max_length=2)
    postal_code: str | None = Field(None, max_length=50)


class CreateDesignation(_DesignationFields):
    """Create a designation fund."""
    operation: Literal["create_designation"] = "create_designation"
    name: str = Field(..., min_length=1, max_length=127)


class UpdateDesignation(_DesignationFields):
    """Update only supplied designation fields."""
    operation: Literal["update_designation"] = "update_designation"
    designation_id: ID


class UpdateTransaction(_Input):
    """Update donation comments, reporting and visibility fields."""
    operation: Literal["update_transaction"] = "update_transaction"
    transaction_id: ID
    comment: str | None = None
    fundraising_tracking_code: str | None = None
    company_name: str | None = None
    hide_amount: bool | None = None
    is_anonymous: bool | None = None


class ListCampaignTransactions(_Page):
    """List one page of campaign transactions."""
    operation: Literal["list_campaign_transactions"] = "list_campaign_transactions"
    campaign_id: ID


class ListCampaignFundraisingPages(_Page):
    """List one page of campaign fundraising-pages."""
    operation: Literal["list_campaign_fundraising_pages"] = "list_campaign_fundraising_pages"
    campaign_id: ID


GoFundMeProOperation = Annotated[Union[
    ListCampaigns, GetCampaign, ListSupporters, GetSupporter, ListTransactions, GetTransaction, ListDesignations, GetDesignation, ListRecurringDonationPlans, GetRecurringDonationPlan, ListFundraisingPages, GetFundraisingPage, ListFundraisingTeams, GetFundraisingTeam, CreateSupporter, UpdateSupporter, CreateDesignation, UpdateDesignation, UpdateTransaction, ListCampaignTransactions, ListCampaignFundraisingPages
], Field(discriminator="operation")]


class GoFundMeProConfig(NodeConfig[GoFundMeProOperation, GoFundMeProAccessTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Method/path pairs pinned to the provider OpenAPI 2.0.0 contract.
ROUTES = {
    "list_campaigns": ('GET', '/organizations/{organization}/campaigns'),
    "get_campaign": ('GET', '/campaigns/{campaign_id}'),
    "list_supporters": ('GET', '/organizations/{organization}/supporters'),
    "get_supporter": ('GET', '/supporters/{supporter_id}'),
    "list_transactions": ('GET', '/organizations/{organization}/transactions'),
    "get_transaction": ('GET', '/transactions/{transaction_id}'),
    "list_designations": ('GET', '/organizations/{organization}/designations'),
    "get_designation": ('GET', '/designations/{designation_id}'),
    "list_recurring_donation_plans": ('GET', '/organizations/{organization}/recurring-donation-plans'),
    "get_recurring_donation_plan": ('GET', '/recurring-donation-plans/{recurring_donation_plan_id}'),
    "list_fundraising_pages": ('GET', '/organizations/{organization}/fundraising-pages'),
    "get_fundraising_page": ('GET', '/fundraising-pages/{fundraising_page_id}'),
    "list_fundraising_teams": ('GET', '/organizations/{organization}/fundraising-teams'),
    "get_fundraising_team": ('GET', '/fundraising-teams/{fundraising_team_id}'),
    "create_supporter": ('POST', '/organizations/{organization}/supporters'),
    "update_supporter": ('PUT', '/supporters/{supporter_id}'),
    "create_designation": ('POST', '/organizations/{organization}/designations'),
    "update_designation": ('PUT', '/designations/{designation_id}'),
    "update_transaction": ('PUT', '/transactions/{transaction_id}'),
    "list_campaign_transactions": ('GET', '/campaigns/{campaign_id}/transactions'),
    "list_campaign_fundraising_pages": ('GET', '/campaigns/{campaign_id}/fundraising-pages'),
}


class GoFundMeProNode(WorkflowNode):
    integration_type = "automation-gofundme-pro"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return GoFundMeProConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GoFundMe Pro access token")
        op = self.config.config
        credential = self.config.credentials
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = path.replace("{organization}", str(credential.organization_id))
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        if method != "GET" and not values:
            raise ValueError("Supply at least one field to write")
        token = credential.access_token
        kwargs = {"params": values} if method == "GET" else {"json": values}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("GoFundMe Pro could not be reached; inspect write outcomes before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                message = payload.get("message") if isinstance(payload, dict) else None
            except ValueError:
                message = None
            message = message if isinstance(message, str) else "GoFundMe Pro request failed"
            result = {"status": "error", "http_status": response.status_code,
                "message": message[:2000].replace(token, "[redacted]")}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("GoFundMe Pro response exceeds the supported size")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("GoFundMe Pro returned an unexpected non-JSON response") from None
            if not isinstance(payload, dict) or "errors" in payload or payload.get("success") is False:
                raise ValueError("GoFundMe Pro returned an unexpected response")
            if op.operation.startswith("list_"):
                if not isinstance(payload.get("data"), list):
                    raise ValueError("GoFundMe Pro list response is missing its data array")
                result = {"status": "success", "operation": op.operation, "http_status": response.status_code,
                    "data": payload["data"], "pagination": {k: v for k, v in payload.items() if k != "data"}}
            else:
                result = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": payload}
        await self.emit(result)
        return result
