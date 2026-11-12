"""La Growth Machine workspace automation against the public v1 REST contract.

Each operation makes one API call; paginated reads expose skip/limit and preserve
provider totals. Messages are queued replies, and do not claim delivery.
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://apiv2.lagrowthmachine.com/flow"
ObjectId = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{24}$")]
Text = Annotated[str, Field(min_length=1)]


class LagrowthmachineAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="La Growth Machine API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.lagrowthmachine.com/settings/api",
            "x-credential-instructions": "Copy your API key from La Growth Machine Settings → Integrations & API, then paste it here. Your plan must include API access. The key acts as the workspace owner; NoClick sends it in the Authorization Bearer header.",
        })
    credential_type: Literal["lagrowthmachine_api_key"] = Field("lagrowthmachine_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a Bearer prefix")
        return value


class Operation(BaseModel):
    """Only documented operation fields are serialized into API requests."""


class GetMe(Operation):
    operation: Literal["get_me"] = "get_me"


class ListWorkspaces(Operation):
    operation: Literal["list_workspaces"] = "list_workspaces"


class ListMembers(Operation):
    operation: Literal["list_members"] = "list_members"


class ListIdentities(Operation):
    operation: Literal["list_identities"] = "list_identities"


class GetCredits(Operation):
    operation: Literal["get_credits"] = "get_credits"


class ListAudiences(Operation):
    operation: Literal["list_audiences"] = "list_audiences"


class CreateAudience(Operation):
    operation: Literal["create_audience"] = "create_audience"
    name: str = Field(..., min_length=1, max_length=100, description="Unique audience name in this workspace.")


class GetAudience(Operation):
    operation: Literal["get_audience"] = "get_audience"
    audience_id: ObjectId


class Page(Operation):
    skip: int = Field(0, ge=0, description="Number of records to skip. Increase by limit for the next page.")
    limit: int = Field(25, ge=1, le=100)


class ListAudienceLeads(Page):
    operation: Literal["list_audience_leads"] = "list_audience_leads"
    audience_id: ObjectId


class UpsertLead(Operation):
    operation: Literal["upsert_lead"] = "upsert_lead"
    audience: Optional[str] = Field(None, max_length=255, description="Audience name or ID. A missing named audience is created.")
    leadId: Optional[ObjectId] = Field(None, title="Lead ID")
    firstname: Optional[str] = Field(None, max_length=255, title="First name")
    lastname: Optional[str] = Field(None, max_length=255, title="Last name")
    proEmail: Optional[EmailStr] = Field(None, max_length=255, title="Work email")
    persoEmail: Optional[EmailStr] = Field(None, max_length=255, title="Personal email")
    linkedinUrl: Optional[Text] = Field(None, title="LinkedIn URL")
    twitter: Optional[Text] = Field(None, max_length=255)
    crm_id: Optional[Text] = Field(None, max_length=255, title="CRM ID")
    companyName: Optional[str] = Field(None, max_length=255, title="Company name")
    companyUrl: Optional[str] = Field(None, title="Company URL")
    jobTitle: Optional[str] = Field(None, max_length=255, title="Job title")
    phone: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=255)
    note: Optional[str] = Field(None, max_length=1500, description="Replaces the existing lead note.")
    bio: Optional[str] = Field(None, max_length=5000)

    @model_validator(mode="after")
    def require_identity(self):
        if not (self.leadId or self.proEmail or self.persoEmail or self.linkedinUrl or self.twitter or self.crm_id or (self.firstname and self.lastname and (self.companyName or self.companyUrl))):
            raise ValueError("Identify the lead with an ID, email, social URL, CRM ID, or first and last name plus company")
        return self


class SearchLead(Operation):
    operation: Literal["search_lead"] = "search_lead"
    leadId: Optional[ObjectId] = Field(None, title="Lead ID")
    email: Optional[EmailStr] = None
    crmId: Optional[Text] = Field(None, max_length=50, title="CRM ID")
    linkedinUrl: Optional[Text] = Field(None, title="LinkedIn URL")
    firstname: Optional[Text] = Field(None, title="First name")
    lastname: Optional[Text] = Field(None, title="Last name")
    companyName: Optional[Text] = Field(None, title="Company name")
    companyUrl: Optional[Text] = Field(None, title="Company URL")

    @model_validator(mode="after")
    def require_criterion(self):
        if not (self.leadId or self.email or self.crmId or self.linkedinUrl or (self.firstname and self.lastname and (self.companyName or self.companyUrl))):
            raise ValueError("Supply a lead search criterion or a full name and company")
        return self


class UpdateLeadStatus(Operation):
    operation: Literal["update_lead_status"] = "update_lead_status"
    leadId: ObjectId = Field(..., title="Lead ID")
    campaign: Text = Field(..., description="Campaign name or ID, or all for every non-stopped campaign containing this lead.")
    status: Literal["RESUME", "PAUSED", "STOPPED", "CONVERTED", "SUBSCRIBED", "COMPLETED_NO_REPLY", "REPLIED", "CANNOT_CONTACT", "NOT_ACTIVATED", "SKIPPED", "ACTIVATED", "ENRICHED", "CONTACTED", "COMPLETED_WITHOUT_REPLY", "TO_QUALIFY", "UNSUBSCRIBED", "OUT_OF_OFFICE", "WRONG_TIMING", "INTERESTED", "NOT_INTERESTED", "CALL_BOOKED", "NEGOTIATING", "READY_TO_BUY", "WRONG_TARGET", "ALREADY_EQUIPPED"]


class ListLeadLogs(Page):
    operation: Literal["list_lead_logs"] = "list_lead_logs"
    lead_id: ObjectId
    identityId: Optional[ObjectId] = Field(None, title="Identity ID")


class ListLeadConversations(Operation):
    operation: Literal["list_lead_conversations"] = "list_lead_conversations"
    lead_id: ObjectId
    identityId: Optional[ObjectId] = Field(None, title="Identity ID")


class ListCampaigns(Page):
    operation: Literal["list_campaigns"] = "list_campaigns"
    limit: int = Field(25, ge=1, le=25)
    status: Optional[Text] = Field(None, description="Comma-separated RUNNING, READY, PAUSED, CANCELED statuses.")
    search: Optional[Text] = None


class GetCampaign(Operation):
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: ObjectId


class GetCampaignStats(Operation):
    operation: Literal["get_campaign_stats"] = "get_campaign_stats"
    campaign_id: ObjectId


class UpdateCampaignStatus(Operation):
    operation: Literal["update_campaign_status"] = "update_campaign_status"
    campaign_id: ObjectId
    status: Literal["PAUSED", "RUNNING"] = Field(..., description="Pause a running campaign or resume a paused campaign.")


class SendLinkedinMessage(Operation):
    operation: Literal["send_linkedin_message"] = "send_linkedin_message"
    identityId: ObjectId = Field(..., title="LinkedIn identity ID")
    memberId: ObjectId = Field(..., title="Member ID")
    leadId: ObjectId = Field(..., title="Lead ID", description="An existing conversation with this sending identity is required.")
    message: Text = Field(..., description="Text to queue for sending. Success does not prove delivery.")


class ReplyEmail(Operation):
    operation: Literal["reply_email"] = "reply_email"
    identityId: ObjectId = Field(..., title="Email identity ID")
    leadId: ObjectId = Field(..., title="Lead ID", description="Replies to this lead's most recent existing email thread.")
    html: Text = Field(..., title="HTML body")
    text: Text = Field(..., title="Plain text body")


# La Growth Machine's own MCP server: agents get its tools through a person's La Growth Machine sign-in.
LagrowthmachineMcpCredential = mcp_credential("lagrowthmachine", "https://mcp.lagrowthmachine.com/mcp", app="La Growth Machine")
LagrowthmachineCredential = Union[LagrowthmachineAPIKeyCredential, LagrowthmachineMcpCredential]


LagrowthmachineConfig = Annotated[Union[
    GetMe, ListWorkspaces, ListMembers, ListIdentities, GetCredits,
    ListAudiences, CreateAudience, GetAudience, ListAudienceLeads,
    UpsertLead, SearchLead, UpdateLeadStatus, ListLeadLogs, ListLeadConversations,
    ListCampaigns, GetCampaign, GetCampaignStats, UpdateCampaignStatus,
    SendLinkedinMessage, ReplyEmail,
], Field(discriminator="operation")]


class LagrowthmachineFullConfig(NodeConfig[LagrowthmachineConfig, LagrowthmachineCredential]):
    pass


# Each entry is one operation in https://developers.lagrowthmachine.com/openapi.yaml.
# The response key/type is deliberately shallow: provider fields are preserved.
ROUTES = {
    "get_me": ("GET", "/me", "id", str),
    "list_workspaces": ("GET", "/workspaces", "workspaces", list),
    "list_members": ("GET", "/members", "members", list),
    "list_identities": ("GET", "/identities", "identities", list),
    "get_credits": ("GET", "/credits", "credits", dict),
    "list_audiences": ("GET", "/audiences", "audiences", list),
    "create_audience": ("POST", "/audiences/create", "audience", dict),
    "get_audience": ("GET", "/audiences/{audience_id}/detail", "data", dict),
    "list_audience_leads": ("GET", "/audiences/{audience_id}/leads", "data", list),
    "upsert_lead": ("POST", "/leads", "leadId", str),
    "search_lead": ("GET", "/leads/search", "lead", dict),
    "update_lead_status": ("POST", "/leads/status", "logs", list),
    "list_lead_logs": ("GET", "/leads/{lead_id}/logs", "data", list),
    "list_lead_conversations": ("GET", "/leads/{lead_id}/conversations", "data", list),
    "list_campaigns": ("GET", "/campaigns", "campaigns", list),
    "get_campaign": ("GET", "/campaigns/{campaign_id}", "campaign", dict),
    "get_campaign_stats": ("GET", "/campaigns/{campaign_id}/stats", "engagementStats", dict),
    "update_campaign_status": ("POST", "/campaigns/{campaign_id}/status", "data", dict),
    "send_linkedin_message": ("POST", "/inbox/linkedin", "lead", dict),
    "reply_email": ("POST", "/inbox/email", "lead", dict),
}


class LagrowthmachineNode(WorkflowNode):
    integration_type = "automation-lagrowthmachine"
    credential_provider_labels = {"lagrowthmachine": "La Growth Machine Account"}
    connection_evidence = ConnectionEvidence(noun="audiences", operation="list_audiences", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return LagrowthmachineFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a La Growth Machine API key")
        op = self.config.config
        method, path, response_key, response_type = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("audience_id", "lead_id", "campaign_id"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        if op.operation == "reply_email":
            values = {"identityId": op.identityId, "leadId": op.leadId,
                      "message": {"html": op.html, "text": op.text}, "replyInLastThread": True}
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"}
        kwargs = {"params": values} if method == "GET" else {"json": values}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        # Preserve provider rejection text for connect, removing a reflected key.
        # Writes are never automatically retried.
        if not response.is_success:
            detail = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"La Growth Machine HTTP {response.status_code}: {detail}")
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Expected a JSON response from La Growth Machine")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("La Growth Machine returned an invalid response envelope")
        if payload.get("error") or payload.get("errors") or (isinstance(payload.get("statusCode"), int) and payload["statusCode"] >= 400):
            detail = str(payload)[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(detail)
        if not isinstance(payload.get(response_key), response_type):
            raise ValueError(f"La Growth Machine response is missing {response_key}")
        return {"status": "success", "data": payload}
