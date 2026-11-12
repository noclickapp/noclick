"""Certifier API 2022-10-26: one request per operation, bearer-token authentication.

Contract: https://certifier.io/openapi.json. Pagination cursors are returned
unchanged; callers explicitly request subsequent pages. Writes are never retried.
"""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from datetime import datetime
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class CertifierTokenCredential(BaseModel):
    model_config = ConfigDict(title="Certifier API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.certifier.io/settings/access-tokens",
            "x-credential-instructions": "Create an access token in Certifier Dashboard settings and paste it here. NoClick sends it as a bearer token to api.certifier.io. Template reads verify access; issuing and sending credentials require the corresponding account permissions."})
    credential_type: Literal["certifier_api_token"] = Field("certifier_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class CreateCredentialConfigRecipient(_Input):
    name: str = Field(..., description="The name of the credential's recipient", min_length=1, max_length=8192)
    email: str | None = Field(None, description="The email of the credential's recipient", min_length=1, max_length=8192)

class CreateCredentialConfig(_Input):
    'Create a credential'
    operation: Literal['create_credential'] = Field('create_credential', json_schema_extra={"ui:hidden": True})
    groupId: str = Field(..., description="The group's (credential template's) ID you want to issue the credential to. Check the Group (Credential Template) object.", min_length=1, max_length=8192)
    recipient: CreateCredentialConfigRecipient = Field(..., description='The recipient of the credential')
    issueDate: str | None = Field(None, description='The issuer-claimed issue date. Omit it or set it to null to resolve it to the UTC date at issuance (YYYY-MM-DD).')
    expiryDate: str | None = Field(None, description="The issuer-claimed expiration date. Omit it or set it to null to derive the credential template's expiration period at issuance; it stays null when no period is configured (YYYY-MM-DD).")
    customAttributes: dict[str, Any] | None = Field(None, description="The key-value object of your custom attributes, where key is your attribute's tag and value is the text value you want to store")

class ListCredentialsConfig(_Input):
    'List credentials'
    operation: Literal['list_credentials'] = Field('list_credentials', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for pagination', min_length=1, max_length=8192)
    limit: int | None = Field(None, description='Number of items to return (default: 20)', ge=1, le=100)

class CreateIssueSendCredentialConfigRecipient(_Input):
    name: str = Field(..., description="The name of the credential's recipient", min_length=1, max_length=8192)
    email: str | None = Field(None, description="The email of the credential's recipient", min_length=1, max_length=8192)

class CreateIssueSendCredentialConfig(_Input):
    'Create, issue, and send a credential'
    operation: Literal['create_issue_send_credential'] = Field('create_issue_send_credential', json_schema_extra={"ui:hidden": True})
    groupId: str = Field(..., description="The group's (credential template's) ID you want to issue the credential to. Read more about groups (credential templates).", min_length=1, max_length=8192)
    recipient: CreateIssueSendCredentialConfigRecipient = Field(..., description='The recipient of the credential')
    issueDate: str | None = Field(None, description='The issuer-claimed issue date. Omit it or set it to null to resolve it to the UTC date at issuance (YYYY-MM-DD).')
    expiryDate: str | None = Field(None, description="The issuer-claimed expiration date. Omit it or set it to null to derive the credential template's expiration period at issuance; it stays null when no period is configured (YYYY-MM-DD).")
    customAttributes: dict[str, Any] | None = Field(None, description="The key-value object of your custom attributes where key is your attribute's tag and value is just your value")

class DeleteCredentialConfig(_Input):
    'Delete a credential'
    operation: Literal['delete_credential'] = Field('delete_credential', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class GetCredentialConfig(_Input):
    'Get a credential'
    operation: Literal['get_credential'] = Field('get_credential', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class UpdateCredentialConfigRecipient(_Input):
    id: str = Field(..., description="The credential recipient's unique identifier", min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., description="The name of the credential's recipient", min_length=1, max_length=8192)
    email: str | None = Field(None, description="The email of the credential's recipient", min_length=1, max_length=8192)

class UpdateCredentialConfig(_Input):
    'Update a credential'
    operation: Literal['update_credential'] = Field('update_credential', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")
    recipient: UpdateCredentialConfigRecipient | None = Field(None, description='The recipient of the credential')
    issueDate: str | None = Field(None, description='The issuer-claimed issue date (YYYY-MM-DD). Set null only on a draft to clear it; issued credentials cannot clear their issue date.')
    expiryDate: str | None = Field(None, description='The issuer-claimed expiration date (YYYY-MM-DD). Set null to clear it; on a draft whose credential template has an expiration period, the date is re-derived at issuance, otherwise the credential never expires. When both dates are set, expiryDate must be after issueDate.')
    customAttributes: dict[str, Any] | None = Field(None, description="The key-value object of your custom attributes, where key is your attribute's tag and value is the text value you want to store")

class GetCredentialDesignsConfig(_Input):
    'Get credential design templates'
    operation: Literal['get_credential_designs'] = Field('get_credential_designs', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class IssueCredentialConfig(_Input):
    'Issue a credential'
    operation: Literal['issue_credential'] = Field('issue_credential', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class SearchCredentialsConfigSort(_Input):
    property: Literal['id', 'createdAt', 'updatedAt', 'issueDate', 'expiryDate'] = Field(..., description='Property to sort by. Available: id, createdAt, updatedAt, issueDate, expiryDate', min_length=1, max_length=8192)
    order: Literal['asc', 'desc'] = Field(..., description='Sort order (asc or desc, default: desc)', min_length=1, max_length=8192)

class SearchCredentialsConfig(_Input):
    'Search credentials'
    operation: Literal['search_credentials'] = Field('search_credentials', json_schema_extra={"ui:hidden": True})
    filter: dict[str, Any] | None = Field(None, description='Filter object with AND, OR, NOT operators and field conditions. Supports filtering by id, publicId, groupId, status, recipientId, recipient.name, recipient.email, issueDate, expiryDate, createdAt, updatedAt')
    sort: SearchCredentialsConfigSort | None = Field(None, description='Sorting options')
    cursor: str | None = Field(None, description='Cursor for pagination', min_length=1, max_length=8192)
    limit: int | None = Field(None, description='Number of items to return (default: 20)', ge=1, le=100)

class SendCredentialConfig(_Input):
    'Send a credential'
    operation: Literal['send_credential'] = Field('send_credential', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")
    deliveryMethod: Literal['email'] = Field(..., description='The way you want to deliver the credential. The only available deliveryMethod for now is email', min_length=1, max_length=8192)

class CreateCredentialInteractionConfig(_Input):
    'Create a credential interaction'
    operation: Literal['create_credential_interaction'] = Field('create_credential_interaction', json_schema_extra={"ui:hidden": True})
    credentialId: str = Field(..., description="The unique credential's identifier, to which this credential interaction belongs", min_length=1, max_length=8192)
    eventType: Literal['credential_viewed', 'credential_shared_to_linkedin', 'credential_added_to_linkedin_profile', 'credential_shared_to_facebook', 'credential_shared_to_twitter', 'credential_shared_to_messenger', 'credential_shared_to_whatsapp', 'credential_shared_to_pinterest', 'credential_shared_to_telegram', 'credential_shared_to_weibo', 'credential_downloaded', 'credential_link_copied', 'credential_verified'] = Field(..., description='Specifies the type of user interaction event related to the credential', min_length=1, max_length=8192)
    triggeredBy: Literal['recipient', 'guest'] = Field(..., description='The actor that triggered this credential interaction. Currently one of two values: recipient or guest', min_length=1, max_length=8192)
    triggeredAt: datetime = Field(..., description='The date and time when this credential interaction happened. Formatted as an ISO 8601 date and time string')

class ListCredentialInteractionsConfig(_Input):
    'List credential interactions'
    operation: Literal['list_credential_interactions'] = Field('list_credential_interactions', json_schema_extra={"ui:hidden": True})
    credentialId: str | None = Field(None, description="The unique credential's identifier", min_length=1, max_length=8192)
    cursor: str | None = Field(None, description='Cursor for pagination', min_length=1, max_length=8192)
    limit: int | None = Field(None, description='Number of items to return (default: 20)', ge=1, le=100)

class GetDesignConfig(_Input):
    'Get a design template'
    operation: Literal['get_design'] = Field('get_design', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the design template', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class ListDesignsConfig(_Input):
    'List design templates'
    operation: Literal['list_designs'] = Field('list_designs', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for pagination', min_length=1, max_length=8192)
    limit: int | None = Field(None, description='Number of items to return (default: 20)', ge=1, le=100)

class CreateGroupConfig(_Input):
    'Create a credential template'
    operation: Literal['create_group'] = Field('create_group', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='The name of the credential template (group) that is used as [group.name] attribute later on', min_length=1, max_length=8192)
    designIds: list[str] = Field(..., description='The ordered list of design template IDs associated with the credential template..', min_length=1)
    learningEventUrl: str | None = Field(None, description="The learning event's URL that is shown in the digital wallet", min_length=1, max_length=8192)

class ListGroupsConfig(_Input):
    'List credential templates'
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for pagination', min_length=1, max_length=8192)
    limit: int | None = Field(None, description='Number of items to return (default: 20)', ge=1, le=100)

class DeleteGroupConfig(_Input):
    'Delete a credential template'
    operation: Literal['delete_group'] = Field('delete_group', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential template (group).', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class GetGroupConfig(_Input):
    'Get a credential template'
    operation: Literal['get_group'] = Field('get_group', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential template (group).', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")

class UpdateGroupConfig(_Input):
    'Update a credential template'
    operation: Literal['update_group'] = Field('update_group', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The unique ID of the credential template (group).', min_length=1, max_length=8192, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(None, description='The name of the credential template (group) that is used as [group.name] attribute later on', min_length=1, max_length=8192)
    designIds: list[str] | None = Field(None, description='Replaces the ordered list of design template IDs associated with the credential template.', min_length=1)
    learningEventUrl: str | None = Field(None, description="The learning event's URL that is shown in the digital wallet", min_length=1, max_length=8192)

# Certifier's own MCP server: agents get its tools through a person's Certifier sign-in.
CertifierMcpCredential = mcp_credential("certifier", "https://api.certifier.io/v1/mcp", app="Certifier")
CertifierCredential = Union[CertifierTokenCredential, CertifierMcpCredential]


CertifierOperation = Annotated[Union[CreateCredentialConfig, ListCredentialsConfig, CreateIssueSendCredentialConfig, DeleteCredentialConfig, GetCredentialConfig, UpdateCredentialConfig, GetCredentialDesignsConfig, IssueCredentialConfig, SearchCredentialsConfig, SendCredentialConfig, CreateCredentialInteractionConfig, ListCredentialInteractionsConfig, GetDesignConfig, ListDesignsConfig, CreateGroupConfig, ListGroupsConfig, DeleteGroupConfig, GetGroupConfig, UpdateGroupConfig], Field(discriminator="operation")]

class CertifierConfig(NodeConfig[CertifierOperation, CertifierCredential]):
    pass

ROUTES = {'create_credential': ('POST', '/v1/credentials', ('groupId', 'recipient', 'issueDate', 'expiryDate', 'customAttributes'), True), 'list_credentials': ('GET', '/v1/credentials', ('cursor', 'limit'), False), 'create_issue_send_credential': ('POST', '/v1/credentials/create-issue-send', ('groupId', 'recipient', 'issueDate', 'expiryDate', 'customAttributes'), True), 'delete_credential': ('DELETE', '/v1/credentials/{id}', (), False), 'get_credential': ('GET', '/v1/credentials/{id}', (), False), 'update_credential': ('PATCH', '/v1/credentials/{id}', ('recipient', 'issueDate', 'expiryDate', 'customAttributes'), True), 'get_credential_designs': ('GET', '/v1/credentials/{id}/designs', (), False), 'issue_credential': ('POST', '/v1/credentials/{id}/issue', (), False), 'search_credentials': ('POST', '/v1/credentials/search', ('filter', 'sort', 'cursor', 'limit'), True), 'send_credential': ('POST', '/v1/credentials/{id}/send', ('deliveryMethod',), True), 'create_credential_interaction': ('POST', '/v1/credential-interactions', ('credentialId', 'eventType', 'triggeredBy', 'triggeredAt'), True), 'list_credential_interactions': ('GET', '/v1/credential-interactions', ('credentialId', 'cursor', 'limit'), False), 'get_design': ('GET', '/v1/designs/{id}', (), False), 'list_designs': ('GET', '/v1/designs', ('cursor', 'limit'), False), 'create_group': ('POST', '/v1/groups', ('name', 'designIds', 'learningEventUrl'), True), 'list_groups': ('GET', '/v1/groups', ('cursor', 'limit'), False), 'delete_group': ('DELETE', '/v1/groups/{id}', (), False), 'get_group': ('GET', '/v1/groups/{id}', (), False), 'update_group': ('PATCH', '/v1/groups/{id}', ('name', 'designIds', 'learningEventUrl'), True)}


class CertifierNode(WorkflowNode):
    integration_type = "automation-certifier"
    credential_provider_labels = {"certifier": "Certifier Account"}
    connection_evidence = ConnectionEvidence(noun="credential templates", operation="list_groups")

    @classmethod
    def get_config_model(cls):
        return CertifierConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Certifier API token")
        config = self.config.config
        method, path, fields, has_body = ROUTES[config.operation]
        if "{id}" in path:
            path = path.replace("{id}", quote(config.id, safe=""))
        values = config.model_dump(mode="json", exclude_unset=True, exclude={"operation", "id"})
        kwargs = {"json": values} if has_body else {"params": values}
        token = self.config.credentials.api_token
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.certifier.io" + path,
                    headers={"Authorization": "Bearer " + token, "Certifier-Version": "2022-10-26", "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Certifier request could not be confirmed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = "Certifier rejected the request"
            raise ValueError(f"Certifier HTTP {response.status_code}: {str(message).replace(token, '[redacted]')}")
        if response.status_code == 204:
            output = {"deleted": True, "id": config.id}
        else:
            try:
                output = response.json()
            except ValueError:
                raise ValueError("Certifier returned an invalid JSON response") from None
            if config.operation == "get_credential_designs" and isinstance(output, list):
                output = {"data": output}
            if not isinstance(output, dict) or "error" in output:
                raise ValueError("Certifier returned an unexpected response")
        await self.emit(output)
        return output
