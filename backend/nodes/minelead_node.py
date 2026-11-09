"""Minelead's published v1 API: prospect research and saved lead lists.

Contract: https://minelead.io/media/api_docs/api_docs.yml (version 1.0).
Each operation makes one request; paid research is never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.minelead.io/v1"


class MineleadAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Minelead API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://minelead.io/docs/",
        "x-credential-instructions": "Copy your API key from your Minelead account. Research operations consume your Minelead credits.",
    })
    credential_type: Literal["minelead_api_key"] = Field("minelead_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False,
                         description="Paste your Minelead API key.", json_schema_extra={"ui:widget": "password"})


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class SearchEmails(_Operation):
    operation: Literal["search_emails"] = Field("search_emails", title="Search Company Emails")
    domain: str = Field(..., min_length=1, description="Company domain, for example example.com.")
    name: str | None = Field(None, title="Company Name")
    max_emails: int | None = Field(None, ge=1, title="Maximum Emails")
    generic: bool | None = Field(None, description="Return only generic addresses.")
    light_mode: bool | None = Field(None, description="Return only previously found emails.")
    enrich: bool | None = Field(None, description="Include professional profile data; consumes credits.")
    deep: bool | None = Field(None, description="Discover employee emails with AI; costs 5 credits plus 2 per verified email.")
    max_deep_results: int | None = Field(None, ge=1, title="Maximum Deep Search Results")


class EnrichEmail(_Operation):
    operation: Literal["enrich_email"] = Field("enrich_email", title="Enrich Email")
    email: str = Field(..., min_length=1)
    name: str | None = Field(None, title="Full Name")
    company: str | None = Field(None, title="Company Name or Domain")


class GetBuyingIntent(_Operation):
    operation: Literal["get_buying_intent"] = Field("get_buying_intent", title="Get Buying Intent")
    company: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    refresh: Literal["true"] | None = Field(None, description="Skip the seven-day cache; a fresh analysis costs credits.")
    level: Literal[1, 2] | None = Field(None, description="1: news only; 2: website/LinkedIn only. Omit for both.")


class ValidateEmail(_Operation):
    operation: Literal["validate_email"] = Field("validate_email", title="Verify Email")
    email: str = Field(..., min_length=1)
    firstname: str | None = Field(None, title="First Name")
    lastname: str | None = Field(None, title="Last Name")


class DetectDisposable(_Operation):
    operation: Literal["detect_disposable"] = Field("detect_disposable", title="Detect Disposable Email")
    email: str = Field(..., min_length=1)


class FindEmail(_Operation):
    operation: Literal["find_email"] = Field("find_email", title="Find Person's Email")
    domain: str = Field(..., min_length=1)
    firstname: str = Field(..., min_length=1, title="First Name")
    lastname: str = Field(..., min_length=1, title="Last Name")


class FindSocialEmails(_Operation):
    operation: Literal["find_social_emails"] = Field("find_social_emails", title="Find Social Profile Emails")
    url: str = Field(..., min_length=1, title="Profile URL", description="YouTube channel or Twitter/X profile URL.")


class GenerateLeads(_Operation):
    operation: Literal["generate_leads"] = Field("generate_leads", title="Generate Leads from Tags")
    tags: list[str] = Field(..., min_length=1, title="Tags", description="Location and industry tags, for example new york and hotel.")


class ListLeads(_Operation):
    operation: Literal["list_leads"] = Field("list_leads", title="List Saved Leads")


class LeadInput(BaseModel):
    email: str = Field(..., min_length=1)


class AddLeads(_Operation):
    operation: Literal["add_leads"] = Field("add_leads", title="Add Saved Leads")
    leads: list[LeadInput] = Field(..., min_length=1, description="Email records to add to your Minelead leads.")


class DeleteLeads(_Operation):
    operation: Literal["delete_leads"] = Field("delete_leads", title="Delete Saved Leads")
    email: list[str] = Field(..., min_length=1, title="Emails", description="Emails to remove from saved leads; does not delete contacts elsewhere.")


class ListHistory(_Operation):
    operation: Literal["list_history"] = Field("list_history", title="List Search History")
    start: int = Field(0, ge=0, title="Start Offset")
    limit: int = Field(7, ge=1, title="Page Size", description="One page is returned. Increase start to retrieve the next page.")


class ListCampaigns(_Operation):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Campaigns")


class ListRecipients(_Operation):
    operation: Literal["list_recipients"] = Field("list_recipients", title="List Recipient Lists")


class CreateRecipients(_Operation):
    operation: Literal["create_recipients"] = Field("create_recipients", title="Create Recipient List")
    list_name: str = Field(..., min_length=1, title="List Name")
    emails: list[str] = Field(..., min_length=1)


class EditRecipients(_Operation):
    operation: Literal["edit_recipients"] = Field("edit_recipients", title="Edit Recipient List")
    id: int = Field(..., ge=1, title="Recipient List ID")
    action: Literal["add", "remove"] = Field(..., title="Action", description="Add or remove the specified emails from this list.")
    emails: list[str] = Field(..., min_length=1)


class GetAccount(_Operation):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", description="Read the account identity and subscription; the returned API key is omitted.")


MineleadOperation = Annotated[Union[
    SearchEmails, EnrichEmail, GetBuyingIntent, ValidateEmail, DetectDisposable,
    FindEmail, FindSocialEmails, GenerateLeads, ListLeads, AddLeads, DeleteLeads,
    ListHistory, ListCampaigns, ListRecipients, CreateRecipients, EditRecipients, GetAccount,
], Field(discriminator="operation")]


class MineleadConfig(NodeConfig[MineleadOperation, MineleadAPIKeyCredential]):
    pass


# One public API operation for each workflow operation. /account is a read even
# though the provider specifies POST (its key is also sent in the JSON body).
ROUTES = {
    "search_emails": ("GET", "/search"),
    "enrich_email": ("GET", "/enrich"),
    "get_buying_intent": ("GET", "/buying-intent"),
    "validate_email": ("GET", "/validate"),
    "detect_disposable": ("GET", "/detect-disposable"),
    "find_email": ("GET", "/find"),
    "find_social_emails": ("GET", "/social-email-finder"),
    "generate_leads": ("POST", "/tags"),
    "list_leads": ("GET", "/leads"),
    "add_leads": ("POST", "/leads"),
    "delete_leads": ("DELETE", "/leads"),
    "list_history": ("GET", "/history"),
    "list_campaigns": ("GET", "/campaigns"),
    "list_recipients": ("GET", "/campaigns-recipients"),
    "create_recipients": ("POST", "/campaigns-recipients"),
    "edit_recipients": ("PUT", "/campaigns-recipients"),
    "get_account": ("POST", "/account"),
}


def _redact(value, key):
    """Account replies echo api_key. Never expose it or a provider-echoed key."""
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k.lower() not in {"api_key", "key", "api-key", "apikey"}}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    return value


class MineleadNode(WorkflowNode):
    integration_type = "automation-minelead"
    connection_evidence = ConnectionEvidence(noun="Minelead account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return MineleadConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Minelead API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        params = {"key": key}
        body = None
        if method == "GET":
            aliases = {"max_emails": "max-emails", "light_mode": "light-mode"}
            params.update({aliases.get(k, k): (str(v).lower() if isinstance(v, bool) else v) for k, v in values.items()})
        else:
            body = {"key": key} if op.operation == "get_account" else values
            if op.operation == "edit_recipients":
                body["operation"] = body.pop("action")
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                                                **({"json": body} if body is not None else {}),
                                                headers={"Accept": "application/json"})
            if not 200 <= response.status_code < 300:
                # HTTP exception text contains query-string credentials. Use only
                # provider JSON text, redacted, never a URL or transport exception.
                message = "Minelead request failed"
                try:
                    failure = response.json()
                    if isinstance(failure, dict) and isinstance(failure.get("message"), str):
                        message = failure["message"][:2000]
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code, "error": _redact(message, key)}
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if data.get("status") in {"error", "failed", "failure"} or data.get("error"):
                return {"status": "error", "error": _redact(str(data.get("message") or data.get("error") or "Minelead rejected the request"), key)}
            data = _redact(data, key)
            if op.operation == "get_account":
                account = data.get("data")
                if not isinstance(account, dict) or not (account.get("email") or account.get("username")):
                    raise ValueError("Account identity is missing")
            return {"status": "success", "data": data}
        except httpx.HTTPError:
            return {"status": "error", "error": "Minelead request could not be completed; inspect the account before retrying a write or paid search"}
        except ValueError:
            return {"status": "error", "error": "Minelead returned an invalid JSON response"}
