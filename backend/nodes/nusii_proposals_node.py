"""Nusii API v2 proposals and their supporting resources.

Contract: https://app.nusii.com/api/v2/openapi.yaml (2.0).
Narrative: https://developer.nusii.com/. One request per operation, no write retries.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.nusii.com/api/v2"


class NusiiProposalsAPIKey(BaseModel):
    model_config = ConfigDict(title="Nusii Proposals API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.nusii.com/settings/api",
            "x-credential-instructions": "Copy your personal API key from Nusii Settings → API. Paste the key alone. NoClick sends it only to app.nusii.com and checks your account before saving. The key can read and modify proposals and clients with your account's permissions.",
        })
    credential_type: Literal["nusii_proposals_api_key"] = Field("nusii_proposals_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Nusii API key")
        value = clean_secret(value, field_name="API key", key=True)
        if not value or any(c.isspace() for c in value) or any(c in value for c in '\"'):
            raise ValueError("Paste the API key alone, without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[int, Field(gt=0, le=9223372036854775807, description="Numeric Nusii resource ID.")]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number; follow next_page in the returned meta. One page is returned per run.")


class GetAccountConfig(_Input):
    """Get account in Nusii."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class ListClientsConfig(_Page):
    """List clients in Nusii."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    email: str | None = None
    query: str | None = None


class GetClientConfig(_Input):
    """Get client in Nusii."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: ResourceID


class CreateClientConfig(_Input):
    """Create client in Nusii."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    name: Text
    email: Text
    web: str | None = None


class UpdateClientConfig(_Input):
    """Update client in Nusii."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    client_id: ResourceID
    name: Text
    email: str | None = None


class DeleteClientConfig(_Input):
    """Delete client in Nusii."""
    operation: Literal["delete_client"] = Field("delete_client", json_schema_extra={"ui:hidden": True})
    client_id: ResourceID


class ListProposalsConfig(_Page):
    """List proposals in Nusii."""
    operation: Literal["list_proposals"] = Field("list_proposals", json_schema_extra={"ui:hidden": True})
    per: int = Field(25, ge=1, le=100)
    status: Literal["draft", "pending", "accepted", "rejected", "clarification"] | None = None
    recipient_emails: str | None = None
    expires_at_after: str | None = None


class GetProposalConfig(_Input):
    """Get proposal in Nusii."""
    operation: Literal["get_proposal"] = Field("get_proposal", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID


class CreateProposalConfig(_Input):
    """Create proposal in Nusii."""
    operation: Literal["create_proposal"] = Field("create_proposal", json_schema_extra={"ui:hidden": True})
    title: Text
    client_id: ResourceID | None = None
    template_id: ResourceID | None = None
    prepared_by_id: ResourceID | None = None


class UpdateProposalConfig(_Input):
    """Update proposal in Nusii."""
    operation: Literal["update_proposal"] = Field("update_proposal", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID
    title: Text
    status: Literal["draft", "pending", "accepted", "rejected", "clarification"] | None = None


class DeleteProposalConfig(_Input):
    """Delete proposal in Nusii."""
    operation: Literal["delete_proposal"] = Field("delete_proposal", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID


class ArchiveProposalConfig(_Input):
    """Archive proposal in Nusii."""
    operation: Literal["archive_proposal"] = Field("archive_proposal", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID


class SendProposalConfig(_Input):
    """Send proposal in Nusii."""
    operation: Literal["send_proposal"] = Field("send_proposal", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID
    email: Text = Field(..., description="Recipient email. This operation sends the proposal immediately.")
    subject: Text
    message: str | None = Field(None, max_length=50000)
    sender_email: str | None = None


class ListTemplatesConfig(_Page):
    """List templates in Nusii."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    public_templates: bool | None = None


class GetTemplateConfig(_Input):
    """Get template in Nusii."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: ResourceID


class ListSectionsConfig(_Page):
    """List sections in Nusii."""
    operation: Literal["list_sections"] = Field("list_sections", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID | None = None
    template_id: ResourceID | None = None


class GetSectionConfig(_Input):
    """Get section in Nusii."""
    operation: Literal["get_section"] = Field("get_section", json_schema_extra={"ui:hidden": True})
    section_id: ResourceID


class CreateSectionConfig(_Input):
    """Create section in Nusii."""
    operation: Literal["create_section"] = Field("create_section", json_schema_extra={"ui:hidden": True})
    title: Text
    proposal_id: ResourceID | None = None
    template_id: ResourceID | None = None
    name: str | None = None
    body: str | None = Field(None, max_length=100000)
    section_type: Literal["text", "cost"] = "text"


class UpdateSectionConfig(_Input):
    """Update section in Nusii."""
    operation: Literal["update_section"] = Field("update_section", json_schema_extra={"ui:hidden": True})
    section_id: ResourceID
    title: Text
    body: str | None = Field(None, max_length=100000)


class DeleteSectionConfig(_Input):
    """Delete section in Nusii."""
    operation: Literal["delete_section"] = Field("delete_section", json_schema_extra={"ui:hidden": True})
    section_id: ResourceID


class ListLineItemsConfig(_Page):
    """List line items in Nusii."""
    operation: Literal["list_line_items"] = Field("list_line_items", json_schema_extra={"ui:hidden": True})
    section_id: ResourceID


class CreateLineItemConfig(_Input):
    """Create line item in Nusii."""
    operation: Literal["create_line_item"] = Field("create_line_item", json_schema_extra={"ui:hidden": True})
    section_id: ResourceID
    name: Text
    amount: int | None = Field(None, ge=0, description="Price in cents.")
    maximum_amount: int | None = Field(None, ge=0, description="High end of a price range in cents.")
    cost_type: Literal["fixed", "range"] = "fixed"


class UpdateLineItemConfig(_Input):
    """Update line item in Nusii."""
    operation: Literal["update_line_item"] = Field("update_line_item", json_schema_extra={"ui:hidden": True})
    line_item_id: ResourceID
    name: str | None = None
    amount: int | None = Field(None, ge=0, description="Price in cents.")
    maximum_amount: int | None = Field(None, ge=0)
    cost_type: Literal["fixed", "range"] | None = None
    choice_type: Literal["none", "checkbox", "radio"] | None = None


class DeleteLineItemConfig(_Input):
    """Delete line item in Nusii."""
    operation: Literal["delete_line_item"] = Field("delete_line_item", json_schema_extra={"ui:hidden": True})
    line_item_id: ResourceID


class ListProposalActivitiesConfig(_Page):
    """List proposal activities in Nusii."""
    operation: Literal["list_proposal_activities"] = Field("list_proposal_activities", json_schema_extra={"ui:hidden": True})
    proposal_id: ResourceID | None = None
    client_id: ResourceID | None = None


NusiiConfig = Annotated[Union[
    GetAccountConfig,
    ListClientsConfig,
    GetClientConfig,
    CreateClientConfig,
    UpdateClientConfig,
    DeleteClientConfig,
    ListProposalsConfig,
    GetProposalConfig,
    CreateProposalConfig,
    UpdateProposalConfig,
    DeleteProposalConfig,
    ArchiveProposalConfig,
    SendProposalConfig,
    ListTemplatesConfig,
    GetTemplateConfig,
    ListSectionsConfig,
    GetSectionConfig,
    CreateSectionConfig,
    UpdateSectionConfig,
    DeleteSectionConfig,
    ListLineItemsConfig,
    CreateLineItemConfig,
    UpdateLineItemConfig,
    DeleteLineItemConfig,
    ListProposalActivitiesConfig
], Field(discriminator="operation")]


class NusiiProposalsConfig(NodeConfig[NusiiConfig, NusiiProposalsAPIKey]):
    pass


ROUTES = {'get_account': ('GET', '/account/me', None, []),
 'list_clients': ('GET', '/clients', None, ['page', 'email', 'query']),
 'get_client': ('GET', '/clients/{client_id}', None, []),
 'create_client': ('POST', '/clients', 'client', []),
 'update_client': ('PUT', '/clients/{client_id}', 'client', []),
 'delete_client': ('DELETE', '/clients/{client_id}', None, []),
 'list_proposals': ('GET',
                    '/proposals',
                    None,
                    ['page', 'per', 'status', 'recipient_emails', 'expires_at_after']),
 'get_proposal': ('GET', '/proposals/{proposal_id}', None, []),
 'create_proposal': ('POST', '/proposals', 'proposal', []),
 'update_proposal': ('PUT', '/proposals/{proposal_id}', 'proposal', []),
 'delete_proposal': ('DELETE', '/proposals/{proposal_id}', None, []),
 'archive_proposal': ('PUT', '/proposals/{proposal_id}/archive', '', []),
 'send_proposal': ('PUT', '/proposals/{proposal_id}/send_proposal', '', []),
 'list_templates': ('GET', '/templates', None, ['page', 'public_templates']),
 'get_template': ('GET', '/templates/{template_id}', None, []),
 'list_sections': ('GET', '/sections', None, ['page', 'proposal_id', 'template_id']),
 'get_section': ('GET', '/sections/{section_id}', None, []),
 'create_section': ('POST', '/sections', 'section', []),
 'update_section': ('PUT', '/sections/{section_id}', 'section', []),
 'delete_section': ('DELETE', '/sections/{section_id}', None, []),
 'list_line_items': ('GET', '/sections/{section_id}/line_items', None, ['page']),
 'create_line_item': ('POST', '/sections/{section_id}/line_items', 'line_item', []),
 'update_line_item': ('PUT', '/line_items/{line_item_id}', 'line_item', []),
 'delete_line_item': ('DELETE', '/line_items/{line_item_id}', None, []),
 'list_proposal_activities': ('GET', '/proposal_activities', None, ['page', 'proposal_id', 'client_id'])}


class _ProviderError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class NusiiProposalsNode(WorkflowNode):
    integration_type = "automation-nusii-proposals"
    connection_evidence = ConnectionEvidence(noun="clients", operation="list_clients", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return NusiiProposalsConfig

    @classmethod
    async def _request(cls, credential, operation):
        method, route, envelope, query_fields = ROUTES[operation.operation]
        values = operation.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"{(\w+)}", route)
        path = route.format(**{key: values.pop(key) for key in path_fields})
        params = {key: values.pop(key) for key in query_fields if key in values}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        body = None
        if method in {"POST", "PUT"}:
            if not values and operation.operation == "update_line_item":
                raise ValueError("Provide at least one line item field to update")
            # The official narrative contract requires JSON, including nested envelopes.
            body = {envelope: values} if envelope else values
        headers = {"Authorization": "Token token=" + credential.api_key,
                   "Accept": "application/json",
                   "User-Agent": "NoClick (https://noclick.com)"}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Nusii request did not complete; inspect the account before retrying a write") from None
        if len(response.content) > 5000000:
            raise ValueError("Nusii response exceeded the supported size")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Nusii did not return JSON; inspect the account before retrying a write") from None
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and ("errors" in payload or "error" in payload)):
            detail = json.dumps(payload, ensure_ascii=True)[:2000]
            raise _ProviderError(response.status_code, _redact(detail, credential.api_key))
        if not isinstance(payload, dict):
            raise ValueError("Nusii returned an unexpected response")
        if operation.operation == "send_proposal":
            if not isinstance(payload.get("status"), str):
                raise ValueError("Nusii did not acknowledge the send request")
        elif "data" not in payload or not isinstance(payload["data"], (dict, list)):
            raise ValueError("Nusii returned an unexpected resource envelope")
        return _redact(payload, credential.api_key)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = NusiiProposalsAPIKey.model_validate(credential_data)
        try:
            payload = await cls._request(credential, GetAccountConfig())
            record = payload["data"]
            if not isinstance(record, dict) or not isinstance(record.get("attributes"), dict):
                raise ValueError("Account identity is unavailable")
            name = record["attributes"].get("name") or record["attributes"].get("email")
            if not isinstance(name, str) or not name:
                raise ValueError("Account identity is unavailable")
        except _ProviderError as exc:
            return {"valid": False if exc.status in {401, 403} else None, "message": str(exc)}
        except (ValueError, httpx.HTTPError):
            return {"valid": None, "message": "Nusii account access could not be verified"}
        return {"valid": True, "identity_verified": True, "message": "Connected to " + name}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect your Nusii Proposals API key")
        payload = await self._request(self.config.credentials, self.config.config)
        output = {"status": "success", "operation": self.config.config.operation, **payload}
        data = payload.get("data")
        if isinstance(data, list):
            items = []
            for row in data:
                if not isinstance(row, dict) or not isinstance(row.get("attributes"), dict) or not isinstance(row.get("id"), str):
                    raise ValueError("Nusii returned an unexpected resource row")
                items.append({**row["attributes"], "id": row["id"], "type": row.get("type")})
            # Human labels for connection evidence; preserve the JSON:API envelope too.
            output["items"] = items
        elif self.config.config.operation == "get_account" and isinstance(data, dict):
            attributes = data.get("attributes", {})
            if isinstance(attributes, dict):
                output["name"] = attributes.get("name") or attributes.get("email")
        # Provider status (e.g. sent) is kept separately from the execution envelope.
        if "status" in payload:
            output["provider_status"] = payload["status"]
            output["status"] = "success"
        await self.emit(output)
        return output
