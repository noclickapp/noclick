"""Givebutter v1 donor CRM and fundraising operations.

Each operation makes one request to the published API contract. List operations
return the first page and its pagination metadata; links are never followed.
"""
from __future__ import annotations

import hmac
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
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
ResourceID = Annotated[str, Field(min_length=1, max_length=255)] | ID
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
    transaction_id: ResourceID


class ListPlans(_Input):
    """List the first page of recurring donation plans."""
    operation: Literal["list_plans"] = "list_plans"


class GetPlan(_Input):
    """Read one recurring donation plan."""
    operation: Literal["get_plan"] = "get_plan"
    plan_id: ResourceID


# Event names and registration: https://givebutter.com/docs/api.json.
# Payloads and static Signature header: https://help.givebutter.com/en/articles/8828428-how-to-automate-workflows-and-data-using-webhooks.
WEBHOOK_EVENTS = (
    "campaign.created", "campaign.updated", "ticket.created", "transaction.succeeded",
    "contact.created", "plan.canceled", "plan.created", "plan.failed", "plan.paused",
    "plan.resumed", "plan.updated", "refund.created",
)


class OnEvent(WebhookTriggerConfigBase):
    """Start a workflow or agent when the selected Givebutter event arrives."""
    operation: Literal["on_event"] = Field("on_event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Givebutter Event",
    })
    event_type: Literal[*WEBHOOK_EVENTS] = Field("transaction.succeeded", title="Event Type",
        description="Start on a donation, new contact, campaign, ticket, recurring plan or refund event. Donation and contact events do not fire for CSV imports.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Givebutter automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


GivebutterOperation = Annotated[Union[
    ListCampaigns, GetCampaign, CreateCampaign, UpdateCampaign,
    ListContacts, GetContact, CreateContact, UpdateContact, RestoreContact,
    AddContactTags, RemoveContactTags, ListContactActivities, CreateContactActivity,
    ListFunds, GetFund, CreateFund, UpdateFund, ListTransactions, GetTransaction,
    ListPlans, GetPlan, OnEvent,
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


class GivebutterNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-givebutter"
    webhook_replace_stale_endpoint = True
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return GivebutterConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event_type = (config or {}).get("event_type", "transaction.succeeded")
        if event_type not in WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Givebutter event")
        payload = await cls._webhook_request("POST", "/v1/webhooks", credential,
            body={"url": webhook_url, "events": [event_type], "name": f"NoClick {node_id}"[:255], "enabled": True})
        endpoint_id, secret = payload.get("id"), payload.get("signature")
        if not isinstance(endpoint_id, str) or not endpoint_id or not isinstance(secret, str) or not secret:
            raise ValueError("Givebutter did not return a webhook ID and signature")
        return {"external_webhook_id": endpoint_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id is not None:
            await cls._webhook_request("DELETE", "/v1/webhooks/" + quote(str(endpoint_id), safe=""), credential)

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "transaction.succeeded")}

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # Givebutter sends the signature verbatim; it does not sign the body.
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "signature"), None)
        return (isinstance(secret, str) and bool(secret) and isinstance(signature, str)
                and hmac.compare_digest(secret.encode(), signature.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (isinstance(payload, dict)
                and payload.get("event") == (config or {}).get("event_type", "transaction.succeeded")
                and isinstance(payload.get("data"), dict) and payload["data"].get("id") is not None)

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") not in WEBHOOK_EVENTS:
            return super().resolve_agent_event(output)
        event = output["event"]
        data = output.get("data")
        if not isinstance(data, dict) or data.get("id") is None:
            return None
        kind = event.split(".")[0]
        identifier = data["id"]
        if kind in {"contact", "transaction", "plan", "ticket"}:
            who = " ".join(str(data.get(k) or "") for k in ("first_name", "last_name")).strip()
        else:
            who = ""
        title = f"Givebutter {event}: {who or identifier}"
        lines = [title, f"{kind}_id: {identifier}"]
        if kind == "campaign":
            lines += [f"Campaign: {data['title']}", f"URL: {data['url']}",
                      f"Raised: {data['raised']} {data['currency']}; goal: {data['goal']}"]
            if data.get("description"):
                lines.append(f"Description: {str(data['description'])[:1500]}")
        elif kind == "contact":
            for key in ("primary_email", "primary_phone", "note"):
                if data.get(key):
                    lines.append(f"{key}: {str(data[key])[:1500]}")
            lines.append(f"To act: get_contact or update_contact with contact_id={identifier}.")
        elif kind == "transaction":
            lines += [f"Donation: {data['amount']} {data['currency']}",
                      f"Campaign: {data['campaign_code']} (campaign_id={data['campaign_id']})",
                      f"Donor email: {data['email']}", f"At: {data['transacted_at']}"]
            giving = data.get("giving_space")
            if isinstance(giving, dict) and giving.get("message"):
                lines.append(f"Message: {str(giving['message'])[:1500]}")
            lines.append(f"To act: get_transaction with transaction_id={identifier}.")
        elif kind == "plan":
            lines += [f"Recurring amount: {data['amount']}; frequency: {data['frequency']}",
                      f"Donor email: {data['email']}", f"Next bill: {data['next_bill_date']}",
                      f"To act: get_plan with plan_id={identifier}."]
        elif kind == "ticket":
            lines += [f"Ticket: {data['title']}", f"Email: {data['email']}",
                      f"transaction_id: {data['transaction_id']}", f"PDF: {data['pdf']}"]
        elif kind == "refund":
            lines += [f"Refund amount: {data['amount']}; type: {data['type']}",
                      f"Reason: {str(data['reason'])[:1500]}", f"transaction_id: {data['transaction_id']}"]
        return {"text": "\n".join(lines), "conversation_key": f"{kind}:{identifier}", "title": title}

    @staticmethod
    async def _request(method, path, key, *, params=None, body=None):
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Givebutter could not be reached; inspect write outcomes before retrying") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Givebutter response exceeds the supported size")
        return response

    @classmethod
    async def _webhook_request(cls, method, path, credential, *, body=None):
        key = GivebutterAPIKeyCredential.model_validate(credential or {}).api_key
        response = await cls._request(method, path, key, body=body)
        if method == "DELETE" and (response.status_code == 404 or 200 <= response.status_code < 300):
            return {}
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Givebutter webhook request failed (HTTP {response.status_code})")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Givebutter returned an unexpected non-JSON response") from None
        if not isinstance(payload, dict):
            raise ValueError("Givebutter returned an unexpected webhook response")
        return payload

    async def execute(self, inputs):
        if self.config and isinstance(self.config.config, OnEvent):
            return self.no_event_output("on_event")
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Givebutter API key")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        if config.operation in {"update_contact", "update_campaign"} and not values:
            raise ValueError("Supply at least one field to update")
        key = self.config.credentials.api_key
        response = await self._request(method, path, key,
            params=values if method == "GET" else None,
            body=values if method != "GET" and values else None)
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
