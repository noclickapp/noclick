"""Cakemail v1.30.2 operations and authenticated compliance webhooks.
Contract: https://api.cakemail.dev/openapi.json
Deliveries: https://cakemail.dev/en/guides/using-webhooks
"""
from __future__ import annotations
import hashlib
import json
import hmac
import re
from typing import Annotated, Literal, Union, Optional, Any
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.cakemail.dev"

class CakemailTokenCredential(BaseModel):
    model_config = ConfigDict(title="Cakemail Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.cakemail.dev/docs",
        "x-credential-instructions": "Paste a personal access token created with POST /users/self/pats. Grant the read/write scopes for the operations you use; triggers need webhooks:read and webhooks:write. Tokens are sent only to api.cakemail.dev."})
    credential_type: Literal["cakemail_token"] = Field("cakemail_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the Cakemail token without a Bearer header")
        return value

class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

class CakemailGetAccountConfig(OperationConfig):
    """Show my account details."""
    operation: Literal["get_account"] = Field("get_account", title='Show my account details', json_schema_extra={"ui:hidden": True})

class CakemailListListsConfig(OperationConfig):
    """Show all lists."""
    operation: Literal["list_lists"] = Field("list_lists", title='Show all lists', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)

class CakemailGetListConfig(OperationConfig):
    """Show a list parameters."""
    operation: Literal["get_list"] = Field("get_list", title='Show a list parameters', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')

class CakemailListContactsConfig(OperationConfig):
    """Show contacts of a list."""
    operation: Literal["list_contacts"] = Field("list_contacts", title='Show contacts of a list', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)

class CakemailCreateContactConfig(OperationConfig):
    """Add a contact."""
    operation: Literal["create_contact"] = Field("create_contact", title='Add a contact', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    resubscribe: bool = Field(False, description="Explicitly allow reactivating an unsubscribed contact")
    email: str = Field(..., min_length=1)

class CakemailGetContactConfig(OperationConfig):
    """Show a contact details."""
    operation: Literal["get_contact"] = Field("get_contact", title='Show a contact details', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    contact_id: int = Field(..., ge=1, title='Contact Id')

class CakemailUpdateContactConfig(OperationConfig):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", title='Update a contact', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    contact_id: int = Field(..., ge=1, title='Contact Id')
    email: str = Field(..., min_length=1)

class CakemailDeleteContactConfig(OperationConfig):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", title='Delete a contact', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    contact_id: int = Field(..., ge=1, title='Contact Id')

class CakemailUnsubscribeContactConfig(OperationConfig):
    """Unsubscribe a contact from a list."""
    operation: Literal["unsubscribe_contact"] = Field("unsubscribe_contact", title='Unsubscribe a contact from a list', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    contact_id: int = Field(..., ge=1, title='Contact Id')

class CakemailListCampaignsConfig(OperationConfig):
    """Show all campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", title='Show all campaigns', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)

class CakemailGetCampaignConfig(OperationConfig):
    """Show a campaign details."""
    operation: Literal["get_campaign"] = Field("get_campaign", title='Show a campaign details', json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., ge=1, title='Campaign Id')

class CakemailCreateCampaignConfig(OperationConfig):
    """Create a campaign."""
    operation: Literal["create_campaign"] = Field("create_campaign", title='Create a campaign', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)

class CakemailUpdateCampaignConfig(OperationConfig):
    """Update a campaign."""
    operation: Literal["update_campaign"] = Field("update_campaign", title='Update a campaign', json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., ge=1, title='Campaign Id')
    name: str = Field(..., min_length=1)

class CakemailCancelCampaignConfig(OperationConfig):
    """Cancel a campaign."""
    operation: Literal["cancel_campaign"] = Field("cancel_campaign", title='Cancel a campaign', json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., ge=1, title='Campaign Id')

class CakemailListTemplatesConfig(OperationConfig):
    """Show all templates."""
    operation: Literal["list_templates"] = Field("list_templates", title='Show all templates', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)

class CakemailGetTemplateConfig(OperationConfig):
    """Get a template."""
    operation: Literal["get_template"] = Field("get_template", title='Get a template', json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1, title='Template Id')

class CakemailListSendersConfig(OperationConfig):
    """Show all senders."""
    operation: Literal["list_senders"] = Field("list_senders", title='Show all senders', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)

class CakemailGetCampaignStatsConfig(OperationConfig):
    """Show campaign report."""
    operation: Literal["get_campaign_stats"] = Field("get_campaign_stats", title='Show campaign report', json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., ge=1, title='Campaign Id')

class CakemailListSegmentsConfig(OperationConfig):
    """Show all segments."""
    operation: Literal["list_segments"] = Field("list_segments", title='Show all segments', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title='List Id')
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)

class CakemailListSuppressedEmailsConfig(OperationConfig):
    """Show all suppressed emails."""
    operation: Literal["list_suppressed_emails"] = Field("list_suppressed_emails", title='Show all suppressed emails', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=100)


class CakemailOnComplianceConfig(WebhookTriggerConfigBase):
    operation: Literal["on_compliance_event"] = Field("on_compliance_event", title="On Compliance Event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    event_type: Literal["Email.Bounced", "Email.ReportedAsSpam", "Email.Unsubscribed", "Email.GlobalUnsubscribed", "Email.Rejected", "Email.Error", "Contact.Removed", "SuppressedEmail.Added"] = Field("Email.Bounced", title="Event")

OPERATIONS = {'get_account': ('GET', '/accounts/self', [], []), 'list_lists': ('GET', '/lists', ['page', 'per_page'], []), 'get_list': ('GET', '/lists/{list_id}', [], []), 'list_contacts': ('GET', '/lists/{list_id}/contacts', ['page', 'per_page'], []), 'create_contact': ('POST', '/lists/{list_id}/contacts', ['resubscribe'], ['email']), 'get_contact': ('GET', '/lists/{list_id}/contacts/{contact_id}', [], []), 'update_contact': ('PATCH', '/lists/{list_id}/contacts/{contact_id}', [], ['email']), 'delete_contact': ('DELETE', '/lists/{list_id}/contacts/{contact_id}', [], []), 'unsubscribe_contact': ('POST', '/lists/{list_id}/contacts/{contact_id}/unsubscribe', [], []), 'list_campaigns': ('GET', '/campaigns', ['page', 'per_page'], []), 'get_campaign': ('GET', '/campaigns/{campaign_id}', [], []), 'create_campaign': ('POST', '/campaigns', [], ['name']), 'update_campaign': ('PATCH', '/campaigns/{campaign_id}', [], ['name']), 'cancel_campaign': ('POST', '/campaigns/{campaign_id}/cancel', [], []), 'list_templates': ('GET', '/templates', ['page', 'per_page'], []), 'get_template': ('GET', '/templates/{template_id}', [], []), 'list_senders': ('GET', '/brands/default/senders', ['page', 'per_page'], []), 'get_campaign_stats': ('GET', '/reports/campaigns/{campaign_id}', [], []), 'list_segments': ('GET', '/lists/{list_id}/segments', ['page', 'per_page'], []), 'list_suppressed_emails': ('GET', '/suppressed-emails', ['page', 'per_page'], [])}

CakemailConfig = Annotated[Union[CakemailGetAccountConfig, CakemailListListsConfig, CakemailGetListConfig, CakemailListContactsConfig, CakemailCreateContactConfig, CakemailGetContactConfig, CakemailUpdateContactConfig, CakemailDeleteContactConfig, CakemailUnsubscribeContactConfig, CakemailListCampaignsConfig, CakemailGetCampaignConfig, CakemailCreateCampaignConfig, CakemailUpdateCampaignConfig, CakemailCancelCampaignConfig, CakemailListTemplatesConfig, CakemailGetTemplateConfig, CakemailListSendersConfig, CakemailGetCampaignStatsConfig, CakemailListSegmentsConfig, CakemailListSuppressedEmailsConfig, CakemailOnComplianceConfig], Field(discriminator="operation")]

class CakemailNodeConfig(NodeConfig[CakemailConfig, CakemailTokenCredential]):
    pass

class CakemailNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-cakemail"
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="account")

    @classmethod
    def get_config_model(cls):
        return CakemailNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if response.is_error:
            try:
                error = response.json()
                detail = error.get("detail", error) if isinstance(error, dict) else error
                text = json.dumps(detail, ensure_ascii=False)
            except ValueError:
                text = "Unexpected non-JSON response"
            text = text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"Cakemail API error {response.status_code}: {text}")
        if not response.content:
            return {}
        return response.json()

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = CakemailOnComplianceConfig.model_validate(config or {})
        token = CakemailTokenCredential.model_validate(credential).api_token
        created = await cls._request(token, "POST", "/webhooks", body={"event": op.event_type, "url": webhook_url})
        identifier = created.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Cakemail did not return a webhook ID")
        try:
            details = await cls._request(token, "GET", "/webhooks/" + quote(identifier, safe=""))
            signature = details.get("signature", {})
            if signature.get("hash_function") != "sha256" or not signature.get("key"):
                raise ValueError("Cakemail did not return a supported signing key")
        except Exception:
            await cls._request(token, "POST", "/webhooks/" + quote(identifier, safe="") + "/archive")
            raise
        return {"external_webhook_id": identifier, "signing_secret": signature["key"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier:
            token = CakemailTokenCredential.model_validate(credential).api_token
            await cls._request(token, "POST", "/webhooks/" + quote(str(identifier), safe="") + "/archive")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "Email.Bounced")}

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict, config: dict) -> bool:
        secret = (config or {}).get("signing_secret")
        received = next((v for k, v in headers.items() if k.lower() == "x-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(received, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected.encode(), received.encode())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event") == (config or {}).get("event_type", "Email.Bounced")

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output
        data = payload.get("data") or {}
        contact = (data["contact"] or {}) if "contact" in data else {}
        target = contact.get("email") or ((data["suppressedEmail"] or {}).get("email") if "suppressedEmail" in data else None) or ((data["email"] or {}).get("id") if "email" in data else None) or "recipient"
        return {"title": f"Cakemail {payload.get('event')}: {target}",
                "text": f"Cakemail account {payload.get('account_id')} reported {payload.get('event')} for {target}.\n" + json.dumps(payload, ensure_ascii=False)[:10000],
                "conversation_key": f"cakemail:{payload.get('account_id')}:{target}",
                "data": payload}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Cakemail personal access token")
        op = self.config.config
        if isinstance(op, CakemailOnComplianceConfig):
            if not inputs:
                return {"status": "no_event"}
            if inputs.get("event") != op.event_type:
                return {"status": "ignored"}
            return {"status": "success", **inputs}
        method, path, query, body_fields = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        result = await self._request(self.config.credentials.api_token, method, path,
            params={k: values[k] for k in query if k in values},
            body={k: values[k] for k in body_fields if k in values} if body_fields else None)
        output = {"status": "success", "operation": op.operation, "data": result}
        await self.emit(output)
        return output
